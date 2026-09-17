# -*- coding: utf-8 -*-
"""PlaybackWindow: TiviMate-style in-player OSD driven by a PlaybackSession
(issue #27, building on the minimal window from issue #24).

The top info bar, the Groups/Channels zapping overlay and number entry are
all driven off window properties and injectable collaborators
(player/probe/scheduler/clock/persist_learned_form/osd_hide_seconds/
number_commit_delay/now_fn) so the window is unit-testable with fakes.
"""
import threading
import time
from datetime import datetime, timedelta

import xbmc
import xbmcaddon
import xbmcgui

from .. import channels, guide, log, osd, playback
from .. import player as player_module
from .. import providers

_STR_CONNECTING = 32084
_STR_RECONNECTING = 32085
_STR_UNAVAILABLE = 32086
_STR_LOGIN_REJECTED = 32087
_STR_CONNECTION_LIMIT = 32088
_STR_CONNECTION_LIMIT_N = 32089
_STR_NO_INFO = 32083
_STR_ALL_CHANNELS = 32038
_STR_FAVOURITES = 32039
_STR_CATCHUP_UNAVAILABLE = 32093

_REASON_STRINGS = {
    'unavailable': _STR_UNAVAILABLE,
    'login_rejected': _STR_LOGIN_REJECTED,
    'connection_limit': _STR_CONNECTION_LIMIT,
}

_ACTIVATE_FULLSCREEN_SLEEP_MS = 300

_ALIVE_STATES = ('connecting', 'reconnecting', 'playing')
_CONNECTING_STATES = ('connecting', 'reconnecting')

GROUPS_LIST_ID = 200
CHANNELS_LIST_ID = 201
PROGRESS_TRACK_ID = 703
PROGRESS_FILL_ID = 704
PROGRESS_WIDTH = 600

_DEFAULT_OSD_HIDE_SECONDS = 3
_DEFAULT_NUMBER_COMMIT_DELAY = 1.5

_PROGRAMME_WINDOW_BEFORE = timedelta(hours=1)
_PROGRAMME_WINDOW_AFTER = timedelta(hours=12)


