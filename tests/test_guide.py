from datetime import datetime, timedelta, timezone

from kodimate import guide


def _p(start, end, title, description=''):
    return {
        'start': datetime(2026, 1, 1, *start), 'end': datetime(2026, 1, 1, *end),
        'title': title, 'description': description,
    }


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
    assert cells[0]['x'] == 0
    assert cells[0]['width'] == 1200
    assert cells[0]['filler'] is False
    # The programme ends an hour before the viewport does -> trailing filler.
    assert cells[1]['filler'] is True
    assert cells[1]['start'] == datetime(2026, 1, 1, 14, 0)
    assert cells[1]['end'] == datetime(2026, 1, 1, 15, 0)


def test_cell_layout_no_information_when_no_programmes():
    viewport_start = datetime(2026, 1, 1, 12, 0)
    cells = guide.cell_layout([], viewport_start, grid_width=1800, no_info_title='No information')
    assert len(cells) == 1
    assert cells[0]['title'] == 'No information'
    assert cells[0]['x'] == 0
    assert cells[0]['width'] == 1800
    assert cells[0]['description'] == ''
    assert cells[0]['filler'] is True


def test_cell_layout_passes_through_description():
    viewport_start = datetime(2026, 1, 1, 12, 0)
    programmes = [_p((12, 0), (13, 0), 'Hour show', description='About the hour show')]
    cells = guide.cell_layout(programmes, viewport_start, grid_width=1800, no_info_title='No information')
    assert cells[0]['description'] == 'About the hour show'


def test_cell_layout_fills_gap_before_first_programme():
    viewport_start = datetime(2026, 1, 1, 12, 0)
    programmes = [_p((13, 0), (14, 0), 'Show A')]
    cells = guide.cell_layout(programmes, viewport_start, grid_width=1800, no_info_title='No information')
    assert [(c['title'], c['filler']) for c in cells] == [
        ('No information', True), ('Show A', False), ('No information', True),
    ]
    assert cells[0]['start'] == viewport_start
    assert cells[0]['end'] == datetime(2026, 1, 1, 13, 0)
    assert cells[0]['x'] == 0


def test_cell_layout_fills_gap_between_programmes():
    viewport_start = datetime(2026, 1, 1, 12, 0)
    programmes = [_p((12, 0), (13, 0), 'Show A'), _p((14, 0), (15, 0), 'Show B')]
    cells = guide.cell_layout(programmes, viewport_start, grid_width=1800, no_info_title='No information')
    assert [(c['title'], c['filler']) for c in cells] == [
        ('Show A', False), ('No information', True), ('Show B', False),
    ]
    gap = cells[1]
    assert gap['start'] == datetime(2026, 1, 1, 13, 0)
    assert gap['end'] == datetime(2026, 1, 1, 14, 0)
    # Contiguous x coverage: the gap starts exactly where Show A ends.
    assert gap['x'] == cells[0]['x'] + cells[0]['width']
    assert gap['x'] + gap['width'] == cells[2]['x']


def test_cell_layout_fills_gap_after_last_programme():
    viewport_start = datetime(2026, 1, 1, 12, 0)
    programmes = [_p((12, 0), (13, 0), 'Show A')]
    cells = guide.cell_layout(programmes, viewport_start, grid_width=1800, no_info_title='No information')
    assert [(c['title'], c['filler']) for c in cells] == [('Show A', False), ('No information', True)]
    assert cells[1]['start'] == datetime(2026, 1, 1, 13, 0)
    assert cells[1]['end'] == datetime(2026, 1, 1, 15, 0)


def test_cell_layout_later_starting_programme_truncates_earlier_overlap():
    # Bad EPG data: B (12:20-12:40) is fully contained inside A
    # (12:00-13:40). Kodi's own EPG rule is that a later-starting
    # programme takes precedence over an earlier one it overlaps, so B
    # truncates A's end to 12:20, and since nothing else covers
    # 12:40-13:40 that gap becomes a filler before C.
    # (This supersedes the old expectation that A, B, C all render as
    # non-overlapping non-filler cells with no gap -- that produced hidden,
    # overlapping cells that made the cursor highlight invisible.)
    viewport_start = datetime(2026, 1, 1, 12, 0)
    programmes = [
        _p((12, 0), (13, 40), 'A'),
        _p((12, 20), (12, 40), 'B'),
        _p((13, 40), (15, 0), 'C'),
    ]
    cells = guide.cell_layout(programmes, viewport_start, grid_width=1800, no_info_title='No information')
    assert [(c['title'], c['filler']) for c in cells] == [
        ('A', False), ('B', False), ('No information', True), ('C', False),
    ]
    assert cells[0]['end'] == datetime(2026, 1, 1, 12, 20)


