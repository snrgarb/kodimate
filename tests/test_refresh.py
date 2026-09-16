# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

from kodimate import db, fetch, refresh

_BASIC = '#EXTM3U\n#EXTINF:-1 tvg-id="one",Chan\nhttp://example.com/one\n'


class FakeProps(object):
    def __init__(self):
        self._values = {}

    def get(self, key):
        return self._values.get(key, '')

    def set(self, key, value):
        self._values[key] = value


class FakeNotify(object):
    def __init__(self):
        self.calls = []

    def __call__(self, generation, provider_ids):
        self.calls.append((generation, provider_ids))


def _make_conn(tmp_path):
    return db.open_db(str(tmp_path / 'k.db'))


def _add_provider(conn, id, kind='m3u', enabled=1, deleted_at=None, m3u_url='http://x/list.m3u'):
    conn.execute(
        "INSERT INTO provider (id, kind, name, enabled, deleted_at, m3u_url) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (id, kind, 'P{0}'.format(id), enabled, deleted_at, m3u_url),
    )


def _no_startup_settings(**overrides):
    settings = {'refresh_on_startup': False, 'refresh_interval_hours': 12}
    settings.update(overrides)
    return settings


def test_manual_refresh_ok(tmp_path):
    conn = _make_conn(tmp_path)
    _add_provider(conn, 3)
    props = FakeProps()
    notify = FakeNotify()
    props.set('refresh_request', '3;ui')

    seen_refreshing_during_fetch = {}

    def fetcher(source, user_agent):
        seen_refreshing_during_fetch['value'] = props.get('refreshing')
        return _BASIC

    svc = refresh.RefreshService(
        conn, props, notify, fetcher=fetcher,
        now=lambda: datetime(2024, 1, 1),
        settings=_no_startup_settings(),
    )
    svc.tick()

    assert seen_refreshing_during_fetch['value'] == '3'
    assert props.get('refreshing') == ''
    assert props.get('db_generation') == '1'
    assert props.get('refresh_result.3') == 'ok'
    assert notify.calls == [(1, [3])]


def test_manual_refresh_failure(tmp_path):
    conn = _make_conn(tmp_path)
    _add_provider(conn, 3)
    props = FakeProps()
    props.set('refresh_request', '3;ui')

    def fetcher(source, user_agent):
        raise fetch.FetchError("Unreachable")

    svc = refresh.RefreshService(
        conn, props, FakeNotify(), fetcher=fetcher,
        now=lambda: datetime(2024, 1, 1),
        settings=_no_startup_settings(),
    )
    svc.tick()

    assert props.get('refresh_result.3').startswith('error:')
    row = conn.execute("SELECT last_error, last_refresh_at FROM provider WHERE id = 3").fetchone()
    assert row[0] == 'Unreachable'
    assert row[1] is None
    assert props.get('db_generation') == ''


def test_non_numeric_request_tokens_are_skipped(tmp_path):
    conn = _make_conn(tmp_path)
    _add_provider(conn, 3)
    props = FakeProps()
    props.set('refresh_request', '3,abc,;ui')

    svc = refresh.RefreshService(
        conn, props, FakeNotify(), fetcher=lambda s, u: _BASIC,
        now=lambda: datetime(2024, 1, 1),
        settings=_no_startup_settings(),
    )
    svc._consume_request()

    assert [pid for pid, _ in svc._queue] == [3]


def test_all_enqueues_only_enabled_non_deleted(tmp_path):
    conn = _make_conn(tmp_path)
    _add_provider(conn, 1, enabled=1)
    _add_provider(conn, 2, enabled=0)
    _add_provider(conn, 3, enabled=1, deleted_at='2024-01-01T00:00:00Z')
    props = FakeProps()
    props.set('refresh_request', 'all')

    svc = refresh.RefreshService(
        conn, props, FakeNotify(), fetcher=lambda s, u: _BASIC,
        now=lambda: datetime(2024, 1, 1),
        settings=_no_startup_settings(),
    )
    svc._consume_request()

    assert [pid for pid, _ in svc._queue] == [1]


