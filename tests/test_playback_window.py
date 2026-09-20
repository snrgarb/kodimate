# -*- coding: utf-8 -*-
import threading
from datetime import datetime, timedelta

import pytest

from kodimate import autoplay, channels, db, playback
from kodimate.windows.playback import (
    PlaybackWindow, GROUPS_LIST_ID, CHANNELS_LIST_ID, PROGRESS_FILL_ID,
    PROGRAMME_ROW_ID, SEEK_ROW_ID, BTN_REWIND_ID, BTN_PLAYPAUSE_ID,
    BTN_FASTFORWARD_ID, BTN_LIVE_ID,
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
        self.total_time = 0
        self.seek_calls = []
        self.pause_calls = 0

    def play(self, url, headers, mime_type=None):
        self.plays.append((url, headers))

    def stop(self):
        self.stop_calls += 1

    def getTime(self):
        if self.time_raises:
            raise RuntimeError('no time')
        return self.time

    def getTotalTime(self):
        return self.total_time

    def seekTime(self, seconds):
        self.seek_calls.append(seconds)
        self.time = seconds

    def pause(self):
        self.pause_calls += 1

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
        seek_steps=[-600, -300, -180, -60, -30, -10, 10, 30, 60, 180, 300, 600],
        seek_delay_ms=750,
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


def test_on_init_inhibits_screensaver(tmp_path):
    xbmc.executebuiltin_calls[:] = []
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)

    window.onInit()

    assert 'InhibitScreensaver(true)' in xbmc.executebuiltin_calls


def test_close_uninhibits_screensaver_once(tmp_path):
    xbmc.executebuiltin_calls[:] = []
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)
    window.onInit()

    window.close()

    assert xbmc.executebuiltin_calls.count('InhibitScreensaver(false)') == 1

    window.close()

    assert xbmc.executebuiltin_calls.count('InhibitScreensaver(false)') == 1


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


def test_osd_position_defaults_to_top(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot, osd_position=None)

    assert window.getProperty('osd_position') == 'top'


def test_osd_position_bottom_override(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot, osd_position='bottom')

    assert window.getProperty('osd_position') == 'bottom'


def test_osd_position_invalid_value_normalises_to_top(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot, osd_position='sideways')

    assert window.getProperty('osd_position') == 'top'


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
    assert window.getControl(706).getX() == 1232  # 940 + 300 - 8 (focused, 16px knob)
    assert window.getControl(706).getY() == 74


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
    window.setFocusId(BTN_PLAYPAUSE_ID)

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
    window.setFocusId(PROGRAMME_ROW_ID)
    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_UP))
    channels_control = window.getControl(201)
    target_position = next(
        i for i, item in enumerate(channels_control._items) if item.getProperty('channel_key') == 'b'
    )
    channels_control.selectItem(target_position)

    window.onClick(201)
    window.on_stopped()  # old stream's stop callback, arriving after abort()

    assert window.getProperty('list_visible') == '0'
    assert window.getProperty('channel_name') == 'Bravo'
    assert window.session.state == 'connecting'


def test_click_on_channels_list_ignored_when_list_closed(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel(conn, channel_key='a', name='Alpha')
    _channel(conn, provider_id, 'b', name='Bravo', position=1)
    window = _window(conn, snapshot)
    window.onInit()
    window.setFocusId(PROGRAMME_ROW_ID)
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
    window.setFocusId(PROGRAMME_ROW_ID)
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
    window.setFocusId(PROGRAMME_ROW_ID)
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
    window.setFocusId(PROGRAMME_ROW_ID)
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
    window.on_stopped()  # old stream's stop callback, arriving after abort()

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
    window.setFocusId(BTN_PLAYPAUSE_ID)
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

    window.on_stopped()  # old stream's stop callback, arriving after abort()

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
    window.setFocusId(BTN_PLAYPAUSE_ID)
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
    window.scheduler.advance(3)  # pending-transition fallback: no stop callback arrives here

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
    window.on_stopped()  # old stream's stop callback, arriving after abort()

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


def test_tick_leaves_stream_properties_unset_until_all_resolved(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)
    window.onInit()
    window.session.on_av_started()
    xbmc._info_labels['Player.Process(videowidth)'] = '3,840'
    xbmc._info_labels['Player.Process(videoheight)'] = '2,160'
    xbmc._info_labels['VideoPlayer.VideoCodec'] = 'hevc'
    xbmc._info_labels['Player.Process(videofps)'] = '0'
    xbmc._info_labels['VideoPlayer.AudioCodec'] = 'eac3'
    xbmc._info_labels['VideoPlayer.AudioChannels'] = '6'
    try:
        window._tick()
        assert window.getProperty('stream_res') == ''
        assert window.getProperty('stream_fps') == ''
        assert window.getProperty('stream_vcodec') == ''
        assert window.getProperty('stream_audio') == ''

        xbmc._info_labels['Player.Process(videofps)'] = '50'
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
    window.on_stopped()  # old stream's stop callback, arriving after abort()

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


# -- OSD Left/Right programme stepping (issue #30) --------------------------

import calendar as _calendar


def _epoch(dt):
    return _calendar.timegm(dt.utctimetuple())


def _setup_channel_with_programmes(conn):
    provider_id, snapshot = _setup_channel(conn, channel_key='a', name='Alpha')
    eid = _epg_source(conn, provider_id)
    _programme(conn, eid, 'a', '2026-01-01T10:00:00Z', '2026-01-01T11:00:00Z', 'Show1')
    _programme(conn, eid, 'a', '2026-01-01T11:00:00Z', '2026-01-01T12:00:00Z', 'Show2')
    _programme(conn, eid, 'a', '2026-01-01T12:00:00Z', '2026-01-01T13:00:00Z', 'Show3')
    _programme(conn, eid, 'a', '2026-01-01T13:00:00Z', '2026-01-01T14:00:00Z', 'Show4')
    snapshot['catchup_mode'] = 'shift'
    snapshot['catchup_days'] = 3
    return provider_id, snapshot


def test_left_right_do_not_open_list(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel_with_programmes(conn)
    now = datetime(2026, 1, 1, 12, 30)
    window = _window(conn, snapshot, now_fn=FakeNow(now))
    window.onInit()
    window.session.on_av_started()
    window.setFocusId(PROGRAMME_ROW_ID)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))
    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))

    assert window.getProperty('list_visible') == '0'
    assert window._list_open is False


