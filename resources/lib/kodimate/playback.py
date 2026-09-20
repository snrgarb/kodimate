# -*- coding: utf-8 -*-
"""Playback Session state machine (issue #24, CONTEXT.md "Playback Session").

`PlaybackSession` owns the Connecting -> Playing -> Reconnecting -> Failed
state machine for one Channel. All I/O collaborators (player, probe,
scheduler, clock, persistence, logging) are injected so the machine itself
has no xbmc*/network/DB dependency and is unit-testable with fakes.

The Channel snapshot is loaded once via `load_snapshot()` from the channel
and provider rows and is never re-read for the life of the session
(Reconnect Attempts reuse it verbatim).
"""
import json
import threading

try:
    from urllib.parse import urlparse
except ImportError:  # pragma: no cover - Python 2 fallback, unused on target
    from urlparse import urlparse

from . import fetch
from . import log as log_module
from . import tz
from . import urls

START_TIMEOUT_SECONDS = 30
EARLY_DROP_SECONDS = 5
MAX_START_ATTEMPTS = 2
RECONNECT_DELAYS = (0, 3, 6)
PROBE_TIMEOUT_SECONDS = 5

_NO_FALLBACK = object()


def load_snapshot(conn, provider_id, channel_key):
    """Build a Channel snapshot for a Playback Session, or None if not found."""
    row = conn.execute(
        "SELECT c.channel_key, c.name, c.stream_url, c.headers_json, "
        "COALESCE(o.number, c.provider_number + p.number_offset, "
        "c.position + p.number_offset) AS number, "
        "p.id, p.kind, p.xtream_host, p.xtream_username, p.xtream_password, "
        "p.user_agent, p.stream_format, p.learned_stream_format, "
        "p.allowed_output_formats, p.max_connections, c.id, c.logo_url, "
        "p.name, c.catchup_mode, c.catchup_source, c.catchup_correction_hours, "
        "p.catchup_correction_hours, p.catchup_url_form, "
        "COALESCE(c.catchup_days, p.catchup_days_default), p.server_timezone "
        "FROM channel c "
        "JOIN provider p ON p.id = c.provider_id "
        "LEFT JOIN channel_override o "
        "ON o.provider_id = c.provider_id AND o.channel_key = c.channel_key "
        "WHERE c.provider_id = ? AND c.channel_key = ?",
        (provider_id, channel_key),
    ).fetchone()
    if row is None:
        return None
    headers = json.loads(row[3]) if row[3] else {}
    allowed_output_formats = json.loads(row[13]) if row[13] else None
    return {
        'channel_key': row[0],
        'name': row[1],
        'stream_url': row[2],
        'headers': headers,
        'number': row[4],
        'provider_id': row[5],
        'kind': row[6],
        'xtream_host': row[7],
        'xtream_username': row[8],
        'xtream_password': row[9],
        'user_agent': row[10],
        'stream_format': row[11],
        'learned_stream_format': row[12],
        'allowed_output_formats': allowed_output_formats,
        'max_connections': row[14],
        'id': row[15],
        'logo_url': row[16],
        'provider_name': row[17],
        'catchup_mode': row[18],
        'catchup_source': row[19],
        'catchup_correction_hours': row[20],
        'provider_catchup_correction_hours': row[21],
        'catchup_url_form': row[22],
        'catchup_days': row[23],
        'server_timezone': row[24],
    }


def fetch_probe(url, headers):
    """Production `probe` collaborator: a bounded Range GET via fetch.probe_stream."""
    return fetch.probe_stream(url, headers=headers, timeout=PROBE_TIMEOUT_SECONDS)


def resolve_redirect(url, headers):
    """Production `resolver` collaborator: learns the edge's tokenised URL
    with a single no-follow request, so the player's own request is the
    only one that ever fetches the stream."""
    return fetch.resolve_redirect(url, headers=headers)


def _mime_type_for(url):
    path = urlparse(url).path
    if path.endswith('.ts'):
        return 'video/mp2t'
    if path.endswith('.m3u8'):
        return 'application/vnd.apple.mpegurl'
    return None


class _TimerHandle(object):
    def __init__(self, timer):
        self._timer = timer

    def cancel(self):
        self._timer.cancel()


def timer_scheduler(delay_seconds, fn):
    """Production `scheduler` collaborator: threading.Timer."""
    timer = threading.Timer(delay_seconds, fn)
    timer.daemon = True
    timer.start()
    return _TimerHandle(timer)


