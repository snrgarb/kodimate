from datetime import datetime

import pytest

from kodimate import db
from kodimate.windows.channel_list import ChannelListWindow, GROUPS_LIST_ID, CHANNELS_LIST_ID, \
    TOGGLE_HIDDEN_ID
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


def _conn(tmp_path):
    return db.open_db(str(tmp_path / "kodimate.db"))


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


class FakeNow(object):
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


def _seed(conn):
    p1 = conn.execute(
        "INSERT INTO provider (kind, name, enabled, sort_order) VALUES ('m3u', 'P1', 1, 0)"
    ).lastrowid
    p2 = conn.execute(
        "INSERT INTO provider (kind, name, enabled, sort_order) VALUES ('m3u', 'P2', 1, 1)"
    ).lastrowid
    g1 = conn.execute(
        "INSERT INTO channel_group (provider_id, name, sort_order) VALUES (?, 'Sports', 0)",
        (p1,),
    ).lastrowid
    conn.execute(
        "INSERT INTO channel (provider_id, channel_key, name, normalised_name, stream_url, "
        "group_id, position, logo_url) VALUES (?, 'a', 'Alpha', 'alpha', 'http://x/a', ?, 0, "
        "'http://logo/a.png')",
        (p1, g1),
    )
    conn.execute(
        "INSERT INTO channel (provider_id, channel_key, name, normalised_name, stream_url, "
        "group_id, position) VALUES (?, 'b', 'Beta', 'beta', 'http://x/b', ?, 1)",
        (p1, g1),
    )
    conn.execute(
        "INSERT INTO channel_override (provider_id, channel_key, hidden) VALUES (?, 'b', 1)",
        (p1,),
    )
    return p1, p2, g1


def _window(conn, **overrides):
    kwargs = dict(conn=conn)
    kwargs.update(overrides)
    window = ChannelListWindow('script-kodimate-channel-list.xml', '/addon', 'Main', '1080i',
                                **kwargs)
    window.onInit()
    return window


def test_groups_list_has_all_favourites_and_group(tmp_path):
    conn = _conn(tmp_path)
    try:
        _seed(conn)
        window = _window(conn)
        groups_control = window.getControl(GROUPS_LIST_ID)
        labels = [item.getLabel() for item in groups_control._items]
        assert labels == ["String 32038", "String 32039", "Sports"]
    finally:
        conn.close()


def test_channels_list_excludes_hidden_by_default(tmp_path):
    conn = _conn(tmp_path)
    try:
        _seed(conn)
        window = _window(conn)
        channels_control = window.getControl(CHANNELS_LIST_ID)
        labels = [item.getLabel() for item in channels_control._items]
        assert labels == ["Alpha"]
    finally:
        conn.close()


def test_show_hidden_toggle_reveals_hidden_row(tmp_path):
    conn = _conn(tmp_path)
    try:
        _seed(conn)
        window = _window(conn)
        window.onClick(TOGGLE_HIDDEN_ID)
        channels_control = window.getControl(CHANNELS_LIST_ID)
        labels = [item.getLabel() for item in channels_control._items]
        assert labels == ["Alpha", "Beta"]
        beta = channels_control._items[1]
        assert beta.getProperty('hidden') == '1'
    finally:
        conn.close()


