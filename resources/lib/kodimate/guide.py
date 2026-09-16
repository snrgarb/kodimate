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
    duration across grid_width pixels. A row with no programme overlapping
    the viewport yields a single "No information" cell spanning the full
    width."""
    end = viewport_end(viewport_start)
    px_per_min = grid_width / float(VISIBLE_HOURS * 60)
    cells = []
    for programme in programmes:
        if programme['end'] <= viewport_start or programme['start'] >= end:
            continue
        seg_start = max(programme['start'], viewport_start)
        seg_end = min(programme['end'], end)
        x = (seg_start - viewport_start).total_seconds() / 60.0 * px_per_min
        width = max(1, (seg_end - seg_start).total_seconds() / 60.0 * px_per_min)
        cells.append({
            'start': programme['start'],
            'end': programme['end'],
            'title': programme['title'],
            'x': int(round(x)),
            'width': int(round(width)),
        })
    if not cells:
        cells.append({
            'start': viewport_start,
            'end': end,
            'title': no_info_title,
            'x': 0,
            'width': int(round(grid_width)),
        })
    return cells


def programme_at(programmes, t):
    for programme in programmes:
        if programme['start'] <= t < programme['end']:
            return programme
    return None


def move_cursor_horizontal(programmes, cursor_time, direction):
    """Start time of the adjacent programme in `direction` (-1 or +1) from
    the one containing cursor_time, or None if there is no programme in
    that direction (including when cursor_time isn't inside any)."""
    current = programme_at(programmes, cursor_time)
    if current is None:
        return None
    index = programmes.index(current)
    target_index = index + direction
    if target_index < 0 or target_index >= len(programmes):
        return None
    return programmes[target_index]['start']


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


def scroll_for_target(viewport_start, target_start, target_end, direction, tz, floor, ceiling):
    """New viewport_start to bring an off-screen target programme's near
    edge into view (30-minute aligned, capped at one page per call, then
    clamped to floor/ceiling), or None if the target already overlaps the
    current viewport."""
    end = viewport_end(viewport_start)
    if target_end > viewport_start and target_start < end:
        return None
    page = timedelta(hours=VISIBLE_HOURS)
    rounded = round_down_30_local(target_start, tz)
    if direction > 0:
        new_start = min(rounded, viewport_start + page)
    else:
        new_start = max(rounded, viewport_start - page)
    if new_start < floor:
        new_start = floor
    if new_start > ceiling:
        new_start = ceiling
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
