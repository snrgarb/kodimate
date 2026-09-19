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




def test_channel_panel_rows_preserves_order_and_flags_playing_row():
    channel_rows = [
        {'id': 1, 'number': 1, 'name': 'Alpha', 'logo_url': 'http://x/a.png',
         'provider_id': 1, 'channel_key': 'a'},
        {'id': 2, 'number': 2, 'name': 'Beta', 'logo_url': None,
         'provider_id': 1, 'channel_key': 'b'},
    ]
    rows = guide.channel_panel_rows(channel_rows, (1, 'b'))
    assert rows == [
        {'id': 1, 'number': 1, 'name': 'Alpha', 'logo': 'http://x/a.png', 'playing': False},
        {'id': 2, 'number': 2, 'name': 'Beta', 'logo': '', 'playing': True},
    ]


def test_channel_panel_rows_none_playing_key_flags_nothing():
    channel_rows = [
        {'id': 1, 'number': 1, 'name': 'Alpha', 'logo_url': None,
         'provider_id': 1, 'channel_key': 'a'},
    ]
    rows = guide.channel_panel_rows(channel_rows, None)
    assert rows[0]['playing'] is False


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


def test_zone_transition_rail_left():
    assert guide.zone_transition('rail', 'left') == 'rail'


def test_zone_transition_rail_right():
    assert guide.zone_transition('rail', 'right') == 'panel'


def test_zone_transition_panel_left():
    assert guide.zone_transition('panel', 'left') == 'rail'


def test_zone_transition_panel_right():
    assert guide.zone_transition('panel', 'right') == 'column'


def test_zone_transition_column_left():
    assert guide.zone_transition('column', 'left') == 'panel'


def test_zone_transition_column_right():
    assert guide.zone_transition('column', 'right') == 'grid'


def test_zone_transition_grid_left():
    assert guide.zone_transition('grid', 'left') == 'column'


def test_zone_transition_grid_right():
    assert guide.zone_transition('grid', 'right') == 'grid'


def test_zone_transition_unknown_zone_raises():
    with pytest.raises(ValueError):
        guide.zone_transition('bogus', 'left')


def test_zone_transition_unknown_action_raises():
    with pytest.raises(ValueError):
        guide.zone_transition('rail', 'up')


# -- back_target (issue #46 follow-up) --------------------------------------

def test_back_target_grid_moves_to_column():
    assert guide.back_target('grid') == 'column'


@pytest.mark.parametrize('zone', ['column', 'rail', 'panel'])
def test_back_target_closes(zone):
    assert guide.back_target(zone) == 'close'


def test_back_target_unknown_zone_raises():
    with pytest.raises(ValueError):
        guide.back_target('bogus')


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


# -- cell_time_range (issue #65) ----------------------------------------------

def test_cell_time_range_real_cell():
    cell = {'start': datetime(2026, 1, 1, 12, 0), 'end': datetime(2026, 1, 1, 13, 0), 'filler': False}
    assert guide.cell_time_range(cell, tz=timezone.utc) == '12:00 - 13:00'


def test_cell_time_range_filler_cell_is_empty():
    cell = {'start': datetime(2026, 1, 1, 12, 0), 'end': datetime(2026, 1, 1, 13, 0), 'filler': True}
    assert guide.cell_time_range(cell, tz=timezone.utc) == ''


def test_cell_time_range_crossing_local_midnight():
    tz = timezone(timedelta(hours=2))
    cell = {'start': datetime(2026, 1, 1, 21, 30), 'end': datetime(2026, 1, 1, 22, 30), 'filler': False}
    assert guide.cell_time_range(cell, tz=tz) == '23:30 - 00:30'


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


def test_visible_rows_dense_row_height_fits_eleven_rows():
    assert guide.visible_rows(740, 66) == 11


# -- date_label (issue #54) ---------------------------------------------------

def test_date_label_today():
    now = datetime(2026, 9, 18, 10, 0)
    at_time = datetime(2026, 9, 18, 18, 0)
    assert guide.date_label(at_time, now, today_label='Today', tz=timezone.utc) == 'Today, 18 Sep'


def test_date_label_other_day():
    now = datetime(2026, 9, 18, 10, 0)
    at_time = datetime(2026, 9, 17, 18, 0)
    assert guide.date_label(at_time, now, today_label='Today', tz=timezone.utc) == 'Thu, 17 Sep'


# -- cell_layout progress / header_now_slot (issue #55) ----------------------

def test_cell_layout_progress_none_when_now_not_given():
    viewport_start = datetime(2026, 1, 1, 12, 0)
    programmes = [_p((12, 0), (13, 0), 'Show A')]
    cells = guide.cell_layout(programmes, viewport_start, grid_width=1800, no_info_title='No information')
    assert cells[0]['progress'] is None


def test_cell_layout_progress_for_current_cell():
    viewport_start = datetime(2026, 1, 1, 12, 0)
    programmes = [_p((12, 0), (13, 0), 'Show A')]
    now = datetime(2026, 1, 1, 12, 15)
    cells = guide.cell_layout(
        programmes, viewport_start, grid_width=1800, no_info_title='No information', now=now,
    )
    assert cells[0]['progress'] == 0.25


