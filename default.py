import os
import sys

_ADDON_PATH = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_ADDON_PATH, 'resources', 'lib'))

import xbmc
import xbmcaddon
import xbmcvfs

from kodimate import db, log
from kodimate.windows.main import MainWindow


def run():
    log.log("Kodimate script started")
    addon = xbmcaddon.Addon()
    profile = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
    conn = db.open_db(os.path.join(profile, 'kodimate.db'))
    try:
        MainWindow.open()
    finally:
        conn.close()


if __name__ == '__main__':
    try:
        run()
    except Exception:
        log.log("Kodimate script failed", xbmc.LOGERROR)
        raise
