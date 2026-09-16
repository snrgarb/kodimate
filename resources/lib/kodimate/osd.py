# -*- coding: utf-8 -*-
"""Pure OSD logic for playback (issue #27): no xbmc imports, exercised
directly by tests without the fakes.

Real Kodi's xbmcgui module does not export digit-entry action-id constants
(only xbmcgui.ACTION_MOVE_LEFT/RIGHT/UP/DOWN, ACTION_NAV_BACK,
ACTION_PREVIOUS_MENU and a handful of others genuinely exist there);
defined here directly from Kodi's ActionIDs.h numeric values instead, same
convention as windows/guide.py.
"""
from . import guide

_KEYBOARD_DIGIT_BASE = 0xF030  # 0xF030..0xF039 -> 0..9
_ACTION_REMOTE_0 = 58  # ACTION_REMOTE_0..9 -> 58..67
_ACTION_REMOTE_9 = 67
_ACTION_JUMP_SMS2 = 142  # ACTION_JUMP_SMS2..9 -> 142..149 -> digits 2..9
_ACTION_JUMP_SMS9 = 149


def digit_from_action_id(action_id):
    """The digit (0-9) a key-press action id represents, or None."""
    if _KEYBOARD_DIGIT_BASE <= action_id <= _KEYBOARD_DIGIT_BASE + 9:
        return action_id - _KEYBOARD_DIGIT_BASE
    if _ACTION_REMOTE_0 <= action_id <= _ACTION_REMOTE_9:
        return action_id - _ACTION_REMOTE_0
    if _ACTION_JUMP_SMS2 <= action_id <= _ACTION_JUMP_SMS9:
        return action_id - _ACTION_JUMP_SMS2 + 2
    return None


def resolve_number(rows, number):
    """The first row (from channels.list_channels, already in list order)
    whose 'number' matches, or None. Duplicates resolve to the first in
    list order."""
    for row in rows:
        if row['number'] == number:
            return row
    return None


def now_next(programmes, now):
    """(now_prog, next_prog) from a sorted list of programme dicts with
    datetime 'start'/'end'/'title'; either may be None."""
    now_prog = None
    for programme in programmes:
        if programme['start'] <= now < programme['end']:
            now_prog = programme
            break

    next_prog = None
    if now_prog is not None:
        for programme in programmes:
            if programme['start'] >= now_prog['end']:
                next_prog = programme
                break
    else:
        for programme in programmes:
            if programme['start'] > now:
                next_prog = programme
                break
    return now_prog, next_prog


def progress_fraction(programme, now):
    """Fraction of `programme` elapsed at `now`, clamped to 0..1."""
    total = (programme['end'] - programme['start']).total_seconds()
    if total <= 0:
        return 0.0
    elapsed = (now - programme['start']).total_seconds()
    return max(0.0, min(1.0, elapsed / total))


def format_times(start, end, tz=None):
    """'HH:MM–HH:MM' (en dash) in local time."""
    local_start = guide.utc_to_local(start, tz)
    local_end = guide.utc_to_local(end, tz)
    return u'%s–%s' % (local_start.strftime('%H:%M'), local_end.strftime('%H:%M'))


def back_layer(list_open, bar_visible):
    """Which layer a Back press should act on."""
    if list_open:
        return 'close_list'
    if bar_visible:
        return 'hide_bar'
    return 'leave'
