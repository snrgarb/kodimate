import importlib.util
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_default():
    spec = importlib.util.spec_from_file_location('kodimate_default', os.path.join(_ROOT, 'default.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _stub(monkeypatch, default, name):
    calls = []

    class _Stub(object):
        @classmethod
        def open(cls, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(default, name, _Stub)
    return calls


@pytest.fixture
def default_module(tmp_path, monkeypatch):
    default = _load_default()
    monkeypatch.setattr(default.xbmcvfs, 'translatePath', lambda path: str(tmp_path))
    monkeypatch.setattr(default.xbmcaddon.Addon, 'getSettingBool', lambda self, key: False)
    return default


def test_providers_arg_opens_only_providers(default_module, monkeypatch):
    providers_calls = _stub(monkeypatch, default_module, 'ProvidersWindow')
    guide_calls = _stub(monkeypatch, default_module, 'GuideWindow')
    monkeypatch.setattr(sys, 'argv', ['default.py', 'providers'])

    default_module.run()

    assert len(providers_calls) == 1
    assert guide_calls == []


def test_zero_enabled_opens_providers_then_guide(default_module, monkeypatch):
    providers_calls = _stub(monkeypatch, default_module, 'ProvidersWindow')
    guide_calls = _stub(monkeypatch, default_module, 'GuideWindow')
    monkeypatch.setattr(sys, 'argv', ['default.py'])

    default_module.run()

    assert len(providers_calls) == 1
    assert len(guide_calls) == 1


def test_enabled_provider_autoplay_off_opens_guide_only(default_module, monkeypatch, tmp_path):
    from kodimate import db
    conn = db.open_db(str(tmp_path / 'kodimate.db'))
    conn.execute("INSERT INTO provider (kind, name, enabled, sort_order) VALUES ('m3u', 'P', 1, 0)")
    conn.commit()
    conn.close()
    providers_calls = _stub(monkeypatch, default_module, 'ProvidersWindow')
    guide_calls = _stub(monkeypatch, default_module, 'GuideWindow')
    monkeypatch.setattr(sys, 'argv', ['default.py'])

    default_module.run()

    assert providers_calls == []
    assert len(guide_calls) == 1
