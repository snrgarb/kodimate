# -*- coding: utf-8 -*-
"""Pure seek-stepping logic reproducing Kodi's own seek-step behaviour
(videoplayer.seeksteps / videoplayer.seekdelay settings). No xbmc imports.
"""
import json

DEFAULT_STEPS = [-600, -300, -180, -60, -30, -10, 10, 30, 60, 180, 300, 600]
DEFAULT_DELAY_MS = 750


def _read_setting(execute_jsonrpc, setting, default):
    try:
        raw = execute_jsonrpc(json.dumps({
            'jsonrpc': '2.0', 'id': 1, 'method': 'Settings.GetSettingValue',
            'params': {'setting': setting},
        }))
        result = json.loads(raw)
        return result['result']['value']
    except Exception:
        return default


def read_seek_settings(execute_jsonrpc):
    """(steps, delay_ms) read from Kodi's videoplayer.seeksteps/seekdelay via
    the injected `execute_jsonrpc` (xbmc.executeJSONRPC), falling back to
    Kodi's own defaults on any failure or malformed result."""
    steps = _read_setting(execute_jsonrpc, 'videoplayer.seeksteps', DEFAULT_STEPS)
    delay_ms = _read_setting(execute_jsonrpc, 'videoplayer.seekdelay', DEFAULT_DELAY_MS)
    if not isinstance(steps, list) or not steps:
        steps = DEFAULT_STEPS
    if not isinstance(delay_ms, int):
        delay_ms = DEFAULT_DELAY_MS
    return steps, delay_ms


def format_step(seconds):
    """'+30s' / '-1m' style label for a pending step; '' for no step."""
    if not seconds:
        return u''
    sign = u'-' if seconds < 0 else u'+'
    magnitude = abs(seconds)
    if magnitude % 60 == 0:
        return u'%s%dm' % (sign, magnitude // 60)
    return u'%s%ds' % (sign, magnitude)


class SeekStepper(object):
    """Accumulates repeated Left/Right presses into Kodi's seek-step
    sequence: a press in one direction advances to the next larger step on
    that side (capped at the largest), a press in the opposite direction
    backs off one step (reaching 0 cancels)."""

    def __init__(self, steps):
        self._negative = sorted((s for s in steps if s < 0), reverse=True)  # -10, -30, ...
        self._positive = sorted(s for s in steps if s > 0)  # 10, 30, ...
        self._index = 0  # 0 = no pending step; >0 index into _positive; <0 into _negative

    @property
    def pending(self):
        if self._index > 0:
            return self._positive[self._index - 1]
        if self._index < 0:
            return self._negative[-self._index - 1]
        return 0

    def press(self, direction):
        """direction: -1 (left/back) or +1 (right/forward). Returns the new
        pending step in seconds."""
        if direction > 0:
            if self._index < 0:
                self._index += 1
            elif self._index < len(self._positive):
                self._index += 1
        else:
            if self._index > 0:
                self._index -= 1
            elif -self._index < len(self._negative):
                self._index -= 1
        return self.pending

    def press_largest(self, direction):
        """Jump straight to the largest step in `direction` (big-step
        actions). Returns the new pending step in seconds."""
        if direction > 0:
            self._index = len(self._positive)
        else:
            self._index = -len(self._negative)
        return self.pending

    def reset(self):
        self._index = 0
