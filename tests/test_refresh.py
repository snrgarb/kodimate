# -*- coding: utf-8 -*-
import io
from datetime import datetime, timedelta

import pytest

from kodimate import db, fetch, refresh

_BASIC = '#EXTM3U\n#EXTINF:-1 tvg-id="one",Chan\nhttp://example.com/one\n'
_WITH_EPG = (
    '#EXTM3U url-tvg="http://epg.example/guide.xml"\n'
    '#EXTINF:-1 tvg-id="bbcnews.uk",BBC News HD\nhttp://example.com/one\n'
)
_XMLTV = (
    '<tv><channel id="bbcnews.uk"><display-name>BBC News</display-name></channel>'
    '<programme start="20240101120000 +0000" stop="20240101123000 +0000" '
    'channel="bbcnews.uk"><title>News</title></programme></tv>'
)
_XC_SHAPED_M3U = (
    '#EXTM3U\n#EXTINF:-1 tvg-id="one",Chan\nhttp://xc.example/live/user/pass/100.ts\n'
)
_XC_ACCOUNT_JSON_WITH_TIMEZONE = (
    '{"user_info": {"auth": 1, "status": "Active"}, '
    '"server_info": {"timezone": "America/Toronto"}}'
)


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


def test_m3u_refresh_with_xc_shaped_channel_fetches_and_persists_server_timezone(tmp_path):
    conn = _make_conn(tmp_path)
    _add_provider(conn, 3)
    props = FakeProps()
    props.set('refresh_request', '3;ui')

    seen_sources = []

    def fetcher(source, user_agent):
        seen_sources.append(source)
        if 'player_api.php' in source:
            return _XC_ACCOUNT_JSON_WITH_TIMEZONE
        return _XC_SHAPED_M3U

    svc = refresh.RefreshService(
        conn, props, FakeNotify(), fetcher=fetcher,
        now=lambda: datetime(2024, 1, 1),
        settings=_no_startup_settings(),
    )
    svc.tick()

    assert props.get('refresh_result.3') == 'ok'
    row = conn.execute("SELECT server_timezone FROM provider WHERE id = 3").fetchone()
    assert row[0] == 'America/Toronto'
    player_api_calls = [s for s in seen_sources if 'player_api.php' in s]
    assert len(player_api_calls) == 1
    assert 'username=user' in player_api_calls[0] and 'password=pass' in player_api_calls[0]


def test_m3u_refresh_server_timezone_fetch_failure_is_non_fatal(tmp_path):
    conn = _make_conn(tmp_path)
    _add_provider(conn, 3)
    props = FakeProps()
    props.set('refresh_request', '3;ui')

    def fetcher(source, user_agent):
        if 'player_api.php' in source:
            return '<html>not json</html>'
        return _XC_SHAPED_M3U

    svc = refresh.RefreshService(
        conn, props, FakeNotify(), fetcher=fetcher,
        now=lambda: datetime(2024, 1, 1),
        settings=_no_startup_settings(),
    )
    svc.tick()

    assert props.get('refresh_result.3') == 'ok'
    row = conn.execute("SELECT server_timezone FROM provider WHERE id = 3").fetchone()
    assert row[0] is None


def test_m3u_refresh_non_xc_playlist_does_not_fetch_server_timezone(tmp_path):
    conn = _make_conn(tmp_path)
    _add_provider(conn, 3)
    props = FakeProps()
    props.set('refresh_request', '3;ui')

    seen_sources = []

    def fetcher(source, user_agent):
        seen_sources.append(source)
        return _BASIC

    svc = refresh.RefreshService(
        conn, props, FakeNotify(), fetcher=fetcher,
        now=lambda: datetime(2024, 1, 1),
        settings=_no_startup_settings(),
    )
    svc.tick()

    assert props.get('refresh_result.3') == 'ok'
    assert not any('player_api.php' in s for s in seen_sources)


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


def test_startup_sweep_skips_recently_refreshed_provider(tmp_path):
    conn = _make_conn(tmp_path)
    _add_provider(conn, 1)
    now = datetime(2024, 1, 1, 12, 0, 0)
    conn.execute(
        "UPDATE provider SET last_refresh_at = ? WHERE id = ?",
        (refresh._iso(now - timedelta(hours=1)), 1),
    )
    props = FakeProps()

    svc = refresh.RefreshService(
        conn, props, FakeNotify(), fetcher=lambda s, u: _BASIC,
        now=lambda: now,
        settings={'refresh_on_startup': True, 'refresh_interval_hours': 12},
    )
    svc.on_start()
    svc.tick()

    assert svc._queue == []
    assert props.get('db_generation') == '0'


