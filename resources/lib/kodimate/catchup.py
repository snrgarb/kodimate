# -*- coding: utf-8 -*-
"""Pure Catch-up playability rules (issue #28, CONTEXT.md "Catch-up",
"Catch-up Window"; docs/design/schema.md "Effective Catch-up Window",
"Catch-up playability").

No xbmc imports, no DB access: takes plain datetimes/ints and returns
plain values. Datetimes are naive UTC, as elsewhere in the codebase
(see guide.parse_iso).
"""
from datetime import timedelta

from . import guide

RETENTION_DAYS = guide.RETENTION_DAYS


def effective_window_days(channel_catchup_days, provider_default, url_supported=True):
    """The Effective Catch-up Window: the channel's value if set (0 means
    explicitly no Catch-up, beating the provider default), else the
    provider default. None at both levels means no Catch-up. A Channel
    whose mode cannot produce a Catch-up URL (`url_supported=False`) is
    always unplayable, regardless of window."""
    if not url_supported:
        return None
    days = channel_catchup_days if channel_catchup_days is not None else provider_default
    if not days:
        return None
    return days


def cell_state(programme_start, programme_end, window_days, now):
    """One of 'future', 'live', 'past_playable', 'past_unplayable' for a
    Programme cell against the Effective Catch-up Window."""
    if now < programme_start:
        return 'future'
    if programme_start <= now < programme_end:
        return 'live'
    if not window_days:
        return 'past_unplayable'
    if programme_start < now - timedelta(days=RETENTION_DAYS):
        return 'past_unplayable'
    if programme_start >= now - timedelta(days=window_days):
        return 'past_playable'
    return 'past_unplayable'


def actions_for(state, start_over_ok=False):
    """Ordered action keys for the Programme info dialog; empty = info only."""
    if state == 'live':
        actions = ['watch_live']
        if start_over_ok:
            actions.append('start_over')
        return actions
    if state == 'past_playable':
        return ['play_catchup']
    return []


def requested_duration_seconds(start, end, now):
    """Requested Catch-up playback duration: min(end, now) - start, never
    negative."""
    stop = min(end, now)
    seconds = int((stop - start).total_seconds())
    return max(0, seconds)
