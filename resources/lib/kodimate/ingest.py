# -*- coding: utf-8 -*-
"""M3U playlist -> SQLite rows for one provider. Service-side only (ADR 0003).

Timestamps are stored as ISO-8601 UTC strings of the form
``YYYY-MM-DDTHH:MM:SSZ`` (see ``_to_iso``/``_to_datetime``); callers may pass
either that string form or a naive UTC ``datetime`` as ``now``.
"""
import json
import re
from collections import Counter, OrderedDict
from datetime import datetime, timedelta

try:
    from urllib.parse import urlsplit
except ImportError:  # pragma: no cover - Python 2 fallback, unused on target
    from urlparse import urlsplit

from . import db, m3u

UNCATEGORISED = 'Uncategorised'

_ISO_FORMAT = '%Y-%m-%dT%H:%M:%SZ'
_STALE_PURGE_DAYS = 7

_SUFFIX_RE = re.compile(r'(hd|fhd|uhd|4k)$')
_NON_ALNUM_RE = re.compile(r'[^a-z0-9]+')


class ConfigVersionChanged(Exception):
    """Raised when the provider's config_version changed mid-refresh."""


class RefreshOutcome(object):
    def __init__(self, channel_count, listable_count, epg_url):
        self.channel_count = channel_count
        self.listable_count = listable_count
        self.epg_url = epg_url


def _to_datetime(now):
    if isinstance(now, datetime):
        return now.replace(microsecond=0)
    return datetime.strptime(now, _ISO_FORMAT)


def _to_iso(now):
    return _to_datetime(now).strftime(_ISO_FORMAT)


def normalise_name(name):
    """Lowercase, strip non-alphanumerics, strip a trailing HD/FHD/UHD/4K suffix."""
    lowered = (name or '').lower()
    stripped = _NON_ALNUM_RE.sub('', lowered)
    return _SUFFIX_RE.sub('', stripped)


def strip_url(url):
    """Return `host/path` for `url`: scheme and query string removed."""
    parts = urlsplit(url)
    return (parts.netloc + parts.path)


def _derive_channel_keys(entries):
    tvg_id_counts = Counter(e['tvg_id'] for e in entries if e.get('tvg_id'))
    stripped_candidates = []
    prelim = [None] * len(entries)
    for i, entry in enumerate(entries):
        tvg_id = entry.get('tvg_id')
        if tvg_id and tvg_id_counts[tvg_id] == 1:
            prelim[i] = ('tvg_id', tvg_id)
        else:
            stripped = strip_url(entry['url'])
            prelim[i] = ('stripped', stripped)
            stripped_candidates.append(stripped)
    stripped_counts = Counter(stripped_candidates)

    keys = []
    for i, entry in enumerate(entries):
        kind, value = prelim[i]
        if kind == 'tvg_id':
            keys.append(value)
        elif stripped_counts[value] == 1:
            keys.append(value)
        else:
            keys.append(entry['url'])
    return keys


def listable_channel_count(conn, provider_id):
    return db.listable_channel_count(conn, provider_id)


# Header-level (#EXTM3U) attrs that act as a per-channel default when a
# channel's own #EXTINF omits the attribute (docs/research/m3u-catchup-
# conventions.md: channel-level value wins, header-level is the fallback).
_CATCHUP_FIELD_TO_HEADER_ATTR = {
    'catchup': 'catchup',
    'catchup_source': 'catchup-source',
    'catchup_days': 'catchup-days',
    'catchup_correction': 'catchup-correction',
}


def _with_header_catchup_defaults(entry, header_attrs):
    """Return entry's catchup fields, falling back to header_attrs when absent."""
    resolved = {}
    for field, header_key in _CATCHUP_FIELD_TO_HEADER_ATTR.items():
        value = entry.get(field)
        if value is None and header_key in header_attrs:
            if field == 'catchup_days':
                value = m3u._to_int(header_attrs[header_key])
            elif field == 'catchup_correction':
                value = m3u._to_float(header_attrs[header_key])
            else:
                value = header_attrs[header_key] or None
        resolved[field] = value
    return resolved


def _ensure_groups(conn, provider_id, group_names_in_order):
    existing = dict(conn.execute(
        "SELECT name, id FROM channel_group WHERE provider_id = ?", (provider_id,)
    ).fetchall())
    max_sort_row = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) FROM channel_group WHERE provider_id = ?",
        (provider_id,),
    ).fetchone()
    next_sort = max_sort_row[0] + 1

    group_ids = {}
    for name in group_names_in_order:
        if name in existing:
            group_ids[name] = existing[name]
            continue
        cur = conn.execute(
            "INSERT INTO channel_group (provider_id, name, sort_order) VALUES (?, ?, ?)",
            (provider_id, name, next_sort),
        )
        group_ids[name] = cur.lastrowid
        next_sort += 1
    return group_ids


