import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import pytest

from kodimate import db, guide
from kodimate.windows.catchup_browser import (
    CatchupBrowserWindow, CHANNEL_LIST_ID, PROGRAMME_LIST_ID,
    RAIL_LIVETV_ID, RAIL_CATCHUP_ID, RAIL_SETTINGS_ID,
)
import xbmcaddon
import xbmcgui

_SKIN_XML = os.path.join(
    os.path.dirname(__file__), '..', 'resources', 'skins', 'Main', '1080i',
    'script-kodimate-catchup-browser.xml',
)


@pytest.fixture(autouse=True)
def _clear_db_generation():
    xbmcgui._window_properties.pop(10000, None)
    yield
    xbmcgui._window_properties.pop(10000, None)


def _notify_refreshed(window):
    window._watcher.onNotification('script.kodimate', 'Other.refreshed', '{}')


def _conn(tmp_path):
    return db.open_db(str(tmp_path / "kodimate.db"))


def _provider(conn, name="P1"):
    return conn.execute(
        "INSERT INTO provider (kind, name, enabled, sort_order) VALUES ('m3u', ?, 1, 0)", (name,)
    ).lastrowid


def _channel(conn, provider_id, channel_key, name, position, epg_channel_id=None,
             stream_url='http://x/live/u/p/1.ts', catchup_days=None):
    cursor = conn.execute(
        "INSERT INTO channel (provider_id, channel_key, name, normalised_name, stream_url, "
        "position, epg_channel_id, catchup_days) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (provider_id, channel_key, name, name.lower(), stream_url, position, epg_channel_id,
         catchup_days),
    )
    return cursor.lastrowid


def _epg_source(conn, provider_id):
    return conn.execute(
        "INSERT INTO epg_source (provider_id, url) VALUES (?, 'http://epg')", (provider_id,)
    ).lastrowid


def _programme(conn, epg_source_id, xmltv_channel_id, start, end, title, description=None):
    conn.execute(
        "INSERT INTO programme (epg_source_id, xmltv_channel_id, start, end, title, description) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (epg_source_id, xmltv_channel_id, start, end, title, description),
    )


def _window(conn):
    window = CatchupBrowserWindow(
        'script-kodimate-catchup-browser.xml', '/addon', 'Main', '1080i', conn=conn
    )
    window.onInit()
    return window


class _FakeDialog(object):
    opened_with = None
    result = None

    @classmethod
    def open(cls, **kwargs):
        cls.opened_with = kwargs
        return cls()


class _FakePlaybackWindow(object):
    opened_with = None

    @classmethod
    def open(cls, **kwargs):
        cls.opened_with = kwargs
        return cls()


def _window_with_fakes(conn, dialog_result):
    class _Dialog(_FakeDialog):
        result = dialog_result

    class _Playback(_FakePlaybackWindow):
        pass

    class _Window(CatchupBrowserWindow):
        dialog_cls = _Dialog
        playback_cls = _Playback

    window = _Window(
        'script-kodimate-catchup-browser.xml', '/addon', 'Main', '1080i', conn=conn
    )
    window.onInit()
    return window, _Dialog, _Playback


def test_opens_with_empty_lists_when_no_channels_qualify(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)  # no catchup_days, no provider default
        window = _window(conn)
        assert window.getControl(CHANNEL_LIST_ID).size() == 0
        assert window.getControl(PROGRAMME_LIST_ID).size() == 0
    finally:
        conn.close()


def test_left_pane_filters_by_window_favourites_first_no_duplicates(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, catchup_days=3)
        no_window_id = _channel(conn, pid, "b", "Bravo", 1, catchup_days=0)
        charlie_id = _channel(conn, pid, "c", "Charlie", 2, catchup_days=5)
        conn.execute(
            "INSERT INTO channel_override (provider_id, channel_key, favourite, favourite_order) "
            "VALUES (?, 'c', 1, 0)", (pid,),
        )

        window = _window(conn)
        control = window.getControl(CHANNEL_LIST_ID)
        names = [control.getListItem(i).getLabel() for i in range(control.size())]

        assert names == ['Charlie', 'Alpha']
        assert no_window_id  # Bravo (window=0) excluded
        assert charlie_id
    finally:
        conn.close()


