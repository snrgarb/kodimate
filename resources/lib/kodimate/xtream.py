# -*- coding: utf-8 -*-
"""Xtream Codes `player_api.php` client. Service-side only (ADR 0003).

No xbmc* imports, no direct network I/O: the HTTP GET is injected as
`fetcher(url, user_agent) -> text` (default `fetch.fetch_playlist`, the same
callable the M3U refresh path already uses), so this is testable without a
network. Errors are raised as `fetch.FetchError`, reusing fetch.py's
catalogue (`Unreachable`/`Timed out`/`HTTP <code>`), plus two Xtream-specific
reasons: "Login rejected" (auth failed or account Banned/Expired/Disabled)
and "Not an Xtream server" (response isn't JSON shaped like a player_api.php
account payload).
"""
import json
from datetime import datetime
from urllib.parse import quote

from . import fetch, m3u

_BANNED_STATUSES = {'Banned', 'Expired', 'Disabled'}


def _player_api_url(host, username, password, action=None, category_id=None):
    url = '{0}/player_api.php?username={1}&password={2}'.format(
        host, quote(str(username), safe=''), quote(str(password), safe='')
    )
    if action:
        url += '&action={0}'.format(action)
    if category_id is not None:
        url += '&category_id={0}'.format(quote(str(category_id), safe=''))
    return url


def _fetch_json(url, user_agent, fetcher):
    text = fetcher(url, user_agent)
    try:
        return json.loads(text)
    except ValueError:
        raise fetch.FetchError(fetch.ERROR_NOT_XTREAM)


def _exp_date_iso(exp_date):
    ts = m3u._to_int(exp_date)
    if not ts:
        return None
    return datetime.utcfromtimestamp(ts).strftime('%Y-%m-%dT%H:%M:%SZ')


def fetch_account(host, username, password, user_agent, fetcher):
    """Log in and return {account_expires_at, max_connections, allowed_output_formats}."""
    data = _fetch_json(_player_api_url(host, username, password), user_agent, fetcher)
    user_info = data.get('user_info') if isinstance(data, dict) else None
    if not isinstance(user_info, dict):
        raise fetch.FetchError(fetch.ERROR_NOT_XTREAM)

    if not m3u._to_int(user_info.get('auth')) or user_info.get('status') in _BANNED_STATUSES:
        raise fetch.FetchError(fetch.ERROR_LOGIN_REJECTED)

    allowed_formats = user_info.get('allowed_output_formats')
    if not isinstance(allowed_formats, list):
        allowed_formats = None

    return {
        'account_expires_at': _exp_date_iso(user_info.get('exp_date')),
        'max_connections': m3u._to_int(user_info.get('max_connections')),
        'allowed_output_formats': allowed_formats,
        'status': user_info.get('status'),
        'active_connections': m3u._to_int(user_info.get('active_cons')),
    }


def _require_list_of_dicts(data):
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise fetch.FetchError(fetch.ERROR_NOT_XTREAM)
    return data


def fetch_categories(host, username, password, user_agent, fetcher):
    data = _fetch_json(
        _player_api_url(host, username, password, action='get_live_categories'),
        user_agent, fetcher,
    )
    return _require_list_of_dicts(data)


def fetch_streams(host, username, password, user_agent, fetcher):
    data = _fetch_json(
        _player_api_url(host, username, password, action='get_live_streams'),
        user_agent, fetcher,
    )
    return _require_list_of_dicts(data)
