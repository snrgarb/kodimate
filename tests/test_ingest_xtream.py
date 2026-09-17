# -*- coding: utf-8 -*-
import json

import pytest

from kodimate import db, ingest


def _make_db(tmp_path):
    conn = db.open_db(str(tmp_path / 'k.db'))
    conn.execute(
        "INSERT INTO provider (id, kind, name, enabled, xtream_host, xtream_username, "
        "xtream_password) VALUES (1, 'xtream', 'Test', 1, 'http://xc.example', 'user', 'pass')"
    )
    return conn


_ACCOUNT = {
    'account_expires_at': '2026-01-08T00:00:00Z',
    'max_connections': 1,
    'allowed_output_formats': ['ts', 'm3u8'],
    'server_timezone': 'America/Toronto',
}

_CATEGORIES = [
    {'category_id': '5', 'category_name': 'News', 'parent_id': 0},
    {'category_id': 6, 'category_name': 'Sport', 'parent_id': 0},
]

_STREAMS = [
    {
        'num': '101', 'name': 'BBC News HD', 'stream_id': '12345', 'category_id': '5',
        'stream_icon': 'http://xc.example/logos/bbcnews.png',
        'epg_channel_id': 'bbcnews.uk', 'tv_archive': '1', 'tv_archive_duration': '7',
    },
    {
        'num': 102, 'name': 'Sky News', 'stream_id': 12346, 'category_id': '5',
        'stream_icon': '', 'epg_channel_id': 'skynews.uk',
        'tv_archive': '0', 'tv_archive_duration': '7',
    },
    {
        'num': 201, 'name': 'Sky Sports', 'stream_id': 22345, 'category_id': 6,
        'stream_icon': 'http://xc.example/logos/skysports.png',
        'epg_channel_id': 'skysports.uk', 'tv_archive': 1, 'tv_archive_duration': 3,
    },
]


def _channels_by_key(conn, provider_id=1):
    rows = conn.execute(
        "SELECT channel_key, name, normalised_name, stream_url, group_id, "
        "provider_number, epg_channel_id, catchup_days, logo_url, stale_since "
        "FROM channel WHERE provider_id = ?",
        (provider_id,),
    ).fetchall()
    cols = [
        'channel_key', 'name', 'normalised_name', 'stream_url', 'group_id',
        'provider_number', 'epg_channel_id', 'catchup_days', 'logo_url', 'stale_since',
    ]
    return {row[0]: dict(zip(cols, row)) for row in rows}


def test_creates_group_per_category_and_channel_per_stream(tmp_path):
    conn = _make_db(tmp_path)
    ingest.refresh_xtream_provider(
        conn, 1, _ACCOUNT, _CATEGORIES, _STREAMS, '2026-01-01T00:00:00Z'
    )
    groups = dict(conn.execute("SELECT id, name FROM channel_group WHERE provider_id = 1").fetchall())
    assert set(groups.values()) == {'News', 'Sport'}

    channels = _channels_by_key(conn)
    assert set(channels) == {'12345', '12346', '22345'}
    assert channels['12345']['name'] == 'BBC News HD'
    assert channels['12345']['provider_number'] == 101
    assert channels['12345']['epg_channel_id'] == 'bbcnews.uk'
    assert channels['12345']['stream_url'] == 'http://xc.example/live/user/pass/12345.ts'
    assert groups[channels['12345']['group_id']] == 'News'
    assert groups[channels['22345']['group_id']] == 'Sport'


def test_catchup_days_only_set_when_tv_archive_truthy(tmp_path):
    conn = _make_db(tmp_path)
    ingest.refresh_xtream_provider(
        conn, 1, _ACCOUNT, _CATEGORIES, _STREAMS, '2026-01-01T00:00:00Z'
    )
    channels = _channels_by_key(conn)
    assert channels['12345']['catchup_days'] == 7
    # tv_archive == '0' -> explicit no-catch-up (0), even though a duration
    # is present: a channel value of 0 beats the provider default (issue #28).
    assert channels['12346']['catchup_days'] == 0
    assert channels['22345']['catchup_days'] == 3


def test_catchup_days_null_when_tv_archive_field_absent(tmp_path):
    # An absent tv_archive field (not even present, unlike an explicit '0')
    # must leave catchup_days NULL so the provider default applies, not 0.
    conn = _make_db(tmp_path)
    streams = [
        {
            'num': '301', 'name': 'No Archive Field', 'stream_id': '99999',
            'category_id': '5', 'stream_icon': '', 'epg_channel_id': None,
        },
    ]
    ingest.refresh_xtream_provider(
        conn, 1, _ACCOUNT, _CATEGORIES, streams, '2026-01-01T00:00:00Z'
    )
    channels = _channels_by_key(conn)
    assert channels['99999']['catchup_days'] is None


def test_account_fields_written_on_every_refresh(tmp_path):
    conn = _make_db(tmp_path)
    ingest.refresh_xtream_provider(
        conn, 1, _ACCOUNT, _CATEGORIES, _STREAMS, '2026-01-01T00:00:00Z'
    )
    row = conn.execute(
        "SELECT account_expires_at, max_connections, allowed_output_formats, server_timezone "
        "FROM provider WHERE id = 1"
    ).fetchone()
    assert row[0] == '2026-01-08T00:00:00Z'
    assert row[1] == 1
    assert json.loads(row[2]) == ['ts', 'm3u8']
    assert row[3] == 'America/Toronto'


