import xbmcgui

from kodimate import db, providers
from kodimate.windows import provider_form
from kodimate.windows.provider_form import ProviderFormWindow, LIST_ID


def _conn(tmp_path):
    return db.open_db(str(tmp_path / "kodimate.db"))


def _window(conn, kind, provider_id=None):
    window = ProviderFormWindow('script-kodimate-provider-form.xml', '/addon', 'Main', '1080i',
                                 conn=conn, kind=kind, provider_id=provider_id)
    window.onInit()
    return window


def test_title_label_for_xtream_kind(tmp_path):
    conn = _conn(tmp_path)
    try:
        window = _window(conn, 'xtream')
        assert window.getControl(100).getLabel() == "String 32052"
    finally:
        conn.close()


def test_title_label_for_m3u_kind(tmp_path):
    conn = _conn(tmp_path)
    try:
        window = _window(conn, 'm3u')
        assert window.getControl(100).getLabel() == "String 32017"
    finally:
        conn.close()


# -- row order -------------------------------------------------------------

def test_m3u_row_order_and_heading_position(tmp_path):
    conn = _conn(tmp_path)
    try:
        window = _window(conn, 'm3u')
        assert window._rows == [
            'kind', 'name', 'playlist', 'epg_override', 'catchup_days', 'advanced',
            'user_agent', 'catchup_correction', 'number_offset', 'enabled',
        ]
    finally:
        conn.close()


def test_xtream_row_order_and_heading_position(tmp_path):
    conn = _conn(tmp_path)
    try:
        window = _window(conn, 'xtream')
        assert window._rows == [
            'kind', 'name', 'server', 'username', 'password',
            'epg_override', 'catchup_days', 'advanced',
            'live_form', 'catchup_url_form', 'user_agent',
            'catchup_correction', 'number_offset', 'enabled',
        ]
    finally:
        conn.close()


def test_advanced_heading_row_marked_and_not_actionable(tmp_path):
    conn = _conn(tmp_path)
    try:
        window = _window(conn, 'm3u')
        idx = window._rows.index('advanced')
        control = window.getControl(LIST_ID)
        control.selectItem(idx)
        window._edit_selected_row()  # should no-op, no exception
        assert control._items[idx].getProperty('heading') == '1'
    finally:
        conn.close()


# -- heading skip on move ---------------------------------------------------

def test_move_down_past_heading_skips_it(tmp_path):
    conn = _conn(tmp_path)
    try:
        window = _window(conn, 'm3u')
        heading_idx = window._rows.index('advanced')
        control = window.getControl(LIST_ID)
        control.selectItem(heading_idx)
        window.setFocusId(LIST_ID)
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_DOWN))
        assert control.getSelectedPosition() == heading_idx + 1
    finally:
        conn.close()


def test_move_up_past_heading_skips_it(tmp_path):
    conn = _conn(tmp_path)
    try:
        window = _window(conn, 'm3u')
        heading_idx = window._rows.index('advanced')
        control = window.getControl(LIST_ID)
        control.selectItem(heading_idx)
        window.setFocusId(LIST_ID)
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_UP))
        assert control.getSelectedPosition() == heading_idx - 1
    finally:
        conn.close()


def test_move_on_non_heading_row_is_untouched(tmp_path):
    conn = _conn(tmp_path)
    try:
        window = _window(conn, 'm3u')
        control = window.getControl(LIST_ID)
        control.selectItem(1)
        window.setFocusId(LIST_ID)
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_DOWN))
        assert control.getSelectedPosition() == 1
    finally:
        conn.close()


# -- validation hint + focus on invalid save --------------------------------