def test_startup_sweep_enqueues_stale_provider(tmp_path):
    conn = _make_conn(tmp_path)
    _add_provider(conn, 1)
    now = datetime(2024, 1, 1, 12, 0, 0)
    conn.execute(
        "UPDATE provider SET last_refresh_at = ? WHERE id = ?",
        (refresh._iso(now - timedelta(hours=13)), 1),
    )
    props = FakeProps()

    svc = refresh.RefreshService(
        conn, props, FakeNotify(), fetcher=lambda s, u: _BASIC,
        now=lambda: now,
        settings={'refresh_on_startup': True, 'refresh_interval_hours': 12},
    )
    svc.on_start()
    svc.tick()

    assert props.get('db_generation') == '1'


def test_startup_sweep_enqueues_provider_with_no_prior_refresh(tmp_path):
    conn = _make_conn(tmp_path)
    _add_provider(conn, 1)
    props = FakeProps()

    svc = refresh.RefreshService(
        conn, props, FakeNotify(), fetcher=lambda s, u: _BASIC,
        now=lambda: datetime(2024, 1, 1),
        settings={'refresh_on_startup': True, 'refresh_interval_hours': 12},
    )
    svc.on_start()
    svc.tick()

    assert props.get('db_generation') == '1'


_XTREAM_ACCOUNT_JSON = (
    '{"user_info": {"auth": 1, "status": "Active", "exp_date": null, '
    '"max_connections": "1", "allowed_output_formats": ["ts"]}}'
)
_XTREAM_CATEGORIES_JSON = '[{"category_id": "5", "category_name": "News"}]'
_XTREAM_STREAMS_JSON = (
    '[{"num": "1", "name": "Chan", "stream_id": "100", "tv_archive": "0", '
    '"tv_archive_duration": "0"}]'
)


def _xtream_fetcher(source, user_agent):
    if 'action=get_live_categories' in source:
        return _XTREAM_CATEGORIES_JSON
    if 'action=get_live_streams' in source:
        return _XTREAM_STREAMS_JSON
    return _XTREAM_ACCOUNT_JSON


def test_manual_refresh_xtream_ok(tmp_path):
    conn = _make_conn(tmp_path)
    conn.execute(
        "INSERT INTO provider (id, kind, name, enabled, xtream_host, xtream_username, "
        "xtream_password) VALUES (3, 'xtream', 'P3', 1, 'http://xc.example', 'user', 'pass')"
    )
    props = FakeProps()
    props.set('refresh_request', '3;ui')

    seen_sources = []

    def counting_fetcher(source, user_agent):
        seen_sources.append(source)
        return _xtream_fetcher(source, user_agent)

    svc = refresh.RefreshService(
        conn, props, FakeNotify(), fetcher=counting_fetcher,
        now=lambda: datetime(2024, 1, 1),
        settings=_no_startup_settings(),
        opener=lambda source, user_agent, etag, last_modified: fetch.StreamResponse(not_modified=True),
    )
    svc.tick()

    assert props.get('refresh_result.3') == 'ok'
    channel = conn.execute("SELECT name FROM channel WHERE provider_id = 3").fetchone()
    assert channel == ('Chan',)
    stream_calls = [s for s in seen_sources if 'action=get_live_streams' in s]
    assert len(stream_calls) == 1


def test_xtream_malformed_account_yields_last_error_not_crash(tmp_path):
    conn = _make_conn(tmp_path)
    conn.execute(
        "INSERT INTO provider (id, kind, name, enabled, xtream_host, xtream_username, "
        "xtream_password) VALUES (3, 'xtream', 'P3', 1, 'http://xc.example', 'user', 'pass')"
    )
    props = FakeProps()
    props.set('refresh_request', '3;ui')

    svc = refresh.RefreshService(
        conn, props, FakeNotify(), fetcher=lambda source, user_agent: '<html>not json</html>',
        now=lambda: datetime(2024, 1, 1),
        settings=_no_startup_settings(),
    )
    svc.tick()

    assert props.get('refresh_result.3').startswith('error:')
    row = conn.execute("SELECT last_error FROM provider WHERE id = 3").fetchone()
    assert row[0]


