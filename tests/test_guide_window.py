import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import pytest

from kodimate import autoplay, channels, db, guide
from kodimate.windows import guide as win_guide
from kodimate.windows.guide import GuideWindow, CHANNEL_LIST_ID
import xbmc
import xbmcaddon
import xbmcgui

_SKIN_XML = os.path.join(
    os.path.dirname(__file__), '..', 'resources', 'skins', 'Main', '1080i', 'script-kodimate-guide.xml',
)


@pytest.fixture(autouse=True)
def _clear_db_generation():
    xbmcgui._window_properties.pop(10000, None)
    yield
    xbmcgui._window_properties.pop(10000, None)


def _bump_generation(value):
    xbmcgui.Window(10000).setProperty('script.kodimate.db_generation', str(value))


def _notify_refreshed(window):
    window._watcher.onNotification('script.kodimate', 'Other.refreshed', '{}')


def _conn(tmp_path):
    return db.open_db(str(tmp_path / "kodimate.db"))


def _provider(conn, name="P1"):
    return conn.execute(
        "INSERT INTO provider (kind, name, enabled, sort_order) VALUES ('m3u', ?, 1, 0)", (name,)
    ).lastrowid


def _channel(conn, provider_id, channel_key, name, position, epg_channel_id=None,
             stream_url='http://x/live/u/p/1.ts'):
    cursor = conn.execute(
        "INSERT INTO channel (provider_id, channel_key, name, normalised_name, stream_url, "
        "position, epg_channel_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (provider_id, channel_key, name, name.lower(), stream_url, position, epg_channel_id),
    )
    return cursor.lastrowid


def _epg_source(conn, provider_id):
    return conn.execute(
        "INSERT INTO epg_source (provider_id, url) VALUES (?, 'http://epg')", (provider_id,)
    ).lastrowid


def _programme(conn, epg_source_id, xmltv_channel_id, start, end, title, description=None):
    conn.execute(
        "INSERT INTO programme (epg_source_id, xmltv_channel_id, start, end, title, description) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (epg_source_id, xmltv_channel_id, start, end, title, description),
    )


def _window(conn):
    window = GuideWindow('script-kodimate-guide.xml', '/addon', 'Main', '1080i', conn=conn)
    window.onInit()
    return window


def test_header_shows_local_time_not_utc(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)

        class _LocalGuideWindow(GuideWindow):
            _tz = timezone(timedelta(hours=9, minutes=30))

        window = _LocalGuideWindow('script-kodimate-guide.xml', '/addon', 'Main', '1080i', conn=conn)
        window.onInit()
        expected = guide.utc_to_local(window._viewport_start, tz=window._tz)
        assert window.getProperty('guide_header0') == expected.strftime('%H:%M')
    finally:
        conn.close()


def test_guide_shows_channels_in_native_list(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        _channel(conn, pid, "b", "Beta", 1)
        window = _window(conn)
        labels = [item.getLabel() for item in window.getControl(CHANNEL_LIST_ID)._items]
        assert labels == ["Alpha", "Beta"]
    finally:
        conn.close()


def test_channel_with_no_programmes_shows_no_information_cell(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)
        cells = window._row_cells[0]
        assert len(cells) == 1
        assert cells[0]['title'] == 'String 32083'
    finally:
        conn.close()


def test_cell_proportional_to_duration(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        cid = _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        eid = _epg_source(conn, pid)
        window = _window(conn)
        viewport_start = window._viewport_start
        _programme(conn, eid, "x1", guide.format_iso(viewport_start),
                   guide.format_iso(viewport_start + timedelta(hours=1)), "Show A")
        window._load_programmes()
        window._relayout()
        cells = window._row_cells[0]
        assert cells[0]['title'] == 'Show A'
        assert cells[0]['width'] == _third_of_grid(1010)
        # The remaining two-thirds of the viewport is a filler cell.
        assert cells[1]['filler'] is True
    finally:
        conn.close()


def _third_of_grid(grid_width):
    # 1-hour cell out of a 3-hour viewport is one third of the grid.
    return int(round(grid_width / 3.0))


def test_left_right_move_cursor_between_programmes(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        eid = _epg_source(conn, pid)
        window = _window(conn)
        viewport_start = window._viewport_start
        _programme(conn, eid, "x1", guide.format_iso(viewport_start),
                   guide.format_iso(viewport_start + timedelta(hours=1)), "Show A")
        _programme(conn, eid, "x1", guide.format_iso(viewport_start + timedelta(hours=1)),
                   guide.format_iso(viewport_start + timedelta(hours=2)), "Show B")
        window._load_programmes()
        window._relayout()

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))  # column -> grid, cell 0
        assert window._zone == 'grid'
        assert window._cursor_time == viewport_start

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))
        assert window._cursor_time == viewport_start + timedelta(hours=1)

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))
        assert window._cursor_time == viewport_start
    finally:
        conn.close()


def test_left_from_leftmost_cell_scrolls_viewport_one_slot(tmp_path):
    # Bug fix: Left/Right must always move (scrolling the viewport by one
    # slot at the cell edge) rather than doing nothing just because there
    # happens to be no earlier programme in the data. (issue #46 follow-up:
    # Left in the grid zone always moves the cursor/scrolls time -- the
    # grid<->column edge is Back, not Left; see test_back_from_grid_moves_to_column.)
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        eid = _epg_source(conn, pid)
        window = _window(conn)
        viewport_start = window._viewport_start
        _programme(conn, eid, "x1", guide.format_iso(viewport_start),
                   guide.format_iso(viewport_start + timedelta(hours=1)), "Show A")
        window._load_programmes()
        window._relayout()
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))  # column -> grid, cell 0

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))

        assert window._zone == 'grid'
        assert window._viewport_start == viewport_start - timedelta(minutes=30)
        assert window._cursor_time == window._viewport_start
    finally:
        conn.close()


def test_up_down_keeps_time_position_across_channels(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        _channel(conn, pid, "b", "Beta", 1, epg_channel_id="x2")
        eid = _epg_source(conn, pid)
        window = _window(conn)
        viewport_start = window._viewport_start
        _programme(conn, eid, "x1", guide.format_iso(viewport_start),
                   guide.format_iso(viewport_start + timedelta(hours=1)), "A Show")
        _programme(conn, eid, "x2", guide.format_iso(viewport_start),
                   guide.format_iso(viewport_start + timedelta(hours=1, minutes=30)), "B Show")
        window._load_programmes()
        window._relayout()

        list_control = window.getControl(CHANNEL_LIST_ID)
        list_control.selectItem(1)
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_DOWN))

        # Cursor time position (viewport_start) is preserved across the
        # move; on Beta's row that time falls inside "B Show".
        assert window._cursor_time == viewport_start
        row_index = 1 - window._top_row
        cells = window._row_cells[row_index]
        cursor_cell = next(c for c in cells if c['start'] <= window._cursor_time < c['end'])
        assert cursor_cell['title'] == 'B Show'
    finally:
        conn.close()


def test_down_over_long_past_starting_programme_does_not_move_viewport(tmp_path):
    # Regression for bug 1: Alpha's current programme started hours before
    # the viewport; Down to Beta must not carry that old start time or
    # scroll the viewport.
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        _channel(conn, pid, "b", "Beta", 1, epg_channel_id="x2")
        eid = _epg_source(conn, pid)
        window = _window(conn)
        viewport_start = window._viewport_start
        _programme(conn, eid, "x1", guide.format_iso(viewport_start - timedelta(hours=5)),
                   guide.format_iso(viewport_start + timedelta(hours=1)), "Old Movie")
        _programme(conn, eid, "x2", guide.format_iso(viewport_start),
                   guide.format_iso(viewport_start + timedelta(hours=1)), "B Show")
        window._load_programmes()
        window._relayout()

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_DOWN))

        assert window._viewport_start == viewport_start
        assert window._cursor_time == viewport_start
        row_index = 1 - window._top_row
        cells = window._row_cells[row_index]
        cursor_cell = next(c for c in cells if c['start'] <= window._cursor_time < c['end'])
        assert cursor_cell['title'] == 'B Show'
    finally:
        conn.close()


def test_left_onto_several_hour_programme_scrolls_one_slot(tmp_path):
    # Regression for bug 2: Left onto an off-screen multi-hour programme
    # must scroll by one 30-minute slot, not snap to the programme's start.
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        eid = _epg_source(conn, pid)
        window = _window(conn)
        t0 = window._viewport_start
        _programme(conn, eid, "x1", guide.format_iso(t0 - timedelta(hours=4)),
                   guide.format_iso(t0), "Long Movie")
        _programme(conn, eid, "x1", guide.format_iso(t0), guide.format_iso(t0 + timedelta(hours=1)),
                   "Current")
        window._load_programmes()
        window._relayout()
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))  # column -> grid, cell 0

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))

        assert window._viewport_start == t0 - timedelta(minutes=30)
        assert window._cursor_time == window._viewport_start
    finally:
        conn.close()


def test_next_item_and_prev_item_skip_twelve_hours(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)
        t0 = window._viewport_start

        window.onAction(xbmcgui.Action(win_guide._ACTION_NEXT_ITEM))
        assert window._viewport_start == t0 + timedelta(hours=guide.SKIP_HOURS)

        window.onAction(xbmcgui.Action(win_guide._ACTION_PREV_ITEM))
        assert window._viewport_start == t0
    finally:
        conn.close()


def test_skip_clamps_at_ceiling(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)
        now = datetime.utcnow()
        _, ceiling = window._clamp_bounds(now)

        for _ in range(40):  # far more than enough to hit the ceiling
            window.onAction(xbmcgui.Action(win_guide._ACTION_NEXT_ITEM))

        assert window._viewport_start <= ceiling
    finally:
        conn.close()


def test_remote_0_jumps_to_now(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)
        window.onAction(xbmcgui.Action(win_guide._ACTION_NEXT_ITEM))

        window.onAction(xbmcgui.Action(win_guide._ACTION_REMOTE_0))

        assert window._viewport_start == guide.round_down_30_local(window._cursor_time, window._tz)
    finally:
        conn.close()


