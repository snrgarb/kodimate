# -*- coding: utf-8 -*-
"""GuideWindow: read-only EPG grid, channels down the side, D-pad cursor
over programme cells (issue #26). OK on a cell does nothing yet."""
from datetime import datetime, timedelta

import xbmc
import xbmcaddon
import xbmcgui

from .. import channels, guide, log
from .base import BaseWindow

CHANNEL_LIST_ID = 500

_STR_NO_INFO = 32083

_LEFT_COL_WIDTH = 300
_HEADER_HEIGHT = 60
_ROW_HEIGHT = 98
_GRID_WIDTH = 1920 - _LEFT_COL_WIDTH
_POOL_COLS = 28  # real EPG data can pack ~24 short programmes into a 3h window

_HEADER_SLOTS = 6  # 3 hours in 30-minute slots
_SLOT_MINUTES = 30

_ANIM_TIME_MS = 200
_ANIM_SLIDE_PX = 120

_NOW_LINE_RELPATH = 'resources/skins/Main/media/white.png'

_TEXT_COLOR = 'FFCCCCCC'
_CURSOR_TEXT_COLOR = 'FFFFFFFF'
_PAST_TEXT_COLOR = 'FF808080'

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
        self._anim_parity = 0

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
        # OK on a cell/channel row: no-op (Programme info dialog is a
        # later ticket).
        pass

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
                label = xbmcgui.ControlLabel(0, 0, 1, _ROW_HEIGHT, '')
                added.append(image)
                added.append(label)
                row_pool.append((image, label))
            self._pool.append(row_pool)
        self.addControls(added)
        for row_pool in self._pool:
            for image, label in row_pool:
                image.setVisible(False)
                label.setVisible(False)

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

    def _relayout(self, anim_dx=None, anim_dy=None):
        """Hide -> update -> flip -> show: rebuild every visible row's
        cells from the pool so no frame exposes stale text. When called
        with a direction (anim_dx/anim_dy not None -- the top row or the
        time viewport actually changed) the moved cells slide in from that
        offset, or fade in place when a slide would cross the header,
        footer, or channel column; otherwise any leftover animation from a
        previous move is cleared and nothing new is attached."""
        for row_pool in self._pool:
            for image, label in row_pool:
                image.setVisible(False)
                label.setVisible(False)

        selected = self.getControl(CHANNEL_LIST_ID).getSelectedPosition()
        self._top_row = guide.compute_top_row(self._top_row, selected)
        focused_row = selected - self._top_row
        now = datetime.utcnow()

        self._update_header()
        self._row_cells = []
        to_show = []
        animated_specs = []
        dx_val = anim_dx or 0
        dy_val = anim_dy or 0
        grid_bottom_y = _HEADER_HEIGHT + (guide.VISIBLE_ROWS - 1) * _ROW_HEIGHT

        for row in range(guide.VISIBLE_ROWS):
            channel_index = self._top_row + row
            cells = []
            if channel_index < len(self._channel_rows):
                programmes = self._channel_programmes(channel_index)
                layout_cells = guide.cell_layout(
                    programmes, self._viewport_start, _GRID_WIDTH, self._no_info_title
                )
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
                    image, label = row_pool[col]
                    self._set_cell((image, label), cell, y, is_cursor, now)
                    to_show.append((image, label))
                    cells.append(dict(cell, pool_index=col))

                    final_x = cell['x'] + _LEFT_COL_WIDTH
                    start_x = final_x + dx_val
                    start_y = y + dy_val
                    if start_x < _LEFT_COL_WIDTH or start_y < _HEADER_HEIGHT \
                            or start_y > grid_bottom_y:
                        kind = 'fade'
                    else:
                        kind = 'slide'
                    animated_specs.append((image, kind, dx_val, dy_val))
                    animated_specs.append((label, kind, dx_val, dy_val))
            self._row_cells.append(cells)

        if anim_dx is not None or anim_dy is not None:
            self._animate(animated_specs)
        else:
            self._clear_animations(animated_specs)
        for image, label in to_show:
            image.setVisible(True)
            label.setVisible(True)
        self._update_now_line()

    def _label_color_for(self, cell, now, is_cursor):
        if is_cursor:
            return _CURSOR_TEXT_COLOR
        if cell['end'] <= now and cell['title'] != self._no_info_title:
            return _PAST_TEXT_COLOR
        return _TEXT_COLOR

    def _set_cell(self, pool_entry, cell, y, is_cursor, now):
        image, label = pool_entry
        text_color = self._label_color_for(cell, now, is_cursor)
        image.setPosition(cell['x'] + _LEFT_COL_WIDTH, y)
        image.setWidth(max(1, cell['width'] - 2))
        image.setHeight(_ROW_HEIGHT - 2)
        image.setColorDiffuse('FF3A6EA5' if is_cursor else 'FF202020')
        label.setPosition(cell['x'] + _LEFT_COL_WIDTH + 8, y)
        label.setWidth(max(1, cell['width'] - 16))
        label.setHeight(_ROW_HEIGHT)
        label.setLabel(_colored(cell['title'], text_color))

    def _animate(self, specs):
        # A window property flipped only when a full relayout happens
        # (top row or time viewport changed) -- never on an in-viewport
        # cursor move -- so skin animations conditioned on it reliably
        # re-fire (a static condition="true" only ever fires once).
        if not specs:
            self._clear_animations(specs)
            return
        self._anim_parity = 1 - self._anim_parity
        want = self._anim_parity
        for control, kind, dx, dy in specs:
            if kind == 'fade':
                effect = 'effect=fade start=0 end=100 time=%d delay=%d' % (_ANIM_TIME_MS, _ANIM_TIME_MS)
            else:
                effect = 'effect=slide start=%d,%d end=0,0 time=%d' % (dx, dy, _ANIM_TIME_MS)
            control.setAnimations([(
                'conditional',
                '%s reversible=false condition=String.IsEqual(Window.Property(guide_anim),%d)'
                % (effect, want),
            )])
        self.setProperty('guide_anim', str(want))

    @staticmethod
    def _clear_animations(specs):
        for control, _kind, _dx, _dy in specs:
            control.setAnimations([])

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
        channel_index = self._top_row + focused_row
        programmes = self._channel_programmes(channel_index)
        target_start = guide.move_cursor_horizontal(programmes, self._cursor_time, direction)
        if target_start is None:
            return
        target = guide.programme_at(programmes, target_start)
        floor, ceiling = self._clamp_bounds(datetime.utcnow())
        new_viewport_start = guide.scroll_for_target(
            self._viewport_start, target['start'], target['end'], direction, floor, ceiling
        )
        if new_viewport_start is None:
            old_time = self._cursor_time
            new_time = max(target['start'], self._viewport_start)
            self._cursor_time = new_time
            if not self._swap_cursor_cell(focused_row, old_time, new_time):
                self._relayout()
            return
        if new_viewport_start == self._viewport_start:
            return
        self._viewport_start = new_viewport_start
        self._load_programmes()
        axis = max(target['start'], new_viewport_start)
        end = guide.viewport_end(new_viewport_start)
        if axis >= end:
            # Even a page-capped scroll didn't bring the target fully into
            # view: land on the actual on-screen cell nearest the new
            # viewport's end (guaranteed to start before it) rather than an
            # arbitrary offset.
            row_programmes = self._channel_programmes(channel_index)
            cells = guide.cell_layout(row_programmes, new_viewport_start, _GRID_WIDTH, self._no_info_title)
            axis = cells[-1]['start']
        self._cursor_time = axis
        self._relayout(anim_dx=_ANIM_SLIDE_PX if direction > 0 else -_ANIM_SLIDE_PX)

    def _skip_viewport(self, hours):
        offset = self._cursor_time - self._viewport_start
        now = datetime.utcnow()
        new_start = guide.clamp_viewport(self._viewport_start + timedelta(hours=hours), now, self._tz)
        self._viewport_start = new_start
        self._cursor_time = new_start + offset
        self._load_programmes()
        self._relayout(anim_dx=_ANIM_SLIDE_PX if hours > 0 else -_ANIM_SLIDE_PX)

    def _jump_to_now(self):
        now = datetime.utcnow()
        new_start = guide.round_down_30_local(now, self._tz)
        anim_dx = _ANIM_SLIDE_PX if new_start >= self._viewport_start else -_ANIM_SLIDE_PX
        self._viewport_start = new_start
        self._cursor_time = now
        self._load_programmes()
        self._relayout(anim_dx=anim_dx)

    def _swap_cursor_cell(self, row, old_time, new_time):
        old_cell = self._find_cell(row, old_time)
        new_cell = self._find_cell(row, new_time)
        if old_cell is None or new_cell is None:
            return False
        now = datetime.utcnow()
        old_pool = self._pool[row][old_cell['pool_index']]
        old_pool[0].setColorDiffuse('FF202020')
        old_pool[1].setLabel(_colored(old_cell['title'], self._label_color_for(old_cell, now, False)))
        new_pool = self._pool[row][new_cell['pool_index']]
        new_pool[0].setColorDiffuse('FF3A6EA5')
        new_pool[1].setLabel(_colored(new_cell['title'], _CURSOR_TEXT_COLOR))
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
            dy = _ROW_HEIGHT if new_top > prev_top else -_ROW_HEIGHT
            self._relayout(anim_dy=dy)
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
        old_cell = self._find_cell(old_row, self._cursor_time)
        if old_cell is not None:
            old_pool = self._pool[old_row][old_cell['pool_index']]
            old_pool[0].setColorDiffuse('FF202020')
            old_pool[1].setLabel(_colored(old_cell['title'], self._label_color_for(old_cell, now, False)))
        new_pool = self._pool[new_row][new_cell['pool_index']]
        new_pool[0].setColorDiffuse('FF3A6EA5')
        new_pool[1].setLabel(_colored(new_cell['title'], _CURSOR_TEXT_COLOR))
        return True


def _abs_path(addon_path, relpath):
    # Python-created controls need absolute texture paths -- bare skin
    # texture names stop resolving for them after any layout mutation.
    return addon_path.rstrip('/') + '/' + relpath