def test_up_down_still_open_list_in_playback(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel_with_programmes(conn)
    now = datetime(2026, 1, 1, 12, 30)
    window = _window(conn, snapshot, now_fn=FakeNow(now))
    window.onInit()
    window.session.on_av_started()
    window.setFocusId(PROGRAMME_ROW_ID)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_UP))

    assert window.getProperty('list_visible') == '1'


def test_step_left_updates_osd_immediately_without_stream_change(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel_with_programmes(conn)
    now = datetime(2026, 1, 1, 12, 30)
    window = _window(conn, snapshot, now_fn=FakeNow(now))
    window.onInit()
    window.session.on_av_started()
    window.setFocusId(PROGRAMME_ROW_ID)
    plays_before = len(window.player.plays)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))

    assert window.getProperty('now_title') == 'Show2'
    assert len(window.player.plays) == plays_before


def test_step_commits_after_debounce_with_exactly_one_play(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel_with_programmes(conn)
    now = datetime(2026, 1, 1, 12, 30)
    window = _window(conn, snapshot, now_fn=FakeNow(now))
    window.onInit()
    window.session.on_av_started()
    window.setFocusId(PROGRAMME_ROW_ID)
    plays_before = len(window.player.plays)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))
    window.scheduler.advance(1.5)
    window.on_stopped()  # old stream's stop callback, arriving after abort()

    assert len(window.player.plays) == plays_before + 1
    assert window.catchup is not None
    assert window.catchup['title'] == 'Show2'


def test_rapid_left_presses_commit_only_once(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel_with_programmes(conn)
    now = datetime(2026, 1, 1, 12, 30)
    window = _window(conn, snapshot, now_fn=FakeNow(now))
    window.onInit()
    window.session.on_av_started()
    window.setFocusId(PROGRAMME_ROW_ID)
    plays_before = len(window.player.plays)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))
    window.scheduler.advance(0.5)
    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))
    window.scheduler.advance(0.5)
    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))

    assert len(window.player.plays) == plays_before
    assert window.getProperty('now_title') == 'Show1'

    window.scheduler.advance(1.5)
    window.on_stopped()  # old stream's stop callback, arriving after abort()

    assert len(window.player.plays) == plays_before + 1
    assert window.catchup['title'] == 'Show1'


def test_step_clamps_at_earliest_loaded_programme(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel_with_programmes(conn)
    now = datetime(2026, 1, 1, 10, 30)  # Show1 is "now"
    window = _window(conn, snapshot, now_fn=FakeNow(now))
    window.onInit()
    window.session.on_av_started()
    window.setFocusId(PROGRAMME_ROW_ID)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))

    assert window.getProperty('now_title') == 'Show1'
    assert window.scheduler.pending_count() == 0 or window._step_timer is None


def test_back_cancels_pending_step_and_restores_osd(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel_with_programmes(conn)
    now = datetime(2026, 1, 1, 12, 30)
    window = _window(conn, snapshot, now_fn=FakeNow(now))
    window.onInit()
    window.session.on_av_started()
    window.setFocusId(PROGRAMME_ROW_ID)
    plays_before = len(window.player.plays)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))
    assert window.getProperty('now_title') == 'Show2'

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))

    assert window.getProperty('now_title') == 'Show3'
    assert window._step_programme is None
    window.scheduler.advance(1.5)
    assert len(window.player.plays) == plays_before


def test_step_to_now_while_in_catchup_goes_live(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel_with_programmes(conn)
    now = datetime(2026, 1, 1, 12, 30)  # Show3 airing now
    start_dt = datetime(2026, 1, 1, 11, 0)
    end_dt = datetime(2026, 1, 1, 12, 0)
    catchup_dict = {
        'start': _epoch(start_dt), 'end': _epoch(end_dt), 'now': _epoch(now),
        'title': 'Show2', 'start_dt': start_dt, 'end_dt': end_dt, 'catchup_id': None,
    }
    window = _window(conn, snapshot, now_fn=FakeNow(now), catchup=catchup_dict)
    window.onInit()
    window.session.on_av_started()
    window.setFocusId(PROGRAMME_ROW_ID)
    assert window.getProperty('catchup') == '1'

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))
    window.scheduler.advance(1.5)
    window.on_stopped()  # old stream's stop callback, arriving after abort()

    assert window.catchup is None
    assert window.getProperty('catchup') == '0'


