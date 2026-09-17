# -*- coding: utf-8 -*-
from kodimate import playback
from kodimate import db
from kodimate import providers


class FakePlayer(object):
    def __init__(self):
        self.plays = []
        self.stop_calls = 0

    def play(self, url, headers):
        self.plays.append((url, headers))

    def stop(self):
        self.stop_calls += 1


class FakeScheduler(object):
    """Manual scheduler: advance(seconds) fires due handles in schedule order."""

    def __init__(self):
        self._pending = []  # [handle_id, due_at, fn, cancelled]
        self._now = 0
        self._next_id = 0

    def __call__(self, delay_seconds, fn):
        self._next_id += 1
        entry = {'id': self._next_id, 'due': self._now + delay_seconds, 'fn': fn, 'cancelled': False}
        self._pending.append(entry)
        return _Handle(entry)

    def advance(self, seconds):
        self._now += seconds
        due = [e for e in self._pending if not e['cancelled'] and e['due'] <= self._now]
        self._pending = [e for e in self._pending if e not in due]
        for entry in due:
            entry['fn']()


class _Handle(object):
    def __init__(self, entry):
        self._entry = entry

    def cancel(self):
        self._entry['cancelled'] = True


class FakeClock(object):
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class ScriptedProbe(object):
    def __init__(self, results):
        self._results = list(results)
        self.calls = []

    def __call__(self, url, headers):
        self.calls.append((url, headers))
        return self._results.pop(0)


class FakeLogger(object):
    def __init__(self):
        self.info_lines = []
        self.debug_lines = []

    def log(self, msg, level=None):
        self.info_lines.append(msg)

    def debug(self, msg):
        self.debug_lines.append(msg)


class RecordingPersist(object):
    def __init__(self):
        self.calls = []

    def __call__(self, provider_id, form):
        self.calls.append((provider_id, form))


class StateRecorder(object):
    def __init__(self):
        self.calls = []

    def __call__(self, state, reason):
        self.calls.append((state, reason))


def _xtream_snapshot(**overrides):
    snapshot = {
        'channel_key': '123',
        'name': 'Alpha',
        'stream_url': None,
        'headers': {},
        'number': 1,
        'provider_id': 7,
        'kind': 'xtream',
        'xtream_host': 'http://panel.example',
        'xtream_username': 'user',
        'xtream_password': 'pass',
        'user_agent': None,
        'stream_format': None,
        'learned_stream_format': None,
        'allowed_output_formats': None,
        'max_connections': 1,
    }
    snapshot.update(overrides)
    return snapshot


def _m3u_snapshot(**overrides):
    snapshot = {
        'channel_key': 'a',
        'name': 'Alpha',
        'stream_url': 'http://cdn.example/a.m3u8',
        'headers': {},
        'number': 1,
        'provider_id': 5,
        'kind': 'm3u',
        'xtream_host': None,
        'xtream_username': None,
        'xtream_password': None,
        'user_agent': None,
        'stream_format': None,
        'learned_stream_format': None,
        'allowed_output_formats': None,
        'max_connections': None,
    }
    snapshot.update(overrides)
    return snapshot


def _session(snapshot, probe_results=None, persist=None):
    player = FakePlayer()
    scheduler = FakeScheduler()
    clock = FakeClock()
    probe = ScriptedProbe(probe_results or [])
    logger = FakeLogger()
    state = StateRecorder()
    persist = persist if persist is not None else RecordingPersist()
    session = playback.PlaybackSession(
        snapshot, player, probe, scheduler, clock, persist, state, logger=logger,
    )
    return session, player, scheduler, clock, probe, logger, state, persist


def _catchup_xtream_snapshot(**overrides):
    overrides.setdefault('catchup_url_form', 'auto')
    overrides.setdefault('provider_catchup_correction_hours', 0)
    overrides.setdefault('catchup_correction_hours', 0)
    return _xtream_snapshot(**overrides)


def _catchup_m3u_snapshot(**overrides):
    overrides.setdefault('catchup_mode', 'default')
    overrides.setdefault('catchup_source', None)
    overrides.setdefault('provider_catchup_correction_hours', 0)
    overrides.setdefault('catchup_correction_hours', 0)
    return _m3u_snapshot(**overrides)


def _catchup_session(snapshot, catchup, probe_results=None, persist_catchup=None):
    player = FakePlayer()
    scheduler = FakeScheduler()
    clock = FakeClock()
    probe = ScriptedProbe(probe_results or [])
    logger = FakeLogger()
    state = StateRecorder()
    persist_learned = RecordingPersist()
    persist_catchup = persist_catchup if persist_catchup is not None else RecordingPersist()
    session = playback.PlaybackSession(
        snapshot, player, probe, scheduler, clock, persist_learned, state, logger=logger,
        catchup=catchup, persist_catchup_form=persist_catchup,
    )
    return session, player, scheduler, clock, probe, logger, state, persist_learned, persist_catchup


