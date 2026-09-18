LOGDEBUG = 0
LOGINFO = 1
LOGWARNING = 2
LOGERROR = 3
LOGFATAL = 4

log_calls = []
executebuiltin_calls = []
play_calls = []
_info_labels = {}
_jsonrpc_results = {}


def log(msg, level=LOGINFO):
    log_calls.append((msg, level))


def executebuiltin(cmd):
    executebuiltin_calls.append(cmd)


def executeJSONRPC(request):
    import json
    payload = json.loads(request)
    setting = payload.get('params', {}).get('setting')
    if setting in _jsonrpc_results:
        return json.dumps({'id': 1, 'jsonrpc': '2.0', 'result': {'value': _jsonrpc_results[setting]}})
    return json.dumps({'id': 1, 'jsonrpc': '2.0', 'error': {'code': -1, 'message': 'unknown setting'}})


def getInfoLabel(label):
    return _info_labels.get(label, '')


def sleep(ms):
    pass


class Player(object):
    def __init__(self):
        pass

    def play(self, item='', listitem=None, windowed=False, startpos=-1):
        play_calls.append((item, listitem))

    def stop(self):
        pass

    def isPlaying(self):
        return False

    def getTime(self):
        return 0

    def getTotalTime(self):
        return 0

    def seekTime(self, seconds):
        pass

    def pause(self):
        pass

    def onAVStarted(self):
        pass

    def onPlayBackError(self):
        pass

    def onPlayBackStopped(self):
        pass

    def onPlayBackEnded(self):
        pass


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
