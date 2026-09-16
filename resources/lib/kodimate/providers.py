# -*- coding: utf-8 -*-
"""Script-side provider CRUD and list query (pure SQL, no xbmc imports)."""
import os
import sqlite3
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

from . import db

_MAX_RETRIES = 3
_RETRY_SLEEP_SECONDS = 0.1

ERROR_PLAYLIST_REQUIRED = 32010
ERROR_PLAYLIST_INVALID = 32011


def _execute_with_retry(conn, fn):
    """Run fn(conn) retrying up to _MAX_RETRIES times on 'database is locked'."""
    for attempt in range(_MAX_RETRIES):
        try:
            return fn(conn)
        except sqlite3.OperationalError as exc:
            if 'database is locked' not in str(exc) or attempt == _MAX_RETRIES - 1:
                raise
            time.sleep(_RETRY_SLEEP_SECONDS)


def list_providers(conn):
    rows = conn.execute(
        "SELECT id, kind, name, enabled, m3u_url, last_refresh_at, last_error, sort_order "
        "FROM provider WHERE deleted_at IS NULL ORDER BY sort_order, id"
    ).fetchall()
    result = []
    for row in rows:
        result.append({
            'id': row[0],
            'kind': row[1],
            'name': row[2],
            'enabled': row[3],
            'm3u_url': row[4],
            'last_refresh_at': row[5],
            'last_error': row[6],
            'sort_order': row[7],
            'listable_count': db.listable_channel_count(conn, row[0]),
        })
    return result


def count_enabled(conn):
    row = conn.execute(
        "SELECT COUNT(*) FROM provider WHERE deleted_at IS NULL AND enabled = 1"
    ).fetchone()
    return row[0]


def get_provider(conn, provider_id):
    row = conn.execute(
        "SELECT id, kind, name, enabled, m3u_url, last_refresh_at, last_error, "
        "sort_order, config_version FROM provider WHERE id = ? AND deleted_at IS NULL",
        (provider_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        'id': row[0],
        'kind': row[1],
        'name': row[2],
        'enabled': row[3],
        'm3u_url': row[4],
        'last_refresh_at': row[5],
        'last_error': row[6],
        'sort_order': row[7],
        'config_version': row[8],
    }


def create_m3u_provider(conn, name, m3u_url, enabled=True):
    def _do(conn):
        row = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM provider WHERE deleted_at IS NULL"
        ).fetchone()
        sort_order = row[0]
        cursor = conn.execute(
            "INSERT INTO provider (kind, name, enabled, sort_order, m3u_url) "
            "VALUES ('m3u', ?, ?, ?, ?)",
            (name, 1 if enabled else 0, sort_order, m3u_url),
        )
        return cursor.lastrowid

    return _execute_with_retry(conn, _do)


def update_provider(conn, provider_id, name, m3u_url, enabled):
    def _do(conn):
        current = get_provider(conn, provider_id)
        url_changed = current['m3u_url'] != m3u_url
        enabling = current['enabled'] == 0 and enabled
        needs_refresh = url_changed or enabling
        if url_changed:
            conn.execute(
                "UPDATE provider SET name = ?, m3u_url = ?, enabled = ?, "
                "config_version = config_version + 1 WHERE id = ?",
                (name, m3u_url, 1 if enabled else 0, provider_id),
            )
        else:
            conn.execute(
                "UPDATE provider SET name = ?, m3u_url = ?, enabled = ? WHERE id = ?",
                (name, m3u_url, 1 if enabled else 0, provider_id),
            )
        return needs_refresh

    return _execute_with_retry(conn, _do)


def validate_m3u(name, m3u_url):
    errors = []
    if not m3u_url:
        errors.append(('m3u_url', ERROR_PLAYLIST_REQUIRED))
    else:
        parsed = urlparse(m3u_url)
        is_url = parsed.scheme in ('http', 'https')
        if not is_url and not os.path.isfile(m3u_url):
            errors.append(('m3u_url', ERROR_PLAYLIST_INVALID))
    return errors


def auto_name(m3u_url):
    if not m3u_url:
        return ''
    parsed = urlparse(m3u_url)
    path = parsed.path if parsed.scheme in ('http', 'https') else m3u_url
    segment = os.path.basename(path.rstrip('/'))
    if segment:
        return os.path.splitext(segment)[0]
    if parsed.netloc:
        return parsed.netloc
    return m3u_url


def _parse_iso(iso_text):
    text = iso_text.strip()
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def relative_time(iso_text, now):
    if not iso_text:
        return None
    dt = _parse_iso(iso_text)
    seconds = (now - dt).total_seconds()
    if seconds < 60:
        return ('just_now', 0)
    if seconds < 3600:
        return ('minutes_ago', int(seconds // 60))
    if seconds < 86400:
        return ('hours_ago', int(seconds // 3600))
    return ('days_ago', int(seconds // 86400))


def error_snippet(last_error, max_len=40):
    if not last_error:
        return None
    if len(last_error) <= max_len:
        return last_error
    return last_error[:max_len] + '…'