def test_save_with_missing_playlist_focuses_row_and_sets_hint(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    try:
        notifications = []
        monkeypatch.setattr(
            xbmcgui.Dialog, 'notification',
            lambda self, heading, message, icon=None, time=5000: notifications.append(message)
        )
        window = _window(conn, 'm3u')
        window._save()
        control = window.getControl(LIST_ID)
        playlist_idx = window._rows.index('playlist')
        assert control.getSelectedPosition() == playlist_idx
        assert control._items[playlist_idx].getProperty('hint') == "String 32010"
        assert notifications == ["String 32010"]
        assert window.result is None
    finally:
        conn.close()


def test_save_with_invalid_number_offset_focuses_that_row(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    try:
        monkeypatch.setattr(
            xbmcgui.Dialog, 'notification',
            lambda self, heading, message, icon=None, time=5000: None
        )
        window = _window(conn, 'm3u')
        window._m3u_url = 'http://example.com/x.m3u'
        window._number_offset = -1
        window._save()
        control = window.getControl(LIST_ID)
        offset_idx = window._rows.index('number_offset')
        assert control.getSelectedPosition() == offset_idx
    finally:
        conn.close()


# -- dirty/clean cancel ------------------------------------------------------

def test_clean_cancel_closes_without_prompt(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    try:
        calls = []
        monkeypatch.setattr(xbmcgui.Dialog, 'yesno', lambda self, h, m: calls.append(1) or True)
        window = _window(conn, 'm3u')
        window._cancel()
        assert calls == []
    finally:
        conn.close()


def test_dirty_cancel_prompts_and_discards_on_yes(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    try:
        monkeypatch.setattr(xbmcgui.Dialog, 'yesno', lambda self, h, m: True)
        window = _window(conn, 'm3u')
        window._dirty = True
        closed = []
        window.close = lambda: closed.append(1)
        window._cancel()
        assert closed == [1]
    finally:
        conn.close()


def test_dirty_cancel_keeps_form_open_on_no(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    try:
        monkeypatch.setattr(xbmcgui.Dialog, 'yesno', lambda self, h, m: False)
        window = _window(conn, 'm3u')
        window._dirty = True
        closed = []
        window.close = lambda: closed.append(1)
        window._cancel()
        assert closed == []
    finally:
        conn.close()


# -- config_version / needs_refresh on save ---------------------------------

def test_epg_override_change_bumps_config_version(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = providers.create_m3u_provider(conn, "One", "http://example.com/one.m3u")
        before = providers.get_provider(conn, pid)
        window = _window(conn, 'm3u', provider_id=pid)
        window._epg_override_url = 'http://example.com/epg.xml'
        window._save()
        after = providers.get_provider(conn, pid)
        assert window.needs_refresh is True
        assert after['config_version'] == before['config_version'] + 1
    finally:
        conn.close()


def test_offset_correction_user_agent_name_changes_do_not_bump_or_refresh(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = providers.create_m3u_provider(conn, "One", "http://example.com/one.m3u")
        before = providers.get_provider(conn, pid)
        window = _window(conn, 'm3u', provider_id=pid)
        window._number_offset = 5
        window._catchup_correction_hours = 2
        window._user_agent = 'MyAgent/1.0'
        window._name = 'Renamed'
        window._save()
        after = providers.get_provider(conn, pid)
        assert window.needs_refresh is False
        assert after['config_version'] == before['config_version']
        assert after['number_offset'] == 5
        assert after['name'] == 'Renamed'
    finally:
        conn.close()


# -- Test Connection --------------------------------------------------------

def test_test_connection_generic_exception_shows_error_dialog_not_crash(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    try:
        def _raise(kind, fields, fetcher):
            raise KeyError('boom')

        monkeypatch.setattr(provider_form.connection_test, 'test_connection', _raise)
        ok_calls = []
        monkeypatch.setattr(
            xbmcgui.Dialog, 'ok',
            lambda self, heading, message: ok_calls.append(message) or True
        )
        window = _window(conn, 'm3u')
        window._m3u_url = 'http://example.com/x.m3u'
        window._test_connection()
        assert len(ok_calls) == 1
    finally:
        conn.close()


def test_explicit_stream_format_clears_learned_stream_format(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = providers.create_xtream_provider(conn, "One", "http://xc.example", "user", "pass")
        conn.execute("UPDATE provider SET learned_stream_format = 'm3u8' WHERE id = ?", (pid,))
        window = _window(conn, 'xtream', provider_id=pid)
        window._stream_format = 'ts'
        window._save()
        row = conn.execute(
            "SELECT learned_stream_format, stream_format FROM provider WHERE id = ?", (pid,)
        ).fetchone()
        assert row[0] is None
        assert row[1] == 'ts'
    finally:
        conn.close()
