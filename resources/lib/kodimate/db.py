# -*- coding: utf-8 -*-
"""Shared SQLite connection helper: WAL pragmas + idempotent schema migrations.

Both default.py (script) and service.py open the Kodimate database through
open_db() so that whichever process starts first creates the v1 schema
(ADR 0003, docs/design/schema.md).
"""
import os
import sqlite3

SCHEMA_VERSION = 2

_SCHEMA_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS provider (
        id INTEGER PRIMARY KEY,
        kind TEXT NOT NULL,
        name TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        deleted_at TEXT,
        sort_order INTEGER NOT NULL DEFAULT 0,
        m3u_url TEXT,
        xtream_host TEXT,
        xtream_username TEXT,
        xtream_password TEXT,
        user_agent TEXT,
        account_expires_at TEXT,
        max_connections INTEGER,
        allowed_output_formats TEXT,
        epg_override_url TEXT,
        catchup_days_default INTEGER,
        catchup_url_form TEXT NOT NULL DEFAULT 'path',
        catchup_correction_hours INTEGER NOT NULL DEFAULT 0,
        number_offset INTEGER NOT NULL DEFAULT 0,
        stream_format TEXT,
        learned_stream_format TEXT,
        last_refresh_at TEXT,
        last_error TEXT,
        config_version INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS epg_source (
        id INTEGER PRIMARY KEY,
        provider_id INTEGER NOT NULL UNIQUE REFERENCES provider(id),
        url TEXT,
        last_fetched_at TEXT,
        etag TEXT,
        last_modified TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS programme_staging (
        epg_source_id INTEGER NOT NULL,
        xmltv_channel_id TEXT NOT NULL,
        start TEXT NOT NULL,
        end TEXT NOT NULL,
        title TEXT,
        subtitle TEXT,
        description TEXT,
        icon_url TEXT,
        category TEXT,
        catchup_id TEXT,
        PRIMARY KEY (epg_source_id, xmltv_channel_id, start)
    )""",
    """CREATE TABLE IF NOT EXISTS channel_group (
        id INTEGER PRIMARY KEY,
        provider_id INTEGER NOT NULL REFERENCES provider(id),
        name TEXT NOT NULL,
        sort_order INTEGER NOT NULL DEFAULT 0,
        UNIQUE (provider_id, name)
    )""",
    """CREATE TABLE IF NOT EXISTS channel (
        id INTEGER PRIMARY KEY,
        provider_id INTEGER NOT NULL REFERENCES provider(id),
        channel_key TEXT NOT NULL,
        name TEXT NOT NULL,
        normalised_name TEXT NOT NULL,
        stream_url TEXT NOT NULL,
        logo_url TEXT,
        group_id INTEGER REFERENCES channel_group(id),
        provider_number INTEGER,
        position INTEGER NOT NULL DEFAULT 0,
        epg_channel_id TEXT,
        catchup_days INTEGER,
        catchup_mode TEXT,
        catchup_source TEXT,
        catchup_correction_hours INTEGER,
        headers_json TEXT,
        stale_since TEXT,
        last_seen_at TEXT,
        UNIQUE (provider_id, channel_key)
    )""",
    """CREATE TABLE IF NOT EXISTS channel_override (
        provider_id INTEGER NOT NULL,
        channel_key TEXT NOT NULL,
        number INTEGER,
        hidden INTEGER NOT NULL DEFAULT 0,
        favourite INTEGER NOT NULL DEFAULT 0,
        favourite_order INTEGER,
        PRIMARY KEY (provider_id, channel_key)
    )""",
    """CREATE TABLE IF NOT EXISTS programme (
        epg_source_id INTEGER NOT NULL,
        xmltv_channel_id TEXT NOT NULL,
        start TEXT NOT NULL,
        end TEXT NOT NULL,
        title TEXT,
        subtitle TEXT,
        description TEXT,
        icon_url TEXT,
        category TEXT,
        catchup_id TEXT,
        PRIMARY KEY (epg_source_id, xmltv_channel_id, start)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_programme_channel_end ON programme (xmltv_channel_id, end)",
]


def _connect(path):
    # check_same_thread=False: the script's ProvidersWindow polls IPC
    # properties from a background thread and re-queries via the script's
    # single connection (ADR 0003); writes stay on the main thread.
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _current_schema_version(conn):
    row = conn.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()
    return int(row[0]) if row else 0


def listable_channel_count(conn, provider_id):
    """Count of provider_id's listable channels (see docs/design/schema.md
    "Visibility"): not Stale and not Hidden via channel_override."""
    row = conn.execute(
        """
        SELECT COUNT(*) FROM channel c
        WHERE c.provider_id = ? AND c.stale_since IS NULL
        AND NOT EXISTS (
            SELECT 1 FROM channel_override o
            WHERE o.provider_id = c.provider_id
            AND o.channel_key = c.channel_key
            AND o.hidden = 1
        )
        """,
        (provider_id,),
    ).fetchone()
    return row[0]


def _add_allowed_output_formats_column_if_missing(conn):
    columns = {row[1] for row in conn.execute("PRAGMA table_info(provider)").fetchall()}
    if 'allowed_output_formats' not in columns:
        conn.execute("ALTER TABLE provider ADD COLUMN allowed_output_formats TEXT")


def migrate(conn):
    """Idempotently bring the schema up to SCHEMA_VERSION under BEGIN IMMEDIATE."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        version = _current_schema_version(conn)
        if version < SCHEMA_VERSION:
            for statement in _SCHEMA_STATEMENTS:
                conn.execute(statement)
            if version >= 1:
                _add_allowed_output_formats_column_if_missing(conn)
            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(SCHEMA_VERSION),),
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def open_db(path):
    """Open the Kodimate SQLite DB at path, applying pragmas and migrations.

    Accepts an explicit path so callers (and tests) control location; the
    profile directory is created if missing.
    """
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = _connect(path)
    migrate(conn)
    return conn
