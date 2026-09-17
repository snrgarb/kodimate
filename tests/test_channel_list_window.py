from datetime import datetime

import pytest

from kodimate import db
from kodimate.windows.channel_list import ChannelListWindow, GROUPS_LIST_ID, CHANNELS_LIST_ID, \
    TOGGLE_HIDDEN_ID
import xbmcgui


def _select_channel(window, channel_key):
    control = window.getControl(CHANNELS_LIST_ID)
    for index, item in enumerate(control._items):
        if item.getProperty('channel_key') == channel_key:
            control.selectItem(index)
            return
    raise AssertionError("channel %s not in list" % channel_key)


def _open_context_menu(window, monkeypatch, choice):
    window.setFocusId(CHANNELS_LIST_ID)
    monkeypatch.setattr(xbmcgui.Dialog, 'contextmenu', lambda self, options: choice)
    window.onAction(xbmcgui.Action(xbmcgui.ACTION_CONTEXT_MENU))


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


def test_context_menu_renumber_changes_effective_number(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    try:
        _seed(conn)
        window = _window(conn)
        _select_channel(window, 'a')
        monkeypatch.setattr(xbmcgui.Dialog, 'numeric', lambda self, t, h, d: '55')
        _open_context_menu(window, monkeypatch, choice=0)  # Renumber

        channels_control = window.getControl(CHANNELS_LIST_ID)
        assert channels_control.getSelectedItem().getProperty('channel_key') == 'a'
        assert channels_control.getSelectedItem().getProperty('number') == '55'
        assert window.getFocusId() == CHANNELS_LIST_ID
    finally:
        conn.close()


def test_context_menu_renumber_cancel_keeps_value(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    try:
        _seed(conn)
        window = _window(conn)
        _select_channel(window, 'a')
        original = window.getControl(CHANNELS_LIST_ID).getSelectedItem().getProperty('number')
        monkeypatch.setattr(xbmcgui.Dialog, 'numeric', lambda self, t, h, d: '')
        _open_context_menu(window, monkeypatch, choice=0)  # Renumber, empty/cancel

        channels_control = window.getControl(CHANNELS_LIST_ID)
        assert channels_control.getSelectedItem().getProperty('number') == original
    finally:
        conn.close()


def test_context_menu_hide_removes_row_and_returns_focus(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    try:
        _seed(conn)
        window = _window(conn)
        _select_channel(window, 'a')
        _open_context_menu(window, monkeypatch, choice=1)  # Hide

        channels_control = window.getControl(CHANNELS_LIST_ID)
        labels = [item.getLabel() for item in channels_control._items]
        assert 'Alpha' not in labels
        assert window.getFocusId() == CHANNELS_LIST_ID
    finally:
        conn.close()


def test_context_menu_unhide_restores_row(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    try:
        _seed(conn)
        window = _window(conn)
        window.onClick(TOGGLE_HIDDEN_ID)  # reveal Beta (hidden)
        _select_channel(window, 'b')
        _open_context_menu(window, monkeypatch, choice=1)  # Unhide

        channels_control = window.getControl(CHANNELS_LIST_ID)
        beta = [item for item in channels_control._items if item.getProperty('channel_key') == 'b'][0]
        assert beta.getProperty('hidden') == '0'
    finally:
        conn.close()


def test_context_menu_add_favourite(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    try:
        _seed(conn)
        window = _window(conn)
        _select_channel(window, 'a')
        _open_context_menu(window, monkeypatch, choice=2)  # Add to Favourites

        groups_control = window.getControl(GROUPS_LIST_ID)
        groups_control.selectItem(1)  # Favourites
        window._render_channels()
        channels_control = window.getControl(CHANNELS_LIST_ID)
        assert [item.getProperty('channel_key') for item in channels_control._items] == ['a']
    finally:
        conn.close()


def test_context_menu_remove_favourite(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    try:
        p1, p2, g1 = _seed(conn)
        conn.execute(
            "INSERT INTO channel_override (provider_id, channel_key, favourite, favourite_order) "
            "VALUES (?, 'a', 1, 0)", (p1,)
        )
        window = _window(conn)
        groups_control = window.getControl(GROUPS_LIST_ID)
        groups_control.selectItem(1)  # Favourites
        window._render_channels()
        _select_channel(window, 'a')
        _open_context_menu(window, monkeypatch, choice=2)  # Remove from Favourites

        channels_control = window.getControl(CHANNELS_LIST_ID)
        assert channels_control.size() == 0
    finally:
        conn.close()


def test_context_menu_move_pickup_shift_drop_persists_order(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    try:
        p1, p2, g1 = _seed(conn)
        conn.execute(
            "INSERT INTO channel_override (provider_id, channel_key, favourite, favourite_order) "
            "VALUES (?, 'a', 1, 0)", (p1,)
        )
        conn.execute(
            "UPDATE channel_override SET hidden = 0, favourite = 1, favourite_order = 1 "
            "WHERE provider_id = ? AND channel_key = 'b'", (p1,)
        )
        window = _window(conn)
        groups_control = window.getControl(GROUPS_LIST_ID)
        groups_control.selectItem(1)  # Favourites
        window._render_channels()
        _select_channel(window, 'a')
        _open_context_menu(window, monkeypatch, choice=3)  # Move

        assert window._move_key == (p1, 'a')
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_DOWN))

        channels_control = window.getControl(CHANNELS_LIST_ID)
        assert [item.getProperty('channel_key') for item in channels_control._items] == ['b', 'a']

        window.onClick(CHANNELS_LIST_ID)  # OK drops

        assert window._move_key is None
        order = conn.execute(
            "SELECT channel_key FROM channel_override WHERE provider_id = ? AND favourite = 1 "
            "ORDER BY favourite_order",
            (p1,),
        ).fetchall()
        assert [row[0] for row in order] == ['b', 'a']
        assert window.getFocusId() == CHANNELS_LIST_ID
    finally:
        conn.close()


def test_context_menu_move_back_restores_order(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    try:
        p1, p2, g1 = _seed(conn)
        conn.execute(
            "INSERT INTO channel_override (provider_id, channel_key, favourite, favourite_order) "
            "VALUES (?, 'a', 1, 0)", (p1,)
        )
        conn.execute(
            "UPDATE channel_override SET hidden = 0, favourite = 1, favourite_order = 1 "
            "WHERE provider_id = ? AND channel_key = 'b'", (p1,)
        )
        window = _window(conn)
        groups_control = window.getControl(GROUPS_LIST_ID)
        groups_control.selectItem(1)  # Favourites
        window._render_channels()
        _select_channel(window, 'a')
        _open_context_menu(window, monkeypatch, choice=3)  # Move
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_DOWN))

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))  # Back restores

        assert window._move_key is None
        order = conn.execute(
            "SELECT channel_key FROM channel_override WHERE provider_id = ? AND favourite = 1 "
            "ORDER BY favourite_order",
            (p1,),
        ).fetchall()
        assert [row[0] for row in order] == ['a', 'b']
        channels_control = window.getControl(CHANNELS_LIST_ID)
        assert [item.getProperty('channel_key') for item in channels_control._items] == ['a', 'b']
    finally:
        conn.close()


def test_context_menu_reset_clears_number_hidden_and_favourite(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    try:
        p1, p2, g1 = _seed(conn)
        conn.execute(
            "INSERT INTO channel_override (provider_id, channel_key, number, favourite, "
            "favourite_order) VALUES (?, 'a', 999, 1, 0)", (p1,)
        )
        window = _window(conn)
        _select_channel(window, 'a')
        _open_context_menu(window, monkeypatch, choice=3)  # Reset (no Move: not in Favourites view)

        row = conn.execute(
            "SELECT * FROM channel_override WHERE provider_id = ? AND channel_key = 'a'", (p1,)
        ).fetchone()
        assert row is None
    finally:
        conn.close()


def test_context_menu_deferred_generation_change_applied_after_close(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    try:
        _seed(conn)
        window = _window(conn)
        _select_channel(window, 'a')

        def fake_contextmenu(self, options):
            conn.execute("UPDATE channel SET name = 'Alpha2' WHERE channel_key = 'a'")
            _bump_generation(2)
            _notify_refreshed(window)
            # While the menu is open, the deferred refresh must not have applied yet.
            assert window.getControl(CHANNELS_LIST_ID).getSelectedItem().getLabel() == 'Alpha'
            return -1

        window.setFocusId(CHANNELS_LIST_ID)
        monkeypatch.setattr(xbmcgui.Dialog, 'contextmenu', fake_contextmenu)
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_CONTEXT_MENU))

        assert window.getControl(CHANNELS_LIST_ID).getSelectedItem().getLabel() == 'Alpha2'
    finally:
        conn.close()


def test_second_oninit_keeps_watcher_state_and_selection(tmp_path):
    conn = _conn(tmp_path)
    try:
        _seed(conn)
        window = _window(conn)
        window.onClick(TOGGLE_HIDDEN_ID)  # reveal Beta, _show_hidden = True
        _select_channel(window, 'b')
        original_watcher = window._watcher

        window.onInit()  # simulate Kodi re-entering onInit (e.g. back from playback)

        assert window._watcher is original_watcher
        assert window._show_hidden is True
        channels_control = window.getControl(CHANNELS_LIST_ID)
        assert channels_control.getSelectedItem().getProperty('channel_key') == 'b'
    finally:
        conn.close()


def test_second_oninit_applies_pending_refresh(tmp_path):
    conn = _conn(tmp_path)
    try:
        _seed(conn)
        window = _window(conn)
        window._enter_modal()

        conn.execute("UPDATE channel SET name = 'Alpha2' WHERE channel_key = 'a'")
        _bump_generation(2)
        _notify_refreshed(window)
        assert window._render_pending is True

        window.onInit()

        assert window._render_pending is False
        channels_control = window.getControl(CHANNELS_LIST_ID)
        assert channels_control.getSelectedItem().getLabel() == 'Alpha2'
    finally:
        conn.close()


def test_group_debounce_timer_is_noop_during_favourites_move(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    try:
        p1, p2, g1 = _seed(conn)
        conn.execute(
            "INSERT INTO channel_override (provider_id, channel_key, favourite, favourite_order) "
            "VALUES (?, 'a', 1, 0)", (p1,)
        )
        conn.execute(
            "UPDATE channel_override SET hidden = 0, favourite = 1, favourite_order = 1 "
            "WHERE provider_id = ? AND channel_key = 'b'", (p1,)
        )
        window = _window(conn)
        groups_control = window.getControl(GROUPS_LIST_ID)
        groups_control.selectItem(1)  # Favourites
        window._render_channels()
        _select_channel(window, 'a')
        _open_context_menu(window, monkeypatch, choice=3)  # Move
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_DOWN))  # temporary order ['b', 'a']

        scheduled = []

        class FakeTimer(object):
            def __init__(self, interval, function):
                self.function = function
                scheduled.append(self)

            def start(self):
                pass

            def cancel(self):
                pass

        monkeypatch.setattr('kodimate.windows.channel_list.threading.Timer', FakeTimer)

        # A Groups-pane selection change queued (e.g. just before Move was
        # picked up) fires its debounce timer while move mode is still active.
        window._schedule_render_channels()
        scheduled[-1].function()

        channels_control = window.getControl(CHANNELS_LIST_ID)
        assert [item.getProperty('channel_key') for item in channels_control._items] == ['b', 'a']
    finally:
        conn.close()
