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
