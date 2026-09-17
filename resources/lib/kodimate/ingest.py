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
    from urllib.parse import urlsplit, quote
except ImportError:  # pragma: no cover - Python 2 fallback, unused on target
    from urlparse import urlsplit
    from urllib import quote

from . import db, m3u, urls

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


def _resolve_epg_source(conn, provider_id, declared_url):
    """Upsert (or clear) the provider's epg_source row from `epg_override_url`
    (wins) or `declared_url` (the playlist/xmltv.php default). Returns the
    resolved URL, or None if there is no EPG Source at all."""
    override_row = conn.execute(
        "SELECT epg_override_url FROM provider WHERE id = ?", (provider_id,)
    ).fetchone()
    override = override_row[0] if override_row else None
    resolved = override or declared_url

    if resolved:
        existing = conn.execute(
            "SELECT url FROM epg_source WHERE provider_id = ?", (provider_id,)
        ).fetchone()
        if existing is None or existing[0] != resolved:
            conn.execute(
                "INSERT INTO epg_source (provider_id, url) VALUES (?, ?) "
                "ON CONFLICT(provider_id) DO UPDATE SET "
                "url = excluded.url, etag = NULL, last_modified = NULL",
                (provider_id, resolved),
            )
    else:
        conn.execute(
            "DELETE FROM programme WHERE epg_source_id IN "
            "(SELECT id FROM epg_source WHERE provider_id = ?)", (provider_id,)
        )
        conn.execute(
            "DELETE FROM epg_channel WHERE epg_source_id IN "
            "(SELECT id FROM epg_source WHERE provider_id = ?)", (provider_id,)
        )
        conn.execute("DELETE FROM epg_source WHERE provider_id = ?", (provider_id,))

    return resolved