def test_ok_on_bar_visible_opens_dialog_and_starts_catchup(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel_with_programmes(conn)
    now = datetime(2026, 1, 1, 12, 30)  # Show3 airing now

    class _Dialog(object):
        opened_with = None
        result = 'start_over'

        @classmethod
        def open(cls, **kwargs):
            _Dialog.opened_with = kwargs
            return cls()

    window = _window(conn, snapshot, now_fn=FakeNow(now), dialog_cls=_Dialog)
    window.onInit()
    window.session.on_av_started()
    window.setFocusId(PROGRAMME_ROW_ID)
    plays_before = len(window.player.plays)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
    window.on_stopped()  # old stream's stop callback, arriving after abort()

    assert _Dialog.opened_with['title'] == 'Show3'
    assert 'start_over' in _Dialog.opened_with['actions']
    assert window.catchup is not None
    assert window.catchup['title'] == 'Show3'
    assert len(window.player.plays) == plays_before + 1


def test_ok_on_bar_visible_watch_live_from_catchup(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel_with_programmes(conn)
    now = datetime(2026, 1, 1, 12, 30)
    start_dt = datetime(2026, 1, 1, 11, 0)
    end_dt = datetime(2026, 1, 1, 12, 0)
    catchup_dict = {
        'start': _epoch(start_dt), 'end': _epoch(end_dt), 'now': _epoch(now),
        'title': 'Show2', 'start_dt': start_dt, 'end_dt': end_dt, 'catchup_id': None,
    }

    class _Dialog(object):
        result = 'watch_live'

        @classmethod
        def open(cls, **kwargs):
            return cls()

    window = _window(conn, snapshot, now_fn=FakeNow(now), catchup=catchup_dict, dialog_cls=_Dialog)
    window.onInit()
    window.session.on_av_started()
    window.setFocusId(PROGRAMME_ROW_ID)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
    window.on_stopped()  # old stream's stop callback, arriving after abort()

    assert window.catchup is None
    assert window.getProperty('catchup') == '0'


def test_ok_on_bar_visible_cancels_pending_step(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel_with_programmes(conn)
    now = datetime(2026, 1, 1, 12, 30)

    class _Dialog(object):
        result = None

        @classmethod
        def open(cls, **kwargs):
            return cls()

    window = _window(conn, snapshot, now_fn=FakeNow(now), dialog_cls=_Dialog)
    window.onInit()
    window.session.on_av_started()
    window.setFocusId(PROGRAMME_ROW_ID)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))
    window.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert window._step_timer is None
    assert window._step_programme is None


# -- CATCH-UP position/duration label (issue #30) ----------------------------

def test_catchup_bar_shows_position_over_duration(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    snapshot['catchup_mode'] = 'shift'
    start_dt = datetime(2026, 1, 1, 10, 0)
    end_dt = datetime(2026, 1, 1, 11, 0)
    catchup_dict = {'start': 0, 'end': 3600, 'now': 3600, 'title': 'Old Show',
                     'start_dt': start_dt, 'end_dt': end_dt, 'catchup_id': None}
    window = _window(conn, snapshot, catchup=catchup_dict)
    window.onInit()
    window.player.time = 900
    window.session.on_av_started()
    window._tick()

    assert window.getProperty('now_times') == u'0:15:00 / 1:00:00'


# -- Up-next countdown (issue #30) -------------------------------------------

def _catchup_end_setup(conn, next_state='live'):
    provider_id, snapshot = _setup_channel_with_programmes(conn)
    start_dt = datetime(2026, 1, 1, 11, 0)
    end_dt = datetime(2026, 1, 1, 12, 0)
    now = datetime(2026, 1, 1, 12, 30) if next_state == 'live' else datetime(2026, 1, 1, 13, 30)
    catchup_dict = {
        'start': _epoch(start_dt), 'end': _epoch(end_dt), 'now': _epoch(end_dt),
        'title': 'Show2', 'start_dt': start_dt, 'end_dt': end_dt, 'catchup_id': None,
    }
    window = _window(conn, snapshot, now_fn=FakeNow(now), catchup=catchup_dict)
    return window


def test_tick_reaching_duration_starts_upnext_countdown(tmp_path):
    conn = _conn(tmp_path)
    window = _catchup_end_setup(conn)
    window.onInit()
    window.session.on_av_started()
    window.player.time = 3600  # duration = end(3600) - start(0) = 3600

    window._tick()

    assert window.getProperty('upnext') == '1'
    assert window.getProperty('upnext_title') == 'Show3'
    assert window.getProperty('upnext_seconds') == '5'
    assert window.player.stop_calls == 0  # video kept playing under the countdown


def test_upnext_countdown_ticks_down_and_awaits_stopped_before_playing_next(tmp_path):
    conn = _conn(tmp_path)
    window = _catchup_end_setup(conn)
    window.onInit()
    window.session.on_av_started()
    window.player.time = 3600
    window._tick()
    plays_before = len(window.player.plays)

    for _ in range(5):
        window.scheduler.advance(1)

    assert window.getProperty('upnext') == '0'
    assert window.player.stop_calls == 1
    assert len(window.player.plays) == plays_before  # not yet -- awaiting onPlayBackStopped

    window.on_stopped()

    assert len(window.player.plays) == plays_before + 1
    assert window.catchup is None  # Show3 is airing now -> live
    assert window.getProperty('catchup') == '0'


def test_upnext_fallback_timer_proceeds_if_stopped_callback_never_arrives(tmp_path):
    conn = _conn(tmp_path)
    window = _catchup_end_setup(conn)
    window.onInit()
    window.session.on_av_started()
    window.player.time = 3600
    window._tick()
    plays_before = len(window.player.plays)

    for _ in range(5):
        window.scheduler.advance(1)  # expiry: player.stop() called, awaiting callback
    window.scheduler.advance(3)  # fallback fires

    assert len(window.player.plays) == plays_before + 1
    assert window.catchup is None


def test_upnext_next_programme_past_starts_catchup_session(tmp_path):
    conn = _conn(tmp_path)
    window = _catchup_end_setup(conn, next_state='past')
    window.onInit()
    window.session.on_av_started()
    window.player.time = 3600
    window._tick()
    for _ in range(5):
        window.scheduler.advance(1)
    plays_before = len(window.player.plays)

    window.on_stopped()

    assert len(window.player.plays) == plays_before + 1
    assert window.catchup is not None
    assert window.catchup['title'] == 'Show3'


def test_upnext_no_next_programme_closes_window(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel(conn, channel_key='a', name='Alpha')
    eid = _epg_source(conn, provider_id)
    start_dt = datetime(2026, 1, 1, 11, 0)
    end_dt = datetime(2026, 1, 1, 12, 0)
    _programme(conn, eid, 'a', '2026-01-01T11:00:00Z', '2026-01-01T12:00:00Z', 'Show2')
    now = datetime(2026, 1, 1, 12, 30)
    catchup_dict = {
        'start': _epoch(start_dt), 'end': _epoch(end_dt), 'now': _epoch(end_dt),
        'title': 'Show2', 'start_dt': start_dt, 'end_dt': end_dt, 'catchup_id': None,
    }
    window = _window(conn, snapshot, now_fn=FakeNow(now), catchup=catchup_dict)
    window.onInit()
    window.session.on_av_started()
    window.player.time = 3600
    window._tick()

    for _ in range(5):
        window.scheduler.advance(1)
    window.on_stopped()

    assert window._stop_event.is_set()


def test_back_during_upnext_countdown_aborts_and_closes(tmp_path):
    conn = _conn(tmp_path)
    window = _catchup_end_setup(conn)
    window.onInit()
    window.session.on_av_started()
    window.player.time = 3600
    window._tick()

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))

    assert window._stop_event.is_set()
    assert window.player.stop_calls >= 1


def test_up_down_during_upnext_cancels_countdown_and_opens_list(tmp_path):
    conn = _conn(tmp_path)
    window = _catchup_end_setup(conn)
    window.onInit()
    window.session.on_av_started()
    window.player.time = 3600
    window._tick()
    window.setFocusId(PROGRAMME_ROW_ID)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_UP))

    assert window.getProperty('upnext') == '0'
    assert window.getProperty('list_visible') == '1'


