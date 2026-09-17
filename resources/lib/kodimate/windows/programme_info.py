# -*- coding: utf-8 -*-
"""ProgrammeInfoDialog: the shared Programme info dialog (issue #28,
CONTEXT.md "Programme info dialog"), reached from the Guide (and, in later
tickets, the Catch-up browser and the OSD).

Shows a Programme's title, times, and description, with the action set
(among Watch live / Start Over / Play Catch-up) that applies to the cell it
was opened for -- an empty action set is info-only. `open(**kwargs)`
returns the window so the caller reads `.result` (an action key, or None
if the dialog was closed via the Close button or Back)."""
import xbmcaddon
import xbmcgui

WATCH_LIVE_ID = 900
START_OVER_ID = 901
PLAY_CATCHUP_ID = 902
CLOSE_ID = 903

_ACTION_CONTROL_IDS = {
    'watch_live': WATCH_LIVE_ID,
    'start_over': START_OVER_ID,
    'play_catchup': PLAY_CATCHUP_ID,
}


class ProgrammeInfoDialog(xbmcgui.WindowXMLDialog):
    xmlFile = 'script-kodimate-programme-info.xml'
    theme = 'Main'
    res = '1080i'

    title = ''
    times = ''
    description = ''
    actions = ()

    def __init__(self, *args, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
        super(ProgrammeInfoDialog, self).__init__(*args)
        self.result = None

    @classmethod
    def open(cls, **kwargs):
        path = xbmcaddon.Addon().getAddonInfo('path')
        window = cls(cls.xmlFile, path, cls.theme, cls.res, **kwargs)
        window.doModal()
        return window

    def onInit(self):
        self.setProperty('title', self.title or '')
        self.setProperty('times', self.times or '')
        self.setProperty('description', self.description or '')
        for key, control_id in _ACTION_CONTROL_IDS.items():
            self.setProperty('has_' + key, '1' if key in self.actions else '0')
        self.setFocusId(self._first_focus_id())

    def _first_focus_id(self):
        for key in ('watch_live', 'start_over', 'play_catchup'):
            if key in self.actions:
                return _ACTION_CONTROL_IDS[key]
        return CLOSE_ID

    def onClick(self, control_id):
        for key, action_control_id in _ACTION_CONTROL_IDS.items():
            if control_id == action_control_id:
                self.result = key
                self.close()
                return
        if control_id == CLOSE_ID:
            self.result = None
            self.close()

    def onAction(self, action):
        action_id = action.getId()
        if action_id in (xbmcgui.ACTION_NAV_BACK, xbmcgui.ACTION_PREVIOUS_MENU):
            self.result = None
            self.close()
