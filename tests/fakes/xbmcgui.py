ACTION_SELECT_ITEM = 7
ACTION_PREVIOUS_MENU = 10
ACTION_NAV_BACK = 92
ACTION_CONTEXT_MENU = 117

_window_properties = {}


class Action(object):
    def __init__(self, action_id=0):
        self._id = action_id

    def getId(self):
        return self._id


class ListItem(object):
    def __init__(self, label='', label2=''):
        self._label = label
        self._label2 = label2
        self._properties = {}
        self._art = {}

    def setLabel(self, label):
        self._label = label

    def getLabel(self):
        return self._label

    def setLabel2(self, label2):
        self._label2 = label2

    def getLabel2(self):
        return self._label2

    def setProperty(self, key, value):
        self._properties[key] = value

    def getProperty(self, key):
        return self._properties.get(key, '')

    def setArt(self, art):
        self._art.update(art)

    def getArt(self, key):
        return self._art.get(key, '')


class Control(object):
    def __init__(self):
        self._items = []
        self._selected = 0
        self._label = ''

    def reset(self):
        self._items = []
        self._selected = 0

    def setLabel(self, label):
        self._label = label

    def getLabel(self):
        return self._label

    def addItem(self, item):
        self._items.append(item)

    def addItems(self, items):
        self._items.extend(items)

    def size(self):
        return len(self._items)

    def getSelectedPosition(self):
        return self._selected

    def selectItem(self, position):
        self._selected = position

    def getSelectedItem(self):
        if not self._items:
            return None
        return self._items[self._selected]


class Window(object):
    def __init__(self, window_id=0):
        self._id = window_id
        _window_properties.setdefault(window_id, {})

    def getProperty(self, key):
        return _window_properties[self._id].get(key, '')

    def setProperty(self, key, value):
        _window_properties[self._id][key] = value

    def clearProperty(self, key):
        _window_properties[self._id].pop(key, None)


class WindowXML(object):
    def __init__(self, *args, **kwargs):
        self._controls = {}
        self._focus_id = 0
        self._window_properties = {}

    def setProperty(self, key, value):
        self._window_properties[key] = value

    def getProperty(self, key):
        return self._window_properties.get(key, '')

    def doModal(self):
        pass

    def close(self):
        pass

    def getControl(self, control_id):
        return self._controls.setdefault(control_id, Control())

    def setFocusId(self, control_id):
        self._focus_id = control_id

    def getFocusId(self):
        return self._focus_id

    def onInit(self):
        pass

    def onAction(self, action):
        pass

    def onClick(self, control_id):
        pass


class Dialog(object):
    def select(self, heading, options):
        return -1

    def yesno(self, heading, message):
        return False

    def ok(self, heading, message):
        return True

    def notification(self, heading, message, icon=None, time=5000):
        pass

    def contextmenu(self, options):
        return -1

    def browse(self, type_, heading, shares, mask='', use_thumbs=False,
               treat_as_folder=False, default=''):
        return ''
