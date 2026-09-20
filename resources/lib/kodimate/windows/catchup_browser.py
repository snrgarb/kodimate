# -*- coding: utf-8 -*-
"""CatchupBrowserWindow: the Catch-up browser (issue #30 part 1), CONTEXT.md
"Catch-up browser". Left pane lists every channel with an Effective
Catch-up Window (Favourites first), right pane lists that channel's past
Programmes grouped by day, newest first; OK opens the shared Programme
info dialog, same as the Guide."""
import calendar
import threading
from collections import OrderedDict
from datetime import datetime, timedelta

import xbmcaddon
import xbmcgui

from .. import catchup, channels, guide, ipc, osd, playback
from .base import BaseWindow
from .playback import PlaybackWindow
from .programme_info import ProgrammeInfoDialog
from .rail import RAIL_LIVETV_ID, RAIL_CATCHUP_ID, RAIL_SETTINGS_ID

CHANNEL_LIST_ID = 200
PROGRAMME_LIST_ID = 201

_STR_TODAY = 32111
_STR_YESTERDAY = 32112
_STR_NO_CATCHUP_CHANNELS = 32122
_STR_NO_CATCHUP_PROGRAMMES = 32123
_STR_CATCHUP_DAYS = 32124

# Real Kodi's xbmcgui module does not export these action-id constants (only
# xbmcgui.ACTION_MOVE_LEFT/RIGHT/UP/DOWN, ACTION_NAV_BACK, ACTION_PREVIOUS_MENU
# and a handful of others genuinely exist there); defined here directly from
# Kodi's ActionIDs.h numeric values instead, same convention as windows/guide.py.
_ACTION_PAGE_UP = 5
_ACTION_PAGE_DOWN = 6