def test_right_pane_groups_by_day_newest_first_with_headers(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1", catchup_days=3)
        eid = _epg_source(conn, pid)
        now = datetime.utcnow()
        today_start = now - timedelta(hours=1)
        yesterday_start = now - timedelta(days=1, hours=1)
        older_start = now - timedelta(days=2, hours=1)
        _programme(conn, eid, "x1", guide.format_iso(today_start),
                   guide.format_iso(today_start + timedelta(minutes=30)), "Today Show")
        _programme(conn, eid, "x1", guide.format_iso(yesterday_start),
                   guide.format_iso(yesterday_start + timedelta(minutes=30)), "Yesterday Show")
        _programme(conn, eid, "x1", guide.format_iso(older_start),
                   guide.format_iso(older_start + timedelta(minutes=30)), "Older Show")

        window = _window(conn)
        control = window.getControl(PROGRAMME_LIST_ID)
        labels = [control.getListItem(i).getLabel() for i in range(control.size())]
        headers = [control.getListItem(i).getProperty('header') for i in range(control.size())]

        assert labels[0] == 'String 32111'  # "Today"
        assert headers[0] == '1'
        assert labels[1] == 'Today Show'
        assert labels[2] == 'String 32112'  # "Yesterday"
        assert labels[3] == 'Yesterday Show'
        assert headers[4] == '1'  # the older-day header is present too
        assert labels[5] == 'Older Show'
    finally:
        conn.close()


def test_right_pane_excludes_future_and_out_of_window_programmes(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1", catchup_days=1)
        eid = _epg_source(conn, pid)
        now = datetime.utcnow()
        _programme(conn, eid, "x1", guide.format_iso(now + timedelta(minutes=10)),
                   guide.format_iso(now + timedelta(minutes=40)), "Future Show")
        _programme(conn, eid, "x1", guide.format_iso(now - timedelta(days=5)),
                   guide.format_iso(now - timedelta(days=5) + timedelta(minutes=30)),
                   "Too Old Show")
        _programme(conn, eid, "x1", guide.format_iso(now - timedelta(hours=1)),
                   guide.format_iso(now - timedelta(minutes=30)), "In Window Show")

        window = _window(conn)
        control = window.getControl(PROGRAMME_LIST_ID)
        labels = [control.getListItem(i).getLabel() for i in range(control.size())]

        assert 'Future Show' not in labels
        assert 'Too Old Show' not in labels
        assert 'In Window Show' in labels
    finally:
        conn.close()


def test_changing_left_selection_rerenders_right_pane_on_action(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1", catchup_days=3)
        _channel(conn, pid, "b", "Bravo", 1, epg_channel_id="x2", catchup_days=3)
        eid = _epg_source(conn, pid)
        now = datetime.utcnow()
        _programme(conn, eid, "x1", guide.format_iso(now - timedelta(hours=1)),
                   guide.format_iso(now - timedelta(minutes=30)), "Alpha Show")
        _programme(conn, eid, "x2", guide.format_iso(now - timedelta(hours=1)),
                   guide.format_iso(now - timedelta(minutes=30)), "Bravo Show")

        window = _window(conn)
        left = window.getControl(CHANNEL_LIST_ID)
        right = window.getControl(PROGRAMME_LIST_ID)
        assert any(right.getListItem(i).getLabel() == 'Alpha Show' for i in range(right.size()))

        left.selectItem(1)
        window.setFocusId(CHANNEL_LIST_ID)
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_DOWN))

        labels = [right.getListItem(i).getLabel() for i in range(right.size())]
        assert 'Bravo Show' in labels
        assert 'Alpha Show' not in labels
    finally:
        conn.close()


def test_changing_left_selection_rerenders_right_pane_on_focus(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1", catchup_days=3)
        _channel(conn, pid, "b", "Bravo", 1, epg_channel_id="x2", catchup_days=3)
        eid = _epg_source(conn, pid)
        now = datetime.utcnow()
        _programme(conn, eid, "x2", guide.format_iso(now - timedelta(hours=1)),
                   guide.format_iso(now - timedelta(minutes=30)), "Bravo Show")

        window = _window(conn)
        right = window.getControl(PROGRAMME_LIST_ID)
        window.getControl(CHANNEL_LIST_ID).selectItem(1)
        window.onFocus(CHANNEL_LIST_ID)

        labels = [right.getListItem(i).getLabel() for i in range(right.size())]
        assert labels == ['String 32111', 'Bravo Show']
    finally:
        conn.close()


def test_focus_entering_programme_list_skips_header_to_first_programme(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1", catchup_days=3)
        eid = _epg_source(conn, pid)
        now = datetime.utcnow()
        _programme(conn, eid, "x1", guide.format_iso(now - timedelta(hours=1)),
                   guide.format_iso(now - timedelta(minutes=30)), "Today Show")

        window = _window(conn)
        control = window.getControl(PROGRAMME_LIST_ID)
        control.selectItem(0)  # native focus lands on the "Today" header
        window.setFocusId(PROGRAMME_LIST_ID)

        window.onFocus(PROGRAMME_LIST_ID)

        assert control.getSelectedPosition() == 1
        assert control.getListItem(1).getLabel() == 'Today Show'
    finally:
        conn.close()


def test_down_from_last_programme_of_day_skips_header_to_next_days_first_programme(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1", catchup_days=3)
        eid = _epg_source(conn, pid)
        now = datetime.utcnow()
        today_start = now - timedelta(hours=1)
        yesterday_start = now - timedelta(days=1, hours=1)
        _programme(conn, eid, "x1", guide.format_iso(today_start),
                   guide.format_iso(today_start + timedelta(minutes=30)), "Today Show")
        _programme(conn, eid, "x1", guide.format_iso(yesterday_start),
                   guide.format_iso(yesterday_start + timedelta(minutes=30)), "Yesterday Show")

        window = _window(conn)
        control = window.getControl(PROGRAMME_LIST_ID)
        # Positions: 0 header "Today", 1 "Today Show", 2 header "Yesterday", 3 "Yesterday Show"
        control.selectItem(2)  # native Down already moved onto the "Yesterday" header
        window.setFocusId(PROGRAMME_LIST_ID)

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_DOWN))

        assert control.getSelectedPosition() == 3
        assert control.getListItem(3).getLabel() == 'Yesterday Show'
    finally:
        conn.close()


def test_up_onto_header_skips_to_previous_days_last_programme(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1", catchup_days=3)
        eid = _epg_source(conn, pid)
        now = datetime.utcnow()
        today_start = now - timedelta(hours=1)
        yesterday_start = now - timedelta(days=1, hours=1)
        _programme(conn, eid, "x1", guide.format_iso(today_start),
                   guide.format_iso(today_start + timedelta(minutes=30)), "Today Show")
        _programme(conn, eid, "x1", guide.format_iso(yesterday_start),
                   guide.format_iso(yesterday_start + timedelta(minutes=30)), "Yesterday Show")

        window = _window(conn)
        control = window.getControl(PROGRAMME_LIST_ID)
        control.selectItem(2)  # native Up already moved onto the "Yesterday" header
        window.setFocusId(PROGRAMME_LIST_ID)

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_UP))

        assert control.getSelectedPosition() == 1
        assert control.getListItem(1).getLabel() == 'Today Show'
    finally:
        conn.close()


def test_up_on_first_programme_stays_on_first_programme(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1", catchup_days=3)
        eid = _epg_source(conn, pid)
        now = datetime.utcnow()
        _programme(conn, eid, "x1", guide.format_iso(now - timedelta(hours=1)),
                   guide.format_iso(now - timedelta(minutes=30)), "Today Show")

        window = _window(conn)
        control = window.getControl(PROGRAMME_LIST_ID)
        control.selectItem(0)  # native Up already moved onto the top "Today" header
        window.setFocusId(PROGRAMME_LIST_ID)

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_UP))

        assert control.getSelectedPosition() == 1
        assert control.getListItem(1).getLabel() == 'Today Show'
    finally:
        conn.close()


