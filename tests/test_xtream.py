# -*- coding: utf-8 -*-
import os

import pytest

from kodimate import fetch, xtream

_FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')


def _read_fixture(name):
    with open(os.path.join(_FIXTURES, name), 'r') as f:
        return f.read()


def _fetcher_from(fixture_name):
    text = _read_fixture(fixture_name)

    def fetcher(url, user_agent):
        return text

    return fetcher


def test_fetch_account_parses_expiry_and_formats():
    account = xtream.fetch_account(
        'http://xc.example', 'user', 'pass', None, _fetcher_from('xtream_account.json')
    )
    assert account['account_expires_at'] == '2025-01-01T00:00:00Z'
    assert account['max_connections'] == 1
    assert account['allowed_output_formats'] == ['m3u8', 'ts']


def test_fetch_account_returns_server_timezone():
    account = xtream.fetch_account(
        'http://xc.example', 'user', 'pass', None, _fetcher_from('xtream_account.json')
    )
    assert account['server_timezone'] == 'Europe/London'


def test_fetch_account_no_expiry_is_none():
    account = xtream.fetch_account(
        'http://xc.example', 'user', 'pass', None,
        _fetcher_from('xtream_account_no_expiry.json'),
    )
    assert account['account_expires_at'] is None


def test_fetch_account_banned_raises_login_rejected():
    with pytest.raises(fetch.FetchError, match='Login rejected'):
        xtream.fetch_account(
            'http://xc.example', 'user', 'pass', None,
            _fetcher_from('xtream_account_banned.json'),
        )


def test_fetch_account_non_json_raises_not_an_xtream_server():
    with pytest.raises(fetch.FetchError, match='Not an Xtream server'):
        xtream.fetch_account(
            'http://xc.example', 'user', 'pass', None,
            _fetcher_from('xtream_not_json.html'),
        )


def test_fetch_categories_returns_list():
    categories = xtream.fetch_categories(
        'http://xc.example', 'user', 'pass', None, _fetcher_from('xtream_categories.json')
    )
    assert categories == [
        {'category_id': '5', 'category_name': 'News', 'parent_id': 0},
        {'category_id': '6', 'category_name': 'Sport', 'parent_id': 0},
    ]


def test_fetch_streams_tolerates_string_typed_fields():
    streams = xtream.fetch_streams(
        'http://xc.example', 'user', 'pass', None, _fetcher_from('xtream_streams.json')
    )
    assert streams[0]['stream_id'] == '12345'
    assert streams[0]['num'] == '101'


def test_fetch_account_percent_encodes_username_and_password_in_url():
    seen = {}

    def fetcher(url, user_agent):
        seen['url'] = url
        return _read_fixture('xtream_account.json')

    xtream.fetch_account('http://xc.example', 'user', 'p&ss#word', None, fetcher)

    assert 'p&ss#word' not in seen['url']
    assert 'p%26ss%23word' in seen['url']


def test_fetch_streams_raises_not_an_xtream_server_when_element_not_dict():
    def fetcher(url, user_agent):
        return '["not", "a", "dict"]'

    with pytest.raises(fetch.FetchError, match='Not an Xtream server'):
        xtream.fetch_streams('http://xc.example', 'user', 'pass', None, fetcher)


def test_fetch_server_timezone_returns_zone_name():
    zone = xtream.fetch_server_timezone(
        'http://xc.example', 'user', 'pass', None, _fetcher_from('xtream_account.json')
    )
    assert zone == 'Europe/London'


def test_fetch_server_timezone_returns_none_when_absent():
    zone = xtream.fetch_server_timezone(
        'http://xc.example', 'user', 'pass', None, _fetcher_from('xtream_account_no_expiry.json')
    )
    assert zone is None


def test_fetch_server_timezone_returns_none_on_error_instead_of_raising():
    def fetcher(url, user_agent):
        return '<html>not json</html>'

    zone = xtream.fetch_server_timezone('http://xc.example', 'user', 'pass', None, fetcher)
    assert zone is None
