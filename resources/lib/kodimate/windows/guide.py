# -*- coding: utf-8 -*-
"""GuideWindow: read-only EPG grid, channels down the side, D-pad cursor
over programme cells (issue #26). OK on a cell opens the shared Programme
info dialog and dispatches to Watch live / Start Over / Play Catch-up
playback (issue #28)."""
import calendar
import threading
from datetime import datetime, timedelta

import xbmc
import xbmcaddon
import xbmcgui

from .. import autoplay, catchup, channels, guide, ipc, log, osd, playback, providers
from .base import BaseWindow
from .catchup_browser import CatchupBrowserWindow
from .playback import PlaybackWindow
from .programme_info import ProgrammeInfoDialog
from .rail import RAIL_LIVETV_ID, RAIL_CATCHUP_ID, RAIL_SETTINGS_ID  # noqa: F401 (re-exported)

CHANNEL_LIST_ID = 500
PANEL_LIST_ID = 520
PANEL_HEADER_ID = 521
PANEL_CHANNELS_ID = 522

_STR_NO_INFO = 32083
_STR_ALL_CHANNELS = 32038
_STR_FAVOURITES = 32039
_STR_GROUPS = 32125
_STR_REMAINING = 32129
_STR_TODAY = 32130

_RAIL_WIDTH = 150
_PANEL_WIDTH = 385
_LEFT_COL_WIDTH = 150
_GRID_X = _RAIL_WIDTH + _PANEL_WIDTH + _LEFT_COL_WIDTH
_STRIP_HEIGHT = 220
_HEADER_HEIGHT = 60
_HINT_BAR_HEIGHT = 60
_HINT_SLOT_COUNT = 5
_ROW_HEIGHT = 66
_GRID_WIDTH = 1920 - _GRID_X
_POOL_COLS = 28  # real EPG data can pack ~24 short programmes into a 3h window

# Visible row count derives from the height left over below the strip, the
# sticky time header and the remote-hint bar, replacing guide.VISIBLE_ROWS's
# fixed constant.
_VISIBLE_ROWS = guide.visible_rows(1080 - _STRIP_HEIGHT - _HEADER_HEIGHT - _HINT_BAR_HEIGHT, _ROW_HEIGHT)

_STRIP_PROGRESS_FILL_ID = 531
_STRIP_PROGRESS_WIDTH = 300  # matches the skin's row-3 progress track width

_HEADER_SLOTS = 6  # 3 hours in 30-minute slots
_SLOT_MINUTES = 30

_NOW_BADGE_IMAGE_ID = 516
_NOW_BADGE_LABEL_ID = 517
_NOW_BADGE_WIDTH = 80
_NOW_BADGE_Y = _STRIP_HEIGHT

_NOW_LINE_RELPATH = 'resources/skins/Main/media/white.png'

_CELL_COLOR = 'FF2A2A2A'
_CURSOR_CELL_COLOR = 'FF3A6EA5'
_PROGRESS_COLOR = 'FF3A6EA5'
_PROGRESS_HEIGHT = 4

_TEXT_COLOR = 'FFCCCCCC'
_CURSOR_TEXT_COLOR = 'FFFFFFFF'
_PAST_TEXT_COLOR = 'FF808080'

_DESC_TEXT_COLOR = 'FF8A8A8A'
_DESC_CURSOR_TEXT_COLOR = 'FFE0E0E0'
_DESC_PAST_TEXT_COLOR = 'FF606060'

_TITLE_HEIGHT = 34

# Real Kodi's xbmcgui module does not export these action-id constants (only
# xbmcgui.ACTION_MOVE_LEFT/RIGHT/UP/DOWN, ACTION_NAV_BACK, ACTION_PREVIOUS_MENU
# and a handful of others genuinely exist there); defined here directly from
# Kodi's ActionIDs.h numeric values instead.
_ACTION_PAGE_UP = 5
_ACTION_PAGE_DOWN = 6
_ACTION_NEXT_ITEM = 14
_ACTION_PREV_ITEM = 15
_ACTION_REMOTE_0 = 58
_ACTION_SHOW_INFO = 11

# Kodi's default keymaps deliver a held OK as ACTION_CONTEXT_MENU (there is
# no dedicated long-press-select action id); the context-menu action from
# #48 remains the fallback on remotes without long press.
_ACTION_LONG_PRESS_OK = xbmcgui.ACTION_CONTEXT_MENU


def _colored(title, color):
    return '[COLOR %s]%s[/COLOR]' % (color, title)