def test_rapid_group_changes_debounce_to_single_render(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    try:
        _seed(conn)
        window = _window(conn)

        scheduled = []

        class FakeTimer(object):
            def __init__(self, interval, function):
                self.function = function
                self.cancelled = False
                scheduled.append(self)

            def start(self):
                pass

            def cancel(self):
                self.cancelled = True

        monkeypatch.setattr('kodimate.windows.channel_list.threading.Timer', FakeTimer)

        render_calls = []
        original_render = window._render_channels

        def counting_render():
            render_calls.append(1)
            original_render()

        window._render_channels = counting_render

        window.setFocusId(GROUPS_LIST_ID)
        groups_control = window.getControl(GROUPS_LIST_ID)

        groups_control.selectItem(1)
        window.onAction(xbmcgui.Action(3))
        groups_control.selectItem(2)
        window.onAction(xbmcgui.Action(3))

        assert len(scheduled) == 2
        assert scheduled[0].cancelled is True
        assert render_calls == []

        scheduled[-1].function()

        assert render_calls == [1]
    finally:
        conn.close()


def test_logo_art_set_only_when_logo_url_present(tmp_path):
    conn = _conn(tmp_path)
    try:
        _seed(conn)
        window = _window(conn)
        window.onClick(TOGGLE_HIDDEN_ID)
        channels_control = window.getControl(CHANNELS_LIST_ID)
        alpha, beta = channels_control._items
        assert alpha.getArt('icon') == 'http://logo/a.png'
        assert beta.getArt('icon') == ''
    finally:
        conn.close()


def test_ok_on_channel_row_opens_playback(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    try:
        _seed(conn)
        window = _window(conn)

        opened = {}

        @classmethod
        def fake_open(cls, **kwargs):
            opened.update(kwargs)

        from kodimate.windows.channel_list import PlaybackWindow
        monkeypatch.setattr(PlaybackWindow, 'open', fake_open)

        channels_control = window.getControl(CHANNELS_LIST_ID)
        channels_control.selectItem(0)
        window.onClick(CHANNELS_LIST_ID)

        assert opened['conn'] is conn
        assert opened['snapshot']['channel_key'] == 'a'
        assert opened['snapshot']['name'] == 'Alpha'
    finally:
        conn.close()


def test_generation_change_keeps_focus_by_channel_key(tmp_path):
    conn = _conn(tmp_path)
    try:
        _seed(conn)
        window = _window(conn)
        window.onClick(TOGGLE_HIDDEN_ID)  # reveal Beta too
        channels_control = window.getControl(CHANNELS_LIST_ID)
        channels_control.selectItem(1)  # Beta

        conn.execute("UPDATE channel SET name = 'Beta2' WHERE channel_key = 'b'")
        _bump_generation(2)
        _notify_refreshed(window)

        selected = channels_control.getSelectedItem()
        assert selected.getProperty('channel_key') == 'b'
        assert selected.getLabel() == 'Beta2'
    finally:
        conn.close()


def test_generation_change_selects_nearest_row_when_focused_channel_went_stale(tmp_path):
    conn = _conn(tmp_path)
    try:
        _seed(conn)
        window = _window(conn)
        window.onClick(TOGGLE_HIDDEN_ID)  # reveal Alpha + Beta
        channels_control = window.getControl(CHANNELS_LIST_ID)
        channels_control.selectItem(1)  # Beta, last row

        conn.execute("UPDATE channel SET stale_since = '2026-01-01T00:00:00' WHERE channel_key = 'b'")
        _bump_generation(2)
        _notify_refreshed(window)

        assert channels_control.size() == 1
        assert channels_control.getSelectedPosition() == 0
    finally:
        conn.close()


def test_generation_change_falls_back_to_all_when_group_vanishes(tmp_path):
    conn = _conn(tmp_path)
    try:
        p1, p2, g1 = _seed(conn)
        window = _window(conn)
        groups_control = window.getControl(GROUPS_LIST_ID)
        groups_control.selectItem(2)  # 'Sports' group
        window._render_channels()

        conn.execute("UPDATE channel SET stale_since = '2026-01-01T00:00:00' WHERE group_id = ?", (g1,))
        _bump_generation(2)
        _notify_refreshed(window)

        assert groups_control.getSelectedPosition() == 0
        assert groups_control.getSelectedItem().getProperty('kind') == 'all'
    finally:
        conn.close()


def test_generation_change_deferred_while_modal_open_then_applied_on_close(tmp_path):
    conn = _conn(tmp_path)
    try:
        _seed(conn)
        window = _window(conn)
        window._enter_modal()

        conn.execute("UPDATE channel SET name = 'Alpha2' WHERE channel_key = 'a'")
        _bump_generation(2)
        _notify_refreshed(window)

        channels_control = window.getControl(CHANNELS_LIST_ID)
        assert channels_control.getSelectedItem().getLabel() == 'Alpha'

        window._exit_modal()

        assert channels_control.getSelectedItem().getLabel() == 'Alpha2'
    finally:
        conn.close()


def test_generation_watcher_stopped_on_close(tmp_path):
    conn = _conn(tmp_path)
    try:
        _seed(conn)
        window = _window(conn)
        window.close()
        assert window._watcher._stopped is True
    finally:
        conn.close()


def test_channel_row_gets_now_title_property(tmp_path):
    conn = _conn(tmp_path)
    try:
        p1, p2, g1 = _seed(conn)
        conn.execute("UPDATE channel SET epg_channel_id = 'a' WHERE channel_key = 'a'")
        eid = _epg_source(conn, p1)
        _programme(conn, eid, 'a', '2026-01-01T11:00:00Z', '2026-01-01T12:00:00Z', 'Now Show')
        now = datetime(2026, 1, 1, 11, 30)
        window = _window(conn, now_fn=FakeNow(now))
        channels_control = window.getControl(CHANNELS_LIST_ID)
        alpha = channels_control._items[0]
        assert alpha.getProperty('now_title') == 'Now Show'
    finally:
        conn.close()


def test_channel_row_now_title_empty_when_no_current_programme(tmp_path):
    conn = _conn(tmp_path)
    try:
        _seed(conn)
        window = _window(conn, now_fn=FakeNow(datetime(2026, 1, 1, 11, 30)))
        channels_control = window.getControl(CHANNELS_LIST_ID)
        alpha = channels_control._items[0]
        assert alpha.getProperty('now_title') == ''
    finally:
        conn.close()
