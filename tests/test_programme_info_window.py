# -*- coding: utf-8 -*-
from kodimate.windows.programme_info import (
    ProgrammeInfoDialog, WATCH_LIVE_ID, START_OVER_ID, PLAY_CATCHUP_ID, CLOSE_ID,
)
import xbmcgui


def _dialog(**overrides):
    kwargs = dict(title='Old Show', times='10:00-11:00', description='About the show',
                  actions=['play_catchup'])
    kwargs.update(overrides)
    return ProgrammeInfoDialog('script-kodimate-programme-info.xml', '/addon', 'Main', '1080i', **kwargs)


def test_sets_title_times_description_properties():
    window = _dialog()
    window.onInit()

    assert window.getProperty('title') == 'Old Show'
    assert window.getProperty('times') == '10:00-11:00'
    assert window.getProperty('description') == 'About the show'


def test_action_visibility_properties_for_live_state():
    window = _dialog(actions=['watch_live', 'start_over'])
    window.onInit()

    assert window.getProperty('has_watch_live') == '1'
    assert window.getProperty('has_start_over') == '1'
    assert window.getProperty('has_play_catchup') == '0'


def test_action_visibility_properties_for_past_playable_state():
    window = _dialog(actions=['play_catchup'])
    window.onInit()

    assert window.getProperty('has_watch_live') == '0'
    assert window.getProperty('has_start_over') == '0'
    assert window.getProperty('has_play_catchup') == '1'


def test_info_only_has_no_action_visible_and_focuses_close():
    window = _dialog(actions=[])
    window.onInit()

    assert window.getProperty('has_watch_live') == '0'
    assert window.getProperty('has_start_over') == '0'
    assert window.getProperty('has_play_catchup') == '0'
    assert window.getFocusId() == CLOSE_ID


def test_focuses_first_available_action():
    window = _dialog(actions=['start_over'])
    window.onInit()

    assert window.getFocusId() == START_OVER_ID


def test_click_watch_live_sets_result_and_closes():
    window = _dialog(actions=['watch_live'])
    window.onInit()

    window.onClick(WATCH_LIVE_ID)

    assert window.result == 'watch_live'


def test_click_play_catchup_sets_result():
    window = _dialog(actions=['play_catchup'])
    window.onInit()

    window.onClick(PLAY_CATCHUP_ID)

    assert window.result == 'play_catchup'


def test_click_close_sets_result_none():
    window = _dialog(actions=['play_catchup'])
    window.onInit()

    window.onClick(CLOSE_ID)

    assert window.result is None


def test_back_closes_with_result_none():
    window = _dialog(actions=['play_catchup'])
    window.onInit()

    window.onAction(xbmcgui.Action(xbmcgui.ACTION_NAV_BACK))

    assert window.result is None
