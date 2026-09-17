_settings = {}


class _LocalizedString(str):
    """A str that tolerates %-formatting against a template with no actual
    placeholder (the fake doesn't carry strings.po's real %s/%d), so
    production code that always does `getLocalizedString(id) % value` for a
    string that has a substitution in the real .po file doesn't crash under
    test; equality with a plain string (existing exact-match assertions)
    still holds since this is a str subclass."""

    def __mod__(self, args):
        try:
            return str.__mod__(self, args)
        except TypeError:
            return self


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

    def getSettingInt(self, key):
        return int(_settings.get(key, 0))

    def setSettingInt(self, key, value):
        _settings[key] = value

    def getSettingNumber(self, key):
        return float(_settings.get(key, 0))

    def setSettingNumber(self, key, value):
        _settings[key] = value

    def getLocalizedString(self, string_id):
        return _LocalizedString("String {0}".format(string_id))
