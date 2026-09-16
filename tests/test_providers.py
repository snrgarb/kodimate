from datetime import datetime, timezone

from kodimate import db, providers


def _conn(tmp_path):
    return db.open_db(str(tmp_path / "kodimate.db"))


def test_create_m3u_provider_assigns_incrementing_sort_order(tmp_path):
    conn = _conn(tmp_path)
    try:
        id1 = providers.create_m3u_provider(conn, "One", "http://example.com/one.m3u")
        id2 = providers.create_m3u_provider(conn, "Two", "http://example.com/two.m3u")
        rows = providers.list_providers(conn)
        assert [r['id'] for r in rows] == [id1, id2]
        assert rows[0]['sort_order'] < rows[1]['sort_order']
    finally:
        conn.close()


def test_create_m3u_provider_defaults_enabled_true(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = providers.create_m3u_provider(conn, "One", "http://example.com/one.m3u")
        row = providers.get_provider(conn, pid)
        assert row['enabled'] == 1
        assert row['kind'] == 'm3u'
    finally:
        conn.close()


def test_list_providers_excludes_deleted(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = providers.create_m3u_provider(conn, "One", "http://example.com/one.m3u")
        conn.execute("UPDATE provider SET deleted_at = '2026-01-01T00:00:00Z' WHERE id = ?", (pid,))
        assert providers.list_providers(conn) == []
    finally:
        conn.close()


def test_count_enabled(tmp_path):
    conn = _conn(tmp_path)
    try:
        providers.create_m3u_provider(conn, "One", "http://example.com/one.m3u", enabled=True)
        providers.create_m3u_provider(conn, "Two", "http://example.com/two.m3u", enabled=False)
        assert providers.count_enabled(conn) == 1
    finally:
        conn.close()


def test_update_provider_needs_refresh_when_url_changes(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = providers.create_m3u_provider(conn, "One", "http://example.com/one.m3u")
        before = providers.get_provider(conn, pid)
        needs_refresh = providers.update_provider(
            conn, pid, "One", "http://example.com/changed.m3u", True
        )
        after = providers.get_provider(conn, pid)
        assert needs_refresh is True
        assert after['config_version'] == before['config_version'] + 1
        assert after['m3u_url'] == "http://example.com/changed.m3u"
    finally:
        conn.close()


def test_update_provider_needs_refresh_when_disabled_to_enabled(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = providers.create_m3u_provider(conn, "One", "http://example.com/one.m3u", enabled=False)
        before = providers.get_provider(conn, pid)
        needs_refresh = providers.update_provider(conn, pid, "One", "http://example.com/one.m3u", True)
        after = providers.get_provider(conn, pid)
        assert needs_refresh is True
        # config_version unchanged: URL did not change
        assert after['config_version'] == before['config_version']
    finally:
        conn.close()


def test_update_provider_no_refresh_for_name_only_change(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = providers.create_m3u_provider(conn, "One", "http://example.com/one.m3u")
        needs_refresh = providers.update_provider(conn, pid, "Renamed", "http://example.com/one.m3u", True)
        after = providers.get_provider(conn, pid)
        assert needs_refresh is False
        assert after['name'] == "Renamed"
    finally:
        conn.close()


def test_list_providers_listable_count_excludes_stale_and_hidden(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = providers.create_m3u_provider(conn, "One", "http://example.com/one.m3u")
        conn.execute(
            "INSERT INTO channel (provider_id, channel_key, name, normalised_name, stream_url, position) "
            "VALUES (?, 'a', 'A', 'a', 'http://x/a', 0)", (pid,)
        )
        conn.execute(
            "INSERT INTO channel (provider_id, channel_key, name, normalised_name, stream_url, position, stale_since) "
            "VALUES (?, 'b', 'B', 'b', 'http://x/b', 1, '2026-01-01T00:00:00Z')", (pid,)
        )
        conn.execute(
            "INSERT INTO channel (provider_id, channel_key, name, normalised_name, stream_url, position) "
            "VALUES (?, 'c', 'C', 'c', 'http://x/c', 2)", (pid,)
        )
        conn.execute(
            "INSERT INTO channel_override (provider_id, channel_key, hidden) VALUES (?, 'c', 1)", (pid,)
        )
        rows = providers.list_providers(conn)
        assert rows[0]['listable_count'] == 1
    finally:
        conn.close()


def test_validate_m3u_requires_playlist():
    errors = providers.validate_m3u("Name", "")
    assert any(field == 'm3u_url' for field, _ in errors)


def test_validate_m3u_accepts_http_url():
    assert providers.validate_m3u("Name", "http://example.com/x.m3u") == []


def test_validate_m3u_accepts_existing_file(tmp_path):
    f = tmp_path / "list.m3u"
    f.write_text("#EXTM3U\n")
    assert providers.validate_m3u("Name", str(f)) == []


def test_validate_m3u_rejects_nonexistent_path():
    errors = providers.validate_m3u("Name", "/no/such/file.m3u")
    assert any(field == 'm3u_url' for field, _ in errors)


def test_validate_m3u_allows_blank_name():
    assert providers.validate_m3u("", "http://example.com/x.m3u") == []


def test_auto_name_from_path_segment():
    assert providers.auto_name("http://example.com/lists/uk.m3u") == "uk"


def test_auto_name_falls_back_to_host():
    assert providers.auto_name("http://example.com/") == "example.com"


def test_auto_name_local_file():
    assert providers.auto_name("/tmp/my-playlist.m3u8") == "my-playlist"


def test_relative_time_just_now():
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert providers.relative_time("2026-01-01T11:59:40Z", now) == ('just_now', 0)


def test_relative_time_minutes_ago():
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert providers.relative_time("2026-01-01T11:55:00Z", now) == ('minutes_ago', 5)


def test_relative_time_hours_ago():
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert providers.relative_time("2026-01-01T09:00:00Z", now) == ('hours_ago', 3)


def test_relative_time_days_ago():
    now = datetime(2026, 1, 3, 12, 0, 0, tzinfo=timezone.utc)
    assert providers.relative_time("2026-01-01T12:00:00Z", now) == ('days_ago', 2)


def test_relative_time_tolerates_fractional_seconds_no_z():
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert providers.relative_time("2026-01-01T11:55:00.000000", now) == ('minutes_ago', 5)


def test_relative_time_none_when_missing():
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert providers.relative_time(None, now) is None


def test_relative_time_none_when_blank():
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert providers.relative_time("", now) is None


def test_error_snippet_truncates():
    assert providers.error_snippet("x" * 60, max_len=10) == "x" * 10 + "…"


def test_error_snippet_short_passthrough():
    assert providers.error_snippet("boom") == "boom"


def test_error_snippet_none():
    assert providers.error_snippet(None) is None


# -- Xtream provider CRUD -----------------------------------------------

def test_create_xtream_provider_stores_kind_and_fields(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = providers.create_xtream_provider(
            conn, "My XC", "http://xc.example:80", "user", "pass"
        )
        row = providers.get_provider(conn, pid)
        assert row['kind'] == 'xtream'
        assert row['xtream_host'] == 'http://xc.example:80'
        assert row['xtream_username'] == 'user'
        assert row['xtream_password'] == 'pass'
        assert row['enabled'] == 1
    finally:
        conn.close()


def test_create_xtream_provider_strips_path_from_host(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = providers.create_xtream_provider(
            conn, "My XC", "http://xc.example/get.php?x=1", "user", "pass"
        )
        row = providers.get_provider(conn, pid)
        assert row['xtream_host'] == 'http://xc.example'
    finally:
        conn.close()


def test_update_xtream_provider_bumps_config_version_and_clears_learned_format(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = providers.create_xtream_provider(conn, "One", "http://xc.example", "user", "pass")
        conn.execute(
            "UPDATE provider SET learned_stream_format = 'm3u8' WHERE id = ?", (pid,)
        )
        before = providers.get_provider(conn, pid)
        needs_refresh = providers.update_xtream_provider(
            conn, pid, "One", "http://xc.example", "user", "newpass", True
        )
        after = providers.get_provider(conn, pid)
        assert needs_refresh is True
        assert after['config_version'] == before['config_version'] + 1
        learned = conn.execute(
            "SELECT learned_stream_format FROM provider WHERE id = ?", (pid,)
        ).fetchone()[0]
        assert learned is None
    finally:
        conn.close()


def test_update_xtream_provider_no_refresh_for_name_only_change(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = providers.create_xtream_provider(conn, "One", "http://xc.example", "user", "pass")
        needs_refresh = providers.update_xtream_provider(
            conn, pid, "Renamed", "http://xc.example", "user", "pass", True
        )
        after = providers.get_provider(conn, pid)
        assert needs_refresh is False
        assert after['name'] == "Renamed"
    finally:
        conn.close()


def test_update_xtream_provider_needs_refresh_when_disabled_to_enabled(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = providers.create_xtream_provider(
            conn, "One", "http://xc.example", "user", "pass", enabled=False
        )
        needs_refresh = providers.update_xtream_provider(
            conn, pid, "One", "http://xc.example", "user", "pass", True
        )
        assert needs_refresh is True
    finally:
        conn.close()


def test_set_enabled_true_from_false_needs_refresh(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = providers.create_m3u_provider(conn, "One", "http://x/one.m3u", enabled=False)
        needs_refresh = providers.set_enabled(conn, pid, True)
        assert needs_refresh is True
        assert providers.get_provider(conn, pid)['enabled'] == 1
    finally:
        conn.close()


def test_set_enabled_false_no_refresh(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = providers.create_m3u_provider(conn, "One", "http://x/one.m3u", enabled=True)
        needs_refresh = providers.set_enabled(conn, pid, False)
        assert needs_refresh is False
        assert providers.get_provider(conn, pid)['enabled'] == 0
    finally:
        conn.close()


# -- normalise_xtream_host -------------------------------------------------

def test_normalise_xtream_host_strips_path_query_fragment_and_slash():
    assert providers.normalise_xtream_host(
        "http://xc.example:8080/get.php?x=1#frag"
    ) == "http://xc.example:8080"
    assert providers.normalise_xtream_host("http://xc.example/") == "http://xc.example"


# -- validate_xtream ---------------------------------------------------

def test_validate_xtream_requires_host_username_password():
    errors = providers.validate_xtream("Name", "", "", "")
    fields = {field for field, _ in errors}
    assert fields == {'xtream_host', 'xtream_username', 'xtream_password'}


def test_validate_xtream_accepts_valid_host():
    assert providers.validate_xtream("Name", "http://xc.example:80", "user", "pass") == []


def test_validate_xtream_rejects_non_url_host():
    errors = providers.validate_xtream("Name", "not-a-url", "user", "pass")
    assert any(field == 'xtream_host' for field, _ in errors)


# -- split_get_php_url ---------------------------------------------------

def test_split_get_php_url_parses_username_password():
    result = providers.split_get_php_url(
        "http://xc.example:80/get.php?username=bob&password=secret&type=m3u_plus"
    )
    assert result == ("http://xc.example:80", "bob", "secret")


def test_split_get_php_url_returns_none_for_non_matching_text():
    assert providers.split_get_php_url("http://xc.example/live/bob/secret/1.ts") is None
    assert providers.split_get_php_url("just some text") is None


# -- auto_name for Xtream -------------------------------------------------

def test_auto_name_xtream_uses_host_netloc():
    assert providers.auto_name_xtream("http://xc.example:80") == "xc.example:80"


# -- expiry_state ---------------------------------------------------------

def test_expiry_state_none_when_absent():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert providers.expiry_state(None, now) is None


def test_expiry_state_warning_under_seven_days():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    state, _ = providers.expiry_state("2026-01-05T00:00:00Z", now)
    assert state == 'warning'


def test_expiry_state_ok_when_far_off():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    state, _ = providers.expiry_state("2026-06-01T00:00:00Z", now)
    assert state == 'ok'


def test_expiry_state_expired_when_in_past():
    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    state, _ = providers.expiry_state("2026-01-01T00:00:00Z", now)
    assert state == 'expired'


# -- new provider fields: round-trip and validation ------------------------

def test_create_m3u_provider_round_trips_new_fields(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = providers.create_m3u_provider(
            conn, "One", "http://example.com/one.m3u",
            epg_override_url="http://example.com/epg.xml",
            catchup_days_default=3, user_agent="MyAgent/1.0",
            catchup_correction_hours=-2, number_offset=100,
        )
        row = providers.get_provider(conn, pid)
        assert row['epg_override_url'] == "http://example.com/epg.xml"
        assert row['catchup_days_default'] == 3
        assert row['user_agent'] == "MyAgent/1.0"
        assert row['catchup_correction_hours'] == -2
        assert row['number_offset'] == 100
        listed = providers.list_providers(conn)[0]
        assert listed['epg_override_url'] == "http://example.com/epg.xml"
    finally:
        conn.close()


def test_create_m3u_provider_stores_empty_optional_text_as_none(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = providers.create_m3u_provider(
            conn, "One", "http://example.com/one.m3u",
            epg_override_url="", user_agent="",
        )
        row = providers.get_provider(conn, pid)
        assert row['epg_override_url'] is None
        assert row['user_agent'] is None
    finally:
        conn.close()


def test_create_xtream_provider_round_trips_new_fields(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = providers.create_xtream_provider(
            conn, "One", "http://xc.example", "user", "pass",
            stream_format="ts", catchup_url_form="query",
        )
        row = providers.get_provider(conn, pid)
        assert row['stream_format'] == 'ts'
        assert row['catchup_url_form'] == 'query'
    finally:
        conn.close()


def test_update_provider_epg_override_bumps_config_version(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = providers.create_m3u_provider(conn, "One", "http://example.com/one.m3u")
        before = providers.get_provider(conn, pid)
        needs_refresh = providers.update_provider(
            conn, pid, "One", "http://example.com/one.m3u", True,
            epg_override_url="http://example.com/epg.xml",
        )
        after = providers.get_provider(conn, pid)
        assert needs_refresh is True
        assert after['config_version'] == before['config_version'] + 1
    finally:
        conn.close()


def test_update_provider_offset_and_correction_do_not_bump_version(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = providers.create_m3u_provider(conn, "One", "http://example.com/one.m3u")
        before = providers.get_provider(conn, pid)
        needs_refresh = providers.update_provider(
            conn, pid, "One", "http://example.com/one.m3u", True,
            number_offset=5, catchup_correction_hours=3, user_agent="A/1.0",
        )
        after = providers.get_provider(conn, pid)
        assert needs_refresh is False
        assert after['config_version'] == before['config_version']
        assert after['number_offset'] == 5
    finally:
        conn.close()


def test_update_xtream_provider_explicit_stream_format_clears_learned(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = providers.create_xtream_provider(conn, "One", "http://xc.example", "user", "pass")
        conn.execute("UPDATE provider SET learned_stream_format = 'ts' WHERE id = ?", (pid,))
        needs_refresh = providers.update_xtream_provider(
            conn, pid, "One", "http://xc.example", "user", "pass", True,
            stream_format='m3u8',
        )
        after = providers.get_provider(conn, pid)
        assert needs_refresh is False
        assert after['learned_stream_format'] is None
        assert after['stream_format'] == 'm3u8'
    finally:
        conn.close()


def test_validate_m3u_rejects_bad_epg_override_url():
    errors = providers.validate_m3u("Name", "http://x/list.m3u", epg_override_url="not-a-url")
    assert any(field == 'epg_override_url' for field, _ in errors)


def test_validate_accepts_valid_epg_override_url():
    assert providers.validate_m3u("Name", "http://x/list.m3u", epg_override_url="http://x/epg.xml") == []


def test_validate_rejects_negative_catchup_days_default():
    errors = providers.validate_m3u("Name", "http://x/list.m3u", catchup_days_default=-1)
    assert any(field == 'catchup_days_default' for field, _ in errors)


def test_validate_rejects_negative_number_offset():
    errors = providers.validate_m3u("Name", "http://x/list.m3u", number_offset=-1)
    assert any(field == 'number_offset' for field, _ in errors)


def test_validate_rejects_out_of_range_catchup_correction():
    errors = providers.validate_xtream(
        "Name", "http://xc.example", "user", "pass", catchup_correction_hours=13
    )
    assert any(field == 'catchup_correction_hours' for field, _ in errors)


def test_validate_reports_correction_before_number_offset_when_both_invalid():
    # Row order (both kinds) shows Catch-up correction before Number offset,
    # so "first invalid row" must report correction first.
    errors = providers.validate_xtream(
        "Name", "http://xc.example", "user", "pass",
        number_offset=-1, catchup_correction_hours=13,
    )
    assert errors[0][0] == 'catchup_correction_hours'


def test_validate_accepts_boundary_catchup_correction():
    assert providers.validate_xtream(
        "Name", "http://xc.example", "user", "pass", catchup_correction_hours=-12
    ) == []
    assert providers.validate_xtream(
        "Name", "http://xc.example", "user", "pass", catchup_correction_hours=12
    ) == []
