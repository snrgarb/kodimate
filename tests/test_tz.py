# -*- coding: utf-8 -*-
import time
from datetime import datetime, timezone

from kodimate import tz

_SEPTEMBER = int(datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc).timestamp())
_JANUARY = int(datetime(2026, 1, 17, 12, 0, 0, tzinfo=timezone.utc).timestamp())


def test_toronto_september_is_edt_minus_4h():
    assert tz.zone_offset_seconds('America/Toronto', _SEPTEMBER) == -14400


def test_toronto_january_is_est_minus_5h():
    assert tz.zone_offset_seconds('America/Toronto', _JANUARY) == -18000


def test_utc_zone_is_zero():
    assert tz.zone_offset_seconds('UTC', _SEPTEMBER) == 0


def test_falsy_zone_name_is_zero():
    assert tz.zone_offset_seconds(None, _SEPTEMBER) == 0
    assert tz.zone_offset_seconds('', _SEPTEMBER) == 0


def test_unknown_zone_name_is_zero():
    assert tz.zone_offset_seconds('Not/AZone', _SEPTEMBER) == 0


# ---------------------------------------------------------------------------
# host_offset_seconds
# ---------------------------------------------------------------------------

def test_host_offset_seconds_matches_localtime(monkeypatch):
    import time as time_module

    def fake_localtime(epoch):
        return time_module.gmtime(epoch - 14400)  # pretend host is UTC-4

    monkeypatch.setattr(tz.time, 'localtime', fake_localtime)
    assert tz.host_offset_seconds(_SEPTEMBER) == -14400


def test_host_offset_seconds_utc_host_is_zero(monkeypatch):
    monkeypatch.setattr(tz.time, 'localtime', time.gmtime)
    assert tz.host_offset_seconds(_SEPTEMBER) == 0
