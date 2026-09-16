# -*- coding: utf-8 -*-
import gzip
import io
import lzma
import xml.etree.ElementTree as ET

import pytest

from kodimate import db, epg, ingest


_DB_COUNTER = [0]


def _make_conn(tmp_path):
    _DB_COUNTER[0] += 1
    conn = db.open_db(str(tmp_path / 'k{0}.db'.format(_DB_COUNTER[0])))
    conn.execute(
        "INSERT INTO provider (id, kind, name, enabled) VALUES (1, 'm3u', 'P1', 1)"
    )
    epg_source_id = conn.execute(
        "INSERT INTO epg_source (provider_id, url) VALUES (1, 'http://epg.example/g.xml')"
    ).lastrowid
    return conn, epg_source_id


_XML = """<?xml version="1.0" encoding="UTF-8"?>
<tv>
  <channel id="bbcnews.uk">
    <display-name>BBC News HD</display-name>
  </channel>
  <programme start="20240101120000 +0000" stop="20240101123000 +0000" channel="bbcnews.uk">
    <title>Midday News</title>
    <sub-title>Live</sub-title>
    <desc>The news at midday.</desc>
    <icon src="http://icons.example/bbcnews.png" />
    <category>News</category>
  </programme>
</tv>
"""


def _stream(text):
    return io.BytesIO(text.encode('utf-8'))


def _programme_rows(conn, epg_source_id):
    return conn.execute(
        "SELECT xmltv_channel_id, start, end, title, subtitle, description, "
        "icon_url, category, catchup_id FROM programme WHERE epg_source_id = ?",
        (epg_source_id,),
    ).fetchall()


# -- strip_source_suffix -----------------------------------------------------

def test_strip_source_suffix_removes_srcnn_suffix():
    assert epg.strip_source_suffix('FoxCricket.au (src05)') == 'FoxCricket.au'


def test_strip_source_suffix_leaves_plain_id_untouched():
    assert epg.strip_source_suffix('bbcnews.uk') == 'bbcnews.uk'


def test_strip_source_suffix_none_stays_none():
    assert epg.strip_source_suffix(None) is None


# -- plain / gzip / lzma parity ----------------------------------------------

def test_plain_gzip_lzma_produce_identical_programme_rows(tmp_path):
    plain_conn, plain_src = _make_conn(tmp_path)
    epg.load_xmltv(plain_conn, plain_src, _stream(_XML), '2024-01-01T00:00:00Z')
    plain_rows = _programme_rows(plain_conn, plain_src)

    gzip_conn, gzip_src = _make_conn(tmp_path)
    gzip_stream = io.BytesIO(gzip.compress(_XML.encode('utf-8')))
    epg.load_xmltv(gzip_conn, gzip_src, gzip_stream, '2024-01-01T00:00:00Z')
    gzip_rows = _programme_rows(gzip_conn, gzip_src)

    lzma_conn, lzma_src = _make_conn(tmp_path)
    lzma_stream = io.BytesIO(lzma.compress(_XML.encode('utf-8')))
    epg.load_xmltv(lzma_conn, lzma_src, lzma_stream, '2024-01-01T00:00:00Z')
    lzma_rows = _programme_rows(lzma_conn, lzma_src)

    assert plain_rows == gzip_rows == lzma_rows
    assert plain_rows == [(
        'bbcnews.uk', '2024-01-01T12:00:00Z', '2024-01-01T12:30:00Z',
        'Midday News', 'Live', 'The news at midday.',
        'http://icons.example/bbcnews.png', 'News', None,
    )]


# -- time parsing -------------------------------------------------------------

def test_parse_xmltv_time_with_zero_offset():
    assert epg.parse_xmltv_time('20240101120000 +0000') == '2024-01-01T12:00:00Z'


def test_parse_xmltv_time_with_nonzero_offset():
    assert epg.parse_xmltv_time('20240101120000 +0530') == '2024-01-01T06:30:00Z'