def test_cell_layout_progress_none_for_past_and_future_cells():
    viewport_start = datetime(2026, 1, 1, 12, 0)
    programmes = [
        _p((12, 0), (12, 30), 'Past show'),
        _p((12, 30), (13, 0), 'Now show'),
        _p((13, 0), (13, 30), 'Future show'),
    ]
    now = datetime(2026, 1, 1, 12, 45)
    cells = guide.cell_layout(
        programmes, viewport_start, grid_width=1800, no_info_title='No information', now=now,
    )
    assert cells[0]['progress'] is None
    assert cells[1]['progress'] == 0.5
    assert cells[2]['progress'] is None


def test_cell_layout_filler_progress_always_none():
    viewport_start = datetime(2026, 1, 1, 12, 0)
    now = datetime(2026, 1, 1, 12, 15)
    cells = guide.cell_layout(
        [], viewport_start, grid_width=1800, no_info_title='No information', now=now,
    )
    assert cells[0]['filler'] is True
    assert cells[0]['progress'] is None


def test_cell_layout_progress_recomputed_when_truncated_by_later_programme():
    # A (12:00-13:00) is truncated to 12:00-12:30 by later-starting B
    # (12:30-12:45). now=12:40 falls in B, not in A's truncated span, so
    # A's progress must be None (not the fraction computed against its
    # original, untruncated end) and B's progress is 2/3.
    viewport_start = datetime(2026, 1, 1, 12, 0)
    programmes = [_p((12, 0), (13, 0), 'A'), _p((12, 30), (12, 45), 'B')]
    now = datetime(2026, 1, 1, 12, 40)
    cells = guide.cell_layout(
        programmes, viewport_start, grid_width=1800, no_info_title='No information', now=now,
    )
    assert cells[0]['title'] == 'A'
    assert cells[0]['end'] == datetime(2026, 1, 1, 12, 30)
    assert cells[0]['progress'] is None
    assert cells[1]['title'] == 'B'
    assert cells[1]['progress'] == 2.0 / 3.0


def test_cell_layout_progress_for_now_inside_truncated_span():
    # Mirror case: now falls inside A's truncated (not original) span, so
    # A gets progress against 12:00-12:30, and B (not yet reached) is None.
    viewport_start = datetime(2026, 1, 1, 12, 0)
    programmes = [_p((12, 0), (13, 0), 'A'), _p((12, 30), (12, 45), 'B')]
    now = datetime(2026, 1, 1, 12, 15)
    cells = guide.cell_layout(
        programmes, viewport_start, grid_width=1800, no_info_title='No information', now=now,
    )
    assert cells[0]['title'] == 'A'
    assert cells[0]['progress'] == 0.5
    assert cells[1]['title'] == 'B'
    assert cells[1]['progress'] is None


def test_cell_layout_progress_clipped_at_viewport_start():
    # Programme starts before the viewport (11:00), so its visible span is
    # clipped to 12:00-13:00. Progress must be the fraction of that visible
    # span (0.5 at 12:30), not of the programme's unclipped 11:00-13:00
    # span (which would be 0.75) -- otherwise the progress bar overshoots
    # the now-line.
    viewport_start = datetime(2026, 1, 1, 12, 0)
    programmes = [_p((11, 0), (13, 0), 'A')]
    now = datetime(2026, 1, 1, 12, 30)
    cells = guide.cell_layout(
        programmes, viewport_start, grid_width=1800, no_info_title='No information', now=now,
    )
    assert cells[0]['title'] == 'A'
    assert cells[0]['progress'] == 0.5


def test_header_now_slot_in_first_slot():
    viewport_start = datetime(2026, 1, 1, 12, 0)
    assert guide.header_now_slot(viewport_start, datetime(2026, 1, 1, 12, 10)) == 0


def test_header_now_slot_in_later_slot():
    viewport_start = datetime(2026, 1, 1, 12, 0)
    assert guide.header_now_slot(viewport_start, datetime(2026, 1, 1, 13, 45)) == 3


def test_header_now_slot_at_viewport_end_is_none():
    viewport_start = datetime(2026, 1, 1, 12, 0)
    assert guide.header_now_slot(viewport_start, datetime(2026, 1, 1, 15, 0)) is None


def test_header_now_slot_before_viewport_is_none():
    viewport_start = datetime(2026, 1, 1, 12, 0)
    assert guide.header_now_slot(viewport_start, datetime(2026, 1, 1, 11, 59)) is None


# -- Remote-hint bar (issue #56) ----------------------------------------------

def test_visible_rows_accounts_for_hint_bar_budget():
    assert guide.visible_rows(740, 98) == 7


def test_hint_text_column_zone():
    assert guide.hint_text('column', str) == (
        u'OK 32131 · ← 32132 · → 32133 · Info 32134 · 32136 32135'
    )


