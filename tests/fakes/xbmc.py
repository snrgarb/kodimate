LOGDEBUG = 0
LOGINFO = 1
LOGWARNING = 2
LOGERROR = 3
LOGFATAL = 4

log_calls = []


def log(msg, level=LOGINFO):
    log_calls.append((msg, level))


class Monitor(object):
    def waitForAbort(self, timeout=None):
        return True

    def abortRequested(self):
        return True

    def onNotification(self, sender, method, data):
        pass


class Keyboard(object):
    def __init__(self, default='', heading='', hidden=False):
        self._text = default
        self._confirmed = False

    def doModal(self):
        self._confirmed = True

    def isConfirmed(self):
        return self._confirmed

    def getText(self):
        return self._text

    def setDefault(self, text):
        self._text = text

    def setHeading(self, heading):
        pass
