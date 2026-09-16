import xbmcaddon
import xbmcgui

from kodimate import db, providers
from kodimate.windows import providers as providers_window
from kodimate.windows.providers import ProvidersWindow, LIST_ID, ADD_BUTTON_ID


def _conn(tmp_path):
    return db.open_db(str(tmp_path / "kodimate.db"))


def _window(conn):
    window = ProvidersWindow('script-kodimate-providers.xml', '/addon', 'Main', '1080i',
                              conn=conn)
    window.onInit()
    return window


def _patch_delete_message(monkeypatch):
    original = xbmcaddon.Addon.getLocalizedString

    def fake(self, string_id):
        if string_id == providers_window._STR_DELETE_MESSAGE:
            return "Remove %s's channels"
        return original(self, string_id)

    monkeypatch.setattr(xbmcaddon.Addon, 'getLocalizedString', fake)


def _select(window, provider_id):
    control = window.getControl(LIST_ID)
    for index, item in enumerate(control._items):
        if item.getProperty('provider_id') == str(provider_id):
            control.selectItem(index)
            return
    raise AssertionError("provider %s not in list" % provider_id)


def test_context_menu_offers_options_in_order(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    try:
        pid = providers.create_m3u_provider(conn, "One", "http://example.com/one.m3u")
        window = _window(conn)
        _select(window, pid)

        seen = {}

        def fake_contextmenu(self, options):
            seen['options'] = options
            return -1

        monkeypatch.setattr(xbmcgui.Dialog, 'contextmenu', fake_contextmenu)
        window.getFocusId = lambda: LIST_ID
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_CONTEXT_MENU))

        addon = xbmcaddon.Addon()
        assert seen['options'] == [
            addon.getLocalizedString(providers_window._STR_REFRESH_NOW),
            addon.getLocalizedString(providers_window._STR_DISABLE),
            addon.getLocalizedString(providers_window._STR_MOVE),
            addon.getLocalizedString(providers_window._STR_DELETE),
        ]
    finally:
        conn.close()


def test_delete_with_yesno_true_soft_deletes_and_requests_refresh(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    try:
        pid = providers.create_m3u_provider(conn, "One", "http://example.com/one.m3u")
        window = _window(conn)
        _select(window, pid)

        _patch_delete_message(monkeypatch)
        monkeypatch.setattr(xbmcgui.Dialog, 'yesno', lambda self, h, m: True)
        window._delete_provider(pid, providers.get_provider(conn, pid))

        assert providers.get_provider(conn, pid) is None
        assert providers.list_providers(conn) == []
        window_props = xbmcgui.Window(10000)
        assert window_props.getProperty('script.kodimate.refresh_request') == str(pid) + ';ui'
        assert window.getFocusId() == ADD_BUTTON_ID
    finally:
        conn.close()


def test_delete_with_yesno_false_changes_nothing(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    try:
        pid = providers.create_m3u_provider(conn, "One", "http://example.com/one.m3u")
        window = _window(conn)
        _select(window, pid)

        _patch_delete_message(monkeypatch)
        monkeypatch.setattr(xbmcgui.Dialog, 'yesno', lambda self, h, m: False)
        window._delete_provider(pid, providers.get_provider(conn, pid))

        assert providers.get_provider(conn, pid) is not None
    finally:
        conn.close()


def test_move_up_then_drop_persists_sort_order(tmp_path):
    conn = _conn(tmp_path)
    try:
        p1 = providers.create_m3u_provider(conn, "One", "http://example.com/one.m3u")
        p2 = providers.create_m3u_provider(conn, "Two", "http://example.com/two.m3u")
        window = _window(conn)
        _select(window, p2)

        window._start_move(p2)
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_UP))
        assert window.getFocusId() == LIST_ID
        window.onClick(LIST_ID)

        rows = providers.list_providers(conn)
        assert [r['id'] for r in rows] == [p2, p1]
        assert window._move_provider_id is None
        assert window.getControl(LIST_ID).getSelectedPosition() == 0
        assert window.getFocusId() == LIST_ID
    finally:
        conn.close()


def test_move_back_restores_original_order(tmp_path):
    conn = _conn(tmp_path)
    try:
        p1 = providers.create_m3u_provider(conn, "One", "http://example.com/one.m3u")
        p2 = providers.create_m3u_provider(conn, "Two", "http://example.com/two.m3u")
        window = _window(conn)
        _select(window, p2)

        window._start_move(p2)
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_UP))
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))

        rows = providers.list_providers(conn)
        assert [r['id'] for r in rows] == [p1, p2]
        assert window._move_provider_id is None
        assert window.getControl(LIST_ID).getSelectedPosition() == 1
        assert window.getFocusId() == LIST_ID
    finally:
        conn.close()