def test_page_up_page_down_route_into_vertical_move(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        _channel(conn, pid, "b", "Beta", 1)
        window = _window(conn)

        list_control = window.getControl(CHANNEL_LIST_ID)
        list_control.selectItem(1)
        window.onAction(xbmcgui.Action(win_guide._ACTION_PAGE_DOWN))

        assert window._last_selected == 1
    finally:
        conn.close()


def test_past_cell_is_dimmed_but_cursor_cell_is_not(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        eid = _epg_source(conn, pid)
        window = _window(conn)
        t0 = window._viewport_start
        now_snapshot = datetime.utcnow()
        _programme(conn, eid, "x1", guide.format_iso(t0), guide.format_iso(now_snapshot), "Past Show")
        _programme(conn, eid, "x1", guide.format_iso(now_snapshot),
                   guide.format_iso(t0 + timedelta(hours=2)), "Current Show")
        window._load_programmes()
        # Put the travel axis on "Current Show" so "Past Show" is dimmed
        # without being the cursor cell.
        window._cursor_time = now_snapshot
        window._zone = 'grid'
        window._relayout()

        past_image, past_label, past_desc = window._pool[0][0]
        current_image, current_label, current_desc = window._pool[0][1]
        assert past_label.getLabel() == '[COLOR FF808080]Past Show[/COLOR]'
        assert current_label.getLabel() == '[COLOR FFFFFFFF]Current Show[/COLOR]'
        assert past_desc.getLabel() == ''
        assert current_desc.getLabel() == ''
    finally:
        conn.close()


def test_cell_shows_description_below_title_with_colour_by_state(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        eid = _epg_source(conn, pid)
        window = _window(conn)
        t0 = window._viewport_start
        now_snapshot = datetime.utcnow()
        _programme(conn, eid, "x1", guide.format_iso(t0), guide.format_iso(now_snapshot), "Past Show",
                   description="About the past show")
        _programme(conn, eid, "x1", guide.format_iso(now_snapshot),
                   guide.format_iso(t0 + timedelta(hours=2)), "Current Show",
                   description="About the current show")
        window._load_programmes()
        window._cursor_time = now_snapshot
        window._zone = 'grid'
        window._relayout()

        _past_image, _past_label, past_desc = window._pool[0][0]
        _current_image, _current_label, current_desc = window._pool[0][1]
        assert past_desc.getLabel() == '[COLOR FF606060]About the past show[/COLOR]'
        assert current_desc.getLabel() == '[COLOR FFE0E0E0]About the current show[/COLOR]'
    finally:
        conn.close()


def test_filler_cell_description_is_empty(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        window = _window(conn)
        window._load_programmes()
        window._relayout()

        _no_info_image, _no_info_label, no_info_desc = window._pool[0][0]
        assert no_info_desc.getLabel() == ''
    finally:
        conn.close()


def test_no_information_cell_is_never_dimmed(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        window = _window(conn)
        # No programmes at all -> the whole (past-and-future) viewport
        # renders as a single "No information" cell that must not dim.
        window._load_programmes()
        window._relayout()

        no_info_image, no_info_label, _no_info_desc = window._pool[0][0]
        assert 'FF808080' not in no_info_label.getLabel()
    finally:
        conn.close()


def test_relayout_highlights_filler_cell_when_axis_falls_in_a_former_gap(tmp_path):
    # Gaps between programmes are now filled with "No information" filler
    # cells, so a cursor_time between A and B lands exactly on the filler
    # cell it falls in, not (via a nearest-cell fallback) on B.
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        eid = _epg_source(conn, pid)
        window = _window(conn)
        t0 = window._viewport_start
        _programme(conn, eid, "x1", guide.format_iso(t0), guide.format_iso(t0 + timedelta(minutes=30)), "A")
        _programme(conn, eid, "x1", guide.format_iso(t0 + timedelta(hours=1)),
                   guide.format_iso(t0 + timedelta(hours=2)), "B")
        window._load_programmes()
        # 50 minutes in: inside the filler gap between A's end (30m) and
        # B's start (1h).
        window._cursor_time = t0 + timedelta(minutes=50)
        window._zone = 'grid'
        window._relayout()

        cells = window._row_cells[0]
        gap_cell = next(c for c in cells if c['filler'])
        assert gap_cell['start'] == t0 + timedelta(minutes=30)
        assert gap_cell['end'] == t0 + timedelta(hours=1)
        _gap_image, gap_label, _gap_desc = window._pool[0][gap_cell['pool_index']]
        assert gap_label.getLabel() == '[COLOR FFFFFFFF]%s[/COLOR]' % window._no_info_title
    finally:
        conn.close()


def test_swap_cursor_cell_restores_past_color_not_plain_text_color(tmp_path):
    # Review fix 2: the cheap Left/Right swap path must restore the old
    # cursor cell to the dimmed past color when it has since ended, not
    # the plain future/present text color.
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        eid = _epg_source(conn, pid)
        window = _window(conn)
        t0 = window._viewport_start
        now_snapshot = datetime.utcnow()
        _programme(conn, eid, "x1", guide.format_iso(t0), guide.format_iso(now_snapshot), "Past Show")
        _programme(conn, eid, "x1", guide.format_iso(now_snapshot),
                   guide.format_iso(t0 + timedelta(hours=2)), "Current Show")
        window._load_programmes()
        window._relayout()
        window._zone = 'grid'

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))

        past_cell = next(c for c in window._row_cells[0] if c['title'] == 'Past Show')
        _past_image, past_label, _past_desc = window._pool[0][past_cell['pool_index']]
        assert past_label.getLabel() == '[COLOR FF808080]Past Show[/COLOR]'
    finally:
        conn.close()


def test_swap_cursor_row_restores_past_color_not_plain_text_color(tmp_path):
    # Review fix 2, other swap path: Down away from a now-past cell must
    # restore it to the dimmed past color, not the plain text color.
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        _channel(conn, pid, "b", "Beta", 1, epg_channel_id="x2")
        eid = _epg_source(conn, pid)
        window = _window(conn)
        t0 = window._viewport_start
        now_snapshot = datetime.utcnow()
        _programme(conn, eid, "x1", guide.format_iso(t0), guide.format_iso(now_snapshot), "Past Show")
        _programme(conn, eid, "x2", guide.format_iso(t0), guide.format_iso(t0 + timedelta(hours=1)), "B Show")
        window._load_programmes()
        window._relayout()

        list_control = window.getControl(CHANNEL_LIST_ID)
        list_control.selectItem(1)
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_DOWN))

        past_cell = next(c for c in window._row_cells[0] if c['title'] == 'Past Show')
        _past_image, past_label, _past_desc = window._pool[0][past_cell['pool_index']]
        assert past_label.getLabel() == '[COLOR FF808080]Past Show[/COLOR]'
    finally:
        conn.close()


def test_right_on_empty_row_scrolls_viewport_and_lands_on_right_edge_filler(tmp_path):
    # Bug fix: Right on a row with no programmes ("No information") must
    # still scroll the viewport, landing on the filler cell that now
    # covers the newly-revealed right edge, not do nothing. The whole row
    # is one filler cell, so its 'start' is the new viewport_start.
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        window = _window(conn)
        t0 = window._viewport_start
        window._load_programmes()
        window._relayout()

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))  # column -> grid, on the row's only cell
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))

        assert window._viewport_start == t0 + timedelta(minutes=30)
        assert window._cursor_time == window._viewport_start
        cell = window._find_cell(window._focused_row_index(), window._cursor_time)
        assert cell['filler'] is True
        assert cell['start'] == window._viewport_start
        assert cell['end'] == guide.viewport_end(window._viewport_start)
    finally:
        conn.close()


def test_left_on_empty_row_scrolls_viewport_back_one_slot(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        window = _window(conn)
        t0 = window._viewport_start
        window._load_programmes()
        window._relayout()
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))  # column -> grid, on the row's only cell

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))

        assert window._viewport_start == t0 - timedelta(minutes=30)
        assert window._cursor_time == window._viewport_start
    finally:
        conn.close()


def test_right_from_programme_into_gap_then_into_next_programme(tmp_path):
    # Right from a real programme first lands on the filler gap after it,
    # then a second Right lands on the following programme.
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        eid = _epg_source(conn, pid)
        window = _window(conn)
        t0 = window._viewport_start
        _programme(conn, eid, "x1", guide.format_iso(t0), guide.format_iso(t0 + timedelta(minutes=30)), "A")
        _programme(conn, eid, "x1", guide.format_iso(t0 + timedelta(hours=1)),
                   guide.format_iso(t0 + timedelta(hours=2)), "B")
        window._load_programmes()
        window._relayout()

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))  # column -> grid, cell 0 ('A')
        assert window._cursor_time == t0

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))
        assert window._cursor_time == t0 + timedelta(minutes=30)
        cell = window._find_cell(window._focused_row_index(), window._cursor_time)
        assert cell['filler'] is True

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))
        assert window._cursor_time == t0 + timedelta(hours=1)
        cell = window._find_cell(window._focused_row_index(), window._cursor_time)
        assert cell['title'] == 'B'
    finally:
        conn.close()


def test_left_at_retention_floor_off_screen_target_is_a_no_op(tmp_path):
    # A clamped scroll that lands exactly back on the current viewport_start
    # (Left at the retention floor) must not relayout: nothing moved, so
    # programmes should not be reloaded and the grid should not rebuild.
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        window = _window(conn)
        floor, _ceiling = window._clamp_bounds(datetime.utcnow())
        channel_id = window._channel_rows[0]['id']
        window._viewport_start = floor
        window._cursor_time = floor
        window._programmes_by_channel = {
            channel_id: [
                {'start': floor - timedelta(hours=1), 'end': floor, 'title': 'Prev Show'},
                {'start': floor, 'end': floor + timedelta(hours=1), 'title': 'Current Show'},
            ]
        }
        window._load_programmes = lambda: None  # keep the seeded data
        window._zone = 'grid'
        window._relayout()

        load_calls = []
        window._load_programmes = lambda: load_calls.append(1)
        relayout_calls = []
        window._relayout = lambda: relayout_calls.append(1)

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))

        assert window._viewport_start == floor
        assert window._cursor_time == floor
        assert load_calls == []
        assert relayout_calls == []
    finally:
        conn.close()


def test_back_closes_window(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)
        closed = []
        window.close = lambda: closed.append(True)
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
        assert closed == [True]
    finally:
        conn.close()


def test_ok_on_cell_is_a_no_op(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)
        window.onClick(CHANNEL_LIST_ID)  # must not raise
    finally:
        conn.close()


