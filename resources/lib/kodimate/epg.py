# -*- coding: utf-8 -*-
"""XMLTV EPG ingest: stream, parse, stage, swap. Service-side only (ADR 0003).

No xbmc* imports. `load_xmltv` streams `stream` (a file-like object, already
opened by fetch.open_stream) through `xml.etree.ElementTree.iterparse`,
clearing each element as it is consumed, stages programme rows outside any
long transaction, then swaps them into `programme` plus `epg_channel` inside
one short `BEGIN IMMEDIATE` transaction. `match_channels` resolves each
Channel's `epg_channel_id` against the `epg_channel` rows recorded for its
Provider's EPG Source.
"""
import gzip
import io
import lzma
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from . import ingest

_SRC_SUFFIX_RE = re.compile(r'\s*\(src\d+\)\s*$', re.IGNORECASE)

_XMLTV_TIME_RE = re.compile(
    r'^(\d{12}|\d{14})\s*(?:([+-]\d{4}))?$'
)

_RETENTION_DAYS = 7
_BATCH_SIZE = 500

# A decompressed XMLTV document larger than this aborts the parse; guards
# against a compression-bomb response from an untrusted EPG Source.
MAX_XMLTV_BYTES = 256 * 1024 * 1024

_PROGRAMME_COLUMNS = (
    'epg_source_id', 'xmltv_channel_id', 'start', 'end',
    'title', 'subtitle', 'description', 'icon_url', 'category', 'catchup_id',
)


class EpgTooLarge(Exception):
    pass


_DOCTYPE_NEEDLE = b'<!DOCTYPE'

# A legitimate XMLTV DOCTYPE is one short line; an unresolved declaration
# longer than this is treated as malformed rather than buffered indefinitely.
_MAX_DOCTYPE_BYTES = 4096


class _GuardedReader(object):
    """Wraps the (possibly decompressed) XMLTV file object: raises
    EpgTooLarge once cumulative bytes read exceed MAX_XMLTV_BYTES (checked
    against the module attribute on every call, so tests can lower it), and
    raises ET.ParseError on a DOCTYPE with an internal subset (a `[` outside
    any quoted literal, before the declaration's closing `>`, also outside
    any quoted literal), which is what entity-expansion / billion-laughs
    attacks require; a DOCTYPE that only references an external DTD (name /
    PUBLIC / SYSTEM literals, no unquoted `[...]`) is harmless with expat,
    which never fetches external DTDs by default, and is passed through
    unchanged. The scan is quote-aware (a `'...'` or `"..."` literal may
    itself contain `[` or `>` without those counting) and size-capped at
    _MAX_DOCTYPE_BYTES, so a declaration that never resolves can't be used to
    stall the guard. ET.XMLParser's C-accelerated implementation doesn't
    expose the underlying expat parser for a StartDoctypeDeclHandler, so this
    is a stream-level check instead; it buffers from the point the DOCTYPE
    needle is seen until the declaration's unquoted `[` or `>` is found, so
    both the needle and the declaration itself may straddle a read
    boundary."""

    def __init__(self, fileobj):
        self._fileobj = fileobj
        self._count = 0
        self._tail = b''
        self._pending = None

    def read(self, *args, **kwargs):
        chunk = self._fileobj.read(*args, **kwargs)
        self._count += len(chunk)
        if self._count > MAX_XMLTV_BYTES:
            raise EpgTooLarge('EPG document exceeds max size')
        if self._pending is not None:
            self._pending += chunk
            self._resolve_pending()
        else:
            self._scan_window(self._tail + chunk)
        return chunk

    def _scan_window(self, window):
        idx = window.find(_DOCTYPE_NEEDLE)
        if idx == -1:
            self._tail = window[-(len(_DOCTYPE_NEEDLE) - 1):]
        else:
            self._pending = window[idx:]
            self._resolve_pending()

    def _resolve_pending(self):
        quote = None
        i = 0
        n = len(self._pending)
        while i < n:
            if i >= _MAX_DOCTYPE_BYTES:
                raise ET.ParseError('DOCTYPE not allowed')
            ch = self._pending[i:i + 1]
            if quote is not None:
                if ch == quote:
                    quote = None
            elif ch in (b'"', b"'"):
                quote = ch
            elif ch == b'[':
                raise ET.ParseError('DOCTYPE not allowed')
            elif ch == b'>':
                remainder = self._pending[i + 1:]
                self._pending = None
                self._scan_window(remainder)
                return
            i += 1