def test_catchup_xtream_attempt1_uses_path_form_and_minutes_from_window():
    catchup = {'start': 1000, 'end': 4600, 'now': 5000}  # 1h programme, all past
    session, player, scheduler, clock, probe, logger, state, persist_learned, persist_catchup = \
        _catchup_session(_catchup_xtream_snapshot(), catchup)

    session.start()

    assert len(player.plays) == 1
    url = player.plays[0][0]
    assert '/timeshift/' in url
    assert url.endswith('.ts')
    # duration = min(end, now) - start = 4600 - 1000 = 3600s = 60 minutes
    assert '/60/' in url


def test_catchup_xtream_alternate_form_retry_after_transient_probe():
    catchup = {'start': 1000, 'end': 4600, 'now': 5000}
    session, player, scheduler, clock, probe, logger, state, persist_learned, persist_catchup = \
        _catchup_session(_catchup_xtream_snapshot(), catchup, probe_results=[404])

    session.start()
    assert '/timeshift/' in player.plays[0][0]

    session.on_error()

    assert len(player.plays) == 2
    assert 'streaming/timeshift.php' in player.plays[1][0]
    assert state.calls[-1] == ('connecting', None)

    session.on_av_started()

    assert state.calls[-1] == ('playing', None)
    assert persist_catchup.calls == [(7, 'query')]
    assert persist_learned.calls == []  # never the live-form learner


def test_catchup_pinned_form_never_persisted():
    catchup = {'start': 1000, 'end': 4600, 'now': 5000}
    session, player, scheduler, clock, probe, logger, state, persist_learned, persist_catchup = \
        _catchup_session(_catchup_xtream_snapshot(catchup_url_form='path'), catchup, probe_results=[404])

    session.start()
    session.on_error()
    session.on_av_started()

    assert persist_catchup.calls == []


def test_catchup_m3u_no_retry_fails_catchup_unavailable():
    catchup = {'start': 1000, 'end': 4600, 'now': 5000}
    session, player, scheduler, clock, probe, logger, state, persist_learned, persist_catchup = \
        _catchup_session(
            _catchup_m3u_snapshot(stream_url='http://host/live/u/p/42.ts'),
            catchup, probe_results=['timeout'],
        )

    session.start()
    session.on_error()

    assert len(player.plays) == 1
    assert state.calls[-1] == ('failed', 'catchup_unavailable')


def test_catchup_m3u_unbuildable_url_fails_immediately_with_no_play():
    # default mode, no catchup-source, non-XC-shaped live URL: no URL can be
    # built at all, so the Attempt must fail without ever calling player.play.
    catchup = {'start': 1000, 'end': 4600, 'now': 5000}
    session, player, scheduler, clock, probe, logger, state, persist_learned, persist_catchup = \
        _catchup_session(_catchup_m3u_snapshot(), catchup)

    session.start()

    assert len(player.plays) == 0
    assert state.calls[-1] == ('failed', 'catchup_unavailable')


def test_catchup_login_rejected_still_classifies_but_fails_catchup_unavailable():
    catchup = {'start': 1000, 'end': 4600, 'now': 5000}
    session, player, scheduler, clock, probe, logger, state, persist_learned, persist_catchup = \
        _catchup_session(_catchup_xtream_snapshot(), catchup, probe_results=[401])

    session.start()
    session.on_error()

    assert len(player.plays) == 1  # no second attempt after login_rejected
    assert state.calls[-1] == ('failed', 'catchup_unavailable')


def test_catchup_exhausted_alternate_form_fails_catchup_unavailable():
    catchup = {'start': 1000, 'end': 4600, 'now': 5000}
    session, player, scheduler, clock, probe, logger, state, persist_learned, persist_catchup = \
        _catchup_session(_catchup_xtream_snapshot(), catchup, probe_results=[404, 404])

    session.start()
    session.on_error()
    session.on_error()

    assert len(player.plays) == 2
    assert state.calls[-1] == ('failed', 'catchup_unavailable')