def test_pool_overflow_logs_warning(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        eid = _epg_source(conn, pid)
        window = _window(conn)
        viewport_start = window._viewport_start
        # 30 back-to-back 6-minute programmes fill the whole 180-minute
        # viewport, exceeding the 28-column pool.
        for i in range(30):
            start = viewport_start + timedelta(minutes=6 * i)
            end = start + timedelta(minutes=6)
            _programme(conn, eid, "x1", guide.format_iso(start), guide.format_iso(end),
                       "Show %d" % i)
        xbmc.log_calls[:] = []
        window._load_programmes()
        window._relayout()
        assert any(
            "pool exhausted" in msg and level == xbmc.LOGWARNING
            for msg, level in xbmc.log_calls
        )
    finally:
        conn.close()


def test_horizontal_viewport_jump_is_instant_and_clips_edge_cell(tmp_path):
    # User feedback: horizontal scrolling (Left/Right) must be instant, no
    # slide or fade animation. A programme starting before the new
    # viewport must also clip to the grid's left edge (x=0) rather than
    # spill off-screen.
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        eid = _epg_source(conn, pid)
        window = _window(conn)
        t0 = window._viewport_start
        _programme(conn, eid, "x1", guide.format_iso(t0 - timedelta(minutes=90)),
                   guide.format_iso(t0), "Before")
        _programme(conn, eid, "x1", guide.format_iso(t0), guide.format_iso(t0 + timedelta(hours=1)),
                   "Current")
        window._load_programmes()
        window._relayout()
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))  # column -> grid, cell 0

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))

        assert window._viewport_start == t0 - timedelta(minutes=30)
        edge_cell = window._row_cells[0][0]
        assert edge_cell['title'] == 'Before'
        assert edge_cell['x'] == 0
        edge_image, edge_label, _edge_desc = window._pool[0][0]
        assert edge_image._animations == []
        assert edge_label._animations == []
    finally:
        conn.close()


def test_vertical_row_scroll_is_instant(tmp_path):
    # User feedback: the vertical row-scroll slide/fade "felt like rubber
    # banding" -- Up/Down that changes the list's top row must now be
    # instant too, attaching no animation, matching horizontal scrolling.
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        for i in range(win_guide._VISIBLE_ROWS + 1):
            _channel(conn, pid, "c%d" % i, "Chan %d" % i, i)
        window = _window(conn)
        list_control = window.getControl(CHANNEL_LIST_ID)
        list_control.selectItem(win_guide._VISIBLE_ROWS)

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_DOWN))

        assert window._top_row == 1
        for row_pool in window._pool:
            for image, label, desc_label in row_pool:
                assert image._animations == []
                assert label._animations == []
                assert desc_label._animations == []
    finally:
        conn.close()


def test_in_viewport_cursor_move_does_not_touch_animations(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        eid = _epg_source(conn, pid)
        window = _window(conn)
        viewport_start = window._viewport_start
        _programme(conn, eid, "x1", guide.format_iso(viewport_start),
                   guide.format_iso(viewport_start + timedelta(hours=1)), "Show A")
        _programme(conn, eid, "x1", guide.format_iso(viewport_start + timedelta(hours=1)),
                   guide.format_iso(viewport_start + timedelta(hours=2)), "Show B")
        window._load_programmes()
        window._relayout()

        image_a, _label_a, _desc_a = window._pool[0][0]
        image_b, _label_b, _desc_b = window._pool[0][1]
        image_a._animations = ['sentinel']
        image_b._animations = ['sentinel']

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))

        assert image_a._animations == ['sentinel']
        assert image_b._animations == ['sentinel']
    finally:
        conn.close()


# -- catch-up glyph/greying (issue #28) ------------------------------------

