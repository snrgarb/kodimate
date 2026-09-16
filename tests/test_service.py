import importlib.util
import json
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location('service', os.path.join(_ROOT, 'service.py'))
service = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(service)


def test_notify_builtin_basic():
    assert service._notify_builtin(1, [3]) == (
        'NotifyAll(script.kodimate,refreshed,"{\\"generation\\": 1, \\"providers\\": [3]}")'
    )


def test_notify_builtin_roundtrip():
    result = service._notify_builtin(7, [1, 2])
    assert result == (
        'NotifyAll(script.kodimate,refreshed,"{\\"generation\\": 7, \\"providers\\": [1, 2]}")'
    )
    prefix = 'NotifyAll(script.kodimate,refreshed,"'
    suffix = '")'
    assert result.startswith(prefix)
    assert result.endswith(suffix)
    inner = result[len(prefix):-len(suffix)]
    unescaped = inner.replace('\\"', '"')
    assert json.loads(unescaped) == {"generation": 7, "providers": [1, 2]}


def test_notify_builtin_casts_provider_ids_to_int():
    result = service._notify_builtin(2, ['4'])
    assert '\\"providers\\": [4]' in result


def test_notify_builtin_empty_providers():
    assert service._notify_builtin(3, []) == (
        'NotifyAll(script.kodimate,refreshed,"{\\"generation\\": 3, \\"providers\\": []}")'
    )
