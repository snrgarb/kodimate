_settings = {}


class Addon(object):
    def __init__(self, id=None):
        self._info = {
            'path': '/addon',
            'profile': '/profile',
            'name': 'Kodimate',
        }

    def getAddonInfo(self, key):
        return self._info.get(key, '')

    def getSettingBool(self, key):
        return bool(_settings.get(key, False))

    def setSettingBool(self, key, value):
        _settings[key] = value

    def getLocalizedString(self, string_id):
        return "String {0}".format(string_id)