def test_playable_past_cell_has_no_glyph_and_is_not_greyed(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        cid = _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        conn.execute("UPDATE channel SET catchup_days = 3 WHERE id = ?", (cid,))
        eid = _epg_source(conn, pid)
        window = _window(conn)
        t0 = window._viewport_start
        now_snapshot = datetime.utcnow()
        _programme(conn, eid, "x1", guide.format_iso(t0), guide.format_iso(now_snapshot), "Past Show")
        _programme(conn, eid, "x1", guide.format_iso(now_snapshot),
                   guide.format_iso(t0 + timedelta(hours=2)), "Current Show")
        window._load_programmes()
        window._cursor_time = now_snapshot  # cursor on "Current Show", not the past cell
        window._relayout()

        past_label = window._pool[0][0][1]
        assert past_label.getLabel() == '[COLOR FFCCCCCC]Past Show[/COLOR]'
    finally:
        conn.close()


def test_channel_list_item_catchup_property_reflects_catchup_days(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        cid = _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        _channel(conn, pid, "b", "Beta", 1, epg_channel_id="x2")
        conn.execute("UPDATE channel SET catchup_days = 3 WHERE id = ?", (cid,))
        window = _window(conn)

        items = window.getControl(CHANNEL_LIST_ID)._items
        assert items[0].getProperty('catchup') == '1'
        assert items[1].getProperty('catchup') == '0'
    finally:
        conn.close()


def test_unplayable_past_cell_has_no_glyph_and_is_greyed(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        # No catchup_days on channel or provider -> no Catch-up Window.
        eid = _epg_source(conn, pid)
        window = _window(conn)
        t0 = window._viewport_start
        now_snapshot = datetime.utcnow()
        _programme(conn, eid, "x1", guide.format_iso(t0), guide.format_iso(now_snapshot), "Past Show")
        _programme(conn, eid, "x1", guide.format_iso(now_snapshot),
                   guide.format_iso(t0 + timedelta(hours=2)), "Current Show")
        window._load_programmes()
        window._cursor_time = now_snapshot
        window._relayout()

        past_label = window._pool[0][0][1]
        assert past_label.getLabel() == '[COLOR FF808080]Past Show[/COLOR]'
    finally:
        conn.close()


def test_unsupported_m3u_url_past_cell_is_greyed_despite_catchup_days(tmp_path):
    # default mode, no catchup-source, non-XC live URL: the Channel's mode
    # cannot produce a Catch-up URL at all, so it must be treated as
    # unplayable even though catchup_days is set (issue #39).
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        cid = _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1",
                        stream_url='http://cdn.example/a.m3u8')
        conn.execute("UPDATE channel SET catchup_days = 3 WHERE id = ?", (cid,))
        eid = _epg_source(conn, pid)
        window = _window(conn)
        t0 = window._viewport_start
        now_snapshot = datetime.utcnow()
        _programme(conn, eid, "x1", guide.format_iso(t0), guide.format_iso(now_snapshot), "Past Show")
        _programme(conn, eid, "x1", guide.format_iso(now_snapshot),
                   guide.format_iso(t0 + timedelta(hours=2)), "Current Show")
        window._load_programmes()
        window._cursor_time = now_snapshot
        window._relayout()

        past_label = window._pool[0][0][1]
        assert past_label.getLabel() == '[COLOR FF808080]Past Show[/COLOR]'
    finally:
        conn.close()


def test_unsupported_m3u_url_past_cell_dialog_is_info_only(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        cid = _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1",
                        stream_url='http://cdn.example/a.m3u8')
        conn.execute("UPDATE channel SET catchup_days = 3 WHERE id = ?", (cid,))
        eid = _epg_source(conn, pid)
        window, dialog_cls, playback_cls = _guide_window_with_fakes(conn, None)
        t0 = window._viewport_start
        now_snapshot = datetime.utcnow()
        _programme(conn, eid, "x1", guide.format_iso(t0), guide.format_iso(now_snapshot), "Past Show")
        window._load_programmes()
        window._cursor_time = t0
        window._zone = 'grid'
        window._relayout()

        window.onClick(CHANNEL_LIST_ID)

        assert dialog_cls.opened_with['actions'] == []
    finally:
        conn.close()


class _FakeDialog(object):
    opened_with = None
    result = None

    @classmethod
    def open(cls, **kwargs):
        cls.opened_with = kwargs
        return cls()


class _FakePlaybackWindow(object):
    opened_with = None

    @classmethod
    def open(cls, **kwargs):
        cls.opened_with = kwargs
        return cls()


def _guide_window_with_fakes(conn, dialog_result):
    class _Dialog(_FakeDialog):
        result = dialog_result

    class _Playback(_FakePlaybackWindow):
        pass

    class _Window(GuideWindow):
        dialog_cls = _Dialog
        playback_cls = _Playback

    window = _Window('script-kodimate-guide.xml', '/addon', 'Main', '1080i', conn=conn)
    window.onInit()
    return window, _Dialog, _Playback


def test_ok_on_live_cell_opens_dialog_with_watch_live_action_and_dispatches(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        eid = _epg_source(conn, pid)
        window, dialog_cls, playback_cls = _guide_window_with_fakes(conn, 'watch_live')
        t0 = window._viewport_start
        now_snapshot = datetime.utcnow()
        _programme(conn, eid, "x1", guide.format_iso(now_snapshot - timedelta(minutes=10)),
                   guide.format_iso(now_snapshot + timedelta(minutes=10)), "Live Show")
        window._load_programmes()
        window._cursor_time = now_snapshot
        window._zone = 'grid'
        window._relayout()

        window.onClick(CHANNEL_LIST_ID)

        assert dialog_cls.opened_with['actions'] == ['watch_live']
        assert playback_cls.opened_with is not None
        assert 'catchup' not in playback_cls.opened_with
    finally:
        conn.close()


def test_ok_on_live_cell_with_window_dispatches_start_over_as_catchup(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        cid = _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        conn.execute("UPDATE channel SET catchup_days = 3 WHERE id = ?", (cid,))
        eid = _epg_source(conn, pid)
        window, dialog_cls, playback_cls = _guide_window_with_fakes(conn, 'start_over')
        now_snapshot = datetime.utcnow()
        start = now_snapshot - timedelta(minutes=10)
        end = now_snapshot + timedelta(minutes=10)
        _programme(conn, eid, "x1", guide.format_iso(start), guide.format_iso(end), "Live Show")
        window._load_programmes()
        window._cursor_time = now_snapshot
        window._zone = 'grid'
        window._relayout()

        window.onClick(CHANNEL_LIST_ID)

        assert dialog_cls.opened_with['actions'] == ['watch_live', 'start_over']
        assert playback_cls.opened_with['catchup']['title'] == 'Live Show'
        assert playback_cls.opened_with['catchup']['start'] == win_guide._epoch(start)
    finally:
        conn.close()


def test_ok_on_playable_past_cell_dispatches_play_catchup(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        cid = _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        conn.execute("UPDATE channel SET catchup_days = 3 WHERE id = ?", (cid,))
        eid = _epg_source(conn, pid)
        window, dialog_cls, playback_cls = _guide_window_with_fakes(conn, 'play_catchup')
        t0 = window._viewport_start
        now_snapshot = datetime.utcnow()
        _programme(conn, eid, "x1", guide.format_iso(t0), guide.format_iso(now_snapshot), "Past Show")
        window._load_programmes()
        window._cursor_time = t0
        window._zone = 'grid'
        window._relayout()

        window.onClick(CHANNEL_LIST_ID)

        assert dialog_cls.opened_with['actions'] == ['play_catchup']
        assert playback_cls.opened_with['catchup']['title'] == 'Past Show'
    finally:
        conn.close()


def test_ok_on_filler_cell_does_not_open_dialog(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window, dialog_cls, playback_cls = _guide_window_with_fakes(conn, None)

        window.onClick(CHANNEL_LIST_ID)

        assert dialog_cls.opened_with is None
    finally:
        conn.close()


def test_generation_change_keeps_channel_focus_and_viewport_offset(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        for i in range(win_guide._VISIBLE_ROWS + 2):
            _channel(conn, pid, "c%d" % i, "Chan%d" % i, i)
        window = _window(conn)
        list_control = window.getControl(CHANNEL_LIST_ID)
        list_control.selectItem(win_guide._VISIBLE_ROWS)  # scrolls the viewport down
        window._handle_vertical_move()
        old_top_row = window._top_row
        old_offset = list_control.getSelectedPosition() - old_top_row

        conn.execute("UPDATE channel SET name = 'Renamed' WHERE channel_key = 'c%d' " % win_guide._VISIBLE_ROWS)
        _bump_generation(2)
        _notify_refreshed(window)

        new_selected = list_control.getSelectedPosition()
        assert list_control.getListItem(new_selected).getLabel() == 'Renamed'
        assert new_selected - window._top_row == old_offset
    finally:
        conn.close()


def test_generation_change_selects_nearest_row_when_focused_channel_went_stale(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        _channel(conn, pid, "b", "Beta", 1)
        window = _window(conn)
        list_control = window.getControl(CHANNEL_LIST_ID)
        list_control.selectItem(1)  # Beta

        conn.execute("UPDATE channel SET stale_since = '2026-01-01T00:00:00' WHERE channel_key = 'b'")
        _bump_generation(2)
        _notify_refreshed(window)

        assert list_control.size() == 1
        assert list_control.getSelectedPosition() == 0
    finally:
        conn.close()


def test_generation_change_deferred_under_modal_then_applied_after_dialog_closes(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        eid = _epg_source(conn, pid)
        window, dialog_cls, playback_cls = _guide_window_with_fakes(conn, None)
        viewport_start = window._viewport_start
        _programme(conn, eid, "x1", guide.format_iso(viewport_start),
                   guide.format_iso(viewport_start + timedelta(hours=1)), "Show A")
        window._load_programmes()
        window._relayout()
        window._zone = 'grid'

        class _BumpingDialog(_FakeDialog):
            result = None

            @classmethod
            def open(cls, **kwargs):
                conn.execute("UPDATE channel SET name = 'Alpha2' WHERE channel_key = 'a'")
                _bump_generation(2)
                _notify_refreshed(window)
                return super(_BumpingDialog, cls).open(**kwargs)

        window.dialog_cls = _BumpingDialog

        list_control = window.getControl(CHANNEL_LIST_ID)
        assert list_control.getListItem(0).getLabel() == 'Alpha'

        window.onClick(CHANNEL_LIST_ID)

        assert list_control.getListItem(0).getLabel() == 'Alpha2'
    finally:
        conn.close()


def test_generation_watcher_stopped_on_close(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)
        window.close()
        assert window._watcher._stopped is True
    finally:
        conn.close()


def test_reentering_oninit_does_not_rebuild_pool_or_now_line(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        _channel(conn, pid, "b", "Beta", 1)
        window = _window(conn)

        added_before = len(window._added_controls)
        now_line_before = window.now_line
        watcher_before = window._watcher
        top_row_before = window._top_row
        viewport_start_before = window._viewport_start
        cursor_time_before = window._cursor_time
        selected_before = window.getControl(CHANNEL_LIST_ID).getSelectedPosition()

        window.onInit()

        assert len(window._added_controls) == added_before
        assert window.now_line is now_line_before
        assert window._watcher is watcher_before
        assert window._top_row == top_row_before
        assert window._viewport_start == viewport_start_before
        assert window._cursor_time == cursor_time_before
        assert window.getControl(CHANNEL_LIST_ID).getSelectedPosition() == selected_before
    finally:
        conn.close()


def test_reentering_oninit_applies_deferred_refresh(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)

        list_control = window.getControl(CHANNEL_LIST_ID)
        assert list_control.getListItem(0).getLabel() == 'Alpha'

        conn.execute("UPDATE channel SET name = 'Alpha2' WHERE channel_key = 'a'")
        _bump_generation(2)
        window._render_pending = True

        window.onInit()

        assert window._render_pending is False
        assert list_control.getListItem(0).getLabel() == 'Alpha2'
    finally:
        conn.close()


def test_default_filter_is_all_channels(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)
        assert window.getProperty('guide_filter') == 'String 32038'
    finally:
        conn.close()


def test_group_filter_restricts_rows_and_sets_header(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        gid = conn.execute(
            "INSERT INTO channel_group (provider_id, name, sort_order) VALUES (?, 'Sports', 0)",
            (pid,),
        ).lastrowid
        _channel(conn, pid, "a", "Alpha", 0)
        cid = _channel(conn, pid, "b", "Beta", 1)
        conn.execute("UPDATE channel SET group_id = ? WHERE id = ?", (gid, cid))
        window = GuideWindow('script-kodimate-guide.xml', '/addon', 'Main', '1080i',
                              conn=conn, group_id=gid)
        window.onInit()
        assert [row['name'] for row in window._channel_rows] == ['Beta']
        assert window.getProperty('guide_filter') == 'Sports'
    finally:
        conn.close()


def test_provider_filter_restricts_rows_and_sets_header(tmp_path):
    conn = _conn(tmp_path)
    try:
        pa = _provider(conn, name="Provider A")
        pb = _provider(conn, name="Provider B")
        _channel(conn, pa, "a", "Alpha", 0)
        _channel(conn, pb, "b", "Beta", 1)
        window = GuideWindow('script-kodimate-guide.xml', '/addon', 'Main', '1080i',
                              conn=conn, provider_id=pa)
        window.onInit()
        assert [row['name'] for row in window._channel_rows] == ['Alpha']
        assert window.getProperty('guide_filter') == 'Provider A'
    finally:
        conn.close()


def test_provider_filter_unknown_provider_id_falls_back_to_all_label(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = GuideWindow('script-kodimate-guide.xml', '/addon', 'Main', '1080i',
                              conn=conn, provider_id=999)
        window.onInit()
        assert window.getProperty('guide_filter') == 'String 32038'
        assert window._channel_rows == []
    finally:
        conn.close()


def test_provider_and_group_filter_combined_restricts_to_group(tmp_path):
    conn = _conn(tmp_path)
    try:
        pa = _provider(conn, name="Provider A")
        pb = _provider(conn, name="Provider B")
        gid = conn.execute(
            "INSERT INTO channel_group (provider_id, name, sort_order) VALUES (?, 'Sports', 0)",
            (pa,),
        ).lastrowid
        cid = _channel(conn, pa, "a", "Alpha", 0)
        conn.execute("UPDATE channel SET group_id = ? WHERE id = ?", (gid, cid))
        _channel(conn, pa, "c", "Charlie", 1)
        _channel(conn, pb, "b", "Beta", 0)
        window = GuideWindow('script-kodimate-guide.xml', '/addon', 'Main', '1080i',
                              conn=conn, provider_id=pa, group_id=gid)
        window.onInit()
        assert [row['name'] for row in window._channel_rows] == ['Alpha']
    finally:
        conn.close()


def test_generation_change_keeps_provider_filter(tmp_path):
    conn = _conn(tmp_path)
    try:
        pa = _provider(conn, name="Provider A")
        pb = _provider(conn, name="Provider B")
        _channel(conn, pa, "a", "Alpha", 0)
        _channel(conn, pb, "b", "Beta", 1)
        window = GuideWindow('script-kodimate-guide.xml', '/addon', 'Main', '1080i',
                              conn=conn, provider_id=pa)
        window.onInit()
        _bump_generation(1)
        _notify_refreshed(window)
        assert [row['name'] for row in window._channel_rows] == ['Alpha']
    finally:
        conn.close()


def test_favourites_filter_restricts_rows_and_sets_header(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        _channel(conn, pid, "b", "Beta", 1)
        conn.execute(
            "INSERT INTO channel_override (provider_id, channel_key, favourite) VALUES (?, 'b', 1)",
            (pid,),
        )
        window = GuideWindow('script-kodimate-guide.xml', '/addon', 'Main', '1080i',
                              conn=conn, favourites=True)
        window.onInit()
        assert [row['name'] for row in window._channel_rows] == ['Beta']
        assert window.getProperty('guide_filter') == 'String 32039'
    finally:
        conn.close()


def test_focus_channel_id_selects_initial_cursor(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        cid_b = _channel(conn, pid, "b", "Beta", 1)
        window = GuideWindow('script-kodimate-guide.xml', '/addon', 'Main', '1080i',
                              conn=conn, focus_channel_id=cid_b)
        window.onInit()
        assert window.getControl(CHANNEL_LIST_ID).getSelectedPosition() == 1
        assert window._last_selected == 1
    finally:
        conn.close()




def test_generation_change_keeps_group_filter(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        gid = conn.execute(
            "INSERT INTO channel_group (provider_id, name, sort_order) VALUES (?, 'Sports', 0)",
            (pid,),
        ).lastrowid
        _channel(conn, pid, "a", "Alpha", 0)
        cid = _channel(conn, pid, "b", "Beta", 1)
        conn.execute("UPDATE channel SET group_id = ? WHERE id = ?", (gid, cid))
        window = GuideWindow('script-kodimate-guide.xml', '/addon', 'Main', '1080i',
                              conn=conn, group_id=gid)
        window.onInit()
        _bump_generation(1)
        _notify_refreshed(window)
        assert [row['name'] for row in window._channel_rows] == ['Beta']
    finally:
        conn.close()


def test_empty_favourites_filter_is_a_no_op_grid_no_exceptions(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = GuideWindow('script-kodimate-guide.xml', '/addon', 'Main', '1080i',
                              conn=conn, favourites=True)
        window.onInit()
        assert window._channel_rows == []
        assert window.getProperty('guide_filter') == 'String 32039'
        for action_id in (xbmcgui.ACTION_MOVE_LEFT, xbmcgui.ACTION_MOVE_RIGHT,
                           xbmcgui.ACTION_MOVE_UP, xbmcgui.ACTION_MOVE_DOWN):
            window.onAction(xbmcgui.Action(action_id))
        closed = []
        window.close = lambda: closed.append(True)
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))
        assert closed == [True]
    finally:
        conn.close()


# -- Icon rail / focus zones (issue #46) ------------------------------------

def test_opens_with_column_zone_focused_on_channel_list(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)
        assert window._zone == 'column'
        assert window.getFocusId() == CHANNEL_LIST_ID
        assert window.getFocusId() not in (
            win_guide.RAIL_LIVETV_ID, win_guide.RAIL_CATCHUP_ID, win_guide.RAIL_SETTINGS_ID,
        )
    finally:
        conn.close()


def test_rail_selected_property_set_to_livetv(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)
        assert window.getProperty('rail_selected') == 'livetv'
    finally:
        conn.close()


def test_left_from_column_opens_panel_with_current_filter_selected(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))

        assert window._zone == 'panel'
        assert window.getFocusId() == win_guide.PANEL_LIST_ID
        panel = window.getControl(win_guide.PANEL_LIST_ID)
        assert [item.getLabel() for item in panel._items] == ['String 32038', 'String 32039', 'P1']
        assert panel.getSelectedPosition() == 0
        assert panel.getListItem(0).getProperty('active') == '1'
        assert window.getProperty('panel_heading') == 'String 32125'
    finally:
        conn.close()


def test_left_from_panel_reaches_rail(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))  # column -> panel

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))

        assert window._zone == 'rail'
        assert window.getFocusId() == win_guide.RAIL_LIVETV_ID
    finally:
        conn.close()


def test_right_from_rail_returns_to_panel(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))  # column -> panel
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))  # panel -> rail

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))

        assert window._zone == 'panel'
        assert window.getFocusId() == win_guide.PANEL_LIST_ID
    finally:
        conn.close()


def test_ok_on_group_row_applies_filter_and_moves_to_column(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn, name="P1")
        gid = conn.execute(
            "INSERT INTO channel_group (provider_id, name, sort_order) VALUES (?, 'Sports', 0)",
            (pid,),
        ).lastrowid
        _channel(conn, pid, "a", "Alpha", 0)
        cid_b = _channel(conn, pid, "b", "Beta", 1)
        conn.execute("UPDATE channel SET group_id = ? WHERE id = ?", (gid, cid_b))
        window = _window(conn)
        original_viewport = window._viewport_start
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))  # column -> panel
        panel = window.getControl(win_guide.PANEL_LIST_ID)
        panel.selectItem(3)  # 'Sports'

        window.onClick(win_guide.PANEL_LIST_ID)

        assert [row['name'] for row in window._channel_rows] == ['Beta']
        assert window._top_row == 0
        assert window._viewport_start == original_viewport
        assert window.getProperty('guide_filter') == 'Sports'
        assert window.getProperty('panel_heading') == 'String 32125'
        assert window._zone == 'column'
        assert window.getFocusId() == CHANNEL_LIST_ID
        assert panel.getSelectedPosition() == 3
        assert panel.getListItem(3).getProperty('active') == '1'
    finally:
        conn.close()


def test_right_on_group_row_applies_filter_and_moves_to_column(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn, name="P1")
        gid = conn.execute(
            "INSERT INTO channel_group (provider_id, name, sort_order) VALUES (?, 'Sports', 0)",
            (pid,),
        ).lastrowid
        _channel(conn, pid, "a", "Alpha", 0)
        cid_b = _channel(conn, pid, "b", "Beta", 1)
        conn.execute("UPDATE channel SET group_id = ? WHERE id = ?", (gid, cid_b))
        window = _window(conn)
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))  # column -> panel
        panel = window.getControl(win_guide.PANEL_LIST_ID)
        panel.selectItem(3)  # 'Sports'

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))

        assert [row['name'] for row in window._channel_rows] == ['Beta']
        assert window.getProperty('guide_filter') == 'Sports'
        assert window._zone == 'column'
        assert window.getFocusId() == CHANNEL_LIST_ID
    finally:
        conn.close()