class CatchupBrowserWindow(BaseWindow):
    xmlFile = 'script-kodimate-catchup-browser.xml'
    _tz = None  # override in tests/subclasses to fix the local zone
    dialog_cls = ProgrammeInfoDialog
    playback_cls = PlaybackWindow

    def onInit(self):
        if getattr(self, '_initialised', False):
            with self._lock:
                if self._render_pending:
                    self._render_pending = False
                    self._refresh_in_place()
            return

        self._modal_depth = 0
        self._render_pending = False
        self._closed = False
        self._watcher = None
        # Guards _modal_depth/_render_pending/_closed and every render below:
        # GenerationWatcher.onNotification runs on Kodi's Monitor thread
        # while the UI thread may be inside onAction/onClick.
        self._lock = threading.RLock()
        self._last_channel_position = 0
        self._right_entries = []
        self._rail_focus_id = RAIL_CATCHUP_ID

        self._channel_rows = self._build_channel_rows()
        self._render_channels()
        self._render_programmes()
        self.setProperty('rail_selected', 'catchup')
        self._watcher = ipc.GenerationWatcher(self._on_generation_change)
        self.setFocusId(CHANNEL_LIST_ID)
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
                return True
        return False

    def _refresh_in_place(self):
        control = self.getControl(CHANNEL_LIST_ID)
        selected = control.getSelectedPosition()
        old_row = self._channel_rows[selected] if 0 <= selected < len(self._channel_rows) else None
        old_key = (old_row['provider_id'], old_row['channel_key']) if old_row else None

        self._channel_rows = self._build_channel_rows()
        self._render_channels()

        new_index = 0
        if old_key is not None:
            for index, row in enumerate(self._channel_rows):
                if (row['provider_id'], row['channel_key']) == old_key:
                    new_index = index
                    break
            else:
                new_index = min(selected, len(self._channel_rows) - 1) if self._channel_rows else 0
        if self._channel_rows:
            control.selectItem(new_index)
        self._last_channel_position = new_index
        self._render_programmes()

    def close(self):
        with self._lock:
            self._closed = True
            if getattr(self, '_watcher', None) is not None:
                self._watcher.stop()
        super(CatchupBrowserWindow, self).close()

    def onAction(self, action):
        action_id = action.getId()
        if action_id in (xbmcgui.ACTION_NAV_BACK, xbmcgui.ACTION_PREVIOUS_MENU):
            self.close()
            return
        if action_id == xbmcgui.ACTION_MOVE_LEFT:
            self._handle_left()
            return
        if action_id == xbmcgui.ACTION_MOVE_RIGHT:
            self._handle_right()
            return
        if self.getFocusId() == CHANNEL_LIST_ID:
            self._maybe_render_for_channel_move()
            return
        if self.getFocusId() == PROGRAMME_LIST_ID and action_id in (
                xbmcgui.ACTION_MOVE_UP, xbmcgui.ACTION_MOVE_DOWN,
                _ACTION_PAGE_UP, _ACTION_PAGE_DOWN):
            direction = -1 if action_id in (xbmcgui.ACTION_MOVE_UP, _ACTION_PAGE_UP) else 1
            self._skip_header_row(direction)
            self._update_day_property()

    def _handle_left(self):
        if self.getFocusId() == CHANNEL_LIST_ID:
            self.setFocusId(self._rail_focus_id)
        elif self.getFocusId() == PROGRAMME_LIST_ID:
            self.setFocusId(CHANNEL_LIST_ID)

    def _handle_right(self):
        focus_id = self.getFocusId()
        if focus_id in (RAIL_LIVETV_ID, RAIL_CATCHUP_ID, RAIL_SETTINGS_ID):
            self._rail_focus_id = focus_id
            self.setFocusId(CHANNEL_LIST_ID)

    def onFocus(self, control_id):
        if control_id == CHANNEL_LIST_ID:
            self._maybe_render_for_channel_move()
            self._update_day_property(0)
        elif control_id == PROGRAMME_LIST_ID:
            self._skip_header_row(1)
            self._update_day_property()

    def _maybe_render_for_channel_move(self):
        position = self.getControl(CHANNEL_LIST_ID).getSelectedPosition()
        if position != self._last_channel_position:
            self._last_channel_position = position
            self._render_programmes()

    def _skip_header_row(self, direction):
        """Header rows never hold focus: called after 201 gains focus or a
        Up/Down move lands on one, this steps in `direction` to the next
        programme row, falling back to the row after (the first programme
        of the top day) when `direction` runs off the top of the list."""
        control = self.getControl(PROGRAMME_LIST_ID)
        position = control.getSelectedPosition()
        if not (0 <= position < len(self._right_entries)):
            return
        if self._right_entries[position]['type'] == 'programme':
            return
        target = position + direction
        if not (0 <= target < len(self._right_entries)):
            target = position + 1
        if 0 <= target < len(self._right_entries):
            control.selectItem(target)

    def _update_day_property(self, index=None):
        if index is None:
            index = self.getControl(PROGRAMME_LIST_ID).getSelectedPosition()
        if 0 <= index < len(self._right_entries):
            self.setProperty('catchup_day', self._right_entries[index]['day_label'])
        else:
            self.setProperty('catchup_day', '')

    def _update_channel_header(self):
        row = self._selected_channel_row()
        if row is None:
            self.setProperty('catchup_channel', '')
            self.setProperty('catchup_channel_logo', '')
            return
        addon = xbmcaddon.Addon()
        suffix = addon.getLocalizedString(_STR_CATCHUP_DAYS) % row['window_days']
        self.setProperty('catchup_channel', u'%s %s · %s' % (row['number'], row['name'], suffix))
        self.setProperty('catchup_channel_logo', row['logo_url'] or '')

    def onClick(self, control_id):
        if control_id == RAIL_LIVETV_ID:
            self.close()
            return
        if control_id == RAIL_CATCHUP_ID:
            return
        if control_id == RAIL_SETTINGS_ID:
            self._open_settings()
            return
        if control_id != PROGRAMME_LIST_ID:
            return
        position = self.getControl(PROGRAMME_LIST_ID).getSelectedPosition()
        if not (0 <= position < len(self._right_entries)):
            return
        entry = self._right_entries[position]
        if entry['type'] != 'programme':
            return
        channel_row = self._selected_channel_row()
        if channel_row is None:
            return
        now = datetime.utcnow()
        window_days = channel_row['window_days']
        state = catchup.cell_state(entry['start'], entry['end'], window_days, now)
        self._enter_modal()
        try:
            dialog = self.dialog_cls.open(
                title=entry['title'],
                times=osd.format_times(entry['start'], entry['end'], self._tz),
                description=entry.get('description') or '',
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
                                'start': _epoch(entry['start']),
                                'end': _epoch(entry['end']),
                                'now': _epoch(now),
                                'catchup_id': entry.get('catchup_id'),
                                'title': entry['title'],
                                'start_dt': entry['start'],
                                'end_dt': entry['end'],
                            },
                        )
        finally:
            refreshed = self._exit_modal()
        if not refreshed:
            self._render_programmes()

    def _open_settings(self):
        self._enter_modal()
        try:
            xbmcaddon.Addon().openSettings()
        finally:
            self._exit_modal()

    # -- data ----------------------------------------------------------

    def _build_channel_rows(self):
        favourites = channels.list_channels(self.conn, favourites=True)
        all_rows = channels.list_channels(self.conn)
        seen = set()
        ordered = []
        for row in favourites + all_rows:
            key = (row['provider_id'], row['channel_key'])
            if key in seen:
                continue
            seen.add(key)
            ordered.append(row)

        result = []
        for row in ordered:
            window_days = catchup.effective_window_days(
                row.get('catchup_days'), None, url_supported=row.get('catchup_supported', True),
            )
            if window_days:
                row = dict(row)
                row['window_days'] = window_days
                result.append(row)
        return result

    def _selected_channel_row(self):
        position = self.getControl(CHANNEL_LIST_ID).getSelectedPosition()
        if 0 <= position < len(self._channel_rows):
            return self._channel_rows[position]
        return None

    # -- rendering -------------------------------------------------------

    def _render_channels(self):
        control = self.getControl(CHANNEL_LIST_ID)
        control.reset()
        items = []
        if self._channel_rows:
            for row in self._channel_rows:
                item = xbmcgui.ListItem(label=row['name'])
                item.setProperty('number', str(row['number']))
                item.setProperty('catchup', '1')
                if row['logo_url']:
                    item.setArt({'icon': row['logo_url']})
                items.append(item)
        else:
            addon = xbmcaddon.Addon()
            hint_item = xbmcgui.ListItem(label=addon.getLocalizedString(_STR_NO_CATCHUP_CHANNELS))
            hint_item.setProperty('hint', '1')
            items.append(hint_item)
        control.addItems(items)
        if items:
            control.selectItem(0)

    def _render_programmes(self):
        control = self.getControl(PROGRAMME_LIST_ID)
        control.reset()
        self._right_entries = []
        self._update_channel_header()

        channel_row = self._selected_channel_row()
        if channel_row is None:
            self._update_day_property(0)
            return

        now = datetime.utcnow()
        window_days = channel_row['window_days']
        window_start = guide.format_iso(now - timedelta(days=window_days))
        window_end = guide.format_iso(now)
        raw = channels.list_programmes(self.conn, [channel_row['id']], window_start, window_end)
        rows = raw.get(channel_row['id'], [])

        groups = OrderedDict()
        for prow in rows:
            start = guide.parse_iso(prow['start'])
            if not (start < now and start >= now - timedelta(days=window_days)):
                continue
            groups.setdefault(guide.utc_to_local(start, self._tz).date(), []).append({
                'type': 'programme',
                'start': start,
                'end': guide.parse_iso(prow['end']),
                'title': prow['title'] or '',
                'description': prow.get('description') or '',
                'catchup_id': prow.get('catchup_id'),
            })

        today = guide.utc_to_local(now, self._tz).date()
        yesterday = today - timedelta(days=1)
        addon = xbmcaddon.Addon()
        items = []
        for day in sorted(groups.keys(), reverse=True):
            if day == today:
                label = addon.getLocalizedString(_STR_TODAY)
            elif day == yesterday:
                label = addon.getLocalizedString(_STR_YESTERDAY)
            else:
                label = day.strftime('%a %d %b')
            header_item = xbmcgui.ListItem(label=label)
            header_item.setProperty('header', '1')
            items.append(header_item)
            self._right_entries.append({'type': 'header', 'day_label': label})

            for entry in sorted(groups[day], key=lambda e: e['start'], reverse=True):
                item = xbmcgui.ListItem(label=entry['title'])
                item.setProperty('header', '0')
                item.setProperty('times', osd.format_times(entry['start'], entry['end'], self._tz))
                item.setProperty('duration', osd.format_duration(entry['start'], entry['end']))
                item.setProperty('description', entry['description'])
                state = catchup.cell_state(entry['start'], entry['end'], window_days, now)
                entry['type'] = 'programme'
                entry['day_label'] = label
                item.setProperty('playable', '1' if state == 'past_playable' else '0')
                items.append(item)
                self._right_entries.append(entry)

        if not items:
            hint_item = xbmcgui.ListItem(label=addon.getLocalizedString(_STR_NO_CATCHUP_PROGRAMMES))
            hint_item.setProperty('header', '1')
            items.append(hint_item)
            self._right_entries.append({'type': 'hint', 'day_label': ''})

        control.addItems(items)
        self._update_day_property(0)



def _epoch(dt):
    return calendar.timegm(dt.utctimetuple())
