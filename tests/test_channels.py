from kodimate import channels, db


def _conn(tmp_path):
    return db.open_db(str(tmp_path / "kodimate.db"))


def _provider(conn, name="P1", enabled=1, deleted_at=None, sort_order=0, number_offset=0):
    cursor = conn.execute(
        "INSERT INTO provider (kind, name, enabled, deleted_at, sort_order, number_offset) "
        "VALUES ('m3u', ?, ?, ?, ?, ?)",
        (name, enabled, deleted_at, sort_order, number_offset),
    )
    return cursor.lastrowid


def _group(conn, provider_id, name="Group A", sort_order=0):
    cursor = conn.execute(
        "INSERT INTO channel_group (provider_id, name, sort_order) VALUES (?, ?, ?)",
        (provider_id, name, sort_order),
    )
    return cursor.lastrowid


def _channel(conn, provider_id, channel_key, name="Chan", group_id=None,
             provider_number=None, position=0, stale_since=None, logo_url=None):
    cursor = conn.execute(
        "INSERT INTO channel (provider_id, channel_key, name, normalised_name, stream_url, "
        "group_id, provider_number, position, stale_since, logo_url) "
        "VALUES (?, ?, ?, ?, 'http://x', ?, ?, ?, ?, ?)",
        (provider_id, channel_key, name, name.lower(), group_id, provider_number, position,
         stale_since, logo_url),
    )
    return cursor.lastrowid


def _override(conn, provider_id, channel_key, number=None, hidden=0, favourite=0,
               favourite_order=None):
    conn.execute(
        "INSERT INTO channel_override (provider_id, channel_key, number, hidden, favourite, "
        "favourite_order) VALUES (?, ?, ?, ?, ?, ?)",
        (provider_id, channel_key, number, hidden, favourite, favourite_order),
    )


def test_numbering_uses_override_number_when_present(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn, number_offset=100)
        _channel(conn, pid, "a", provider_number=5, position=0)
        _override(conn, pid, "a", number=999)
        rows = channels.list_channels(conn)
        assert rows[0]['number'] == 999
    finally:
        conn.close()


def test_numbering_falls_back_to_provider_number_plus_offset(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn, number_offset=100)
        _channel(conn, pid, "a", provider_number=5, position=0)
        rows = channels.list_channels(conn)
        assert rows[0]['number'] == 105
    finally:
        conn.close()


def test_numbering_falls_back_to_position_plus_offset_when_no_provider_number(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn, number_offset=100)
        _channel(conn, pid, "a", provider_number=None, position=3)
        rows = channels.list_channels(conn)
        assert rows[0]['number'] == 103
    finally:
        conn.close()


