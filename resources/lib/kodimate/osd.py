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
    datetime 'start'/'end'/'title'; either may be None. When several
    programmes cover `now` (overlapping EPG data), the later-starting one
    takes precedence, matching Kodi's own EPG behaviour."""
    now_prog = None
    for programme in programmes:
        if programme['start'] <= now < programme['end']:
            now_prog = programme

    next_prog = None
    if now_prog is not None:
        for programme in programmes:
            if programme['start'] > now_prog['start'] and programme['start'] >= now:
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


def catchup_progress_fraction(start, end, offset_seconds, player_seconds):
    """Fraction of a catch-up programme elapsed, clamped to 0..1."""
    total = end - start
    if total <= 0:
        return 0.0
    elapsed = offset_seconds + player_seconds
    return max(0.0, min(1.0, elapsed / total))


def format_times(start, end, tz=None):
    """'HH:MM–HH:MM' (en dash) in local time."""
    local_start = guide.utc_to_local(start, tz)
    local_end = guide.utc_to_local(end, tz)
    return u'%s–%s' % (local_start.strftime('%H:%M'), local_end.strftime('%H:%M'))


def neighbour_programme(programmes, current, direction):
    """The programme adjacent to `current` in `programmes` (matched by
    'start', ordered by 'start') in `direction` (-1 previous, +1 next);
    `current` itself if there is no such neighbour (clamps at the ends of
    the loaded list, or `current`/`programmes` is empty)."""
    if current is None or not programmes:
        return current
    ordered = sorted(programmes, key=lambda p: p['start'])
    index = None
    for i, programme in enumerate(ordered):
        if programme['start'] == current['start']:
            index = i
            break
    if index is None:
        return current
    new_index = index + direction
    if 0 <= new_index < len(ordered):
        return ordered[new_index]
    return current


def _format_hms(seconds):
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return u'%d:%02d:%02d' % (hours, minutes, secs)


def format_position(position_seconds, duration_seconds):
    """'H:MM:SS / H:MM:SS' (player position / requested duration)."""
    return u'%s / %s' % (_format_hms(position_seconds), _format_hms(duration_seconds))


def back_layer(list_open, bar_visible):
    """Which layer a Back press should act on."""
    if list_open:
        return 'close_list'
    if bar_visible:
        return 'hide_bar'
    return 'leave'


_CHANNEL_LABELS = {1: '1.0', 2: '2.0', 6: '5.1', 8: '7.1'}


def format_stream_info(width, height, video_codec, fps, audio_codec, audio_channels):
    """Dict with keys 'res', 'fps', 'vcodec', 'audio', each a short display
    string derived independently from the matching raw Kodi infolabel (empty
    string when that particular input is unavailable/unparseable)."""
    try:
        width_n = int(str(width).replace(',', '').strip())
        height_n = int(str(height).replace(',', '').strip())
    except ValueError:
        res = ''
    else:
        if width_n <= 0 or height_n <= 0:
            res = ''
        elif height_n >= 2000 or width_n >= 3800:
            res = '4K'
        elif height_n >= 1000:
            res = 'FHD'
        elif height_n >= 700:
            res = 'HD'
        else:
            res = 'SD'

    try:
        fps_n = round(float(fps))
    except (TypeError, ValueError):
        fps_text = ''
    else:
        fps_text = u'%dfps' % fps_n if fps_n > 0 else ''

    vcodec = video_codec.upper() if video_codec else ''

    try:
        channels_n = int(audio_channels)
    except (TypeError, ValueError):
        channels_n = None
    channels_text = _CHANNEL_LABELS.get(channels_n, u'%dch' % channels_n) if channels_n is not None else None

    audio_bits = [bit for bit in (audio_codec.upper() if audio_codec else None, channels_text) if bit]
    audio = u' '.join(audio_bits)

    return {'res': res, 'fps': fps_text, 'vcodec': vcodec, 'audio': audio}
