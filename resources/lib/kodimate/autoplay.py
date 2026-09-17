# -*- coding: utf-8 -*-
"""Startup autoplay of the last channel (issue #29)."""
from . import channels, db, playback

_KEY_PROVIDER_ID = 'last_channel_provider_id'
_KEY_CHANNEL_KEY = 'last_channel_key'


def remember_last_channel(conn, provider_id, channel_key):
    """Persist the last-played channel so a future startup can autoplay it."""
    def _do(conn):
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (_KEY_PROVIDER_ID, str(provider_id)),
        )
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (_KEY_CHANNEL_KEY, channel_key),
        )

    return db.execute_with_retry(conn, _do)


def resolve_autoplay_channel(conn):
    """(provider_id, channel_key) to autoplay on startup, or None if there
    is nothing listable. The remembered last channel is used only while it
    is still listable; otherwise falls back to the first listable channel
    (channels.list_channels() order)."""
    row = conn.execute(
        "SELECT value FROM meta WHERE key = ?", (_KEY_PROVIDER_ID,)
    ).fetchone()
    channel_row = conn.execute(
        "SELECT value FROM meta WHERE key = ?", (_KEY_CHANNEL_KEY,)
    ).fetchone()
    if row is not None and channel_row is not None:
        provider_id = int(row[0])
        channel_key = channel_row[0]
        listable = conn.execute(
            "SELECT 1" + channels._BASE_JOIN
            + " AND COALESCE(o.hidden, 0) = 0 AND c.provider_id = ? AND c.channel_key = ?",
            (provider_id, channel_key),
        ).fetchone()
        if listable is not None:
            return provider_id, channel_key

    rows = channels.list_channels(conn)
    if not rows:
        return None
    return rows[0]['provider_id'], rows[0]['channel_key']


def startup_snapshot(conn):
    """Channel snapshot to autoplay on startup, or None to skip autoplay."""
    resolved = resolve_autoplay_channel(conn)
    if resolved is None:
        return None
    provider_id, channel_key = resolved
    return playback.load_snapshot(conn, provider_id, channel_key)
