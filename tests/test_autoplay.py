# -*- coding: utf-8 -*-
from kodimate import autoplay, db


def _conn(tmp_path):
    return db.open_db(str(tmp_path / "kodimate.db"))


def _provider(conn, name="P1", enabled=1, deleted_at=None, sort_order=0):
    cursor = conn.execute(
        "INSERT INTO provider (kind, name, enabled, deleted_at, sort_order) "
        "VALUES ('m3u', ?, ?, ?, ?)",
        (name, enabled, deleted_at, sort_order),
    )
    return cursor.lastrowid


def _channel(conn, provider_id, channel_key, name="Chan", position=0, stale_since=None):
    conn.execute(
        "INSERT INTO channel (provider_id, channel_key, name, normalised_name, stream_url, "
        "position, stale_since) VALUES (?, ?, ?, ?, 'http://x', ?, ?)",
        (provider_id, channel_key, name, name.lower(), position, stale_since),
    )


def _override(conn, provider_id, channel_key, hidden=0):
    conn.execute(
        "INSERT INTO channel_override (provider_id, channel_key, hidden) VALUES (?, ?, ?)",
        (provider_id, channel_key, hidden),
    )


def test_resolve_returns_remembered_listable_channel(tmp_path):
    conn = _conn(tmp_path)
    pid = _provider(conn)
    _channel(conn, pid, "a", position=0)
    _channel(conn, pid, "b", position=1)
    autoplay.remember_last_channel(conn, pid, "b")

    assert autoplay.resolve_autoplay_channel(conn) == (pid, "b")


def test_resolve_falls_back_when_remembered_channel_is_stale(tmp_path):
    conn = _conn(tmp_path)
    pid = _provider(conn)
    _channel(conn, pid, "a", position=0)
    _channel(conn, pid, "b", position=1, stale_since="2024-01-01T00:00:00Z")
    autoplay.remember_last_channel(conn, pid, "b")

    assert autoplay.resolve_autoplay_channel(conn) == (pid, "a")


def test_resolve_falls_back_when_remembered_channel_is_hidden(tmp_path):
    conn = _conn(tmp_path)
    pid = _provider(conn)
    _channel(conn, pid, "a", position=0)
    _channel(conn, pid, "b", position=1)
    _override(conn, pid, "b", hidden=1)
    autoplay.remember_last_channel(conn, pid, "b")

    assert autoplay.resolve_autoplay_channel(conn) == (pid, "a")


def test_resolve_falls_back_when_remembered_provider_disabled(tmp_path):
    conn = _conn(tmp_path)
    pid = _provider(conn)
    _channel(conn, pid, "a", position=0)
    pid2 = _provider(conn, name="P2", enabled=0)
    _channel(conn, pid2, "b", position=0)
    autoplay.remember_last_channel(conn, pid2, "b")

    assert autoplay.resolve_autoplay_channel(conn) == (pid, "a")


def test_resolve_falls_back_when_remembered_provider_deleted(tmp_path):
    conn = _conn(tmp_path)
    pid = _provider(conn)
    _channel(conn, pid, "a", position=0)
    pid2 = _provider(conn, name="P2", deleted_at="2024-01-01T00:00:00Z")
    _channel(conn, pid2, "b", position=0)
    autoplay.remember_last_channel(conn, pid2, "b")

    assert autoplay.resolve_autoplay_channel(conn) == (pid, "a")


def test_resolve_uses_first_listable_when_nothing_remembered(tmp_path):
    conn = _conn(tmp_path)
    pid = _provider(conn)
    _channel(conn, pid, "a", position=0)
    _channel(conn, pid, "b", position=1)

    assert autoplay.resolve_autoplay_channel(conn) == (pid, "a")


def test_resolve_returns_none_when_no_listable_channels(tmp_path):
    conn = _conn(tmp_path)
    pid = _provider(conn)
    _channel(conn, pid, "a", position=0, stale_since="2024-01-01T00:00:00Z")

    assert autoplay.resolve_autoplay_channel(conn) is None


def test_startup_snapshot_matches_resolved_channel(tmp_path):
    conn = _conn(tmp_path)
    pid = _provider(conn)
    _channel(conn, pid, "a", position=0)

    snapshot = autoplay.startup_snapshot(conn)

    assert snapshot['channel_key'] == 'a'
    assert snapshot['provider_id'] == pid


def test_startup_snapshot_none_when_nothing_listable(tmp_path):
    conn = _conn(tmp_path)
    pid = _provider(conn)
    _channel(conn, pid, "a", position=0, stale_since="2024-01-01T00:00:00Z")

    assert autoplay.startup_snapshot(conn) is None


def test_last_channel_id_returns_remembered_channel_row_id(tmp_path):
    conn = _conn(tmp_path)
    pid = _provider(conn)
    _channel(conn, pid, "a", position=0)
    _channel(conn, pid, "b", position=1)
    autoplay.remember_last_channel(conn, pid, "b")

    row_id = conn.execute(
        "SELECT id FROM channel WHERE provider_id = ? AND channel_key = 'b'", (pid,)
    ).fetchone()[0]
    assert autoplay.last_channel_id(conn) == row_id


def test_last_channel_id_falls_back_to_first_row_when_remembered_not_listable(tmp_path):
    conn = _conn(tmp_path)
    pid = _provider(conn)
    _channel(conn, pid, "a", position=0)
    _channel(conn, pid, "b", position=1, stale_since="2024-01-01T00:00:00Z")
    autoplay.remember_last_channel(conn, pid, "b")

    row_id = conn.execute(
        "SELECT id FROM channel WHERE provider_id = ? AND channel_key = 'a'", (pid,)
    ).fetchone()[0]
    assert autoplay.last_channel_id(conn) == row_id


def test_last_channel_id_none_when_nothing_listable(tmp_path):
    conn = _conn(tmp_path)
    pid = _provider(conn)
    _channel(conn, pid, "a", position=0, stale_since="2024-01-01T00:00:00Z")

    assert autoplay.last_channel_id(conn) is None