def test_catchup_days_coalesces_channel_over_provider_default(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        conn.execute("UPDATE provider SET catchup_days_default = 5 WHERE id = ?", (pid,))
        _channel(conn, pid, "a", position=0)
        conn.execute("UPDATE channel SET catchup_days = 2 WHERE provider_id = ? AND channel_key = 'a'", (pid,))
        rows = channels.list_channels(conn)
        assert rows[0]['catchup_days'] == 2
    finally:
        conn.close()


def test_catchup_days_falls_back_to_provider_default(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        conn.execute("UPDATE provider SET catchup_days_default = 5 WHERE id = ?", (pid,))
        _channel(conn, pid, "a", position=0)
        rows = channels.list_channels(conn)
        assert rows[0]['catchup_days'] == 5
    finally:
        conn.close()


def test_catchup_supported_true_for_xtream_provider(tmp_path):
    conn = _conn(tmp_path)
    try:
        cursor = conn.execute(
            "INSERT INTO provider (kind, name, enabled) VALUES ('xtream', 'X1', 1)"
        )
        pid = cursor.lastrowid
        conn.execute(
            "INSERT INTO channel (provider_id, channel_key, name, normalised_name, stream_url, "
            "position) VALUES (?, 'a', 'Chan', 'chan', 'http://x/live/u/p/1.ts', 0)",
            (pid,),
        )
        rows = channels.list_channels(conn)
        assert rows[0]['catchup_supported'] is True
    finally:
        conn.close()


def test_catchup_supported_false_for_m3u_default_mode_non_xc_url(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        conn.execute(
            "INSERT INTO channel (provider_id, channel_key, name, normalised_name, stream_url, "
            "position, catchup_mode) VALUES (?, 'a', 'Chan', 'chan', 'http://cdn.example/a.m3u8', "
            "0, 'default')",
            (pid,),
        )
        rows = channels.list_channels(conn)
        assert rows[0]['catchup_supported'] is False
    finally:
        conn.close()


def test_catchup_supported_true_for_m3u_default_mode_xc_shaped_url(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        conn.execute(
            "INSERT INTO channel (provider_id, channel_key, name, normalised_name, stream_url, "
            "position, catchup_mode) VALUES (?, 'a', 'Chan', 'chan', "
            "'https://xc.example/live/u/p/1.ts', 0, 'default')",
            (pid,),
        )
        rows = channels.list_channels(conn)
        assert rows[0]['catchup_supported'] is True
    finally:
        conn.close()


def test_stale_channel_excluded(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", stale_since="2026-01-01T00:00:00Z")
        assert channels.list_channels(conn) == []
    finally:
        conn.close()


def test_hidden_channel_excluded_by_default_and_flagged_when_shown(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a")
        _override(conn, pid, "a", hidden=1)
        assert channels.list_channels(conn) == []
        rows = channels.list_channels(conn, show_hidden=True)
        assert len(rows) == 1
        assert rows[0]['hidden'] is True
    finally:
        conn.close()


def test_disabled_provider_channel_excluded(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn, enabled=0)
        _channel(conn, pid, "a")
        assert channels.list_channels(conn) == []
    finally:
        conn.close()


def test_deleted_provider_channel_excluded(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn, deleted_at="2026-01-01T00:00:00Z")
        _channel(conn, pid, "a")
        assert channels.list_channels(conn) == []
    finally:
        conn.close()


def test_empty_group_not_listed_in_list_groups(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        gid = _group(conn, pid, name="Empty")
        _channel(conn, pid, "a", group_id=gid, stale_since="2026-01-01T00:00:00Z")
        assert channels.list_groups(conn) == []
    finally:
        conn.close()


def test_non_empty_group_listed(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        gid = _group(conn, pid, name="Sports")
        _channel(conn, pid, "a", group_id=gid)
        rows = channels.list_groups(conn)
        assert rows == [{'id': gid, 'provider_id': pid, 'name': "Sports"}]
    finally:
        conn.close()


def test_ordering_by_provider_then_position(tmp_path):
    conn = _conn(tmp_path)
    try:
        p2 = _provider(conn, name="P2", sort_order=1)
        p1 = _provider(conn, name="P1", sort_order=0)
        _channel(conn, p2, "x", name="X", position=0)
        _channel(conn, p1, "b", name="B", position=1)
        _channel(conn, p1, "a", name="A", position=0)
        rows = channels.list_channels(conn)
        assert [r['name'] for r in rows] == ["A", "B", "X"]
    finally:
        conn.close()


def test_same_channel_key_in_two_providers_yields_two_rows(tmp_path):
    conn = _conn(tmp_path)
    try:
        p1 = _provider(conn, name="P1", sort_order=0)
        p2 = _provider(conn, name="P2", sort_order=1)
        _channel(conn, p1, "same", name="Same1")
        _channel(conn, p2, "same", name="Same2")
        rows = channels.list_channels(conn)
        assert len(rows) == 2
        assert {r['provider_id'] for r in rows} == {p1, p2}
    finally:
        conn.close()


def test_favourites_filter_and_order(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", name="A", position=0)
        _channel(conn, pid, "b", name="B", position=1)
        _channel(conn, pid, "c", name="C", position=2)
        _override(conn, pid, "a", favourite=1, favourite_order=2)
        _override(conn, pid, "b", favourite=1, favourite_order=1)
        rows = channels.list_channels(conn, favourites=True)
        assert [r['name'] for r in rows] == ["B", "A"]
    finally:
        conn.close()


def test_list_groups_orders_by_provider_sort_order_then_group_sort_order(tmp_path):
    conn = _conn(tmp_path)
    try:
        pa = _provider(conn, name="A", sort_order=1)
        pb = _provider(conn, name="B", sort_order=0)
        ga2 = _group(conn, pa, name="A2", sort_order=1)
        ga1 = _group(conn, pa, name="A1", sort_order=0)
        gb = _group(conn, pb, name="B1", sort_order=0)
        _channel(conn, pa, "a2", group_id=ga2)
        _channel(conn, pa, "a1", group_id=ga1)
        _channel(conn, pb, "b1", group_id=gb)
        rows = channels.list_groups(conn)
        assert [r['name'] for r in rows] == ["B1", "A1", "A2"]
    finally:
        conn.close()


def test_group_id_filter(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        g1 = _group(conn, pid, name="G1")
        g2 = _group(conn, pid, name="G2")
        _channel(conn, pid, "a", name="A", group_id=g1)
        _channel(conn, pid, "b", name="B", group_id=g2)
        rows = channels.list_channels(conn, group_id=g1)
        assert [r['name'] for r in rows] == ["A"]
    finally:
        conn.close()


def test_set_number_upserts_and_reflects_in_list_channels(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", provider_number=5, position=0)
        channels.set_number(conn, pid, "a", 42)
        rows = channels.list_channels(conn)
        assert rows[0]['number'] == 42
        channels.set_number(conn, pid, "a", 7)
        rows = channels.list_channels(conn)
        assert rows[0]['number'] == 7
    finally:
        conn.close()


def test_set_hidden_upserts_and_reflects_in_list_channels(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", position=0)
        channels.set_hidden(conn, pid, "a", True)
        assert channels.list_channels(conn) == []
        channels.set_hidden(conn, pid, "a", False)
        assert len(channels.list_channels(conn)) == 1
    finally:
        conn.close()


def test_set_favourite_appends_at_end_of_order(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", name="A", position=0)
        _channel(conn, pid, "b", name="B", position=1)
        _override(conn, pid, "a", favourite=1, favourite_order=0)
        channels.set_favourite(conn, pid, "b", True)
        rows = channels.list_channels(conn, favourites=True)
        assert [r['name'] for r in rows] == ["A", "B"]
    finally:
        conn.close()


def test_set_favourite_false_removes_from_favourites(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", position=0)
        _override(conn, pid, "a", favourite=1, favourite_order=0)
        channels.set_favourite(conn, pid, "a", False)
        assert channels.list_channels(conn, favourites=True) == []
    finally:
        conn.close()


def test_set_favourite_order_renumbers(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", name="A", position=0)
        _channel(conn, pid, "b", name="B", position=1)
        _override(conn, pid, "a", favourite=1, favourite_order=0)
        _override(conn, pid, "b", favourite=1, favourite_order=1)
        channels.set_favourite_order(conn, [(pid, "b"), (pid, "a")])
        rows = channels.list_channels(conn, favourites=True)
        assert [r['name'] for r in rows] == ["B", "A"]
    finally:
        conn.close()


def test_reset_deletes_override_row(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", provider_number=5, position=0)
        _override(conn, pid, "a", number=999, hidden=1, favourite=1, favourite_order=0)
        channels.reset(conn, pid, "a")
        row = conn.execute(
            "SELECT * FROM channel_override WHERE provider_id = ? AND channel_key = 'a'", (pid,)
        ).fetchone()
        assert row is None
        rows = channels.list_channels(conn)
        assert rows[0]['number'] == 5
        assert rows[0]['hidden'] is False
    finally:
        conn.close()


def _epg_source(conn, provider_id, url="http://epg"):
    cursor = conn.execute(
        "INSERT INTO epg_source (provider_id, url) VALUES (?, ?)", (provider_id, url)
    )
    return cursor.lastrowid


def _programme(conn, epg_source_id, xmltv_channel_id, start, end, title, description=None):
    conn.execute(
        "INSERT INTO programme (epg_source_id, xmltv_channel_id, start, end, title, description) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (epg_source_id, xmltv_channel_id, start, end, title, description),
    )


def test_list_programmes_returns_rows_overlapping_window(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        cid = _channel(conn, pid, "a")
        conn.execute("UPDATE channel SET epg_channel_id = 'x1' WHERE id = ?", (cid,))
        eid = _epg_source(conn, pid)
        _programme(conn, eid, "x1", "2026-01-01T12:00:00Z", "2026-01-01T13:00:00Z", "Show A",
                   description="About show A")
        _programme(conn, eid, "x1", "2026-01-01T09:00:00Z", "2026-01-01T10:00:00Z", "Before window")
        result = channels.list_programmes(
            conn, [cid], "2026-01-01T11:00:00Z", "2026-01-01T14:00:00Z"
        )
        assert [p['title'] for p in result[cid]] == ["Show A"]
        assert result[cid][0]['description'] == "About show A"
    finally:
        conn.close()


def test_list_programmes_description_empty_string_when_null(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        cid = _channel(conn, pid, "a")
        conn.execute("UPDATE channel SET epg_channel_id = 'x1' WHERE id = ?", (cid,))
        eid = _epg_source(conn, pid)
        _programme(conn, eid, "x1", "2026-01-01T12:00:00Z", "2026-01-01T13:00:00Z", "Show A")
        result = channels.list_programmes(
            conn, [cid], "2026-01-01T11:00:00Z", "2026-01-01T14:00:00Z"
        )
        assert result[cid][0]['description'] == ""
    finally:
        conn.close()


def test_list_programmes_includes_catchup_id(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        cid = _channel(conn, pid, "a")
        conn.execute("UPDATE channel SET epg_channel_id = 'x1' WHERE id = ?", (cid,))
        eid = _epg_source(conn, pid)
        conn.execute(
            "INSERT INTO programme (epg_source_id, xmltv_channel_id, start, end, title, catchup_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (eid, "x1", "2026-01-01T12:00:00Z", "2026-01-01T13:00:00Z", "Show A", "cid-1"),
        )
        result = channels.list_programmes(
            conn, [cid], "2026-01-01T11:00:00Z", "2026-01-01T14:00:00Z"
        )
        assert result[cid][0]['catchup_id'] == "cid-1"
    finally:
        conn.close()


def test_list_programmes_empty_for_channel_without_epg_match(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        cid = _channel(conn, pid, "a")
        result = channels.list_programmes(
            conn, [cid], "2026-01-01T11:00:00Z", "2026-01-01T14:00:00Z"
        )
        assert result[cid] == []
    finally:
        conn.close()


def test_now_titles_returns_title_for_channel_airing_now(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        cid = _channel(conn, pid, "a")
        conn.execute("UPDATE channel SET epg_channel_id = 'x1' WHERE id = ?", (cid,))
        eid = _epg_source(conn, pid)
        _programme(conn, eid, "x1", "2026-01-01T11:00:00Z", "2026-01-01T12:00:00Z", "Now Show")
        result = channels.now_titles(conn, [cid], "2026-01-01T11:30:00Z")
        assert result[cid] == "Now Show"
    finally:
        conn.close()


def test_now_titles_prefers_later_starting_overlap(tmp_path):
    # Umbrella 09:30-16:00 overlapping a replay 11:00-11:30; the
    # later-starting replay should win for a channel airing at 11:15.
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        cid = _channel(conn, pid, "a")
        conn.execute("UPDATE channel SET epg_channel_id = 'x1' WHERE id = ?", (cid,))
        eid = _epg_source(conn, pid)
        _programme(conn, eid, "x1", "2026-01-01T09:30:00Z", "2026-01-01T16:00:00Z", "Live: Race Day")
        _programme(conn, eid, "x1", "2026-01-01T11:00:00Z", "2026-01-01T11:30:00Z", "Racing Replay: 1")
        result = channels.now_titles(conn, [cid], "2026-01-01T11:15:00Z")
        assert result[cid] == "Racing Replay: 1"
    finally:
        conn.close()


def test_now_titles_omits_channel_without_current_programme(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        cid = _channel(conn, pid, "a")
        result = channels.now_titles(conn, [cid], "2026-01-01T11:30:00Z")
        assert cid not in result
    finally:
        conn.close()
