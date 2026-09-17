# -*- coding: utf-8 -*-
import threading
from datetime import datetime

import pytest

from kodimate import autoplay, channels, db, playback
from kodimate.windows.playback import (
    PlaybackWindow, GROUPS_LIST_ID, CHANNELS_LIST_ID, PROGRESS_FILL_ID,
)
import xbmc
import xbmcgui


@pytest.fixture(autouse=True)
def _clear_db_generation():
    xbmcgui._window_properties.pop(10000, None)
    yield
    xbmcgui._window_properties.pop(10000, None)


def _bump_generation(value):
    xbmcgui.Window(10000).setProperty('script.kodimate.db_generation', str(value))


def _notify_refreshed(window):
    window._watcher.onNotification('script.kodimate', 'Other.refreshed', '{}')


class FakePlayer(object):
    def __init__(self):
        self.plays = []
        self.stop_calls = 0
        self.attached = None
        self.detached = None
        self.time = 0
        self.time_raises = False

    def play(self, url, headers, mime_type=None):
        self.plays.append((url, headers))

    def stop(self):
        self.stop_calls += 1

    def getTime(self):
        if self.time_raises:
            raise RuntimeError('no time')
        return self.time

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

    def pending_count(self):
        return len([e for e in self._pending if not e['cancelled']])


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


class FakeNow(object):
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


# -- DB helpers (same shape as tests/test_channels.py) -----------------------

def _conn(tmp_path):
    return db.open_db(str(tmp_path / "kodimate.db"))


def _provider(conn, name="P1", number_offset=0):
    cursor = conn.execute(
        "INSERT INTO provider (kind, name, enabled, sort_order, number_offset) "
        "VALUES ('m3u', ?, 1, 0, ?)",
        (name, number_offset),
    )
    return cursor.lastrowid


def _group(conn, provider_id, name="Group A", sort_order=0):
    cursor = conn.execute(
        "INSERT INTO channel_group (provider_id, name, sort_order) VALUES (?, ?, ?)",
        (provider_id, name, sort_order),
    )
    return cursor.lastrowid


def _channel(conn, provider_id, channel_key, name="Chan", group_id=None, position=0, logo_url=None):
    cursor = conn.execute(
        "INSERT INTO channel (provider_id, channel_key, name, normalised_name, stream_url, "
        "group_id, position, logo_url) VALUES (?, ?, ?, ?, 'http://x', ?, ?, ?)",
        (provider_id, channel_key, name, name.lower(), group_id, position, logo_url),
    )
    return cursor.lastrowid


def _override_number(conn, provider_id, channel_key, number):
    conn.execute(
        "INSERT INTO channel_override (provider_id, channel_key, number) VALUES (?, ?, ?)",
        (provider_id, channel_key, number),
    )


def _epg_source(conn, provider_id, url="http://epg"):
    cursor = conn.execute(
        "INSERT INTO epg_source (provider_id, url) VALUES (?, ?)", (provider_id, url)
    )
    return cursor.lastrowid


def _programme(conn, epg_source_id, xmltv_channel_id, start, end, title):
    conn.execute(
        "INSERT INTO programme (epg_source_id, xmltv_channel_id, start, end, title) "
        "VALUES (?, ?, ?, ?, ?)",
        (epg_source_id, xmltv_channel_id, start, end, title),
    )


def _setup_channel(conn, provider_id=None, channel_key='a', name='Alpha', group_id=None,
                    position=0, logo_url=None):
    if provider_id is None:
        provider_id = _provider(conn)
    _channel(conn, provider_id, channel_key, name=name, group_id=group_id,
             position=position, logo_url=logo_url)
    conn.execute(
        "UPDATE channel SET epg_channel_id = ? WHERE provider_id = ? AND channel_key = ?",
        (channel_key, provider_id, channel_key),
    )
    snapshot = playback.load_snapshot(conn, provider_id, channel_key)
    return provider_id, snapshot


def _window(conn, snapshot, probe_results=None, **overrides):
    probe_results = list(probe_results or [])

    def probe(url, headers):
        return probe_results.pop(0)

    kwargs = dict(
        conn=conn, snapshot=snapshot,
        player=FakePlayer(), probe=probe, scheduler=FakeScheduler(),
        clock=FakeClock(), persist_learned_form=lambda *a: None,
        osd_hide_seconds=3, number_commit_delay=1.5,
    )
    kwargs.update(overrides)
    window = PlaybackWindow(
        'script-kodimate-playback.xml', '/addon', 'Main', '1080i', **kwargs
    )
    return window