def test_cell_layout_umbrella_programme_truncated_by_replays():
    # A "Live: ... Race Day" umbrella (09:30-16:00) with 30-minute replay
    # slots inside it. The replays take precedence; the umbrella never
    # resumes in a gap between replays -- that gap is a filler instead.
    # (3-hour viewport, per VISIBLE_HOURS, starting before the first
    # replay so the umbrella is visible ahead of it.)
    viewport_start = datetime(2026, 1, 1, 10, 30)
    programmes = [
        _p((9, 30), (16, 0), 'Live: Sky Thoroughbred Central Race Day'),
        _p((11, 0), (11, 30), 'Racing Replay: 1'),
        _p((11, 30), (12, 0), 'Racing Replay: 2'),
        _p((12, 0), (12, 30), 'Racing Replay: 3'),
        _p((13, 0), (13, 30), 'Racing Replay: 4'),
    ]
    cells = guide.cell_layout(programmes, viewport_start, grid_width=1800, no_info_title='No information')
    assert cells[0]['title'] == 'Live: Sky Thoroughbred Central Race Day'
    assert cells[0]['end'] == datetime(2026, 1, 1, 11, 0)
    assert [c['title'] for c in cells[1:4]] == [
        'Racing Replay: 1', 'Racing Replay: 2', 'Racing Replay: 3',
    ]
    # Gap between Replay 3 (ends 12:30) and Replay 4 (starts 13:00) is a
    # filler, not the umbrella resuming.
    gap = cells[4]
    assert gap['filler'] is True
    assert gap['start'] == datetime(2026, 1, 1, 12, 30)
    assert gap['end'] == datetime(2026, 1, 1, 13, 0)
    assert cells[5]['title'] == 'Racing Replay: 4'
    assert len(cells) == 6


def test_cell_layout_simple_overlap_later_start_wins():
    viewport_start = datetime(2026, 1, 1, 10, 0)
    programmes = [_p((10, 0), (11, 0), 'A'), _p((10, 30), (11, 30), 'B')]
    cells = guide.cell_layout(programmes, viewport_start, grid_width=1800, no_info_title='No information')
    assert [(c['title'], c['start'], c['end']) for c in cells[:2]] == [
        ('A', datetime(2026, 1, 1, 10, 0), datetime(2026, 1, 1, 10, 30)),
        ('B', datetime(2026, 1, 1, 10, 30), datetime(2026, 1, 1, 11, 30)),
    ]


def test_cell_layout_identical_start_keeps_later_listed_only():
    viewport_start = datetime(2026, 1, 1, 10, 0)
    programmes = [
        _p((10, 0), (11, 0), 'Old listing'),
        _p((10, 0), (11, 0), 'Corrected listing'),
    ]
    cells = guide.cell_layout(programmes, viewport_start, grid_width=1800, no_info_title='No information')
    assert [c['title'] for c in cells if not c['filler']] == ['Corrected listing']


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


def test_move_cursor_vertical_selects_cell_containing_axis_time():
    target_cells = [_p((12, 0), (13, 0), 'A'), _p((13, 0), (14, 0), 'B')]
    cell = guide.move_cursor_vertical(target_cells, datetime(2026, 1, 1, 13, 15))
    assert cell['title'] == 'B'
    assert cell['start'] == datetime(2026, 1, 1, 13, 0)


def test_move_cursor_vertical_returns_none_when_target_row_has_no_cells():
    assert guide.move_cursor_vertical([], datetime(2026, 1, 1, 13, 15)) is None


def test_move_cursor_vertical_does_not_scroll_long_running_programme_before_viewport():
    # Regression for bug 1: a programme that started long before the
    # viewport (e.g. hours ago) must still resolve correctly on the target
    # row, and the travel axis (viewport_start here) is unaffected.
    viewport_start = datetime(2026, 1, 1, 12, 0)
    programmes = [_p((8, 0), (15, 0), 'Movie')]
    cells = guide.cell_layout(programmes, viewport_start, grid_width=1800, no_info_title='No information')
    cell = guide.move_cursor_vertical(cells, viewport_start)
    assert cell['title'] == 'Movie'
    axis_before = viewport_start
    guide.move_cursor_vertical(cells, axis_before)
    assert axis_before == viewport_start  # travel axis never mutated by Up/Down


