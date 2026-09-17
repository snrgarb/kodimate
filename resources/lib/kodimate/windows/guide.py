# -*- coding: utf-8 -*-
"""GuideWindow: read-only EPG grid, channels down the side, D-pad cursor
over programme cells (issue #26). OK on a cell opens the shared Programme
info dialog and dispatches to Watch live / Start Over / Play Catch-up
playback (issue #28)."""
import calendar
from datetime import datetime, timedelta

import xbmc
import xbmcaddon
import xbmcgui

from .. import catchup, channels, guide, log, osd, playback
from .base import BaseWindow
from .playback import PlaybackWindow
from .programme_info import ProgrammeInfoDialog

CHANNEL_LIST_ID = 500

CATCHUP_GLYPH = u'« '

_STR_NO_INFO = 32083

_LEFT_COL_WIDTH = 300
_HEADER_HEIGHT = 60
_ROW_HEIGHT = 98
_GRID_WIDTH = 1920 - _LEFT_COL_WIDTH
_POOL_COLS = 28  # real EPG data can pack ~24 short programmes into a 3h window

_HEADER_SLOTS = 6  # 3 hours in 30-minute slots
_SLOT_MINUTES = 30

_NOW_LINE_RELPATH = 'resources/skins/Main/media/white.png'

_TEXT_COLOR = 'FFCCCCCC'
_CURSOR_TEXT_COLOR = 'FFFFFFFF'
_PAST_TEXT_COLOR = 'FF808080'

_DESC_TEXT_COLOR = 'FF8A8A8A'
_DESC_CURSOR_TEXT_COLOR = 'FFE0E0E0'
_DESC_PAST_TEXT_COLOR = 'FF606060'

_TITLE_HEIGHT = 40

# Real Kodi's xbmcgui module does not export these action-id constants (only
# xbmcgui.ACTION_MOVE_LEFT/RIGHT/UP/DOWN, ACTION_NAV_BACK, ACTION_PREVIOUS_MENU
# and a handful of others genuinely exist there); defined here directly from
# Kodi's ActionIDs.h numeric values instead.
_ACTION_PAGE_UP = 5
_ACTION_PAGE_DOWN = 6
_ACTION_NEXT_ITEM = 14
_ACTION_PREV_ITEM = 15
_ACTION_REMOTE_0 = 58


def _colored(title, color):
    return '[COLOR %s]%s[/COLOR]' % (color, title)