def test_parse_xmltv_time_with_no_offset():
    assert epg.parse_xmltv_time('20240101120000') == '2024-01-01T12:00:00Z'


def test_parse_xmltv_time_twelve_digit():
    assert epg.parse_xmltv_time('202401011200') == '2024-01-01T12:00:00Z'


def test_parse_xmltv_time_unparsable_returns_none():
    assert epg.parse_xmltv_time('not-a-time') is None


# -- retention ----------------------------------------------------------------

def test_old_programme_not_retained_recent_is(tmp_path):
    conn, src = _make_conn(tmp_path)
    xml = """<tv>
      <channel id="c1"><display-name>C1</display-name></channel>
      <programme start="20240101000000 +0000" stop="20240101010000 +0000" channel="c1">
        <title>Old</title>
      </programme>
      <programme start="20240108060000 +0000" stop="20240108070000 +0000" channel="c1">
        <title>Recent</title>
      </programme>
    </tv>"""
    epg.load_xmltv(conn, src, _stream(xml), '2024-01-08T12:00:00Z')
    titles = {row[3] for row in _programme_rows(conn, src)}
    assert titles == {'Recent'}


# -- staging swap ---------------------------------------------------------

def test_second_load_replaces_wholesale_and_drops_staging(tmp_path):
    conn, src = _make_conn(tmp_path)
    epg.load_xmltv(conn, src, _stream(_XML), '2024-01-01T00:00:00Z')

    other_xml = """<tv>
      <channel id="other.uk"><display-name>Other</display-name></channel>
      <programme start="20240101130000 +0000" stop="20240101140000 +0000" channel="other.uk">
        <title>Other Show</title>
      </programme>
    </tv>"""
    epg.load_xmltv(conn, src, _stream(other_xml), '2024-01-01T00:00:00Z')

    rows = _programme_rows(conn, src)
    assert [r[0] for r in rows] == ['other.uk']
    with pytest.raises(Exception):
        conn.execute("SELECT * FROM programme_staging")


def test_rows_for_a_different_epg_source_untouched(tmp_path):
    conn, src1 = _make_conn(tmp_path)
    conn.execute("INSERT INTO provider (id, kind, name, enabled) VALUES (2, 'm3u', 'P2', 1)")
    src2 = conn.execute(
        "INSERT INTO epg_source (provider_id, url) VALUES (2, 'http://epg.example/g2.xml')"
    ).lastrowid

    epg.load_xmltv(conn, src1, _stream(_XML), '2024-01-01T00:00:00Z')
    epg.load_xmltv(conn, src2, _stream(_XML), '2024-01-01T00:00:00Z')
    epg.load_xmltv(conn, src1, _stream("<tv></tv>"), '2024-01-01T00:00:00Z')

    assert _programme_rows(conn, src1) == []
    assert len(_programme_rows(conn, src2)) == 1


def test_config_version_change_during_swap_raises_and_commits_nothing(tmp_path):
    conn, src = _make_conn(tmp_path)
    conn.execute("UPDATE provider SET config_version = 5 WHERE id = 1")

    with pytest.raises(ingest.ConfigVersionChanged):
        epg.load_xmltv(
            conn, src, _stream(_XML), '2024-01-01T00:00:00Z',
            expected_config_version=4,
        )

    assert _programme_rows(conn, src) == []
    assert conn.execute(
        "SELECT last_fetched_at FROM epg_source WHERE id = ?", (src,)
    ).fetchone()[0] is None


def test_etag_last_modified_last_fetched_at_stored(tmp_path):
    conn, src = _make_conn(tmp_path)
    epg.load_xmltv(
        conn, src, _stream(_XML), '2024-01-01T00:00:00Z',
        etag='"abc"', last_modified='Mon, 01 Jan 2024 00:00:00 GMT',
    )
    row = conn.execute(
        "SELECT etag, last_modified, last_fetched_at FROM epg_source WHERE id = ?", (src,)
    ).fetchone()
    assert row == ('"abc"', 'Mon, 01 Jan 2024 00:00:00 GMT', '2024-01-01T00:00:00Z')


