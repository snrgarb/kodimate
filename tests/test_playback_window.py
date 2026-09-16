# -*- coding: utf-8 -*-
from kodimate.windows.playback import PlaybackWindow
import xbmc
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


def test_state_is_connecting_before_first_play_call():
    """The spinner's Window.Property(state) condition must already be
    'connecting' by the time the session issues its first play() call, not
    only after PlaybackSession.start() returns."""
    window = PlaybackWindow(
        'script-kodimate-playback.xml', '/addon', 'Main', '1080i',
        snapshot=_snapshot(), player=FakePlayer(), probe=lambda *a: 200,
        scheduler=FakeScheduler(), clock=FakeClock(),
        persist_learned_form=lambda *a: None,
    )
    seen_state_at_first_play = []

    original_play = window.player.play

    def capturing_play(url, headers):
        seen_state_at_first_play.append(window.getProperty('state'))
        original_play(url, headers)

    window.player.play = capturing_play

    window.onInit()

    assert seen_state_at_first_play == ['connecting']


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


def test_busy_dialog_activated_during_init():
    xbmc.executebuiltin_calls[:] = []
    window = _window()

    window.onInit()

    assert 'ActivateWindow(busydialognocancel)' in xbmc.executebuiltin_calls


def test_busy_dialog_closed_on_transition_to_playing():
    xbmc.executebuiltin_calls[:] = []
    window = _window()
    window.onInit()

    window.session.on_av_started()

    assert xbmc.executebuiltin_calls[-1] == 'Dialog.Close(busydialognocancel)'


def test_busy_dialog_closed_on_transition_to_failed():
    xbmc.executebuiltin_calls[:] = []
    window = _window(probe_results=[401])
    window.onInit()

    window.session.on_error()

    assert xbmc.executebuiltin_calls[-1] == 'Dialog.Close(busydialognocancel)'


def test_busy_dialog_closed_on_back_abort():
    xbmc.executebuiltin_calls[:] = []
    window = _window()
    window.onInit()

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))

    assert xbmc.executebuiltin_calls[-1] == 'Dialog.Close(busydialognocancel)'


def test_busy_dialog_not_reactivated_for_second_connecting_state():
    # Xtream 404-on-ts falls back to m3u8: attempt 1 and attempt 2 both
    # emit on_state('connecting', ...), but the busy dialog should only be
    # (re-)activated once by the state-driven path.
    xtream_snapshot = _snapshot(
        kind='xtream', xtream_host='http://panel.example',
        xtream_username='u', xtream_password='p', channel_key='1',
        stream_url=None,
    )
    xbmc.executebuiltin_calls[:] = []
    window = _window(probe_results=[404], snapshot=xtream_snapshot)
    window.onInit()
    activate_count_after_init = xbmc.executebuiltin_calls.count(
        'ActivateWindow(busydialognocancel)'
    )

    window.session.on_error()  # attempt 1 fails, falls back to attempt 2 (still connecting)

    assert window.getProperty('state') == 'connecting'
    assert xbmc.executebuiltin_calls.count('ActivateWindow(busydialognocancel)') \
        == activate_count_after_init


def test_busy_dialog_not_reopened_if_playing_during_activate_sleep(monkeypatch):
    # If on_av_started fires during the post-start() sleep (before
    # ActivateWindow(fullscreenvideo)), _on_state('playing') will already
    # have closed the busy dialog; the fullscreen-activation step must not
    # reopen it over live video.
    xbmc.executebuiltin_calls[:] = []
    window = _window()

    def fake_sleep(ms):
        window.session.on_av_started()

    monkeypatch.setattr(xbmc, 'sleep', fake_sleep)

    window.onInit()

    close_index = xbmc.executebuiltin_calls.index('Dialog.Close(busydialognocancel)')
    assert 'ActivateWindow(busydialognocancel)' not in xbmc.executebuiltin_calls[close_index + 1:]


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