class PlaybackWindow(xbmcgui.WindowXMLDialog):
    xmlFile = 'script-kodimate-playback.xml'
    theme = 'Main'
    res = '1080i'
    _tz = None  # override in tests/subclasses to fix the local zone

    conn = None
    snapshot = None
    player = None
    probe = None
    scheduler = None
    clock = None
    persist_learned_form = None
    osd_hide_seconds = None
    number_commit_delay = None
    now_fn = None
    session = None
    catchup = None
    persist_catchup_form = None
    notify = None

    def __init__(self, *args, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
        super(PlaybackWindow, self).__init__(*args)
        self._list_open = False
        self._digits = ''
        self._digit_timer = None
        self._hide_timer = None
        self._playing = False
        self._programmes = []
        self._last_group_position = 0
        self._stop_event = None
        self._thread = None
        self._lock = threading.RLock()
        # Set before doModal() draws the first frame: WindowXMLDialog
        # honours setProperty() called here, so the spinner and channel
        # labels are already correct on frame one instead of appearing a
        # beat later once onInit() runs.
        self.setProperty('state', 'connecting')
        self.setProperty('status_text', xbmcaddon.Addon().getLocalizedString(_STR_CONNECTING))
        self.setProperty('bar_visible', '1')
        self.setProperty('list_visible', '0')
        self.setProperty('digits', '')
        if self.snapshot is not None:
            self.setProperty('channel_name', self.snapshot['name'])
            self.setProperty('channel_number', str(self.snapshot['number']))
            self.setProperty('channel_logo', self.snapshot.get('logo_url') or '')

    @classmethod
    def open(cls, **kwargs):
        path = xbmcaddon.Addon().getAddonInfo('path')
        window = cls(cls.xmlFile, path, cls.theme, cls.res, **kwargs)
        window.doModal()
        return window

    def onInit(self):
        if self.player is None:
            self.player = player_module.get_player()
        if self.probe is None:
            self.probe = playback.fetch_probe
        if self.scheduler is None:
            self.scheduler = playback.timer_scheduler
        if self.clock is None:
            self.clock = time.monotonic
        if self.persist_learned_form is None:
            self.persist_learned_form = self._persist_learned_form
        if self.persist_catchup_form is None:
            self.persist_catchup_form = self._persist_catchup_form
        if self.notify is None:
            self.notify = self._notify
        if self.osd_hide_seconds is None:
            self.osd_hide_seconds = self._addon_setting_int(
                'osd_hide_seconds', _DEFAULT_OSD_HIDE_SECONDS
            )
        if self.number_commit_delay is None:
            self.number_commit_delay = self._addon_setting_number(
                'number_commit_delay', _DEFAULT_NUMBER_COMMIT_DELAY
            )
        if self.now_fn is None:
            self.now_fn = datetime.utcnow

        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._progress_loop)
        self._thread.daemon = True
        self._thread.start()

        self._start_new_session()

    @staticmethod
    def _addon_setting_int(key, default):
        try:
            value = xbmcaddon.Addon().getSettingInt(key)
        except Exception:
            value = 0
        return value if value else default

    @staticmethod
    def _addon_setting_number(key, default):
        try:
            value = xbmcaddon.Addon().getSettingNumber(key)
        except Exception:
            value = 0
        return value if value else default

    def _persist_learned_form(self, provider_id, form):
        providers.set_learned_stream_format(self.conn, provider_id, form)

    def _persist_catchup_form(self, provider_id, form):
        providers.set_catchup_url_form(self.conn, provider_id, form)

    @staticmethod
    def _notify(heading, message):
        xbmcgui.Dialog().notification(heading, message)

    # -- session lifecycle -------------------------------------------------

    def _start_new_session(self):
        self.setProperty('state', 'connecting')
        self.setProperty('status_text', xbmcaddon.Addon().getLocalizedString(_STR_CONNECTING))
        self.setProperty('reason', '')
        self.setProperty('catchup', '1' if self.catchup else '0')
        self._playing = False
        self._load_channel_info()
        self._show_bar(arm_hide=False)
        self.session = playback.PlaybackSession(
            self.snapshot, self.player, self.probe, self.scheduler, self.clock,
            self.persist_learned_form, self._on_state,
            catchup=self.catchup, persist_catchup_form=self.persist_catchup_form,
        )
        self.player.attach(self.session)
        self.session.start()
        xbmc.sleep(_ACTIVATE_FULLSCREEN_SLEEP_MS)
        xbmc.executebuiltin('ActivateWindow(fullscreenvideo)')

    def _zap(self, provider_id, channel_key):
        with self._lock:
            self._abort_current_session()
            snapshot = playback.load_snapshot(self.conn, provider_id, channel_key)
            if snapshot is None:
                return
            self.snapshot = snapshot
            self.catchup = None
            self._start_new_session()

    def _abort_current_session(self):
        """Abort the current session (if alive) and leave the window in a
        consistent, visible 'stopped' state -- never a dangling session with
        stale 'Connecting...' properties. Used by every abort path: zap,
        digit entry, Back with the list open, and Back leaving playback."""
        if self.session is not None and self.getProperty('state') in _ALIVE_STATES:
            self.session.abort()
            self.player.detach(self.session)
            self._playing = False
            self.setProperty('state', 'stopped')
            self.setProperty('status_text', '')
            self._show_bar(arm_hide=False)

    def _on_state(self, state, reason):
        # Called from player callback threads: only setProperty/timer calls
        # here, except the Failed -> auto-open-list transition the spec
        # requires (issue #27 acceptance criteria), and the catch-up
        # failure toast + close (issue #28), which is only reachable when
        # self.catchup is set (a catch-up PlaybackSession never reports any
        # other failure reason).
        addon = xbmcaddon.Addon()
        if state == 'failed' and reason == 'catchup_unavailable':
            self.setProperty('state', state)
            self.setProperty('reason', reason)
            self.notify('Kodimate', addon.getLocalizedString(_STR_CATCHUP_UNAVAILABLE)
                        % self.snapshot['provider_name'])
            self.close()
            return
        self.setProperty('state', state)
        self.setProperty('reason', reason or '')
        if state == 'connecting':
            self.setProperty('status_text', addon.getLocalizedString(_STR_CONNECTING))
        elif state == 'reconnecting':
            self.setProperty('status_text', addon.getLocalizedString(_STR_RECONNECTING))
        elif state == 'playing':
            self.setProperty('status_text', '')
        elif state == 'failed':
            string_id = _REASON_STRINGS.get(reason, _STR_UNAVAILABLE)
            text = addon.getLocalizedString(string_id)
            if reason == 'connection_limit' and self.snapshot.get('max_connections'):
                text = addon.getLocalizedString(_STR_CONNECTION_LIMIT_N) % self.snapshot['max_connections']
            self.setProperty('status_text', text)

        self._playing = (state == 'playing')
        self._show_bar(arm_hide=(state == 'playing'))
        if state == 'failed':
            self._open_list()

    # -- info bar ------------------------------------------------------

    def _load_channel_info(self):
        self.setProperty('channel_name', self.snapshot['name'])
        self.setProperty('channel_number', str(self.snapshot['number']))
        self.setProperty('channel_logo', self.snapshot.get('logo_url') or '')
        if self.catchup:
            self._apply_catchup_bar()
            return
        self._load_programmes()
        self._apply_now_next(self.now_fn())

    def _apply_catchup_bar(self):
        self.setProperty('now_title', self.catchup.get('title') or '')
        self.setProperty('now_times', osd.format_times(
            self.catchup['start_dt'], self.catchup['end_dt'], self._tz,
        ))
        self.setProperty('next_title', '')
        offset_seconds = self.session.catchup_offset_seconds if self.session is not None else 0
        player_seconds = self._player_time_seconds()
        fraction = osd.catchup_progress_fraction(
            self.catchup['start'], self.catchup['end'], offset_seconds, player_seconds,
        )
        try:
            self.getControl(PROGRESS_FILL_ID).setWidth(int(PROGRESS_WIDTH * fraction))
        except Exception:
            pass

    def _player_time_seconds(self):
        if not self._playing:
            return 0
        try:
            return self.player.getTime()
        except Exception:
            return 0

    def _load_programmes(self):
        self._programmes = []
        channel_id = self.snapshot.get('id') if self.snapshot else None
        if channel_id is None or self.conn is None:
            return
        now = self.now_fn()
        window_start = guide.format_iso(now - _PROGRAMME_WINDOW_BEFORE)
        window_end = guide.format_iso(now + _PROGRAMME_WINDOW_AFTER)
        raw = channels.list_programmes(self.conn, [channel_id], window_start, window_end)
        self._programmes = [
            {
                'start': guide.parse_iso(row['start']),
                'end': guide.parse_iso(row['end']),
                'title': row['title'] or '',
            }
            for row in raw.get(channel_id, [])
        ]

    def _apply_now_next(self, now):
        addon = xbmcaddon.Addon()
        now_prog, next_prog = osd.now_next(self._programmes, now)
        if now_prog is not None:
            self.setProperty('now_title', now_prog['title'])
            self.setProperty('now_times', osd.format_times(now_prog['start'], now_prog['end'], self._tz))
            fraction = osd.progress_fraction(now_prog, now)
        else:
            self.setProperty('now_title', addon.getLocalizedString(_STR_NO_INFO))
            self.setProperty('now_times', '')
            fraction = 0.0
        self.setProperty('next_title', next_prog['title'] if next_prog is not None else '')
        try:
            self.getControl(PROGRESS_FILL_ID).setWidth(int(PROGRESS_WIDTH * fraction))
        except Exception:
            pass
        return now_prog

    def _show_bar(self, arm_hide):
        # Deliberately does NOT take self._lock: _on_state (called by
        # PlaybackSession while it holds its own internal lock) calls this,
        # and the UI thread calls session.abort() (which takes that same
        # session lock) while holding self._lock -- session-lock-then-
        # window-lock on one thread and window-lock-then-session-lock on
        # the other is a lock-order deadlock. setProperty and the timer
        # cancel/arm here are cheap; callers that need atomicity already
        # hold self._lock themselves (an RLock), so nothing is lost.
        self.setProperty('bar_visible', '1')
        self._cancel_hide_timer()
        if arm_hide:
            self._hide_timer = self.scheduler(self.osd_hide_seconds, self._hide_bar)

    def _hide_bar(self):
        with self._lock:
            self._cancel_hide_timer()
            self.setProperty('bar_visible', '0')

    def _cancel_hide_timer(self):
        if self._hide_timer is not None:
            self._hide_timer.cancel()
            self._hide_timer = None

    # -- 1Hz progress thread ------------------------------------------------

    def _progress_loop(self):
        while not self._stop_event.wait(1.0):
            self._tick()

    def _tick(self):
        if self._stop_event is not None and self._stop_event.is_set():
            return
        try:
            if not self._playing or self.getProperty('bar_visible') != '1':
                return
            if self.catchup:
                self._apply_catchup_bar()
                return
            now = self.now_fn()
            now_prog, _ = osd.now_next(self._programmes, now)
            if now_prog is not None and now_prog['end'] <= now:
                self._load_programmes()
            self._apply_now_next(now)
        except Exception as exc:
            log.debug('Playback OSD tick failed: {0}'.format(exc))

    # -- Groups/Channels overlay --------------------------------------------

    def _open_list(self):
        self._list_open = True
        self.setProperty('list_visible', '1')
        self._render_groups()
        self._last_group_position = self.getControl(GROUPS_LIST_ID).getSelectedPosition()
        self._render_channels_list()
        self.setFocusId(CHANNELS_LIST_ID)

    def _close_list(self):
        self._list_open = False
        self.setProperty('list_visible', '0')

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

    def _render_channels_list(self):
        item = self.getControl(GROUPS_LIST_ID).getSelectedItem()
        kind = item.getProperty('kind') if item is not None else 'all'
        group_id = None
        favourites = False
        if kind == 'favourites':
            favourites = True
        elif kind == 'group':
            group_id = int(item.getProperty('group_id'))

        control = self.getControl(CHANNELS_LIST_ID)
        control.reset()
        rows = channels.list_channels(
            self.conn, group_id=group_id, favourites=favourites, show_hidden=False,
        )
        now_titles = channels.now_titles(
            self.conn, [row['id'] for row in rows], guide.format_iso(self.now_fn())
        )
        items = []
        select_position = 0
        current_provider_id = self.snapshot.get('provider_id') if self.snapshot else None
        current_channel_key = self.snapshot.get('channel_key') if self.snapshot else None
        for index, row in enumerate(rows):
            list_item = xbmcgui.ListItem(label=row['name'])
            list_item.setLabel2(str(row['number']))
            list_item.setProperty('channel_key', row['channel_key'])
            list_item.setProperty('provider_id', str(row['provider_id']))
            list_item.setProperty('now_title', now_titles.get(row['id']) or '')
            if row['logo_url']:
                list_item.setArt({'icon': row['logo_url']})
            items.append(list_item)
            if row['provider_id'] == current_provider_id and row['channel_key'] == current_channel_key:
                select_position = index
        control.addItems(items)
        if items:
            control.selectItem(select_position)

    def onClick(self, control_id):
        with self._lock:
            if control_id == GROUPS_LIST_ID:
                if not self._list_open:
                    return
                self._last_group_position = self.getControl(GROUPS_LIST_ID).getSelectedPosition()
                self._render_channels_list()
                self.setFocusId(CHANNELS_LIST_ID)
            elif control_id == CHANNELS_LIST_ID:
                if not self._list_open:
                    return
                item = self.getControl(CHANNELS_LIST_ID).getSelectedItem()
                if item is None:
                    return
                provider_id = int(item.getProperty('provider_id'))
                channel_key = item.getProperty('channel_key')
                self._close_list()
                self._zap(provider_id, channel_key)

    # -- number entry --------------------------------------------------

    def _on_digit(self, digit):
        with self._lock:
            if self.getProperty('state') in _CONNECTING_STATES:
                self._abort_current_session()
            self._digits += str(digit)
            self.setProperty('digits', self._digits)
            self._cancel_digit_timer()
            self._digit_timer = self.scheduler(self.number_commit_delay, self._commit_digits)

    def _commit_digits(self):
        with self._lock:
            self._cancel_digit_timer()
            digits = self._digits
            self._digits = ''
            self.setProperty('digits', '')
            if not digits:
                return
            rows = channels.list_channels(self.conn)
            row = osd.resolve_number(rows, int(digits))
            if row is not None:
                self._zap(row['provider_id'], row['channel_key'])

    def _cancel_digit_entry(self):
        self._cancel_digit_timer()
        self._digits = ''
        self.setProperty('digits', '')

    def _cancel_digit_timer(self):
        if self._digit_timer is not None:
            self._digit_timer.cancel()
            self._digit_timer = None

    # -- input -----------------------------------------------------------

    def onAction(self, action):
        with self._lock:
            action_id = action.getId()

            digit = osd.digit_from_action_id(action_id)
            if digit is not None and not self._list_open:
                self._on_digit(digit)
                return

            if action_id in (xbmcgui.ACTION_NAV_BACK, xbmcgui.ACTION_PREVIOUS_MENU):
                self._on_back()
                return

            if action_id == xbmcgui.ACTION_SELECT_ITEM:
                self._on_ok()
                return

            if self._list_open:
                if self.getFocusId() == GROUPS_LIST_ID:
                    position = self.getControl(GROUPS_LIST_ID).getSelectedPosition()
                    if position != self._last_group_position:
                        self._last_group_position = position
                        self._render_channels_list()
                return

            if action_id in (xbmcgui.ACTION_MOVE_UP, xbmcgui.ACTION_MOVE_DOWN,
                              xbmcgui.ACTION_MOVE_LEFT, xbmcgui.ACTION_MOVE_RIGHT):
                self._open_list()

    def _on_ok(self):
        if self._digits:
            self._commit_digits()
            return
        if self._list_open:
            return
        if self.getProperty('state') in ('failed', 'stopped'):
            self._start_new_session()
            return
        if self.getProperty('bar_visible') == '1':
            self._hide_bar()
        else:
            self._show_bar(arm_hide=(self.getProperty('state') == 'playing'))

    def _on_back(self):
        with self._lock:
            if self._digits:
                self._cancel_digit_entry()
                return
            if self._list_open:
                if self.getProperty('state') in _CONNECTING_STATES:
                    self._abort_current_session()
                self._close_list()
                return
            if self.getProperty('state') in _CONNECTING_STATES:
                self._abort_and_close()
                return
            if self.getProperty('bar_visible') == '1':
                self._hide_bar()
                return
            self._abort_and_close()

    def _abort_and_close(self):
        self._abort_current_session()
        self.close()

    def close(self):
        if self._stop_event is not None:
            self._stop_event.set()
        if self._thread is not None:
            self._thread.join(1.0)
        self._cancel_hide_timer()
        self._cancel_digit_timer()
        super(PlaybackWindow, self).close()
