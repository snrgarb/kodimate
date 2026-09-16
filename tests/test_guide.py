from datetime import datetime, timedelta, timezone

from kodimate import guide


def _p(start, end, title):
    return {'start': datetime(2026, 1, 1, *start), 'end': datetime(2026, 1, 1, *end), 'title': title}


def test_cell_layout_proportional_widths():
    viewport_start = datetime(2026, 1, 1, 12, 0)
    programmes = [
        _p((12, 0), (13, 0), 'Hour show'),
        _p((13, 0), (13, 30), 'Half hour show'),
    ]
    cells = guide.cell_layout(programmes, viewport_start, grid_width=1800, no_info_title='No information')
    assert cells[0]['x'] == 0
    assert cells[0]['width'] == 600
    assert cells[1]['x'] == 600
    assert cells[1]['width'] == 300


def test_cell_layout_clips_programme_extending_past_viewport():
    viewport_start = datetime(2026, 1, 1, 12, 0)
    programmes = [_p((11, 0), (14, 0), 'Long show')]
    cells = guide.cell_layout(programmes, viewport_start, grid_width=1800, no_info_title='No information')
    assert len(cells) == 1
    assert cells[0]['x'] == 0
    assert cells[0]['width'] == 1200


def test_cell_layout_no_information_when_no_programmes():
    viewport_start = datetime(2026, 1, 1, 12, 0)
    cells = guide.cell_layout([], viewport_start, grid_width=1800, no_info_title='No information')
    assert len(cells) == 1
    assert cells[0]['title'] == 'No information'
    assert cells[0]['x'] == 0
    assert cells[0]['width'] == 1800


def test_utc_to_local_applies_offset_regardless_of_machine_zone():
    tz = timezone(timedelta(hours=9, minutes=30))
    local = guide.utc_to_local(datetime(2026, 1, 1, 5, 50), tz=tz)
    assert local == datetime(2026, 1, 1, 15, 20)


def test_round_down_30_local_rounds_to_local_half_hour_boundary():
    tz = timezone(timedelta(hours=9, minutes=30))
    # 05:50Z is 15:20 local; the local half-hour boundary at or before it
    # is 15:00 local, which is 05:30Z.
    rounded = guide.round_down_30_local(datetime(2026, 1, 1, 5, 50), tz=tz)
    assert rounded == datetime(2026, 1, 1, 5, 30)


def test_move_cursor_horizontal_moves_to_next_and_previous():
    programmes = [_p((12, 0), (13, 0), 'A'), _p((13, 0), (14, 0), 'B'), _p((14, 0), (15, 0), 'C')]
    assert guide.move_cursor_horizontal(programmes, datetime(2026, 1, 1, 12, 30), 1) == datetime(2026, 1, 1, 13, 0)
    assert guide.move_cursor_horizontal(programmes, datetime(2026, 1, 1, 13, 30), -1) == datetime(2026, 1, 1, 12, 0)


def test_move_cursor_horizontal_returns_none_at_edge():
    programmes = [_p((12, 0), (13, 0), 'A'), _p((13, 0), (14, 0), 'B')]
    assert guide.move_cursor_horizontal(programmes, datetime(2026, 1, 1, 12, 30), -1) is None
    assert guide.move_cursor_horizontal(programmes, datetime(2026, 1, 1, 13, 30), 1) is None


def test_move_cursor_vertical_selects_programme_containing_time():
    target = [_p((12, 0), (13, 0), 'A'), _p((13, 0), (14, 0), 'B')]
    assert guide.move_cursor_vertical(target, datetime(2026, 1, 1, 13, 15)) == datetime(2026, 1, 1, 13, 0)


def test_move_cursor_vertical_returns_none_when_no_programme_at_time():
    assert guide.move_cursor_vertical([], datetime(2026, 1, 1, 13, 15)) is None


def test_needs_viewport_jump_true_when_target_outside_window():
    viewport_start = datetime(2026, 1, 1, 12, 0)
    assert guide.needs_viewport_jump(datetime(2026, 1, 1, 11, 59), viewport_start) is True
    assert guide.needs_viewport_jump(datetime(2026, 1, 1, 15, 0), viewport_start) is True
    assert guide.needs_viewport_jump(datetime(2026, 1, 1, 14, 59), viewport_start) is False


def test_round_down_30():
    assert guide.round_down_30(datetime(2026, 1, 1, 12, 10)) == datetime(2026, 1, 1, 12, 0)
    assert guide.round_down_30(datetime(2026, 1, 1, 12, 45)) == datetime(2026, 1, 1, 12, 30)


def test_compute_top_row_scrolls_minimally_at_edges():
    assert guide.compute_top_row(0, 3, visible_rows=10) == 0
    assert guide.compute_top_row(0, 10, visible_rows=10) == 1
    assert guide.compute_top_row(5, 2, visible_rows=10) == 2


def test_viewport_changed_gate():
    start = datetime(2026, 1, 1, 12, 0)
    assert guide.viewport_changed(0, 0, start, start) is False
    assert guide.viewport_changed(0, 1, start, start) is True
    assert guide.viewport_changed(0, 0, start, start.replace(hour=13)) is True