def strip_source_suffix(value):
    if value is None:
        return None
    return _SRC_SUFFIX_RE.sub('', value)


def open_xmltv(stream):
    """Wrap `stream` and transparently decompress gzip/lzma by magic bytes."""
    buffered = stream if hasattr(stream, 'peek') else io.BufferedReader(stream)
    head = buffered.peek(6)
    if head[:2] == b'\x1f\x8b':
        return gzip.GzipFile(fileobj=buffered)
    if head[:6] == b'\xfd7zXZ\x00':
        return lzma.LZMAFile(buffered)
    return buffered


def parse_xmltv_time(value):
    """Parse an XMLTV timestamp (`YYYYMMDDHHMMSS [+-]HHMM` or a 12-digit /
    no-offset variant) into an ISO UTC string, or None if unparsable."""
    if not value:
        return None
    m = _XMLTV_TIME_RE.match(value.strip())
    if not m:
        return None
    digits, offset = m.group(1), m.group(2)
    if len(digits) == 12:
        digits += '00'
    try:
        dt = datetime.strptime(digits, '%Y%m%d%H%M%S')
    except ValueError:
        return None
    if offset:
        sign = 1 if offset[0] == '+' else -1
        delta = timedelta(hours=int(offset[1:3]), minutes=int(offset[3:5]))
        dt = dt - sign * delta
    return ingest._to_iso(dt)


def _first_text(elem, tag):
    child = elem.find(tag)
    return child.text if child is not None else None


