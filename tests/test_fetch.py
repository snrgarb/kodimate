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
