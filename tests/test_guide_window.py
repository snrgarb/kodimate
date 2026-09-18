from datetime import datetime, timedelta, timezone

import pytest

from kodimate import db, guide
from kodimate.windows import guide as win_guide
from kodimate.windows.guide import GuideWindow, CHANNEL_LIST_ID
import xbmc
import xbmcgui


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
        assert cells[0]['width'] == _third_of_grid(1620)
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

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))
        assert window._cursor_time == viewport_start + timedelta(hours=1)

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))
        assert window._cursor_time == viewport_start
    finally:
        conn.close()


def test_left_from_leftmost_cell_scrolls_viewport_one_slot(tmp_path):
    # Bug fix: Left/Right must always move (scrolling the viewport by one
    # slot at the cell edge) rather than doing nothing just because there
    # happens to be no earlier programme in the data.
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

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))

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
        for i in range(guide.VISIBLE_ROWS + 1):
            _channel(conn, pid, "c%d" % i, "Chan %d" % i, i)
        window = _window(conn)
        list_control = window.getControl(CHANNEL_LIST_ID)
        list_control.selectItem(guide.VISIBLE_ROWS)

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
        for i in range(guide.VISIBLE_ROWS + 2):
            _channel(conn, pid, "c%d" % i, "Chan%d" % i, i)
        window = _window(conn)
        list_control = window.getControl(CHANNEL_LIST_ID)
        list_control.selectItem(guide.VISIBLE_ROWS)  # scrolls the viewport down
        window._handle_vertical_move()
        old_top_row = window._top_row
        old_offset = list_control.getSelectedPosition() - old_top_row

        conn.execute("UPDATE channel SET name = 'Renamed' WHERE channel_key = 'c%d' " % guide.VISIBLE_ROWS)
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


def test_group_picker_changes_filter_resets_cursor_keeps_viewport(tmp_path, monkeypatch):
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
        window = _window(conn)
        original_viewport = window._viewport_start
        window.getControl(CHANNEL_LIST_ID).selectItem(1)

        monkeypatch.setattr(xbmcgui.Dialog, 'select', lambda self, heading, options: 2)
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_CONTEXT_MENU))

        assert [row['name'] for row in window._channel_rows] == ['Beta']
        assert window.getControl(CHANNEL_LIST_ID).getSelectedPosition() == 0
        assert window._top_row == 0
        assert window._viewport_start == original_viewport
        assert window.getProperty('guide_filter') == 'Sports'
    finally:
        conn.close()


def test_group_picker_cancel_leaves_filter_unchanged(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0)
        window = _window(conn)
        monkeypatch.setattr(xbmcgui.Dialog, 'select', lambda self, heading, options: -1)
        window.onAction(xbmcgui.Action(xbmcgui.ACTION_CONTEXT_MENU))
        assert window._group_id is None
        assert window._favourites is False
        assert window.getProperty('guide_filter') == 'String 32038'
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
