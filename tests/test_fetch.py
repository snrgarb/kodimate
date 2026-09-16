# -*- coding: utf-8 -*-
from kodimate import fetch


class _FakeHeaders(object):
    def get_content_charset(self):
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