def test_catchup_drop_reconnects_with_recomputed_start():
    catchup = {'start': 1000, 'end': 100000, 'now': 5000}
    session, player, scheduler, clock, probe, logger, state, persist_learned, persist_catchup = \
        _catchup_session(_catchup_xtream_snapshot(), catchup)

    session.start()
    session.on_av_started()
    clock.advance(30)  # 30s elapsed while playing -> crosses a minute boundary

    session.on_stopped()  # drop past 5s -> reconnecting

    assert state.calls[-1] == ('reconnecting', None)
    plays_before = len(player.plays)
    scheduler.advance(0)

    assert len(player.plays) == plays_before + 1
    new_url = player.plays[-1][0]
    # New start = 1000 (original) + 30 (elapsed) = 1030 -> local start
    # advances by a minute; just confirm the URL differs from attempt 1's.
    assert new_url != player.plays[0][0]


def test_catchup_reconnect_exhaustion_fails_catchup_unavailable():
    catchup = {'start': 1000, 'end': 100000, 'now': 5000}
    session, player, scheduler, clock, probe, logger, state, persist_learned, persist_catchup = \
        _catchup_session(
            _catchup_m3u_snapshot(stream_url='http://host/live/u/p/42.ts'), catchup,
        )

    session.start()
    session.on_av_started()
    clock.advance(10)
    session.on_stopped()
    scheduler.advance(0)
    session.on_stopped()
    scheduler.advance(3)
    session.on_stopped()
    scheduler.advance(6)
    session.on_stopped()

    assert state.calls[-1] == ('failed', 'catchup_unavailable')


def test_catchup_xtream_uses_provider_correction_not_channel_correction():
    # programme starts at epoch 3600 = 1970-01-01:01-00; a +1h provider
    # correction should shift the timeshift stamp back an hour, to :00-00.
    # A non-zero channel-level correction must be ignored for this call.
    catchup = {'start': 3600, 'end': 7200, 'now': 8000}
    session, player, scheduler, clock, probe, logger, state, persist_learned, persist_catchup = \
        _catchup_session(
            _catchup_xtream_snapshot(provider_catchup_correction_hours=1,
                                      catchup_correction_hours=5),
            catchup,
        )

    session.start()

    url = player.plays[0][0]
    assert '1970-01-01:00-00' in url


def test_catchup_xtream_stamp_uses_server_timezone_september_dst():
    # 2026-09-17T12:00:00Z -> America/Toronto is EDT (-4h) in September.
    epoch = 1789646400
    catchup = {'start': epoch, 'end': epoch + 3600, 'now': epoch + 4000}
    session, player, scheduler, clock, probe, logger, state, persist_learned, persist_catchup = \
        _catchup_session(
            _catchup_xtream_snapshot(server_timezone='America/Toronto'), catchup,
        )

    session.start()

    from datetime import datetime
    expected_stamp = datetime.utcfromtimestamp(epoch - 14400).strftime('%Y-%m-%d:%H-%M')
    assert expected_stamp in player.plays[0][0]


def test_catchup_xtream_stamp_uses_server_timezone_january_no_dst():
    # 2026-01-17T12:00:00Z -> America/Toronto is EST (-5h) in January.
    epoch = 1768651200
    catchup = {'start': epoch, 'end': epoch + 3600, 'now': epoch + 4000}
    session, player, scheduler, clock, probe, logger, state, persist_learned, persist_catchup = \
        _catchup_session(
            _catchup_xtream_snapshot(server_timezone='America/Toronto'), catchup,
        )

    session.start()

    from datetime import datetime
    expected_stamp = datetime.utcfromtimestamp(epoch - 18000).strftime('%Y-%m-%d:%H-%M')
    assert expected_stamp in player.plays[0][0]


def test_catchup_m3u_default_no_source_xc_shaped_uses_server_timezone():
    epoch = 1789646400  # September -> Toronto -4h
    catchup = {'start': epoch, 'end': epoch + 3600, 'now': epoch + 4000}
    snapshot = _catchup_m3u_snapshot(
        stream_url='https://xc.example/live/u/p/1.ts',
        server_timezone='America/Toronto',
    )
    session, player, scheduler, clock, probe, logger, state, persist_learned, persist_catchup = \
        _catchup_session(snapshot, catchup)

    session.start()

    from datetime import datetime
    expected_stamp = datetime.utcfromtimestamp(epoch - 14400).strftime('%Y-%m-%d:%H-%M')
    url = player.plays[0][0]
    assert '/timeshift/' in url
    assert expected_stamp in url


def test_live_catchup_none_behaviour_unchanged():
    session, player, scheduler, clock, probe, logger, state, persist = _session(_xtream_snapshot())
    session.start()
    session.on_av_started()
    assert state.calls[-1] == ('playing', None)
    assert session.catchup is None