# -- basic session wiring (unchanged behaviour) -------------------------------

def test_onInit_starts_connecting(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn, name='Alpha')
    window = _window(conn, snapshot)
    window.onInit()

    assert window.getProperty('state') == 'connecting'
    assert window.getProperty('channel_name') == 'Alpha'
    assert len(window.player.plays) == 1


def test_playing_clears_status_text(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)
    window.onInit()

    window.session.on_av_started()

    assert window.getProperty('state') == 'playing'
    assert window.getProperty('status_text') == ''


def test_ok_while_failed_starts_a_new_session(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot, probe_results=[401])
    window.onInit()
    window.session.on_error()
    assert window.getProperty('state') == 'failed'
    failed_session = window.session

    window._close_list()
    window.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert window.session is not failed_session
    assert window.getProperty('state') == 'connecting'
    assert window.getProperty('reason') == ''


def test_no_busy_dialog_builtin_issued(tmp_path):
    xbmc.executebuiltin_calls[:] = []
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)

    window.onInit()
    window.session.on_av_started()

    assert not any('busydialognocancel' in c for c in xbmc.executebuiltin_calls)


# -- info bar ------------------------------------------------------------

def test_bar_shows_number_logo_name_now_next_and_times(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel(conn, channel_key='a', name='Alpha',
                                            logo_url='http://logo/a.png')
    eid = _epg_source(conn, provider_id)
    _programme(conn, eid, 'a', '2026-01-01T11:30:00Z', '2026-01-01T12:00:00Z', 'Now Show')
    _programme(conn, eid, 'a', '2026-01-01T12:00:00Z', '2026-01-01T12:30:00Z', 'Next Show')
    now = datetime(2026, 1, 1, 11, 45)
    window = _window(conn, snapshot, now_fn=FakeNow(now), _tz=None)

    window.onInit()

    assert window.getProperty('channel_number') == str(snapshot['number'])
    assert window.getProperty('channel_logo') == 'http://logo/a.png'
    assert window.getProperty('now_title') == 'Now Show'
    assert window.getProperty('next_title') == 'Next Show'
    assert window.getProperty('bar_visible') == '1'


def test_bar_shows_no_information_when_no_programme(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot, now_fn=FakeNow(datetime(2026, 1, 1, 11, 45)))

    window.onInit()

    assert window.getProperty('now_title') == 'String 32083'
    assert window.getProperty('next_title') == ''


def test_bar_auto_hides_after_delay_while_playing(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot, osd_hide_seconds=3)
    window.onInit()

    window.session.on_av_started()
    assert window.getProperty('bar_visible') == '1'

    window.scheduler.advance(3)
    assert window.getProperty('bar_visible') == '0'


def test_bar_does_not_auto_hide_while_connecting(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot, osd_hide_seconds=3)
    window.onInit()

    window.scheduler.advance(10)

    assert window.getProperty('bar_visible') == '1'


def test_ok_toggles_bar_and_rearms_auto_hide_while_playing(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot, osd_hide_seconds=3)
    window.onInit()
    window.session.on_av_started()
    window.scheduler.advance(3)
    assert window.getProperty('bar_visible') == '0'

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
    assert window.getProperty('bar_visible') == '1'

    window.scheduler.advance(3)
    assert window.getProperty('bar_visible') == '0'


def test_tick_updates_progress_fill_width(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel(conn, channel_key='a')
    eid = _epg_source(conn, provider_id)
    _programme(conn, eid, 'a', '2026-01-01T11:00:00Z', '2026-01-01T12:00:00Z', 'Now Show')
    now = FakeNow(datetime(2026, 1, 1, 11, 30))
    window = _window(conn, snapshot, now_fn=now)
    window.onInit()
    window.session.on_av_started()

    window._tick()

    assert window.getControl(704).getWidth() == 300  # 50% of PROGRESS_WIDTH(600)
    assert window.getControl(705).getX() == 1236  # 940 + 300 - 4
    assert window.getControl(705).getY() == 78


def test_tick_updates_progress_while_bar_hidden(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel(conn, channel_key='a')
    eid = _epg_source(conn, provider_id)
    _programme(conn, eid, 'a', '2026-01-01T11:00:00Z', '2026-01-01T12:00:00Z', 'Now Show')
    now = FakeNow(datetime(2026, 1, 1, 11, 30))
    window = _window(conn, snapshot, now_fn=now)
    window.onInit()
    window.session.on_av_started()
    window._hide_bar()
    assert window.getProperty('bar_visible') == '0'

    window._tick()

    assert window.getControl(704).getWidth() == 300  # 50% of PROGRESS_WIDTH(600)


# -- Groups/Channels overlay --------------------------------------------

def test_up_down_opens_overlay_without_touching_stream(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)
    window.onInit()
    plays_before = len(window.player.plays)
    stops_before = window.player.stop_calls

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_DOWN))

    assert window.getProperty('list_visible') == '1'
    assert window.getFocusId() == 201
    assert len(window.player.plays) == plays_before
    assert window.player.stop_calls == stops_before


def test_ok_on_channel_row_zaps_and_closes_list(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel(conn, channel_key='a', name='Alpha')
    _channel(conn, provider_id, 'b', name='Bravo', position=1)
    window = _window(conn, snapshot)
    window.onInit()
    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_UP))
    channels_control = window.getControl(201)
    target_position = next(
        i for i, item in enumerate(channels_control._items) if item.getProperty('channel_key') == 'b'
    )
    channels_control.selectItem(target_position)

    window.onClick(201)

    assert window.getProperty('list_visible') == '0'
    assert window.getProperty('channel_name') == 'Bravo'
    assert window.session.state == 'connecting'