def _classify(probe_status, kind):
    if probe_status in (401, 403):
        return 'login_rejected'
    if probe_status in (429, 509, 406):
        return 'connection_limit'
    if probe_status == 404:
        return 'unavailable' if kind == 'm3u' else 'transient'
    return 'transient'


class PlaybackSession(object):
    def __init__(self, snapshot, player, probe, scheduler, clock,
                 persist_learned_form, on_state, logger=None,
                 catchup=None, persist_catchup_form=None, resolver=None):
        self.snapshot = snapshot
        self.player = player
        self.probe = probe
        self.scheduler = scheduler
        self.clock = clock
        self.resolver = resolver if resolver is not None else resolve_redirect
        self.persist_learned_form = persist_learned_form
        self.on_state = on_state
        self.logger = logger if logger is not None else log_module
        self.catchup = catchup
        self.persist_catchup_form = persist_catchup_form
        self._catchup_offset_seconds = int(catchup.get('offset', 0)) if catchup is not None else 0
        self._catchup_clock_origin = self.clock() if catchup is not None else None
        self._explicit_catchup_form = (
            catchup is not None and snapshot.get('catchup_url_form') in ('path', 'query')
        )

        self._lock = threading.Lock()
        self._alive = True
        self.state = None
        self.reason = None
        self._phase = None
        self._attempt_number = 0
        self._reconnect_delay_index = 0
        self._form = None
        self._current_url = None
        self._current_headers = None
        self._av_started_at = None
        self._attempt_start_clock = None
        self._start_timer = None
        self._reconnect_timer = None
        self._explicit_format = bool(snapshot.get('stream_format'))
        self._probing = False

    @property
    def catchup_offset_seconds(self):
        return self._catchup_offset_seconds

    # -- entry point ---------------------------------------------------

    def start(self):
        with self._lock:
            if not self._alive:
                return
            form = self._initial_form()
            self._begin_attempt('start', 1, form)

    def abort(self):
        with self._lock:
            if not self._alive:
                return
            self._cancel_start_timer()
            self._cancel_reconnect_timer()
            if self.state in ('connecting', 'reconnecting'):
                self._debug_attempt_outcome('aborted')
            self._alive = False
            self.player.stop()

    # -- player callbacks ------------------------------------------------

    def on_av_started(self):
        with self._lock:
            self.logger.debug('Playback callback: onAVStarted')
            if (not self._alive or self._probing
                    or self.state not in ('connecting', 'reconnecting')):
                return
            self._cancel_start_timer()
            self._av_started_at = self.clock()
            self.state = 'playing'
            self._log_attempt('playing')
            if self._phase == 'start' and self._attempt_number == 2 and self.snapshot['kind'] == 'xtream':
                if self.catchup is not None:
                    if not self._explicit_catchup_form and self.persist_catchup_form is not None:
                        self.persist_catchup_form(self.snapshot['provider_id'], self._form)
                elif not self._explicit_format:
                    self.persist_learned_form(self.snapshot['provider_id'], self._form)
            self.on_state('playing', None)

    def on_error(self):
        with self._lock:
            self.logger.debug('Playback callback: onPlayBackError')
            self._handle_stop_or_error(is_error=True)

    def on_stopped(self):
        with self._lock:
            self.logger.debug('Playback callback: onPlayBackStopped')
            self._handle_stop_or_error(is_error=False)

    def on_ended(self):
        with self._lock:
            self.logger.debug('Playback callback: onPlayBackEnded')
            self._handle_stop_or_error(is_error=False)

    # -- internal transitions --------------------------------------------

    def _handle_stop_or_error(self, is_error):
        if not self._alive or self._probing or self.state == 'failed':
            return
        if is_error:
            is_start_failure = True
        elif self.state in ('connecting', 'reconnecting'):
            is_start_failure = True
        elif self.state == 'playing':
            elapsed = self.clock() - self._av_started_at
            is_start_failure = elapsed < EARLY_DROP_SECONDS
        else:
            return

        if is_start_failure:
            if self._phase == 'reconnect':
                self._reconnect_attempt_failed()
            else:
                self._start_attempt_failed()
        else:
            self._enter_reconnecting()

    def _on_start_timeout(self):
        with self._lock:
            self.logger.debug('Playback timer: start timeout')
            if (not self._alive or self._probing
                    or self.state not in ('connecting', 'reconnecting')):
                return
            if self._phase == 'reconnect':
                self._reconnect_attempt_failed()
            else:
                self._start_attempt_failed()

    def _reconnect_fire(self, attempt_number):
        with self._lock:
            self.logger.debug('Playback timer: reconnect attempt {0}'.format(attempt_number))
            if not self._alive or self._phase != 'reconnect':
                return
            self._begin_attempt('reconnect', attempt_number, self._form)

    def _start_attempt_failed(self):
        self._cancel_start_timer()
        self.player.stop()
        url = self._current_url
        headers = self._current_headers
        attempt_number = self._attempt_number
        self.logger.debug(
            'Playback probe: attempt {0} form={1}'.format(
                attempt_number, self._form if self._form else '-'
            )
        )
        # Run the network probe with the lock released: it can take up to
        # PROBE_TIMEOUT_SECONDS and must never block abort() (called from
        # the UI thread on Back) or other callbacks.
        self._probing = True
        self._lock.release()
        try:
            probe_status = self.probe(url, headers)
        finally:
            self._lock.acquire()
            self._probing = False

        if not self._alive:
            # Aborted (or otherwise ended) while the probe was in flight;
            # discard the result rather than acting on a dead session.
            return

        self._log_attempt('start-failure', probe_status)

        classification = _classify(probe_status, self.snapshot['kind'])
        if classification in ('login_rejected', 'connection_limit', 'unavailable'):
            self._fail(classification)
            return

        if attempt_number >= MAX_START_ATTEMPTS:
            self._fail('unavailable')
            return

        next_form = self._next_form_for_attempt2()
        if next_form is _NO_FALLBACK:
            self._fail('unavailable')
            return
        self._begin_attempt('start', attempt_number + 1, next_form)

    def _reconnect_attempt_failed(self):
        self._cancel_start_timer()
        self.player.stop()
        self._log_attempt('start-failure')
        if self._reconnect_delay_index < len(RECONNECT_DELAYS):
            self._schedule_next_reconnect()
        else:
            self._fail('unavailable')

    def _enter_reconnecting(self):
        if self.catchup is not None and self._av_started_at is not None:
            self._catchup_offset_seconds += self.clock() - self._av_started_at
        self.player.stop()
        self._debug_attempt_outcome('dropped')
        self._phase = 'reconnect'
        self._reconnect_delay_index = 0
        self.state = 'reconnecting'
        self.reason = None
        self.on_state('reconnecting', None)
        self._schedule_next_reconnect()

    def _schedule_next_reconnect(self):
        delay = RECONNECT_DELAYS[self._reconnect_delay_index]
        attempt_number = self._reconnect_delay_index + 1
        self._reconnect_delay_index += 1
        self._reconnect_timer = self.scheduler(
            delay, lambda: self._reconnect_fire(attempt_number)
        )

    def _fail(self, reason):
        self._cancel_start_timer()
        self._cancel_reconnect_timer()
        if self.catchup is not None:
            reason = 'catchup_unavailable'
        self.state = 'failed'
        self.reason = reason
        self._alive = False
        self.on_state('failed', reason)

    # -- attempt bookkeeping ----------------------------------------------

    def _begin_attempt(self, phase, attempt_number, form):
        self._phase = phase
        self._attempt_number = attempt_number
        self._form = form
        self._current_url, self._current_headers = self._url_and_headers(form)
        self._av_started_at = None
        self._attempt_start_clock = self.clock()
        self.state = 'reconnecting' if phase == 'reconnect' else 'connecting'
        self.reason = None
        self.logger.debug(
            'Playback attempt {0} phase={1} form={2}'.format(
                attempt_number, phase, form if form else '-'
            )
        )
        if self._current_url is None:
            # Catch-up only: the Channel's mode cannot produce a URL at all
            # (e.g. M3U `default` mode, no catchup-source, non-XC live URL).
            # Not retryable, so fail the Attempt outright without playing.
            self._fail('catchup_unavailable')
            return
        play_url = self.resolver(self._current_url, self._current_headers)
        if play_url != self._current_url:
            self.logger.debug(
                'Playback redirect resolved for attempt {0}'.format(attempt_number)
            )
        mime_type = _mime_type_for(self._current_url)
        self.player.play(play_url, self._current_headers, mime_type=mime_type)
        self._arm_start_timer()
        self.on_state(self.state, None)

    def _initial_form(self):
        if self.snapshot['kind'] != 'xtream':
            return None
        if self.catchup is not None:
            configured = self.snapshot.get('catchup_url_form')
            return configured if configured in ('path', 'query') else 'path'
        return urls.live_form(self.snapshot, self.snapshot.get('allowed_output_formats'))

    def _next_form_for_attempt2(self):
        if self.snapshot['kind'] == 'xtream':
            if self.catchup is not None:
                return 'query' if self._form == 'path' else 'path'
            other = 'm3u8' if self._form == 'ts' else 'ts'
            allowed = self.snapshot.get('allowed_output_formats')
            if other == 'm3u8' and allowed is not None and 'm3u8' not in allowed:
                return _NO_FALLBACK
            return other
        if self.catchup is not None:
            return _NO_FALLBACK
        return self._form

    def _catchup_times(self):
        start = int(self.catchup['start'] + self._catchup_offset_seconds)
        end = self.catchup['end']
        now = int(self.catchup['now'] + (self.clock() - self._catchup_clock_origin))
        return start, end, now

    def _catchup_url_and_headers(self, form):
        snapshot = self.snapshot
        start, end, now = self._catchup_times()
        offset = tz.zone_offset_seconds(snapshot.get('server_timezone'), start)
        if snapshot['kind'] == 'xtream':
            start_local = urls.xtream_local_start(
                start, offset,
                {'catchup_correction_hours': snapshot.get('provider_catchup_correction_hours')},
            )
            duration_seconds = max(0, end - start)
            minutes = max(1, duration_seconds // 60)
            ext = urls.live_form(snapshot, snapshot.get('allowed_output_formats'))
            url = urls.xtream_catchup_url(
                snapshot['xtream_host'], snapshot['xtream_username'],
                snapshot['xtream_password'], snapshot['channel_key'],
                start_local, minutes, form=form, ext=ext,
            )
        else:
            corrected_start = urls.corrected_start(
                start, snapshot,
                {'catchup_correction_hours': snapshot.get('provider_catchup_correction_hours')},
            )
            url = urls.m3u_catchup_url(
                snapshot, corrected_start, end, now, self.catchup.get('catchup_id'),
                local_offset_seconds=offset,
            )
        if url is None:
            return None, None
        headers = dict(snapshot.get('headers') or {})
        if 'User-Agent' not in headers and snapshot.get('user_agent'):
            headers['User-Agent'] = snapshot['user_agent']
        return url, headers

    def _url_and_headers(self, form):
        if self.catchup is not None:
            return self._catchup_url_and_headers(form)
        snapshot = self.snapshot
        if snapshot['kind'] == 'xtream':
            url = urls.xtream_live_url(
                snapshot['xtream_host'], snapshot['xtream_username'],
                snapshot['xtream_password'], snapshot['channel_key'], form,
            )
        else:
            url = urls.m3u_live_url(snapshot)
        headers = dict(snapshot.get('headers') or {})
        if 'User-Agent' not in headers and snapshot.get('user_agent'):
            headers['User-Agent'] = snapshot['user_agent']
        return url, headers

    def _arm_start_timer(self):
        self._start_timer = self.scheduler(START_TIMEOUT_SECONDS, self._on_start_timeout)

    def _cancel_start_timer(self):
        if self._start_timer is not None:
            self._start_timer.cancel()
            self._start_timer = None

    def _cancel_reconnect_timer(self):
        if self._reconnect_timer is not None:
            self._reconnect_timer.cancel()
            self._reconnect_timer = None

    def _max_attempts_for_phase(self):
        return MAX_START_ATTEMPTS if self._phase == 'start' else len(RECONNECT_DELAYS)

    def _log_attempt(self, outcome, probe_status=None):
        elapsed = self.clock() - self._attempt_start_clock
        self.logger.log(
            'Playback attempt {0}/{1} channel={2} provider={3} form={4} '
            'outcome={5} probe={6} elapsed={7:.1f}s'.format(
                self._attempt_number, self._max_attempts_for_phase(),
                self.snapshot['channel_key'], self.snapshot['provider_id'],
                self._form if self._form else '-', outcome,
                probe_status if probe_status is not None else '-', elapsed,
            )
        )

    def _debug_attempt_outcome(self, outcome):
        """Same shape as _log_attempt but at DEBUG level, for outcomes that
        are not the one-INFO-line-per-Attempt the spec calls for (a Drop
        ends the Playing Attempt outside the Attempt sequence, and an abort
        is a user action, not an Attempt outcome)."""
        elapsed = self.clock() - self._attempt_start_clock
        self.logger.debug(
            'Playback attempt {0}/{1} channel={2} provider={3} form={4} '
            'outcome={5} elapsed={6:.1f}s'.format(
                self._attempt_number, self._max_attempts_for_phase(),
                self.snapshot['channel_key'], self.snapshot['provider_id'],
                self._form if self._form else '-', outcome, elapsed,
            )
        )
