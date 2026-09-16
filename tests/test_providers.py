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
