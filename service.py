import os
import sys

_ADDON_PATH = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_ADDON_PATH, 'resources', 'lib'))

import xbmc
import xbmcaddon
import xbmcvfs

from kodimate import db, log


def run():
    log.log("Kodimate service started")
    addon = xbmcaddon.Addon()
    profile = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
    conn = db.open_db(os.path.join(profile, 'kodimate.db'))
    try:
        xbmc.Monitor().waitForAbort()
    finally:
        conn.close()
    log.log("Kodimate service stopped")


if __name__ == '__main__':
    try:
        run()
    except Exception:
        log.log("Kodimate service failed", xbmc.LOGERROR)
        raise
