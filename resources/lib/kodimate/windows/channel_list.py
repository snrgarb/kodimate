# -*- coding: utf-8 -*-
"""ChannelListWindow: Groups pane and Channels pane (issue #19, browsing only)."""
import xbmcaddon
import xbmcgui

from .. import channels
from .base import BaseWindow

TOGGLE_HIDDEN_ID = 300
GROUPS_LIST_ID = 200
CHANNELS_LIST_ID = 201

_STR_ALL_CHANNELS = 32038
_STR_FAVOURITES = 32039


class ChannelListWindow(BaseWindow):
    xmlFile = 'script-kodimate-channel-list.xml'

    def onInit(self):
        self._show_hidden = False
        self._last_group_position = 0
        self.setProperty('show_hidden', '0')
        self._render_groups()
        self._render_channels()

    def onAction(self, action):
        action_id = action.getId()
        if action_id in (xbmcgui.ACTION_NAV_BACK, xbmcgui.ACTION_PREVIOUS_MENU):
            self.close()
            return
        if self.getFocusId() == GROUPS_LIST_ID:
            position = self.getControl(GROUPS_LIST_ID).getSelectedPosition()
            if position != self._last_group_position:
                self._last_group_position = position
                self._render_channels()

    def onClick(self, control_id):
        if control_id == TOGGLE_HIDDEN_ID:
            self._show_hidden = not self._show_hidden
            self.setProperty('show_hidden', '1' if self._show_hidden else '0')
            self._render_channels()
        elif control_id == GROUPS_LIST_ID:
            self._last_group_position = self.getControl(GROUPS_LIST_ID).getSelectedPosition()
            self._render_channels()
            self.setFocusId(CHANNELS_LIST_ID)

    def _render_groups(self):
        addon = xbmcaddon.Addon()
        control = self.getControl(GROUPS_LIST_ID)
        control.reset()

        all_item = xbmcgui.ListItem(label=addon.getLocalizedString(_STR_ALL_CHANNELS))
        all_item.setProperty('kind', 'all')
        control.addItem(all_item)

        favourites_item = xbmcgui.ListItem(label=addon.getLocalizedString(_STR_FAVOURITES))
        favourites_item.setProperty('kind', 'favourites')
        control.addItem(favourites_item)

        for group in channels.list_groups(self.conn):
            item = xbmcgui.ListItem(label=group['name'])
            item.setProperty('kind', 'group')
            item.setProperty('group_id', str(group['id']))
            control.addItem(item)

    def _selected_group_item(self):
        return self.getControl(GROUPS_LIST_ID).getSelectedItem()

    def _render_channels(self):
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
        for row in channels.list_channels(
            self.conn, group_id=group_id, favourites=favourites,
            show_hidden=self._show_hidden,
        ):
            list_item = xbmcgui.ListItem(label=row['name'])
            list_item.setLabel2(str(row['number']))
            list_item.setProperty('number', str(row['number']))
            list_item.setProperty('hidden', '1' if row['hidden'] else '0')
            list_item.setProperty('channel_key', row['channel_key'])
            list_item.setProperty('provider_id', str(row['provider_id']))
            if row['logo_url']:
                list_item.setArt({'icon': row['logo_url']})
            control.addItem(list_item)
