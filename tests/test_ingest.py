# -*- coding: utf-8 -*-
import os

import pytest

from kodimate import db, ingest, m3u

_FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')


def _read_fixture(name):
    with open(os.path.join(_FIXTURES, name), 'r') as f:
        return f.read()


def _make_db(tmp_path):
    conn = db.open_db(str(tmp_path / 'k.db'))
    conn.execute(
        "INSERT INTO provider (id, kind, name, enabled) VALUES (1, 'm3u', 'Test', 1)"
    )
    return conn


def _channels_by_key(conn, provider_id=1):
    rows = conn.execute(
        "SELECT channel_key, name, normalised_name, stream_url, group_id, "
        "provider_number, catchup_days, catchup_mode, catchup_source, "
        "catchup_correction_hours, headers_json, stale_since, last_seen_at "
        "FROM channel WHERE provider_id = ?",
        (provider_id,),
    ).fetchall()
    cols = [
        'channel_key', 'name', 'normalised_name', 'stream_url', 'group_id',
        'provider_number', 'catchup_days', 'catchup_mode', 'catchup_source',
        'catchup_correction_hours', 'headers_json', 'stale_since', 'last_seen_at',
    ]
    return {row[0]: dict(zip(cols, row)) for row in rows}


def test_malformed_playlist_raises(tmp_path):
    conn = _make_db(tmp_path)
    with pytest.raises(m3u.M3UError):
        ingest.refresh_m3u_provider(conn, 1, _read_fixture('malformed.m3u'), '2024-01-01T00:00:00Z')


def test_channel_identity_rules(tmp_path):
    conn = _make_db(tmp_path)
    ingest.refresh_m3u_provider(conn, 1, _read_fixture('basic.m3u'), '2024-01-01T00:00:00Z')
    channels = _channels_by_key(conn)

    # Unique tvg-id kept as-is.
    assert 'one.us' in channels
    # Duplicate tvg-id ("dup") falls back to the stripped URL (scheme+query removed).
    assert 'example.com/two' in channels
    assert 'example.com/three' in channels
    # No tvg-id at all -> stripped URL.
    assert 'example.com/four' in channels
    assert channels['one.us']['stream_url'] == 'http://example.com/one?token=abc'


def test_duplicate_stripped_url_falls_back_to_full_url(tmp_path):
    conn = _make_db(tmp_path)
    ingest.refresh_m3u_provider(conn, 1, _read_fixture('collision.m3u'), '2024-01-01T00:00:00Z')
    channels = _channels_by_key(conn)
    assert 'http://example.com/collide?x=1' in channels
    assert 'http://example.com/collide?x=2' in channels


def test_groups_first_segment_and_uncategorised(tmp_path):
    conn = _make_db(tmp_path)
    ingest.refresh_m3u_provider(conn, 1, _read_fixture('basic.m3u'), '2024-01-01T00:00:00Z')
    channels = _channels_by_key(conn)
    groups = dict(conn.execute("SELECT id, name FROM channel_group WHERE provider_id = 1").fetchall())

    assert groups[channels['one.us']['group_id']] == 'News'
    assert groups[channels['example.com/four']['group_id']] == ingest.UNCATEGORISED
    # Every channel has exactly one group.
    for row in channels.values():
        assert row['group_id'] is not None


def test_catchup_and_headers_persisted(tmp_path):
    conn = _make_db(tmp_path)
    ingest.refresh_m3u_provider(conn, 1, _read_fixture('basic.m3u'), '2024-01-01T00:00:00Z')
    channel = _channels_by_key(conn)['one.us']
    assert channel['catchup_mode'] == 'append'
    assert channel['catchup_source'] == '?utc={utc}'
    assert channel['catchup_days'] == 7
    assert channel['catchup_correction_hours'] == 1.5
    assert '"User-Agent": "MyUA"' in channel['headers_json']


def test_header_level_catchup_is_per_channel_default(tmp_path):
    conn = _make_db(tmp_path)
    ingest.refresh_m3u_provider(
        conn, 1, _read_fixture('catchup_header_default.m3u'), '2024-01-01T00:00:00Z'
    )
    channels = _channels_by_key(conn)

    inherited = channels['inherits']
    assert inherited['catchup_mode'] == 'shift'
    assert inherited['catchup_source'] == '?utc={utc}'
    assert inherited['catchup_days'] == 3
    assert inherited['catchup_correction_hours'] == 2.0

    overridden = channels['overrides']
    assert overridden['catchup_mode'] == 'default'
    assert overridden['catchup_days'] == 7
    # Not overridden at channel level, so still falls back to the header.
    assert overridden['catchup_source'] == '?utc={utc}'
    assert overridden['catchup_correction_hours'] == 2.0


def test_second_refresh_marks_missing_channel_stale(tmp_path):
    conn = _make_db(tmp_path)
    ingest.refresh_m3u_provider(conn, 1, _read_fixture('basic.m3u'), '2024-01-01T00:00:00Z')
    before = ingest.listable_channel_count(conn, 1)

    ingest.refresh_m3u_provider(conn, 1, _read_fixture('one_channel.m3u'), '2024-01-02T00:00:00Z')
    channels = _channels_by_key(conn)
    after = ingest.listable_channel_count(conn, 1)

    assert channels['example.com/four']['stale_since'] == '2024-01-02T00:00:00Z'
    assert after == before - 3
    assert channels['one.us']['stale_since'] is None