def test_ok_on_header_is_a_no_op(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1", catchup_days=3)
        eid = _epg_source(conn, pid)
        now = datetime.utcnow()
        _programme(conn, eid, "x1", guide.format_iso(now - timedelta(hours=1)),
                   guide.format_iso(now - timedelta(minutes=30)), "Alpha Show")

        window, dialog_cls, playback_cls = _window_with_fakes(conn, None)
        control = window.getControl(PROGRAMME_LIST_ID)
        control.selectItem(0)  # the "Today" header

        window.onClick(PROGRAMME_LIST_ID)

        assert dialog_cls.opened_with is None
    finally:
        conn.close()


def test_ok_on_programme_opens_dialog_and_dispatches_play_catchup(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1", catchup_days=3)
        eid = _epg_source(conn, pid)
        now = datetime.utcnow()
        start = now - timedelta(hours=1)
        end = now - timedelta(minutes=30)
        _programme(conn, eid, "x1", guide.format_iso(start), guide.format_iso(end), "Alpha Show")

        window, dialog_cls, playback_cls = _window_with_fakes(conn, 'play_catchup')
        control = window.getControl(PROGRAMME_LIST_ID)
        control.selectItem(1)  # the programme row, after the header

        window.onClick(PROGRAMME_LIST_ID)

        assert dialog_cls.opened_with['actions'] == ['play_catchup']
        assert playback_cls.opened_with['catchup']['title'] == 'Alpha Show'
    finally:
        conn.close()


def test_ok_on_live_like_programme_dispatches_watch_live(tmp_path):
    # A channel with a very small correction window can leave a "past" row
    # that is still airing by wall-clock now; exercise watch_live too since
    # cell_state is computed fresh at OK time.
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1", catchup_days=3)
        eid = _epg_source(conn, pid)
        now = datetime.utcnow()
        start = now - timedelta(minutes=10)
        end = now - timedelta(seconds=1)
        _programme(conn, eid, "x1", guide.format_iso(start), guide.format_iso(end), "Alpha Show")

        window, dialog_cls, playback_cls = _window_with_fakes(conn, 'play_catchup')
        control = window.getControl(PROGRAMME_LIST_ID)
        control.selectItem(1)

        window.onClick(PROGRAMME_LIST_ID)

        assert playback_cls.opened_with is not None
        assert 'catchup' in playback_cls.opened_with
    finally:
        conn.close()


def test_back_closes_window(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, catchup_days=3)
        window = _window(conn)
        closed = {}
        window.close = lambda: closed.setdefault('done', True)
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
        assert closed.get('done') is True
    finally:
        conn.close()


# -- Icon rail (issue #46 follow-up) ----------------------------------------

def test_rail_selected_property_set_to_catchup(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, catchup_days=3)
        window = _window(conn)
        assert window.getProperty('rail_selected') == 'catchup'
    finally:
        conn.close()


def test_focus_not_on_rail_after_init(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, catchup_days=3)
        window = _window(conn)
        assert window.getFocusId() not in (RAIL_LIVETV_ID, RAIL_CATCHUP_ID, RAIL_SETTINGS_ID)
    finally:
        conn.close()


def test_left_from_channel_list_focuses_catchup_rail(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, catchup_days=3)
        window = _window(conn)
        window.setFocusId(CHANNEL_LIST_ID)

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))

        assert window.getFocusId() == RAIL_CATCHUP_ID
    finally:
        conn.close()


