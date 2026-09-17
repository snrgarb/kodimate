# -*- coding: utf-8 -*-
"""ProviderFormWindow: add/edit an M3U or Xtream Provider (issue #18, #20, #21)."""
import functools
import threading
import time

import xbmc
import xbmcaddon
import xbmcgui

from .. import connection_test, fetch, m3u, providers
from .base import BaseWindow

LIST_ID = 200
SAVE_BUTTON_ID = 300
CANCEL_BUTTON_ID = 301
TEST_BUTTON_ID = 302

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
_STR_EPG_OVERRIDE = 32059
_STR_CATCHUP_DAYS = 32060
_STR_ADVANCED = 32061
_STR_USER_AGENT = 32062
_STR_CATCHUP_CORRECTION = 32063
_STR_NUMBER_OFFSET = 32064
_STR_LIVE_FORM = 32065
_STR_CATCHUP_URL_FORM = 32066
_STR_AUTO = 32067
_STR_TEST_CONNECTION = 32068
_STR_STATUS = 32069
_STR_EXPIRES = 32070
_STR_CONNECTIONS = 32071
_STR_ALLOWED_FORMATS = 32072
_STR_LIVE_CATEGORIES = 32073
_STR_CHANNELS = 32074
_STR_EPG_DECLARED = 32075
_STR_YES = 32076
_STR_NO = 32077

_PASSWORD_MASK = '••••'

# Field -> validation-error-field mapping per kind, used to focus the
# offending row on Save/Test.
_COMMON_ERROR_ROWS = {
    'epg_override_url': 'epg_override',
    'catchup_days_default': 'catchup_days',
    'number_offset': 'number_offset',
    'catchup_correction_hours': 'catchup_correction',
}
_M3U_ERROR_ROWS = dict(_COMMON_ERROR_ROWS, m3u_url='playlist')
_XTREAM_ERROR_ROWS = dict(
    _COMMON_ERROR_ROWS,
    xtream_host='server', xtream_username='username', xtream_password='password',
)

