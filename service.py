import xbmc

xbmc.log("Kodimate service started", xbmc.LOGINFO)
xbmc.Monitor().waitForAbort()
xbmc.log("Kodimate service stopped", xbmc.LOGINFO)
