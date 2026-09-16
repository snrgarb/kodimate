# -*- coding: utf-8 -*-
"""ProviderFormWindow: add/edit an M3U or Xtream Provider (issue #18, #20)."""
import xbmc
import xbmcaddon
import xbmcgui

from .. import providers
from .base import BaseWindow

LIST_ID = 200
SAVE_BUTTON_ID = 300
CANCEL_BUTTON_ID = 301

_STR_KIND = 32042
_STR_KIND_M3U = 32029
_STR_KIND_XTREAM = 32030
_STR_NAME = 32012
_STR_PLAYLIST = 32013
_STR_ENABLED = 32014
_STR_SERVER = 32043
_STR_USERNAME = 32044
_STR_PASSWORD = 32045
_STR_ENTER_URL = 32018
_STR_BROWSE_FILE = 32019
_STR_DISCARD = 32036
_STR_GET_PHP_PARSED = 32050
_STR_TITLE_M3U = 32017
_STR_TITLE_XTREAM = 32052
_STR_ENABLED_ON = 32053
_STR_ENABLED_OFF = 32054

_PASSWORD_MASK = '••••'

# Field -> validation-error-field mapping per kind, used to focus the
# offending row on Save.
_M3U_ERROR_ROWS = {'m3u_url': 'playlist'}
_XTREAM_ERROR_ROWS = {
    'xtream_host': 'server', 'xtream_username': 'username', 'xtream_password': 'password',
}


class ProviderFormWindow(BaseWindow):
    xmlFile = 'script-kodimate-provider-form.xml'

    def onInit(self):
        self._addon = xbmcaddon.Addon()
        self.result = None
        self.needs_refresh = False
        existing = providers.get_provider(self.conn, self.provider_id) if self.provider_id else None
        self._kind = existing['kind'] if existing else getattr(self, 'kind', 'm3u')
        self.getControl(100).setLabel(self._addon.getLocalizedString(
            _STR_TITLE_XTREAM if self._kind == 'xtream' else _STR_TITLE_M3U
        ))
        self._name = existing['name'] if existing else ''
        self._m3u_url = existing['m3u_url'] if existing else ''
        self._host = (existing['xtream_host'] if existing else '') or ''
        self._username = (existing['xtream_username'] if existing else '') or ''
        self._password = (existing['xtream_password'] if existing else '') or ''
        self._enabled = bool(existing['enabled']) if existing else True
        self._dirty = False
        self._rows = self._row_types()
        self._render()

    def _row_types(self):
        if self._kind == 'xtream':
            return ['kind', 'name', 'server', 'username', 'password', 'enabled']
        return ['kind', 'name', 'playlist', 'enabled']

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

    def _kind_label(self):
        string_id = _STR_KIND_XTREAM if self._kind == 'xtream' else _STR_KIND_M3U
        return self._addon.getLocalizedString(string_id)

    def _render(self):
        control = self.getControl(LIST_ID)
        control.reset()
        for row_type in self._rows:
            item = xbmcgui.ListItem(label=self._row_label(row_type))
            item.setLabel2(self._row_value(row_type))
            control.addItem(item)

    def _row_label(self, row_type):
        return self._addon.getLocalizedString({
            'kind': _STR_KIND,
            'name': _STR_NAME,
            'playlist': _STR_PLAYLIST,
            'server': _STR_SERVER,
            'username': _STR_USERNAME,
            'password': _STR_PASSWORD,
            'enabled': _STR_ENABLED,
        }[row_type])

    def _row_value(self, row_type):
        if row_type == 'kind':
            return self._kind_label()
        if row_type == 'name':
            return self._name
        if row_type == 'playlist':
            return self._m3u_url
        if row_type == 'server':
            return self._host
        if row_type == 'username':
            return self._username
        if row_type == 'password':
            return _PASSWORD_MASK if self._password else ''
        return self._addon.getLocalizedString(_STR_ENABLED_ON if self._enabled else _STR_ENABLED_OFF)

    def _edit_selected_row(self):
        row_type = self._rows[self.getControl(LIST_ID).getSelectedPosition()]
        if row_type == 'kind':
            return
        if row_type == 'name':
            self._edit_name()
        elif row_type == 'playlist':
            self._edit_playlist()
        elif row_type == 'server':
            self._edit_server()
        elif row_type == 'username':
            self._edit_username()
        elif row_type == 'password':
            self._edit_password()
        elif row_type == 'enabled':
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

    def _edit_server(self):
        keyboard = xbmc.Keyboard(self._host, self._addon.getLocalizedString(_STR_SERVER))
        keyboard.doModal()
        if not keyboard.isConfirmed():
            return
        text = keyboard.getText()
        split = providers.split_get_php_url(text)
        if split:
            self._host, self._username, self._password = split
            xbmcgui.Dialog().notification(
                self._addon.getLocalizedString(32000),
                self._addon.getLocalizedString(_STR_GET_PHP_PARSED),
            )
        else:
            self._host = text
        self._dirty = True
        self._render()

    def _edit_username(self):
        keyboard = xbmc.Keyboard(self._username, self._addon.getLocalizedString(_STR_USERNAME))
        keyboard.doModal()
        if keyboard.isConfirmed():
            self._username = keyboard.getText()
            self._dirty = True
            self._render()

    def _edit_password(self):
        keyboard = xbmc.Keyboard(self._password, self._addon.getLocalizedString(_STR_PASSWORD), True)
        keyboard.doModal()
        if keyboard.isConfirmed():
            self._password = keyboard.getText()
            self._dirty = True
            self._render()

    def _save(self):
        if self._kind == 'xtream':
            errors = providers.validate_xtream(self._name, self._host, self._username, self._password)
            error_rows = _XTREAM_ERROR_ROWS
        else:
            errors = providers.validate_m3u(self._name, self._m3u_url)
            error_rows = _M3U_ERROR_ROWS
        if errors:
            field, message_id = errors[0]
            row_type = error_rows.get(field, 'name')
            self.getControl(LIST_ID).selectItem(self._rows.index(row_type))
            xbmcgui.Dialog().notification(
                self._addon.getLocalizedString(32000),
                self._addon.getLocalizedString(message_id),
            )
            return

        if self._kind == 'xtream':
            name = self._name.strip() or providers.auto_name_xtream(self._host)
            if self.provider_id:
                self.needs_refresh = providers.update_xtream_provider(
                    self.conn, self.provider_id, name, self._host, self._username,
                    self._password, self._enabled,
                )
                self.result = self.provider_id
            else:
                self.result = providers.create_xtream_provider(
                    self.conn, name, self._host, self._username, self._password,
                    enabled=self._enabled,
                )
                self.needs_refresh = True
        else:
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
