# -*- coding: utf-8 -*-
"""PlaybackWindow: TiviMate-style in-player OSD driven by a PlaybackSession
(issue #27, building on the minimal window from issue #24).

The top info bar, the Groups/Channels zapping overlay and number entry are
all driven off window properties and injectable collaborators
(player/probe/scheduler/clock/persist_learned_form/osd_hide_seconds/
number_commit_delay/now_fn) so the window is unit-testable with fakes.
"""
import calendar
import threading
import time
from datetime import datetime, timedelta

import xbmc
import xbmcaddon
import xbmcgui

from .. import autoplay, catchup, channels, guide, ipc, log, osd, playback, seek, urls
from .. import player as player_module
from .. import providers
from . import programme_info

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

_ALIVE_STATES = ('connecting', 'reconnecting', 'playing')
_CONNECTING_STATES = ('connecting', 'reconnecting')

GROUPS_LIST_ID = 200
CHANNELS_LIST_ID = 201
PROGRESS_TRACK_ID = 703
PROGRESS_FILL_ID = 704
PROGRESS_WIDTH = 600
PROGRESS_KNOB_ID = 705
PROGRESS_X = 940
PROGRESS_KNOB_Y = 78
PROGRESS_KNOB_SIZE = 8
PROGRESS_KNOB_FOCUSED_ID = 706
PROGRESS_KNOB_FOCUSED_Y = 74
PROGRESS_KNOB_FOCUSED_SIZE = 16
PROGRAMME_ROW_ID = 710
SEEK_ROW_ID = 711
BTN_REWIND_ID = 712
BTN_PLAYPAUSE_ID = 713
BTN_FASTFORWARD_ID = 714
BTN_LIVE_ID = 715
_BUTTON_ROW_IDS = (BTN_REWIND_ID, BTN_PLAYPAUSE_ID, BTN_FASTFORWARD_ID, BTN_LIVE_ID)

_DEFAULT_OSD_HIDE_SECONDS = 3
_DEFAULT_NUMBER_COMMIT_DELAY = 1.5
# ffmpegdirect's timeshift buffer end runs ~1s ahead of the decode position at
# the live edge, so a small tolerance is needed to avoid a false "-00:01" indicator.
_BEHIND_LIVE_TOLERANCE_SECONDS = 3

# Wide enough to step (Left/Right) back through a Catch-up window.
_PROGRAMME_WINDOW_BEFORE = timedelta(days=7)
_PROGRAMME_WINDOW_AFTER = timedelta(hours=12)

_UPNEXT_END_TOLERANCE_SECONDS = 5

_NO_UPNEXT_TARGET = object()


def _epoch(dt):
    return calendar.timegm(dt.utctimetuple())


