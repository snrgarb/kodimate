# -*- coding: utf-8 -*-
"""ChannelListWindow: Groups pane and Channels pane (issue #19, browsing only)."""
import threading
from datetime import datetime

import xbmcaddon
import xbmcgui

from .. import channels, guide, ipc, playback
from .base import BaseWindow
from .guide import GuideWindow
from .playback import PlaybackWindow

TOGGLE_HIDDEN_ID = 300
GROUPS_LIST_ID = 200
CHANNELS_LIST_ID = 201

# Real Kodi's xbmcgui module does not export ACTION_SHOW_INFO; defined here
# directly from Kodi's ActionIDs.h numeric value instead (see guide.py for
# the same pattern with its own numeric action ids).
_ACTION_SHOW_INFO = 11

_STR_ALL_CHANNELS = 32038
_STR_FAVOURITES = 32039
_STR_MOVE = 32078
_STR_RENUMBER = 32100
_STR_RENUMBER_HEADING = 32101
_STR_HIDE = 32102
_STR_UNHIDE = 32103
_STR_ADD_FAVOURITE = 32104
_STR_REMOVE_FAVOURITE = 32105
_STR_RESET = 32106

_GROUP_SELECTION_DEBOUNCE_SECONDS = 0.35


class ChannelListWindow(BaseWindow):
    xmlFile = 'script-kodimate-channel-list.xml'
    now_fn = datetime.utcnow
    guide_cls = GuideWindow

    def onInit(self):
        if getattr(self, '_initialised', False):
            with self._lock:
                if self._render_pending:
                    self._render_pending = False
                    self._refresh_in_place()
            return

        self._show_hidden = False
        self._last_group_position = 0
        self._render_timer = None
        self._closed = False
        self._modal_depth = 0
        self._render_pending = False
        self._watcher = None
        self._move_key = None
        self._move_order = None
        self._move_original_order = None
        # Guards _modal_depth/_render_pending/_closed and every render below:
        # GenerationWatcher.onNotification runs on Kodi's Monitor thread
        # while the UI thread may be inside onAction/onClick.
        self._lock = threading.RLock()
        self.setProperty('show_hidden', '0')
        self._render_groups()
        self._render_channels()
        self._watcher = ipc.GenerationWatcher(self._on_generation_change)
        self._initialised = True

    def _on_generation_change(self, generation):
        with self._lock:
            if self._modal_depth > 0 or self._closed:
                self._render_pending = True
                return
            self._refresh_in_place()

    def _enter_modal(self):
        with self._lock:
            self._modal_depth += 1

    def _exit_modal(self):
        # Never called with the lock held across a modal open() -- callers
        # take it only to bump/drop _modal_depth, not while doModal() blocks.
        with self._lock:
            self._modal_depth -= 1
            if self._modal_depth <= 0 and self._render_pending:
                self._render_pending = False
                self._refresh_in_place()

    def _refresh_in_place(self):
        group_item = self._selected_group_item()
        group_kind = group_item.getProperty('kind') if group_item is not None else 'all'
        group_id = group_item.getProperty('group_id') if group_item is not None else ''

        channel_item = self.getControl(CHANNELS_LIST_ID).getSelectedItem()
        channel_key = channel_item.getProperty('channel_key') if channel_item is not None else None
        provider_id = channel_item.getProperty('provider_id') if channel_item is not None else None
        channel_position = self.getControl(CHANNELS_LIST_ID).getSelectedPosition()

        focus_id = self.getFocusId()

        self._render_groups()
        groups_control = self.getControl(GROUPS_LIST_ID)
        new_group_position = 0
        group_kept = False
        for index in range(groups_control.size()):
            item = groups_control.getListItem(index)
            if item.getProperty('kind') == group_kind and (
                group_kind != 'group' or item.getProperty('group_id') == group_id
            ):
                new_group_position = index
                group_kept = True
                break
        groups_control.selectItem(new_group_position)
        self._last_group_position = new_group_position

        self._render_channels()
        channels_control = self.getControl(CHANNELS_LIST_ID)
        count = channels_control.size()
        if count:
            new_channel_position = None
            if group_kept and channel_key is not None:
                for index in range(count):
                    item = channels_control.getListItem(index)
                    if item.getProperty('channel_key') == channel_key and \
                            item.getProperty('provider_id') == provider_id:
                        new_channel_position = index
                        break
            if new_channel_position is None:
                new_channel_position = min(channel_position, count - 1) if group_kept else 0
            channels_control.selectItem(new_channel_position)

        self.setFocusId(focus_id)

    def onAction(self, action):
        action_id = action.getId()
        if self._move_key is not None:
            if action_id in (xbmcgui.ACTION_NAV_BACK, xbmcgui.ACTION_PREVIOUS_MENU):
                self._cancel_move()
                return
            if action_id == xbmcgui.ACTION_MOVE_UP:
                self._shift_move(-1)
                return
            if action_id == xbmcgui.ACTION_MOVE_DOWN:
                self._shift_move(1)
                return
        if action_id in (xbmcgui.ACTION_NAV_BACK, xbmcgui.ACTION_PREVIOUS_MENU):
            self.close()
            return
        if self.getFocusId() == GROUPS_LIST_ID:
            position = self.getControl(GROUPS_LIST_ID).getSelectedPosition()
            if position != self._last_group_position:
                self._last_group_position = position
                self._schedule_render_channels()
        elif action_id == xbmcgui.ACTION_CONTEXT_MENU and self.getFocusId() == CHANNELS_LIST_ID:
            self._context_menu()
        elif action_id == _ACTION_SHOW_INFO and self.getFocusId() == CHANNELS_LIST_ID \
                and self._move_key is None:
            self._open_guide()

    def onClick(self, control_id):
        if control_id == TOGGLE_HIDDEN_ID:
            self._show_hidden = not self._show_hidden
            self.setProperty('show_hidden', '1' if self._show_hidden else '0')
            self._render_channels()
        elif control_id == GROUPS_LIST_ID:
            self._cancel_pending_render()
            self._last_group_position = self.getControl(GROUPS_LIST_ID).getSelectedPosition()
            self._render_channels()
            self.setFocusId(CHANNELS_LIST_ID)
        elif control_id == CHANNELS_LIST_ID:
            if self._move_key is not None:
                self._drop_move()
            else:
                self._open_playback()

    def _open_playback(self):
        item = self.getControl(CHANNELS_LIST_ID).getSelectedItem()
        if item is None:
            return
        provider_id = int(item.getProperty('provider_id'))
        channel_key = item.getProperty('channel_key')
        snapshot = playback.load_snapshot(self.conn, provider_id, channel_key)
        if snapshot is not None:
            self._enter_modal()
            try:
                PlaybackWindow.open(conn=self.conn, snapshot=snapshot)
            finally:
                self._exit_modal()

    def _open_guide(self):
        group_item = self._selected_group_item()
        kind = group_item.getProperty('kind') if group_item is not None else 'all'
        group_id = int(group_item.getProperty('group_id')) if kind == 'group' else None
        favourites = kind == 'favourites'

        channel_item = self.getControl(CHANNELS_LIST_ID).getSelectedItem()
        channel_id = channel_item.getProperty('channel_id') if channel_item is not None else ''
        focus_channel_id = int(channel_id) if channel_id else None

        self._enter_modal()
        try:
            self.guide_cls.open(
                conn=self.conn, group_id=group_id, favourites=favourites,
                focus_channel_id=focus_channel_id,
            )
        finally:
            self._exit_modal()

    def _context_menu(self):
        item = self.getControl(CHANNELS_LIST_ID).getSelectedItem()
        if item is None:
            return
        provider_id = int(item.getProperty('provider_id'))
        channel_key = item.getProperty('channel_key')
        hidden = item.getProperty('hidden') == '1'
        favourite = item.getProperty('favourite') == '1'
        group_item = self._selected_group_item()
        in_favourites = group_item is not None and group_item.getProperty('kind') == 'favourites'

        addon = xbmcaddon.Addon()
        options = [addon.getLocalizedString(_STR_RENUMBER)]
        actions = ['renumber']
        options.append(addon.getLocalizedString(_STR_UNHIDE if hidden else _STR_HIDE))
        actions.append('unhide' if hidden else 'hide')
        options.append(addon.getLocalizedString(_STR_REMOVE_FAVOURITE if favourite else _STR_ADD_FAVOURITE))
        actions.append('unfavourite' if favourite else 'favourite')
        if in_favourites:
            options.append(addon.getLocalizedString(_STR_MOVE))
            actions.append('move')
        options.append(addon.getLocalizedString(_STR_RESET))
        actions.append('reset')

        self._enter_modal()
        try:
            choice = xbmcgui.Dialog().contextmenu(options)
        finally:
            self._exit_modal()
        if choice is None or choice < 0:
            return
        action = actions[choice]
        if action == 'renumber':
            self._renumber(provider_id, channel_key, item.getProperty('number'))
        elif action in ('hide', 'unhide'):
            channels.set_hidden(self.conn, provider_id, channel_key, action == 'hide')
            self._refresh_after_edit(provider_id, channel_key)
        elif action in ('favourite', 'unfavourite'):
            channels.set_favourite(self.conn, provider_id, channel_key, action == 'favourite')
            self._refresh_after_edit(provider_id, channel_key)
        elif action == 'move':
            self._start_move(provider_id, channel_key)
        elif action == 'reset':
            channels.reset(self.conn, provider_id, channel_key)
            self._refresh_after_edit(provider_id, channel_key)

    def _renumber(self, provider_id, channel_key, current_number):
        addon = xbmcaddon.Addon()
        self._enter_modal()
        try:
            value = xbmcgui.Dialog().numeric(
                0, addon.getLocalizedString(_STR_RENUMBER_HEADING), str(current_number)
            )
        finally:
            self._exit_modal()
        if value:
            channels.set_number(self.conn, provider_id, channel_key, int(value))
        self._refresh_after_edit(provider_id, channel_key)

    def _refresh_after_edit(self, provider_id, channel_key):
        channels_control = self.getControl(CHANNELS_LIST_ID)
        position = channels_control.getSelectedPosition()
        self._render_channels()
        count = channels_control.size()
        if count:
            new_position = None
            for index in range(count):
                row_item = channels_control.getListItem(index)
                if row_item.getProperty('channel_key') == channel_key and \
                        row_item.getProperty('provider_id') == str(provider_id):
                    new_position = index
                    break
            if new_position is None:
                new_position = min(position, count - 1)
            channels_control.selectItem(new_position)
        self.setFocusId(CHANNELS_LIST_ID)

    def _start_move(self, provider_id, channel_key):
        self._cancel_pending_render()
        self._enter_modal()
        rows = channels.list_channels(self.conn, favourites=True, show_hidden=self._show_hidden)
        order = [(row['provider_id'], row['channel_key']) for row in rows]
        self._move_order = order
        self._move_original_order = list(order)
        self._move_key = (provider_id, channel_key)

    def _shift_move(self, delta):
        index = self._move_order.index(self._move_key)
        new_index = index + delta
        if new_index < 0 or new_index >= len(self._move_order):
            return
        self._move_order[index], self._move_order[new_index] = \
            self._move_order[new_index], self._move_order[index]
        self._render_channels(order=self._move_order)
        self.setFocusId(CHANNELS_LIST_ID)
        self.getControl(CHANNELS_LIST_ID).selectItem(new_index)

    def _drop_move(self):
        moved_key = self._move_key
        order = self._move_order
        channels.set_favourite_order(self.conn, order)
        self._move_key = None
        self._move_order = None
        self._move_original_order = None
        self._exit_modal()
        self._render_channels()
        self.getControl(CHANNELS_LIST_ID).selectItem(order.index(moved_key))
        self.setFocusId(CHANNELS_LIST_ID)

    def _cancel_move(self):
        moved_key = self._move_key
        order = self._move_original_order
        self._move_key = None
        self._move_order = None
        self._move_original_order = None
        self._exit_modal()
        self._render_channels()
        self.getControl(CHANNELS_LIST_ID).selectItem(order.index(moved_key))
        self.setFocusId(CHANNELS_LIST_ID)

    def close(self):
        with self._lock:
            self._closed = True
            self._cancel_pending_render()
            if getattr(self, '_watcher', None) is not None:
                self._watcher.stop()
        super(ChannelListWindow, self).close()

    def _cancel_pending_render(self):
        if self._render_timer is not None:
            self._render_timer.cancel()
            self._render_timer = None

    def _schedule_render_channels(self):
        self._cancel_pending_render()
        self._render_timer = threading.Timer(
            _GROUP_SELECTION_DEBOUNCE_SECONDS, self._render_channels_if_open
        )
        self._render_timer.daemon = True
        self._render_timer.start()

    def _render_channels_if_open(self):
        with self._lock:
            if not self._closed and self._move_key is None:
                self._render_channels()

    def _render_groups(self):
        addon = xbmcaddon.Addon()
        control = self.getControl(GROUPS_LIST_ID)
        control.reset()

        items = []

        all_item = xbmcgui.ListItem(label=addon.getLocalizedString(_STR_ALL_CHANNELS))
        all_item.setProperty('kind', 'all')
        items.append(all_item)

        favourites_item = xbmcgui.ListItem(label=addon.getLocalizedString(_STR_FAVOURITES))
        favourites_item.setProperty('kind', 'favourites')
        items.append(favourites_item)

        for group in channels.list_groups(self.conn):
            item = xbmcgui.ListItem(label=group['name'])
            item.setProperty('kind', 'group')
            item.setProperty('group_id', str(group['id']))
            items.append(item)

        control.addItems(items)

    def _selected_group_item(self):
        return self.getControl(GROUPS_LIST_ID).getSelectedItem()

    def _render_channels(self, order=None):
        with self._lock:
            item = self._selected_group_item()
            kind = item.getProperty('kind') if item is not None else 'all'
            group_id = None
            favourites = False
            if kind == 'favourites':
                favourites = True
            elif kind == 'group':
                group_id = int(item.getProperty('group_id'))

            control = self.getControl(CHANNELS_LIST_ID)
            control.reset()
            items = []
            rows = channels.list_channels(
                self.conn, group_id=group_id, favourites=favourites,
                show_hidden=self._show_hidden,
            )
            if order is not None:
                by_key = {(row['provider_id'], row['channel_key']): row for row in rows}
                rows = [by_key[key] for key in order if key in by_key]
            now_titles = channels.now_titles(
                self.conn, [row['id'] for row in rows], guide.format_iso(self.now_fn())
            )
            for row in rows:
                list_item = xbmcgui.ListItem(label=row['name'])
                list_item.setLabel2(str(row['number']))
                list_item.setProperty('number', str(row['number']))
                list_item.setProperty('hidden', '1' if row['hidden'] else '0')
                list_item.setProperty('favourite', '1' if row['favourite'] else '0')
                list_item.setProperty('channel_key', row['channel_key'])
                list_item.setProperty('provider_id', str(row['provider_id']))
                list_item.setProperty('channel_id', str(row['id']))
                list_item.setProperty('now_title', now_titles.get(row['id']) or '')
                if row['logo_url']:
                    list_item.setArt({'icon': row['logo_url']})
                items.append(list_item)
            control.addItems(items)
