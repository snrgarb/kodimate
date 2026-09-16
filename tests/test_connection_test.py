# -*- coding: utf-8 -*-
import os

import pytest

from kodimate import connection_test, fetch, m3u

_FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')


def _read_fixture(name):
    with open(os.path.join(_FIXTURES, name), 'r') as f:
        return f.read()


def test_m3u_test_returns_channel_count_and_epg_declared():
    text = "#EXTM3U url-tvg=\"http://epg\"\n#EXTINF:-1,A\nhttp://x/a\n#EXTINF:-1,B\nhttp://x/b\n"

    def fetcher(url, user_agent):
        assert url == 'http://x/list.m3u'
        return text

    result = connection_test.test_connection(
        'm3u', {'m3u_url': 'http://x/list.m3u'}, fetcher
    )
    assert result == {'channel_count': 2, 'epg_declared': True}


def test_m3u_test_epg_not_declared():
    text = "#EXTM3U\n#EXTINF:-1,A\nhttp://x/a\n"

    def fetcher(url, user_agent):
        return text

    result = connection_test.test_connection('m3u', {'m3u_url': 'http://x/list.m3u'}, fetcher)
    assert result['epg_declared'] is False


def test_m3u_test_propagates_m3u_error():
    def fetcher(url, user_agent):
        return "not a playlist"

    with pytest.raises(m3u.M3UError, match=fetch.ERROR_NOT_M3U):
        connection_test.test_connection('m3u', {'m3u_url': 'http://x/list.m3u'}, fetcher)


def test_m3u_test_propagates_fetch_error():
    def fetcher(url, user_agent):
        raise fetch.FetchError(fetch.ERROR_UNREACHABLE)

    with pytest.raises(fetch.FetchError, match=fetch.ERROR_UNREACHABLE):
        connection_test.test_connection('m3u', {'m3u_url': 'http://x/list.m3u'}, fetcher)


def test_xtream_test_returns_summary():
    def fetcher(url, user_agent):
        if 'get_live_categories' in url:
            return _read_fixture('xtream_categories.json')
        return _read_fixture('xtream_account.json')

    result = connection_test.test_connection(
        'xtream',
        {'xtream_host': 'http://xc.example', 'xtream_username': 'user', 'xtream_password': 'pass'},
        fetcher,
    )
    assert result == {
        'status': 'Active',
        'account_expires_at': '2025-01-01T00:00:00Z',
        'max_connections': 1,
        'active_connections': 0,
        'allowed_output_formats': ['m3u8', 'ts'],
        'live_category_count': 2,
    }


def test_xtream_test_propagates_login_rejected():
    def fetcher(url, user_agent):
        return _read_fixture('xtream_account_banned.json')

    with pytest.raises(fetch.FetchError, match=fetch.ERROR_LOGIN_REJECTED):
        connection_test.test_connection(
            'xtream',
            {'xtream_host': 'http://xc.example', 'xtream_username': 'user', 'xtream_password': 'pass'},
            fetcher,
        )


# -- wait_for_worker -----------------------------------------------------

class _FakeWorker(object):
    def __init__(self, alive_for):
        self._alive_for = alive_for
        self._calls = 0

    def is_alive(self):
        self._calls += 1
        return self._calls <= self._alive_for


class _FakeProgress(object):
    def __init__(self, cancel_after=None):
        self._cancel_after = cancel_after
        self._polls = 0

    def iscanceled(self):
        self._polls += 1
        return self._cancel_after is not None and self._polls >= self._cancel_after


class _FakeClock(object):
    def __init__(self, values):
        self._values = list(values)

    def __call__(self):
        return self._values.pop(0) if len(self._values) > 1 else self._values[0]


def test_wait_for_worker_returns_done_when_worker_finishes():
    worker = _FakeWorker(alive_for=2)
    progress = _FakeProgress()
    clock = _FakeClock([0, 0.1, 0.2])
    result = connection_test.wait_for_worker(
        worker, progress, sleep=lambda s: None, clock=clock, timeout=15
    )
    assert result == 'done'


def test_wait_for_worker_returns_cancelled_when_progress_cancelled():
    worker = _FakeWorker(alive_for=100)
    progress = _FakeProgress(cancel_after=2)
    clock = _FakeClock([0] * 10)
    result = connection_test.wait_for_worker(
        worker, progress, sleep=lambda s: None, clock=clock, timeout=15
    )
    assert result == 'cancelled'


def test_wait_for_worker_returns_timeout_after_deadline():
    worker = _FakeWorker(alive_for=100)
    progress = _FakeProgress()
    clock = _FakeClock([0, 20])
    result = connection_test.wait_for_worker(
        worker, progress, sleep=lambda s: None, clock=clock, timeout=15
    )
    assert result == 'timeout'
