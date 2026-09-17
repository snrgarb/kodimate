# -*- coding: utf-8 -*-
from datetime import datetime, timedelta

from kodimate import catchup


def test_effective_window_days_channel_zero_beats_provider_default():
    assert catchup.effective_window_days(0, 5) is None


def test_effective_window_days_channel_value_wins():
    assert catchup.effective_window_days(3, 5) == 3


def test_effective_window_days_falls_back_to_provider_default():
    assert catchup.effective_window_days(None, 5) == 5


def test_effective_window_days_none_at_both_levels():
    assert catchup.effective_window_days(None, None) is None


def test_effective_window_days_none_when_url_not_supported():
    assert catchup.effective_window_days(3, 5, url_supported=False) is None


def test_effective_window_days_url_supported_defaults_true():
    assert catchup.effective_window_days(3, 5) == 3


def test_cell_state_future():
    now = datetime(2026, 1, 5, 12, 0)
    start = now + timedelta(hours=1)
    end = now + timedelta(hours=2)
    assert catchup.cell_state(start, end, 3, now) == 'future'


def test_cell_state_live():
    now = datetime(2026, 1, 5, 12, 0)
    start = now - timedelta(minutes=30)
    end = now + timedelta(minutes=30)
    assert catchup.cell_state(start, end, 3, now) == 'live'


def test_cell_state_past_playable_within_window():
    now = datetime(2026, 1, 5, 12, 0)
    start = now - timedelta(days=1, hours=2)
    end = now - timedelta(days=1, hours=1)
    assert catchup.cell_state(start, end, 3, now) == 'past_playable'


def test_cell_state_past_unplayable_outside_window():
    now = datetime(2026, 1, 5, 12, 0)
    start = now - timedelta(days=4)
    end = now - timedelta(days=3, hours=23)
    assert catchup.cell_state(start, end, 3, now) == 'past_unplayable'


def test_cell_state_past_unplayable_no_window():
    now = datetime(2026, 1, 5, 12, 0)
    start = now - timedelta(hours=2)
    end = now - timedelta(hours=1)
    assert catchup.cell_state(start, end, None, now) == 'past_unplayable'


def test_cell_state_past_capped_by_retention_even_with_wide_window():
    now = datetime(2026, 1, 5, 12, 0)
    start = now - timedelta(days=8)
    end = now - timedelta(days=7, hours=23)
    assert catchup.cell_state(start, end, 30, now) == 'past_unplayable'


def test_actions_for_live_without_start_over():
    assert catchup.actions_for('live', start_over_ok=False) == ['watch_live']


def test_actions_for_live_with_start_over():
    assert catchup.actions_for('live', start_over_ok=True) == ['watch_live', 'start_over']


def test_actions_for_past_playable():
    assert catchup.actions_for('past_playable') == ['play_catchup']


def test_actions_for_future_is_info_only():
    assert catchup.actions_for('future') == []


def test_actions_for_past_unplayable_is_info_only():
    assert catchup.actions_for('past_unplayable') == []


def test_requested_duration_seconds_within_programme():
    start = datetime(2026, 1, 5, 10, 0)
    end = datetime(2026, 1, 5, 11, 0)
    now = datetime(2026, 1, 5, 12, 0)
    assert catchup.requested_duration_seconds(start, end, now) == 3600


def test_requested_duration_seconds_clamped_to_now_for_live():
    start = datetime(2026, 1, 5, 10, 0)
    end = datetime(2026, 1, 5, 13, 0)
    now = datetime(2026, 1, 5, 10, 30)
    assert catchup.requested_duration_seconds(start, end, now) == 1800


def test_requested_duration_seconds_never_negative():
    start = datetime(2026, 1, 5, 12, 0)
    end = datetime(2026, 1, 5, 13, 0)
    now = datetime(2026, 1, 5, 11, 0)
    assert catchup.requested_duration_seconds(start, end, now) == 0