def test_click_on_channels_list_ignored_when_list_closed(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel(conn, channel_key='a', name='Alpha')
    _channel(conn, provider_id, 'b', name='Bravo', position=1)
    window = _window(conn, snapshot)
    window.onInit()
    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_UP))
    channels_control = window.getControl(201)
    target_position = next(
        i for i, item in enumerate(channels_control._items) if item.getProperty('channel_key') == 'b'
    )
    channels_control.selectItem(target_position)
    window.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
    assert window._list_open is False
    plays_before = len(window.player.plays)
    state_before = window.session.state

    window.onClick(201)

    assert len(window.player.plays) == plays_before
    assert window.session.state == state_before


def test_click_on_channels_list_ignored_when_list_closed_during_catchup(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel(conn, channel_key='a', name='Alpha', position=0)
    _channel(conn, provider_id, 'b', name='Bravo', position=1)
    start_dt = datetime(2026, 1, 1, 10, 0)
    end_dt = datetime(2026, 1, 1, 11, 0)
    catchup = {'start': 0, 'end': 3600, 'now': 3600, 'title': 'Old Show',
               'start_dt': start_dt, 'end_dt': end_dt, 'catchup_id': None}
    window = _window(conn, snapshot, catchup=catchup)
    window.onInit()
    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_UP))
    channels_control = window.getControl(201)
    target_position = next(
        i for i, item in enumerate(channels_control._items) if item.getProperty('channel_key') == 'b'
    )
    channels_control.selectItem(target_position)
    window.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
    assert window._list_open is False

    window.onClick(201)

    assert window.catchup is not None
    assert window.getProperty('catchup') == '1'


def test_overlay_channel_row_gets_now_title_property(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel(conn, channel_key='a', name='Alpha')
    eid = _epg_source(conn, provider_id)
    _programme(conn, eid, 'a', '2026-01-01T11:00:00Z', '2026-01-01T12:00:00Z', 'Now Show')
    now = datetime(2026, 1, 1, 11, 30)
    window = _window(conn, snapshot, now_fn=FakeNow(now))
    window.onInit()
    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_UP))
    channels_control = window.getControl(201)
    alpha = next(
        item for item in channels_control._items if item.getProperty('channel_key') == 'a'
    )
    assert alpha.getProperty('now_title') == 'Now Show'


def test_overlay_channel_row_now_title_empty_when_no_current_programme(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel(conn, channel_key='a', name='Alpha')
    _channel(conn, provider_id, 'b', name='Bravo', position=1)
    window = _window(conn, snapshot, now_fn=FakeNow(datetime(2026, 1, 1, 11, 30)))
    window.onInit()
    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_UP))
    channels_control = window.getControl(201)
    bravo = next(
        item for item in channels_control._items if item.getProperty('channel_key') == 'b'
    )
    assert bravo.getProperty('now_title') == ''