def test_on_ended_near_duration_routes_to_upnext_instead_of_reconnect(tmp_path):
    conn = _conn(tmp_path)
    window = _catchup_end_setup(conn)
    window.onInit()
    window.session.on_av_started()
    window.player.time = 3598  # within the 5s tolerance of duration=3600

    window.on_ended()

    assert window.getProperty('upnext') == '1'
    assert window.getProperty('state') != 'reconnecting'


# -- Back from Catch-up (issue #30) ------------------------------------------

def test_back_on_bare_video_bar_hidden_in_catchup_closes_and_stops(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    snapshot['catchup_mode'] = 'shift'
    start_dt = datetime(2026, 1, 1, 10, 0)
    end_dt = datetime(2026, 1, 1, 11, 0)
    catchup_dict = {'start': 0, 'end': 3600, 'now': 3600, 'title': 'Old Show',
                     'start_dt': start_dt, 'end_dt': end_dt, 'catchup_id': None}
    window = _window(conn, snapshot, catchup=catchup_dict)
    window.onInit()
    window.session.on_av_started()
    window._hide_bar()
    assert window.getProperty('bar_visible') == '0'

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))

    assert window._stop_event.is_set()
    assert window.player.stop_calls >= 1


def test_action_stop_aborts_and_closes(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)
    window.onInit()
    window.session.on_av_started()
    stops_before = window.player.stop_calls

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_STOP))

    assert window.player.stop_calls > stops_before
    assert window._stop_event.is_set()


# -- OSD transport controls: seek stepping, pause/resume, behind-live -------

def test_bar_shown_defaults_focus_to_seek_row(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)
    window.onInit()

    assert window.getFocusId() == SEEK_ROW_ID


def test_programme_row_up_opens_list(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)
    window.onInit()
    window.setFocusId(PROGRAMME_ROW_ID)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_UP))

    assert window.getProperty('list_visible') == '1'


def test_programme_row_down_moves_focus_to_seek_row(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)
    window.onInit()
    window.setFocusId(PROGRAMME_ROW_ID)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_DOWN))

    assert window.getFocusId() == SEEK_ROW_ID
    assert window.getProperty('list_visible') == '0'


def test_seek_row_up_moves_focus_to_programme_row(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)
    window.onInit()
    window.setFocusId(SEEK_ROW_ID)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_UP))

    assert window.getFocusId() == PROGRAMME_ROW_ID
    assert window.getProperty('list_visible') == '0'


def test_seek_row_down_moves_focus_to_playpause_button(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)
    window.onInit()
    window.setFocusId(SEEK_ROW_ID)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_DOWN))

    assert window.getFocusId() == BTN_PLAYPAUSE_ID
    assert window.getProperty('list_visible') == '0'


def test_seek_left_in_buffer_calls_seektime_natively(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel_with_programmes(conn)
    now = datetime(2026, 1, 1, 12, 30)
    window = _window(conn, snapshot, now_fn=FakeNow(now))
    window.onInit()
    window.session.on_av_started()
    window.player.total_time = 100
    window.player.time = 50
    window.setFocusId(SEEK_ROW_ID)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))
    assert window.getProperty('seek_step') == '-10s'

    window.scheduler.advance(0.75)

    assert window.player.seek_calls == [40]
    assert window.getProperty('seek_step') == ''
    assert window.catchup is None


def test_seek_outside_buffer_rebuilds_catchup_session(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel_with_programmes(conn)
    now = datetime(2026, 1, 1, 12, 30)  # Show3 12:00-13:00 airing
    window = _window(
        conn, snapshot, now_fn=FakeNow(now),
        seek_steps=[-3600, -1800, -600, 600, 1800, 3600],
    )
    window.onInit()
    window.session.on_av_started()
    window.player.total_time = 100
    window.player.time = 50
    window.setFocusId(SEEK_ROW_ID)
    plays_before = len(window.player.plays)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_BIG_STEP_BACK))
    window.scheduler.advance(0.75)
    window.on_stopped()  # old stream's stop callback, arriving after abort()

    assert window.catchup is not None
    assert window.catchup['title'] == 'Show2'
    assert window.catchup['offset'] > 0
    assert len(window.player.plays) == plays_before + 1


def test_seek_left_on_unseekable_live_stream_starts_over_airing_programme(tmp_path):
    # Regression: rewind on a live, unseekable (getTotalTime()==0) TS stream
    # used to _zap() the live URL for a still-airing programme, which the
    # provider then refused as an immediate reconnect ("unavailable"). It
    # must instead rebuild a Catch-up (Start Over) session for that
    # programme, and only once the old stream's own stop callback (or the
    # fallback) arrives -- never forwarding that stop to the new session.
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel_with_programmes(conn)
    now = datetime(2026, 1, 1, 12, 30)  # Show3 12:00-13:00 airing
    window = _window(conn, snapshot, now_fn=FakeNow(now))
    window.onInit()
    window.session.on_av_started()
    window.player.total_time = 0  # unseekable live TS: no player buffer
    window.player.time = 0
    window.setFocusId(SEEK_ROW_ID)
    plays_before = len(window.player.plays)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))
    window.scheduler.advance(0.75)

    # The old stream's stop callback has not arrived yet: no new play, and
    # the OSD shows 'connecting', never a 'stopped' flash.
    assert len(window.player.plays) == plays_before
    assert window.getProperty('state') == 'connecting'

    old_session = window.session
    window.on_stopped()  # old stream's stop callback, arriving after abort()

    assert window.session is not old_session
    assert window.catchup is not None
    assert window.catchup['title'] == 'Show3'
    assert window.catchup['start'] == _epoch(datetime(2026, 1, 1, 12, 0))
    # now (12:30) is 1800s into Show3 (12:00-13:00); a 10s rewind targets 1790s in.
    assert window.catchup['offset'] == 1790
    assert len(window.player.plays) == plays_before + 1