class PlaybackWindow(xbmcgui.WindowXML):
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
    osd_position = None
    number_commit_delay = None
    seek_steps = None
    seek_delay_ms = None
    now_fn = None
    session = None
    catchup = None
    persist_catchup_form = None
    notify = None
    open_list_on_init = False
    dialog_cls = programme_info.ProgrammeInfoDialog
    upnext_delay = 5

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
        self._render_pending = False
        self._step_programme = None
        self._step_timer = None
        self._upnext = False
        self._upnext_timer = None
        self._upnext_fallback_timer = None
        self._upnext_programme = None
        self._upnext_remaining = 0
        self._upnext_session_stopped = False
        self._awaiting_upnext_stop_target = _NO_UPNEXT_TARGET
        self._pending_transition = None
        self._pending_transition_fallback_timer = None
        self._lock = threading.RLock()
        self._paused = False
        self._seek_timer = None
        self._seek_stepper = None
        self._screensaver_inhibited = False
        if self.osd_position is None:
            self.osd_position = self._addon_setting_string('osd_position', 'top')
        if self.osd_position != 'bottom':
            self.osd_position = 'top'
        # Set before doModal() draws the first frame: a Window's property
        # store is independent of Dialog vs XML window type, so WindowXML
        # honours setProperty() called here exactly like WindowXMLDialog
        # did -- the spinner and channel labels are already correct on
        # frame one instead of appearing a beat later once onInit() runs.
        self.setProperty('state', 'connecting')
        self.setProperty('status_text', xbmcaddon.Addon().getLocalizedString(_STR_CONNECTING))
        self.setProperty('bar_visible', '1')
        self.setProperty('osd_position', self.osd_position)
        self.setProperty('list_visible', '0')
        self.setProperty('digits', '')
        self.setProperty('catchup', '1' if self.catchup else '0')
        self.setProperty('programme_live', '0')
        self.setProperty('seekable', '0')
        self.setProperty('upnext', '0')
        self.setProperty('upnext_title', '')
        self.setProperty('upnext_seconds', '')
        self.setProperty('paused', '0')
        self.setProperty('seek_step', '')
        self.setProperty('behind_live', '0')
        self.setProperty('behind_text', '')
        if self.snapshot is not None:
            self.setProperty('channel_name', self.snapshot['name'])
            self.setProperty('channel_number', str(self.snapshot['number']))
            self.setProperty('channel_logo', self.snapshot.get('logo_url') or '')
            self.setProperty('seekable', '1' if self._catchup_window_days() else '0')

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
        if self.seek_steps is None or self.seek_delay_ms is None:
            steps, delay_ms = seek.read_seek_settings(xbmc.executeJSONRPC)
            if self.seek_steps is None:
                self.seek_steps = steps
            if self.seek_delay_ms is None:
                self.seek_delay_ms = delay_ms
        self._seek_stepper = seek.SeekStepper(self.seek_steps)

        xbmc.executebuiltin('InhibitScreensaver(true)')
        self._screensaver_inhibited = True

        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._progress_loop)
        self._thread.daemon = True
        self._thread.start()

        self._start_new_session()
        if self.open_list_on_init:
            self._open_list()
        self._watcher = ipc.GenerationWatcher(self._on_generation_change)

    def _on_generation_change(self, generation):
        with self._lock:
            if self._digits:
                self._render_pending = True
                return
            self._refresh_in_place()

    def _refresh_in_place(self):
        if not self.catchup:
            self._load_programmes()
            self._apply_now_next(self.now_fn())
        if self._list_open:
            groups_control = self.getControl(GROUPS_LIST_ID)
            group_item = groups_control.getSelectedItem()
            group_kind = group_item.getProperty('kind') if group_item is not None else 'all'
            group_id = group_item.getProperty('group_id') if group_item is not None else ''

            self._render_groups()
            new_group_position = 0
            for index in range(groups_control.size()):
                item = groups_control.getListItem(index)
                if item.getProperty('kind') == group_kind and (
                    group_kind != 'group' or item.getProperty('group_id') == group_id
                ):
                    new_group_position = index
                    break
            groups_control.selectItem(new_group_position)
            self._last_group_position = new_group_position
            self._render_channels_list()

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

    @staticmethod
    def _addon_setting_string(key, default):
        try:
            value = xbmcaddon.Addon().getSettingString(key)
        except Exception:
            value = ''
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
        self.setProperty('stream_res', '')
        self.setProperty('stream_fps', '')
        self.setProperty('stream_vcodec', '')
        self.setProperty('stream_audio', '')
        self.setProperty('catchup', '1' if self.catchup else '0')
        self.setProperty('seekable', '1' if self._catchup_window_days() else '0')
        self._playing = False
        if self.catchup is None and self.conn is not None:
            autoplay.remember_last_channel(
                self.conn, self.snapshot['provider_id'], self.snapshot['channel_key']
            )
        self._load_channel_info()
        self._show_bar(arm_hide=False)
        if not self._list_open:
            self.setFocusId(SEEK_ROW_ID)
        self.session = playback.PlaybackSession(
            self.snapshot, self.player, self.probe, self.scheduler, self.clock,
            self.persist_learned_form, self._on_state,
            catchup=self.catchup, persist_catchup_form=self.persist_catchup_form,
        )
        self.player.attach(self)
        self.session.start()

    # -- player callbacks (issue #30): the window is attached to the
    # player (not the session directly) so it can intercept a Catch-up
    # programme naturally ending and route it to the Up-next countdown
    # instead of the session's Drop/reconnect handling. -----------------

    def on_av_started(self):
        session = self.session
        if session is not None:
            session.on_av_started()

    def on_error(self):
        session = self.session
        if session is not None:
            session.on_error()

    def on_stopped(self):
        self._on_player_stop_or_end(is_ended=False)

    def on_ended(self):
        self._on_player_stop_or_end(is_ended=True)

    def _on_player_stop_or_end(self, is_ended):
        with self._lock:
            log.debug(
                'Playback stop/end callback: is_ended={0} pending={1} catchup={2} playing={3}'.format(
                    is_ended, self._pending_transition is not None, bool(self.catchup), self._playing
                )
            )
            if self._awaiting_upnext_stop_target is not _NO_UPNEXT_TARGET:
                target = self._awaiting_upnext_stop_target
                self._awaiting_upnext_stop_target = _NO_UPNEXT_TARGET
                self._cancel_upnext_fallback_timer()
                self._advance_upnext(target)
                return
            if self._pending_transition is not None:
                # The outgoing session's own stop/end callback, arriving
                # (possibly late) after we already asked it to abort in
                # _replace_session: run the deferred transition instead of
                # forwarding this to whatever session is current now.
                self._run_pending_transition('callback')
                return
            if self.catchup and self._playing and not self._upnext and self._near_catchup_end():
                session = self.session
                self._playing = False
                if session is not None:
                    session.abort()
                    self.player.detach(session)
                self._begin_upnext(session_already_stopped=True)
                return
            session = self.session
        if session is not None:
            if is_ended:
                session.on_ended()
            else:
                session.on_stopped()

    def _zap(self, provider_id, channel_key):
        with self._lock:
            self._cancel_step_timer()
            self._step_programme = None
            snapshot = playback.load_snapshot(self.conn, provider_id, channel_key)
            if snapshot is None:
                self._abort_current_session()
                return

            def prepare():
                self.snapshot = snapshot
                self.catchup = None
            self._replace_session(prepare)

    def _abort_current_session(self):
        """Abort the current session (if alive) and leave the window in a
        consistent, visible 'stopped' state -- never a dangling session with
        stale 'Connecting...' properties. Used by every abort-without-
        restart path: digit entry, Back with the list open, and Back
        leaving playback. A transition that replaces the session with a new
        one (zap, catch-up rebuild, ...) goes through `_replace_session`
        instead, which never lets the outgoing session's stop/end callback
        reach the new one."""
        self._reset_transient_playback_state()
        self._cancel_pending_transition()
        if self.session is not None and self.getProperty('state') in _ALIVE_STATES:
            self.session.abort()
            self.player.detach(self.session)
            self._playing = False
            self.setProperty('state', 'stopped')
            self.setProperty('status_text', '')
            self._show_bar(arm_hide=False)

    def _replace_session(self, prepare):
        """Replace the running session with a new one built by `prepare()`
        (sets self.snapshot/self.catchup for the session `_start_new_session`
        is about to build) without ever letting the outgoing session's
        onPlayBackStopped/Ended reach the new one: Kodi can deliver that
        callback (tens to hundreds of ms after `player.stop()`) well after
        the new stream's `player.play()` already started, and forwarding it
        there aborts the just-opened stream ("Catch-up not available" from
        a perfectly good URL). If a session is alive, abort it, show
        'connecting' (never 'stopped', so the OSD doesn't flash it) and
        defer `prepare()` + `_start_new_session()` until that stop callback
        arrives (`_on_player_stop_or_end`) or a 3s fallback fires. A second
        call while one is already pending just replaces which `prepare`
        eventually runs (last wins). With no alive session, run
        immediately. Used by every "replace the running session" transition
        (zap, live-to-Catch-up seek rebuild, programme-step catch-up);
        Up-next keeps its own, pre-existing await-stop mechanism."""
        self._reset_transient_playback_state()
        if self._pending_transition is not None:
            log.debug('Playback session replace: transition already pending, replacing it (last wins)')
            self._pending_transition = prepare
            return
        session = self.session
        if session is not None and self.getProperty('state') in _ALIVE_STATES:
            log.debug('Playback session replace: deferred, session alive (state={0})'.format(
                self.getProperty('state')
            ))
            self._pending_transition = prepare
            session.abort()
            self.player.detach(session)
            self._playing = False
            self.setProperty('state', 'connecting')
            self.setProperty(
                'status_text', xbmcaddon.Addon().getLocalizedString(_STR_CONNECTING)
            )
            self._show_bar(arm_hide=False)
            self._pending_transition_fallback_timer = self.scheduler(
                3, self._on_pending_transition_fallback
            )
            return
        log.debug('Playback session replace: immediate, no alive session')
        prepare()
        self._start_new_session()

    def _run_pending_transition(self, source):
        log.debug('Playback pending transition running (source={0})'.format(source))
        prepare = self._pending_transition
        self._pending_transition = None
        self._cancel_pending_transition_fallback()
        if prepare is None:
            return
        prepare()
        self._start_new_session()

    def _on_pending_transition_fallback(self):
        with self._lock:
            if self._pending_transition is None:
                return
            self._run_pending_transition('fallback')

    def _cancel_pending_transition_fallback(self):
        if self._pending_transition_fallback_timer is not None:
            self._pending_transition_fallback_timer.cancel()
            self._pending_transition_fallback_timer = None

    def _cancel_pending_transition(self):
        self._pending_transition = None
        self._cancel_pending_transition_fallback()

    def _reset_transient_playback_state(self):
        self._paused = False
        self.setProperty('paused', '0')
        self._cancel_seek_timer()
        if self._seek_stepper is not None:
            self._seek_stepper.reset()
        self.setProperty('seek_step', '')

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
        self._load_programmes()
        if self.catchup:
            self._apply_catchup_bar()
            self._update_behind_live()
            return
        self._apply_now_next(self.now_fn())
        self._update_behind_live()

    def _apply_catchup_bar(self):
        self.setProperty(
            'programme_live',
            '1' if _epoch(self.now_fn()) < self.catchup['end'] else '0',
        )
        self.setProperty('now_title', self.catchup.get('title') or '')
        self.setProperty('now_times', osd.format_position(
            self._catchup_elapsed_seconds(), self._catchup_duration_seconds(),
        ))
        self.setProperty('next_title', '')
        fraction = osd.catchup_progress_fraction(
            self.catchup['start'], self.catchup['end'], 0, self._catchup_elapsed_seconds(),
        )
        self._set_progress(fraction)

    def _catchup_duration_seconds(self):
        if not self.catchup:
            return 0
        return max(0, self.catchup['end'] - self.catchup['start'])

    def _catchup_elapsed_seconds(self):
        # ffmpegdirect's catchup mode already includes the Attempt's buffer
        # offset in getTime() (it adds catchup_buffer_offset to every pts),
        # so once AV has started that call alone is the elapsed position
        # within the programme; before it, fall back to the session's own
        # offset (e.g. a rebuild landing mid-programme before playback begins).
        if self._playing:
            return self._player_time_seconds()
        return int(self.catchup.get('offset', 0)) if self.catchup else 0

    def _near_catchup_end(self):
        duration = self._catchup_duration_seconds()
        if duration <= 0:
            return False
        elapsed = self._catchup_elapsed_seconds()
        return elapsed > 0 and (duration - elapsed) <= _UPNEXT_END_TOLERANCE_SECONDS

    def _catchup_reached_end(self):
        duration = self._catchup_duration_seconds()
        return duration > 0 and self._catchup_elapsed_seconds() >= duration

    # -- Up-next countdown (issue #30) ----------------------------------

    def _next_programme_after(self, end_dt):
        candidates = sorted(self._programmes, key=lambda p: p['start'])
        for programme in candidates:
            if programme['start'] >= end_dt:
                return programme
        return None

    def _begin_upnext(self, session_already_stopped):
        with self._lock:
            if self._upnext:
                return
            self._upnext = True
            self._upnext_session_stopped = session_already_stopped
            next_programme = self._next_programme_after(self.catchup['end_dt'])
            self._upnext_programme = next_programme
            self.setProperty('upnext', '1')
            self.setProperty('upnext_title', next_programme['title'] if next_programme is not None else '')
            self._upnext_remaining = self.upnext_delay
            self.setProperty('upnext_seconds', str(self._upnext_remaining))
            self._show_bar(arm_hide=False)
            self._arm_upnext_tick()

    def _arm_upnext_tick(self):
        self._upnext_timer = self.scheduler(1, self._upnext_tick)

    def _upnext_tick(self):
        with self._lock:
            if not self._upnext:
                return
            self._upnext_remaining -= 1
            if self._upnext_remaining <= 0:
                self.setProperty('upnext_seconds', '0')
                self._expire_upnext()
                return
            self.setProperty('upnext_seconds', str(self._upnext_remaining))
            self._arm_upnext_tick()

    def _expire_upnext(self):
        self._cancel_upnext_timer()
        self._upnext = False
        self.setProperty('upnext', '0')
        next_programme = self._upnext_programme
        self._upnext_programme = None
        if self._upnext_session_stopped:
            self._advance_upnext(next_programme)
            return
        self._awaiting_upnext_stop_target = next_programme
        session = self.session
        if session is not None:
            session.abort()
            self.player.detach(session)
        self._upnext_fallback_timer = self.scheduler(3, self._on_upnext_fallback)

    def _on_upnext_fallback(self):
        with self._lock:
            if self._awaiting_upnext_stop_target is _NO_UPNEXT_TARGET:
                return
            target = self._awaiting_upnext_stop_target
            self._awaiting_upnext_stop_target = _NO_UPNEXT_TARGET
            self._advance_upnext(target)

    def _advance_upnext(self, next_programme):
        with self._lock:
            if next_programme is None:
                self.close()
                return
            now = self.now_fn()
            state = catchup.cell_state(
                next_programme['start'], next_programme['end'], self._catchup_window_days(), now,
            )
            if state not in ('live', 'past_playable'):
                self.close()
                return
            self._abort_current_session()
            if state == 'live':
                self.catchup = None
            else:
                self.catchup = self._catchup_dict_for(next_programme, now)
            self._start_new_session()

    def _cancel_upnext(self):
        if not self._upnext:
            return
        self._upnext = False
        self._cancel_upnext_timer()
        self.setProperty('upnext', '0')
        self.setProperty('upnext_title', '')
        self.setProperty('upnext_seconds', '')

    def _cancel_upnext_timer(self):
        if self._upnext_timer is not None:
            self._upnext_timer.cancel()
            self._upnext_timer = None

    def _cancel_upnext_fallback_timer(self):
        if self._upnext_fallback_timer is not None:
            self._upnext_fallback_timer.cancel()
            self._upnext_fallback_timer = None

    # -- Left/Right programme stepping (issue #30) -----------------------

    def _catchup_window_days(self):
        snapshot = self.snapshot
        supported = True if snapshot['kind'] != 'm3u' else urls.m3u_catchup_supported(snapshot)
        return catchup.effective_window_days(snapshot.get('catchup_days'), None, url_supported=supported)

    def _catchup_dict_for(self, programme, now, offset=0):
        return {
            'start': _epoch(programme['start']),
            'end': _epoch(programme['end']),
            'now': _epoch(now),
            'catchup_id': programme.get('catchup_id'),
            'title': programme.get('title') or '',
            'start_dt': programme['start'],
            'end_dt': programme['end'],
            'offset': offset,
        }

    def _programme_containing(self, epoch_seconds):
        for programme in self._programmes:
            if _epoch(programme['start']) <= epoch_seconds < _epoch(programme['end']):
                return programme
        return None

    def _start_catchup_for(self, programme):
        with self._lock:
            now = self.now_fn()

            def prepare():
                self.catchup = self._catchup_dict_for(programme, now)
            self._replace_session(prepare)

    def _referenced_programme(self):
        if self._step_programme is not None:
            return self._step_programme
        if self.catchup:
            for programme in self._programmes:
                if programme['start'] == self.catchup['start_dt']:
                    return programme
            return {
                'start': self.catchup['start_dt'], 'end': self.catchup['end_dt'],
                'title': self.catchup.get('title') or '', 'description': '',
                'catchup_id': self.catchup.get('catchup_id'),
            }
        now_prog, _ = osd.now_next(self._programmes, self.now_fn())
        return now_prog

    def _restore_osd_to_actual(self):
        if self.catchup:
            self._apply_catchup_bar()
        else:
            self._apply_now_next(self.now_fn())

    def _on_step(self, direction):
        with self._lock:
            if self._upnext:
                return
            current = self._referenced_programme()
            if current is None:
                return
            target = osd.neighbour_programme(self._programmes, current, direction)
            if target is current:
                return
            self._step_programme = target
            self.setProperty('now_title', target['title'])
            self.setProperty('now_times', osd.format_times(target['start'], target['end'], self._tz))
            self._show_bar(arm_hide=True)
            self._cancel_step_timer()
            self._step_timer = self.scheduler(self.number_commit_delay, self._commit_step)

    def _commit_step(self):
        with self._lock:
            self._cancel_step_timer()
            programme = self._step_programme
            if programme is None:
                return
            now = self.now_fn()
            window_days = self._catchup_window_days()
            state = catchup.cell_state(programme['start'], programme['end'], window_days, now)
            if state == 'live':
                self._step_programme = None
                if self.catchup is not None:
                    self._zap(self.snapshot['provider_id'], self.snapshot['channel_key'])
                return
            if state == 'past_playable':
                self._step_programme = None
                self._start_catchup_for(programme)
                return
            # 'future' or 'past_unplayable': OSD already shows the stepped
            # programme; no stream change.

    def _cancel_step_timer(self):
        if self._step_timer is not None:
            self._step_timer.cancel()
            self._step_timer = None

    def _set_progress(self, fraction):
        if self._stopped():
            return
        try:
            self.getControl(PROGRESS_FILL_ID).setWidth(int(PROGRESS_WIDTH * fraction))
            self.getControl(PROGRESS_KNOB_ID).setPosition(
                PROGRESS_X + int(PROGRESS_WIDTH * fraction) - PROGRESS_KNOB_SIZE // 2,
                PROGRESS_KNOB_Y,
            )
            self.getControl(PROGRESS_KNOB_FOCUSED_ID).setPosition(
                PROGRESS_X + int(PROGRESS_WIDTH * fraction) - PROGRESS_KNOB_FOCUSED_SIZE // 2,
                PROGRESS_KNOB_FOCUSED_Y,
            )
        except Exception:
            pass

    def _player_time_seconds(self):
        if not self._playing:
            return 0
        try:
            return self.player.getTime()
        except Exception:
            return 0

    def _player_total_seconds(self):
        if not self._playing:
            return 0
        try:
            return self.player.getTotalTime()
        except Exception:
            return 0

    # -- seek stepping / behind-live / pause (issue: OSD transport controls) --

    def _behind_live_seconds(self):
        if self.catchup:
            position = self.catchup['start'] + self._catchup_elapsed_seconds()
            return max(0, _epoch(self.now_fn()) - position)
        total = self._player_total_seconds()
        return max(0, total - self._player_time_seconds())

    def _update_behind_live(self):
        if self.catchup is not None:
            self.setProperty('behind_live', '1')
            self.setProperty('behind_text', '')
            return
        self.setProperty('programme_live', '0')
        behind = self._behind_live_seconds()
        if behind > _BEHIND_LIVE_TOLERANCE_SECONDS:
            self.setProperty('behind_live', '1')
            self.setProperty('behind_text', osd.format_behind(behind))
        else:
            self.setProperty('behind_live', '0')
            self.setProperty('behind_text', '')

    def _cancel_seek_timer(self):
        if self._seek_timer is not None:
            self._seek_timer.cancel()
            self._seek_timer = None

    def _seek_allowed(self):
        return self.catchup is None or bool(self._catchup_window_days())

    def _seek_press(self, direction):
        with self._lock:
            if self._list_open or not self._seek_allowed():
                return
            step = self._seek_stepper.press(direction)
            self._arm_seek(step)

    def _seek_big(self, direction):
        with self._lock:
            if self._list_open or not self._seek_allowed():
                return
            step = self._seek_stepper.press_largest(direction)
            self._arm_seek(step)

    def _arm_seek(self, step):
        self._show_bar(arm_hide=not self._paused)
        self._cancel_seek_timer()
        if step == 0:
            self.setProperty('seek_step', '')
            return
        self.setProperty('seek_step', seek.format_step(step))
        self._seek_timer = self.scheduler(self.seek_delay_ms / 1000.0, self._commit_seek)

    def _commit_seek(self):
        with self._lock:
            self._cancel_seek_timer()
            step = self._seek_stepper.pending
            self._seek_stepper.reset()
            self.setProperty('seek_step', '')
            if step == 0:
                return
            if self._pending_transition is not None or self.getProperty('state') != 'playing':
                # A session replacement is already in flight (or the player
                # isn't attached to anything playing): committing against a
                # stopped/about-to-be-replaced player reads a stale/zeroed
                # position and would rebuild from the wrong place.
                log.debug(
                    'Playback seek commit dropped: pending_transition={0} state={1}'.format(
                        self._pending_transition is not None, self.getProperty('state')
                    )
                )
                return
            self._apply_seek(step)

    def _apply_seek(self, step):
        behind = self._behind_live_seconds()
        now = _epoch(self.now_fn())
        target = min(now, now - behind + step)
        time_seconds = self._player_time_seconds()
        total_seconds = self._player_total_seconds()
        if target >= now - _BEHIND_LIVE_TOLERANCE_SECONDS:
            log.debug(
                'Playback seek: behind={0} time={1} total={2} target={3} path=live'.format(
                    behind, time_seconds, total_seconds, target
                )
            )
            self._go_live_if_needed()
            return
        if self.catchup is not None:
            # ffmpegdirect catchup mode seeks within the programme itself
            # (it expands catchup_url_format_string on every seek), so a
            # seek inside a Catch-up session never rebuilds the URL; it is
            # always native, clamped to the programme's bounds.
            duration = self._catchup_duration_seconds()
            clamped = max(0, min(duration - 1, time_seconds + step)) if duration > 0 \
                else max(0, time_seconds + step)
            log.debug(
                'Playback seek: behind={0} time={1} total={2} target={3} path={4}'.format(
                    behind, time_seconds, total_seconds, target,
                    'native' if clamped == time_seconds + step else 'clamp'
                )
            )
            try:
                self.player.seekTime(clamped)
            except Exception:
                pass
            self._update_behind_live()
            return
        in_buffer = total_seconds > 0 and 0 <= time_seconds + step <= total_seconds
        clamp = not self._catchup_window_days()
        log.debug(
            'Playback seek: behind={0} time={1} total={2} target={3} path={4}'.format(
                behind, time_seconds, total_seconds, target,
                'native' if in_buffer else ('clamp' if clamp else 'rebuild')
            )
        )
        if in_buffer:
            try:
                self.player.seekTime(time_seconds + step)
            except Exception:
                pass
            self._update_behind_live()
            return
        if clamp:
            if total_seconds > 0:
                try:
                    self.player.seekTime(0)
                except Exception:
                    pass
            self._update_behind_live()
            return
        self._rebuild_for_target(target)

    def _go_live_if_needed(self):
        if self.catchup is not None:
            self._zap(self.snapshot['provider_id'], self.snapshot['channel_key'])
            return
        if self._behind_live_seconds() > _BEHIND_LIVE_TOLERANCE_SECONDS:
            self._go_live()

    def _go_live(self):
        total = self._player_total_seconds()
        if total > 0:
            try:
                self.player.seekTime(total)
            except Exception:
                pass
        if self._paused:
            self._paused = False
            self.setProperty('paused', '0')
            self._set_player_paused(False)
        self._update_behind_live()

    def _rebuild_at_target(self, target_epoch, unavailable):
        """Live -> Catch-up rebuild: find the programme covering
        `target_epoch` and start a Catch-up session there -- Start Over
        semantics when the programme is still airing (state 'live') -- or
        call `unavailable()` when no programme covers it or it isn't
        playable (including a 'live' programme with no Catch-up Window at
        all). Used only when a seek on a live session lands before the
        timeshift buffer start; a seek inside an existing Catch-up session
        never rebuilds (ffmpegdirect re-expands the URL itself)."""
        self._load_programmes()
        programme = self._programme_containing(target_epoch)
        window_days = self._catchup_window_days()
        now = self.now_fn()
        state = catchup.cell_state(
            programme['start'], programme['end'], window_days, now
        ) if programme is not None else None
        playable = state == 'past_playable' or (state == 'live' and window_days)
        if programme is None or not playable:
            unavailable()
            return
        programme_start = _epoch(programme['start'])
        offset = max(0, target_epoch - programme_start)

        def prepare():
            self.catchup = self._catchup_dict_for(programme, now, offset=offset)
        self._replace_session(prepare)

    def _rebuild_for_target(self, target_epoch):
        def unavailable():
            addon = xbmcaddon.Addon()
            self.notify('Kodimate', addon.getLocalizedString(_STR_CATCHUP_UNAVAILABLE)
                        % self.snapshot['provider_name'])
        self._rebuild_at_target(target_epoch, unavailable)

    def _player_paused(self):
        try:
            return bool(xbmc.getCondVisibility('Player.Paused'))
        except Exception:
            return None

    def _set_player_paused(self, desired):
        if self._player_paused() == desired:
            return
        try:
            self.player.pause()
        except Exception:
            pass

    def _toggle_pause(self):
        with self._lock:
            if self._list_open or (not self._playing and not self._paused):
                return
            if not self._paused:
                # A pending seek would otherwise commit later against a
                # since-paused player; cancel it so pausing always leaves a
                # clean, non-pending seek state (self._paused itself is
                # untouched by a *later* seek commit -- seekTime() on a
                # paused player stays paused, and a rebuild goes through
                # _abort_current_session, which clears pause state anyway).
                self._cancel_seek_timer()
                self._seek_stepper.reset()
                self.setProperty('seek_step', '')
                self._paused = True
                self._set_player_paused(True)
                self.setProperty('paused', '1')
                self._update_behind_live()
                self._show_bar(arm_hide=False)
                return
            self._paused = False
            self.setProperty('paused', '0')
            self._set_player_paused(False)
            self._update_behind_live()
            self._show_bar(arm_hide=True)

    # -- OSD focus row navigation --------------------------------------

    def _on_horizontal(self, direction):
        focus = self.getFocusId()
        if focus == PROGRAMME_ROW_ID:
            self._on_step(direction)
        elif focus in _BUTTON_ROW_IDS:
            self._move_button_focus(direction)
        else:
            self._seek_press(direction)

    def _visible_button_row_ids(self):
        if self.getProperty('behind_live') == '1':
            ids = _BUTTON_ROW_IDS
        else:
            ids = tuple(i for i in _BUTTON_ROW_IDS if i != BTN_LIVE_ID)
        if self.getProperty('seekable') != '1':
            ids = tuple(i for i in ids if i not in (BTN_REWIND_ID, BTN_FASTFORWARD_ID))
        return ids

    def _move_button_focus(self, direction):
        ids = self._visible_button_row_ids()
        focus = self.getFocusId()
        if focus not in ids:
            ids = _BUTTON_ROW_IDS
        index = ids.index(focus)
        new_index = min(max(index + direction, 0), len(ids) - 1)
        self.setFocusId(ids[new_index])

    def _on_vertical(self, direction):
        focus = self.getFocusId()
        if focus == PROGRAMME_ROW_ID and direction > 0:
            self.setFocusId(SEEK_ROW_ID)
            return
        if focus == SEEK_ROW_ID:
            self.setFocusId(PROGRAMME_ROW_ID if direction < 0 else BTN_PLAYPAUSE_ID)
            return
        if focus in _BUTTON_ROW_IDS and direction < 0:
            self.setFocusId(SEEK_ROW_ID)
            return
        if self._upnext:
            self._cancel_upnext()
        self._open_list()

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
                'description': row.get('description') or '',
                'catchup_id': row.get('catchup_id'),
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
        self._set_progress(fraction)
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
        was_hidden = self.getProperty('bar_visible') != '1'
        self.setProperty('bar_visible', '1')
        if was_hidden and not self._list_open:
            self.setFocusId(SEEK_ROW_ID)
        self._cancel_hide_timer()
        if arm_hide and not self._paused:
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

    def _stopped(self):
        return self._stop_event is not None and self._stop_event.is_set()

    def _tick(self):
        if self._stopped():
            return
        try:
            if not self._playing:
                return
            self._update_stream_info()
            if self._stopped():
                return
            if self.catchup:
                self._apply_catchup_bar()
                self._update_behind_live()
                if not self._upnext and self._catchup_reached_end():
                    self._playing = False
                    self._begin_upnext(session_already_stopped=False)
                return
            now = self.now_fn()
            now_prog, _ = osd.now_next(self._programmes, now)
            if now_prog is not None and now_prog['end'] <= now:
                self._load_programmes()
            if self._stopped():
                return
            self._apply_now_next(now)
            self._update_behind_live()
        except Exception as exc:
            log.debug('Playback OSD tick failed: {0}'.format(exc))

    def _update_stream_info(self):
        if self._stopped():
            return
        info = osd.format_stream_info(
            xbmc.getInfoLabel('Player.Process(videowidth)'),
            xbmc.getInfoLabel('Player.Process(videoheight)'),
            xbmc.getInfoLabel('VideoPlayer.VideoCodec'),
            xbmc.getInfoLabel('Player.Process(videofps)'),
            xbmc.getInfoLabel('VideoPlayer.AudioCodec'),
            xbmc.getInfoLabel('VideoPlayer.AudioChannels'),
        )
        if info['res'] and info['fps'] and info['vcodec'] and info['audio']:
            self.setProperty('stream_res', info['res'])
            self.setProperty('stream_fps', info['fps'])
            self.setProperty('stream_vcodec', info['vcodec'])
            self.setProperty('stream_audio', info['audio'])

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
        found = False
        current_provider_id = self.snapshot.get('provider_id') if self.snapshot else None
        current_channel_key = self.snapshot.get('channel_key') if self.snapshot else None
        current_number = self.snapshot.get('number') if self.snapshot else None
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
                found = True
        if not found and rows and current_number is not None:
            # The current channel went Stale/hidden: zapping away from it
            # lands on the nearest listable channel by Effective Channel
            # Number (ties keep the earlier row in list order).
            select_position = min(
                range(len(rows)), key=lambda i: abs(rows[i]['number'] - current_number)
            )
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
            elif control_id == SEEK_ROW_ID:
                self._toggle_pause()
            elif control_id == BTN_REWIND_ID:
                self._seek_press(-1)
            elif control_id == BTN_PLAYPAUSE_ID:
                self._toggle_pause()
            elif control_id == BTN_FASTFORWARD_ID:
                self._seek_press(1)
            elif control_id == BTN_LIVE_ID:
                if self.catchup is not None:
                    self._zap(self.snapshot['provider_id'], self.snapshot['channel_key'])
                else:
                    self._go_live()

    # -- number entry --------------------------------------------------

    def _on_digit(self, digit):
        with self._lock:
            if self._upnext:
                self._cancel_upnext()
            self._cancel_step_timer()
            self._step_programme = None
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
            self._apply_pending_render()
            if not digits:
                return
            rows = channels.list_channels(self.conn)
            row = osd.resolve_number(rows, int(digits))
            if row is not None:
                self._zap(row['provider_id'], row['channel_key'])

    def _cancel_digit_entry(self):
        with self._lock:
            self._cancel_digit_timer()
            self._digits = ''
            self.setProperty('digits', '')
            self._apply_pending_render()

    def _apply_pending_render(self):
        if self._render_pending:
            self._render_pending = False
            self._refresh_in_place()

    def _cancel_digit_timer(self):
        if self._digit_timer is not None:
            self._digit_timer.cancel()
            self._digit_timer = None

    # -- input -----------------------------------------------------------

    _PAUSE_ACTION_IDS = (
        xbmcgui.ACTION_PAUSE, xbmcgui.ACTION_PLAYER_PLAY, xbmcgui.ACTION_PLAYER_PLAYPAUSE,
    )

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

            if action_id == xbmcgui.ACTION_STOP:
                self._abort_and_close()
                return

            # Remote/keyboard player transport, honoured regardless of focus.
            if action_id in self._PAUSE_ACTION_IDS:
                self._toggle_pause()
                return
            if action_id in (xbmcgui.ACTION_STEP_BACK, xbmcgui.ACTION_PLAYER_REWIND):
                self._seek_press(-1)
                return
            if action_id in (xbmcgui.ACTION_STEP_FORWARD, xbmcgui.ACTION_PLAYER_FORWARD):
                self._seek_press(1)
                return
            if action_id == xbmcgui.ACTION_BIG_STEP_BACK:
                self._seek_big(-1)
                return
            if action_id == xbmcgui.ACTION_BIG_STEP_FORWARD:
                self._seek_big(1)
                return

            if self._list_open:
                if self.getFocusId() == GROUPS_LIST_ID:
                    position = self.getControl(GROUPS_LIST_ID).getSelectedPosition()
                    if position != self._last_group_position:
                        self._last_group_position = position
                        self._render_channels_list()
                return

            if self.getProperty('bar_visible') != '1':
                if action_id in (
                    xbmcgui.ACTION_MOVE_LEFT, xbmcgui.ACTION_MOVE_RIGHT,
                    xbmcgui.ACTION_MOVE_UP, xbmcgui.ACTION_MOVE_DOWN,
                ):
                    self._show_bar(arm_hide=(self.getProperty('state') == 'playing'))
                return

            if action_id in (xbmcgui.ACTION_MOVE_LEFT, xbmcgui.ACTION_MOVE_RIGHT):
                self._on_horizontal(-1 if action_id == xbmcgui.ACTION_MOVE_LEFT else 1)
                return

            if action_id in (xbmcgui.ACTION_MOVE_UP, xbmcgui.ACTION_MOVE_DOWN):
                self._on_vertical(-1 if action_id == xbmcgui.ACTION_MOVE_UP else 1)
                return

    def _on_ok(self):
        if self._upnext:
            self._cancel_upnext()
        if self._digits:
            self._commit_digits()
            return
        if self._list_open:
            return
        if self.getProperty('state') in ('failed', 'stopped'):
            self._start_new_session()
            return
        if self.getProperty('bar_visible') == '1':
            focus = self.getFocusId()
            if focus == SEEK_ROW_ID:
                # onClick(711) already fires for a real OK/click on this
                # focused button; toggling here too would double-toggle.
                pass
            elif focus in _BUTTON_ROW_IDS:
                # onClick(712-715) already handles these.
                pass
            else:
                self._on_ok_bar_visible()
        else:
            self._show_bar(arm_hide=(self.getProperty('state') == 'playing'))

    def _on_ok_bar_visible(self):
        self._cancel_step_timer()
        programme = self._referenced_programme()
        if programme is None:
            return
        now = self.now_fn()
        window_days = self._catchup_window_days()
        state = catchup.cell_state(programme['start'], programme['end'], window_days, now)
        dialog = self.dialog_cls.open(
            title=programme.get('title') or '',
            times=osd.format_times(programme['start'], programme['end'], self._tz),
            description=programme.get('description') or '',
            actions=catchup.actions_for(state, start_over_ok=bool(window_days)),
        )
        result = dialog.result
        self._step_programme = None
        if result == 'watch_live':
            self._zap(self.snapshot['provider_id'], self.snapshot['channel_key'])
        elif result in ('start_over', 'play_catchup'):
            self._start_catchup_for(programme)

    def _on_back(self):
        with self._lock:
            if self._upnext:
                self._cancel_upnext()
                self._abort_and_close()
                return
            if self._step_programme is not None:
                self._cancel_step_timer()
                self._step_programme = None
                self._restore_osd_to_actual()
                return
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
        if getattr(self, '_watcher', None) is not None:
            self._watcher.stop()
        if self._stop_event is not None:
            self._stop_event.set()
        if self._thread is not None and threading.current_thread() is not self._thread:
            self._thread.join(5.0)
        self._cancel_hide_timer()
        self._cancel_digit_timer()
        self._cancel_step_timer()
        self._cancel_seek_timer()
        self._cancel_upnext_timer()
        self._cancel_upnext_fallback_timer()
        self._cancel_pending_transition_fallback()
        if self._screensaver_inhibited:
            xbmc.executebuiltin('InhibitScreensaver(false)')
            self._screensaver_inhibited = False
        super(PlaybackWindow, self).close()
