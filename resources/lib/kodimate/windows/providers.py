# -*- coding: utf-8 -*-
"""ProvidersWindow: list, add, edit, refresh Providers (issue #18 tracer bullet)."""
import threading
import time
from datetime import datetime, timezone

import xbmc
import xbmcaddon
import xbmcgui

from .. import ipc, log, providers
from .base import BaseWindow
from .provider_form import ProviderFormWindow

_POLL_JOIN_TIMEOUT_SECONDS = 2

LIST_ID = 200
ADD_BUTTON_ID = 300
REFRESH_ALL_BUTTON_ID = 301

_POLL_INTERVAL_SECONDS = 1
_SERVICE_TIMEOUT_SECONDS = 10

_STR_REFRESHING = 32020
_STR_NEVER_REFRESHED = 32021
_STR_CHANNELS_COUNT = 32022
_STR_MIN_AGO = 32023
_STR_HOURS_AGO = 32024
_STR_DAYS_AGO = 32025
_STR_JUST_NOW = 32026
_STR_SERVICE_NOT_RUNNING = 32027
_STR_SELECT_KIND = 32028
_STR_KIND_M3U = 32029
_STR_KIND_XTREAM = 32030
_STR_XTREAM_UNAVAILABLE = 32031
_STR_REFRESH_NOW = 32033
_STR_ENABLE = 32034
_STR_DISABLE = 32035


def _format_relative_time(addon, rel):
    if rel is None:
        return addon.getLocalizedString(_STR_NEVER_REFRESHED)
    kind, n = rel
    if kind == 'just_now':
        return addon.getLocalizedString(_STR_JUST_NOW)
    if kind == 'minutes_ago':
        return addon.getLocalizedString(_STR_MIN_AGO) % n
    if kind == 'hours_ago':
        return addon.getLocalizedString(_STR_HOURS_AGO) % n
    return addon.getLocalizedString(_STR_DAYS_AGO) % n


