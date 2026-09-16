# -*- coding: utf-8 -*-
"""Pure layout/cursor logic for the Guide window (issue #26): no xbmc
imports, so it is exercised directly by tests without the fakes."""
from datetime import datetime, timedelta

VISIBLE_ROWS = 10
VISIBLE_HOURS = 3

_ISO_FORMAT = '%Y-%m-%dT%H:%M:%SZ'


def parse_iso(value):
    return datetime.strptime(value, _ISO_FORMAT)


def format_iso(dt):
    return dt.strftime(_ISO_FORMAT)


def round_down_30(dt):
    """Nearest 30-minute boundary at or before dt."""
    minute = 0 if dt.minute < 30 else 30
    return dt.replace(minute=minute, second=0, microsecond=0)


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


def move_cursor_vertical(target_programmes, cursor_time):
    """Start time of the programme containing cursor_time on the target
    row, or None if the target row has no programme at that time."""
    current = programme_at(target_programmes, cursor_time)
    return current['start'] if current else None


def needs_viewport_jump(target_start, viewport_start):
    return target_start < viewport_start or target_start >= viewport_end(viewport_start)


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