def test_returning_channel_clears_stale(tmp_path):
    conn = _make_db(tmp_path)
    ingest.refresh_m3u_provider(conn, 1, _read_fixture('basic.m3u'), '2024-01-01T00:00:00Z')
    ingest.refresh_m3u_provider(conn, 1, _read_fixture('one_channel.m3u'), '2024-01-02T00:00:00Z')
    ingest.refresh_m3u_provider(conn, 1, _read_fixture('basic.m3u'), '2024-01-03T00:00:00Z')

    channels = _channels_by_key(conn)
    assert channels['example.com/four']['stale_since'] is None


def test_stale_channel_purged_after_seven_days(tmp_path):
    conn = _make_db(tmp_path)
    ingest.refresh_m3u_provider(conn, 1, _read_fixture('basic.m3u'), '2024-01-01T00:00:00Z')
    ingest.refresh_m3u_provider(conn, 1, _read_fixture('one_channel.m3u'), '2024-01-02T00:00:00Z')
    # 7 days after going stale on 2024-01-02: purge should happen once "now" reaches 2024-01-09.
    ingest.refresh_m3u_provider(conn, 1, _read_fixture('one_channel.m3u'), '2024-01-09T00:00:01Z')

    channels = _channels_by_key(conn)
    assert 'example.com/four' not in channels
    assert 'example.com/two' not in channels
    assert 'example.com/three' not in channels


def test_override_row_survives_rebuild(tmp_path):
    conn = _make_db(tmp_path)
    ingest.refresh_m3u_provider(conn, 1, _read_fixture('basic.m3u'), '2024-01-01T00:00:00Z')
    conn.execute(
        "INSERT INTO channel_override (provider_id, channel_key, hidden) VALUES (1, 'one.us', 1)"
    )

    ingest.refresh_m3u_provider(conn, 1, _read_fixture('basic.m3u'), '2024-01-02T00:00:00Z')

    override = conn.execute(
        "SELECT hidden FROM channel_override WHERE provider_id = 1 AND channel_key = 'one.us'"
    ).fetchone()
    assert override == (1,)
    # Hidden override excludes the channel from the listable count.
    assert ingest.listable_channel_count(conn, 1) == 3


def test_epg_source_upserted_from_header(tmp_path):
    conn = _make_db(tmp_path)
    outcome = ingest.refresh_m3u_provider(conn, 1, _read_fixture('basic.m3u'), '2024-01-01T00:00:00Z')
    assert outcome.epg_url == 'http://epg.example/guide.xml'
    row = conn.execute("SELECT url FROM epg_source WHERE provider_id = 1").fetchone()
    assert row == ('http://epg.example/guide.xml',)


def test_epg_override_url_wins_over_playlist_header(tmp_path):
    conn = _make_db(tmp_path)
    conn.execute(
        "UPDATE provider SET epg_override_url = ? WHERE id = 1",
        ('http://override.example/guide.xml',),
    )
    outcome = ingest.refresh_m3u_provider(conn, 1, _read_fixture('basic.m3u'), '2024-01-01T00:00:00Z')
    assert outcome.epg_url == 'http://override.example/guide.xml'
    row = conn.execute("SELECT url FROM epg_source WHERE provider_id = 1").fetchone()
    assert row == ('http://override.example/guide.xml',)


def test_no_epg_source_url_when_no_header_and_no_override(tmp_path):
    conn = _make_db(tmp_path)
    outcome = ingest.refresh_m3u_provider(
        conn, 1, _read_fixture('one_channel.m3u'), '2024-01-01T00:00:00Z'
    )
    assert outcome.epg_url is None
    assert conn.execute(
        "SELECT COUNT(*) FROM epg_source WHERE provider_id = 1"
    ).fetchone()[0] == 0


def test_epg_source_url_change_clears_etag(tmp_path):
    conn = _make_db(tmp_path)
    ingest.refresh_m3u_provider(conn, 1, _read_fixture('basic.m3u'), '2024-01-01T00:00:00Z')
    conn.execute(
        "UPDATE epg_source SET etag = 'stale-etag', last_modified = 'stale-lm' "
        "WHERE provider_id = 1"
    )
    conn.execute(
        "UPDATE provider SET epg_override_url = ? WHERE id = 1",
        ('http://override.example/guide.xml',),
    )

    ingest.refresh_m3u_provider(conn, 1, _read_fixture('basic.m3u'), '2024-01-02T00:00:00Z')

    row = conn.execute(
        "SELECT url, etag, last_modified FROM epg_source WHERE provider_id = 1"
    ).fetchone()
    assert row == ('http://override.example/guide.xml', None, None)


def test_config_version_changed_rolls_back(tmp_path):
    conn = _make_db(tmp_path)
    conn.execute("UPDATE provider SET config_version = 5 WHERE id = 1")
    with pytest.raises(ingest.ConfigVersionChanged):
        ingest.refresh_m3u_provider(
            conn, 1, _read_fixture('basic.m3u'), '2024-01-01T00:00:00Z',
            expected_config_version=4,
        )
    assert conn.execute("SELECT COUNT(*) FROM channel WHERE provider_id = 1").fetchone()[0] == 0
