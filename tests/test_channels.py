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
