from datetime import datetime, timedelta

import pytest

from kodimate import db, guide
from kodimate.windows.catchup_browser import CatchupBrowserWindow, CHANNEL_LIST_ID, PROGRAMME_LIST_ID
import xbmcgui


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
