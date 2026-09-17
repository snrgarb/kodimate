# -*- coding: utf-8 -*-
from kodimate import fetch


class _FakeHeaders(object):
    def get_content_charset(self):
        return None

    def get(self, key):
        return None


class _FakeResponse(object):
    headers = _FakeHeaders()

    def read(self, n):
        return b''

    def close(self):
        pass


def _capture_request(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured['request'] = request
        return _FakeResponse()

    monkeypatch.setattr(fetch, 'urlopen', fake_urlopen)
    return captured


def test_fetch_playlist_uses_default_user_agent_when_none_given(monkeypatch):
    captured = _capture_request(monkeypatch)

    fetch.fetch_playlist('http://xc.example/playlist.m3u', user_agent=None)

    assert captured['request'].get_header('User-agent') == fetch.DEFAULT_USER_AGENT


def test_fetch_playlist_uses_given_user_agent(monkeypatch):
    captured = _capture_request(monkeypatch)

    fetch.fetch_playlist('http://xc.example/playlist.m3u', user_agent='SomeAgent/1.0')

    assert captured['request'].get_header('User-agent') == 'SomeAgent/1.0'


def test_open_stream_sends_conditional_headers_when_given(monkeypatch):
    captured = _capture_request(monkeypatch)

    fetch.open_stream(
        'http://xc.example/xmltv.php', etag='"abc"', last_modified='Mon, 01 Jan 2024 00:00:00 GMT',
    )

    assert captured['request'].get_header('If-none-match') == '"abc"'
    assert captured['request'].get_header('If-modified-since') == 'Mon, 01 Jan 2024 00:00:00 GMT'


def test_open_stream_omits_conditional_headers_when_none_given(monkeypatch):
    captured = _capture_request(monkeypatch)

    fetch.open_stream('http://xc.example/xmltv.php')

    assert captured['request'].get_header('If-none-match') is None
    assert captured['request'].get_header('If-modified-since') is None


def test_open_stream_304_yields_not_modified(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise fetch.HTTPError(request.full_url, 304, 'Not Modified', {}, None)

    monkeypatch.setattr(fetch, 'urlopen', fake_urlopen)

    resp = fetch.open_stream('http://xc.example/xmltv.php', etag='"abc"')

    assert resp.not_modified is True
    assert resp.stream is None


def test_open_stream_captures_etag_and_last_modified(monkeypatch):
    class _Headers(object):
        def get(self, key):
            return {'ETag': '"xyz"', 'Last-Modified': 'Tue, 02 Jan 2024 00:00:00 GMT'}.get(key)

    class _Response(_FakeResponse):
        headers = _Headers()

    def fake_urlopen(request, timeout=None):
        return _Response()

    monkeypatch.setattr(fetch, 'urlopen', fake_urlopen)

    resp = fetch.open_stream('http://xc.example/xmltv.php')

    assert resp.not_modified is False
    assert resp.etag == '"xyz"'
    assert resp.last_modified == 'Tue, 02 Jan 2024 00:00:00 GMT'


class _FakeStatusResponse(_FakeResponse):
    def __init__(self, code):
        self._code = code

    def getcode(self):
        return self._code


class _FakeOpener(object):
    """Stand-in for build_opener(...)'s result: probe_stream calls
    opener.open(request, timeout=...) rather than urlopen() directly, so
    tests patch fetch.build_opener to return one of these."""

    def __init__(self, fn):
        self._fn = fn

    def open(self, request, timeout=None):
        return self._fn(request, timeout=timeout)


def _patch_opener(monkeypatch, fn):
    monkeypatch.setattr(fetch, 'build_opener', lambda *handlers: _FakeOpener(fn))


def test_probe_stream_sends_range_header(monkeypatch):
    captured = {}

    def fake_open(request, timeout=None):
        captured['request'] = request
        return _FakeStatusResponse(200)

    _patch_opener(monkeypatch, fake_open)

    fetch.probe_stream('http://xc.example/live/u/p/1.ts', headers={'User-Agent': 'X'})

    assert captured['request'].get_header('Range') == 'bytes=0-0'
    assert captured['request'].get_header('User-agent') == 'X'


def test_probe_stream_returns_status_on_success(monkeypatch):
    def fake_open(request, timeout=None):
        return _FakeStatusResponse(200)

    _patch_opener(monkeypatch, fake_open)

    assert fetch.probe_stream('http://xc.example/live/u/p/1.ts') == 200


def test_probe_stream_returns_http_error_code(monkeypatch):
    def fake_open(request, timeout=None):
        raise fetch.HTTPError(request.full_url, 403, 'Forbidden', {}, None)

    _patch_opener(monkeypatch, fake_open)

    assert fetch.probe_stream('http://xc.example/live/u/p/1.ts') == 403


def test_probe_stream_returns_timeout(monkeypatch):
    def fake_open(request, timeout=None):
        raise fetch.URLError(TimeoutError('timed out'))

    _patch_opener(monkeypatch, fake_open)

    assert fetch.probe_stream('http://xc.example/live/u/p/1.ts') == 'timeout'


def test_probe_stream_returns_error_on_other_failure(monkeypatch):
    def fake_open(request, timeout=None):
        raise fetch.URLError('connection refused')

    _patch_opener(monkeypatch, fake_open)

    assert fetch.probe_stream('http://xc.example/live/u/p/1.ts') == 'error'


def test_probe_stream_rejects_non_http_scheme_without_opening(monkeypatch):
    def fail_if_called(request, timeout=None):
        raise AssertionError('urlopen/opener.open must not be called for a non-http(s) URL')

    monkeypatch.setattr(fetch, 'urlopen', fail_if_called)
    _patch_opener(monkeypatch, fail_if_called)

    assert fetch.probe_stream('file:///etc/hosts') == 'error'


def test_redirect_handler_strips_credentials_on_cross_host_redirect():
    request = fetch.Request(
        'http://origin.example/live/u/p/1.ts',
        headers={
            'User-Agent': 'UA', 'Referer': 'http://origin.example/x',
            'Cookie': 'session=abc', 'Authorization': 'Bearer token',
            'Origin': 'http://origin.example', 'Range': 'bytes=0-0',
        },
    )
    handler = fetch._SafeRedirectHandler()

    new_request = handler.redirect_request(
        request, None, 302, 'Found', {}, 'http://other.example/stream.ts',
    )

    assert new_request.get_header('Cookie') is None
    assert new_request.get_header('Authorization') is None
    assert new_request.get_header('Origin') is None
    assert new_request.get_header('User-agent') == 'UA'
    assert new_request.get_header('Referer') == 'http://origin.example/x'
    assert new_request.get_header('Range') == 'bytes=0-0'


class _FakeRedirectHeaders(object):
    def __init__(self, location):
        self._location = location

    def get(self, key):
        return self._location if key == 'Location' else None


def test_resolve_redirect_returns_location_for_302(monkeypatch):
    def fake_open(request, timeout=None):
        raise fetch.HTTPError(
            request.full_url, 302, 'Found',
            _FakeRedirectHeaders('http://edge.example/live/play/tok/1'), None,
        )

    _patch_opener(monkeypatch, fake_open)

    result = fetch.resolve_redirect('https://xc.example/live/u/p/1.ts')

    assert result == 'http://edge.example/live/play/tok/1'


def test_resolve_redirect_joins_relative_location(monkeypatch):
    def fake_open(request, timeout=None):
        raise fetch.HTTPError(
            request.full_url, 302, 'Found', _FakeRedirectHeaders('/play/tok/1'), None,
        )

    _patch_opener(monkeypatch, fake_open)

    result = fetch.resolve_redirect('https://xc.example/live/u/p/1.ts')

    assert result == 'https://xc.example/play/tok/1'


def test_resolve_redirect_returns_original_url_on_200(monkeypatch):
    def fake_open(request, timeout=None):
        return _FakeStatusResponse(200)

    _patch_opener(monkeypatch, fake_open)

    result = fetch.resolve_redirect('https://xc.example/live/u/p/1.ts')

    assert result == 'https://xc.example/live/u/p/1.ts'


def test_resolve_redirect_returns_original_url_on_http_error(monkeypatch):
    def fake_open(request, timeout=None):
        raise fetch.HTTPError(request.full_url, 404, 'Not Found', {}, None)

    _patch_opener(monkeypatch, fake_open)

    result = fetch.resolve_redirect('https://xc.example/live/u/p/1.ts')

    assert result == 'https://xc.example/live/u/p/1.ts'


def test_resolve_redirect_returns_original_url_on_timeout(monkeypatch):
    def fake_open(request, timeout=None):
        raise fetch.URLError(TimeoutError('timed out'))

    _patch_opener(monkeypatch, fake_open)

    result = fetch.resolve_redirect('https://xc.example/live/u/p/1.ts')

    assert result == 'https://xc.example/live/u/p/1.ts'


def test_resolve_redirect_returns_original_url_when_no_location(monkeypatch):
    def fake_open(request, timeout=None):
        raise fetch.HTTPError(
            request.full_url, 302, 'Found', _FakeRedirectHeaders(None), None,
        )

    _patch_opener(monkeypatch, fake_open)

    result = fetch.resolve_redirect('https://xc.example/live/u/p/1.ts')

    assert result == 'https://xc.example/live/u/p/1.ts'


def test_resolve_redirect_rejects_non_http_scheme_location(monkeypatch):
    def fake_open(request, timeout=None):
        raise fetch.HTTPError(
            request.full_url, 302, 'Found', _FakeRedirectHeaders('file:///etc/passwd'), None,
        )

    _patch_opener(monkeypatch, fake_open)

    result = fetch.resolve_redirect('https://xc.example/live/u/p/1.ts')

    assert result == 'https://xc.example/live/u/p/1.ts'


def test_resolve_redirect_rejects_location_with_pipe_char(monkeypatch):
    def fake_open(request, timeout=None):
        raise fetch.HTTPError(
            request.full_url, 302, 'Found',
            _FakeRedirectHeaders('http://edge.example/x|User-Agent=evil'), None,
        )

    _patch_opener(monkeypatch, fake_open)

    result = fetch.resolve_redirect('https://xc.example/live/u/p/1.ts')

    assert result == 'https://xc.example/live/u/p/1.ts'


def test_resolve_redirect_closes_response_on_redirect(monkeypatch):
    closed = []

    def fake_open(request, timeout=None):
        exc = fetch.HTTPError(
            request.full_url, 302, 'Found', _FakeRedirectHeaders('http://edge.example/x'), None,
        )
        exc.close = lambda: closed.append(True)
        raise exc

    _patch_opener(monkeypatch, fake_open)

    fetch.resolve_redirect('https://xc.example/live/u/p/1.ts')

    assert closed == [True]


def test_redirect_handler_keeps_credentials_on_same_host_redirect():
    request = fetch.Request(
        'http://origin.example/live/u/p/1.ts',
        headers={'Cookie': 'session=abc', 'Authorization': 'Bearer token'},
    )
    handler = fetch._SafeRedirectHandler()

    new_request = handler.redirect_request(
        request, None, 302, 'Found', {}, 'http://origin.example/other.ts',
    )

    assert new_request.get_header('Cookie') == 'session=abc'
    assert new_request.get_header('Authorization') == 'Bearer token'
