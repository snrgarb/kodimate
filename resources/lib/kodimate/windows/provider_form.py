# -*- coding: utf-8 -*-
"""ProviderFormWindow: add/edit an M3U Provider (issue #18 tracer bullet)."""
import xbmc
import xbmcaddon
import xbmcgui

from .. import providers
from .base import BaseWindow

LIST_ID = 200
SAVE_BUTTON_ID = 300
CANCEL_BUTTON_ID = 301

_ROW_NAME = 0
_ROW_PLAYLIST = 1
_ROW_ENABLED = 2

_STR_NAME = 32012
_STR_PLAYLIST = 32013
_STR_ENABLED = 32014
_STR_ENTER_URL = 32018
_STR_BROWSE_FILE = 32019
_STR_DISCARD = 32036


class ProviderFormWindow(BaseWindow):
    xmlFile = 'script-kodimate-provider-form.xml'

    def onInit(self):
        self._addon = xbmcaddon.Addon()
        self.result = None
        self.needs_refresh = False
        existing = providers.get_provider(self.conn, self.provider_id) if self.provider_id else None
        self._name = existing['name'] if existing else ''
        self._m3u_url = existing['m3u_url'] if existing else ''
        self._enabled = bool(existing['enabled']) if existing else True
        self._dirty = False
        self._render()

    def onAction(self, action):
        action_id = action.getId()
        if action_id in (xbmcgui.ACTION_NAV_BACK, xbmcgui.ACTION_PREVIOUS_MENU):
            self._cancel()

    def onClick(self, control_id):
        if control_id == SAVE_BUTTON_ID:
            self._save()
        elif control_id == CANCEL_BUTTON_ID:
            self._cancel()
        elif control_id == LIST_ID:
            self._edit_selected_row()

    def _render(self):
        control = self.getControl(LIST_ID)
        control.reset()
        name_item = xbmcgui.ListItem(label=self._addon.getLocalizedString(_STR_NAME))
        name_item.setLabel2(self._name)
        control.addItem(name_item)
        playlist_item = xbmcgui.ListItem(label=self._addon.getLocalizedString(_STR_PLAYLIST))
        playlist_item.setLabel2(self._m3u_url)
        control.addItem(playlist_item)
        enabled_item = xbmcgui.ListItem(label=self._addon.getLocalizedString(_STR_ENABLED))
        enabled_item.setLabel2('1' if self._enabled else '0')
        control.addItem(enabled_item)

    def _edit_selected_row(self):
        position = self.getControl(LIST_ID).getSelectedPosition()
        if position == _ROW_NAME:
            self._edit_name()
        elif position == _ROW_PLAYLIST:
            self._edit_playlist()
        elif position == _ROW_ENABLED:
            self._enabled = not self._enabled
            self._dirty = True
            self._render()

    def _edit_name(self):
        keyboard = xbmc.Keyboard(self._name, self._addon.getLocalizedString(_STR_NAME))
        keyboard.doModal()
        if keyboard.isConfirmed():
            self._name = keyboard.getText()
            self._dirty = True
            self._render()

    def _edit_playlist(self):
        options = [
            self._addon.getLocalizedString(_STR_ENTER_URL),
            self._addon.getLocalizedString(_STR_BROWSE_FILE),
        ]
        choice = xbmcgui.Dialog().select(self._addon.getLocalizedString(_STR_PLAYLIST), options)
        if choice == 0:
            keyboard = xbmc.Keyboard(self._m3u_url, self._addon.getLocalizedString(_STR_PLAYLIST))
            keyboard.doModal()
            if keyboard.isConfirmed():
                self._m3u_url = keyboard.getText()
                self._dirty = True
                self._render()
        elif choice == 1:
            path = xbmcgui.Dialog().browse(
                1, self._addon.getLocalizedString(_STR_PLAYLIST), 'files', '.m3u|.m3u8'
            )
            if path:
                self._m3u_url = path
                self._dirty = True
                self._render()

    def _save(self):
        errors = providers.validate_m3u(self._name, self._m3u_url)
        if errors:
            field, message_id = errors[0]
            row = {'m3u_url': _ROW_PLAYLIST}.get(field, _ROW_NAME)
            self.getControl(LIST_ID).selectItem(row)
            xbmcgui.Dialog().notification(
                self._addon.getLocalizedString(32000),
                self._addon.getLocalizedString(message_id),
            )
            return
        name = self._name.strip() or providers.auto_name(self._m3u_url)
        if self.provider_id:
            self.needs_refresh = providers.update_provider(
                self.conn, self.provider_id, name, self._m3u_url, self._enabled
            )
            self.result = self.provider_id
        else:
            self.result = providers.create_m3u_provider(
                self.conn, name, self._m3u_url, enabled=self._enabled
            )
            self.needs_refresh = True
        self.close()

    def _cancel(self):
        if self._dirty:
            if not xbmcgui.Dialog().yesno(
                self._addon.getLocalizedString(32000),
                self._addon.getLocalizedString(_STR_DISCARD),
            ):
                return
        self.close()
