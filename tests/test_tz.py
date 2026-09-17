# -*- coding: utf-8 -*-
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