def test_seek_rebuild_fallback_starts_session_if_no_stop_arrives(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel_with_programmes(conn)
    now = datetime(2026, 1, 1, 12, 30)  # Show3 12:00-13:00 airing
    window = _window(conn, snapshot, now_fn=FakeNow(now))
    window.onInit()
    window.session.on_av_started()
    window.player.total_time = 0
    window.player.time = 0
    window.setFocusId(SEEK_ROW_ID)
    plays_before = len(window.player.plays)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))
    window.scheduler.advance(0.75)
    assert len(window.player.plays) == plays_before

    window.scheduler.advance(3)  # no stop callback ever arrives

    assert window.catchup is not None
    assert window.catchup['title'] == 'Show3'
    assert len(window.player.plays) == plays_before + 1


def test_seek_rebuild_old_stream_stop_not_forwarded_to_old_session(tmp_path):
    # The defect: the outgoing session's onPlayBackStopped/Ended, arriving
    # after _replace_session() already asked it to abort, used to be
    # forwarded straight to whatever `self.session` was (see
    # _on_player_stop_or_end) -- by the time it arrived that was already
    # the freshly-started new session, so the stale callback aborted it.
    # It must instead be consumed to drive the deferred transition, never
    # reach a session's on_stopped/on_ended at all.
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel_with_programmes(conn)
    now = datetime(2026, 1, 1, 12, 30)  # Show3 12:00-13:00 airing
    window = _window(conn, snapshot, now_fn=FakeNow(now))
    window.onInit()
    window.session.on_av_started()
    window.player.total_time = 0
    window.player.time = 0
    window.setFocusId(SEEK_ROW_ID)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))
    window.scheduler.advance(0.75)
    old_session = window.session
    stop_forwarded = []
    old_session.on_stopped = lambda: stop_forwarded.append(True)

    window.on_stopped()  # old stream's stop callback, arriving after abort()

    assert stop_forwarded == []
    assert window.session is not old_session
    assert window.catchup is not None


def test_back_while_transition_pending_cancels_it(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel_with_programmes(conn)
    now = datetime(2026, 1, 1, 12, 30)  # Show3 12:00-13:00 airing
    window = _window(conn, snapshot, now_fn=FakeNow(now))
    window.onInit()
    window.session.on_av_started()
    window.player.total_time = 0
    window.player.time = 0
    window.setFocusId(SEEK_ROW_ID)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))
    window.scheduler.advance(0.75)
    assert window.getProperty('state') == 'connecting'

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))

    assert window.getProperty('state') == 'stopped'
    assert window._pending_transition is None

    window.on_stopped()  # a late stop callback must not resurrect the transition

    assert window.catchup is None
    assert window.getProperty('state') == 'stopped'


def test_seek_disabled_on_channel_without_catchup_window(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)
    window.onInit()
    window.session.on_av_started()
    window.player.total_time = 100
    window.player.time = 50
    window.setFocusId(SEEK_ROW_ID)

    assert window.getProperty('seekable') == '0'

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))
    assert window.getProperty('seek_step') == ''
    window.scheduler.advance(0.75)
    assert window.player.seek_calls == []

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_PLAYER_REWIND))
    assert window.getProperty('seek_step') == ''
    window.scheduler.advance(0.75)
    assert window.player.seek_calls == []

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_BIG_STEP_BACK))
    assert window.getProperty('seek_step') == ''
    window.scheduler.advance(0.75)
    assert window.player.seek_calls == []

    window.onClick(BTN_REWIND_ID)
    assert window.getProperty('seek_step') == ''
    window.scheduler.advance(0.75)
    assert window.player.seek_calls == []


def test_pause_still_works_on_channel_without_catchup_window(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)
    window.onInit()
    window.session.on_av_started()
    window.player.total_time = 100
    window.player.time = 50

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_PAUSE))

    assert window.getProperty('paused') == '1'
    assert window.player.pause_calls == 1

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_PAUSE))

    assert window.getProperty('paused') == '0'
    assert window.player.pause_calls == 2


def test_seekable_property_set_when_channel_has_catchup_window(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    snapshot['catchup_days'] = 3
    snapshot['catchup_mode'] = 'shift'
    window = _window(conn, snapshot)
    window.onInit()
    window.session.on_av_started()
    window.player.total_time = 100
    window.player.time = 50
    window.setFocusId(SEEK_ROW_ID)

    assert window.getProperty('seekable') == '1'

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))
    assert window.getProperty('seek_step') == '-10s'
    window.scheduler.advance(0.75)
    assert window.player.seek_calls == [40]


def test_button_row_excludes_rewind_and_fastforward_when_not_seekable(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)
    window.onInit()
    assert window.getProperty('seekable') == '0'

    assert BTN_REWIND_ID not in window._visible_button_row_ids()
    assert BTN_FASTFORWARD_ID not in window._visible_button_row_ids()


def test_pause_cancels_pending_seek(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    snapshot['catchup_days'] = 3
    snapshot['catchup_mode'] = 'shift'
    window = _window(conn, snapshot)
    window.onInit()
    window.session.on_av_started()
    window.player.total_time = 100
    window.player.time = 50
    window.setFocusId(SEEK_ROW_ID)
    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))
    assert window.getProperty('seek_step') == '-10s'

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_PAUSE))

    assert window.getProperty('seek_step') == ''
    assert window._seek_timer is None
    window.scheduler.advance(0.75)
    assert window.player.seek_calls == []


def test_seek_committed_while_paused_in_buffer_stays_paused(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    snapshot['catchup_days'] = 3
    snapshot['catchup_mode'] = 'shift'
    window = _window(conn, snapshot)
    window.onInit()
    window.session.on_av_started()
    window.player.total_time = 100
    window.player.time = 50
    window.onAction(xbmcgui.Action(xbmcgui.ACTION_PAUSE))
    assert window.getProperty('paused') == '1'
    window.setFocusId(SEEK_ROW_ID)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))
    window.scheduler.advance(0.75)

    assert window.player.seek_calls == [40]
    assert window.getProperty('paused') == '1'