def test_refresh_one_purges_soft_deleted_provider(tmp_path):
    conn = _make_conn(tmp_path)
    _add_provider(conn, 1, deleted_at='2024-01-01T00:00:00Z')
    epg_source_id = conn.execute(
        "INSERT INTO epg_source (provider_id) VALUES (1)"
    ).lastrowid
    conn.execute(
        "INSERT INTO programme (epg_source_id, xmltv_channel_id, start, end, title) "
        "VALUES (?, 'c', '2024-01-01T00:00:00Z', '2024-01-01T01:00:00Z', 'T')",
        (epg_source_id,),
    )
    conn.execute("INSERT INTO channel_group (provider_id, name) VALUES (1, 'G')")
    conn.execute(
        "INSERT INTO channel (provider_id, channel_key, name, normalised_name, stream_url) "
        "VALUES (1, 'k', 'n', 'n', 'http://x')"
    )
    conn.execute("INSERT INTO channel_override (provider_id, channel_key) VALUES (1, 'k')")
    props = FakeProps()
    notify = FakeNotify()
    props.set('refresh_request', '1')

    svc = refresh.RefreshService(conn, props, notify, settings=_no_startup_settings())
    svc.tick()

    assert conn.execute("SELECT COUNT(*) FROM provider WHERE id = 1").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM channel WHERE provider_id = 1").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM channel_group WHERE provider_id = 1").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM channel_override WHERE provider_id = 1").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM epg_source WHERE provider_id = 1").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM programme").fetchone()[0] == 0
    assert props.get('db_generation') == '1'
    assert notify.calls == [(1, [1])]


def test_config_version_changed_for_gone_provider_not_requeued(tmp_path):
    conn = _make_conn(tmp_path)
    _add_provider(conn, 1)
    props = FakeProps()
    props.set('refresh_request', '1;ui')

    def fetcher(source, user_agent):
        # Simulate the provider being deleted mid-fetch.
        conn.execute("DELETE FROM provider WHERE id = 1")
        return _BASIC

    svc = refresh.RefreshService(
        conn, props, FakeNotify(), fetcher=fetcher,
        now=lambda: datetime(2024, 1, 1),
        settings=_no_startup_settings(),
    )
    svc.tick()

    assert svc._queue == []


def test_epg_304_skips_parse_but_matching_still_runs(tmp_path):
    conn = _make_conn(tmp_path)
    _add_provider(conn, 1, m3u_url='http://x/list.m3u')
    props = FakeProps()
    props.set('refresh_request', '1;ui')

    opener_calls = []

    def opener(source, user_agent, etag, last_modified):
        opener_calls.append((source, etag, last_modified))
        return fetch.StreamResponse(not_modified=True)

    svc = refresh.RefreshService(
        conn, props, FakeNotify(), fetcher=lambda s, u: _WITH_EPG,
        now=lambda: datetime(2024, 1, 1),
        settings=_no_startup_settings(), opener=opener,
    )
    svc.tick()

    assert opener_calls == [('http://epg.example/guide.xml', None, None)]
    assert props.get('refresh_result.1') == 'ok'
    row = conn.execute(
        "SELECT last_error FROM provider WHERE id = 1"
    ).fetchone()
    assert row[0] is None
    channel = conn.execute(
        "SELECT epg_channel_id FROM channel WHERE provider_id = 1"
    ).fetchone()
    assert channel == (None,)  # matching ran, found nothing in epg_channel yet


def test_epg_opener_receives_stored_etag_and_last_modified(tmp_path):
    conn = _make_conn(tmp_path)
    _add_provider(conn, 1, m3u_url='http://x/list.m3u')
    conn.execute(
        "INSERT INTO epg_source (provider_id, url, etag, last_modified) "
        "VALUES (1, 'http://epg.example/guide.xml', '\"etag1\"', 'lm1')"
    )
    props = FakeProps()
    props.set('refresh_request', '1;ui')

    opener_calls = []

    def opener(source, user_agent, etag, last_modified):
        opener_calls.append((source, etag, last_modified))
        return fetch.StreamResponse(not_modified=True)

    svc = refresh.RefreshService(
        conn, props, FakeNotify(), fetcher=lambda s, u: _WITH_EPG,
        now=lambda: datetime(2024, 1, 1),
        settings=_no_startup_settings(), opener=opener,
    )
    svc.tick()

    assert opener_calls == [('http://epg.example/guide.xml', '"etag1"', 'lm1')]


def test_epg_fetch_error_leaves_channels_refreshed_but_records_last_error(tmp_path):
    conn = _make_conn(tmp_path)
    _add_provider(conn, 1, m3u_url='http://x/list.m3u')
    props = FakeProps()
    props.set('refresh_request', '1;ui')

    def opener(source, user_agent, etag, last_modified):
        raise fetch.FetchError('Unreachable')

    svc = refresh.RefreshService(
        conn, props, FakeNotify(), fetcher=lambda s, u: _WITH_EPG,
        now=lambda: datetime(2024, 1, 1),
        settings=_no_startup_settings(), opener=opener,
    )
    svc.tick()

    assert props.get('refresh_result.1') == 'ok'
    channel_count = conn.execute(
        "SELECT COUNT(*) FROM channel WHERE provider_id = 1"
    ).fetchone()[0]
    assert channel_count == 1
    row = conn.execute("SELECT last_error FROM provider WHERE id = 1").fetchone()
    assert row[0] == 'EPG: Unreachable'


