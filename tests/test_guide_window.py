from datetime import datetime, timedelta, timezone

from kodimate import db, guide
from kodimate.windows import guide as win_guide
from kodimate.windows.guide import GuideWindow, CHANNEL_LIST_ID
import xbmc
import xbmcgui


def _conn(tmp_path):
    return db.open_db(str(tmp_path / "kodimate.db"))


def _provider(conn, name="P1"):
    return conn.execute(
        "INSERT INTO provider (kind, name, enabled, sort_order) VALUES ('m3u', ?, 1, 0)", (name,)
    ).lastrowid


def _channel(conn, provider_id, channel_key, name, position, epg_channel_id=None):
    cursor = conn.execute(
        "INSERT INTO channel (provider_id, channel_key, name, normalised_name, stream_url, "
        "position, epg_channel_id) VALUES (?, ?, ?, ?, 'http://x', ?, ?)",
        (provider_id, channel_key, name, name.lower(), position, epg_channel_id),
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
        assert len(cells) == 1
        assert cells[0]['title'] == 'Show A'
        assert cells[0]['width'] == _third_of_grid(1620)
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


def test_left_beyond_first_programme_is_a_no_op(tmp_path):
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
        assert window._cursor_time == viewport_start
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


def test_relayout_highlights_nearest_cell_when_axis_in_gap(tmp_path):
    # Review fix 1: a real gap between two programmes on the focused row
    # (not the "No information" whole-row case) must still resolve to the
    # nearest cell, not leave the row with no highlighted cell.
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
        # 50 minutes in: 20 minutes past A's end, 10 minutes before B's
        # start -- B is nearer.
        window._cursor_time = t0 + timedelta(minutes=50)
        window._relayout()

        cells = window._row_cells[0]
        b_cell = next(c for c in cells if c['title'] == 'B')
        _b_image, b_label, _b_desc = window._pool[0][b_cell['pool_index']]
        assert b_label.getLabel() == '[COLOR FFFFFFFF]B[/COLOR]'
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


def test_right_onto_far_off_screen_target_after_one_slot_scroll_lands_on_last_visible_cell(tmp_path):
    # Review fix 3: when even a one-slot scroll doesn't bring the target
    # programme into view, the travel axis must land on a real on-screen
    # cell (here, the still-airing previous programme's raw start), not an
    # arbitrary offset before the new viewport's end. The real EPG-loading
    # window buffer (VISIBLE_HOURS either side) never lets a genuinely
    # off-screen-even-after-one-slot target load in practice, so this
    # seeds the programme data directly to exercise the clamp.
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        window = _window(conn)
        t0 = window._viewport_start
        channel_id = window._channel_rows[0]['id']
        window._programmes_by_channel = {
            channel_id: [
                {'start': t0, 'end': t0 + timedelta(hours=7), 'title': 'Long Show'},
                {'start': t0 + timedelta(hours=7), 'end': t0 + timedelta(hours=8), 'title': 'Next Show'},
            ]
        }
        window._load_programmes = lambda: None  # keep the seeded wide-range data
        window._relayout()

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))

        assert window._viewport_start == t0 + timedelta(minutes=30)
        assert window._cursor_time == t0
    finally:
        conn.close()


def test_left_at_retention_floor_off_screen_target_is_a_no_op(tmp_path):
    # A clamped scroll that lands exactly back on the current viewport_start
    # (Left at the retention floor) must not relayout: nothing moved, so
    # programmes should not be reloaded and no animation should fire.
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

        calls = []
        window._load_programmes = lambda: calls.append(1)
        anim_parity_before = window._anim_parity

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))

        assert window._viewport_start == floor
        assert window._cursor_time == floor
        assert calls == []
        assert window._anim_parity == anim_parity_before
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
    # slide or fade animation -- unlike vertical (row) moves, which still
    # animate. A programme starting before the new viewport must also
    # clip to the grid's left edge (x=0) rather than spill off-screen.
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
        anim_before = window.getProperty('guide_anim')

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))

        assert window._viewport_start == t0 - timedelta(minutes=30)
        edge_cell = window._row_cells[0][0]
        assert edge_cell['title'] == 'Before'
        assert edge_cell['x'] == 0
        edge_image, edge_label, _edge_desc = window._pool[0][0]
        assert edge_image._animations == []
        assert edge_label._animations == []
        assert window.getProperty('guide_anim') == anim_before
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
        anim_before = window.getProperty('guide_anim')

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))

        assert image_a._animations == ['sentinel']
        assert image_b._animations == ['sentinel']
        assert window.getProperty('guide_anim') == anim_before
    finally:
        conn.close()