def test_connecting_then_playing_on_av_started():
    session, player, scheduler, clock, probe, logger, state, persist = _session(_xtream_snapshot())

    session.start()
    assert state.calls == [('connecting', None)]
    assert len(player.plays) == 1
    assert player.plays[0][0] == 'http://panel.example/live/user/pass/123.ts'

    session.on_av_started()

    assert state.calls[-1] == ('playing', None)
    assert session.state == 'playing'
    assert logger.info_lines[-1].startswith('Playback attempt 1/2')
    assert 'outcome=playing' in logger.info_lines[-1]


def test_error_then_401_fails_login_rejected_after_one_attempt():
    session, player, scheduler, clock, probe, logger, state, persist = _session(
        _xtream_snapshot(), probe_results=[401],
    )
    session.start()

    session.on_error()

    assert state.calls[-1] == ('failed', 'login_rejected')
    assert len(player.plays) == 1
    assert 'outcome=start-failure' in logger.info_lines[-1]
    assert 'probe=401' in logger.info_lines[-1]


def test_429_fails_connection_limit():
    session, player, scheduler, clock, probe, logger, state, persist = _session(
        _xtream_snapshot(), probe_results=[429],
    )
    session.start()

    session.on_error()

    assert state.calls[-1] == ('failed', 'connection_limit')


def test_m3u_404_fails_unavailable_with_no_second_attempt():
    session, player, scheduler, clock, probe, logger, state, persist = _session(
        _m3u_snapshot(), probe_results=[404],
    )
    session.start()

    session.on_error()

    assert state.calls[-1] == ('failed', 'unavailable')
    assert len(player.plays) == 1


def test_xtream_404_ts_falls_back_to_m3u8_and_persists_learned_form():
    session, player, scheduler, clock, probe, logger, state, persist = _session(
        _xtream_snapshot(), probe_results=[404],
    )
    session.start()
    assert player.plays[0][0].endswith('.ts')

    session.on_error()

    assert len(player.plays) == 2
    assert player.plays[1][0].endswith('.m3u8')
    assert state.calls[-1] == ('connecting', None)

    session.on_av_started()

    assert state.calls[-1] == ('playing', None)
    assert persist.calls == [(7, 'm3u8')]


def test_m3u8_not_allowed_skips_fallback_and_fails_unavailable():
    session, player, scheduler, clock, probe, logger, state, persist = _session(
        _xtream_snapshot(allowed_output_formats=['ts']), probe_results=[404],
    )
    session.start()

    session.on_error()

    assert state.calls[-1] == ('failed', 'unavailable')
    assert len(player.plays) == 1


def test_explicit_stream_format_fallback_success_does_not_persist():
    session, player, scheduler, clock, probe, logger, state, persist = _session(
        _xtream_snapshot(stream_format='ts'), probe_results=[404],
    )
    session.start()
    session.on_error()
    session.on_av_started()

    assert state.calls[-1] == ('playing', None)
    assert persist.calls == []


def test_m3u_timeout_retries_same_url_once_then_fails():
    session, player, scheduler, clock, probe, logger, state, persist = _session(
        _m3u_snapshot(), probe_results=['timeout', 'timeout'],
    )
    session.start()

    session.on_error()
    assert len(player.plays) == 2
    assert player.plays[0][0] == player.plays[1][0]
    assert state.calls[-1] == ('connecting', None)

    session.on_error()

    assert state.calls[-1] == ('failed', 'unavailable')
    assert len(player.plays) == 2


def test_30s_no_av_timer_is_a_start_failure():
    session, player, scheduler, clock, probe, logger, state, persist = _session(
        _m3u_snapshot(), probe_results=[200, 'timeout'],
    )
    session.start()

    clock.advance(30)
    scheduler.advance(30)

    assert len(player.plays) == 2
    assert state.calls[-1] == ('connecting', None)


def test_drop_under_5s_after_av_start_is_start_failure_with_probe():
    session, player, scheduler, clock, probe, logger, state, persist = _session(
        _m3u_snapshot(), probe_results=[200, 200],
    )
    session.start()
    session.on_av_started()
    clock.advance(2)

    session.on_stopped()

    assert probe.calls  # probe ran
    assert state.calls[-1] == ('connecting', None)
    assert len(player.plays) == 2