def test_epg_fetch_error_message_is_preserved_in_last_error(tmp_path):
    conn = _make_conn(tmp_path)
    _add_provider(conn, 1, m3u_url='http://x/list.m3u')
    props = FakeProps()
    props.set('refresh_request', '1;ui')

    def opener(source, user_agent, etag, last_modified):
        raise fetch.FetchError('HTTP 404')

    svc = refresh.RefreshService(
        conn, props, FakeNotify(), fetcher=lambda s, u: _WITH_EPG,
        now=lambda: datetime(2024, 1, 1),
        settings=_no_startup_settings(), opener=opener,
    )
    svc.tick()

    row = conn.execute("SELECT last_error FROM provider WHERE id = 1").fetchone()
    assert row[0] == 'EPG: HTTP 404'


def test_retention_pruned_on_304_path(tmp_path):
    conn = _make_conn(tmp_path)
    _add_provider(conn, 1, m3u_url='http://x/list.m3u')
    epg_source_id = conn.execute(
        "INSERT INTO epg_source (provider_id, url) VALUES (1, 'http://epg.example/guide.xml')"
    ).lastrowid
    conn.execute(
        "INSERT INTO programme (epg_source_id, xmltv_channel_id, start, end, title) "
        "VALUES (?, 'bbcnews.uk', '2023-12-01T00:00:00Z', '2023-12-01T01:00:00Z', 'Old')",
        (epg_source_id,),
    )
    conn.execute(
        "INSERT INTO programme (epg_source_id, xmltv_channel_id, start, end, title) "
        "VALUES (?, 'bbcnews.uk', '2024-01-01T06:00:00Z', '2024-01-01T07:00:00Z', 'Recent')",
        (epg_source_id,),
    )
    props = FakeProps()
    props.set('refresh_request', '1;ui')

    def opener(source, user_agent, etag, last_modified):
        return fetch.StreamResponse(not_modified=True)

    svc = refresh.RefreshService(
        conn, props, FakeNotify(), fetcher=lambda s, u: _WITH_EPG,
        now=lambda: datetime(2024, 1, 8),
        settings=_no_startup_settings(), opener=opener,
    )
    svc.tick()

    titles = {row[0] for row in conn.execute(
        "SELECT title FROM programme WHERE epg_source_id = ?", (epg_source_id,)
    ).fetchall()}
    assert titles == {'Recent'}


def test_successful_epg_clears_last_error(tmp_path):
    conn = _make_conn(tmp_path)
    _add_provider(conn, 1, m3u_url='http://x/list.m3u')
    conn.execute("UPDATE provider SET last_error = 'EPG: Unreachable' WHERE id = 1")
    props = FakeProps()
    props.set('refresh_request', '1;ui')

    def opener(source, user_agent, etag, last_modified):
        return fetch.StreamResponse(stream=io.BytesIO(_XMLTV.encode('utf-8')))

    svc = refresh.RefreshService(
        conn, props, FakeNotify(), fetcher=lambda s, u: _WITH_EPG,
        now=lambda: datetime(2024, 1, 1),
        settings=_no_startup_settings(), opener=opener,
    )
    svc.tick()

    row = conn.execute("SELECT last_error FROM provider WHERE id = 1").fetchone()
    assert row[0] is None
    channel = conn.execute(
        "SELECT epg_channel_id FROM channel WHERE provider_id = 1"
    ).fetchone()
    assert channel == ('bbcnews.uk',)


def test_on_start_drops_precreated_programme_staging_table(tmp_path):
    conn = _make_conn(tmp_path)
    conn.execute(
        "CREATE TABLE programme_staging (epg_source_id INTEGER, xmltv_channel_id TEXT, "
        "start TEXT, end TEXT, title TEXT, subtitle TEXT, description TEXT, "
        "icon_url TEXT, category TEXT, catchup_id TEXT)"
    )
    props = FakeProps()

    svc = refresh.RefreshService(conn, props, FakeNotify(), settings=_no_startup_settings())
    svc.on_start()

    with pytest.raises(Exception):
        conn.execute("SELECT * FROM programme_staging")


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
