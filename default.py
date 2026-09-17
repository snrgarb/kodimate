import os
import sys

_ADDON_PATH = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_ADDON_PATH, 'resources', 'lib'))

import xbmc
import xbmcaddon
import xbmcvfs

from kodimate import autoplay, db, log, providers
from kodimate.windows.main import MainWindow
from kodimate.windows.playback import PlaybackWindow
from kodimate.windows.providers import ProvidersWindow


def run():
    log.log("Kodimate script started")
    addon = xbmcaddon.Addon()
    profile = xbmcvfs.translatePath(addon.getAddonInfo('profile'))
    conn = db.open_db(os.path.join(profile, 'kodimate.db'))
    try:
        arg = sys.argv[1] if len(sys.argv) > 1 else None
        if arg == 'providers' or providers.count_enabled(conn) == 0:
            ProvidersWindow.open(conn=conn)
        else:
            if addon.getSettingBool('autoplay_last_channel'):
                snapshot = autoplay.startup_snapshot(conn)
                if snapshot is not None:
                    PlaybackWindow.open(
                        conn=conn, snapshot=snapshot,
                        open_list_on_init=addon.getSettingBool('autoplay_overlay_list'),
                    )
            MainWindow.open(conn=conn)
    finally:
        conn.close()


if __name__ == '__main__':
    try:
        run()
    except Exception:
        log.log("Kodimate script failed", xbmc.LOGERROR)
        raise