def _mark_stale_purge_and_clean_groups(conn, provider_id, now_iso, now_dt):
    """Shared refresh tail: mark absent channels Stale, purge old-Stale rows,
    and drop groups left with no channels. Used by both M3U and Xtream
    ingest (docs/design/schema.md "Stale"; CONTEXT.md "Group")."""
    conn.execute(
        "UPDATE channel SET stale_since = ? "
        "WHERE provider_id = ? AND stale_since IS NULL "
        "AND (last_seen_at IS NULL OR last_seen_at < ?)",
        (now_iso, provider_id, now_iso),
    )

    purge_cutoff = _to_iso(now_dt - timedelta(days=_STALE_PURGE_DAYS))
    conn.execute(
        "DELETE FROM channel_override WHERE provider_id = ? AND channel_key IN "
        "(SELECT channel_key FROM channel WHERE provider_id = ? "
        "AND stale_since IS NOT NULL AND stale_since <= ?)",
        (provider_id, provider_id, purge_cutoff),
    )
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

        for position, (entry, key) in enumerate(zip(playlist.entries, keys), start=1):
            group_name = entry.get('group_title') or UNCATEGORISED
            headers = entry.get('headers') or {}
            headers_json = json.dumps(headers) if headers else None
            catchup = _with_header_catchup_defaults(entry, playlist.header_attrs)

            conn.execute(
                """
                INSERT INTO channel (
                    provider_id, channel_key, name, normalised_name, stream_url,
                    logo_url, group_id, provider_number, position, epg_channel_id,
                    catchup_days, catchup_mode, catchup_source, catchup_correction_hours,
                    headers_json, stale_since, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                ON CONFLICT(provider_id, channel_key) DO UPDATE SET
                    name = excluded.name,
                    normalised_name = excluded.normalised_name,
                    stream_url = excluded.stream_url,
                    logo_url = excluded.logo_url,
                    group_id = excluded.group_id,
                    provider_number = excluded.provider_number,
                    position = excluded.position,
                    epg_channel_id = excluded.epg_channel_id,
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
                    entry.get('tvg_chno'), position, entry.get('tvg_id') or None,
                    catchup['catchup_days'], catchup['catchup'],
                    catchup['catchup_source'], catchup['catchup_correction'],
                    headers_json, now_iso,
                ),
            )

        _mark_stale_purge_and_clean_groups(conn, provider_id, now_iso, now_dt)

        resolved_epg_url = _resolve_epg_source(conn, provider_id, epg_url)

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
    return RefreshOutcome(channel_count, listable_count, resolved_epg_url)


def refresh_xtream_provider(conn, provider_id, account, categories, streams, now,
                             expected_config_version=None):
    """Ingest an Xtream account/categories/streams triple (from xtream.py) for one provider.

    `streams` is the flat list of raw `get_live_streams` stream dicts (in
    server response order), each carrying its own `category_id`.
    """
    now_dt = _to_datetime(now)
    now_iso = _to_iso(now_dt)

    conn.execute("BEGIN IMMEDIATE")
    try:
        if expected_config_version is not None:
            row = conn.execute(
                "SELECT config_version FROM provider WHERE id = ?", (provider_id,)
            ).fetchone()
            if row is None or row[0] != expected_config_version:
                conn.execute("ROLLBACK")
                raise ConfigVersionChanged()

        provider_row = conn.execute(
            "SELECT xtream_host, xtream_username, xtream_password, "
            "stream_format, learned_stream_format FROM provider WHERE id = ?",
            (provider_id,),
        ).fetchone()
        host, username, password, stream_format, learned_stream_format = provider_row
        provider = {'stream_format': stream_format, 'learned_stream_format': learned_stream_format}
        form = urls.live_form(provider, account.get('allowed_output_formats'))

        category_names = OrderedDict()
        for category in categories:
            cid = str(category.get('category_id'))
            category_names[cid] = category.get('category_name') or UNCATEGORISED
        cid_by_norm = {}
        for cid in category_names:
            norm = m3u._to_int(cid)
            if norm is not None:
                cid_by_norm[norm] = cid

        def _matched_cid(stream):
            norm = m3u._to_int(stream.get('category_id'))
            if norm is None:
                return None
            return cid_by_norm.get(norm)

        group_names_in_order = list(category_names.values())
        if UNCATEGORISED not in group_names_in_order and \
                any(_matched_cid(stream) is None for stream in streams):
            group_names_in_order.append(UNCATEGORISED)
        group_ids = _ensure_groups(conn, provider_id, group_names_in_order)

        position = 0
        for stream in streams:
            cid = _matched_cid(stream)
            category_name = category_names[cid] if cid is not None else UNCATEGORISED
            position += 1
            stream_id = str(stream.get('stream_id'))
            tv_archive = m3u._to_int(stream.get('tv_archive'))
            if tv_archive is None:
                catchup_days = None
            elif tv_archive:
                catchup_days = m3u._to_int(stream.get('tv_archive_duration'))
            else:
                catchup_days = 0

            conn.execute(
                """
                INSERT INTO channel (
                    provider_id, channel_key, name, normalised_name, stream_url,
                    logo_url, group_id, provider_number, position,
                    epg_channel_id, catchup_days, stale_since, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                ON CONFLICT(provider_id, channel_key) DO UPDATE SET
                    name = excluded.name,
                    normalised_name = excluded.normalised_name,
                    stream_url = excluded.stream_url,
                    logo_url = excluded.logo_url,
                    group_id = excluded.group_id,
                    provider_number = excluded.provider_number,
                    position = excluded.position,
                    epg_channel_id = excluded.epg_channel_id,
                    catchup_days = excluded.catchup_days,
                    stale_since = NULL,
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    provider_id, stream_id, stream.get('name') or '',
                    normalise_name(stream.get('name')),
                    urls.xtream_live_url(host, username, password, stream_id, form),
                    stream.get('stream_icon') or None, group_ids[category_name],
                    m3u._to_int(stream.get('num')), position,
                    stream.get('epg_channel_id') or None, catchup_days, now_iso,
                ),
            )

        _mark_stale_purge_and_clean_groups(conn, provider_id, now_iso, now_dt)

        conn.execute(
            "UPDATE provider SET account_expires_at = ?, max_connections = ?, "
            "allowed_output_formats = ?, server_timezone = ? WHERE id = ?",
            (
                account.get('account_expires_at'), account.get('max_connections'),
                json.dumps(account['allowed_output_formats'])
                if account.get('allowed_output_formats') is not None else None,
                account.get('server_timezone'),
                provider_id,
            ),
        )

        epg_url = '{0}/xmltv.php?username={1}&password={2}'.format(
            host, quote(str(username), safe=''), quote(str(password), safe='')
        )
        resolved_epg_url = _resolve_epg_source(conn, provider_id, epg_url)

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
    return RefreshOutcome(channel_count, listable_count, resolved_epg_url)
