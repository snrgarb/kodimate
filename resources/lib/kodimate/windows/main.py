# -*- coding: utf-8 -*-
import xbmcgui

from .base import BaseWindow
from .catchup_browser import CatchupBrowserWindow
from .channel_list import ChannelListWindow
from .guide import GuideWindow

CHANNELS_BUTTON_ID = 201
GUIDE_BUTTON_ID = 202
CATCHUP_BUTTON_ID = 203


class MainWindow(BaseWindow):
    xmlFile = 'script-kodimate-main.xml'

    def onAction(self, action):
        if action.getId() in (xbmcgui.ACTION_NAV_BACK, xbmcgui.ACTION_PREVIOUS_MENU):
            self.close()

    def onClick(self, control_id):
        if control_id == CHANNELS_BUTTON_ID:
            ChannelListWindow.open(conn=self.conn)
        elif control_id == GUIDE_BUTTON_ID:
            GuideWindow.open(conn=self.conn)
        elif control_id == CATCHUP_BUTTON_ID:
            CatchupBrowserWindow.open(conn=self.conn)