class GuideWindow(BaseWindow):
    xmlFile = 'script-kodimate-guide.xml'
    _tz = None  # override in tests/subclasses to fix the local zone
    dialog_cls = ProgrammeInfoDialog
    playback_cls = PlaybackWindow

    def onInit(self):
        addon = xbmcaddon.Addon()
        addon_path = addon.getAddonInfo('path')
        self._no_info_title = addon.getLocalizedString(_STR_NO_INFO)
        self._tex_cell = _abs_path(addon_path, _NOW_LINE_RELPATH)

        self._channel_rows = channels.list_channels(self.conn)
        self._top_row = 0
        self._viewport_start = guide.round_down_30_local(datetime.utcnow(), self._tz)
        self._cursor_time = self._viewport_start
        self._row_cells = []
        self._last_selected = 0

        self._populate_channel_list()
        self._build_pool()
        self._load_programmes()
        # Created last (after the pool) so draw order -- which follows
        # control creation order for Python-created controls -- puts it
        # above every cell, including the cursor cell.
        self._create_now_line()
        self._relayout()
        self.setFocusId(CHANNEL_LIST_ID)

    def onAction(self, action):
        action_id = action.getId()
        if action_id in (xbmcgui.ACTION_NAV_BACK, xbmcgui.ACTION_PREVIOUS_MENU):
            self.close()
            return
        if action_id == xbmcgui.ACTION_MOVE_LEFT:
            self._move_cursor_horizontal(-1)
            return
        if action_id == xbmcgui.ACTION_MOVE_RIGHT:
            self._move_cursor_horizontal(1)
            return
        if action_id in (xbmcgui.ACTION_MOVE_UP, xbmcgui.ACTION_MOVE_DOWN):
            self._handle_vertical_move()
            return
        if action_id in (_ACTION_PAGE_UP, _ACTION_PAGE_DOWN):
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

    def onClick(self, control_id):
        if control_id != CHANNEL_LIST_ID:
            return
        focused_row = self._focused_row_index()
        cell = self._find_cell(focused_row, self._cursor_time)
        if cell is None or cell.get('filler'):
            return
        channel_index = self._top_row + focused_row
        if not (0 <= channel_index < len(self._channel_rows)):
            return
        channel_row = self._channel_rows[channel_index]
        window_days = self._window_days_for_channel(channel_index)
        now = datetime.utcnow()
        state = catchup.cell_state(cell['start'], cell['end'], window_days, now)
        dialog = self.dialog_cls.open(
            title=cell['title'],
            times=osd.format_times(cell['start'], cell['end'], self._tz),
            description=cell.get('description') or '',
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
                            'start': _epoch(cell['start']),
                            'end': _epoch(cell['end']),
                            'now': _epoch(now),
                            'catchup_id': self._catchup_id_for_cell(channel_index, cell),
                            'title': cell['title'],
                            'start_dt': cell['start'],
                            'end_dt': cell['end'],
                        },
                    )
        self._relayout()

    def _window_days_for_channel(self, channel_index):
        if 0 <= channel_index < len(self._channel_rows):
            return catchup.effective_window_days(
                self._channel_rows[channel_index].get('catchup_days'), None
            )
        return None

    def _catchup_id_for_cell(self, channel_index, cell):
        for programme in self._channel_programmes(channel_index):
            if programme['start'] == cell['start'] and programme['end'] == cell['end']:
                return programme.get('catchup_id')
        return None

    # -- setup -----------------------------------------------------------

    def _populate_channel_list(self):
        control = self.getControl(CHANNEL_LIST_ID)
        control.reset()
        items = []
        for row in self._channel_rows:
            item = xbmcgui.ListItem(label=row['name'])
            item.setProperty('number', str(row['number']))
            items.append(item)
        control.addItems(items)
        if items:
            control.selectItem(0)
        self._last_selected = control.getSelectedPosition()

    def _build_pool(self):
        self._pool = []
        added = []
        for _row in range(guide.VISIBLE_ROWS):
            row_pool = []
            for _col in range(_POOL_COLS):
                image = xbmcgui.ControlImage(0, 0, 1, _ROW_HEIGHT - 2, self._tex_cell)
                image.setColorDiffuse('FF202020')
                label = xbmcgui.ControlLabel(0, 0, 1, _TITLE_HEIGHT, '')
                desc_label = xbmcgui.ControlLabel(0, 0, 1, _ROW_HEIGHT - _TITLE_HEIGHT, '', font='font12')
                added.append(image)
                added.append(label)
                added.append(desc_label)
                row_pool.append((image, label, desc_label))
            self._pool.append(row_pool)
        self.addControls(added)
        for row_pool in self._pool:
            for image, label, desc_label in row_pool:
                image.setVisible(False)
                label.setVisible(False)
                desc_label.setVisible(False)

    def _create_now_line(self):
        # Created last so draw order (which follows control creation
        # order for Python-created controls) puts it above every cell.
        addon_path = xbmcaddon.Addon().getAddonInfo('path')
        self.now_line = xbmcgui.ControlImage(
            0, _HEADER_HEIGHT, 2, guide.VISIBLE_ROWS * _ROW_HEIGHT,
            _abs_path(addon_path, _NOW_LINE_RELPATH))
        self.addControl(self.now_line)
        self.now_line.setColorDiffuse('FFFF3333')
        self._update_now_line()

    def _update_now_line(self):
        now = datetime.utcnow()
        minutes_from_view = (now - self._viewport_start).total_seconds() / 60.0
        px_per_min = _GRID_WIDTH / float(guide.VISIBLE_HOURS * 60)
        visible = 0 <= minutes_from_view <= guide.VISIBLE_HOURS * 60
        self.now_line.setVisible(visible)
        if visible:
            x = int(_LEFT_COL_WIDTH + minutes_from_view * px_per_min)
            self.now_line.setPosition(x, _HEADER_HEIGHT)

    def _update_header(self):
        for i in range(_HEADER_SLOTS):
            t = self._viewport_start + timedelta(minutes=i * _SLOT_MINUTES)
            local_t = guide.utc_to_local(t, self._tz)
            self.setProperty('guide_header%d' % i, local_t.strftime('%H:%M'))

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
        for row_pool in self._pool:
            for image, label, desc_label in row_pool:
                image.setVisible(False)
                label.setVisible(False)
                desc_label.setVisible(False)

        selected = self.getControl(CHANNEL_LIST_ID).getSelectedPosition()
        self._top_row = guide.compute_top_row(self._top_row, selected)
        focused_row = selected - self._top_row
        now = datetime.utcnow()

        self._update_header()
        self._row_cells = []
        to_show = []

        for row in range(guide.VISIBLE_ROWS):
            channel_index = self._top_row + row
            cells = []
            if channel_index < len(self._channel_rows):
                programmes = self._channel_programmes(channel_index)
                layout_cells = guide.cell_layout(
                    programmes, self._viewport_start, _GRID_WIDTH, self._no_info_title
                )
                window_days = self._window_days_for_channel(channel_index)
                y = _HEADER_HEIGHT + row * _ROW_HEIGHT
                row_pool = self._pool[row]
                cursor_cell = guide.resolve_cursor(layout_cells, self._cursor_time) \
                    if row == focused_row else None
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
                    self._set_cell((image, label, desc_label), cell, y, is_cursor, state)
                    to_show.append((image, label, desc_label))
                    cells.append(dict(cell, pool_index=col))
            self._row_cells.append(cells)

        for image, label, desc_label in to_show:
            image.setVisible(True)
            label.setVisible(True)
            desc_label.setVisible(True)
        self._update_now_line()

    def _state_for_cell(self, cell, window_days, now):
        if cell['filler']:
            return 'filler'
        return catchup.cell_state(cell['start'], cell['end'], window_days, now)

    def _cell_title(self, cell, state):
        if state == 'past_playable':
            return CATCHUP_GLYPH + cell['title']
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
        image.setPosition(cell['x'] + _LEFT_COL_WIDTH, y)
        image.setWidth(max(1, cell['width'] - 2))
        image.setHeight(_ROW_HEIGHT - 2)
        image.setColorDiffuse('FF3A6EA5' if is_cursor else 'FF202020')
        label_x = cell['x'] + _LEFT_COL_WIDTH + 8
        label_width = max(1, cell['width'] - 16)
        label.setPosition(label_x, y)
        label.setWidth(label_width)
        label.setHeight(_TITLE_HEIGHT)
        label.setLabel(_colored(self._cell_title(cell, state), text_color))
        desc_label.setPosition(label_x, y + _TITLE_HEIGHT)
        desc_label.setWidth(label_width)
        desc_label.setHeight(_ROW_HEIGHT - _TITLE_HEIGHT)
        desc_label.setLabel(_colored(cell['description'], desc_color) if cell['description'] else '')

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
        old_cell = self._find_cell(row, old_time)
        new_cell = self._find_cell(row, new_time)
        if old_cell is None or new_cell is None:
            return False
        now = datetime.utcnow()
        window_days = self._window_days_for_channel(self._top_row + row)
        old_state = self._state_for_cell(old_cell, window_days, now)
        new_state = self._state_for_cell(new_cell, window_days, now)
        old_pool = self._pool[row][old_cell['pool_index']]
        old_pool[0].setColorDiffuse('FF202020')
        old_pool[1].setLabel(_colored(
            self._cell_title(old_cell, old_state), self._label_color_for(old_cell, old_state, False)
        ))
        old_desc_color = self._desc_color_for(old_cell, old_state, False)
        old_pool[2].setLabel(_colored(old_cell['description'], old_desc_color) if old_cell['description'] else '')
        new_pool = self._pool[row][new_cell['pool_index']]
        new_pool[0].setColorDiffuse('FF3A6EA5')
        new_pool[1].setLabel(_colored(self._cell_title(new_cell, new_state), _CURSOR_TEXT_COLOR))
        new_pool[2].setLabel(
            _colored(new_cell['description'], _DESC_CURSOR_TEXT_COLOR) if new_cell['description'] else ''
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
        new_top = guide.compute_top_row(self._top_row, selected)
        if new_top != prev_top:
            self._relayout()
            self._last_selected = selected
            return

        old_row = prev_selected - prev_top
        new_row = selected - prev_top
        if not self._swap_cursor_row(old_row, new_row):
            self._relayout()
        self._last_selected = selected

    def _swap_cursor_row(self, old_row, new_row):
        # Rule B: the travel axis (self._cursor_time) is never changed by
        # Up/Down; only the target row's cell is resolved against it.
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
            old_pool[0].setColorDiffuse('FF202020')
            old_pool[1].setLabel(_colored(
                self._cell_title(old_cell, old_state), self._label_color_for(old_cell, old_state, False)
            ))
            old_desc_color = self._desc_color_for(old_cell, old_state, False)
            old_pool[2].setLabel(
                _colored(old_cell['description'], old_desc_color) if old_cell['description'] else ''
            )
        new_pool = self._pool[new_row][new_cell['pool_index']]
        new_pool[0].setColorDiffuse('FF3A6EA5')
        new_pool[1].setLabel(_colored(self._cell_title(new_cell, new_state), _CURSOR_TEXT_COLOR))
        new_pool[2].setLabel(
            _colored(new_cell['description'], _DESC_CURSOR_TEXT_COLOR) if new_cell['description'] else ''
        )
        return True


def _abs_path(addon_path, relpath):
    # Python-created controls need absolute texture paths -- bare skin
    # texture names stop resolving for them after any layout mutation.
    return addon_path.rstrip('/') + '/' + relpath


def _epoch(dt):
    return calendar.timegm(dt.utctimetuple())
