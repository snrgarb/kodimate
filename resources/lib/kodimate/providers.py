# -*- coding: utf-8 -*-
"""Script-side provider CRUD and list query (pure SQL, no xbmc imports)."""
import os
import sqlite3
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from . import db

_MAX_RETRIES = 3
_RETRY_SLEEP_SECONDS = 0.1

ERROR_PLAYLIST_REQUIRED = 32010
ERROR_PLAYLIST_INVALID = 32011
ERROR_HOST_REQUIRED = 32046
ERROR_HOST_INVALID = 32047
ERROR_USERNAME_REQUIRED = 32048
ERROR_PASSWORD_REQUIRED = 32049

_EXPIRY_WARNING_DAYS = 7


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
        "SELECT id, kind, name, enabled, m3u_url, last_refresh_at, last_error, sort_order, "
        "xtream_host, xtream_username, xtream_password, account_expires_at, max_connections "
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
            'xtream_host': row[8],
            'xtream_username': row[9],
            'xtream_password': row[10],
            'account_expires_at': row[11],
            'max_connections': row[12],
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
        "sort_order, config_version, xtream_host, xtream_username, xtream_password, "
        "account_expires_at, max_connections "
        "FROM provider WHERE id = ? AND deleted_at IS NULL",
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
        'xtream_host': row[9],
        'xtream_username': row[10],
        'xtream_password': row[11],
        'account_expires_at': row[12],
        'max_connections': row[13],
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


def set_enabled(conn, provider_id, enabled):
    """Enable/disable a provider of either kind; returns needs_refresh."""
    def _do(conn):
        current = get_provider(conn, provider_id)
        needs_refresh = current['enabled'] == 0 and enabled
        conn.execute(
            "UPDATE provider SET enabled = ? WHERE id = ?",
            (1 if enabled else 0, provider_id),
        )
        return needs_refresh

    return _execute_with_retry(conn, _do)


def normalise_xtream_host(host):
    """Return `scheme://netloc` for host: path/query/fragment and trailing slash stripped."""
    parsed = urlparse(host)
    return '{0}://{1}'.format(parsed.scheme, parsed.netloc)


def create_xtream_provider(conn, name, host, username, password, enabled=True):
    def _do(conn):
        row = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM provider WHERE deleted_at IS NULL"
        ).fetchone()
        sort_order = row[0]
        cursor = conn.execute(
            "INSERT INTO provider (kind, name, enabled, sort_order, "
            "xtream_host, xtream_username, xtream_password) "
            "VALUES ('xtream', ?, ?, ?, ?, ?, ?)",
            (name, 1 if enabled else 0, sort_order,
             normalise_xtream_host(host), username, password),
        )
        return cursor.lastrowid

    return _execute_with_retry(conn, _do)


def update_xtream_provider(conn, provider_id, name, host, username, password, enabled):
    def _do(conn):
        current = get_provider(conn, provider_id)
        normalised_host = normalise_xtream_host(host)
        creds_changed = (
            current['xtream_host'] != normalised_host
            or current['xtream_username'] != username
            or current['xtream_password'] != password
        )
        enabling = current['enabled'] == 0 and enabled
        needs_refresh = creds_changed or enabling
        if creds_changed:
            conn.execute(
                "UPDATE provider SET name = ?, xtream_host = ?, xtream_username = ?, "
                "xtream_password = ?, enabled = ?, config_version = config_version + 1, "
                "learned_stream_format = NULL WHERE id = ?",
                (name, normalised_host, username, password, 1 if enabled else 0, provider_id),
            )
        else:
            conn.execute(
                "UPDATE provider SET name = ?, xtream_host = ?, xtream_username = ?, "
                "xtream_password = ?, enabled = ? WHERE id = ?",
                (name, normalised_host, username, password, 1 if enabled else 0, provider_id),
            )
        return needs_refresh

    return _execute_with_retry(conn, _do)


def validate_xtream(name, host, username, password):
    errors = []
    if not host:
        errors.append(('xtream_host', ERROR_HOST_REQUIRED))
    else:
        parsed = urlparse(host)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc:
            errors.append(('xtream_host', ERROR_HOST_INVALID))
    if not username:
        errors.append(('xtream_username', ERROR_USERNAME_REQUIRED))
    if not password:
        errors.append(('xtream_password', ERROR_PASSWORD_REQUIRED))
    return errors


def auto_name_xtream(host):
    return urlparse(host).netloc


def split_get_php_url(text):
    """Split a `get.php?username=...&password=...` URL into (host, username, password)."""
    parsed = urlparse(text or '')
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        return None
    if not parsed.path.rstrip('/').endswith('get.php'):
        return None
    params = parse_qs(parsed.query)
    if 'username' not in params or 'password' not in params:
        return None
    host = '{0}://{1}'.format(parsed.scheme, parsed.netloc)
    return (host, params['username'][0], params['password'][0])


def expiry_state(account_expires_at_iso, now):
    """('ok'|'warning'|'expired', date_text) for the Xtream expiry, or None if absent."""
    if not account_expires_at_iso:
        return None
    dt = _parse_iso(account_expires_at_iso)
    date_text = dt.strftime('%Y-%m-%d')
    remaining_days = (dt - now).total_seconds() / 86400
    if remaining_days < 0:
        return ('expired', date_text)
    if remaining_days < _EXPIRY_WARNING_DAYS:
        return ('warning', date_text)
    return ('ok', date_text)


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
