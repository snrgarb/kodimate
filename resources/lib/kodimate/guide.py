# -*- coding: utf-8 -*-
"""Pure layout/cursor logic for the Guide window (issue #26): no xbmc
imports, so it is exercised directly by tests without the fakes."""
from datetime import datetime, timedelta, timezone

VISIBLE_ROWS = 10
VISIBLE_HOURS = 3

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


def cell_layout(programmes, viewport_start, grid_width, no_info_title):
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
    programme's start."""
    end = viewport_end(viewport_start)
    px_per_min = grid_width / float(VISIBLE_HOURS * 60)

    def _rect(seg_start, seg_end):
        x = (seg_start - viewport_start).total_seconds() / 60.0 * px_per_min
        width = max(1, (seg_end - seg_start).total_seconds() / 60.0 * px_per_min)
        return int(round(x)), int(round(width))

    def _filler(seg_start, seg_end):
        x, width = _rect(seg_start, seg_end)
        return {
            'start': seg_start, 'end': seg_end, 'title': no_info_title,
            'description': '', 'x': x, 'width': width, 'filler': True,
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
        })
        cursor = seg_end
        prev_seg_start = seg_start
    if cursor < end:
        cells.append(_filler(cursor, end))
    return cells


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