class ProvidersWindow(BaseWindow):
    xmlFile = 'script-kodimate-providers.xml'

    def onInit(self):
        self._addon = xbmcaddon.Addon()
        self._pending = ipc.PendingRequests(timeout_seconds=_SERVICE_TIMEOUT_SECONDS)
        self._stop = threading.Event()
        self._render()
        if not providers.list_providers(self.conn):
            self.setFocusId(ADD_BUTTON_ID)
        self._poll_thread = threading.Thread(target=self._poll_loop)
        self._poll_thread.daemon = True
        self._poll_thread.start()

    def onAction(self, action):
        action_id = action.getId()
        if action_id in (xbmcgui.ACTION_NAV_BACK, xbmcgui.ACTION_PREVIOUS_MENU):
            self.close()
            return
        if action_id == xbmcgui.ACTION_CONTEXT_MENU and self.getFocusId() == LIST_ID:
            self._context_menu()

    def onClick(self, control_id):
        if control_id == ADD_BUTTON_ID:
            self._add_provider()
        elif control_id == REFRESH_ALL_BUTTON_ID:
            self._refresh_all()
        elif control_id == LIST_ID:
            self._edit_selected()

    def close(self):
        self._stop.set()
        if hasattr(self, '_poll_thread'):
            self._poll_thread.join(_POLL_JOIN_TIMEOUT_SECONDS)
        super(ProvidersWindow, self).close()

    def _render(self):
        rows = providers.list_providers(self.conn)
        control = self.getControl(LIST_ID)
        control.reset()
        refreshing = set(ipc.refreshing_ids())
        for row in rows:
            item = xbmcgui.ListItem(label=row['name'])
            item.setLabel2(self._status_text(row, refreshing))
            item.setProperty('kind', row['kind'])
            item.setProperty('enabled', '1' if row['enabled'] else '0')
            item.setProperty('refreshing', '1' if str(row['id']) in refreshing else '0')
            item.setProperty('provider_id', str(row['id']))
            control.addItem(item)

    def _status_text(self, row, refreshing):
        if str(row['id']) in refreshing:
            return self._addon.getLocalizedString(_STR_REFRESHING)
        if row['last_error']:
            return providers.error_snippet(row['last_error'])
        if row['last_refresh_at']:
            rel = providers.relative_time(row['last_refresh_at'], datetime.now(timezone.utc))
            return self._addon.getLocalizedString(_STR_CHANNELS_COUNT) % (
                row['listable_count'], _format_relative_time(self._addon, rel)
            )
        return self._addon.getLocalizedString(_STR_NEVER_REFRESHED)

    def _selected_provider_id(self):
        item = self.getControl(LIST_ID).getSelectedItem()
        if item is None:
            return None
        return int(item.getProperty('provider_id'))

    def _add_provider(self):
        options = [
            self._addon.getLocalizedString(_STR_KIND_M3U),
            self._addon.getLocalizedString(_STR_KIND_XTREAM),
        ]
        choice = xbmcgui.Dialog().select(
            self._addon.getLocalizedString(_STR_SELECT_KIND), options
        )
        if choice == 1:
            xbmcgui.Dialog().notification(
                self._addon.getLocalizedString(32000),
                self._addon.getLocalizedString(_STR_XTREAM_UNAVAILABLE),
            )
            return
        if choice != 0:
            return
        form = ProviderFormWindow.open(conn=self.conn, provider_id=None)
        if getattr(form, 'result', None) is not None:
            self._after_save(form.result, form.needs_refresh)

    def _edit_selected(self):
        provider_id = self._selected_provider_id()
        if provider_id is None:
            return
        form = ProviderFormWindow.open(conn=self.conn, provider_id=provider_id)
        if getattr(form, 'result', None) is not None:
            self._after_save(form.result, form.needs_refresh)

    def _after_save(self, provider_id, needs_refresh):
        self._render()
        if needs_refresh:
            self._request_refresh([provider_id])

    def _refresh_all(self):
        self._request_refresh('all')

    def _request_refresh(self, ids_or_all):
        ipc.request_refresh(ids_or_all, ui=True)
        now = time.time()
        generation = ipc.db_generation()
        if ids_or_all == 'all':
            self._pending.add('all', now, generation)
        else:
            for provider_id in ids_or_all:
                self._pending.add(provider_id, now, generation)
        self._render()

    def _context_menu(self):
        provider_id = self._selected_provider_id()
        if provider_id is None:
            return
        row = providers.get_provider(self.conn, provider_id)
        if row is None:
            return
        refreshing = set(ipc.refreshing_ids())
        options = []
        actions = []
        if str(provider_id) not in refreshing:
            options.append(self._addon.getLocalizedString(_STR_REFRESH_NOW))
            actions.append('refresh')
        if row['enabled']:
            options.append(self._addon.getLocalizedString(_STR_DISABLE))
            actions.append('disable')
        else:
            options.append(self._addon.getLocalizedString(_STR_ENABLE))
            actions.append('enable')
        choice = xbmcgui.Dialog().contextmenu(options)
        if choice is None or choice < 0:
            return
        action = actions[choice]
        if action == 'refresh':
            self._request_refresh([provider_id])
        elif action in ('enable', 'disable'):
            needs_refresh = providers.update_provider(
                self.conn, provider_id, row['name'], row['m3u_url'],
                action == 'enable',
            )
            self._render()
            if needs_refresh:
                self._request_refresh([provider_id])

    def _poll_loop(self):
        last_refreshing = None
        last_generation = None
        while not self._stop.is_set():
            time.sleep(_POLL_INTERVAL_SECONDS)
            if self._stop.is_set():
                return
            try:
                refreshing = ipc.refreshing_ids()
                generation = ipc.db_generation()
                self._pending.observe(refreshing, generation)
                changed = refreshing != last_refreshing or generation != last_generation
                if changed:
                    last_refreshing = refreshing
                    last_generation = generation
                    self._render()
                self._check_timeouts()
                self._check_results()
            except Exception:
                log.log("ProvidersWindow poll iteration failed", xbmc.LOGERROR)

    def _check_timeouts(self):
        for _ in self._pending.timed_out(time.time()):
            xbmcgui.Dialog().notification(
                self._addon.getLocalizedString(32000),
                self._addon.getLocalizedString(_STR_SERVICE_NOT_RUNNING),
            )

    def _check_results(self):
        rows = providers.list_providers(self.conn)
        for row in rows:
            result = ipc.pop_refresh_result(row['id'])
            if result:
                self._pending.observe_result(row['id'])
            if result and result.startswith('error:'):
                xbmcgui.Dialog().notification(
                    self._addon.getLocalizedString(32000), result[len('error:'):]
                )