def _flush_batch(conn, batch):
    if not batch:
        return
    conn.execute("BEGIN")
    try:
        conn.executemany(
            "INSERT OR REPLACE INTO programme_staging "
            "(epg_source_id, xmltv_channel_id, start, end, title, subtitle, "
            "description, icon_url, category, catchup_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            batch,
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    del batch[:]


def load_xmltv(conn, epg_source_id, stream, now, etag=None, last_modified=None,
                expected_config_version=None):
    now_dt = ingest._to_datetime(now)
    cutoff = ingest._to_iso(now_dt - timedelta(days=_RETENTION_DAYS))

    conn.execute("DROP TABLE IF EXISTS programme_staging")
    conn.execute(
        """CREATE TABLE programme_staging (
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
        )"""
    )

    channels = {}
    batch = []
    fileobj = _GuardedReader(open_xmltv(stream))
    try:
        for event, elem in ET.iterparse(fileobj, events=('end',)):
            if elem.tag == 'channel':
                channel_id = elem.get('id')
                if channel_id:
                    name = ingest.normalise_name(_first_text(elem, 'display-name'))
                    channels[channel_id] = name
                elem.clear()
            elif elem.tag == 'programme':
                channel_id = elem.get('channel')
                start = parse_xmltv_time(elem.get('start'))
                end = parse_xmltv_time(elem.get('stop'))
                if not channel_id or not start or not end:
                    elem.clear()
                    continue
                if end < cutoff:
                    elem.clear()
                    continue
                channels.setdefault(channel_id, None)
                category_elem = elem.find('category')
                batch.append((
                    epg_source_id, channel_id, start, end,
                    _first_text(elem, 'title'),
                    _first_text(elem, 'sub-title'),
                    _first_text(elem, 'desc'),
                    _icon_src(elem),
                    category_elem.text if category_elem is not None else None,
                    elem.get('catchup-id'),
                ))
                if len(batch) >= _BATCH_SIZE:
                    _flush_batch(conn, batch)
                elem.clear()
        _flush_batch(conn, batch)
    except Exception:
        conn.execute("DROP TABLE IF EXISTS programme_staging")
        raise

    return _swap(
        conn, epg_source_id, channels, now_dt, etag, last_modified,
        expected_config_version,
    )


def _icon_src(elem):
    icon = elem.find('icon')
    return icon.get('src') if icon is not None else None


def _swap(conn, epg_source_id, channels, now_dt, etag, last_modified,
          expected_config_version):
    conn.execute("BEGIN IMMEDIATE")
    try:
        if expected_config_version is not None:
            row = conn.execute(
                "SELECT p.config_version FROM provider p "
                "JOIN epg_source e ON e.provider_id = p.id WHERE e.id = ?",
                (epg_source_id,),
            ).fetchone()
            if row is None or row[0] != expected_config_version:
                conn.execute("ROLLBACK")
                conn.execute("DROP TABLE IF EXISTS programme_staging")
                raise ingest.ConfigVersionChanged()

        conn.execute("DELETE FROM programme WHERE epg_source_id = ?", (epg_source_id,))
        conn.execute(
            "INSERT INTO programme ({0}) SELECT {0} FROM programme_staging".format(
                ', '.join(_PROGRAMME_COLUMNS)
            )
        )
        inserted = conn.execute(
            "SELECT COUNT(*) FROM programme WHERE epg_source_id = ?", (epg_source_id,)
        ).fetchone()[0]

        conn.execute("DELETE FROM epg_channel WHERE epg_source_id = ?", (epg_source_id,))
        conn.executemany(
            "INSERT INTO epg_channel (epg_source_id, xmltv_channel_id, normalised_name) "
            "VALUES (?, ?, ?)",
            [(epg_source_id, cid, name) for cid, name in channels.items()],
        )

        conn.execute("DROP TABLE programme_staging")
        conn.execute(
            "UPDATE epg_source SET last_fetched_at = ?, etag = ?, last_modified = ? "
            "WHERE id = ?",
            (ingest._to_iso(now_dt), etag, last_modified, epg_source_id),
        )
        conn.execute("COMMIT")
    except ingest.ConfigVersionChanged:
        raise
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        try:
            conn.execute("DROP TABLE IF EXISTS programme_staging")
        except Exception:
            pass
        raise
    return inserted


def prune_expired(conn, epg_source_id, now):
    """Delete `programme` rows for epg_source_id whose `end` is older than
    the retention window. Run unconditionally after every EPG fetch attempt
    (304, error, or success alike), so retention holds even when nothing new
    was parsed."""
    cutoff = ingest._to_iso(ingest._to_datetime(now) - timedelta(days=_RETENTION_DAYS))
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "DELETE FROM programme WHERE epg_source_id = ? AND end < ?",
            (epg_source_id, cutoff),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def match_channels(conn, provider_id):
    epg_source_row = conn.execute(
        "SELECT id FROM epg_source WHERE provider_id = ?", (provider_id,)
    ).fetchone()

    ids = set()
    name_map = {}
    epg_source_id = epg_source_row[0] if epg_source_row else None
    if epg_source_id is not None:
        for xmltv_channel_id, normalised_name in conn.execute(
            "SELECT xmltv_channel_id, normalised_name FROM epg_channel "
            "WHERE epg_source_id = ? ORDER BY xmltv_channel_id",
            (epg_source_id,),
        ).fetchall():
            ids.add(xmltv_channel_id)
            if normalised_name and normalised_name not in name_map:
                name_map[normalised_name] = xmltv_channel_id

    rows = conn.execute(
        "SELECT id, epg_channel_id, normalised_name FROM channel WHERE provider_id = ?",
        (provider_id,),
    ).fetchall()

    updates = []
    for channel_id, epg_channel_id, normalised_name in rows:
        candidate = strip_source_suffix(epg_channel_id)
        if candidate and candidate in ids:
            resolved = candidate
        else:
            resolved = name_map.get(normalised_name)
        updates.append((resolved, channel_id))

    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.executemany(
            "UPDATE channel SET epg_channel_id = ? WHERE id = ?", updates
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