# -- security: DOCTYPE rejection / size cap ---------------------------------

def test_doctype_prologue_raises_parse_error_and_leaves_programme_untouched(tmp_path):
    conn, src = _make_conn(tmp_path)
    epg.load_xmltv(conn, src, _stream(_XML), '2024-01-01T00:00:00Z')

    malicious = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE tv [<!ENTITY a "x">]>'
        '<tv><channel id="c1"><display-name>C1</display-name></channel></tv>'
    )
    with pytest.raises(ET.ParseError):
        epg.load_xmltv(conn, src, _stream(malicious), '2024-01-01T00:00:00Z')

    # The prior successful load's rows are untouched by the aborted one.
    assert len(_programme_rows(conn, src)) == 1
    with pytest.raises(Exception):
        conn.execute("SELECT * FROM programme_staging")


def test_oversized_document_raises_epg_too_large_and_drops_staging(tmp_path, monkeypatch):
    conn, src = _make_conn(tmp_path)
    epg.load_xmltv(conn, src, _stream(_XML), '2024-01-01T00:00:00Z')
    monkeypatch.setattr(epg, 'MAX_XMLTV_BYTES', 50)

    with pytest.raises(epg.EpgTooLarge):
        epg.load_xmltv(conn, src, _stream(_XML), '2024-01-01T00:00:00Z')

    assert len(_programme_rows(conn, src)) == 1
    with pytest.raises(Exception):
        conn.execute("SELECT * FROM programme_staging")


# -- retention: prune_expired -------------------------------------------

def test_prune_expired_deletes_only_rows_past_retention(tmp_path):
    conn, src = _make_conn(tmp_path)
    conn.execute(
        "INSERT INTO programme (epg_source_id, xmltv_channel_id, start, end, title) "
        "VALUES (?, 'c1', '2024-01-01T00:00:00Z', '2024-01-01T01:00:00Z', 'Old')",
        (src,),
    )
    conn.execute(
        "INSERT INTO programme (epg_source_id, xmltv_channel_id, start, end, title) "
        "VALUES (?, 'c1', '2024-01-08T06:00:00Z', '2024-01-08T07:00:00Z', 'Recent')",
        (src,),
    )

    epg.prune_expired(conn, src, '2024-01-08T12:00:00Z')

    titles = {row[0] for row in conn.execute(
        "SELECT title FROM programme WHERE epg_source_id = ?", (src,)
    ).fetchall()}
    assert titles == {'Recent'}


# -- epg_channel rows -----------------------------------------------------

def test_epg_channel_rows_declared_and_programme_only(tmp_path):
    conn, src = _make_conn(tmp_path)
    xml = """<tv>
      <channel id="declared.uk"><display-name>Declared Ch HD</display-name></channel>
      <programme start="20240101120000 +0000" stop="20240101123000 +0000" channel="declared.uk">
        <title>A</title>
      </programme>
      <programme start="20240101120000 +0000" stop="20240101123000 +0000" channel="undeclared.uk">
        <title>B</title>
      </programme>
    </tv>"""
    epg.load_xmltv(conn, src, _stream(xml), '2024-01-01T00:00:00Z')

    rows = dict(conn.execute(
        "SELECT xmltv_channel_id, normalised_name FROM epg_channel WHERE epg_source_id = ?",
        (src,),
    ).fetchall())
    assert rows['declared.uk'] == ingest.normalise_name('Declared Ch HD')
    assert rows['undeclared.uk'] is None


# -- matching ---------------------------------------------------------------