def test_hint_text_grid_zone():
    # The grid's Left/Right hint is one bidirectional glyph (↔), not the
    # column zone's two separate arrows -- updated for issue #56 follow-up.
    assert guide.hint_text('grid', str) == (
        u'OK 32131 · ↔ 32133 · Info 32134 · 32136 32135'
    )


def test_hint_text_rail_zone():
    assert guide.hint_text('rail', str) == u'OK 32137'


def test_hint_text_panel_zone():
    assert guide.hint_text('panel', str) == u'OK 32138'


def test_hint_slots_column():
    slots = guide.hint_slots('column', str)
    assert slots == [
        {'icon': u'OK', 'key': u'', 'verb': '32131', 'texture': u'hint_ok.png'},
        {'icon': u'←', 'key': u'', 'verb': '32132', 'texture': u'hint_left.png'},
        {'icon': u'→', 'key': u'', 'verb': '32133', 'texture': u'hint_right.png'},
        {'icon': u'i', 'key': u'Info', 'verb': '32134', 'texture': u'hint_info.png'},
        {'icon': u'★', 'key': '32136', 'verb': '32135', 'texture': u'hint_star.png'},
    ]


def test_hint_slots_grid():
    slots = guide.hint_slots('grid', str)
    assert slots == [
        {'icon': u'OK', 'key': u'', 'verb': '32131', 'texture': u'hint_ok.png'},
        {'icon': u'↔', 'key': u'', 'verb': '32133', 'texture': u'hint_lr.png'},
        {'icon': u'i', 'key': u'Info', 'verb': '32134', 'texture': u'hint_info.png'},
        {'icon': u'★', 'key': '32136', 'verb': '32135', 'texture': u'hint_star.png'},
    ]


def test_hint_slots_panel():
    assert guide.hint_slots('panel', str) == [
        {'icon': u'OK', 'key': u'', 'verb': '32138', 'texture': u'hint_ok.png'},
    ]


def test_hint_slots_panel_channels_mode_explicit():
    assert guide.hint_slots('panel', str, 'channels') == [
        {'icon': u'OK', 'key': u'', 'verb': '32138', 'texture': u'hint_ok.png'},
    ]


def test_hint_slots_panel_groups_mode():
    assert guide.hint_slots('panel', str, 'groups') == [
        {'icon': u'OK', 'key': u'', 'verb': '32132', 'texture': u'hint_ok.png'},
    ]


def test_hint_slots_column_second_slot_is_left_groups():
    slots = guide.hint_slots('column', str)
    assert slots[1] == {'icon': u'←', 'key': u'', 'verb': '32132', 'texture': u'hint_left.png'}


def test_dim_color_scales_rgb_keeps_alpha():
    assert guide.dim_color('FF2A2A2A', 0.5) == 'FF151515'


def test_dim_color_clamps_at_255():
    assert guide.dim_color('FFFFFFFF', 2.0) == 'FFFFFFFF'


def test_cell_progress_fraction_within_span():
    cell = {'start': datetime(2026, 1, 1, 12, 0), 'end': datetime(2026, 1, 1, 13, 0), 'filler': False}
    now = datetime(2026, 1, 1, 12, 30)
    viewport_start = datetime(2026, 1, 1, 12, 0)
    viewport_end = datetime(2026, 1, 1, 15, 0)
    assert guide.cell_progress(cell, now, viewport_start, viewport_end) == 0.5


def test_cell_progress_none_at_or_after_end():
    cell = {'start': datetime(2026, 1, 1, 12, 0), 'end': datetime(2026, 1, 1, 13, 0), 'filler': False}
    viewport_start = datetime(2026, 1, 1, 12, 0)
    viewport_end = datetime(2026, 1, 1, 15, 0)
    assert guide.cell_progress(cell, datetime(2026, 1, 1, 13, 0), viewport_start, viewport_end) is None
    assert guide.cell_progress(cell, datetime(2026, 1, 1, 13, 30), viewport_start, viewport_end) is None


def test_cell_progress_none_for_filler():
    cell = {'start': datetime(2026, 1, 1, 12, 0), 'end': datetime(2026, 1, 1, 13, 0), 'filler': True}
    viewport_start = datetime(2026, 1, 1, 12, 0)
    viewport_end = datetime(2026, 1, 1, 15, 0)
    assert guide.cell_progress(cell, datetime(2026, 1, 1, 12, 30), viewport_start, viewport_end) is None


def test_cell_progress_matches_cell_layout_when_start_precedes_viewport():
    viewport_start = datetime(2026, 1, 1, 12, 0)
    now = datetime(2026, 1, 1, 12, 30)
    programmes = [{'title': 'Ongoing', 'start': datetime(2026, 1, 1, 10, 0),
                   'end': datetime(2026, 1, 1, 13, 0)}]
    cells = guide.cell_layout(programmes, viewport_start, 1440, 'No info', now=now)
    cell = cells[0]
    fraction = guide.cell_progress(cell, now, viewport_start, guide.viewport_end(viewport_start))
    assert fraction == cell['progress']
    assert fraction == 0.5
