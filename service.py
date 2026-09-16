import json
import os
import sys

_ADDON_PATH = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_ADDON_PATH, 'resources', 'lib'))

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from kodimate import db, log, refresh

_PROP_PREFIX = 'script.kodimate.'


class _WindowProps(object):
    """Adapter over Window(10000) properties for refresh.RefreshService."""

    def __init__(self, window):
        self._window = window

    def get(self, key):
        return self._window.getProperty(_PROP_PREFIX + key)

    def set(self, key, value):
        self._window.setProperty(_PROP_PREFIX + key, value)


def _notify_builtin(generation, provider_ids):
    payload = json.dumps({
        "generation": generation,
        "providers": [int(i) for i in provider_ids],
    })
    escaped = payload.replace('\\', '\\\\').replace('"', '\\"')
    return 'NotifyAll(script.kodimate,refreshed,"{0}")'.format(escaped)


def _notify(generation, provider_ids):
    xbmc.executebuiltin(_notify_builtin(generation, provider_ids))


def _read_settings(addon):
    try:
        interval = addon.getSettingInt('refresh_interval_hours')
    except Exception:
        interval = 12
    try:
        on_startup = addon.getSettingBool('refresh_on_startup')
    except Exception:
        on_startup = True
    return {'refresh_interval_hours': interval or 12, 'refresh_on_startup': on_startup}


def run():
    log.log("Kodimate service started")
    addon = xbmcaddon.Addon()
    profile = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
    conn = db.open_db(os.path.join(profile, 'kodimate.db'))

    window = xbmcgui.Window(10000)
    svc = refresh.RefreshService(
        conn, _WindowProps(window), _notify,
        settings=_read_settings(addon),
    )
    svc.on_start()

    monitor = xbmc.Monitor()
    try:
        while not monitor.abortRequested():
            try:
                svc.tick()
            except Exception:
                log.log("Kodimate service tick failed", xbmc.LOGERROR)
            monitor.waitForAbort(1)
    finally:
        conn.close()
    log.log("Kodimate service stopped")


if __name__ == '__main__':
    try:
        run()
    except Exception:
        log.log("Kodimate service failed", xbmc.LOGERROR)
        raise