def refresh_m3u_provider(conn, provider_id, playlist_text, now, expected_config_version=None):
    playlist = m3u.parse(playlist_text)
    now_dt = _to_datetime(now)
    now_iso = _to_iso(now_dt)

    keys = _derive_channel_keys(playlist.entries)
    epg_url = playlist.header_attrs.get('url-tvg') or playlist.header_attrs.get('x-tvg-url')

    group_names_in_order = list(OrderedDict(
        (entry.get('group_title') or UNCATEGORISED, None) for entry in playlist.entries
    ).keys())

    conn.execute("BEGIN IMMEDIATE")
    try:
        if expected_config_version is not None:
            row = conn.execute(
                "SELECT config_version FROM provider WHERE id = ?", (provider_id,)
            ).fetchone()
            if row is None or row[0] != expected_config_version:
                conn.execute("ROLLBACK")
                raise ConfigVersionChanged()

        group_ids = _ensure_groups(conn, provider_id, group_names_in_order)

        present_keys = []
        for position, (entry, key) in enumerate(zip(playlist.entries, keys), start=1):
            group_name = entry.get('group_title') or UNCATEGORISED
            headers = entry.get('headers') or {}
            headers_json = json.dumps(headers) if headers else None
            catchup = _with_header_catchup_defaults(entry, playlist.header_attrs)

            conn.execute(
                """
                INSERT INTO channel (
                    provider_id, channel_key, name, normalised_name, stream_url,
                    logo_url, group_id, provider_number, position,
                    catchup_days, catchup_mode, catchup_source, catchup_correction_hours,
                    headers_json, stale_since, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                ON CONFLICT(provider_id, channel_key) DO UPDATE SET
                    name = excluded.name,
                    normalised_name = excluded.normalised_name,
                    stream_url = excluded.stream_url,
                    logo_url = excluded.logo_url,
                    group_id = excluded.group_id,
                    provider_number = excluded.provider_number,
                    position = excluded.position,
                    catchup_days = excluded.catchup_days,
                    catchup_mode = excluded.catchup_mode,
                    catchup_source = excluded.catchup_source,
                    catchup_correction_hours = excluded.catchup_correction_hours,
                    headers_json = excluded.headers_json,
                    stale_since = NULL,
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    provider_id, key, entry['name'], normalise_name(entry['name']),
                    entry['url'], entry.get('tvg_logo'), group_ids[group_name],
                    entry.get('tvg_chno'), position,
                    catchup['catchup_days'], catchup['catchup'],
                    catchup['catchup_source'], catchup['catchup_correction'],
                    headers_json, now_iso,
                ),
            )
            present_keys.append(key)

        if present_keys:
            placeholders = ','.join('?' * len(present_keys))
            conn.execute(
                "UPDATE channel SET stale_since = ? "
                "WHERE provider_id = ? AND stale_since IS NULL "
                "AND channel_key NOT IN ({0})".format(placeholders),
                [now_iso, provider_id] + present_keys,
            )
        else:
            conn.execute(
                "UPDATE channel SET stale_since = ? "
                "WHERE provider_id = ? AND stale_since IS NULL",
                (now_iso, provider_id),
            )

        purge_cutoff = _to_iso(now_dt - timedelta(days=_STALE_PURGE_DAYS))
        conn.execute(
            "DELETE FROM channel WHERE provider_id = ? "
            "AND stale_since IS NOT NULL AND stale_since <= ?",
            (provider_id, purge_cutoff),
        )
        conn.execute(
            "DELETE FROM channel_group WHERE provider_id = ? AND id NOT IN "
            "(SELECT DISTINCT group_id FROM channel WHERE provider_id = ? "
            "AND group_id IS NOT NULL)",
            (provider_id, provider_id),
        )

        if epg_url:
            conn.execute(
                "INSERT INTO epg_source (provider_id, url) VALUES (?, ?) "
                "ON CONFLICT(provider_id) DO UPDATE SET url = excluded.url",
                (provider_id, epg_url),
            )

        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise

    channel_count = conn.execute(
        "SELECT COUNT(*) FROM channel WHERE provider_id = ?", (provider_id,)
    ).fetchone()[0]
    listable_count = listable_channel_count(conn, provider_id)
    return RefreshOutcome(channel_count, listable_count, epg_url)