class GuideWindow(BaseWindow):
    xmlFile = 'script-kodimate-guide.xml'
    _tz = None  # override in tests/subclasses to fix the local zone
    dialog_cls = ProgrammeInfoDialog
    playback_cls = PlaybackWindow
    catchup_cls = CatchupBrowserWindow
    group_id = None
    favourites = False
    focus_channel_id = None
    provider_id = None

    def onInit(self):
        if getattr(self, '_initialised', False):
            with self._lock:
                if self._render_pending:
                    self._render_pending = False
                    self._refresh_in_place()
                else:
                    self._relayout()
            self._apply_zone()
            return

        addon = xbmcaddon.Addon()
        addon_path = addon.getAddonInfo('path')
        self._no_info_title = addon.getLocalizedString(_STR_NO_INFO)
        self._tex_cell = _abs_path(addon_path, _NOW_LINE_RELPATH)

        self._group_id = self.group_id
        self._favourites = self.favourites
        self._provider_id = self.provider_id
        self._zone = 'column'
        self._panel_mode = 'channels'
        self._collapsed = set()
        self._panel_rows = []
        self._rail_focus_id = RAIL_LIVETV_ID
        self.setProperty('panel_mode', 'channels')
        self.setProperty('panel_heading', addon.getLocalizedString(_STR_GROUPS))

        self._channel_rows = self._query_rows()
        self._top_row = 0
        self._viewport_start = guide.round_down_30_local(datetime.utcnow(), self._tz)
        self._cursor_time = self._viewport_start
        self._row_cells = []
        self._last_selected = 0

        self._modal_depth = 0
        self._render_pending = False
        self._closed = False
        self._watcher = None
        # Guards _modal_depth/_render_pending/_closed and every render below:
        # GenerationWatcher.onNotification runs on Kodi's Monitor thread
        # while the UI thread may be inside onAction/onClick.
        self._lock = threading.RLock()

        self._populate_channel_list()
        index = guide.initial_cursor_index(self._channel_rows, self.focus_channel_id)
        if self._channel_rows:
            self.getControl(CHANNEL_LIST_ID).selectItem(index)
        self._top_row = guide.compute_top_row(0, index, visible_rows=_VISIBLE_ROWS)
        self._last_selected = index
        self._update_filter_header()
        self._render_channel_panel(keep_index=index)
        self._build_pool()
        self._load_programmes()
        # Created last (after the pool) so draw order -- which follows
        # control creation order for Python-created controls -- puts it
        # above every cell, including the cursor cell.
        self._create_now_line()
        self._relayout()
        self.setProperty('rail_selected', 'livetv')
        self._apply_zone()
        self._watcher = ipc.GenerationWatcher(self._on_generation_change)
        self._initialised = True

    def _apply_zone(self):
        if self._zone == 'rail':
            self.setFocusId(self._rail_focus_id)
        elif self._zone == 'panel':
            self.setFocusId(PANEL_CHANNELS_ID if self._panel_mode == 'channels' else PANEL_LIST_ID)
        else:
            self.setFocusId(CHANNEL_LIST_ID)
        addon = xbmcaddon.Addon()
        get_string = addon.getLocalizedString
        self.setProperty('hint_bar', guide.hint_text(self._zone, get_string, self._panel_mode))
        slots = guide.hint_slots(self._zone, get_string, self._panel_mode)
        for i in range(_HINT_SLOT_COUNT):
            slot = slots[i] if i < len(slots) else {'icon': '', 'key': '', 'verb': '', 'texture': ''}
            n = i + 1
            self.setProperty('hint%d_icon' % n, slot['icon'])
            self.setProperty('hint%d_key' % n, slot['key'])
            self.setProperty('hint%d_verb' % n, slot['verb'])
            self.setProperty('hint%d_texture' % n, slot.get('texture', ''))

    def _on_generation_change(self, generation):
        with self._lock:
            if self._modal_depth > 0 or self._closed:
                self._render_pending = True
                return
            self._refresh_in_place()

    def _enter_modal(self):
        with self._lock:
            self._modal_depth += 1
        self.setProperty('hint_bar', '')

    def _exit_modal(self):
        # Never called with the lock held across a modal open() -- callers
        # take it only to bump/drop _modal_depth, not while doModal() blocks.
        with self._lock:
            self._modal_depth -= 1
            if self._modal_depth <= 0 and self._render_pending:
                self._render_pending = False
                self._refresh_in_place()
                return True
        return False

    def _filter_still_valid(self):
        if self._group_id is not None:
            groups = channels.list_groups(self.conn)
            return any(group['id'] == self._group_id for group in groups)
        if self._provider_id is not None:
            provider_rows = providers.list_providers(self.conn)
            return any(
                provider['id'] == self._provider_id and provider.get('enabled', True)
                for provider in provider_rows
            )
        return True

    def _refresh_in_place(self):
        control = self.getControl(CHANNEL_LIST_ID)
        selected = control.getSelectedPosition()
        old_offset = selected - self._top_row
        old_row = self._channel_rows[selected] if 0 <= selected < len(self._channel_rows) else None
        old_key = (old_row['provider_id'], old_row['channel_key']) if old_row else None

        fell_back = not self._filter_still_valid()
        if fell_back:
            self._group_id = None
            self._provider_id = None
            self._favourites = False

        self._channel_rows = self._query_rows()
        self._populate_channel_list()

        if fell_back:
            new_index = 0
            self._top_row = 0
        else:
            new_index = 0
            if old_key is not None:
                for index, row in enumerate(self._channel_rows):
                    if (row['provider_id'], row['channel_key']) == old_key:
                        new_index = index
                        break
                else:
                    new_index = min(selected, len(self._channel_rows) - 1) if self._channel_rows else 0

            top_row = new_index - old_offset
            max_top = max(0, len(self._channel_rows) - _VISIBLE_ROWS)
            self._top_row = max(0, min(top_row, max_top))

        if self._channel_rows:
            control.selectItem(new_index)
        self._last_selected = new_index

        self._update_filter_header()
        self._load_programmes()
        self._relayout()
        if self._panel_mode == 'channels':
            selected_channels = self.getControl(PANEL_CHANNELS_ID).getSelectedPosition()
            self._render_channel_panel(keep_index=selected_channels)
        elif fell_back:
            self._render_panel()
        else:
            selected_panel = self.getControl(PANEL_LIST_ID).getSelectedPosition()
            self._render_panel(keep_index=selected_panel)

    def close(self):
        with self._lock:
            self._closed = True
            if getattr(self, '_watcher', None) is not None:
                self._watcher.stop()
        super(GuideWindow, self).close()

    def onAction(self, action):
        action_id = action.getId()
        if action_id in (xbmcgui.ACTION_NAV_BACK, xbmcgui.ACTION_PREVIOUS_MENU):
            self._handle_back()
            return
        if action_id == xbmcgui.ACTION_MOVE_LEFT:
            self._handle_left()
            return
        if action_id == xbmcgui.ACTION_MOVE_RIGHT:
            self._handle_right()
            return
        if action_id in (xbmcgui.ACTION_MOVE_UP, xbmcgui.ACTION_MOVE_DOWN):
            if self._zone not in ('rail', 'panel'):
                self._handle_vertical_move()
            return
        if action_id in (_ACTION_PAGE_UP, _ACTION_PAGE_DOWN):
            if self._zone not in ('rail', 'panel'):
                self._handle_vertical_move()
            return
        if action_id == _ACTION_NEXT_ITEM:
            self._skip_viewport(guide.SKIP_HOURS)
            return
        if action_id == _ACTION_PREV_ITEM:
            self._skip_viewport(-guide.SKIP_HOURS)
            return
        if action_id == _ACTION_REMOTE_0:
            self._jump_to_now()
            return
        if action_id == _ACTION_SHOW_INFO:
            self._handle_info()
            return
        if action_id == _ACTION_LONG_PRESS_OK:
            self._toggle_favourite()
            return

    def _handle_left(self):
        if self._zone == 'grid':
            self._move_cursor_horizontal(-1)
            return
        next_zone = guide.zone_transition(self._zone, 'left')
        if next_zone == self._zone:
            return
        with self._lock:
            if next_zone == 'panel':
                selected = self.getControl(CHANNEL_LIST_ID).getSelectedPosition()
                self._panel_mode = 'channels'
                self.setProperty('panel_mode', 'channels')
                self._render_channel_panel(keep_index=selected)
            self._zone = next_zone
        self._apply_zone()

    def _handle_back(self):
        if self._zone == 'panel' and self._panel_mode == 'groups':
            self._return_to_channels_mode()
            return
        target = guide.back_target(self._zone)
        if target == 'column':
            self._zone = 'column'
            self._relayout()
            self._apply_zone()
            return
        self.close()

    def _handle_right(self):
        if self._zone == 'grid':
            self._move_cursor_horizontal(1)
            return
        if self._zone == 'rail':
            self._rail_focus_id = self.getFocusId()
        if self._zone == 'panel':
            if self._panel_mode == 'channels':
                self._select_channel_from_panel()
                return
            row = self._selected_panel_row()
            if row is None:
                return
            if row['kind'] == 'provider':
                self._return_to_channels_mode()
                return
            self._apply_filter(guide.picked_filter(row))
            return
        next_zone = guide.zone_transition(self._zone, 'right')
        self._zone = next_zone
        self._apply_zone()
        if next_zone == 'grid':
            self._relayout()

    def _play_selected_channel(self):
        channel_index = self.getControl(CHANNEL_LIST_ID).getSelectedPosition()
        if not (0 <= channel_index < len(self._channel_rows)):
            return
        channel_row = self._channel_rows[channel_index]
        snapshot = playback.load_snapshot(self.conn, channel_row['provider_id'], channel_row['channel_key'])
        if snapshot is None:
            return
        self._enter_modal()
        try:
            self.playback_cls.open(conn=self.conn, snapshot=snapshot)
        finally:
            refreshed = self._exit_modal()
        if not refreshed:
            self._relayout()
        self._apply_zone()

    def _open_catchup(self):
        self._enter_modal()
        try:
            self.catchup_cls.open(conn=self.conn)
        finally:
            self._exit_modal()
        self._apply_zone()

    def _open_settings(self):
        self._enter_modal()
        try:
            xbmcaddon.Addon().openSettings()
        finally:
            refreshed = self._exit_modal()
        if not refreshed:
            self._relayout()
        self._apply_zone()

    def onClick(self, control_id):
        if control_id == RAIL_CATCHUP_ID:
            self._rail_focus_id = control_id
            self._open_catchup()
            return
        if control_id == RAIL_SETTINGS_ID:
            self._rail_focus_id = control_id
            self._open_settings()
            return
        if control_id == PANEL_HEADER_ID:
            with self._lock:
                self._panel_mode = 'groups'
                self.setProperty('panel_mode', 'groups')
                self.setProperty('panel_heading', xbmcaddon.Addon().getLocalizedString(_STR_GROUPS))
                self._render_panel()
            self._apply_zone()
            return
        if control_id == PANEL_CHANNELS_ID:
            self._select_channel_from_panel()
            return
        if control_id == PANEL_LIST_ID:
            row = self._selected_panel_row()
            if row is None:
                return
            if row['kind'] == 'provider':
                with self._lock:
                    selected = self.getControl(PANEL_LIST_ID).getSelectedPosition()
                    if row['provider_id'] in self._collapsed:
                        self._collapsed.discard(row['provider_id'])
                    else:
                        self._collapsed.add(row['provider_id'])
                    self._render_panel(keep_index=selected)
                self.setFocusId(PANEL_LIST_ID)
                return
            self._apply_filter(guide.picked_filter(row))
            return
        if control_id != CHANNEL_LIST_ID:
            return
        if self._zone == 'column':
            self._play_selected_channel()
            return
        found = self._focused_grid_cell()
        if found is None:
            return
        channel_index, cell = found
        self._open_programme_info(channel_index, cell)

    def _open_programme_info(self, channel_index, programme):
        """Open the shared Programme info dialog for `programme` (a cell or
        a plain channel-programme dict, both carrying start/end/title/
        description) and dispatch to playback per the dialog's result."""
        if not (0 <= channel_index < len(self._channel_rows)):
            return
        channel_row = self._channel_rows[channel_index]
        window_days = self._window_days_for_channel(channel_index)
        now = datetime.utcnow()
        state = catchup.cell_state(programme['start'], programme['end'], window_days, now)
        self._enter_modal()
        try:
            dialog = self.dialog_cls.open(
                title=programme['title'],
                times=osd.format_times(programme['start'], programme['end'], self._tz),
                description=programme.get('description') or '',
                actions=catchup.actions_for(state, start_over_ok=bool(window_days)),
            )
            result = dialog.result
            if result in ('watch_live', 'start_over', 'play_catchup'):
                snapshot = playback.load_snapshot(
                    self.conn, channel_row['provider_id'], channel_row['channel_key']
                )
                if snapshot is not None:
                    if result == 'watch_live':
                        self.playback_cls.open(conn=self.conn, snapshot=snapshot)
                    else:
                        self.playback_cls.open(
                            conn=self.conn, snapshot=snapshot,
                            catchup={
                                'start': _epoch(programme['start']),
                                'end': _epoch(programme['end']),
                                'now': _epoch(now),
                                'catchup_id': self._catchup_id_for_cell(channel_index, programme),
                                'title': programme['title'],
                                'start_dt': programme['start'],
                                'end_dt': programme['end'],
                            },
                        )
        finally:
            refreshed = self._exit_modal()
        if not refreshed:
            self._relayout()
        self._apply_zone()

    def _handle_info(self):
        if self._zone == 'column':
            channel_index = self.getControl(CHANNEL_LIST_ID).getSelectedPosition()
            if not (0 <= channel_index < len(self._channel_rows)):
                return
            now = datetime.utcnow()
            programme = next(
                (p for p in self._channel_programmes(channel_index) if p['start'] <= now < p['end']), None
            )
            if programme is None:
                return
            self._open_programme_info(channel_index, programme)
            return
        if self._zone == 'grid':
            found = self._focused_grid_cell()
            if found is None:
                return
            channel_index, cell = found
            self._open_programme_info(channel_index, cell)

    def _focused_grid_cell(self):
        """(channel_index, cell) for the focused grid row's cursor cell, or
        None when there is no row, no cell, or the cell is a filler."""
        focused_row = self._focused_row_index()
        cell = self._find_cell(focused_row, self._cursor_time)
        if cell is None or cell.get('filler'):
            return None
        return self._top_row + focused_row, cell

    def _toggle_favourite(self):
        if self._zone != 'column':
            return
        selected = self.getControl(CHANNEL_LIST_ID).getSelectedPosition()
        if not (0 <= selected < len(self._channel_rows)):
            return
        row = self._channel_rows[selected]
        with self._lock:
            channels.set_favourite(self.conn, row['provider_id'], row['channel_key'], not row['favourite'])
            self._channel_rows = self._query_rows()
            self._populate_channel_list()
            new_index = min(selected, len(self._channel_rows) - 1) if self._channel_rows else 0
            if self._channel_rows:
                self.getControl(CHANNEL_LIST_ID).selectItem(new_index)
            self._last_selected = new_index
            max_top = max(0, len(self._channel_rows) - _VISIBLE_ROWS)
            self._top_row = max(0, min(self._top_row, max_top))
            self._load_programmes()
            self._relayout()
        self._apply_zone()

    def _window_days_for_channel(self, channel_index):
        if 0 <= channel_index < len(self._channel_rows):
            row = self._channel_rows[channel_index]
            return catchup.effective_window_days(
                row.get('catchup_days'), None,
                url_supported=row.get('catchup_supported', True),
            )
        return None

    def _catchup_id_for_cell(self, channel_index, cell):
        for programme in self._channel_programmes(channel_index):
            if programme['start'] == cell['start'] and programme['end'] == cell['end']:
                return programme.get('catchup_id')
        return None

    # -- setup -----------------------------------------------------------

    def _query_rows(self):
        return channels.list_channels(
            self.conn, group_id=self._group_id, favourites=self._favourites,
            provider_id=self._provider_id,
        )

    def _update_filter_header(self):
        addon = xbmcaddon.Addon()
        groups = channels.list_groups(self.conn)
        provider_rows = providers.list_providers(self.conn)
        label = guide.filter_label(
            self._group_id, self._favourites, groups,
            addon.getLocalizedString(_STR_ALL_CHANNELS), addon.getLocalizedString(_STR_FAVOURITES),
            provider_id=self._provider_id, providers=provider_rows,
        )
        self.setProperty('guide_filter', label)
        if self._panel_mode != 'groups':
            self.setProperty('panel_heading', label)

    def _selected_panel_row(self):
        position = self.getControl(PANEL_LIST_ID).getSelectedPosition()
        if 0 <= position < len(self._panel_rows):
            return self._panel_rows[position]
        return None

    def _render_panel(self, keep_index=None):
        addon = xbmcaddon.Addon()
        provider_rows = providers.list_providers(self.conn)
        groups = channels.list_groups(self.conn)
        self._panel_rows = guide.panel_rows(
            provider_rows, groups, self._collapsed,
            addon.getLocalizedString(_STR_ALL_CHANNELS), addon.getLocalizedString(_STR_FAVOURITES),
        )
        selected_index = guide.panel_selected_index(
            self._panel_rows, self._provider_id, self._group_id, self._favourites,
        )
        control = self.getControl(PANEL_LIST_ID)
        control.reset()
        items = []
        for row in self._panel_rows:
            item = xbmcgui.ListItem(label=row['label'])
            item.setProperty('kind', row['kind'])
            item.setProperty('collapsed', '1' if row['collapsed'] else '0')
            item.setProperty('active', '1' if guide.picked_filter(row) == {
                'provider_id': self._provider_id, 'group_id': self._group_id, 'favourites': self._favourites,
            } else '0')
            items.append(item)
        control.addItems(items)
        if items:
            index = selected_index if keep_index is None else min(keep_index, len(items) - 1)
            control.selectItem(index)

    def _render_channel_panel(self, keep_index=None):
        playing_key = autoplay.last_channel_key_pair(self.conn)
        rows = guide.channel_panel_rows(self._channel_rows, playing_key)
        control = self.getControl(PANEL_CHANNELS_ID)
        control.reset()
        items = []
        for row in rows:
            item = xbmcgui.ListItem(label=row['name'])
            item.setProperty('number', str(row['number']))
            item.setProperty('logo', row['logo'])
            item.setProperty('playing', '1' if row['playing'] else '0')
            items.append(item)
        control.addItems(items)
        if items:
            index = 0 if keep_index is None else max(0, min(keep_index, len(items) - 1))
            control.selectItem(index)

    def _select_channel_from_panel(self):
        with self._lock:
            index = self.getControl(PANEL_CHANNELS_ID).getSelectedPosition()
            if self._channel_rows and 0 <= index < len(self._channel_rows):
                self.getControl(CHANNEL_LIST_ID).selectItem(index)
                self._zone = 'column'
                self._handle_vertical_move()
            else:
                self._zone = 'column'
        self._apply_zone()

    def _return_to_channels_mode(self):
        with self._lock:
            selected = self.getControl(CHANNEL_LIST_ID).getSelectedPosition()
            self._panel_mode = 'channels'
            self.setProperty('panel_mode', 'channels')
            self.setProperty('panel_heading', self.getProperty('guide_filter'))
            self._render_channel_panel(keep_index=selected)
        self._apply_zone()

    def _apply_filter(self, filter_state):
        with self._lock:
            self._group_id = filter_state['group_id']
            self._favourites = filter_state['favourites']
            self._provider_id = filter_state['provider_id']
            self._channel_rows = self._query_rows()
            self._populate_channel_list()
            self._top_row = 0
            self._last_selected = 0
            self._panel_mode = 'channels'
            self.setProperty('panel_mode', 'channels')
            self._update_filter_header()
            self._load_programmes()
            self._relayout()
            self._render_channel_panel(keep_index=0)
        self._apply_zone()

    def _populate_channel_list(self):
        control = self.getControl(CHANNEL_LIST_ID)
        control.reset()
        playing_key = autoplay.last_channel_key_pair(self.conn)
        items = []
        for index, row in enumerate(self._channel_rows):
            item = xbmcgui.ListItem(label=row['name'])
            item.setProperty('number', str(row['number']))
            item.setProperty('logo', row.get('logo_url') or '')
            window_days = self._window_days_for_channel(index)
            item.setProperty('catchup', '1' if window_days else '0')
            item.setProperty(
                'playing', '1' if (row['provider_id'], row['channel_key']) == playing_key else '0'
            )
            item.setProperty('favourite', '1' if row['favourite'] else '0')
            items.append(item)
        control.addItems(items)
        if items:
            control.selectItem(0)
        self._last_selected = control.getSelectedPosition()

    def _build_pool(self):
        self._pool = []
        self._progress_pool = []
        added = []
        for _row in range(_VISIBLE_ROWS):
            row_pool = []
            row_progress = []
            for _col in range(_POOL_COLS):
                image = xbmcgui.ControlImage(0, 0, 1, _ROW_HEIGHT - 2, self._tex_cell)
                image.setColorDiffuse(_CELL_COLOR)
                progress = xbmcgui.ControlImage(0, 0, 1, _PROGRESS_HEIGHT, self._tex_cell)
                progress.setColorDiffuse(_PROGRESS_COLOR)
                label = xbmcgui.ControlLabel(0, 0, 1, _TITLE_HEIGHT, '')
                desc_label = xbmcgui.ControlLabel(0, 0, 1, _ROW_HEIGHT - _TITLE_HEIGHT, '', font='font12')
                added.append(image)
                added.append(progress)
                added.append(label)
                added.append(desc_label)
                row_pool.append((image, label, desc_label))
                row_progress.append(progress)
            self._pool.append(row_pool)
            self._progress_pool.append(row_progress)
        self.addControls(added)
        for row_pool, row_progress in zip(self._pool, self._progress_pool):
            for image, label, desc_label in row_pool:
                image.setVisible(False)
                label.setVisible(False)
                desc_label.setVisible(False)
            for progress in row_progress:
                progress.setVisible(False)

    def _create_now_line(self):
        # Created last so draw order (which follows control creation
        # order for Python-created controls) puts it above every cell.
        addon_path = xbmcaddon.Addon().getAddonInfo('path')
        self.now_line = xbmcgui.ControlImage(
            0, _STRIP_HEIGHT + _HEADER_HEIGHT, 2, _VISIBLE_ROWS * _ROW_HEIGHT,
            _abs_path(addon_path, _NOW_LINE_RELPATH))
        self.addControl(self.now_line)
        self.now_line.setColorDiffuse('FFFF3333')
        self._update_now_line()

    def _update_now_line(self):
        now = datetime.utcnow()
        minutes_from_view = (now - self._viewport_start).total_seconds() / 60.0
        px_per_min = _GRID_WIDTH / float(guide.VISIBLE_HOURS * 60)
        visible = 0 <= minutes_from_view <= guide.VISIBLE_HOURS * 60
        x = int(_GRID_X + minutes_from_view * px_per_min) if visible else None
        self.now_line.setVisible(visible)
        if visible:
            self.now_line.setPosition(x, _STRIP_HEIGHT + _HEADER_HEIGHT)
            self.getControl(_NOW_BADGE_IMAGE_ID).setPosition(x - _NOW_BADGE_WIDTH // 2, _NOW_BADGE_Y)
            self.getControl(_NOW_BADGE_LABEL_ID).setPosition(x - _NOW_BADGE_WIDTH // 2, _NOW_BADGE_Y)

    def _update_header(self):
        now = datetime.utcnow()
        for i in range(_HEADER_SLOTS):
            t = self._viewport_start + timedelta(minutes=i * _SLOT_MINUTES)
            local_t = guide.utc_to_local(t, self._tz)
            self.setProperty('guide_header%d' % i, local_t.strftime('%H:%M'))
        slot = guide.header_now_slot(self._viewport_start, now)
        self.setProperty('guide_header_now', str(slot) if slot is not None else '')
        self.setProperty(
            'guide_now_label', guide.utc_to_local(now, self._tz).strftime('%H:%M') if slot is not None else ''
        )

    def _update_strip(self):
        addon = xbmcaddon.Addon()
        now = datetime.utcnow()
        selected = self.getControl(CHANNEL_LIST_ID).getSelectedPosition()
        row = self._channel_rows[selected] if 0 <= selected < len(self._channel_rows) else None

        if row is not None:
            if self._zone == 'grid':
                at_time = self._cursor_time
            elif self._viewport_start <= now < guide.viewport_end(self._viewport_start):
                at_time = now
            else:
                at_time = self._cursor_time
            programmes = self._programmes_by_channel.get(row['id'], [])
            window_days = self._window_days_for_channel(selected)
            hd = guide.is_hd_name(row['name'])
        else:
            at_time = now
            programmes = []
            window_days = None
            hd = False

        values = guide.strip_values(programmes, at_time, now, self._no_info_title, tz=self._tz)

        # LIVE and Catch-up are mutually exclusive, driven by the
        # programme's own state (not just the channel's entitlement).
        programme = next(
            (p for p in programmes if p['start'] <= at_time < p['end']), None
        )
        if programme is not None:
            state = catchup.cell_state(programme['start'], programme['end'], window_days, now)
        else:
            state = None

        channel_logo = (row.get('logo_url') or '') if row else ''
        self.setProperty('strip_channel_logo', channel_logo)
        self.setProperty('strip_image', values['icon'] or channel_logo)
        self.setProperty('strip_channel_name', row['name'] if row else '')
        self.setProperty('strip_channel_number', str(row['number']) if row else '')
        self.setProperty('strip_title', values['title'])
        self.setProperty('strip_times', values['times'])
        self.setProperty('strip_progress', str(values['progress']))
        remaining = _format_remaining(addon, values['remaining']) if values['remaining'] else ''
        self.setProperty('strip_remaining', remaining)
        self.setProperty('strip_description', values['description'])
        has_programme = values['has_programme']
        self.setProperty('strip_live', '1' if state == 'live' else '')
        self.setProperty('strip_hd', '1' if has_programme and hd else '')
        self.setProperty('strip_catchup', '1' if state == 'past_playable' else '')
        self.setProperty(
            'strip_date',
            guide.date_label(at_time, now, addon.getLocalizedString(_STR_TODAY), tz=self._tz),
        )
        self.getControl(_STRIP_PROGRESS_FILL_ID).setWidth(
            int(_STRIP_PROGRESS_WIDTH * values['progress'] / 100.0)
        )

    # -- data --------------------------------------------------------------

    def _load_programmes(self):
        # Load a wider window than the visible viewport (one extra
        # viewport-width either side) so Left/Right can find the adjacent
        # programme that triggers a viewport jump even when it starts
        # before, or ends after, what's currently on screen.
        buffer = timedelta(hours=guide.VISIBLE_HOURS)
        channel_ids = [row['id'] for row in self._channel_rows]
        window_start = guide.format_iso(self._viewport_start - buffer)
        window_end = guide.format_iso(guide.viewport_end(self._viewport_start) + buffer)
        raw = channels.list_programmes(self.conn, channel_ids, window_start, window_end)
        self._programmes_by_channel = {}
        for channel_id, rows in raw.items():
            self._programmes_by_channel[channel_id] = [
                {
                    'start': guide.parse_iso(row['start']),
                    'end': guide.parse_iso(row['end']),
                    'title': row['title'] or '',
                    'description': row['description'],
                    'catchup_id': row.get('catchup_id'),
                    'icon': row.get('icon'),
                }
                for row in rows
            ]

    def _channel_programmes(self, channel_index):
        if 0 <= channel_index < len(self._channel_rows):
            channel_id = self._channel_rows[channel_index]['id']
            return self._programmes_by_channel.get(channel_id, [])
        return []

    # -- layout ------------------------------------------------------------

    def _focused_row_index(self):
        return self.getControl(CHANNEL_LIST_ID).getSelectedPosition() - self._top_row

    def _relayout(self):
        """Hide -> update -> show: rebuild every visible row's cells from
        the pool so no frame exposes stale text. Always instant -- no
        animation is attached (the native channel list at id 500 handles
        its own scroll)."""
        with self._lock:
            for row_pool, row_progress in zip(self._pool, self._progress_pool):
                for image, label, desc_label in row_pool:
                    image.setVisible(False)
                    label.setVisible(False)
                    desc_label.setVisible(False)
                for progress in row_progress:
                    progress.setVisible(False)

            selected = self.getControl(CHANNEL_LIST_ID).getSelectedPosition()
            self._top_row = guide.compute_top_row(self._top_row, selected, visible_rows=_VISIBLE_ROWS)
            focused_row = selected - self._top_row
            now = datetime.utcnow()

            self._update_header()
            self._row_cells = []
            to_show = []
            to_show_progress = []

            for row in range(_VISIBLE_ROWS):
                channel_index = self._top_row + row
                cells = []
                if channel_index < len(self._channel_rows):
                    programmes = self._channel_programmes(channel_index)
                    layout_cells = guide.cell_layout(
                        programmes, self._viewport_start, _GRID_WIDTH, self._no_info_title, now=now,
                    )
                    window_days = self._window_days_for_channel(channel_index)
                    y = _STRIP_HEIGHT + _HEADER_HEIGHT + row * _ROW_HEIGHT
                    row_pool = self._pool[row]
                    row_progress = self._progress_pool[row]
                    cursor_cell = guide.resolve_cursor(layout_cells, self._cursor_time) \
                        if row == focused_row and self._zone == 'grid' else None
                    for col, cell in enumerate(layout_cells):
                        if col >= _POOL_COLS:
                            log.log(
                                "guide: pool exhausted for row %d (>%d programmes visible)"
                                % (row, _POOL_COLS), xbmc.LOGWARNING,
                            )
                            break
                        is_cursor = cell is cursor_cell
                        state = self._state_for_cell(cell, window_days, now)
                        image, label, desc_label = row_pool[col]
                        cell_visible = self._set_cell((image, label, desc_label), cell, y, is_cursor, state)
                        if cell_visible:
                            to_show.append((image, label, desc_label))
                        progress_image = row_progress[col]
                        if cell['progress'] is not None:
                            progress_visible = self._set_cell_progress(progress_image, cell, y)
                            if cell_visible and progress_visible:
                                to_show_progress.append(progress_image)
                        cells.append(dict(cell, pool_index=col))
                self._row_cells.append(cells)

            for image, label, desc_label in to_show:
                image.setVisible(True)
                label.setVisible(True)
                desc_label.setVisible(True)
            for progress_image in to_show_progress:
                progress_image.setVisible(True)
            self._update_now_line()
            self._update_strip()

    def _state_for_cell(self, cell, window_days, now):
        if cell['filler']:
            return 'filler'
        return catchup.cell_state(cell['start'], cell['end'], window_days, now)

    def _cell_title(self, cell, state):
        return cell['title']

    def _label_color_for(self, cell, state, is_cursor):
        if is_cursor:
            return _CURSOR_TEXT_COLOR
        if state == 'past_unplayable':
            return _PAST_TEXT_COLOR
        return _TEXT_COLOR

    def _desc_color_for(self, cell, state, is_cursor):
        if is_cursor:
            return _DESC_CURSOR_TEXT_COLOR
        if state == 'past_unplayable':
            return _DESC_PAST_TEXT_COLOR
        return _DESC_TEXT_COLOR

    def _set_cell(self, pool_entry, cell, y, is_cursor, state):
        image, label, desc_label = pool_entry
        text_color = self._label_color_for(cell, state, is_cursor)
        desc_color = self._desc_color_for(cell, state, is_cursor)
        cell_color = _CURSOR_CELL_COLOR if is_cursor else _CELL_COLOR
        x = cell['x'] + _GRID_X
        width = max(1, cell['width'] - 2)
        image.setPosition(x, y)
        image.setWidth(width)
        image.setHeight(_ROW_HEIGHT - 2)
        image.setColorDiffuse(cell_color)
        label_x = x + 8
        label_width = max(1, width - 16)
        label.setPosition(label_x, y)
        label.setWidth(label_width)
        label.setHeight(_TITLE_HEIGHT)
        label.setLabel(_colored(self._cell_title(cell, state), text_color))
        desc_label.setPosition(label_x, y + _TITLE_HEIGHT)
        desc_label.setWidth(label_width)
        desc_label.setHeight(_ROW_HEIGHT - _TITLE_HEIGHT)
        time_range = guide.cell_time_range(cell, self._tz)
        desc_label.setLabel(_colored(time_range, desc_color) if time_range else '')
        return True

    def _set_cell_progress(self, progress_image, cell, y):
        width = max(1, int((cell['width'] - 2) * cell['progress']))
        x = cell['x'] + _GRID_X
        progress_image.setPosition(x, y + _ROW_HEIGHT - 2 - _PROGRESS_HEIGHT)
        progress_image.setWidth(width)
        return True

    # -- cursor --------------------------------------------------------

    def _find_cell(self, row, t):
        if row < 0 or row >= len(self._row_cells):
            return None
        for cell in self._row_cells[row]:
            if cell['start'] <= t < cell['end']:
                return cell
        return None

    def _clamp_bounds(self, now):
        floor = guide.round_down_30_local(now - timedelta(days=guide.RETENTION_DAYS), self._tz)
        ceiling = guide.round_down_30_local(now + timedelta(days=guide.HORIZON_DAYS), self._tz) \
            - timedelta(hours=guide.VISIBLE_HOURS)
        return floor, ceiling

    def _move_cursor_horizontal(self, direction):
        focused_row = self._focused_row_index()
        row_cells = self._row_cells[focused_row] if 0 <= focused_row < len(self._row_cells) else []
        current_cell = self._find_cell(focused_row, self._cursor_time)
        if current_cell is None:
            self._relayout()
            return
        neighbour_index = row_cells.index(current_cell) + direction
        if 0 <= neighbour_index < len(row_cells):
            neighbour = row_cells[neighbour_index]
            old_time = self._cursor_time
            new_time = max(neighbour['start'], self._viewport_start)
            self._cursor_time = new_time
            if not self._swap_cursor_cell(focused_row, old_time, new_time):
                self._relayout()
            else:
                self._update_strip()
            return

        # The cursor cell touches the viewport's edge in this direction:
        # scroll by one 30-minute slot instead (a clamped no-op at the
        # floor/ceiling returns without touching data or relaying out).
        floor, ceiling = self._clamp_bounds(datetime.utcnow())
        new_viewport_start = guide.scroll_viewport(self._viewport_start, direction, floor, ceiling)
        if new_viewport_start == self._viewport_start:
            return
        old_viewport_end = guide.viewport_end(self._viewport_start)
        self._viewport_start = new_viewport_start
        self._load_programmes()
        channel_index = self._top_row + focused_row
        row_programmes = self._channel_programmes(channel_index)
        new_cells = guide.cell_layout(row_programmes, new_viewport_start, _GRID_WIDTH, self._no_info_title)
        probe = old_viewport_end if direction > 0 else new_viewport_start
        self._cursor_time = max(guide.resolve_cursor(new_cells, probe)['start'], new_viewport_start)
        self._relayout()

    def _skip_viewport(self, hours):
        offset = self._cursor_time - self._viewport_start
        now = datetime.utcnow()
        new_start = guide.clamp_viewport(self._viewport_start + timedelta(hours=hours), now, self._tz)
        self._viewport_start = new_start
        self._cursor_time = new_start + offset
        self._load_programmes()
        self._relayout()

    def _jump_to_now(self):
        now = datetime.utcnow()
        new_start = guide.round_down_30_local(now, self._tz)
        self._viewport_start = new_start
        self._cursor_time = now
        self._load_programmes()
        self._relayout()

    def _swap_cursor_cell(self, row, old_time, new_time):
        if self._zone != 'grid':
            return False
        old_cell = self._find_cell(row, old_time)
        new_cell = self._find_cell(row, new_time)
        if old_cell is None or new_cell is None:
            return False
        now = datetime.utcnow()
        window_days = self._window_days_for_channel(self._top_row + row)
        old_state = self._state_for_cell(old_cell, window_days, now)
        new_state = self._state_for_cell(new_cell, window_days, now)
        old_pool = self._pool[row][old_cell['pool_index']]
        old_pool[0].setColorDiffuse(_CELL_COLOR)
        old_pool[1].setLabel(_colored(
            self._cell_title(old_cell, old_state), self._label_color_for(old_cell, old_state, False)
        ))
        old_desc_color = self._desc_color_for(old_cell, old_state, False)
        old_time_range = guide.cell_time_range(old_cell, self._tz)
        old_pool[2].setLabel(_colored(old_time_range, old_desc_color) if old_time_range else '')
        new_pool = self._pool[row][new_cell['pool_index']]
        new_pool[0].setColorDiffuse(_CURSOR_CELL_COLOR)
        new_pool[1].setLabel(_colored(self._cell_title(new_cell, new_state), _CURSOR_TEXT_COLOR))
        new_time_range = guide.cell_time_range(new_cell, self._tz)
        new_pool[2].setLabel(
            _colored(new_time_range, _DESC_CURSOR_TEXT_COLOR) if new_time_range else ''
        )
        return True

    def _handle_vertical_move(self):
        # The native list already moved focus before Python's onAction is
        # invoked, so "the previous selection" has to be state saved from
        # the last time a move finished (self._last_selected), not
        # anything read fresh here.
        selected = self.getControl(CHANNEL_LIST_ID).getSelectedPosition()
        prev_selected = self._last_selected
        if selected == prev_selected:
            return

        prev_top = self._top_row
        new_top = guide.compute_top_row(self._top_row, selected, visible_rows=_VISIBLE_ROWS)
        if new_top != prev_top:
            self._relayout()
            self._last_selected = selected
            return

        old_row = prev_selected - prev_top
        new_row = selected - prev_top
        if not self._swap_cursor_row(old_row, new_row):
            self._relayout()
        else:
            self._update_strip()
        self._last_selected = selected

    def _swap_cursor_row(self, old_row, new_row):
        # Rule B: the travel axis (self._cursor_time) is never changed by
        # Up/Down; only the target row's cell is resolved against it.
        if self._zone != 'grid':
            return False
        new_cells = self._row_cells[new_row] if 0 <= new_row < len(self._row_cells) else []
        new_cell = guide.move_cursor_vertical(new_cells, self._cursor_time)
        if new_cell is None:
            return False
        now = datetime.utcnow()
        new_window_days = self._window_days_for_channel(self._top_row + new_row)
        new_state = self._state_for_cell(new_cell, new_window_days, now)
        old_cell = self._find_cell(old_row, self._cursor_time)
        if old_cell is not None:
            old_window_days = self._window_days_for_channel(self._top_row + old_row)
            old_state = self._state_for_cell(old_cell, old_window_days, now)
            old_pool = self._pool[old_row][old_cell['pool_index']]
            old_pool[0].setColorDiffuse(_CELL_COLOR)
            old_pool[1].setLabel(_colored(
                self._cell_title(old_cell, old_state), self._label_color_for(old_cell, old_state, False)
            ))
            old_desc_color = self._desc_color_for(old_cell, old_state, False)
            old_time_range = guide.cell_time_range(old_cell, self._tz)
            old_pool[2].setLabel(
                _colored(old_time_range, old_desc_color) if old_time_range else ''
            )
        new_pool = self._pool[new_row][new_cell['pool_index']]
        new_pool[0].setColorDiffuse(_CURSOR_CELL_COLOR)
        new_pool[1].setLabel(_colored(self._cell_title(new_cell, new_state), _CURSOR_TEXT_COLOR))
        new_time_range = guide.cell_time_range(new_cell, self._tz)
        new_pool[2].setLabel(
            _colored(new_time_range, _DESC_CURSOR_TEXT_COLOR) if new_time_range else ''
        )
        return True


def _abs_path(addon_path, relpath):
    # Python-created controls need absolute texture paths -- bare skin
    # texture names stop resolving for them after any layout mutation.
    return addon_path.rstrip('/') + '/' + relpath


def _epoch(dt):
    return calendar.timegm(dt.utctimetuple())


def _format_remaining(addon, duration):
    # Guards against a stale/untranslated strings.po (no '%s' in the
    # localized format) raising TypeError on '%' and aborting onInit.
    template = addon.getLocalizedString(_STR_REMAINING)
    if '%s' not in template:
        return duration
    return template % duration
