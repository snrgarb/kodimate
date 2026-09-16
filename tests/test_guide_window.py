from datetime import datetime, timedelta

from kodimate import db, guide
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


def _programme(conn, epg_source_id, xmltv_channel_id, start, end, title):
    conn.execute(
        "INSERT INTO programme (epg_source_id, xmltv_channel_id, start, end, title) "
        "VALUES (?, ?, ?, ?, ?)",
        (epg_source_id, xmltv_channel_id, start, end, title),
    )


def _window(conn):
    window = GuideWindow('script-kodimate-guide.xml', '/addon', 'Main', '1080i', conn=conn)
    window.onInit()
    return window


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


def test_edge_cell_fades_and_inner_cell_slides_on_viewport_jump(tmp_path):
    conn = _conn(tmp_path)
    try:
        pid = _provider(conn)
        _channel(conn, pid, "a", "Alpha", 0, epg_channel_id="x1")
        eid = _epg_source(conn, pid)
        window = _window(conn)
        t0 = window._viewport_start
        _programme(conn, eid, "x1", guide.format_iso(t0 - timedelta(minutes=30)),
                   guide.format_iso(t0), "Before")
        _programme(conn, eid, "x1", guide.format_iso(t0), guide.format_iso(t0 + timedelta(hours=1)),
                   "Current")
        window._load_programmes()
        window._relayout()

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_LEFT))

        assert window._viewport_start == t0 - timedelta(minutes=30)
        edge_image, _edge_label = window._pool[0][0]
        inner_image, _inner_label = window._pool[0][1]
        assert edge_image._animations and 'effect=fade' in edge_image._animations[0][1]
        assert 'delay=200' in edge_image._animations[0][1]
        assert inner_image._animations and 'effect=slide' in inner_image._animations[0][1]
        assert 'delay=' not in inner_image._animations[0][1]
        # The gate: a real viewport jump flips the guide_anim property.
        assert window.getProperty('guide_anim') == '1'
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

        image_a, _ = window._pool[0][0]
        image_b, _ = window._pool[0][1]
        image_a._animations = ['sentinel']
        image_b._animations = ['sentinel']
        anim_before = window.getProperty('guide_anim')

        window.onAction(xbmcgui.Action(xbmcgui.ACTION_MOVE_RIGHT))

        assert image_a._animations == ['sentinel']
        assert image_b._animations == ['sentinel']
        assert window.getProperty('guide_anim') == anim_before
    finally:
        conn.close()
