# -*- coding: utf-8 -*-
"""Single owned `xbmc.Player` instance (ADR 0006), forwarding callbacks to
whichever PlaybackSession is currently attached.

Only one `xbmc.Player` may ever exist in the addon process; `get_player()`
returns that singleton. Headers are applied via Kodi's `|User-Agent=...`
pipe-suffix URL convention, rebuilt fresh on every Attempt.
"""
try:
    from urllib.parse import urlencode
except ImportError:  # pragma: no cover - Python 2 fallback, unused on target
    from urllib import urlencode

import xbmc
import xbmcgui


class KodimatePlayer(xbmc.Player):
    def __init__(self):
        super(KodimatePlayer, self).__init__()
        self._session = None

    def attach(self, session):
        self._session = session

    def detach(self, session):
        if self._session is session:
            self._session = None

    def play(self, url, headers=None, mime_type=None, properties=None):
        target = url
        if headers:
            target = url + '|' + urlencode(headers)
        item = xbmcgui.ListItem(path=target)
        if mime_type:
            item.setMimeType(mime_type)
            item.setContentLookup(False)
        for key, value in (properties or {}).items():
            item.setProperty(key, value)
        # windowed=True: the video renders into our own WindowXML's
        # videowindow control rather than switching Kodi to its
        # fullscreenvideo window, so none of Kodi's own player OSD dialogs
        # (DialogSeekBar, the pause OSD) ever appear over our OSD.
        super(KodimatePlayer, self).play(target, item, windowed=True)

    def onAVStarted(self):
        if self._session is not None:
            self._session.on_av_started()

    def onPlayBackError(self):
        if self._session is not None:
            self._session.on_error()

    def onPlayBackStopped(self):
        if self._session is not None:
            self._session.on_stopped()

    def onPlayBackEnded(self):
        if self._session is not None:
            self._session.on_ended()


_player = None


def get_player():
    global _player
    if _player is None:
        _player = KodimatePlayer()
    return _player
