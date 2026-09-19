# -*- coding: utf-8 -*-
"""Pure layout/cursor logic for the Guide window (issue #26): no xbmc
imports, so it is exercised directly by tests without the fakes."""
import re
from datetime import datetime, timedelta, timezone

VISIBLE_ROWS = 10
VISIBLE_HOURS = 3

# Same suffix rule as ingest.normalise_name (kept local so this pure module
# has no dependency on the service-side ingest module).
_HD_SUFFIX_RE = re.compile(r'(hd|fhd|uhd|4k)$')
_NON_ALNUM_RE = re.compile(r'[^a-z0-9]+')

_WEEKDAY_ABBR = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')
_MONTH_ABBR = (
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
)

RETENTION_DAYS = 7  # Programme retention is fixed at 7 days elsewhere too.
# HORIZON_DAYS is a fixed guess at how far ahead EPG data is ever available,
# not derived from real per-provider data availability.
HORIZON_DAYS = 7
SKIP_HOURS = 12

_ISO_FORMAT = '%Y-%m-%dT%H:%M:%SZ'


def parse_iso(value):
    return datetime.strptime(value, _ISO_FORMAT)


def format_iso(dt):
    return dt.strftime(_ISO_FORMAT)


def round_down_30(dt):
    """Nearest 30-minute boundary at or before dt."""
    minute = 0 if dt.minute < 30 else 30
    return dt.replace(minute=minute, second=0, microsecond=0)


def utc_to_local(dt, tz=None):
    """Convert a naive UTC datetime to a naive local datetime. `tz` is a
    tzinfo to convert to; defaults to the system local zone."""
    return dt.replace(tzinfo=timezone.utc).astimezone(tz).replace(tzinfo=None)


def round_down_30_local(dt_utc, tz=None):
    """Round a naive UTC datetime down to the local 30-minute boundary at
    or before it, returned as naive UTC. `tz` is a tzinfo to convert to;
    defaults to the system local zone."""
    local = dt_utc.replace(tzinfo=timezone.utc).astimezone(tz)
    rounded_local = round_down_30(local)
    return rounded_local.astimezone(timezone.utc).replace(tzinfo=None)


def viewport_end(viewport_start):
    return viewport_start + timedelta(hours=VISIBLE_HOURS)


def _elapsed_fraction(seg_start, seg_end, now):
    if not (seg_start <= now < seg_end):
        return None
    total = (seg_end - seg_start).total_seconds()
    return (now - seg_start).total_seconds() / total


def cell_layout(programmes, viewport_start, grid_width, no_info_title, now=None):
    """Cells for one channel row's programmes, clipped to the 3-hour
    viewport starting at viewport_start and positioned proportionally to
    duration across grid_width pixels. Every gap in the viewport -- before
    the first overlapping programme, between programmes, after the last
    one, or the whole viewport when the row has none -- is filled with a
    "No information" filler cell (start/end clipped to the viewport,
    'filler': True) so the row has contiguous cells to navigate over.
    Real cells carry the programme's actual (unclipped) start/end and
    'filler': False. Programmes are processed in start order; where two
    overlap, the later-starting one takes precedence (matching Kodi's own
    EPG behaviour) and the earlier real cell is truncated -- or dropped
    entirely if that would leave it empty or sub-pixel -- to this
    programme's start. 'progress' is the fraction of the cell's *visible*
    (viewport- and truncation-clipped) span that has elapsed at `now`, so
    the progress bar always ends exactly at the now-line."""
    end = viewport_end(viewport_start)
    px_per_min = grid_width / float(VISIBLE_HOURS * 60)

    def _rect(seg_start, seg_end):
        x = (seg_start - viewport_start).total_seconds() / 60.0 * px_per_min
        width = max(1, (seg_end - seg_start).total_seconds() / 60.0 * px_per_min)
        return int(round(x)), int(round(width))

    def _progress(seg_start, seg_end):
        if now is None:
            return None
        return _elapsed_fraction(seg_start, seg_end, now)

    def _filler(seg_start, seg_end):
        x, width = _rect(seg_start, seg_end)
        return {
            'start': seg_start, 'end': seg_end, 'title': no_info_title,
            'description': '', 'x': x, 'width': width, 'filler': True, 'progress': None,
        }

    cells = []
    cursor = viewport_start
    prev_seg_start = None
    for programme in sorted(programmes, key=lambda p: p['start']):
        if programme['end'] <= viewport_start or programme['start'] >= end:
            continue
        seg_start = max(programme['start'], viewport_start)
        seg_end = min(programme['end'], end)
        if seg_start < cursor and cells and not cells[-1]['filler']:
            prev = cells[-1]
            raw_width = (seg_start - prev_seg_start).total_seconds() / 60.0 * px_per_min
            if seg_start <= prev_seg_start or raw_width < 1:
                cells.pop()
            else:
                prev['end'] = seg_start
                prev['x'], prev['width'] = _rect(prev_seg_start, seg_start)
                prev['progress'] = _progress(prev_seg_start, seg_start)
            cursor = seg_start
        if seg_start > cursor:
            cells.append(_filler(cursor, seg_start))
        x, width = _rect(seg_start, seg_end)
        cells.append({
            'start': programme['start'],
            'end': programme['end'],
            'title': programme['title'],
            'description': programme.get('description', ''),
            'x': x,
            'width': width,
            'filler': False,
            'progress': _progress(seg_start, seg_end),
        })
        cursor = seg_end
        prev_seg_start = seg_start
    if cursor < end:
        cells.append(_filler(cursor, end))
    return cells