def test_duplicate_requests_not_queued_twice(tmp_path):
    conn = _make_conn(tmp_path)
    _add_provider(conn, 1)
    props = FakeProps()
    svc = refresh.RefreshService(
        conn, props, FakeNotify(), fetcher=lambda s, u: _BASIC,
        now=lambda: datetime(2024, 1, 1),
        settings=_no_startup_settings(),
    )
    props.set('refresh_request', '1')
    svc._consume_request()
    props.set('refresh_request', '1')
    svc._consume_request()

    assert [pid for pid, _ in svc._queue] == [1]


def test_disabled_provider_skipped(tmp_path):
    conn = _make_conn(tmp_path)
    _add_provider(conn, 1, enabled=0)
    props = FakeProps()
    props.set('refresh_request', '1;ui')

    svc = refresh.RefreshService(
        conn, props, FakeNotify(), fetcher=lambda s, u: _BASIC,
        now=lambda: datetime(2024, 1, 1),
        settings=_no_startup_settings(),
    )
    svc.tick()

    assert props.get('refresh_result.1') == ''
    assert props.get('db_generation') == ''


def test_config_version_bump_discards_and_requeues(tmp_path):
    conn = _make_conn(tmp_path)
    _add_provider(conn, 1)
    props = FakeProps()
    props.set('refresh_request', '1;ui')

    def fetcher(source, user_agent):
        # Simulate the script editing the provider mid-fetch.
        conn.execute("UPDATE provider SET config_version = config_version + 1 WHERE id = 1")
        return _BASIC

    svc = refresh.RefreshService(
        conn, props, FakeNotify(), fetcher=fetcher,
        now=lambda: datetime(2024, 1, 1),
        settings=_no_startup_settings(),
    )
    svc.tick()

    assert conn.execute("SELECT COUNT(*) FROM channel WHERE provider_id = 1").fetchone()[0] == 0
    assert [pid for pid, _ in svc._queue] == [1]
    assert props.get('db_generation') == ''


def test_startup_sweep_enqueues_all_when_enabled(tmp_path):
    conn = _make_conn(tmp_path)
    _add_provider(conn, 1)
    _add_provider(conn, 2)
    props = FakeProps()

    svc = refresh.RefreshService(
        conn, props, FakeNotify(), fetcher=lambda s, u: _BASIC,
        now=lambda: datetime(2024, 1, 1),
        settings={'refresh_on_startup': True, 'refresh_interval_hours': 12},
    )
    svc.on_start()
    svc.tick()

    # One was popped off and refreshed this tick; the other stays queued.
    assert len(svc._queue) == 1


def test_interval_elapsed_enqueues_all_again(tmp_path):
    conn = _make_conn(tmp_path)
    _add_provider(conn, 1)
    props = FakeProps()
    clock = {'t': datetime(2024, 1, 1, 0, 0, 0)}

    svc = refresh.RefreshService(
        conn, props, FakeNotify(), fetcher=lambda s, u: _BASIC,
        now=lambda: clock['t'],
        settings={'refresh_on_startup': False, 'refresh_interval_hours': 12},
    )
    svc.tick()  # startup tick: refresh_on_startup False, nothing queued/refreshed
    assert props.get('db_generation') == ''

    clock['t'] = clock['t'] + timedelta(hours=13)
    svc.tick()  # interval elapsed -> enqueues + refreshes provider 1
    assert props.get('db_generation') == '1'


def test_deleted_provider_cascaded_at_on_start(tmp_path):
    conn = _make_conn(tmp_path)
    _add_provider(conn, 1, deleted_at='2024-01-01T00:00:00Z')
    conn.execute("INSERT INTO channel_group (provider_id, name) VALUES (1, 'G')")
    conn.execute(
        "INSERT INTO channel (provider_id, channel_key, name, normalised_name, stream_url) "
        "VALUES (1, 'k', 'n', 'n', 'http://x')"
    )
    conn.execute("INSERT INTO channel_override (provider_id, channel_key) VALUES (1, 'k')")
    props = FakeProps()

    svc = refresh.RefreshService(conn, props, FakeNotify(), settings=_no_startup_settings())
    svc.on_start()

    assert conn.execute("SELECT COUNT(*) FROM provider WHERE id = 1").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM channel WHERE provider_id = 1").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM channel_group WHERE provider_id = 1").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM channel_override WHERE provider_id = 1").fetchone()[0] == 0
    assert props.get('db_generation') == '1'
    assert props.get('refreshing') == ''