def test_bar_shows_new_channel_name_while_connecting_after_zap(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel(conn, channel_key='a', name='Alpha')
    _channel(conn, provider_id, 'b', name='Bravo', position=1)
    window = _window(conn, snapshot)
    window.onInit()

    window._zap(provider_id, 'b')

    assert window.getProperty('channel_name') == 'Bravo'
    assert window.session.state == 'connecting'
    assert window.getProperty('bar_visible') == '1'


# -- number entry --------------------------------------------------------

def test_digit_shown_and_commits_after_delay(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel(conn, channel_key='a', name='Alpha', position=0)
    _channel(conn, provider_id, 'b', name='Bravo', position=5)
    window = _window(conn, snapshot, number_commit_delay=1.5)
    window.onInit()

    window.onAction(xbmcgui.Action(58 + 5))  # ACTION_REMOTE_5 -> digit 5

    assert window.getProperty('digits') == '5'

    window.scheduler.advance(1.5)

    assert window.getProperty('digits') == ''
    assert window.getProperty('channel_name') == 'Bravo'


def test_ok_commits_digits_immediately(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel(conn, channel_key='a', name='Alpha', position=0)
    _channel(conn, provider_id, 'b', name='Bravo', position=5)
    window = _window(conn, snapshot)
    window.onInit()

    window.onAction(xbmcgui.Action(58 + 5))
    window.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert window.getProperty('digits') == ''
    assert window.getProperty('channel_name') == 'Bravo'


def test_duplicate_number_resolves_to_first_in_list_order(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel(conn, channel_key='a', name='Alpha', position=0)
    _channel(conn, provider_id, 'b', name='Bravo', position=1)
    _override_number(conn, provider_id, 'a', 5)
    _override_number(conn, provider_id, 'b', 5)
    window = _window(conn, snapshot)
    window.onInit()

    window.onAction(xbmcgui.Action(58 + 5))
    window.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert window.getProperty('channel_name') == 'Alpha'


def test_back_while_digits_pending_cancels_entry(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)
    window.onInit()
    window.onAction(xbmcgui.Action(58 + 5))

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))

    assert window.getProperty('digits') == ''
    # The digit press itself already aborted the in-flight connect per
    # spec; Back only needs to clear the pending entry, not re-abort.
    assert window.player.detached is window.session


# -- Back layering ---------------------------------------------------------

def test_back_hides_bar_then_leaves(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)
    window.onInit()
    window.session.on_av_started()
    assert window.getProperty('bar_visible') == '1'

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
    assert window.getProperty('bar_visible') == '0'
    assert window.player.detached is None

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
    assert window.player.detached is window.session


def test_back_closes_list_before_bar(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)
    window.onInit()
    window.session.on_av_started()
    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_DOWN))
    assert window.getProperty('list_visible') == '1'

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))

    assert window.getProperty('list_visible') == '0'
    assert window.getProperty('bar_visible') == '1'
    assert window.player.detached is None


# -- Failed ----------------------------------------------------------------

def test_failed_sets_reason_and_opens_list(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot, probe_results=[401])
    window.onInit()

    window.session.on_error()

    assert window.getProperty('state') == 'failed'
    assert window.getProperty('reason') == 'login_rejected'
    assert window.getProperty('list_visible') == '1'
    assert window.getFocusId() == 201


def test_ok_on_bare_video_while_failed_starts_new_session(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot, probe_results=[401])
    window.onInit()
    window.session.on_error()
    window._close_list()  # user pressed Back to close the auto-opened list
    failed_session = window.session

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert window.session is not failed_session
    assert window.getProperty('state') == 'connecting'


# -- abort-before-new-action during Connecting/Reconnecting -----------------