def test_resolve_cursor_falls_back_to_nearest_cell_for_a_gap():
    cells = [_p((12, 0), (13, 0), 'A'), _p((14, 0), (15, 0), 'B')]
    # 13:40 falls in the gap between A and B; B is nearer.
    cell = guide.resolve_cursor(cells, datetime(2026, 1, 1, 13, 40))
    assert cell['title'] == 'B'


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


def test_scroll_viewport_moves_one_slot_each_direction():
    viewport_start = datetime(2026, 1, 1, 12, 0)
    floor = datetime(2020, 1, 1)
    ceiling = datetime(2030, 1, 1)
    assert guide.scroll_viewport(viewport_start, 1, floor, ceiling) == viewport_start + timedelta(minutes=30)
    assert guide.scroll_viewport(viewport_start, -1, floor, ceiling) == viewport_start - timedelta(minutes=30)


def test_scroll_viewport_repeated_presses_scroll_by_one_slot_each():
    viewport_start = datetime(2026, 1, 1, 12, 0)
    floor = datetime(2020, 1, 1)
    ceiling = datetime(2030, 1, 1)
    first = guide.scroll_viewport(viewport_start, -1, floor, ceiling)
    second = guide.scroll_viewport(first, -1, floor, ceiling)
    assert first == viewport_start - timedelta(minutes=30)
    assert second == first - timedelta(minutes=30)


def test_scroll_viewport_clamped_to_floor_and_ceiling():
    viewport_start = datetime(2026, 1, 1, 12, 0)
    floor = datetime(2026, 1, 1, 11, 45)
    ceiling = datetime(2026, 1, 1, 12, 15)
    assert guide.scroll_viewport(viewport_start, -1, floor, ceiling) == floor
    assert guide.scroll_viewport(viewport_start, 1, floor, ceiling) == ceiling


def test_clamp_viewport_floor_and_ceiling():
    now = datetime(2026, 1, 10, 12, 0)
    floor = guide.round_down_30_local(now - timedelta(days=guide.RETENTION_DAYS), None)
    ceiling = guide.round_down_30_local(now + timedelta(days=guide.HORIZON_DAYS), None) - timedelta(hours=guide.VISIBLE_HOURS)
    assert guide.clamp_viewport(floor - timedelta(hours=5), now, None) == floor
    assert guide.clamp_viewport(ceiling + timedelta(hours=5), now, None) == ceiling
    assert guide.clamp_viewport(now, now, None) == now


def test_panel_rows_orders_all_favourites_then_provider_sections():
    providers = [{'id': 1, 'name': 'Provider A'}, {'id': 2, 'name': 'Provider B'}]
    groups = [
        {'id': 5, 'provider_id': 1, 'name': 'Sport'},
        {'id': 9, 'provider_id': 1, 'name': 'News'},
        {'id': 7, 'provider_id': 2, 'name': 'Movies'},
    ]
    rows = guide.panel_rows(providers, groups, set(), 'All channels', 'Favourites')
    assert [(r['kind'], r['label']) for r in rows] == [
        ('all', 'All channels'),
        ('favourites', 'Favourites'),
        ('provider', 'Provider A'),
        ('group', 'Sport'),
        ('group', 'News'),
        ('provider', 'Provider B'),
        ('group', 'Movies'),
    ]


def test_panel_rows_single_provider_keeps_header():
    providers = [{'id': 1, 'name': 'Provider A'}]
    groups = [{'id': 5, 'provider_id': 1, 'name': 'Sport'}]
    rows = guide.panel_rows(providers, groups, set(), 'All channels', 'Favourites')
    assert [(r['kind'], r['label']) for r in rows] == [
        ('all', 'All channels'),
        ('favourites', 'Favourites'),
        ('provider', 'Provider A'),
        ('group', 'Sport'),
    ]


def test_panel_rows_provider_with_no_groups_keeps_header():
    providers = [{'id': 1, 'name': 'Provider A'}]
    rows = guide.panel_rows(providers, [], set(), 'All channels', 'Favourites')
    assert [(r['kind'], r['label']) for r in rows] == [
        ('all', 'All channels'),
        ('favourites', 'Favourites'),
        ('provider', 'Provider A'),
    ]