_CORRECTION_RANGE = range(-12, 13)
_TEST_TIMEOUT_SECONDS = 15


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
        self._epg_override_url = (existing['epg_override_url'] if existing else '') or ''
        self._catchup_days_default = existing['catchup_days_default'] if existing else None
        self._user_agent = (existing['user_agent'] if existing else '') or ''
        self._catchup_correction_hours = existing['catchup_correction_hours'] if existing else 0
        self._number_offset = existing['number_offset'] if existing else 0
        self._stream_format = existing['stream_format'] if existing else None
        self._catchup_url_form = (existing['catchup_url_form'] if existing else None) or 'path'
        self._dirty = False
        self._rows = self._row_types()
        self._render()
        self.setFocusId(LIST_ID)

    def _row_types(self):
        if self._kind == 'xtream':
            return [
                'kind', 'name', 'server', 'username', 'password',
                'epg_override', 'catchup_days', 'advanced',
                'live_form', 'catchup_url_form', 'user_agent',
                'catchup_correction', 'number_offset', 'enabled',
            ]
        return [
            'kind', 'name', 'playlist', 'epg_override', 'catchup_days', 'advanced',
            'user_agent', 'catchup_correction', 'number_offset', 'enabled',
        ]

    def onAction(self, action):
        action_id = action.getId()
        if action_id in (xbmcgui.ACTION_NAV_BACK, xbmcgui.ACTION_PREVIOUS_MENU):
            self._cancel()
            return
        if action_id in (xbmcgui.ACTION_MOVE_UP, xbmcgui.ACTION_MOVE_DOWN):
            self._skip_heading(action_id)

    def _skip_heading(self, action_id):
        if self.getFocusId() != LIST_ID:
            return
        control = self.getControl(LIST_ID)
        position = control.getSelectedPosition()
        if self._rows[position] != 'advanced':
            return
        delta = 1 if action_id == xbmcgui.ACTION_MOVE_DOWN else -1
        new_position = position + delta
        if 0 <= new_position < len(self._rows):
            control.selectItem(new_position)

    def onClick(self, control_id):
        if control_id == SAVE_BUTTON_ID:
            self._save()
        elif control_id == CANCEL_BUTTON_ID:
            self._cancel()
        elif control_id == TEST_BUTTON_ID:
            self._test_connection()
        elif control_id == LIST_ID:
            self._edit_selected_row()

    def _kind_label(self):
        string_id = _STR_KIND_XTREAM if self._kind == 'xtream' else _STR_KIND_M3U
        return self._addon.getLocalizedString(string_id)

    def _render(self, hint=None):
        control = self.getControl(LIST_ID)
        had_focus = self.getFocusId() == LIST_ID
        selected_position = control.getSelectedPosition()
        control.reset()
        items = []
        for row_type in self._rows:
            item = xbmcgui.ListItem(label=self._row_label(row_type))
            if row_type == 'advanced':
                item.setProperty('heading', '1')
            else:
                item.setLabel2(self._row_value(row_type))
            items.append(item)
        if hint is not None:
            hint_row_type, message = hint
            if hint_row_type in self._rows:
                items[self._rows.index(hint_row_type)].setProperty('hint', message)
        for item in items:
            control.addItem(item)
        if had_focus:
            self.setFocusId(LIST_ID)
            control.selectItem(min(selected_position, len(items) - 1))

    def _row_label(self, row_type):
        return self._addon.getLocalizedString({
            'kind': _STR_KIND,
            'name': _STR_NAME,
            'playlist': _STR_PLAYLIST,
            'server': _STR_SERVER,
            'username': _STR_USERNAME,
            'password': _STR_PASSWORD,
            'epg_override': _STR_EPG_OVERRIDE,
            'catchup_days': _STR_CATCHUP_DAYS,
            'advanced': _STR_ADVANCED,
            'live_form': _STR_LIVE_FORM,
            'catchup_url_form': _STR_CATCHUP_URL_FORM,
            'user_agent': _STR_USER_AGENT,
            'catchup_correction': _STR_CATCHUP_CORRECTION,
            'number_offset': _STR_NUMBER_OFFSET,
            'enabled': _STR_ENABLED,
        }[row_type])

    def _format_correction(self, hours):
        return '{0}{1} h'.format('+' if hours > 0 else '', hours)

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
        if row_type == 'epg_override':
            return self._epg_override_url
        if row_type == 'catchup_days':
            return '' if self._catchup_days_default is None else str(self._catchup_days_default)
        if row_type == 'user_agent':
            return self._user_agent
        if row_type == 'catchup_correction':
            return self._format_correction(self._catchup_correction_hours)
        if row_type == 'number_offset':
            return str(self._number_offset)
        if row_type == 'live_form':
            return self._stream_format or self._addon.getLocalizedString(_STR_AUTO)
        if row_type == 'catchup_url_form':
            return (
                self._addon.getLocalizedString(_STR_AUTO) if self._catchup_url_form == 'auto'
                else self._catchup_url_form
            )
        return self._addon.getLocalizedString(_STR_ENABLED_ON if self._enabled else _STR_ENABLED_OFF)

    def _edit_selected_row(self):
        row_type = self._rows[self.getControl(LIST_ID).getSelectedPosition()]
        handler = {
            'name': self._edit_name,
            'playlist': self._edit_playlist,
            'server': self._edit_server,
            'username': self._edit_username,
            'password': self._edit_password,
            'epg_override': self._edit_epg_override,
            'catchup_days': self._edit_catchup_days,
            'user_agent': self._edit_user_agent,
            'catchup_correction': self._edit_catchup_correction,
            'number_offset': self._edit_number_offset,
            'live_form': self._edit_live_form,
            'catchup_url_form': self._edit_catchup_url_form,
            'enabled': self._toggle_enabled,
        }.get(row_type)
        if handler:
            handler()

    def _toggle_enabled(self):
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

    def _edit_epg_override(self):
        keyboard = xbmc.Keyboard(self._epg_override_url, self._addon.getLocalizedString(_STR_EPG_OVERRIDE))
        keyboard.doModal()
        if keyboard.isConfirmed():
            self._epg_override_url = keyboard.getText()
            self._dirty = True
            self._render()

    def _edit_user_agent(self):
        keyboard = xbmc.Keyboard(self._user_agent, self._addon.getLocalizedString(_STR_USER_AGENT))
        keyboard.doModal()
        if keyboard.isConfirmed():
            self._user_agent = keyboard.getText()
            self._dirty = True
            self._render()

    def _edit_catchup_days(self):
        current = '' if self._catchup_days_default is None else str(self._catchup_days_default)
        heading = self._addon.getLocalizedString(_STR_CATCHUP_DAYS)
        value = xbmcgui.Dialog().numeric(0, heading, current)
        if value is None:
            return
        self._catchup_days_default = int(value) if value != '' else None
        self._dirty = True
        self._render()

    def _edit_number_offset(self):
        heading = self._addon.getLocalizedString(_STR_NUMBER_OFFSET)
        value = xbmcgui.Dialog().numeric(0, heading, str(self._number_offset))
        if value is None:
            return
        self._number_offset = int(value) if value != '' else 0
        self._dirty = True
        self._render()

    def _edit_catchup_correction(self):
        options = [self._format_correction(h) for h in _CORRECTION_RANGE]
        heading = self._addon.getLocalizedString(_STR_CATCHUP_CORRECTION)
        choice = xbmcgui.Dialog().select(heading, options)
        if choice == -1:
            return
        self._catchup_correction_hours = list(_CORRECTION_RANGE)[choice]
        self._dirty = True
        self._render()

    def _edit_live_form(self):
        auto = self._addon.getLocalizedString(_STR_AUTO)
        options = [auto, 'ts', 'm3u8']
        heading = self._addon.getLocalizedString(_STR_LIVE_FORM)
        choice = xbmcgui.Dialog().select(heading, options)
        if choice == -1:
            return
        self._stream_format = None if choice == 0 else options[choice]
        self._dirty = True
        self._render()

    def _edit_catchup_url_form(self):
        auto = self._addon.getLocalizedString(_STR_AUTO)
        options = [auto, 'path', 'query']
        values = ['auto', 'path', 'query']
        heading = self._addon.getLocalizedString(_STR_CATCHUP_URL_FORM)
        choice = xbmcgui.Dialog().select(heading, options)
        if choice == -1:
            return
        self._catchup_url_form = values[choice]
        self._dirty = True
        self._render()

    def _validate(self):
        if self._kind == 'xtream':
            errors = providers.validate_xtream(
                self._name, self._host, self._username, self._password,
                epg_override_url=self._epg_override_url,
                catchup_days_default=self._catchup_days_default,
                number_offset=self._number_offset,
                catchup_correction_hours=self._catchup_correction_hours,
            )
            return errors, _XTREAM_ERROR_ROWS
        errors = providers.validate_m3u(
            self._name, self._m3u_url,
            epg_override_url=self._epg_override_url,
            catchup_days_default=self._catchup_days_default,
            number_offset=self._number_offset,
            catchup_correction_hours=self._catchup_correction_hours,
        )
        return errors, _M3U_ERROR_ROWS

    def _focus_and_hint(self, errors, error_rows):
        field, message_id = errors[0]
        row_type = error_rows.get(field, 'name')
        message = self._addon.getLocalizedString(message_id)
        self._render(hint=(row_type, message))
        self.getControl(LIST_ID).selectItem(self._rows.index(row_type))
        xbmcgui.Dialog().notification(self._addon.getLocalizedString(32000), message)

    def _save(self):
        errors, error_rows = self._validate()
        if errors:
            self._focus_and_hint(errors, error_rows)
            return

        if self._kind == 'xtream':
            name = self._name.strip() or providers.auto_name_xtream(self._host)
            kwargs = dict(
                epg_override_url=self._epg_override_url,
                catchup_days_default=self._catchup_days_default,
                user_agent=self._user_agent,
                catchup_correction_hours=self._catchup_correction_hours,
                number_offset=self._number_offset,
                stream_format=self._stream_format,
                catchup_url_form=self._catchup_url_form,
            )
            if self.provider_id:
                self.needs_refresh = providers.update_xtream_provider(
                    self.conn, self.provider_id, name, self._host, self._username,
                    self._password, self._enabled, **kwargs
                )
                self.result = self.provider_id
            else:
                self.result = providers.create_xtream_provider(
                    self.conn, name, self._host, self._username, self._password,
                    enabled=self._enabled, **kwargs
                )
                self.needs_refresh = True
        else:
            name = self._name.strip() or providers.auto_name(self._m3u_url)
            kwargs = dict(
                epg_override_url=self._epg_override_url,
                catchup_days_default=self._catchup_days_default,
                user_agent=self._user_agent,
                catchup_correction_hours=self._catchup_correction_hours,
                number_offset=self._number_offset,
            )
            if self.provider_id:
                self.needs_refresh = providers.update_provider(
                    self.conn, self.provider_id, name, self._m3u_url, self._enabled, **kwargs
                )
                self.result = self.provider_id
            else:
                self.result = providers.create_m3u_provider(
                    self.conn, name, self._m3u_url, enabled=self._enabled, **kwargs
                )
                self.needs_refresh = True
        self.close()

    def _connection_fields(self):
        user_agent = self._user_agent or None
        if self._kind == 'xtream':
            return {
                'xtream_host': self._host,
                'xtream_username': self._username,
                'xtream_password': self._password,
                'user_agent': user_agent,
            }
        return {'m3u_url': self._m3u_url, 'user_agent': user_agent}

    def _format_test_result(self, result):
        heading = self._addon.getLocalizedString
        if self._kind == 'xtream':
            lines = [
                '{0}: {1}'.format(heading(_STR_STATUS), result['status'] or ''),
                '{0}: {1}'.format(heading(_STR_EXPIRES), result['account_expires_at'] or ''),
                '{0}: {1}/{2}'.format(
                    heading(_STR_CONNECTIONS),
                    result['active_connections'], result['max_connections'],
                ),
                '{0}: {1}'.format(
                    heading(_STR_ALLOWED_FORMATS), ', '.join(result['allowed_output_formats'] or [])
                ),
                '{0}: {1}'.format(heading(_STR_LIVE_CATEGORIES), result['live_category_count']),
            ]
        else:
            declared = heading(_STR_YES) if result['epg_declared'] else heading(_STR_NO)
            lines = [
                '{0}: {1}'.format(heading(_STR_CHANNELS), result['channel_count']),
                '{0}: {1}'.format(heading(_STR_EPG_DECLARED), declared),
            ]
        return '\n'.join(lines)

    def _test_connection(self):
        errors, error_rows = self._validate()
        if errors:
            self._focus_and_hint(errors, error_rows)
            return

        fields = self._connection_fields()
        fetcher = functools.partial(fetch.fetch_playlist, timeout=_TEST_TIMEOUT_SECONDS)
        outcome = {}

        def _worker():
            try:
                outcome['result'] = connection_test.test_connection(self._kind, fields, fetcher)
            except (fetch.FetchError, m3u.M3UError) as exc:
                outcome['error'] = str(exc)
            except Exception as exc:
                outcome['error'] = str(exc) or fetch.ERROR_UNREACHABLE

        thread = threading.Thread(target=_worker)
        thread.daemon = True
        thread.start()

        progress = xbmcgui.DialogProgress()
        progress.create(self._addon.getLocalizedString(_STR_TEST_CONNECTION))
        status = connection_test.wait_for_worker(
            thread, progress, time.sleep, time.monotonic, timeout=_TEST_TIMEOUT_SECONDS
        )
        progress.close()

        if status == 'cancelled':
            return
        heading = self._addon.getLocalizedString(32000)
        if status == 'timeout':
            xbmcgui.Dialog().ok(heading, fetch.ERROR_TIMED_OUT)
            return
        if 'error' in outcome:
            xbmcgui.Dialog().ok(heading, outcome['error'])
            return
        xbmcgui.Dialog().ok(heading, self._format_test_result(outcome['result']))

    def _cancel(self):
        if self._dirty:
            if not xbmcgui.Dialog().yesno(
                self._addon.getLocalizedString(32000),
                self._addon.getLocalizedString(_STR_DISCARD),
            ):
                return
        self.close()