def test_seek_committed_while_paused_beyond_buffer_clears_paused(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel_with_programmes(conn)
    now = datetime(2026, 1, 1, 12, 30)  # Show3 12:00-13:00 airing
    window = _window(
        conn, snapshot, now_fn=FakeNow(now),
        seek_steps=[-3600, -1800, -600, 600, 1800, 3600],
    )
    window.onInit()
    window.session.on_av_started()
    window.player.total_time = 100
    window.player.time = 50
    window.onAction(xbmcgui.Action(xbmcgui.ACTION_PAUSE))
    assert window.getProperty('paused') == '1'
    window.setFocusId(SEEK_ROW_ID)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_BIG_STEP_BACK))
    window.scheduler.advance(0.75)
    assert window.getProperty('paused') == '0'  # cleared synchronously, not deferred

    window.on_stopped()  # old stream's stop callback, arriving after abort()

    assert window.catchup is not None
    assert window.catchup['title'] == 'Show2'
    assert window.getProperty('paused') == '0'


def test_seek_forward_past_live_edge_goes_live(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel_with_programmes(conn)
    now = datetime(2026, 1, 1, 12, 30)
    start_dt = datetime(2026, 1, 1, 11, 0)
    end_dt = datetime(2026, 1, 1, 12, 0)
    catchup_dict = {
        'start': _epoch(start_dt), 'end': _epoch(end_dt), 'now': _epoch(now),
        'title': 'Show2', 'start_dt': start_dt, 'end_dt': end_dt, 'catchup_id': None,
    }
    window = _window(
        conn, snapshot, now_fn=FakeNow(now), catchup=catchup_dict,
        seek_steps=[-6000, 6000],
    )
    window.onInit()
    window.session.on_av_started()
    window.setFocusId(SEEK_ROW_ID)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_BIG_STEP_FORWARD))
    window.scheduler.advance(0.75)
    window.on_stopped()  # old stream's stop callback, arriving after abort()

    assert window.catchup is None
    assert window.getProperty('catchup') == '0'


def test_seek_in_catchup_range_is_native_even_with_zero_total_time(tmp_path):
    # Regression: the catch-up stream is a fixed range served over HTTP,
    # whose getTotalTime() is frequently 0 -- treating that as "no buffer"
    # forced a rebuild on every single FF/rewind press inside a catch-up
    # session ("fast-forward in a catch-up session completely broken").
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel_with_programmes(conn)
    now = datetime(2026, 1, 1, 12, 30)
    start_dt = datetime(2026, 1, 1, 12, 0)  # Show3 12:00-13:00, airing now
    end_dt = datetime(2026, 1, 1, 13, 0)
    catchup_dict = {
        'start': _epoch(start_dt), 'end': _epoch(end_dt), 'now': _epoch(now),
        'title': 'Show3', 'start_dt': start_dt, 'end_dt': end_dt, 'catchup_id': None,
    }
    window = _window(conn, snapshot, now_fn=FakeNow(now), catchup=catchup_dict)
    window.onInit()
    window.session.on_av_started()
    window.player.total_time = 0  # HTTP TS: getTotalTime() commonly 0
    window.player.time = 100
    window.setFocusId(SEEK_ROW_ID)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))
    window.scheduler.advance(0.75)

    assert window.player.seek_calls == [90]
    assert window.catchup is catchup_dict  # unchanged: native seek, no rebuild


def test_seek_leaving_catchup_range_rebuilds_once(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel_with_programmes(conn)
    now = datetime(2026, 1, 1, 12, 30)
    start_dt = datetime(2026, 1, 1, 12, 0)  # Show3 12:00-13:00, airing now
    end_dt = datetime(2026, 1, 1, 13, 0)
    catchup_dict = {
        'start': _epoch(start_dt), 'end': _epoch(end_dt), 'now': _epoch(now),
        'title': 'Show3', 'start_dt': start_dt, 'end_dt': end_dt, 'catchup_id': None,
    }
    window = _window(conn, snapshot, now_fn=FakeNow(now), catchup=catchup_dict)
    window.onInit()
    window.session.on_av_started()
    window.player.total_time = 0
    window.player.time = 5  # near the very start of the buffered file
    window.setFocusId(SEEK_ROW_ID)
    plays_before = len(window.player.plays)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))  # -10s: before session_start
    window.scheduler.advance(0.75)
    assert window.player.seek_calls == []  # left the buffer: no native seek

    window.on_stopped()  # old stream's stop callback, arriving after abort()

    # 5s into the file minus a 10s rewind lands 5s before session_start,
    # i.e. in the previous programme (Show2, 11:00-12:00) -- "rebuild
    # earlier" -- not a repeated rebuild of Show3.
    assert window.catchup is not None
    assert window.catchup['title'] == 'Show2'
    assert len(window.player.plays) == plays_before + 1