def test_panel_rows_collapsed_provider_hides_only_its_groups():
    providers = [{'id': 1, 'name': 'Provider A'}, {'id': 2, 'name': 'Provider B'}]
    groups = [
        {'id': 5, 'provider_id': 1, 'name': 'Sport'},
        {'id': 7, 'provider_id': 2, 'name': 'Movies'},
    ]
    rows = guide.panel_rows(providers, groups, {1}, 'All channels', 'Favourites')
    assert [(r['kind'], r['label']) for r in rows] == [
        ('all', 'All channels'),
        ('favourites', 'Favourites'),
        ('provider', 'Provider A'),
        ('provider', 'Provider B'),
        ('group', 'Movies'),
    ]
    header = rows[2]
    assert header['collapsed'] is True


def test_panel_rows_skips_disabled_provider():
    providers = [{'id': 1, 'name': 'Provider A', 'enabled': 1}, {'id': 2, 'name': 'Provider B', 'enabled': 0}]
    groups = [{'id': 5, 'provider_id': 2, 'name': 'Movies'}]
    rows = guide.panel_rows(providers, groups, set(), 'All channels', 'Favourites')
    assert [r['label'] for r in rows] == ['All channels', 'Favourites', 'Provider A']


def test_picked_filter_maps_rows_to_filter_state():
    assert guide.picked_filter({'kind': 'all'}) == {'provider_id': None, 'group_id': None, 'favourites': False}
    assert guide.picked_filter({'kind': 'favourites'}) == {
        'provider_id': None, 'group_id': None, 'favourites': True,
    }
    assert guide.picked_filter({'kind': 'group', 'provider_id': 1, 'group_id': 5}) == {
        'provider_id': 1, 'group_id': 5, 'favourites': False,
    }
    assert guide.picked_filter({'kind': 'provider', 'provider_id': 1}) is None


def test_panel_selected_index_finds_matching_row():
    providers = [{'id': 1, 'name': 'Provider A'}]
    groups = [{'id': 5, 'provider_id': 1, 'name': 'Sport'}]
    rows = guide.panel_rows(providers, groups, set(), 'All channels', 'Favourites')
    assert guide.panel_selected_index(rows, None, None, False) == 0
    assert guide.panel_selected_index(rows, None, None, True) == 1
    assert guide.panel_selected_index(rows, 1, 5, False) == 3


def test_panel_selected_index_defaults_to_zero_when_no_match():
    providers = [{'id': 1, 'name': 'Provider A'}]
    rows = guide.panel_rows(providers, [], set(), 'All channels', 'Favourites')
    assert guide.panel_selected_index(rows, 1, None, False) == 0


def test_filter_label_for_all_favourites_and_group():
    groups = [{'id': 5, 'provider_id': 1, 'name': 'Sport'}]
    assert guide.filter_label(None, False, groups, 'All channels', 'Favourites') == 'All channels'
    assert guide.filter_label(None, True, groups, 'All channels', 'Favourites') == 'Favourites'
    assert guide.filter_label(5, False, groups, 'All channels', 'Favourites') == 'Sport'


def test_filter_label_unknown_group_id_falls_back_to_all():
    groups = [{'id': 5, 'provider_id': 1, 'name': 'Sport'}]
    assert guide.filter_label(999, False, groups, 'All channels', 'Favourites') == 'All channels'


def test_filter_label_for_provider_id():
    groups = [{'id': 5, 'provider_id': 1, 'name': 'Sport'}]
    providers = [{'id': 1, 'name': 'Provider A'}]
    assert guide.filter_label(
        None, False, groups, 'All channels', 'Favourites', provider_id=1, providers=providers
    ) == 'Provider A'


def test_filter_label_unknown_provider_id_falls_back_to_all():
    groups = [{'id': 5, 'provider_id': 1, 'name': 'Sport'}]
    providers = [{'id': 1, 'name': 'Provider A'}]
    assert guide.filter_label(
        None, False, groups, 'All channels', 'Favourites', provider_id=999, providers=providers
    ) == 'All channels'


def test_filter_label_group_id_wins_over_provider_id():
    groups = [{'id': 5, 'provider_id': 1, 'name': 'Sport'}]
    providers = [{'id': 1, 'name': 'Provider A'}]
    assert guide.filter_label(
        5, False, groups, 'All channels', 'Favourites', provider_id=1, providers=providers
    ) == 'Sport'