def _add_channel(conn, provider_id, channel_key, name, epg_channel_id):
    conn.execute(
        "INSERT INTO channel (provider_id, channel_key, name, normalised_name, "
        "stream_url, epg_channel_id) VALUES (?, ?, ?, ?, 'http://x', ?)",
        (provider_id, channel_key, name, ingest.normalise_name(name), epg_channel_id),
    )


def test_match_channels_exact_id(tmp_path):
    conn, src = _make_conn(tmp_path)
    conn.execute(
        "INSERT INTO epg_channel (epg_source_id, xmltv_channel_id, normalised_name) "
        "VALUES (?, 'bbcnews.uk', 'bbcnewshd')", (src,),
    )
    _add_channel(conn, 1, 'k1', 'BBC News HD', 'bbcnews.uk')

    epg.match_channels(conn, 1)

    assert conn.execute(
        "SELECT epg_channel_id FROM channel WHERE channel_key = 'k1'"
    ).fetchone() == ('bbcnews.uk',)


def test_match_channels_strips_src_suffix(tmp_path):
    conn, src = _make_conn(tmp_path)
    conn.execute(
        "INSERT INTO epg_channel (epg_source_id, xmltv_channel_id, normalised_name) "
        "VALUES (?, 'FoxCricket.au', 'foxcricket')", (src,),
    )
    _add_channel(conn, 1, 'k1', 'FoxCricket', 'FoxCricket.au (src05)')

    epg.match_channels(conn, 1)

    assert conn.execute(
        "SELECT epg_channel_id FROM channel WHERE channel_key = 'k1'"
    ).fetchone() == ('FoxCricket.au',)


def test_match_channels_name_fallback(tmp_path):
    conn, src = _make_conn(tmp_path)
    conn.execute(
        "INSERT INTO epg_channel (epg_source_id, xmltv_channel_id, normalised_name) "
        "VALUES (?, 'realid.uk', ?)", (src, ingest.normalise_name('BBC News')),
    )
    _add_channel(conn, 1, 'k1', 'BBC News HD', 'nomatch')

    epg.match_channels(conn, 1)

    assert conn.execute(
        "SELECT epg_channel_id FROM channel WHERE channel_key = 'k1'"
    ).fetchone() == ('realid.uk',)


def test_match_channels_unmatched_is_null(tmp_path):
    conn, src = _make_conn(tmp_path)
    _add_channel(conn, 1, 'k1', 'Totally Unknown Channel', 'nomatch')

    epg.match_channels(conn, 1)

    assert conn.execute(
        "SELECT epg_channel_id FROM channel WHERE channel_key = 'k1'"
    ).fetchone() == (None,)


def test_match_channels_name_fallback_is_deterministic_on_collision(tmp_path):
    conn, src = _make_conn(tmp_path)
    norm = ingest.normalise_name('BBC News')
    conn.execute(
        "INSERT INTO epg_channel (epg_source_id, xmltv_channel_id, normalised_name) "
        "VALUES (?, 'zzz.uk', ?)", (src, norm),
    )
    conn.execute(
        "INSERT INTO epg_channel (epg_source_id, xmltv_channel_id, normalised_name) "
        "VALUES (?, 'aaa.uk', ?)", (src, norm),
    )
    _add_channel(conn, 1, 'k1', 'BBC News HD', 'nomatch')

    epg.match_channels(conn, 1)

    assert conn.execute(
        "SELECT epg_channel_id FROM channel WHERE channel_key = 'k1'"
    ).fetchone() == ('aaa.uk',)


def test_match_channels_provider_without_epg_source_all_null_no_error(tmp_path):
    conn = db.open_db(str(tmp_path / 'k.db'))
    conn.execute("INSERT INTO provider (id, kind, name, enabled) VALUES (1, 'm3u', 'P1', 1)")
    _add_channel(conn, 1, 'k1', 'Some Channel', 'anything')

    epg.match_channels(conn, 1)

    assert conn.execute(
        "SELECT epg_channel_id FROM channel WHERE channel_key = 'k1'"
    ).fetchone() == (None,)