def test_ok_on_provider_header_collapses_and_expands(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn, name="P1")
        gid = conn.execute(
            "INSERT INTO channel_group (provider_id, name, sort_order) VALUES (?, 'Sports', 0)",
            (pid,),
        ).lastrowid
        cid = _channel(conn, pid, "a", "Alpha", 0)
        conn.execute("UPDATE channel SET group_id = ? WHERE id = ?", (gid, cid))
        window = _window(conn)
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))  # column -> panel
        panel = window.getControl(win_guide.PANEL_LIST_ID)
        panel.selectItem(2)  # provider header 'P1'

        window.onClick(win_guide.PANEL_LIST_ID)

        labels = [item.getLabel() for item in panel._items]
        assert labels == ['String 32038', 'String 32039', 'P1']
        assert panel.getSelectedPosition() == 2
        assert window.getFocusId() == win_guide.PANEL_LIST_ID
        assert window._zone == 'panel'

        window.onClick(win_guide.PANEL_LIST_ID)

        labels = [item.getLabel() for item in panel._items]
        assert labels == ['String 32038', 'String 32039', 'P1', 'Sports']
    finally:
        conn.close()


def test_right_on_provider_header_moves_to_column_without_changing_filter(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn, name="P1")
        gid = conn.execute(
            "INSERT INTO channel_group (provider_id, name, sort_order) VALUES (?, 'Sports', 0)",
            (pid,),
        ).lastrowid
        cid = _channel(conn, pid, "a", "Alpha", 0)
        conn.execute("UPDATE channel SET group_id = ? WHERE id = ?", (gid, cid))
        window = _window(conn)
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))  # column -> panel
        panel = window.getControl(win_guide.PANEL_LIST_ID)
        panel.selectItem(2)  # provider header 'P1'

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))

        assert window._zone == 'column'
        assert window.getFocusId() == CHANNEL_LIST_ID
        assert window._group_id is None
        assert window._favourites is False
        assert window._collapsed == set()
        assert window.getProperty('guide_filter') == 'String 32038'
    finally:
        conn.close()


def test_back_from_panel_closes_window(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))  # column -> panel
        closed = []
        window.close = lambda: closed.append(True)

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))

        assert closed == [True]
        assert window._group_id is None
        assert window._favourites is False
    finally:
        conn.close()


def test_reopening_panel_highlights_the_applied_row(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn, name="P1")
        gid = conn.execute(
            "INSERT INTO channel_group (provider_id, name, sort_order) VALUES (?, 'Sports', 0)",
            (pid,),
        ).lastrowid
        _channel(conn, pid, "a", "Alpha", 0)
        cid_b = _channel(conn, pid, "b", "Beta", 1)
        conn.execute("UPDATE channel SET group_id = ? WHERE id = ?", (gid, cid_b))
        window = _window(conn)
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))  # column -> panel
        panel = window.getControl(win_guide.PANEL_LIST_ID)
        panel.selectItem(3)  # 'Sports'
        window.onClick(win_guide.PANEL_LIST_ID)  # applies filter, back to column

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))  # column -> panel again

        assert panel.getSelectedPosition() == 3
        assert panel.getListItem(3).getProperty('active') == '1'
    finally:
        conn.close()


def test_refresh_in_place_relists_panel(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn, name="P1")
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)
        panel = window.getControl(win_guide.PANEL_LIST_ID)

        gid = conn.execute(
            "INSERT INTO channel_group (provider_id, name, sort_order) VALUES (?, 'Sports', 0)",
            (pid,),
        ).lastrowid
        _channel(conn, pid, "b", "Beta", 1)
        conn.execute("UPDATE channel SET group_id = ? WHERE channel_key = 'b'", (gid,))
        _bump_generation(2)
        _notify_refreshed(window)

        labels = [item.getLabel() for item in panel._items]
        assert labels == ['String 32038', 'String 32039', 'P1', 'Sports']
    finally:
        conn.close()


def test_applying_empty_favourites_yields_empty_list_no_exception(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))  # column -> panel
        panel = window.getControl(win_guide.PANEL_LIST_ID)
        panel.selectItem(1)  # Favourites

        window.onClick(win_guide.PANEL_LIST_ID)

        assert window._channel_rows == []
        assert window.getProperty('guide_filter') == 'String 32039'
        assert window._zone == 'column'
    finally:
        conn.close()


def test_generation_change_falls_back_to_all_when_group_vanishes(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        gid = conn.execute(
            "INSERT INTO channel_group (provider_id, name, sort_order) VALUES (?, 'Sports', 0)",
            (pid,),
        ).lastrowid
        cid = _channel(conn, pid, "a", "Alpha", 0)
        conn.execute("UPDATE channel SET group_id = ? WHERE id = ?", (gid, cid))
        window = GuideWindow('script-kodimate-guide.xml', '/addon', 'Main', '1080i',
                              conn=conn, group_id=gid)
        window.onInit()

        conn.execute("UPDATE channel SET stale_since = '2026-01-01T00:00:00' WHERE id = ?", (cid,))
        conn.execute("DELETE FROM channel_group WHERE id = ?", (gid,))
        _bump_generation(2)
        _notify_refreshed(window)

        assert window._group_id is None
        assert window._favourites is False
        assert window._provider_id is None
        assert window.getProperty('guide_filter') == 'String 32038'
        assert window.getControl(CHANNEL_LIST_ID).getSelectedPosition() == 0
    finally:
        conn.close()


def test_generation_change_falls_back_and_reselects_all_row_in_panel(tmp_path):
    # Review fix 2: the Groups panel re-render after a fallback must not
    # clamp against the stale (pre-rebuild) row count, and must select the
    # All channels row -- not whatever position happened to be selected in
    # the old (now-gone) 'Sports' section.
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn, name="P1")
        gid = conn.execute(
            "INSERT INTO channel_group (provider_id, name, sort_order) VALUES (?, 'Sports', 0)",
            (pid,),
        ).lastrowid
        cid = _channel(conn, pid, "a", "Alpha", 0)
        conn.execute("UPDATE channel SET group_id = ? WHERE id = ?", (gid, cid))
        window = GuideWindow('script-kodimate-guide.xml', '/addon', 'Main', '1080i',
                              conn=conn, group_id=gid)
        window.onInit()
        panel = window.getControl(win_guide.PANEL_LIST_ID)
        assert [item.getLabel() for item in panel._items] == [
            'String 32038', 'String 32039', 'P1', 'Sports',
        ]
        panel.selectItem(3)  # 'Sports'

        conn.execute("UPDATE channel SET stale_since = '2026-01-01T00:00:00' WHERE id = ?", (cid,))
        conn.execute("DELETE FROM channel_group WHERE id = ?", (gid,))
        _bump_generation(2)
        _notify_refreshed(window)

        assert window.getProperty('guide_filter') == 'String 32038'
        labels = [item.getLabel() for item in panel._items]
        assert 'Sports' not in labels
        assert panel.getSelectedPosition() == 0
        assert panel.getListItem(0).getProperty('active') == '1'
    finally:
        conn.close()


def test_left_on_rail_is_a_no_op(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))
        assert window._zone == 'rail'
        assert window.getFocusId() == win_guide.RAIL_LIVETV_ID
    finally:
        conn.close()