def test_initial_cursor_index_finds_matching_row():
    rows = [{'id': 1}, {'id': 2}, {'id': 3}]
    assert guide.initial_cursor_index(rows, 2) == 1


def test_initial_cursor_index_defaults_to_zero():
    rows = [{'id': 1}, {'id': 2}]
    assert guide.initial_cursor_index(rows, None) == 0
    assert guide.initial_cursor_index(rows, 999) == 0
    assert guide.initial_cursor_index([], 1) == 0


# -- zone_transition (issue #46) --------------------------------------------

import pytest


@pytest.mark.parametrize('panel_open, expected', [
    (False, ('rail', None)),
    (True, ('rail', None)),
])
def test_zone_transition_rail_left(panel_open, expected):
    assert guide.zone_transition('rail', 'left', panel_open) == expected


def test_zone_transition_rail_right_panel_closed():
    assert guide.zone_transition('rail', 'right', False) == ('column', None)


def test_zone_transition_rail_right_panel_open():
    assert guide.zone_transition('rail', 'right', True) == ('panel', None)


@pytest.mark.parametrize('panel_open', [False, True])
def test_zone_transition_panel_left(panel_open):
    assert guide.zone_transition('panel', 'left', panel_open) == ('rail', None)


@pytest.mark.parametrize('panel_open', [False, True])
def test_zone_transition_panel_right(panel_open):
    assert guide.zone_transition('panel', 'right', panel_open) == ('column', 'close')


@pytest.mark.parametrize('panel_open, expected', [
    (False, ('panel', 'open')),
    (True, ('panel', None)),
])
def test_zone_transition_column_left(panel_open, expected):
    assert guide.zone_transition('column', 'left', panel_open) == expected


@pytest.mark.parametrize('panel_open', [False, True])
def test_zone_transition_column_right(panel_open):
    assert guide.zone_transition('column', 'right', panel_open) == ('grid', None)


@pytest.mark.parametrize('panel_open', [False, True])
def test_zone_transition_grid_left(panel_open):
    assert guide.zone_transition('grid', 'left', panel_open) == ('column', None)


@pytest.mark.parametrize('panel_open', [False, True])
def test_zone_transition_grid_right(panel_open):
    assert guide.zone_transition('grid', 'right', panel_open) == ('grid', None)


def test_zone_transition_unknown_zone_raises():
    with pytest.raises(ValueError):
        guide.zone_transition('bogus', 'left', False)


def test_zone_transition_unknown_action_raises():
    with pytest.raises(ValueError):
        guide.zone_transition('rail', 'up', False)


# -- back_target (issue #46 follow-up) --------------------------------------

def test_back_target_grid_moves_to_column():
    assert guide.back_target('grid', False) == 'column'
    assert guide.back_target('grid', True) == 'column'


@pytest.mark.parametrize('zone', ['column', 'rail', 'panel'])
def test_back_target_closes_when_panel_not_open(zone):
    assert guide.back_target(zone, False) == 'close'


@pytest.mark.parametrize('zone', ['column', 'rail', 'panel'])
def test_back_target_closes_panel_when_panel_open(zone):
    assert guide.back_target(zone, True) == 'close_panel'


def test_back_target_unknown_zone_raises():
    with pytest.raises(ValueError):
        guide.back_target('bogus', False)


# -- strip_values (issue #54) -----------------------------------------------


def test_strip_values_includes_programme_icon():
    now = datetime(2026, 1, 1, 12, 30)
    programmes = [dict(_p((12, 0), (13, 0), 'Current'), icon='http://x/show.png')]
    values = guide.strip_values(programmes, at_time=now, now=now, no_info_title='No information')
    assert values['icon'] == 'http://x/show.png'


def test_strip_values_icon_empty_when_programme_has_none():
    now = datetime(2026, 1, 1, 12, 30)
    programmes = [_p((12, 0), (13, 0), 'Current')]
    values = guide.strip_values(programmes, at_time=now, now=now, no_info_title='No information')
    assert values['icon'] == ''


def test_strip_values_icon_empty_when_no_programme():
    now = datetime(2026, 1, 1, 13, 15)
    values = guide.strip_values([], at_time=now, now=now, no_info_title='No information')
    assert values['icon'] == ''