def test_rebuild_snaps_offset_floor_for_rewind_and_bumps_if_unchanged(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel_with_programmes(conn)
    snapshot['catchup_mode'] = 'xc'  # minute-precision granularity (60s)
    now = datetime(2026, 1, 1, 12, 30)
    start_dt = datetime(2026, 1, 1, 12, 0)  # Show3 12:00-13:00
    end_dt = datetime(2026, 1, 1, 13, 0)
    catchup_dict = {
        'start': _epoch(start_dt), 'end': _epoch(end_dt), 'now': _epoch(now),
        'title': 'Show3', 'start_dt': start_dt, 'end_dt': end_dt, 'catchup_id': None,
        'offset': 600,  # the running session's URL starts at 12:10:00
    }
    window = _window(conn, snapshot, now_fn=FakeNow(now), catchup=catchup_dict)
    window.onInit()
    window.session.on_av_started()
    captured = []
    window._replace_session = lambda prepare: captured.append(prepare)

    # 605s past the programme start floors to 600 -- the same minute the
    # current session already opened -- so it must bump one more step.
    window._rebuild_at_target(_epoch(start_dt) + 605, lambda: None, direction=-1)

    captured[-1]()
    assert window.catchup['offset'] == 540  # 600 - 60, not 600


def test_rebuild_snaps_offset_ceil_for_forward_and_bumps_if_unchanged(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel_with_programmes(conn)
    snapshot['catchup_mode'] = 'xc'  # minute-precision granularity (60s)
    now = datetime(2026, 1, 1, 12, 30)
    start_dt = datetime(2026, 1, 1, 12, 0)  # Show3 12:00-13:00
    end_dt = datetime(2026, 1, 1, 13, 0)
    catchup_dict = {
        'start': _epoch(start_dt), 'end': _epoch(end_dt), 'now': _epoch(now),
        'title': 'Show3', 'start_dt': start_dt, 'end_dt': end_dt, 'catchup_id': None,
        'offset': 600,  # the running session's URL starts at 12:10:00
    }
    window = _window(conn, snapshot, now_fn=FakeNow(now), catchup=catchup_dict)
    window.onInit()
    window.session.on_av_started()
    captured = []
    window._replace_session = lambda prepare: captured.append(prepare)

    # 595s past the programme start ceils to 600 -- the same minute the
    # current session already opened -- so it must bump one more step.
    window._rebuild_at_target(_epoch(start_dt) + 595, lambda: None, direction=1)

    captured[-1]()
    assert window.catchup['offset'] == 660  # 600 + 60


def test_commit_seek_dropped_while_transition_pending(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)
    window.onInit()
    window.session.on_av_started()
    window.player.total_time = 100
    window.player.time = 50
    window.setFocusId(SEEK_ROW_ID)
    window._pending_transition = lambda: None

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))
    window.scheduler.advance(0.75)

    assert window.player.seek_calls == []
    assert window.getProperty('seek_step') == ''


def test_commit_seek_dropped_when_not_playing(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)
    window.onInit()
    window.session.on_av_started()
    window.player.total_time = 100
    window.player.time = 50
    window.setFocusId(SEEK_ROW_ID)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))
    window.setProperty('state', 'connecting')  # e.g. a Drop mid-debounce
    window.scheduler.advance(0.75)

    assert window.player.seek_calls == []
    assert window.getProperty('seek_step') == ''


def test_pause_toggles_player_and_property(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)
    window.onInit()
    window.session.on_av_started()
    window.player.total_time = 100
    window.player.time = 50

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_PAUSE))

    assert window.getProperty('paused') == '1'
    assert window.player.pause_calls == 1
    assert window.getProperty('bar_visible') == '1'


def test_ok_with_button_row_focus_does_not_open_dialog_or_double_toggle(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)

    class _Dialog(object):
        @classmethod
        def open(cls, **kwargs):
            raise AssertionError('dialog should not open with button-row focus')

    window = _window(conn, snapshot, dialog_cls=_Dialog)
    window.onInit()
    window.session.on_av_started()
    window.setFocusId(BTN_PLAYPAUSE_ID)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
    window.onClick(BTN_PLAYPAUSE_ID)

    assert window.getProperty('paused') == '1'
    assert window.player.pause_calls == 1


def test_ok_with_seek_row_focus_toggles_pause_once(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)

    class _Dialog(object):
        @classmethod
        def open(cls, **kwargs):
            raise AssertionError('dialog should not open with seek-row focus')

    window = _window(conn, snapshot, dialog_cls=_Dialog)
    window.onInit()
    window.session.on_av_started()
    window.setFocusId(SEEK_ROW_ID)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))
    window.onClick(SEEK_ROW_ID)

    assert window.getProperty('paused') == '1'
    assert window.player.pause_calls == 1


def test_ok_with_programme_row_focus_opens_dialog(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel_with_programmes(conn)
    now = datetime(2026, 1, 1, 12, 30)  # Show3 airing now

    class _Dialog(object):
        opened_with = None
        result = None

        @classmethod
        def open(cls, **kwargs):
            cls.opened_with = kwargs
            return cls()

    window = _window(conn, snapshot, now_fn=FakeNow(now), dialog_cls=_Dialog)
    window.onInit()
    window.session.on_av_started()
    window.setFocusId(PROGRAMME_ROW_ID)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_SELECT_ITEM))

    assert _Dialog.opened_with is not None
    assert _Dialog.opened_with['title'] == 'Show3'


def test_resume_within_buffer_is_native_toggle(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    now = FakeNow(datetime(2026, 1, 1, 12, 30))
    window = _window(conn, snapshot, now_fn=now)
    window.onInit()
    window.session.on_av_started()
    window.player.total_time = 100
    window.player.time = 50
    plays_before = len(window.player.plays)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_PAUSE))
    now.value = now.value + timedelta(seconds=5)
    window.onAction(xbmcgui.Action(xbmcgui.ACTION_PLAYER_PLAYPAUSE))

    assert window.getProperty('paused') == '0'
    assert window.player.pause_calls == 2
    assert window.catchup is None
    assert len(window.player.plays) == plays_before


def test_resume_beyond_buffer_starts_catchup_session(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel_with_programmes(conn)
    now = FakeNow(datetime(2026, 1, 1, 12, 30))  # Show3 12:00-13:00 airing
    window = _window(conn, snapshot, now_fn=now)
    window.onInit()
    window.session.on_av_started()
    window.player.total_time = 10
    window.player.time = 5
    plays_before = len(window.player.plays)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_PAUSE))
    assert window.getProperty('paused') == '1'

    now.value = now.value + timedelta(hours=1)
    window.onAction(xbmcgui.Action(xbmcgui.ACTION_PLAYER_PLAYPAUSE))
    window.on_stopped()  # old stream's stop callback, arriving after abort()

    assert window.getProperty('paused') == '0'
    assert window.catchup is not None
    assert window.catchup['title'] == 'Show3'
    assert len(window.player.plays) == plays_before + 1


