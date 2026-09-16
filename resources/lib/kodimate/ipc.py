# -*- coding: utf-8 -*-
"""Script-side helpers over the Window(10000) refresh-IPC properties.

See docs/design/refresh-ipc.md for the property contract.
"""
import xbmcgui

_PREFIX = 'script.kodimate.'
_WINDOW_ID = 10000


def _default_window():
    return xbmcgui.Window(_WINDOW_ID)


def request_refresh(ids_or_all, ui=True, window=None):
    window = window or _default_window()
    if isinstance(ids_or_all, (list, tuple)):
        value = ','.join(str(i) for i in ids_or_all)
    else:
        value = str(ids_or_all)
    if ui:
        value += ';ui'
    window.setProperty(_PREFIX + 'refresh_request', value)


def refreshing_ids(window=None):
    window = window or _default_window()
    raw = window.getProperty(_PREFIX + 'refreshing')
    if not raw:
        return []
    return [x for x in raw.split(',') if x]


def db_generation(window=None):
    window = window or _default_window()
    raw = window.getProperty(_PREFIX + 'db_generation')
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def pop_refresh_result(provider_id, window=None):
    window = window or _default_window()
    key = _PREFIX + 'refresh_result.{0}'.format(provider_id)
    value = window.getProperty(key)
    if value:
        window.setProperty(key, '')
    return value or None


class PendingRequests(object):
    """Tracks manual (';ui') refresh requests until confirmed in flight or
    complete, to drive the "service not running" toast (docs/design/refresh-ipc.md:
    "If refreshing has not changed 10 s after a request, the script toasts").

    A request is cleared as soon as its id (or, for 'all', any id) appears in
    `refreshing`, its `db_generation` baseline changes, or a refresh_result
    arrives for it; only a request still pending after `timeout_seconds`
    triggers a timeout.
    """

    def __init__(self, timeout_seconds=10):
        self._timeout = timeout_seconds
        self._pending = {}  # key (str provider id, or 'all') -> (requested_at, generation)

    def add(self, key, now, generation):
        self._pending[str(key)] = (now, generation)

    def observe(self, refreshing, generation):
        """Clear entries confirmed in flight: a per-id request whose id is in
        `refreshing`, or the 'all' request once any id is in `refreshing` or
        `generation` has moved past its baseline (a refresh may start and
        finish within one poll tick and never be observed in `refreshing`)."""
        refreshing_set = set(refreshing)
        for key, (_, requested_generation) in list(self._pending.items()):
            if key in refreshing_set:
                del self._pending[key]
            elif key == 'all' and (refreshing_set or generation != requested_generation):
                del self._pending[key]

    def observe_result(self, provider_id):
        """Clear the pending entry for provider_id, and for 'all' if pending."""
        self._pending.pop(str(provider_id), None)
        self._pending.pop('all', None)

    def timed_out(self, now):
        """Return and remove the keys whose timeout has elapsed."""
        expired = []
        for key, (requested_at, _) in list(self._pending.items()):
            if now - requested_at > self._timeout:
                expired.append(key)
                del self._pending[key]
        return expired
