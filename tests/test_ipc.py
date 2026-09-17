from kodimate import ipc


class FakeWindow(object):
    def __init__(self):
        self._props = {}

    def getProperty(self, key):
        return self._props.get(key, '')

    def setProperty(self, key, value):
        self._props[key] = value


def test_request_refresh_single_id_with_ui_suffix():
    window = FakeWindow()
    ipc.request_refresh(5, ui=True, window=window)
    assert window.getProperty('script.kodimate.refresh_request') == '5;ui'


def test_request_refresh_multiple_ids():
    window = FakeWindow()
    ipc.request_refresh([1, 2], ui=True, window=window)
    assert window.getProperty('script.kodimate.refresh_request') == '1,2;ui'


def test_request_refresh_all():
    window = FakeWindow()
    ipc.request_refresh('all', ui=True, window=window)
    assert window.getProperty('script.kodimate.refresh_request') == 'all;ui'


def test_request_refresh_without_ui_suffix():
    window = FakeWindow()
    ipc.request_refresh(5, ui=False, window=window)
    assert window.getProperty('script.kodimate.refresh_request') == '5'


def test_refreshing_ids_empty_when_unset():
    window = FakeWindow()
    assert ipc.refreshing_ids(window=window) == []


def test_refreshing_ids_parses_comma_list():
    window = FakeWindow()
    window.setProperty('script.kodimate.refreshing', '1,2,3')
    assert ipc.refreshing_ids(window=window) == ['1', '2', '3']


def test_db_generation_defaults_to_zero():
    window = FakeWindow()
    assert ipc.db_generation(window=window) == 0


def test_db_generation_parses_int():
    window = FakeWindow()
    window.setProperty('script.kodimate.db_generation', '7')
    assert ipc.db_generation(window=window) == 7


def test_pop_refresh_result_returns_and_clears():
    window = FakeWindow()
    window.setProperty('script.kodimate.refresh_result.5', 'ok')
    result = ipc.pop_refresh_result(5, window=window)
    assert result == 'ok'
    assert window.getProperty('script.kodimate.refresh_result.5') == ''


def test_pop_refresh_result_none_when_absent():
    window = FakeWindow()
    assert ipc.pop_refresh_result(5, window=window) is None


def test_pending_requests_cleared_when_id_appears_in_refreshing_no_toast():
    pending = ipc.PendingRequests(timeout_seconds=10)
    pending.add(5, now=0, generation=0)
    pending.observe(refreshing=['5'], generation=0)
    assert pending.timed_out(now=100) == []


def test_pending_requests_cleared_when_result_popped_without_ever_refreshing():
    pending = ipc.PendingRequests(timeout_seconds=10)
    pending.add(5, now=0, generation=0)
    pending.observe(refreshing=[], generation=0)
    pending.observe_result(5)
    assert pending.timed_out(now=100) == []


def test_pending_requests_times_out_after_window_with_no_signal():
    pending = ipc.PendingRequests(timeout_seconds=10)
    pending.add(5, now=0, generation=0)
    pending.observe(refreshing=[], generation=0)
    assert pending.timed_out(now=5) == []
    assert pending.timed_out(now=11) == ['5']
    # only reported once
    assert pending.timed_out(now=20) == []


def test_pending_requests_all_cleared_when_refreshing_becomes_nonempty():
    pending = ipc.PendingRequests(timeout_seconds=10)
    pending.add('all', now=0, generation=0)
    pending.observe(refreshing=['1', '2'], generation=0)
    assert pending.timed_out(now=100) == []


def test_pending_requests_all_cleared_when_generation_changes():
    pending = ipc.PendingRequests(timeout_seconds=10)
    pending.add('all', now=0, generation=3)
    pending.observe(refreshing=[], generation=4)
    assert pending.timed_out(now=100) == []


def test_pending_requests_all_cleared_by_any_result():
    pending = ipc.PendingRequests(timeout_seconds=10)
    pending.add('all', now=0, generation=0)
    pending.observe_result(7)
    assert pending.timed_out(now=100) == []


def test_generation_watcher_ignores_unchanged_generation():
    window = FakeWindow()
    window.setProperty('script.kodimate.db_generation', '1')
    changes = []
    watcher = ipc.GenerationWatcher(changes.append, window=window)
    watcher.onNotification('script.kodimate', 'Other.refreshed', '{}')
    assert changes == []


def test_generation_watcher_calls_back_once_on_change():
    window = FakeWindow()
    window.setProperty('script.kodimate.db_generation', '1')
    changes = []
    watcher = ipc.GenerationWatcher(changes.append, window=window)
    window.setProperty('script.kodimate.db_generation', '2')
    watcher.onNotification('script.kodimate', 'Other.refreshed', '{}')
    assert changes == [2]
    watcher.onNotification('script.kodimate', 'Other.refreshed', '{}')
    assert changes == [2]


def test_generation_watcher_ignores_other_sender_or_method():
    window = FakeWindow()
    window.setProperty('script.kodimate.db_generation', '1')
    changes = []
    watcher = ipc.GenerationWatcher(changes.append, window=window)
    window.setProperty('script.kodimate.db_generation', '2')
    watcher.onNotification('some.other.addon', 'Other.refreshed', '{}')
    watcher.onNotification('script.kodimate', 'Other.somethingelse', '{}')
    assert changes == []


def test_generation_watcher_stop_ignores_later_notifications():
    window = FakeWindow()
    window.setProperty('script.kodimate.db_generation', '1')
    changes = []
    watcher = ipc.GenerationWatcher(changes.append, window=window)
    watcher.stop()
    window.setProperty('script.kodimate.db_generation', '2')
    watcher.onNotification('script.kodimate', 'Other.refreshed', '{}')
    assert changes == []