def cell_progress(cell, now, viewport_start, viewport_end):
    """Progress fraction (0..1) for a cell_layout cell at `now`, matching
    cell_layout's own progress rule: None when now is outside the
    viewport-clipped [start, end) or the cell is a filler."""
    if cell['filler']:
        return None
    seg_start = max(cell['start'], viewport_start)
    seg_end = min(cell['end'], viewport_end)
    return _elapsed_fraction(seg_start, seg_end, now)


def header_now_slot(viewport_start, now):
    """Header slot index (0..5, 30-minute slots) containing now within the
    3-hour viewport starting at viewport_start, or None when now is
    outside the viewport."""
    end = viewport_end(viewport_start)
    if now < viewport_start or now >= end:
        return None
    minutes = (now - viewport_start).total_seconds() / 60.0
    return int(minutes // 30)


def resolve_cursor(cells, axis_time):
    """The cell (from a cell_layout-produced list) containing axis_time; if
    none matches exactly (e.g. a gap between programmes), fall back to
    whichever cell is nearest. cells must be non-empty."""
    for cell in cells:
        if cell['start'] <= axis_time < cell['end']:
            return cell

    def _distance(cell):
        if axis_time < cell['start']:
            return cell['start'] - axis_time
        return axis_time - cell['end']

    return min(cells, key=_distance)


def move_cursor_vertical(target_cells, axis_time):
    """Cell (from a cell_layout list) on the target row containing the
    travel-axis time, or None if the target row has no cells at all. Never
    moves the travel axis itself -- callers keep it unchanged."""
    if not target_cells:
        return None
    return resolve_cursor(target_cells, axis_time)


def needs_viewport_jump(target_start, viewport_start):
    return target_start < viewport_start or target_start >= viewport_end(viewport_start)


def clamp_viewport(viewport_start, now, tz=None):
    """Clamp viewport_start to the EPG data range: no earlier than the
    retention floor, no later than a fixed horizon ceiling (rule D)."""
    floor = round_down_30_local(now - timedelta(days=RETENTION_DAYS), tz)
    ceiling = round_down_30_local(now + timedelta(days=HORIZON_DAYS), tz) - timedelta(hours=VISIBLE_HOURS)
    if viewport_start < floor:
        return floor
    if viewport_start > ceiling:
        return ceiling
    return viewport_start


def scroll_viewport(viewport_start, direction, floor, ceiling):
    """New viewport_start after scrolling one 30-minute slot in `direction`
    (-1 or +1), clamped to floor/ceiling. Equal to viewport_start when
    already at the clamped bound in that direction."""
    slot = timedelta(minutes=30)
    new_start = viewport_start + slot if direction > 0 else viewport_start - slot
    if new_start < floor:
        return floor
    if new_start > ceiling:
        return ceiling
    return new_start


def compute_top_row(top_row, selected, visible_rows=VISIBLE_ROWS):
    """Mirror Kodi's own "keep selection in view" scrolling: only ever
    shifts by the minimum needed to bring `selected` back into view."""
    if selected < top_row:
        return selected
    if selected >= top_row + visible_rows:
        return selected - visible_rows + 1
    return top_row


def viewport_changed(prev_top_row, new_top_row, prev_viewport_start, new_viewport_start):
    """Whether a full relayout (hide -> update -> flip -> show) is needed:
    gated on the list's top row or the time viewport actually changing,
    never on an in-viewport cursor move."""
    return prev_top_row != new_top_row or prev_viewport_start != new_viewport_start


def panel_rows(providers, groups, collapsed, all_label, favourites_label):
    """Rows for the Groups panel: All channels, Favourites, then one
    section per provider (a header row, followed by that provider's
    groups unless the header's provider_id is in `collapsed`). A
    provider with no groups still gets a header row; disabled providers
    (an 'enabled' key present and falsy) are skipped entirely."""
    rows = [
        {'kind': 'all', 'label': all_label, 'provider_id': None, 'group_id': None, 'collapsed': False},
        {'kind': 'favourites', 'label': favourites_label, 'provider_id': None, 'group_id': None,
         'collapsed': False},
    ]
    for provider in providers:
        if not provider.get('enabled', True):
            continue
        provider_id = provider['id']
        provider_collapsed = provider_id in collapsed
        rows.append({
            'kind': 'provider', 'label': provider['name'], 'provider_id': provider_id,
            'group_id': None, 'collapsed': provider_collapsed,
        })
        if provider_collapsed:
            continue
        rows.extend(
            {'kind': 'group', 'label': group['name'], 'provider_id': group['provider_id'],
             'group_id': group['id'], 'collapsed': False}
            for group in groups if group['provider_id'] == provider_id
        )
    return rows


def picked_filter(row):
    """Filter state {'provider_id','group_id','favourites'} for a picked
    panel row, or None for a 'provider' header (not a filter)."""
    if row['kind'] == 'all':
        return {'provider_id': None, 'group_id': None, 'favourites': False}
    if row['kind'] == 'favourites':
        return {'provider_id': None, 'group_id': None, 'favourites': True}
    if row['kind'] == 'group':
        return {'provider_id': row['provider_id'], 'group_id': row['group_id'], 'favourites': False}
    return None


def panel_selected_index(rows, provider_id, group_id, favourites):
    """Index of the panel row matching the current filter, else 0."""
    for index, row in enumerate(rows):
        if favourites:
            if row['kind'] == 'favourites':
                return index
        elif group_id is not None:
            if row['kind'] == 'group' and row['group_id'] == group_id:
                return index
        elif provider_id is None:
            if row['kind'] == 'all':
                return index
    return 0


def filter_label(group_id, favourites, groups, all_label, favourites_label,
                  provider_id=None, providers=()):
    """Header text for the active filter; an unknown group_id or
    provider_id falls back to all_label."""
    if favourites:
        return favourites_label
    if group_id is not None:
        for group in groups:
            if group['id'] == group_id:
                return group['name']
        return all_label
    if provider_id is not None:
        for provider in providers:
            if provider['id'] == provider_id:
                return provider['name']
        return all_label
    return all_label


def channel_panel_rows(channel_rows, playing_key):
    """Rows for the panel's channel list (issue #64): one dict per channel
    row, in the same order, with {'id','number','name','logo','playing'}.
    `playing_key` is the (provider_id, channel_key) pair of the currently
    playing channel, or None."""
    return [
        {
            'id': row['id'], 'number': row['number'], 'name': row['name'],
            'logo': row.get('logo_url') or '',
            'playing': (row['provider_id'], row['channel_key']) == playing_key,
        }
        for row in channel_rows
    ]


def initial_cursor_index(rows, focus_channel_id):
    """Index of the row whose 'id' == focus_channel_id, else 0."""
    if focus_channel_id is not None:
        for index, row in enumerate(rows):
            if row['id'] == focus_channel_id:
                return index
    return 0


ZONES = ('rail', 'panel', 'column', 'grid')

_ZONE_TRANSITIONS = {
    ('rail', 'left'): 'rail',
    ('rail', 'right'): 'panel',
    ('panel', 'left'): 'rail',
    ('panel', 'right'): 'column',
    ('column', 'left'): 'panel',
    ('column', 'right'): 'grid',
    ('grid', 'left'): 'column',
    ('grid', 'right'): 'grid',
}


def zone_transition(zone, action):
    """Next zone for Left/Right from `zone`: rail<->panel<->column<->grid,
    with rail and grid staying put at their ends."""
    if zone not in ZONES or action not in ('left', 'right'):
        raise ValueError("invalid zone/action: %r/%r" % (zone, action))
    return _ZONE_TRANSITIONS[(zone, action)]


def back_target(zone):
    """Back's next state: 'column' (from 'grid', un-highlighting the
    cursor without closing) or 'close' (close the window)."""
    if zone not in ZONES:
        raise ValueError("invalid zone: %r" % (zone,))
    return 'column' if zone == 'grid' else 'close'


def is_hd_name(name):
    """True when the Normalised Name suffix rule (ingest.normalise_name)
    strips an HD/FHD/UHD/4K suffix off `name`."""
    lowered = (name or '').lower()
    stripped = _NON_ALNUM_RE.sub('', lowered)
    return bool(_HD_SUFFIX_RE.search(stripped))


def format_duration_short(total_seconds):
    """"2h 30m" / "45m" / "2h" for a duration in seconds."""
    total_minutes = int(round(total_seconds / 60.0))
    hours, minutes = divmod(total_minutes, 60)
    if hours and minutes:
        return '%dh %dm' % (hours, minutes)
    if hours:
        return '%dh' % hours
    return '%dm' % minutes


def strip_values(programmes, at_time, now, no_info_title, tz=None):
    """Programme detail strip values (issue #54) for the programme covering
    `at_time`: title, times with duration, progress 0-100, remaining
    duration text (only when airing at `now`), description, live/has_programme
    flags. `progress` is 0 for a programme that has not started at `now` and
    100 for one that has already ended, so a static (non-live) strip still
    renders a sensible bar position."""
    programme = None
    for candidate in programmes:
        if candidate['start'] <= at_time < candidate['end']:
            programme = candidate
            break

    if programme is None:
        return {
            'title': no_info_title, 'times': '', 'progress': 0, 'remaining': '',
            'description': '', 'live': False, 'has_programme': False, 'icon': '',
        }

    start_local = utc_to_local(programme['start'], tz)
    end_local = utc_to_local(programme['end'], tz)
    duration = format_duration_short((programme['end'] - programme['start']).total_seconds())
    times = '%s - %s (%s)' % (start_local.strftime('%H:%M'), end_local.strftime('%H:%M'), duration)

    live = programme['start'] <= now < programme['end']
    if live:
        total = (programme['end'] - programme['start']).total_seconds()
        elapsed = (now - programme['start']).total_seconds()
        progress = int(round(max(0, min(total, elapsed)) / total * 100)) if total > 0 else 0
        remaining = format_duration_short((programme['end'] - now).total_seconds())
    else:
        progress = 100 if now >= programme['end'] else 0
        remaining = ''

    return {
        'title': programme['title'], 'times': times, 'progress': progress,
        'remaining': remaining, 'description': programme.get('description') or '',
        'live': live, 'has_programme': True, 'icon': programme.get('icon') or '',
    }


def cell_time_range(cell, tz=None):
    """Local "HH:MM - HH:MM" for a cell_layout cell's programme start/end,
    or '' for a filler cell."""
    if cell['filler']:
        return ''
    start_local = utc_to_local(cell['start'], tz)
    end_local = utc_to_local(cell['end'], tz)
    return '%s - %s' % (start_local.strftime('%H:%M'), end_local.strftime('%H:%M'))


def visible_rows(available_height, row_height):
    """Number of whole rows that fit in available_height, at least 1."""
    return max(1, int(available_height // row_height))


def _clamp_byte(value):
    return max(0, min(255, value))


def dim_color(argb_hex, factor):
    """`argb_hex` (an "AARRGGBB" string) with its R/G/B channels scaled by
    `factor` and clamped to 0-255; alpha is kept as-is."""
    alpha = argb_hex[0:2]
    r = _clamp_byte(int(round(int(argb_hex[2:4], 16) * factor)))
    g = _clamp_byte(int(round(int(argb_hex[4:6], 16) * factor)))
    b = _clamp_byte(int(round(int(argb_hex[6:8], 16) * factor)))
    return '%s%02X%02X%02X' % (alpha, r, g, b)


# String ids for the remote-hint bar's verb fragments (issue #56); kept as
# constants here so hint_text stays a pure function of `get_string`.
STR_HINT_WATCH = 32131
STR_HINT_GROUPS = 32132
STR_HINT_TIME = 32133
STR_HINT_DETAILS = 32134
STR_HINT_FAVOURITE = 32135
STR_HINT_LONG_PRESS = 32136
STR_HINT_OPEN = 32137
STR_HINT_CHANNELS = 32138


def hint_slots(zone, get_string, panel_mode='channels'):
    """Remote-hint bar slots for the given focus zone: up to five dicts of
    {'icon', 'key', 'verb'}, one per key this zone's Left/Right/OK/Info/
    long-press actually does. For zone == 'panel', `panel_mode` ('channels'
    or 'groups') picks between "OK Channels" and "OK Groups"."""
    if zone == 'column':
        return [
            {'icon': u'OK', 'key': u'', 'verb': get_string(STR_HINT_WATCH), 'texture': u'hint_ok.png'},
            {'icon': u'←', 'key': u'', 'verb': get_string(STR_HINT_GROUPS), 'texture': u'hint_left.png'},
            {'icon': u'→', 'key': u'', 'verb': get_string(STR_HINT_TIME), 'texture': u'hint_right.png'},
            {'icon': u'i', 'key': u'Info', 'verb': get_string(STR_HINT_DETAILS), 'texture': u'hint_info.png'},
            {'icon': u'★', 'key': get_string(STR_HINT_LONG_PRESS), 'verb': get_string(STR_HINT_FAVOURITE), 'texture': u'hint_star.png'},
        ]
    if zone == 'grid':
        return [
            {'icon': u'OK', 'key': u'', 'verb': get_string(STR_HINT_WATCH), 'texture': u'hint_ok.png'},
            {'icon': u'↔', 'key': u'', 'verb': get_string(STR_HINT_TIME), 'texture': u'hint_lr.png'},
            {'icon': u'i', 'key': u'Info', 'verb': get_string(STR_HINT_DETAILS), 'texture': u'hint_info.png'},
            {'icon': u'★', 'key': get_string(STR_HINT_LONG_PRESS), 'verb': get_string(STR_HINT_FAVOURITE), 'texture': u'hint_star.png'},
        ]
    if zone == 'rail':
        return [{'icon': u'OK', 'key': u'', 'verb': get_string(STR_HINT_OPEN), 'texture': u'hint_ok.png'}]
    if zone == 'panel':
        verb = STR_HINT_GROUPS if panel_mode == 'groups' else STR_HINT_CHANNELS
        return [{'icon': u'OK', 'key': u'', 'verb': get_string(verb), 'texture': u'hint_ok.png'}]
    return []


def hint_text(zone, get_string, panel_mode='channels'):
    """Remote-hint bar text for the given focus zone, built from
    hint_slots: each slot renders as "<key> <verb>", or "<icon> <verb>"
    when the slot has no key (an arrow-only hint), joined with ' · '."""
    fragments = [
        u'%s %s' % (slot['key'] or slot['icon'], slot['verb'])
        for slot in hint_slots(zone, get_string, panel_mode)
    ]
    return u' · '.join(fragments)


def date_label(at_time, now, today_label, tz=None):
    """"Today, 18 Sep" when at_time's local date matches now's local date,
    else "Thu, 18 Sep"."""
    local_at = utc_to_local(at_time, tz)
    local_now = utc_to_local(now, tz)
    day_month = '%d %s' % (local_at.day, _MONTH_ABBR[local_at.month - 1])
    if local_at.date() == local_now.date():
        return '%s, %s' % (today_label, day_month)
    return '%s, %s' % (_WEEKDAY_ABBR[local_at.weekday()], day_month)
