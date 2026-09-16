# -*- coding: utf-8 -*-
"""BaseWindow: thin xbmcgui.WindowXML wrapper (script.plexmod BaseWindow pattern)."""
import xbmcaddon
import xbmcgui


class BaseWindow(xbmcgui.WindowXML):
    xmlFile = ''
    theme = 'Main'
    res = '1080i'

    @classmethod
    def open(cls, **kwargs):
        path = xbmcaddon.Addon().getAddonInfo('path')
        window = cls(cls.xmlFile, path, cls.theme, cls.res, **kwargs)
        window.doModal()
        return window