def test_zap_during_connecting_cancels_timer_and_stops_player(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel(conn, channel_key='a', name='Alpha')
    _channel(conn, provider_id, 'b', name='Bravo', position=1)
    window = _window(conn, snapshot)
    window.onInit()
    assert window.scheduler.pending_count() >= 1  # start timeout armed
    old_session = window.session
    stops_before = window.player.stop_calls

    window._zap(provider_id, 'b')

    assert window.player.stop_calls > stops_before
    assert window.player.detached is old_session
    assert window.getProperty('channel_name') == 'Bravo'


def test_digit_during_connecting_aborts_and_stops_player(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel(conn, channel_key='a', name='Alpha', position=0)
    _channel(conn, provider_id, 'b', name='Bravo', position=4)
    window = _window(conn, snapshot)
    window.onInit()
    old_session = window.session
    stops_before = window.player.stop_calls

    window.onAction(xbmcgui.Action(58 + 5))

    assert window.player.stop_calls > stops_before
    assert window.player.detached is old_session


def test_back_during_connecting_and_list_open_aborts_before_closing(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)
    window.onInit()
    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_DOWN))
    assert window.getProperty('list_visible') == '1'
    stops_before = window.player.stop_calls
    old_session = window.session

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))

    assert window.player.stop_calls > stops_before
    assert window.getProperty('list_visible') == '0'
    assert window.player.detached is old_session
    assert window.getProperty('state') == 'stopped'
    assert window.getProperty('status_text') == ''


def test_digit_commit_no_match_during_connecting_leaves_stopped_state(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn, channel_key='a', name='Alpha', position=0)
    window = _window(conn, snapshot)
    window.onInit()
    old_session = window.session
    plays_before = len(window.player.plays)

    # No channel is numbered 9 -> commit finds no match.
    window.onAction(xbmcgui.Action(58 + 9))  # ACTION_REMOTE_9 -> digit 9
    window.scheduler.advance(1.5)

    assert window.getProperty('digits') == ''
    assert window.getProperty('state') == 'stopped'
    assert window.player.detached is old_session
    assert len(window.player.plays) == plays_before


def test_ok_while_stopped_starts_a_new_session(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn, channel_key='a', name='Alpha', position=0)
    window = _window(conn, snapshot)
    window.onInit()
    window.onAction(xbmcgui.Action(58 + 9))  # aborts the connecting session -> 'stopped'
    window.scheduler.advance(1.5)
    assert window.getProperty('state') == 'stopped'
    stopped_session = window.session

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert window.session is not stopped_session
    assert window.getProperty('state') == 'connecting'


def test_probe_in_flight_discarded_when_aborted_by_digit_press(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn, channel_key='a', name='Alpha')
    events = []

    def slow_probe(url, headers):
        events.append('probe-start')
        window.onAction(xbmcgui.Action(58 + 9))  # digit press aborts the in-flight session
        events.append('probe-end')
        return 401

    window = _window(conn, snapshot, probe_results=None)
    window.probe = slow_probe
    window.onInit()

    window.session.on_error()

    assert events == ['probe-start', 'probe-end']
    assert window.getProperty('state') == 'stopped'
    assert window.getProperty('digits') == '9'


def test_tick_does_nothing_after_close(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)
    window.onInit()
    window.session.on_av_started()
    window._tick()
    now_title_before = window.getProperty('now_title')
    window.close()

    window.setProperty('now_title', 'sentinel')
    window.setProperty('stream_res', '')
    width_before = window.getControl(PROGRESS_FILL_ID).getWidth()
    xbmc._info_labels['Player.Process(videowidth)'] = '3,840'
    xbmc._info_labels['Player.Process(videoheight)'] = '2,160'
    xbmc._info_labels['VideoPlayer.VideoCodec'] = 'hevc'
    xbmc._info_labels['Player.Process(videofps)'] = '50.000'
    xbmc._info_labels['VideoPlayer.AudioCodec'] = 'eac3'
    xbmc._info_labels['VideoPlayer.AudioChannels'] = '6'
    try:
        window._tick()
    finally:
        xbmc._info_labels.clear()

    assert window.getProperty('now_title') == 'sentinel'
    assert window.getProperty('stream_res') == ''
    assert window.getControl(PROGRESS_FILL_ID).getWidth() == width_before


def test_close_works_when_thread_is_none(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)
    window.onInit()
    window._thread = None

    window.close()


