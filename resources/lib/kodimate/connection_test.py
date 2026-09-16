# -*- coding: utf-8 -*-
"""Provider Form "Test connection" (issue #21). Pure logic, no xbmc imports,
no DB access: persists nothing. Errors propagate as fetch.FetchError /
m3u.M3UError so callers can show the shared error catalogue.
"""
from . import fetch, m3u, providers, xtream


def _m3u_test(fields, fetcher):
    text = fetcher(fields['m3u_url'], fields.get('user_agent'))
    playlist = m3u.parse(text)
    header = playlist.header_attrs
    epg_declared = bool(header.get('url-tvg') or header.get('x-tvg-url'))
    return {
        'channel_count': len(playlist.entries),
        'epg_declared': epg_declared,
    }


def _xtream_test(fields, fetcher):
    host = providers.normalise_xtream_host(fields['xtream_host'])
    username = fields['xtream_username']
    password = fields['xtream_password']
    user_agent = fields.get('user_agent')
    account = xtream.fetch_account(host, username, password, user_agent, fetcher)
    categories = xtream.fetch_categories(host, username, password, user_agent, fetcher)
    return {
        'status': account['status'],
        'account_expires_at': account['account_expires_at'],
        'max_connections': account['max_connections'],
        'active_connections': account['active_connections'],
        'allowed_output_formats': account['allowed_output_formats'],
        'live_category_count': len(categories),
    }


def test_connection(kind, fields, fetcher):
    """Return a kind-specific summary dict. Raises fetch.FetchError / m3u.M3UError."""
    if kind == 'xtream':
        return _xtream_test(fields, fetcher)
    return _m3u_test(fields, fetcher)


def wait_for_worker(worker, progress, sleep, clock, timeout=15.0, poll_interval=0.1):
    """Poll `worker.is_alive()` until it finishes, the user cancels via
    `progress.iscanceled()`, or `timeout` seconds elapse (per `clock()`).
    Returns 'done', 'cancelled' or 'timeout'. Testable with fakes for all
    four collaborators so cancel/timeout paths don't need real threads/time.
    """
    start = clock()
    while worker.is_alive():
        if progress.iscanceled():
            return 'cancelled'
        if clock() - start >= timeout:
            return 'timeout'
        sleep(poll_interval)
    return 'done'