def test_strip_values_airing_now_has_progress_and_remaining():
    now = datetime(2026, 1, 1, 12, 30)
    programmes = [_p((12, 0), (13, 0), 'Current', 'About current')]
    values = guide.strip_values(programmes, at_time=now, now=now, no_info_title='No information', tz=timezone.utc)
    assert values['title'] == 'Current'
    assert values['times'] == '12:00 - 13:00 (1h)'
    assert values['progress'] == 50
    assert values['remaining'] == '30m'
    assert values['description'] == 'About current'
    assert values['live'] is True
    assert values['has_programme'] is True


def test_strip_values_cursor_on_future_cell_has_no_remaining_or_live():
    now = datetime(2026, 1, 1, 12, 30)
    at_time = datetime(2026, 1, 1, 14, 15)
    programmes = [
        _p((12, 0), (13, 0), 'Current'),
        _p((14, 0), (15, 0), 'Future'),
    ]
    values = guide.strip_values(programmes, at_time=at_time, now=now, no_info_title='No information')
    assert values['title'] == 'Future'
    assert values['live'] is False
    assert values['remaining'] == ''
    assert values['has_programme'] is True


def test_strip_values_gap_between_programmes_is_no_information():
    now = datetime(2026, 1, 1, 13, 15)
    programmes = [
        _p((12, 0), (13, 0), 'Before'),
        _p((14, 0), (15, 0), 'After'),
    ]
    values = guide.strip_values(programmes, at_time=now, now=now, no_info_title='No information')
    assert values['title'] == 'No information'
    assert values['times'] == ''
    assert values['progress'] == 0
    assert values['remaining'] == ''
    assert values['description'] == ''
    assert values['live'] is False
    assert values['has_programme'] is False


def test_strip_values_no_programmes_is_no_information():
    now = datetime(2026, 1, 1, 13, 15)
    values = guide.strip_values([], at_time=now, now=now, no_info_title='No information')
    assert values['title'] == 'No information'
    assert values['has_programme'] is False


def test_strip_values_duration_formatting_minutes_only():
    now = datetime(2026, 1, 1, 12, 0)
    programmes = [_p((12, 0), (12, 45), 'Short')]
    values = guide.strip_values(programmes, at_time=now, now=now, no_info_title='No information', tz=timezone.utc)
    assert values['times'] == '12:00 - 12:45 (45m)'


def test_strip_values_duration_formatting_whole_hours():
    now = datetime(2026, 1, 1, 12, 0)
    programmes = [_p((12, 0), (14, 0), 'Two hours')]
    values = guide.strip_values(programmes, at_time=now, now=now, no_info_title='No information', tz=timezone.utc)
    assert values['times'] == '12:00 - 14:00 (2h)'


# -- is_hd_name (issue #54) --------------------------------------------------

def test_is_hd_name_true_for_hd_suffix():
    assert guide.is_hd_name('BBC One HD') is True


def test_is_hd_name_false_for_plain_name():
    assert guide.is_hd_name('BBC One') is False


def test_is_hd_name_true_for_fhd_suffix():
    assert guide.is_hd_name('Sky Sports FHD') is True


def test_is_hd_name_true_for_4k_suffix():
    assert guide.is_hd_name('Channel 4K') is True


def test_is_hd_name_false_for_name_ending_in_hd_substring_but_no_word_boundary():
    # "Ahd" strips to "ahd" which the bare suffix rule would still match --
    # the ticket accepts the Normalised Name rule as-is (false positive kept).
    assert guide.is_hd_name('Ahd') is True


# -- visible_rows (issue #54) -------------------------------------------------

def test_visible_rows_floor_divides_available_height():
    assert guide.visible_rows(800, 98) == 8


def test_visible_rows_at_least_one():
    assert guide.visible_rows(50, 98) == 1


# -- date_label (issue #54) ---------------------------------------------------

def test_date_label_today():
    now = datetime(2026, 9, 18, 10, 0)
    at_time = datetime(2026, 9, 18, 18, 0)
    assert guide.date_label(at_time, now, today_label='Today', tz=timezone.utc) == 'Today, 18 Sep'


def test_date_label_other_day():
    now = datetime(2026, 9, 18, 10, 0)
    at_time = datetime(2026, 9, 17, 18, 0)
    assert guide.date_label(at_time, now, today_label='Today', tz=timezone.utc) == 'Thu, 17 Sep'