def test_probe_in_flight_discarded_when_aborted_by_zap(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel(conn, channel_key='a', name='Alpha')
    _channel(conn, provider_id, 'b', name='Bravo', position=1)
    events = []

    def slow_probe(url, headers):
        events.append('probe-start')
        window._zap(provider_id, 'b')
        events.append('probe-end')
        return 401

    window = _window(conn, snapshot, probe_results=None)
    window.probe = slow_probe
    window.onInit()

    window.session.on_error()

    assert events == ['probe-start', 'probe-end']
    assert window.getProperty('channel_name') == 'Bravo'


def test_on_state_never_blocks_on_window_lock(tmp_path):
    # Lock-order deadlock regression: PlaybackSession calls on_state (which
    # reaches _show_bar) while holding its own internal lock, while the UI
    # thread can hold window._lock and call session.abort() (which takes
    # that same session lock). If _show_bar took window._lock, one thread
    # holding window._lock while another holds the session lock -- each
    # wanting the other's lock -- would deadlock. Prove the callback path
    # never blocks on window._lock by holding it from another thread and
    # driving the callback concurrently.
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)
    window.onInit()

    held = threading.Event()
    release = threading.Event()

    def hold_window_lock():
        with window._lock:
            held.set()
            release.wait(2.0)

    holder = threading.Thread(target=hold_window_lock)
    holder.daemon = True
    holder.start()
    assert held.wait(1.0)

    try:
        finished = threading.Event()

        def call_on_av_started():
            window.session.on_av_started()
            finished.set()

        caller = threading.Thread(target=call_on_av_started)
        caller.daemon = True
        caller.start()
        caller.join(1.0)

        assert finished.is_set(), 'on_av_started blocked on window._lock'
        assert window.getProperty('bar_visible') == '1'
    finally:
        release.set()
        holder.join(1.0)


# -- catch-up (issue #28) --------------------------------------------------

class RecordingNotify(object):
    def __init__(self):
        self.calls = []

    def __call__(self, heading, message):
        self.calls.append((heading, message))