def test_catchup_session_pause_resume_is_always_native_toggle(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel_with_programmes(conn)
    now = datetime(2026, 1, 1, 12, 30)
    start_dt = datetime(2026, 1, 1, 11, 0)
    end_dt = datetime(2026, 1, 1, 12, 0)
    catchup_dict = {
        'start': _epoch(start_dt), 'end': _epoch(end_dt), 'now': _epoch(now),
        'title': 'Show2', 'start_dt': start_dt, 'end_dt': end_dt, 'catchup_id': None,
    }
    window = _window(conn, snapshot, now_fn=FakeNow(now), catchup=catchup_dict)
    window.onInit()
    window.session.on_av_started()
    plays_before = len(window.player.plays)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_PAUSE))
    window.onAction(xbmcgui.Action(xbmcgui.ACTION_PLAYER_PLAYPAUSE))

    assert window.getProperty('paused') == '0'
    assert window.player.pause_calls == 2
    assert len(window.player.plays) == plays_before


def test_back_to_live_button_click_zaps_live(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel_with_programmes(conn)
    now = datetime(2026, 1, 1, 12, 30)
    start_dt = datetime(2026, 1, 1, 11, 0)
    end_dt = datetime(2026, 1, 1, 12, 0)
    catchup_dict = {
        'start': _epoch(start_dt), 'end': _epoch(end_dt), 'now': _epoch(now),
        'title': 'Show2', 'start_dt': start_dt, 'end_dt': end_dt, 'catchup_id': None,
    }
    window = _window(conn, snapshot, now_fn=FakeNow(now), catchup=catchup_dict)
    window.onInit()
    window.session.on_av_started()

    window.onClick(BTN_LIVE_ID)
    window.on_stopped()  # old stream's stop callback, arriving after abort()

    assert window.catchup is None
    assert window.getProperty('catchup') == '0'


def test_behind_live_property_for_catchup_session(tmp_path):
    conn = _conn(tmp_path)
    provider_id, snapshot = _setup_channel_with_programmes(conn)
    now = datetime(2026, 1, 1, 12, 30)
    start_dt = datetime(2026, 1, 1, 11, 0)
    end_dt = datetime(2026, 1, 1, 12, 0)
    catchup_dict = {
        'start': _epoch(start_dt), 'end': _epoch(end_dt), 'now': _epoch(now),
        'title': 'Show2', 'start_dt': start_dt, 'end_dt': end_dt, 'catchup_id': None,
    }
    window = _window(conn, snapshot, now_fn=FakeNow(now), catchup=catchup_dict)
    window.onInit()
    window.session.on_av_started()

    # Catch-up is always "behind live": the Back to live button (715) stays
    # reachable (bare behind_live=1), but the red LIVE pill and the blue
    # "-MM:SS" behind pill are both gated on !catchup in the skin, so only
    # the CATCH-UP pill (catchup=1) should be showing, never those two.
    assert window.getProperty('behind_live') == '1'
    assert window.getProperty('catchup') == '1'
    assert window.getProperty('behind_text') == ''


def test_behind_live_property_when_live_but_behind_buffer(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)
    window.onInit()
    window.session.on_av_started()
    window.player.total_time = 100
    window.player.time = 40

    window._update_behind_live()

    assert window.getProperty('behind_live') == '1'
    assert window.getProperty('behind_text') == '-01:00'


def test_behind_live_property_zero_when_at_live_edge(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)
    window.onInit()
    window.session.on_av_started()
    window.player.total_time = 100
    window.player.time = 100

    window._update_behind_live()

    assert window.getProperty('behind_live') == '0'
    assert window.getProperty('behind_text') == ''


def test_button_row_left_right_moves_focus(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    snapshot['catchup_days'] = 3
    snapshot['catchup_mode'] = 'shift'
    window = _window(conn, snapshot)
    window.onInit()
    window.setFocusId(BTN_PLAYPAUSE_ID)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))
    assert window.getFocusId() == BTN_REWIND_ID

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))
    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))
    assert window.getFocusId() == BTN_FASTFORWARD_ID


def test_button_row_left_right_skips_hidden_back_to_live_button(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    snapshot['catchup_days'] = 3
    snapshot['catchup_mode'] = 'shift'
    window = _window(conn, snapshot)
    window.onInit()
    assert window.getProperty('behind_live') == '0'
    window.setFocusId(BTN_FASTFORWARD_ID)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))

    assert window.getFocusId() == BTN_FASTFORWARD_ID


def test_button_row_left_right_reaches_back_to_live_button_when_behind(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)
    window.onInit()
    window.setProperty('behind_live', '1')
    window.setFocusId(BTN_FASTFORWARD_ID)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))

    assert window.getFocusId() == BTN_LIVE_ID


def test_button_row_up_moves_focus_to_seek_row(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)
    window.onInit()
    window.setFocusId(BTN_PLAYPAUSE_ID)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_UP))

    assert window.getFocusId() == SEEK_ROW_ID


def test_button_row_down_opens_list(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)
    window.onInit()
    window.setFocusId(BTN_PLAYPAUSE_ID)

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_DOWN))

    assert window.getProperty('list_visible') == '1'


def test_remote_action_with_bar_hidden_only_shows_bar(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)
    window.onInit()
    window.session.on_av_started()
    window._hide_bar()
    assert window.getProperty('bar_visible') == '0'

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))

    assert window.getProperty('bar_visible') == '1'
    assert window.getProperty('seek_step') == ''
    assert window.player.seek_calls == []


def test_pause_action_works_regardless_of_bar_visibility(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    window = _window(conn, snapshot)
    window.onInit()
    window.session.on_av_started()
    window._hide_bar()

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_PAUSE))

    assert window.getProperty('paused') == '1'


def test_rewind_forward_remote_actions_seek(tmp_path):
    conn = _conn(tmp_path)
    _, snapshot = _setup_channel(conn)
    snapshot['catchup_days'] = 3
    snapshot['catchup_mode'] = 'shift'
    window = _window(conn, snapshot)
    window.onInit()
    window.session.on_av_started()
    window.player.total_time = 100
    window.player.time = 50

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_PLAYER_REWIND))
    assert window.getProperty('seek_step') == '-10s'
    window.scheduler.advance(0.75)
    assert window.player.seek_calls == [40]

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_PLAYER_FORWARD))
    window.scheduler.advance(0.75)
    assert window.player.seek_calls == [40, 50]
