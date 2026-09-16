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
    finally:
        conn.close()


def test_load_snapshot_returns_none_when_missing(tmp_path):
    conn = db.open_db(str(tmp_path / "kodimate.db"))
    try:
        assert playback.load_snapshot(conn, 1, 'missing') is None
    finally:
        conn.close()
