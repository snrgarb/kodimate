# -*- coding: utf-8 -*-
"""Fetch playlist text from an HTTP(S) URL or a local file path.

Error catalogue raised as `FetchError(message)`: `Unreachable`, `Timed out`,
`File not found`, `HTTP <code>`, `Playlist too large`.
"""
import os

try:
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError
except ImportError:  # pragma: no cover - Python 2 fallback, unused on target
    from urllib2 import Request, urlopen, HTTPError, URLError

# Playlists are read fully into memory; cap how much we'll pull from an
# untrusted HTTP response or local file.
MAX_PLAYLIST_BYTES = 32 * 1024 * 1024


class FetchError(Exception):
    pass


def _read_local(path):
    if not os.path.isfile(path):
        raise FetchError("File not found")
    with open(path, 'rb') as f:
        raw = f.read(MAX_PLAYLIST_BYTES + 1)
    if len(raw) > MAX_PLAYLIST_BYTES:
        raise FetchError("Playlist too large")
    return raw.decode('utf-8', errors='replace')


def fetch_playlist(source, user_agent=None, timeout=20):
    if source.startswith('file://'):
        return _read_local(source[len('file://'):])

    if not source.startswith('http://') and not source.startswith('https://'):
        return _read_local(source)

    headers = {'User-Agent': user_agent} if user_agent else {}
    request = Request(source, headers=headers)
    try:
        response = urlopen(request, timeout=timeout)
    except HTTPError as exc:
        raise FetchError("HTTP {0}".format(exc.code))
    except URLError as exc:
        if isinstance(getattr(exc, 'reason', None), Exception) and 'timed out' in str(exc.reason).lower():
            raise FetchError("Timed out")
        raise FetchError("Unreachable")
    except Exception:
        raise FetchError("Unreachable")

    try:
        raw = response.read(MAX_PLAYLIST_BYTES + 1)
        charset = response.headers.get_content_charset() if hasattr(response, 'headers') else None
    finally:
        response.close()
    if len(raw) > MAX_PLAYLIST_BYTES:
        raise FetchError("Playlist too large")
    return raw.decode(charset or 'utf-8', errors='replace')