def test_drop_after_5s_enters_reconnecting_with_backoff_and_no_probe():
    session, player, scheduler, clock, probe, logger, state, persist = _session(
        _m3u_snapshot(),
    )
    session.start()
    session.on_av_started()
    clock.advance(10)

    session.on_stopped()

    assert state.calls[-1] == ('reconnecting', None)
    assert probe.calls == []
    # Attempt at 0s already fired synchronously via scheduler.advance(0)? No:
    # first reconnect attempt is scheduled at delay 0 but only fires on advance.
    plays_before = len(player.plays)
    scheduler.advance(0)
    assert len(player.plays) == plays_before + 1

    # That reconnect attempt also fails to start -> scheduled at +3s
    session.on_stopped()
    scheduler.advance(3)
    assert len(player.plays) == plays_before + 2

    # Third attempt at +6s also fails -> Failed unavailable
    session.on_stopped()
    scheduler.advance(6)
    assert len(player.plays) == plays_before + 3

    session.on_stopped()

    assert state.calls[-1] == ('failed', 'unavailable')
    assert probe.calls == []


def test_reconnect_success_returns_to_playing():
    session, player, scheduler, clock, probe, logger, state, persist = _session(
        _m3u_snapshot(),
    )
    session.start()
    session.on_av_started()
    clock.advance(10)
    session.on_stopped()
    scheduler.advance(0)

    session.on_av_started()

    assert state.calls[-1] == ('playing', None)
    assert session.state == 'playing'


def test_abort_cancels_timers_and_ignores_late_callbacks():
    session, player, scheduler, clock, probe, logger, state, persist = _session(
        _m3u_snapshot(),
    )
    session.start()

    session.abort()

    assert player.stop_calls == 1
    assert state.calls == [('connecting', None)]  # no 'failed' emitted by abort

    # Late callback after abort is ignored.
    session.on_av_started()
    assert state.calls == [('connecting', None)]

    # The 30s timer that would have fired is cancelled: advancing does nothing.
    plays_before = len(player.plays)
    clock.advance(30)
    scheduler.advance(30)
    assert len(player.plays) == plays_before


def test_one_info_log_line_per_attempt_with_no_credentials():
    session, player, scheduler, clock, probe, logger, state, persist = _session(
        _xtream_snapshot(), probe_results=[401],
    )
    session.start()
    session.on_error()

    assert len(logger.info_lines) == 1
    line = logger.info_lines[0]
    assert 'user' not in line
    assert 'pass' not in line
    assert '***' not in line  # URL is not included in the INFO line at all
    assert 'panel.example' not in line


def test_debug_lines_emitted_for_callbacks():
    session, player, scheduler, clock, probe, logger, state, persist = _session(
        _xtream_snapshot(),
    )
    session.start()
    session.on_av_started()

    assert any('onAVStarted' in line for line in logger.debug_lines)


def test_abort_during_probe_is_non_blocking_and_probe_result_is_discarded():
    session, player, scheduler, clock, probe, logger, state, persist = _session(
        _xtream_snapshot(),
    )
    events = []

    def slow_probe(url, headers):
        events.append('probe-start')
        # Simulates the UI thread pressing Back while the probe is in
        # flight: abort() must not block waiting for the probe.
        session.abort()
        events.append('probe-end')
        return 404

    session.probe = slow_probe
    session.start()
    plays_before = len(player.plays)

    session.on_error()

    assert events == ['probe-start', 'probe-end']
    assert len(player.plays) == plays_before  # no Attempt 2 started
    assert state.calls == [('connecting', None)]  # no on_state('failed', ...)
    assert player.stop_calls == 2  # attempt-failure stop() + abort() stop()


def test_load_snapshot_reads_channel_and_provider(tmp_path):
    conn = db.open_db(str(tmp_path / "kodimate.db"))
    try:
        provider_id = providers.create_xtream_provider(
            conn, "P1", "http://panel.example", "u", "p",
        )
        conn.execute(
            "INSERT INTO channel (provider_id, channel_key, name, normalised_name, "
            "stream_url, position, headers_json) VALUES (?, '10', 'Ch', 'ch', "
            "'http://x/10.ts', 0, ?)",
            (provider_id, '{"User-Agent": "UA"}'),
        )

        snapshot = playback.load_snapshot(conn, provider_id, '10')

        assert snapshot['channel_key'] == '10'
        assert snapshot['kind'] == 'xtream'
        assert snapshot['headers'] == {'User-Agent': 'UA'}
        assert snapshot['xtream_host'] == 'http://panel.example'
        assert snapshot['provider_name'] == 'P1'
        assert snapshot['catchup_url_form'] == 'path'
        assert snapshot['server_timezone'] is None
    finally:
        conn.close()


def test_load_snapshot_returns_none_when_missing(tmp_path):
    conn = db.open_db(str(tmp_path / "kodimate.db"))
    try:
        assert playback.load_snapshot(conn, 1, 'missing') is None
    finally:
        conn.close()
