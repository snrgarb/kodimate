# -*- coding: utf-8 -*-
"""PlaybackWindow: minimal in-player UI driven by a PlaybackSession (issue #24).

Black screen + spinner while Connecting/Reconnecting, channel number/name
and a status line reflecting the session's state, driven entirely off
window properties (`state`, `channel_name`, `channel_number`, `reason`).
Back aborts the session; OK while Failed starts a brand-new one.
"""
import time

import xbmc
import xbmcaddon
import xbmcgui

from .. import playback
from .. import player as player_module
from .. import providers

_STR_CONNECTING = 32084
_STR_RECONNECTING = 32085
_STR_UNAVAILABLE = 32086
_STR_LOGIN_REJECTED = 32087
_STR_CONNECTION_LIMIT = 32088
_STR_CONNECTION_LIMIT_N = 32089

_REASON_STRINGS = {
    'unavailable': _STR_UNAVAILABLE,
    'login_rejected': _STR_LOGIN_REJECTED,
    'connection_limit': _STR_CONNECTION_LIMIT,
}

_ACTIVATE_FULLSCREEN_SLEEP_MS = 300

_BUSY_DIALOG_ACTIVATE = 'ActivateWindow(busydialognocancel)'
_BUSY_DIALOG_CLOSE = 'Dialog.Close(busydialognocancel)'


class PlaybackWindow(xbmcgui.WindowXMLDialog):
    xmlFile = 'script-kodimate-playback.xml'
    theme = 'Main'
    res = '1080i'

    conn = None
    snapshot = None
    player = None
    probe = None
    scheduler = None
    clock = None
    persist_learned_form = None
    session = None
    _busy_dialog_shown = False

    def __init__(self, *args, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
        super(PlaybackWindow, self).__init__(*args)
        # Set before doModal() draws the first frame: WindowXMLDialog
        # honours setProperty() called here, so the spinner and channel
        # labels are already correct on frame one instead of appearing a
        # beat later once onInit() runs.
        self.setProperty('state', 'connecting')
        self.setProperty('status_text', xbmcaddon.Addon().getLocalizedString(_STR_CONNECTING))
        if self.snapshot is not None:
            self.setProperty('channel_name', self.snapshot['name'])
            self.setProperty('channel_number', str(self.snapshot['number']))

    @classmethod
    def open(cls, **kwargs):
        path = xbmcaddon.Addon().getAddonInfo('path')
        window = cls(cls.xmlFile, path, cls.theme, cls.res, **kwargs)
        window.doModal()
        return window

    def onInit(self):
        if self.player is None:
            self.player = player_module.get_player()
        if self.probe is None:
            self.probe = playback.fetch_probe
        if self.scheduler is None:
            self.scheduler = playback.timer_scheduler
        if self.clock is None:
            self.clock = time.monotonic
        if self.persist_learned_form is None:
            self.persist_learned_form = self._persist_learned_form
        self._start_new_session()

    def _persist_learned_form(self, provider_id, form):
        providers.set_learned_stream_format(self.conn, provider_id, form)

    def _start_new_session(self):
        self.setProperty('state', 'connecting')
        self.setProperty('status_text', xbmcaddon.Addon().getLocalizedString(_STR_CONNECTING))
        self.setProperty('reason', '')
        self._show_busy_dialog()
        self.session = playback.PlaybackSession(
            self.snapshot, self.player, self.probe, self.scheduler, self.clock,
            self.persist_learned_form, self._on_state,
        )
        self.player.attach(self.session)
        self.session.start()
        xbmc.sleep(_ACTIVATE_FULLSCREEN_SLEEP_MS)
        xbmc.executebuiltin('ActivateWindow(fullscreenvideo)')
        # Re-issue (not gated by _busy_dialog_shown) so the busy dialog sits
        # on top of the just-activated fullscreen video -- but only while
        # still connecting/reconnecting: the session may have already
        # reached 'playing'/'failed' and closed the dialog during the sleep
        # above, and reopening it here would leave it orphaned.
        if self.session.state in ('connecting', 'reconnecting'):
            xbmc.executebuiltin(_BUSY_DIALOG_ACTIVATE)
            self._busy_dialog_shown = True

    def _show_busy_dialog(self):
        if not self._busy_dialog_shown:
            xbmc.executebuiltin(_BUSY_DIALOG_ACTIVATE)
            self._busy_dialog_shown = True

    def _close_busy_dialog(self):
        # Always issued on the way out, even if never shown.
        xbmc.executebuiltin(_BUSY_DIALOG_CLOSE)
        self._busy_dialog_shown = False

    def _on_state(self, state, reason):
        addon = xbmcaddon.Addon()
        self.setProperty('state', state)
        self.setProperty('reason', reason or '')
        if state == 'connecting':
            self.setProperty('status_text', addon.getLocalizedString(_STR_CONNECTING))
            self._show_busy_dialog()
        elif state == 'reconnecting':
            self.setProperty('status_text', addon.getLocalizedString(_STR_RECONNECTING))
            self._show_busy_dialog()
        elif state == 'playing':
            self.setProperty('status_text', '')
            self._close_busy_dialog()
        elif state == 'failed':
            string_id = _REASON_STRINGS.get(reason, _STR_UNAVAILABLE)
            text = addon.getLocalizedString(string_id)
            if reason == 'connection_limit' and self.snapshot.get('max_connections'):
                text = addon.getLocalizedString(_STR_CONNECTION_LIMIT_N) % self.snapshot['max_connections']
            self.setProperty('status_text', text)
            self._close_busy_dialog()

    def onAction(self, action):
        action_id = action.getId()
        if action_id in (xbmcgui.ACTION_NAV_BACK, xbmcgui.ACTION_PREVIOUS_MENU):
            self._abort_and_close()
        elif action_id == xbmcgui.ACTION_SELECT_ITEM and self.session.state == 'failed':
            self._start_new_session()

    def _abort_and_close(self):
        self.session.abort()
        self.player.detach(self.session)
        self._close_busy_dialog()
        self.close()
