# -*- coding: utf-8 -*-
"""Fetch playlist text from an HTTP(S) URL or a local file path.

Error catalogue raised as `FetchError(message)`: `Unreachable`, `Timed out`,
`File not found`, `HTTP <code>`, `Playlist too large`.
"""
import os

try:
    from urllib.request import Request, urlopen, build_opener, HTTPRedirectHandler
    from urllib.error import HTTPError, URLError
    from urllib.parse import urlparse, urljoin
except ImportError:  # pragma: no cover - Python 2 fallback, unused on target
    from urllib2 import Request, urlopen, HTTPError, URLError, build_opener, HTTPRedirectHandler
    from urlparse import urlparse, urljoin

# Playlists are read fully into memory; cap how much we'll pull from an
# untrusted HTTP response or local file.
MAX_PLAYLIST_BYTES = 32 * 1024 * 1024

# Some Xtream Codes panels return HTTP 403 to urllib's default User-Agent;
# always send a real one.
DEFAULT_USER_AGENT = 'Kodimate/0.0.1'


ERROR_UNREACHABLE = "Unreachable"
ERROR_LOGIN_REJECTED = "Login rejected"
ERROR_NOT_XTREAM = "Not an Xtream server"
ERROR_NOT_M3U = "Not an M3U playlist"
ERROR_TIMED_OUT = "Timed out"
ERROR_FILE_NOT_FOUND = "File not found"


def http_error(code):
    return "HTTP {0}".format(code)


class FetchError(Exception):
    pass


def _read_local(path):
    if not os.path.isfile(path):
        raise FetchError(ERROR_FILE_NOT_FOUND)
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

    headers = {'User-Agent': user_agent if user_agent else DEFAULT_USER_AGENT}
    request = Request(source, headers=headers)
    try:
        response = urlopen(request, timeout=timeout)
    except HTTPError as exc:
        raise FetchError(http_error(exc.code))
    except URLError as exc:
        if isinstance(getattr(exc, 'reason', None), Exception) and 'timed out' in str(exc.reason).lower():
            raise FetchError(ERROR_TIMED_OUT)
        raise FetchError(ERROR_UNREACHABLE)
    except Exception:
        raise FetchError(ERROR_UNREACHABLE)

    try:
        raw = response.read(MAX_PLAYLIST_BYTES + 1)
        charset = response.headers.get_content_charset() if hasattr(response, 'headers') else None
    finally:
        response.close()
    if len(raw) > MAX_PLAYLIST_BYTES:
        raise FetchError("Playlist too large")
    return raw.decode(charset or 'utf-8', errors='replace')


class StreamResponse(object):
    def __init__(self, stream=None, etag=None, last_modified=None, not_modified=False):
        self.stream = stream
        self.etag = etag
        self.last_modified = last_modified
        self.not_modified = not_modified


def open_stream(source, user_agent=None, etag=None, last_modified=None, timeout=20):
    if source.startswith('file://'):
        return _open_local_stream(source[len('file://'):])

    if not source.startswith('http://') and not source.startswith('https://'):
        return _open_local_stream(source)

    headers = {'User-Agent': user_agent if user_agent else DEFAULT_USER_AGENT}
    if etag:
        headers['If-None-Match'] = etag
    if last_modified:
        headers['If-Modified-Since'] = last_modified
    request = Request(source, headers=headers)
    try:
        response = urlopen(request, timeout=timeout)
    except HTTPError as exc:
        if exc.code == 304:
            return StreamResponse(not_modified=True)
        raise FetchError(http_error(exc.code))
    except URLError as exc:
        if isinstance(getattr(exc, 'reason', None), Exception) and 'timed out' in str(exc.reason).lower():
            raise FetchError(ERROR_TIMED_OUT)
        raise FetchError(ERROR_UNREACHABLE)
    except Exception:
        raise FetchError(ERROR_UNREACHABLE)

    return StreamResponse(
        stream=response,
        etag=response.headers.get('ETag'),
        last_modified=response.headers.get('Last-Modified'),
    )


# Headers that must not be replayed to a different host than the one the
# probe originally targeted (session cookies, auth tokens, CORS origin).
_CROSS_ORIGIN_SENSITIVE_HEADERS = ('Cookie', 'Authorization', 'Origin')


class _SafeRedirectHandler(HTTPRedirectHandler):
    """HTTPRedirectHandler that strips credential-bearing headers when a
    redirect points at a different host (channel headers such as Cookie/
    Authorization/Origin must not be replayed cross-origin)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new_request = HTTPRedirectHandler.redirect_request(
            self, req, fp, code, msg, headers, newurl
        )
        if new_request is None:
            return None
        if urlparse(newurl).netloc != urlparse(req.full_url).netloc:
            for header_name in _CROSS_ORIGIN_SENSITIVE_HEADERS:
                new_request.remove_header(header_name)
        return new_request


def probe_stream(url, headers=None, timeout=5):
    """Out-of-band Range GET used to classify a playback start failure.

    Returns the int HTTP status on success (or from an HTTPError), the
    string 'timeout' on a socket timeout, or 'error' on any other failure
    (including a non-http(s) URL, which is never followed).
    """
    if urlparse(url).scheme not in ('http', 'https'):
        return 'error'
    request_headers = {'User-Agent': DEFAULT_USER_AGENT, 'Range': 'bytes=0-0'}
    if headers:
        request_headers.update(headers)
    request = Request(url, headers=request_headers)
    opener = build_opener(_SafeRedirectHandler)
    try:
        response = opener.open(request, timeout=timeout)
    except HTTPError as exc:
        return exc.code
    except URLError as exc:
        if isinstance(getattr(exc, 'reason', None), Exception) and 'timed out' in str(exc.reason).lower():
            return 'timeout'
        return 'error'
    except Exception:
        return 'error'
    try:
        return response.getcode()
    finally:
        response.close()


_REDIRECT_CODES = (301, 302, 303, 307, 308)


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def resolve_redirect(url, headers=None, timeout=3):
    """Follow one redirect out-of-band to learn its tokenised target URL,
    without ever fetching the target's body. Returns `url` unchanged on a
    non-redirect response, a redirect with no Location, or any error."""
    request_headers = dict(headers) if headers else {}
    if 'User-Agent' not in request_headers:
        request_headers['User-Agent'] = DEFAULT_USER_AGENT
    request = Request(url, headers=request_headers)
    opener = build_opener(_NoRedirectHandler)
    try:
        response = opener.open(request, timeout=timeout)
    except HTTPError as exc:
        try:
            if exc.code in _REDIRECT_CODES:
                location = exc.headers.get('Location') if exc.headers else None
                if location:
                    target = urljoin(url, location)
                    if urlparse(target).scheme in ('http', 'https') and '|' not in target:
                        return target
            return url
        finally:
            try:
                exc.close()
            except Exception:
                pass
    except Exception:
        return url
    try:
        return url
    finally:
        response.close()


def _open_local_stream(path):
    if not os.path.isfile(path):
        raise FetchError(ERROR_FILE_NOT_FOUND)
    return StreamResponse(stream=open(path, 'rb'))
