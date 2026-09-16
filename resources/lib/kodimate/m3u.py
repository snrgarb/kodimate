# -*- coding: utf-8 -*-
"""Pure M3U playlist parser.

No xbmc* imports, no I/O: parse() takes the raw playlist text and returns a
Playlist. Header/entry attribute values may be quoted (spaces allowed) or
bare (no spaces). Header merge order for headers (lowest to highest
precedence, later wins): #EXTVLCOPT lines, then #KODIPROP stream-headers
lines, then the URL's own `|Key=Value&Key2=Value2` pipe suffix. Unknown
#KODIPROP keys are kept verbatim under a `kodiprop` sub-dict rather than
dropped, since a future ticket (stream playback) may need them.
"""
import re

from . import fetch

_ATTR_RE = re.compile(r'([A-Za-z0-9_-]+)=("([^"]*)"|(\S*))')

_CANONICAL_HEADERS = {
    'user-agent': 'User-Agent',
    'referer': 'Referer',
    'referrer': 'Referer',
    'origin': 'Origin',
    'cookie': 'Cookie',
}


class M3UError(ValueError):
    pass


class Playlist(object):
    def __init__(self, header_attrs, entries):
        self.header_attrs = header_attrs
        self.entries = entries


def _parse_attrs(text):
    attrs = {}
    for m in _ATTR_RE.finditer(text):
        key = m.group(1).lower()
        value = m.group(3) if m.group(3) is not None else m.group(4)
        attrs[key] = value
    return attrs


def _canonical_header_name(name):
    return _CANONICAL_HEADERS.get(name.strip().lower(), name.strip())


def _merge_header_pairs(headers, pairs_text, sep='&'):
    for pair in pairs_text.split(sep):
        if '=' not in pair:
            continue
        key, value = pair.split('=', 1)
        headers[_canonical_header_name(key)] = value


def _strip_pipe_suffix(url):
    idx = url.find('|')
    if idx == -1:
        return url, {}
    base = url[:idx]
    headers = {}
    _merge_header_pairs(headers, url[idx + 1:], sep='&')
    return base, headers


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _group_title(raw):
    if not raw:
        return None
    first = raw.split(';', 1)[0].strip()
    return first or None


class _PendingEntry(object):
    def __init__(self, attrs, name):
        self.attrs = attrs
        self.name = name
        self.headers = {}


def parse(text):
    lines = text.splitlines()

    has_extm3u = False
    has_extinf = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('#EXTM3U'):
            has_extm3u = True
        elif stripped.startswith('#EXTINF'):
            has_extinf = True
    if not has_extm3u and not has_extinf:
        raise M3UError(fetch.ERROR_NOT_M3U)

    header_attrs = {}
    entries = []
    pending = None

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith('#EXTM3U'):
            header_attrs = _parse_attrs(stripped[len('#EXTM3U'):])
            continue

        if stripped.startswith('#EXTINF'):
            rest = stripped[len('#EXTINF'):]
            if rest.startswith(':'):
                rest = rest[1:]
            attrs_part, _, name_part = rest.rpartition(',')
            attrs = _parse_attrs(attrs_part)
            name = name_part.strip() or (attrs.get('tvg-name') or '')
            pending = _PendingEntry(attrs, name)
            continue

        if stripped.startswith('#EXTVLCOPT'):
            body = stripped[len('#EXTVLCOPT'):].lstrip(':-')
            if pending is not None and '=' in body:
                key, value = body.split('=', 1)
                key = key.strip().lower()
                if key == 'http-user-agent':
                    pending.headers['User-Agent'] = value
                elif key == 'http-referrer':
                    pending.headers['Referer'] = value
            continue

        if stripped.startswith('#KODIPROP'):
            body = stripped[len('#KODIPROP'):].lstrip(':')
            if pending is not None and '=' in body:
                key, value = body.split('=', 1)
                key = key.strip()
                if key.lower() == 'inputstream.adaptive.stream_headers':
                    _merge_header_pairs(pending.headers, value, sep='&')
                else:
                    pending.headers.setdefault('kodiprop', {})[key] = value
            continue

        if stripped.startswith('#'):
            continue

        # A stream URL line, terminating the current pending entry (if any).
        url, pipe_headers = _strip_pipe_suffix(stripped)
        if not url:
            pending = None
            continue

        if pending is None:
            pending = _PendingEntry({}, '')

        attrs = pending.attrs
        headers = dict(pending.headers)
        headers.update(pipe_headers)

        entries.append({
            'name': pending.name or attrs.get('tvg-name') or '',
            'url': url,
            'tvg_id': attrs.get('tvg-id') or None,
            'tvg_name': attrs.get('tvg-name') or None,
            'tvg_logo': attrs.get('tvg-logo') or None,
            'tvg_chno': _to_int(attrs.get('tvg-chno')),
            'group_title': _group_title(attrs.get('group-title')),
            'catchup': attrs.get('catchup') or attrs.get('catchup-type') or None,
            'catchup_source': attrs.get('catchup-source') or None,
            'catchup_days': _to_int(attrs.get('catchup-days')),
            'catchup_correction': _to_float(attrs.get('catchup-correction')),
            'headers': headers,
        })
        pending = None

    return Playlist(header_attrs, entries)
