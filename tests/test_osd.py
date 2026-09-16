# -*- coding: utf-8 -*-
from datetime import datetime

from kodimate import osd


def test_digit_from_keyboard_action_id():
    assert osd.digit_from_action_id(0xF030) == 0
    assert osd.digit_from_action_id(0xF039) == 9
    assert osd.digit_from_action_id(0xF033) == 3


def test_digit_from_remote_action_id():
    assert osd.digit_from_action_id(58) == 0
    assert osd.digit_from_action_id(67) == 9


def test_digit_from_jump_sms_action_id():
    assert osd.digit_from_action_id(142) == 2
    assert osd.digit_from_action_id(149) == 9


def test_digit_from_action_id_none_for_unrelated():
    assert osd.digit_from_action_id(92) is None
    assert osd.digit_from_action_id(0) is None


def test_resolve_number_returns_first_match_in_list_order():
    rows = [
        {'number': 1, 'channel_key': 'a'},
        {'number': 5, 'channel_key': 'b'},
        {'number': 5, 'channel_key': 'c'},
    ]
    assert osd.resolve_number(rows, 5)['channel_key'] == 'b'


def test_resolve_number_none_when_absent():
    rows = [{'number': 1, 'channel_key': 'a'}]
    assert osd.resolve_number(rows, 9) is None


def _prog(start, end, title):
    return {'start': start, 'end': end, 'title': title}


def test_now_next_finds_current_and_next():
    programmes = [
        _prog(datetime(2026, 1, 1, 11, 0), datetime(2026, 1, 1, 12, 0), 'A'),
        _prog(datetime(2026, 1, 1, 12, 0), datetime(2026, 1, 1, 13, 0), 'B'),
    ]
    now_prog, next_prog = osd.now_next(programmes, datetime(2026, 1, 1, 11, 30))
    assert now_prog['title'] == 'A'
    assert next_prog['title'] == 'B'


def test_now_next_no_current_programme_finds_next_after_now():
    programmes = [
        _prog(datetime(2026, 1, 1, 13, 0), datetime(2026, 1, 1, 14, 0), 'C'),
    ]
    now_prog, next_prog = osd.now_next(programmes, datetime(2026, 1, 1, 12, 0))
    assert now_prog is None
    assert next_prog['title'] == 'C'


def test_now_next_empty_programmes():
    now_prog, next_prog = osd.now_next([], datetime(2026, 1, 1, 12, 0))
    assert now_prog is None
    assert next_prog is None


def test_now_next_later_starting_umbrella_overlap_takes_precedence():
    # Umbrella "Live: ... Race Day" 09:30-16:00 with a 30-minute replay
    # 11:00-11:30 inside it, plus the next replay 11:30-12:00. At 11:15,
    # the later-starting replay should be "now", and "next" should be the
    # following replay -- not the umbrella (which also covers 11:15 and
    # ends much later).
    programmes = [
        _prog(datetime(2026, 1, 1, 9, 30), datetime(2026, 1, 1, 16, 0), 'Live: Race Day'),
        _prog(datetime(2026, 1, 1, 11, 0), datetime(2026, 1, 1, 11, 30), 'Racing Replay: 1'),
        _prog(datetime(2026, 1, 1, 11, 30), datetime(2026, 1, 1, 12, 0), 'Racing Replay: 2'),
    ]
    now_prog, next_prog = osd.now_next(programmes, datetime(2026, 1, 1, 11, 15))
    assert now_prog['title'] == 'Racing Replay: 1'
    assert next_prog['title'] == 'Racing Replay: 2'


def test_progress_fraction_clamped():
    prog = _prog(datetime(2026, 1, 1, 12, 0), datetime(2026, 1, 1, 13, 0), 'A')
    assert osd.progress_fraction(prog, datetime(2026, 1, 1, 12, 15)) == 0.25
    assert osd.progress_fraction(prog, datetime(2026, 1, 1, 11, 0)) == 0.0
    assert osd.progress_fraction(prog, datetime(2026, 1, 1, 14, 0)) == 1.0


def test_format_times_uses_en_dash():
    from datetime import timezone
    text = osd.format_times(
        datetime(2026, 1, 1, 12, 0), datetime(2026, 1, 1, 13, 0), tz=timezone.utc
    )
    assert text == u'12:00–13:00'


def test_back_layer_priority():
    assert osd.back_layer(list_open=True, bar_visible=True) == 'close_list'
    assert osd.back_layer(list_open=False, bar_visible=True) == 'hide_bar'
    assert osd.back_layer(list_open=False, bar_visible=False) == 'leave'
