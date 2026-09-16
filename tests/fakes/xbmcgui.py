ACTION_MOVE_LEFT = 1
ACTION_MOVE_RIGHT = 2
ACTION_MOVE_UP = 3
ACTION_MOVE_DOWN = 4
ACTION_PAGE_UP = 5
ACTION_PAGE_DOWN = 6
ACTION_SELECT_ITEM = 7
ACTION_PREVIOUS_MENU = 10
ACTION_NEXT_ITEM = 14
ACTION_PREV_ITEM = 15
ACTION_REMOTE_0 = 58
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


class BaseControl(object):
    def __init__(self, x=0, y=0, width=0, height=0):
        self._x = x
        self._y = y
        self._width = width
        self._height = height
        self._visible = True
        self._animations = []

    def setPosition(self, x, y):
        self._x = x
        self._y = y

    def getX(self):
        return self._x

    def getY(self):
        return self._y

    def setWidth(self, width):
        self._width = width

    def getWidth(self):
        return self._width

    def setHeight(self, height):
        self._height = height

    def getHeight(self):
        return self._height

    def setVisible(self, visible):
        self._visible = visible

    def isVisible(self):
        return self._visible

    def setAnimations(self, animations):
        self._animations = animations

    def setColorDiffuse(self, color_diffuse):
        self._color_diffuse = color_diffuse


class ControlImage(BaseControl):
    def __init__(self, x, y, width, height, filename='', aspectRatio=0, colorDiffuse=None):
        super(ControlImage, self).__init__(x, y, width, height)
        self._filename = filename
        self._color_diffuse = colorDiffuse

    def setImage(self, filename, useCache=True):
        self._filename = filename

    def getImage(self):
        return self._filename


class ControlLabel(BaseControl):
    def __init__(self, x, y, width, height, label='', font=None, textColor=None,
                 disabledColor=None, alignment=0, hasPath=False, angle=0):
        super(ControlLabel, self).__init__(x, y, width, height)
        self._label = label
        self._text_color = textColor

    def setLabel(self, label='', font=None, textColor=None, disabledColor=None,
                 shadowColor=None, focusedColor=None, label2=''):
        self._label = label
        if textColor is not None:
            self._text_color = textColor

    def getLabel(self):
        return self._label


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
    WIDTH = 1920
    HEIGHT = 1080

    def __init__(self, *args, **kwargs):
        self._controls = {}
        self._focus_id = 0
        self._window_properties = {}
        self._added_controls = []

    def setProperty(self, key, value):
        self._window_properties[key] = value

    def getProperty(self, key):
        return self._window_properties.get(key, '')

    def getWidth(self):
        return self.WIDTH

    def getHeight(self):
        return self.HEIGHT

    def doModal(self):
        pass

    def close(self):
        pass

    def addControl(self, control):
        self._added_controls.append(control)

    def addControls(self, controls):
        self._added_controls.extend(controls)

    def removeControl(self, control):
        if control in self._added_controls:
            self._added_controls.remove(control)

    def removeControls(self, controls):
        for control in controls:
            self.removeControl(control)

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

    def numeric(self, type_, heading, default=''):
        return ''


class DialogProgress(object):
    def __init__(self):
        self._canceled = False
        self._percent = 0
        self._heading = ''
        self._message = ''

    def create(self, heading, message=''):
        self._heading = heading
        self._message = message

    def update(self, percent, message=''):
        self._percent = percent
        if message:
            self._message = message

    def iscanceled(self):
        return self._canceled

    def close(self):
        pass
