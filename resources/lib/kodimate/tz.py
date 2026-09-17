# -*- coding: utf-8 -*-
"""IANA timezone offset lookup (issue #39).

Pure: no xbmc import at module scope, so this stays importable and
testable without the Kodi fakes. `zone_offset_seconds` never raises --
an unresolvable zone name (missing `zoneinfo`, unknown name, falsy
input) yields an offset of 0, with a warning logged once per process.
"""
from datetime import datetime, timezone

_warned_zones = set()


def _warn_once(zone_name):
    if zone_name in _warned_zones:
        return
    _warned_zones.add(zone_name)
    try:
        from . import log
        import xbmc
        log.log('Unresolvable timezone: {0}'.format(zone_name), xbmc.LOGWARNING)
    except Exception:
        pass


def zone_offset_seconds(zone_name, epoch_utc):
    """Seconds east of UTC that `zone_name` observes at `epoch_utc`."""
    if not zone_name:
        return 0
    try:
        from zoneinfo import ZoneInfo
        dt = datetime.fromtimestamp(epoch_utc, tz=timezone.utc).astimezone(ZoneInfo(zone_name))
        return int(dt.utcoffset().total_seconds())
    except Exception:
        _warn_once(zone_name)
        return 0