def test_right_from_rail_returns_to_channel_list(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, catchup_days=3)
        window = _window(conn)
        window.setFocusId(RAIL_CATCHUP_ID)

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))

        assert window.getFocusId() == CHANNEL_LIST_ID
    finally:
        conn.close()


def test_ok_on_livetv_rail_closes_window(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, catchup_days=3)
        window = _window(conn)
        closed = {}
        window.close = lambda: closed.setdefault('done', True)

        window.onClick(RAIL_LIVETV_ID)

        assert closed.get('done') is True
    finally:
        conn.close()


def test_ok_on_settings_rail_opens_addon_settings(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, catchup_days=3)
        window = _window(conn)
        xbmcaddon.open_settings_calls[:] = []

        window.onClick(RAIL_SETTINGS_ID)

        assert xbmcaddon.open_settings_calls == [True]
    finally:
        conn.close()


def test_skin_pins_rail_and_list_horizontal_navigation():
    tree = ET.parse(_SKIN_XML)
    controls_by_id = {}
    for control in tree.getroot().iter('control'):
        control_id = control.get('id')
        if control_id is not None:
            controls_by_id[control_id] = control
    for control_id in ('601', '602', '603'):
        control = controls_by_id[control_id]
        assert control.find('onleft').text == control_id
        assert control.find('onright').text == control_id
    assert controls_by_id['200'].find('onleft').text == '200'
    assert controls_by_id['201'].find('onright').text == '201'