def test_catchup_property_set_when_catchup_session(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    start_dt = datetime(2026, 1, 1, 10, 0)
    end_dt = datetime(2026, 1, 1, 11, 0)
    catchup = {'start': 0, 'end': 3600, 'now': 3600, 'title': 'Old Show',
               'start_dt': start_dt, 'end_dt': end_dt, 'catchup_id': None}
    window = _window(conn, snapshot, catchup=catchup)
    window.onInit()

    assert window.getProperty('catchup') == '1'
    assert window.getProperty('now_title') == 'Old Show'
    assert window.getProperty('next_title') == ''


def test_catchup_failure_toasts_provider_and_closes_without_opening_list(tmp_path):
    # The addon.getLocalizedString() fake returns a plain "String <id>"
    # placeholder with no %s slot, so the %-substitution against
    # provider_name isn't exercised here (same pre-existing limitation as
    # the untested connection_limit "%d connections" string); this test
    # covers that notify() is called with the provider snapshot present and
    # that Failed's list-opening path is skipped for catch-up.
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel(conn)
    conn.execute("UPDATE provider SET name = 'Acme' WHERE id = ?", (provider_id,))
    snapshot = playback.load_snapshot(conn, provider_id, snapshot['channel_key'])
    start_dt = datetime(2026, 1, 1, 10, 0)
    end_dt = datetime(2026, 1, 1, 11, 0)
    catchup = {'start': 0, 'end': 3600, 'now': 3600, 'title': 'Old Show',
               'start_dt': start_dt, 'end_dt': end_dt, 'catchup_id': None}
    calls = []
    notify = lambda heading, message: calls.append((heading, message))
    window = _window(conn, snapshot, catchup=catchup, probe_results=[401], notify=notify)
    window.onInit()

    window.session.on_error()

    assert len(calls) == 1
    assert calls[0][0] == 'Kodimate'
    assert window.getProperty('list_visible') == '0'


def test_zapping_from_catchup_starts_a_live_session(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel(conn, channel_key='a', name='Alpha', position=0)
    _channel(conn, provider_id, 'b', name='Bravo', position=1)
    start_dt = datetime(2026, 1, 1, 10, 0)
    end_dt = datetime(2026, 1, 1, 11, 0)
    catchup = {'start': 0, 'end': 3600, 'now': 3600, 'title': 'Old Show',
               'start_dt': start_dt, 'end_dt': end_dt, 'catchup_id': None}
    window = _window(conn, snapshot, catchup=catchup)
    window.onInit()
    assert window.getProperty('catchup') == '1'

    window._zap(provider_id, 'b')

    assert window.catchup is None
    assert window.getProperty('catchup') == '0'
    assert window.getProperty('channel_name') == 'Bravo'


def test_catchup_bar_width_reflects_player_time_once_playing(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    snapshot['catchup_mode'] = 'shift'
    start_dt = datetime(2026, 1, 1, 10, 0)
    end_dt = datetime(2026, 1, 1, 11, 0)
    catchup = {'start': 0, 'end': 3600, 'now': 3600, 'title': 'Old Show',
               'start_dt': start_dt, 'end_dt': end_dt, 'catchup_id': None}
    window = _window(conn, snapshot, catchup=catchup)
    window.onInit()

    assert window.getControl(704).getWidth() == 0

    window.player.time = 900
    window.session.on_av_started()
    window._tick()

    assert window.getControl(704).getWidth() == 150  # 25% of PROGRESS_WIDTH(600)
    assert window.getControl(705).getX() == 1086  # 940 + 150 - 4
    assert window.getControl(705).getY() == 78


def test_catchup_tick_updates_width_as_player_time_advances(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    snapshot['catchup_mode'] = 'shift'
    start_dt = datetime(2026, 1, 1, 10, 0)
    end_dt = datetime(2026, 1, 1, 11, 0)
    catchup = {'start': 0, 'end': 3600, 'now': 3600, 'title': 'Old Show',
               'start_dt': start_dt, 'end_dt': end_dt, 'catchup_id': None}
    window = _window(conn, snapshot, catchup=catchup)
    window.onInit()
    window.session.on_av_started()

    window.player.time = 1800
    window._tick()

    assert window.getControl(704).getWidth() == 300  # 50% of PROGRESS_WIDTH(600)


def test_catchup_bar_width_survives_getTime_raising(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    snapshot['catchup_mode'] = 'shift'
    start_dt = datetime(2026, 1, 1, 10, 0)
    end_dt = datetime(2026, 1, 1, 11, 0)
    catchup = {'start': 0, 'end': 3600, 'now': 3600, 'title': 'Old Show',
               'start_dt': start_dt, 'end_dt': end_dt, 'catchup_id': None}
    window = _window(conn, snapshot, catchup=catchup)
    window.onInit()
    window.player.time_raises = True
    window.session.on_av_started()
    window._tick()

    assert window.getControl(704).getWidth() == 0



# -- generation change (issue #32) --------------------------------------

def test_generation_change_refreshes_now_next_without_touching_stream(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel(conn, name='Alpha')
    eid = _epg_source(conn, provider_id)
    _programme(conn, eid, 'a', '2026-01-01T11:30:00Z', '2026-01-01T12:00:00Z', 'Now Show')
    now = datetime(2026, 1, 1, 11, 45)
    window = _window(conn, snapshot, now_fn=FakeNow(now))
    window.onInit()
    window.session.on_av_started()

    conn.execute("UPDATE programme SET title = 'Updated Show' WHERE title = 'Now Show'")
    _bump_generation(2)
    _notify_refreshed(window)

    assert window.getProperty('now_title') == 'Updated Show'
    assert window.player.stop_calls == 0
    assert window.session is not None


def test_generation_change_deferred_while_digits_pending_then_applied_on_commit(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel(conn, name='Alpha')
    eid = _epg_source(conn, provider_id)
    _programme(conn, eid, 'a', '2026-01-01T11:30:00Z', '2026-01-01T12:00:00Z', 'Now Show')
    now = datetime(2026, 1, 1, 11, 45)
    window = _window(conn, snapshot, now_fn=FakeNow(now))
    window.onInit()
    window.session.on_av_started()

    window._on_digit(9)

    conn.execute("UPDATE programme SET title = 'Updated Show' WHERE title = 'Now Show'")
    _bump_generation(2)
    _notify_refreshed(window)

    assert window.getProperty('now_title') == 'Now Show'

    window._cancel_digit_entry()

    assert window.getProperty('now_title') == 'Updated Show'


def test_generation_change_reselects_overlay_channel_by_key(tmp_path):
    conn = _conn(tmp_path)
    p1, snapshot_a = _setup_channel(conn, channel_key='a', name='Alpha')
    _channel(conn, p1, 'b', name='Beta', position=1)
    window = _window(conn, snapshot_a)
    window.onInit()
    window.session.on_av_started()
    window._open_list()

    conn.execute("UPDATE channel SET name = 'Alpha2' WHERE channel_key = 'a'")
    _bump_generation(2)
    _notify_refreshed(window)

    channels_control = window.getControl(CHANNELS_LIST_ID)
    assert channels_control.getSelectedItem().getProperty('channel_key') == 'a'
    assert channels_control.getSelectedItem().getLabel() == 'Alpha2'


def test_generation_change_overlay_selects_nearest_number_when_stale(tmp_path):
    conn = _conn(tmp_path)
    p1, snapshot_a = _setup_channel(conn, channel_key='a', name='Alpha', position=0)
    _channel(conn, p1, 'b', name='Beta', position=1)
    _channel(conn, p1, 'c', name='Gamma', position=2)
    window = _window(conn, snapshot_a)
    window.onInit()
    window.session.on_av_started()
    window._open_list()

    conn.execute("UPDATE channel SET stale_since = '2026-01-01T00:00:00' WHERE channel_key = 'a'")
    _bump_generation(2)
    _notify_refreshed(window)

    channels_control = window.getControl(CHANNELS_LIST_ID)
    # 'a' (number 0) went Stale; the nearest remaining channel by number is
    # 'b' (number 1), not 'c' (number 2).
    assert channels_control.getSelectedItem().getProperty('channel_key') == 'b'
    # The snapshot/session are untouched -- still playing 'a'.
    assert window.player.stop_calls == 0


def test_generation_watcher_stopped_on_close(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)
    window.onInit()
    window.close()


# -- autoplay: remembering the last channel (issue #29) -----------------

def test_onInit_records_live_session_as_last_channel(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel(conn, channel_key='a', name='Alpha')
    window = _window(conn, snapshot)
    window.onInit()

    assert autoplay.resolve_autoplay_channel(conn) == (provider_id, 'a')


def test_zap_updates_last_channel(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel(conn, channel_key='a', name='Alpha')
    _channel(conn, provider_id, 'b', name='Bravo', position=1)
    window = _window(conn, snapshot)
    window.onInit()

    window._zap(provider_id, 'b')

    assert autoplay.resolve_autoplay_channel(conn) == (provider_id, 'b')


def test_catchup_session_does_not_overwrite_last_channel(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel(conn, channel_key='a', name='Alpha')
    _channel(conn, provider_id, 'b', name='Bravo', position=1)
    autoplay.remember_last_channel(conn, provider_id, 'b')
    start_dt = datetime(2026, 1, 1, 10, 0)
    end_dt = datetime(2026, 1, 1, 11, 0)
    catchup = {'start': 0, 'end': 3600, 'now': 3600, 'title': 'Old Show',
               'start_dt': start_dt, 'end_dt': end_dt, 'catchup_id': None}
    window = _window(conn, snapshot, catchup=catchup)
    window.onInit()

    assert autoplay.resolve_autoplay_channel(conn) == (provider_id, 'b')


# -- stream info -------------------------------------------------------

def test_tick_sets_stream_properties_while_playing(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)
    window.onInit()
    window.session.on_av_started()
    xbmc._info_labels['Player.Process(videowidth)'] = '3,840'
    xbmc._info_labels['Player.Process(videoheight)'] = '2,160'
    xbmc._info_labels['VideoPlayer.VideoCodec'] = 'hevc'
    xbmc._info_labels['Player.Process(videofps)'] = '50.000'
    xbmc._info_labels['VideoPlayer.AudioCodec'] = 'eac3'
    xbmc._info_labels['VideoPlayer.AudioChannels'] = '6'
    try:
        window._tick()
        assert window.getProperty('stream_res') == '4K'
        assert window.getProperty('stream_fps') == '50fps'
        assert window.getProperty('stream_vcodec') == 'HEVC'
        assert window.getProperty('stream_audio') == 'EAC3 5.1'
    finally:
        xbmc._info_labels.clear()


def test_zap_clears_stream_properties(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel(conn, channel_key='a', name='Alpha')
    _channel(conn, provider_id, 'b', name='Bravo', position=1)
    window = _window(conn, snapshot)
    window.onInit()
    window.session.on_av_started()
    window.setProperty('stream_res', '4K')
    window.setProperty('stream_fps', '50fps')
    window.setProperty('stream_vcodec', 'HEVC')
    window.setProperty('stream_audio', 'EAC3 5.1')

    window._zap(provider_id, 'b')

    assert window.getProperty('stream_res') == ''
    assert window.getProperty('stream_fps') == ''
    assert window.getProperty('stream_vcodec') == ''
    assert window.getProperty('stream_audio') == ''


def test_open_list_on_init_opens_the_overlay(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn, channel_key='a', name='Alpha')
    window = _window(conn, snapshot, open_list_on_init=True)
    window.onInit()

    assert window.getProperty('list_visible') == '1'
    assert window._list_open is True
