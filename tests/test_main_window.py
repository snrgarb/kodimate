from kodimate.windows.main import MainWindow, SETTINGS_BUTTON_ID
import xbmcaddon


def _window():
    return MainWindow('script-kodimate-main.xml', '/addon', 'Main', '1080i', conn=None)


def test_settings_button_opens_addon_settings():
    xbmcaddon.open_settings_calls[:] = []
    window = _window()
    window.onClick(SETTINGS_BUTTON_ID)
    assert xbmcaddon.open_settings_calls == [True]