def test_right_from_column_enters_grid_with_cell_highlighted_at_travel_axis(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        eid = _epg_source(conn, pid)
        window = _window(conn)
        viewport_start = window._viewport_start
        _programme(conn, eid, "x1", guide.format_iso(viewport_start),
                   guide.format_iso(viewport_start + timedelta(hours=1)), "Show A")
        window._load_programmes()
        window._relayout()

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))

        assert window._zone == 'grid'
        assert window.getFocusId() == CHANNEL_LIST_ID
        cell = window._row_cells[0][0]
        image, _label, _desc = window._pool[0][cell['pool_index']]
        assert image._color_diffuse == 'FF3A6EA5'
    finally:
        conn.close()


def test_no_cell_highlighted_while_in_column_zone(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        eid = _epg_source(conn, pid)
        window = _window(conn)
        viewport_start = window._viewport_start
        _programme(conn, eid, "x1", guide.format_iso(viewport_start),
                   guide.format_iso(viewport_start + timedelta(hours=1)), "Show A")
        window._load_programmes()
        window._relayout()

        for image, _label, _desc in window._pool[0]:
            if image.isVisible():
                assert image._color_diffuse != 'FF3A6EA5'
    finally:
        conn.close()


def test_back_from_grid_moves_to_column_without_closing(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        eid = _epg_source(conn, pid)
        window = _window(conn)
        viewport_start = window._viewport_start
        _programme(conn, eid, "x1", guide.format_iso(viewport_start),
                   guide.format_iso(viewport_start + timedelta(hours=1)), "Show A")
        window._load_programmes()
        window._relayout()
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))  # column -> grid, cell 0
        closed = []
        window.close = lambda: closed.append(True)

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))

        assert window._zone == 'column'
        assert closed == []
        assert window.getFocusId() == CHANNEL_LIST_ID
        cell = window._row_cells[0][0]
        image, _label, _desc = window._pool[0][cell['pool_index']]
        assert image._color_diffuse != 'FF3A6EA5'
        assert window.getProperty('hint4_texture') == 'hint_info.png'
        assert window.getProperty('hint5_texture') == 'hint_star.png'
    finally:
        conn.close()


def test_back_from_column_closes_window(tmp_path):
    # Same assertion as test_back_closes_window, phrased for the zone the
    # Back/close mapping is keyed on (see guide.back_target).
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)
        assert window._zone == 'column'
        closed = []
        window.close = lambda: closed.append(True)

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))

        assert closed == [True]
    finally:
        conn.close()


def test_left_from_non_first_cell_still_moves_cursor(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        eid = _epg_source(conn, pid)
        window = _window(conn)
        viewport_start = window._viewport_start
        _programme(conn, eid, "x1", guide.format_iso(viewport_start),
                   guide.format_iso(viewport_start + timedelta(hours=1)), "Show A")
        _programme(conn, eid, "x1", guide.format_iso(viewport_start + timedelta(hours=1)),
                   guide.format_iso(viewport_start + timedelta(hours=2)), "Show B")
        window._load_programmes()
        window._relayout()
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))  # grid, cell 0
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))  # cell 1 (Show B)

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))

        assert window._zone == 'grid'
        assert window._cursor_time == viewport_start
    finally:
        conn.close()


def test_up_down_ignored_while_zone_is_rail(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        _channel(conn, pid, "b", "Beta", 1)
        window = _window(conn)
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))
        list_control = window.getControl(CHANNEL_LIST_ID)
        selected_before = list_control.getSelectedPosition()

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_DOWN))

        assert list_control.getSelectedPosition() == selected_before
    finally:
        conn.close()