def test_epg_source_registered_from_xmltv_php(tmp_path):
    conn = _make_db(tmp_path)
    ingest.refresh_xtream_provider(
        conn, 1, _ACCOUNT, _CATEGORIES, _STREAMS, '2026-01-01T00:00:00Z'
    )
    row = conn.execute("SELECT url FROM epg_source WHERE provider_id = 1").fetchone()
    assert row == ('http://xc.example/xmltv.php?username=user&password=pass',)


def test_epg_source_url_percent_encodes_password_with_ampersand(tmp_path):
    conn = _make_db(tmp_path)
    conn.execute("UPDATE provider SET xtream_password = ? WHERE id = 1", ('pa&ss',))
    ingest.refresh_xtream_provider(
        conn, 1, _ACCOUNT, _CATEGORIES, _STREAMS, '2026-01-01T00:00:00Z'
    )
    row = conn.execute("SELECT url FROM epg_source WHERE provider_id = 1").fetchone()
    assert row == ('http://xc.example/xmltv.php?username=user&password=pa%26ss',)


def test_epg_override_url_wins_over_xmltv_php(tmp_path):
    conn = _make_db(tmp_path)
    conn.execute(
        "UPDATE provider SET epg_override_url = ? WHERE id = 1",
        ('http://override.example/guide.xml',),
    )
    outcome = ingest.refresh_xtream_provider(
        conn, 1, _ACCOUNT, _CATEGORIES, _STREAMS, '2026-01-01T00:00:00Z'
    )
    assert outcome.epg_url == 'http://override.example/guide.xml'
    row = conn.execute("SELECT url FROM epg_source WHERE provider_id = 1").fetchone()
    assert row == ('http://override.example/guide.xml',)


def test_second_refresh_marks_missing_stream_stale(tmp_path):
    conn = _make_db(tmp_path)
    ingest.refresh_xtream_provider(
        conn, 1, _ACCOUNT, _CATEGORIES, _STREAMS, '2026-01-01T00:00:00Z'
    )
    streams_without_sky_news = [s for s in _STREAMS if s['stream_id'] != 12346]
    ingest.refresh_xtream_provider(
        conn, 1, _ACCOUNT, _CATEGORIES, streams_without_sky_news, '2026-01-02T00:00:00Z'
    )
    channels = _channels_by_key(conn)
    assert channels['12346']['stale_since'] == '2026-01-02T00:00:00Z'
    assert channels['12345']['stale_since'] is None


def test_stream_with_unmatched_category_id_lands_in_uncategorised(tmp_path):
    conn = _make_db(tmp_path)
    streams = _STREAMS + [
        {
            'num': 301, 'name': 'Mystery Channel', 'stream_id': 99999, 'category_id': '99',
            'stream_icon': '', 'epg_channel_id': None, 'tv_archive': 0, 'tv_archive_duration': 0,
        },
    ]
    ingest.refresh_xtream_provider(
        conn, 1, _ACCOUNT, _CATEGORIES, streams, '2026-01-01T00:00:00Z'
    )
    groups = dict(conn.execute("SELECT id, name FROM channel_group WHERE provider_id = 1").fetchall())
    assert set(groups.values()) == {'News', 'Sport', ingest.UNCATEGORISED}

    channels = _channels_by_key(conn)
    assert groups[channels['99999']['group_id']] == ingest.UNCATEGORISED


def test_config_version_changed_rolls_back(tmp_path):
    conn = _make_db(tmp_path)
    conn.execute("UPDATE provider SET config_version = 5 WHERE id = 1")
    with pytest.raises(ingest.ConfigVersionChanged):
        ingest.refresh_xtream_provider(
            conn, 1, _ACCOUNT, _CATEGORIES, _STREAMS, '2026-01-01T00:00:00Z',
            expected_config_version=4,
        )
    assert conn.execute("SELECT COUNT(*) FROM channel WHERE provider_id = 1").fetchone()[0] == 0


def test_large_stream_count_does_not_exceed_sqlite_variable_limit(tmp_path):
    conn = _make_db(tmp_path)
    categories = [{'category_id': '1', 'category_name': 'All', 'parent_id': 0}]
    streams = [
        {
            'num': i, 'name': 'Channel %d' % i, 'stream_id': i, 'category_id': '1',
            'stream_icon': '', 'epg_channel_id': None, 'tv_archive': 0, 'tv_archive_duration': 0,
        }
        for i in range(40000)
    ]
    ingest.refresh_xtream_provider(
        conn, 1, _ACCOUNT, categories, streams, '2026-01-01T00:00:00Z'
    )
    assert conn.execute(
        "SELECT COUNT(*) FROM channel WHERE provider_id = 1"
    ).fetchone()[0] == 40000

    half_streams = streams[:20000]
    ingest.refresh_xtream_provider(
        conn, 1, _ACCOUNT, categories, half_streams, '2026-01-02T00:00:00Z'
    )
    assert conn.execute(
        "SELECT COUNT(*) FROM channel WHERE provider_id = 1 AND stale_since IS NOT NULL"
    ).fetchone()[0] == 20000
    assert conn.execute(
        "SELECT COUNT(*) FROM channel WHERE provider_id = 1 AND stale_since IS NULL"
    ).fetchone()[0] == 20000
