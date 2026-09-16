# -*- coding: utf-8 -*-
from kodimate.windows.playback import PlaybackWindow
import xbmcgui


class FakePlayer(object):
    def __init__(self):
        self.plays = []
        self.stop_calls = 0
        self.attached = None
        self.detached = None

    def play(self, url, headers):
        self.plays.append((url, headers))

    def stop(self):
        self.stop_calls += 1

    def attach(self, session):
        self.attached = session

    def detach(self, session):
        self.detached = session


class FakeScheduler(object):
    def __init__(self):
        self._pending = []
        self._now = 0

    def __call__(self, delay_seconds, fn):
        entry = {'due': self._now + delay_seconds, 'fn': fn, 'cancelled': False}
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


def _snapshot(**overrides):
    snapshot = {
        'channel_key': 'a', 'name': 'Alpha', 'stream_url': 'http://cdn.example/a.ts',
        'headers': {}, 'number': 3, 'provider_id': 5, 'kind': 'm3u',
        'xtream_host': None, 'xtream_username': None, 'xtream_password': None,
        'user_agent': None, 'stream_format': None, 'learned_stream_format': None,
        'allowed_output_formats': None, 'max_connections': None,
    }
    snapshot.update(overrides)
    return snapshot


def _window(probe_results=None, snapshot=None):
    probe_results = list(probe_results or [])

    def probe(url, headers):
        return probe_results.pop(0)

    window = PlaybackWindow(
        'script-kodimate-playback.xml', '/addon', 'Main', '1080i',
        snapshot=snapshot or _snapshot(),
        player=FakePlayer(), probe=probe, scheduler=FakeScheduler(),
        clock=FakeClock(), persist_learned_form=lambda *a: None,
    )
    return window


def test_onInit_starts_connecting():
    window = _window()
    window.onInit()

    assert window.getProperty('state') == 'connecting'
    assert window.getProperty('channel_name') == 'Alpha'
    assert window.getProperty('channel_number') == '3'
    assert len(window.player.plays) == 1


def test_playing_clears_status_text():
    window = _window()
    window.onInit()

    window.session.on_av_started()

    assert window.getProperty('state') == 'playing'
    assert window.getProperty('status_text') == ''


def test_failed_sets_reason_property():
    window = _window(probe_results=[401])
    window.onInit()

    window.session.on_error()

    assert window.getProperty('state') == 'failed'
    assert window.getProperty('reason') == 'login_rejected'


def test_back_aborts_session_and_closes():
    window = _window()
    window.onInit()

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))

    assert window.player.stop_calls == 1
    assert window.player.detached is window.session


def test_ok_while_failed_starts_a_new_session():
    window = _window(probe_results=[401])
    window.onInit()
    window.session.on_error()
    assert window.getProperty('state') == 'failed'
    failed_session = window.session

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert window.session is not failed_session
    assert window.getProperty('state') == 'connecting'
    assert window.getProperty('reason') == ''