def test_ok_on_column_row_plays_live_with_channel_snapshot(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window, dialog_cls, playback_cls = _guide_window_with_fakes(conn, None)
        assert window._zone == 'column'

        window.onClick(CHANNEL_LIST_ID)

        assert playback_cls.opened_with is not None
        assert playback_cls.opened_with['snapshot']['channel_key'] == 'a'
        assert dialog_cls.opened_with is None
    finally:
        conn.close()


def test_focus_reasserted_after_playback_closes_with_no_focused_control(tmp_path):
    # Focus robustness (real-Kodi regression): if the modal that closed
    # left no control focused (e.g. PlaybackWindow closing itself after a
    # stream failure without Kodi re-running onInit), the Guide must still
    # come back with a focused control.
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window, dialog_cls, playback_cls = _guide_window_with_fakes(conn, None)

        class _NoFocusPlayback(object):
            @classmethod
            def open(cls, **kwargs):
                window._focus_id = 0
                return cls()

        window.playback_cls = _NoFocusPlayback

        window.onClick(CHANNEL_LIST_ID)

        assert window.getFocusId() == CHANNEL_LIST_ID
    finally:
        conn.close()


def test_ok_on_catchup_rail_opens_stubbed_catchup_browser_and_defers_generation_change(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)

        calls = []

        class _FakeCatchup(object):
            @classmethod
            def open(cls, **kwargs):
                calls.append(kwargs)
                conn.execute("UPDATE channel SET name = 'Alpha2' WHERE channel_key = 'a'")
                _bump_generation(2)
                _notify_refreshed(window)
                return cls()

        window.catchup_cls = _FakeCatchup
        list_control = window.getControl(CHANNEL_LIST_ID)
        assert list_control.getListItem(0).getLabel() == 'Alpha'

        window.onClick(win_guide.RAIL_CATCHUP_ID)

        assert calls and calls[0]['conn'] is conn
        assert list_control.getListItem(0).getLabel() == 'Alpha2'
    finally:
        conn.close()


def test_ok_on_settings_rail_opens_addon_settings(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)
        xbmcaddon.open_settings_calls[:] = []

        window.onClick(win_guide.RAIL_SETTINGS_ID)

        assert xbmcaddon.open_settings_calls == [True]
    finally:
        conn.close()


def test_ok_on_settings_rail_defers_generation_change_until_after(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)
        xbmcaddon.open_settings_calls[:] = []

        def _bumping_open_settings(self):
            xbmcaddon.open_settings_calls.append(True)
            conn.execute("UPDATE channel SET name = 'Alpha2' WHERE channel_key = 'a'")
            _bump_generation(2)
            _notify_refreshed(window)

        monkeypatch.setattr(xbmcaddon.Addon, 'openSettings', _bumping_open_settings)
        list_control = window.getControl(CHANNEL_LIST_ID)
        assert list_control.getListItem(0).getLabel() == 'Alpha'

        window.onClick(win_guide.RAIL_SETTINGS_ID)

        assert xbmcaddon.open_settings_calls == [True]
        assert list_control.getListItem(0).getLabel() == 'Alpha2'
    finally:
        conn.close()


def test_skin_pins_rail_and_channel_list_horizontal_navigation_to_self():
    tree = ET.parse(_SKIN_XML)
    controls_by_id = {}
    for control in tree.getroot().iter('control'):
        control_id = control.get('id')
        if control_id is not None:
            controls_by_id[control_id] = control
    for control_id in ('601', '602', '603', '500', '520'):
        control = controls_by_id[control_id]
        assert control.find('onleft').text == control_id
        assert control.find('onright').text == control_id


def test_skin_panel_is_permanent_with_no_open_state():
    with open(_SKIN_XML) as f:
        xml_text = f.read()
    assert 'rail_open' not in xml_text
    assert 'panel_open' not in xml_text
    assert 'panel_mode' not in xml_text
    tree = ET.parse(_SKIN_XML)
    ids = {c.get('id') for c in tree.getroot().iter('control') if c.get('id') is not None}
    assert '521' not in ids
    assert '522' not in ids
    assert '520' in ids


def test_focus_channel_id_outside_filtered_rows_defaults_to_first_row(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        cid_a = _channel(conn, pid, "a", "Alpha", 0)
        _channel(conn, pid, "b", "Beta", 1)
        window = GuideWindow('script-kodimate-guide.xml', '/addon', 'Main', '1080i',
                              conn=conn, favourites=True, focus_channel_id=cid_a)
        window.onInit()
        assert window._channel_rows == []
        assert window.getControl(CHANNEL_LIST_ID).getSelectedPosition() == 0
        assert window._top_row == 0
    finally:
        conn.close()


# -- Programme detail strip (issue #54) --------------------------------------

def test_strip_properties_after_init_for_programme_airing_now(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        cid = _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        conn.execute(
            "UPDATE channel SET catchup_days = 3, logo_url = 'http://x/alpha.png' WHERE id = ?",
            (cid,),
        )
        eid = _epg_source(conn, pid)
        now = datetime.utcnow()
        start = now - timedelta(minutes=30)
        end = now + timedelta(minutes=30)
        _programme(conn, eid, "x1", guide.format_iso(start), guide.format_iso(end),
                   "Current Show", "About the current show")

        class _LocalGuideWindow(GuideWindow):
            _tz = timezone(timedelta(hours=9, minutes=30))

        window = _LocalGuideWindow('script-kodimate-guide.xml', '/addon', 'Main', '1080i', conn=conn)
        window.onInit()

        assert window.getProperty('strip_channel_name') == 'Alpha'
        assert window.getProperty('strip_channel_number') == '0'
        assert window.getProperty('strip_channel_logo') == 'http://x/alpha.png'
        # No programme icon set on this row -> falls back to the channel logo.
        assert window.getProperty('strip_image') == 'http://x/alpha.png'
        assert window.getProperty('strip_title') == 'Current Show'
        assert window.getProperty('strip_description') == 'About the current show'
        assert window.getProperty('strip_live') == '1'
        # A currently-airing programme is 'live', not 'past_playable' --
        # LIVE and Catch-up are mutually exclusive, driven by state.
        assert window.getProperty('strip_catchup') == ''
        assert int(window.getProperty('strip_progress')) > 0
        assert window.getProperty('strip_remaining') != ''

        start_local = guide.utc_to_local(start, tz=window._tz)
        end_local = guide.utc_to_local(end, tz=window._tz)
        expected_times = '%s - %s (1h)' % (start_local.strftime('%H:%M'), end_local.strftime('%H:%M'))
        assert window.getProperty('strip_times') == expected_times
        assert window.getProperty('strip_date').startswith('String 32130')
    finally:
        conn.close()


def test_strip_live_and_catchup_are_mutually_exclusive_for_live_programme(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        cid = _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        conn.execute("UPDATE channel SET catchup_days = 3 WHERE id = ?", (cid,))
        eid = _epg_source(conn, pid)
        now = datetime.utcnow()
        start = now - timedelta(minutes=30)
        end = now + timedelta(minutes=30)
        _programme(conn, eid, "x1", guide.format_iso(start), guide.format_iso(end), "Current Show")
        window = _window(conn)

        assert window.getProperty('strip_live') == '1'
        assert window.getProperty('strip_catchup') == ''
    finally:
        conn.close()


def test_strip_shows_catchup_not_live_for_past_playable_programme(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        cid = _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        conn.execute("UPDATE channel SET catchup_days = 3 WHERE id = ?", (cid,))
        eid = _epg_source(conn, pid)
        window = _window(conn)
        now = datetime.utcnow()
        past_start = now - timedelta(hours=2)
        past_end = now - timedelta(hours=1)
        _programme(conn, eid, "x1", guide.format_iso(past_start), guide.format_iso(past_end),
                   "Past Show")
        window._load_programmes()

        # Put the cursor directly on the past cell rather than depending on
        # viewport-scrolling navigation to land exactly on it.
        window._zone = 'grid'
        window._cursor_time = past_start
        window._update_strip()

        assert window.getProperty('strip_title') == 'Past Show'
        assert window.getProperty('strip_live') == ''
        assert window.getProperty('strip_catchup') == '1'
    finally:
        conn.close()


def test_strip_no_catchup_for_past_programme_without_catchup_window(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        eid = _epg_source(conn, pid)
        window = _window(conn)
        now = datetime.utcnow()
        past_start = now - timedelta(hours=2)
        past_end = now - timedelta(hours=1)
        _programme(conn, eid, "x1", guide.format_iso(past_start), guide.format_iso(past_end),
                   "Past Show")
        window._load_programmes()

        window._zone = 'grid'
        window._cursor_time = past_start
        window._update_strip()

        assert window.getProperty('strip_title') == 'Past Show'
        assert window.getProperty('strip_live') == ''
        assert window.getProperty('strip_catchup') == ''
    finally:
        conn.close()


def test_strip_image_uses_programme_icon_over_channel_logo(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        cid = _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        conn.execute("UPDATE channel SET logo_url = 'http://x/alpha.png' WHERE id = ?", (cid,))
        eid = _epg_source(conn, pid)
        viewport_start = guide.round_down_30_local(datetime.utcnow(), None)
        conn.execute(
            "INSERT INTO programme (epg_source_id, xmltv_channel_id, start, end, title, icon_url) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (eid, "x1", guide.format_iso(viewport_start),
             guide.format_iso(viewport_start + timedelta(hours=1)), "Show A", "http://x/show-a.png"),
        )
        window = _window(conn)

        assert window.getProperty('strip_image') == 'http://x/show-a.png'
    finally:
        conn.close()


def test_strip_image_empty_when_no_icon_and_no_channel_logo(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)

        assert window.getProperty('strip_image') == ''
    finally:
        conn.close()


def test_strip_remaining_falls_back_to_bare_duration_when_string_not_loaded(tmp_path, monkeypatch):
    # issue #54 follow-up: if strings.po's #32129 hasn't loaded yet,
    # getLocalizedString(32129) can return a plain '' with no '%s' --
    # '' % duration raises TypeError in real Python, which must not abort
    # onInit.
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        eid = _epg_source(conn, pid)
        now = datetime.utcnow()
        start = now - timedelta(minutes=30)
        end = now + timedelta(minutes=30)
        _programme(conn, eid, "x1", guide.format_iso(start), guide.format_iso(end), "Current Show")

        real_get = xbmcaddon.Addon.getLocalizedString

        def _flaky_get(self, string_id):
            if string_id == win_guide._STR_REMAINING:
                return ''
            return real_get(self, string_id)

        monkeypatch.setattr(xbmcaddon.Addon, 'getLocalizedString', _flaky_get)

        window = _window(conn)  # must not raise

        assert window.getProperty('strip_remaining') == guide.format_duration_short(30 * 60)
    finally:
        conn.close()


def test_strip_channel_with_no_programmes_shows_no_information(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)

        assert window.getProperty('strip_title') == 'String 32083'
        assert window.getProperty('strip_times') == ''
        assert window.getProperty('strip_live') == ''
        assert window.getProperty('strip_hd') == ''
        assert window.getProperty('strip_catchup') == ''
    finally:
        conn.close()


def test_strip_no_programme_shows_no_badges_even_when_channel_qualifies(tmp_path):
    # issue #54: "A channel with no programme shows 'No information' and no
    # badges" -- an HD-named, catch-up-enabled channel must not leak its HD
    # or Catch-up badge (or LIVE) onto the strip when there is no programme
    # under the cursor.
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        cid = _channel(conn, pid, "a", "Alpha HD", 0)
        conn.execute("UPDATE channel SET catchup_days = 3 WHERE id = ?", (cid,))
        window = _window(conn)

        assert window.getProperty('strip_title') == 'String 32083'
        assert window.getProperty('strip_live') == ''
        assert window.getProperty('strip_hd') == ''
        assert window.getProperty('strip_catchup') == ''
    finally:
        conn.close()


def test_strip_no_badges_in_gap_between_programmes(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        cid = _channel(conn, pid, "a", "Alpha HD", 0, epg_channel_id="x1")
        conn.execute("UPDATE channel SET catchup_days = 3 WHERE id = ?", (cid,))
        eid = _epg_source(conn, pid)
        window = _window(conn)
        viewport_start = window._viewport_start
        # Programme ends well before the cursor time (viewport_start), so
        # the cursor sits in the trailing gap.
        _programme(conn, eid, "x1", guide.format_iso(viewport_start - timedelta(hours=1)),
                   guide.format_iso(viewport_start - timedelta(minutes=30)), "Before")
        window._load_programmes()
        window._relayout()

        assert window.getProperty('strip_title') == 'String 32083'
        assert window.getProperty('strip_live') == ''
        assert window.getProperty('strip_hd') == ''
        assert window.getProperty('strip_catchup') == ''
    finally:
        conn.close()


def test_strip_hd_flag_set_for_hd_channel_name(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha HD", 0, epg_channel_id="x1")
        _channel(conn, pid, "b", "Beta", 1)
        eid = _epg_source(conn, pid)
        window = _window(conn)
        viewport_start = window._viewport_start
        _programme(conn, eid, "x1", guide.format_iso(viewport_start),
                   guide.format_iso(viewport_start + timedelta(hours=1)), "Show A")
        window._load_programmes()
        window._relayout()

        assert window.getProperty('strip_hd') == '1'

        window.getControl(CHANNEL_LIST_ID).selectItem(1)
        window._handle_vertical_move()

        assert window.getProperty('strip_hd') == ''
    finally:
        conn.close()


def test_strip_follows_focused_row_after_down(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        _channel(conn, pid, "b", "Beta", 1, epg_channel_id="x2")
        eid = _epg_source(conn, pid)
        window = _window(conn)
        viewport_start = window._viewport_start
        _programme(conn, eid, "x2", guide.format_iso(viewport_start),
                   guide.format_iso(viewport_start + timedelta(hours=1)), "Beta Show")
        window._load_programmes()
        window._relayout()

        window.getControl(CHANNEL_LIST_ID).selectItem(1)
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_DOWN))

        assert window.getProperty('strip_channel_name') == 'Beta'
        assert window.getProperty('strip_title') == 'Beta Show'
    finally:
        conn.close()


def test_strip_follows_cursor_into_future_cell_on_right(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        eid = _epg_source(conn, pid)
        window = _window(conn)
        viewport_start = window._viewport_start
        _programme(conn, eid, "x1", guide.format_iso(viewport_start),
                   guide.format_iso(viewport_start + timedelta(hours=1)), "Show A")
        _programme(conn, eid, "x1", guide.format_iso(viewport_start + timedelta(hours=1)),
                   guide.format_iso(viewport_start + timedelta(hours=2)), "Show B")
        window._load_programmes()
        window._relayout()

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))  # column -> grid, cell 0
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))  # cell 0 -> cell 1 (future)

        assert window.getProperty('strip_title') == 'Show B'
        assert window.getProperty('strip_live') == ''
        assert window.getProperty('strip_remaining') == ''
    finally:
        conn.close()


def test_strip_shows_first_row_after_applying_group(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn, name="P1")
        gid = conn.execute(
            "INSERT INTO channel_group (provider_id, name, sort_order) VALUES (?, 'Sports', 0)",
            (pid,),
        ).lastrowid
        _channel(conn, pid, "a", "Alpha", 0)
        cid_b = _channel(conn, pid, "b", "Beta", 1, epg_channel_id="x2")
        conn.execute("UPDATE channel SET group_id = ? WHERE id = ?", (gid, cid_b))
        eid = _epg_source(conn, pid)
        window = _window(conn)
        viewport_start = window._viewport_start
        _programme(conn, eid, "x2", guide.format_iso(viewport_start),
                   guide.format_iso(viewport_start + timedelta(hours=1)), "Beta Show")
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))  # column -> panel
        panel = window.getControl(win_guide.PANEL_LIST_ID)
        panel.selectItem(3)  # 'Sports'

        window.onClick(win_guide.PANEL_LIST_ID)

        assert window.getProperty('strip_channel_name') == 'Beta'
        assert window.getProperty('strip_title') == 'Beta Show'
    finally:
        conn.close()


def test_strip_shows_renamed_programme_after_generation_refresh(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        eid = _epg_source(conn, pid)
        window = _window(conn)
        now = datetime.utcnow()
        start = now - timedelta(minutes=30)
        end = now + timedelta(minutes=30)
        pid_row = _programme(conn, eid, "x1", guide.format_iso(start), guide.format_iso(end), "Old Title")
        window._load_programmes()
        window._relayout()

        conn.execute("UPDATE programme SET title = 'New Title' WHERE epg_source_id = ?", (eid,))
        _bump_generation(2)
        _notify_refreshed(window)

        assert window.getProperty('strip_title') == 'New Title'
    finally:
        conn.close()


def test_strip_property_names_appear_in_skin():
    with open(_SKIN_XML) as f:
        xml_text = f.read()
    for prop in (
        'strip_title', 'strip_live', 'strip_hd', 'strip_catchup',
        'strip_times', 'strip_remaining', 'strip_description',
        'strip_channel_logo', 'strip_channel_name', 'strip_channel_number', 'strip_date',
    ):
        assert prop in xml_text
    assert 'System.Time' in xml_text


# -- EPG grid polish (issue #55) ---------------------------------------------

def test_progress_bar_visible_only_for_cell_spanning_now(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        eid = _epg_source(conn, pid)
        window = _window(conn)
        now = datetime.utcnow()
        # Anchor the viewport comfortably ahead of `now` so the "Past show"
        # segment can't be squeezed to nothing by real-clock/30-min-boundary
        # timing luck.
        viewport_start = guide.round_down_30_local(now - timedelta(hours=1), window._tz)
        window._viewport_start = viewport_start
        _programme(conn, eid, "x1", guide.format_iso(viewport_start),
                   guide.format_iso(now - timedelta(minutes=10)), "Past show")
        _programme(conn, eid, "x1", guide.format_iso(now - timedelta(minutes=10)),
                   guide.format_iso(now + timedelta(minutes=10)), "Now show")
        _programme(conn, eid, "x1", guide.format_iso(now + timedelta(minutes=10)),
                   guide.format_iso(viewport_start + timedelta(hours=3)), "Future show")
        window._load_programmes()
        window._relayout()

        cells = window._row_cells[0]
        assert [c['title'] for c in cells] == ['Past show', 'Now show', 'Future show']
        past_cell, now_cell, future_cell = cells
        assert window._progress_pool[0][past_cell['pool_index']].isVisible() is False
        assert window._progress_pool[0][future_cell['pool_index']].isVisible() is False
        progress_image = window._progress_pool[0][now_cell['pool_index']]
        assert progress_image.isVisible() is True
        cell_image = window._pool[0][now_cell['pool_index']][0]
        assert 0 < progress_image.getWidth() < cell_image.getWidth()
    finally:
        conn.close()


def test_progress_bar_hidden_for_no_information_filler_cell(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)
        cells = window._row_cells[0]
        assert cells[0]['filler'] is True
        progress_image = window._progress_pool[0][cells[0]['pool_index']]
        assert progress_image.isVisible() is False
    finally:
        conn.close()


def test_header_now_slot_and_label_set_when_now_in_viewport(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)
        now = datetime.utcnow()
        expected_slot = guide.header_now_slot(window._viewport_start, now)
        assert window.getProperty('guide_header_now') == str(expected_slot)
        assert window.getProperty('guide_now_label') == guide.utc_to_local(now, window._tz).strftime('%H:%M')
    finally:
        conn.close()


def test_header_now_slot_and_label_empty_when_viewport_jumped_away(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)
        window._skip_viewport(guide.SKIP_HOURS)
        assert window.getProperty('guide_header_now') == ''
        assert window.getProperty('guide_now_label') == ''
    finally:
        conn.close()


def test_playing_property_set_only_on_matching_channel_row(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        _channel(conn, pid, "b", "Beta", 1)
        autoplay.remember_last_channel(conn, pid, "b")
        window = _window(conn)
        control = window.getControl(CHANNEL_LIST_ID)
        assert control.getListItem(0).getProperty('playing') == '0'
        assert control.getListItem(1).getProperty('playing') == '1'
    finally:
        conn.close()


def test_playing_property_survives_generation_refresh(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        _channel(conn, pid, "b", "Beta", 1)
        autoplay.remember_last_channel(conn, pid, "b")
        window = _window(conn)

        _bump_generation(2)
        _notify_refreshed(window)

        control = window.getControl(CHANNEL_LIST_ID)
        assert control.getListItem(1).getProperty('playing') == '1'
    finally:
        conn.close()


def test_playing_property_all_zero_when_no_last_channel_stored(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)
        control = window.getControl(CHANNEL_LIST_ID)
        assert control.getListItem(0).getProperty('playing') == '0'
    finally:
        conn.close()


# -- Remote-hint bar, Info action, long-press Favourite (issue #56) ---------

def test_hint_bar_matches_column_zone_after_init(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)
        addon = xbmcaddon.Addon()
        assert window.getProperty('hint_bar') == guide.hint_text('column', addon.getLocalizedString)
    finally:
        conn.close()


def test_hint_bar_matches_grid_zone_after_right(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)
        window._handle_right()
        addon = xbmcaddon.Addon()
        assert window.getProperty('hint_bar') == guide.hint_text('grid', addon.getLocalizedString)
    finally:
        conn.close()


def test_hint_bar_matches_panel_zone_after_left(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)
        window._handle_left()
        addon = xbmcaddon.Addon()
        assert window.getProperty('hint_bar') == guide.hint_text('panel', addon.getLocalizedString)
    finally:
        conn.close()


def test_hint_bar_restored_after_returning_from_panel(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)
        window._handle_left()  # column -> panel
        window._handle_right()  # applies the selected (All channels) filter -> column
        addon = xbmcaddon.Addon()
        assert window.getProperty('hint_bar') == guide.hint_text('column', addon.getLocalizedString)
    finally:
        conn.close()


def test_hint_bar_hidden_during_modal_and_restored_after(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window, dialog_cls, playback_cls = _guide_window_with_fakes(conn, None)
        captured = {}

        class _Playback(_FakePlaybackWindow):
            @classmethod
            def open(cls, **kwargs):
                captured['hint_bar'] = window.getProperty('hint_bar')
                cls.opened_with = kwargs
                return cls()

        window.playback_cls = _Playback

        window.onClick(CHANNEL_LIST_ID)

        assert captured['hint_bar'] == ''
        addon = xbmcaddon.Addon()
        assert window.getProperty('hint_bar') == guide.hint_text('column', addon.getLocalizedString)
    finally:
        conn.close()


def test_skin_hint_bar_property_appears_in_skin():
    with open(_SKIN_XML) as f:
        xml_text = f.read()
    assert 'Window.Property(hint_bar)' in xml_text


def test_hint_bar_slot_properties_after_init(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)
        addon = xbmcaddon.Addon()
        assert window.getProperty('hint1_icon') == 'OK'
        assert window.getProperty('hint1_key') == ''
        assert window.getProperty('hint1_verb') == addon.getLocalizedString(guide.STR_HINT_WATCH)
        assert window.getProperty('hint1_texture') == 'hint_ok.png'
        assert window.getProperty('hint5_key') == addon.getLocalizedString(guide.STR_HINT_LONG_PRESS)
        assert window.getProperty('hint5_texture') == 'hint_star.png'
    finally:
        conn.close()


def test_hint_bar_slot5_cleared_in_grid_zone(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)
        window._handle_right()
        assert window.getProperty('hint2_texture') == 'hint_back.png'
        assert window.getProperty('hint4_texture') == 'hint_info.png'
        assert window.getProperty('hint5_key') == ''
        assert window.getProperty('hint5_icon') == ''
        assert window.getProperty('hint5_texture') == ''
    finally:
        conn.close()


def test_skin_hint_slot_properties_appear_in_skin():
    with open(_SKIN_XML) as f:
        xml_text = f.read()
    for n in range(1, 6):
        for suffix in ('texture', 'key', 'verb'):
            assert 'Window.Property(hint%d_%s)' % (n, suffix) in xml_text


def test_skin_hint_textures_exist():
    media_dir = os.path.join(
        os.path.dirname(_SKIN_XML), '..', 'media',
    )
    for name in (
        'hint_ok.png', 'hint_left.png', 'hint_right.png',
        'hint_lr.png', 'hint_info.png', 'hint_star.png', 'hint_back.png',
    ):
        assert os.path.isfile(os.path.join(media_dir, name)), name


def test_info_on_column_row_opens_dialog_for_current_programme(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        eid = _epg_source(conn, pid)
        window, dialog_cls, playback_cls = _guide_window_with_fakes(conn, None)
        now_snapshot = datetime.utcnow()
        _programme(conn, eid, "x1", guide.format_iso(now_snapshot - timedelta(minutes=10)),
                   guide.format_iso(now_snapshot + timedelta(minutes=10)), "Live Show", "A description")
        window._load_programmes()

        window.onAction(xbmcgui.Action(win_guide._ACTION_SHOW_INFO))

        assert dialog_cls.opened_with is not None
        assert dialog_cls.opened_with['title'] == 'Live Show'
        assert dialog_cls.opened_with['description'] == 'A description'
    finally:
        conn.close()


def test_info_on_cell_opens_dialog_for_that_cells_programme(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        eid = _epg_source(conn, pid)
        window, dialog_cls, playback_cls = _guide_window_with_fakes(conn, None)
        t0 = window._viewport_start
        _programme(conn, eid, "x1", guide.format_iso(t0), guide.format_iso(t0 + timedelta(hours=1)),
                   "Now Show")
        _programme(conn, eid, "x1", guide.format_iso(t0 + timedelta(hours=1)),
                   guide.format_iso(t0 + timedelta(hours=2)), "Future Show")
        window._load_programmes()
        window._zone = 'grid'
        window._relayout()
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))  # cell 0 -> cell 1 (Future Show)

        window.onAction(xbmcgui.Action(win_guide._ACTION_SHOW_INFO))

        assert dialog_cls.opened_with is not None
        assert dialog_cls.opened_with['title'] == 'Future Show'
    finally:
        conn.close()


def test_info_on_row_with_no_current_programme_opens_nothing(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window, dialog_cls, playback_cls = _guide_window_with_fakes(conn, None)

        window.onAction(xbmcgui.Action(win_guide._ACTION_SHOW_INFO))

        assert dialog_cls.opened_with is None
    finally:
        conn.close()


def test_info_on_filler_cell_opens_no_dialog(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window, dialog_cls, playback_cls = _guide_window_with_fakes(conn, None)
        window._zone = 'grid'
        window._relayout()

        window.onAction(xbmcgui.Action(win_guide._ACTION_SHOW_INFO))

        assert dialog_cls.opened_with is None
    finally:
        conn.close()


def test_long_press_ok_toggles_favourite_and_updates_list_item(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)
        control = window.getControl(CHANNEL_LIST_ID)
        assert control.getListItem(0).getProperty('favourite') == '0'

        window.onAction(xbmcgui.Action(win_guide._ACTION_LONG_PRESS_OK))

        rows = channels.list_channels(conn)
        assert rows[0]['favourite'] is True
        control = window.getControl(CHANNEL_LIST_ID)
        assert control.getListItem(0).getProperty('favourite') == '1'
        assert control.getSelectedPosition() == 0

        window.onAction(xbmcgui.Action(win_guide._ACTION_LONG_PRESS_OK))

        rows = channels.list_channels(conn)
        assert rows[0]['favourite'] is False
        control = window.getControl(CHANNEL_LIST_ID)
        assert control.getListItem(0).getProperty('favourite') == '0'
        assert control.getSelectedPosition() == 0
    finally:
        conn.close()


def test_long_press_favourite_removes_row_under_active_favourites_filter(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        _channel(conn, pid, "b", "Beta", 1)
        channels.set_favourite(conn, pid, "a", True)
        channels.set_favourite(conn, pid, "b", True)
        window = GuideWindow('script-kodimate-guide.xml', '/addon', 'Main', '1080i',
                              conn=conn, favourites=True)
        window.onInit()
        window.getControl(CHANNEL_LIST_ID).selectItem(1)

        window.onAction(xbmcgui.Action(win_guide._ACTION_LONG_PRESS_OK))

        control = window.getControl(CHANNEL_LIST_ID)
        assert len(window._channel_rows) == 1
        assert control.getSelectedPosition() == 0
        addon = xbmcaddon.Addon()
        assert window.getProperty('hint_bar') == guide.hint_text('column', addon.getLocalizedString)
    finally:
        conn.close()


