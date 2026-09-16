# -*- coding: utf-8 -*-
import pytest

from kodimate import m3u


def test_raises_when_not_an_m3u_playlist():
    with pytest.raises(m3u.M3UError):
        m3u.parse("just some random text\nwith no markers")


def test_parses_header_attrs():
    text = (
        '#EXTM3U url-tvg="http://epg.example/guide.xml" catchup="default"\n'
        '#EXTINF:-1,Channel One\n'
        'http://example.com/one\n'
    )
    playlist = m3u.parse(text)
    assert playlist.header_attrs['url-tvg'] == 'http://epg.example/guide.xml'
    assert playlist.header_attrs['catchup'] == 'default'


def test_parses_basic_entry_fields():
    text = (
        '#EXTM3U\n'
        '#EXTINF:-1 tvg-id="one.us" tvg-name="Channel One" tvg-logo="http://logo/1.png" '
        'tvg-chno="101" group-title="News;Extra",Channel One\n'
        'http://example.com/one\n'
    )
    playlist = m3u.parse(text)
    assert len(playlist.entries) == 1
    entry = playlist.entries[0]
    assert entry['name'] == 'Channel One'
    assert entry['url'] == 'http://example.com/one'
    assert entry['tvg_id'] == 'one.us'
    assert entry['tvg_name'] == 'Channel One'
    assert entry['tvg_logo'] == 'http://logo/1.png'
    assert entry['tvg_chno'] == 101
    assert entry['group_title'] == 'News'


def test_name_falls_back_to_tvg_name_when_display_name_missing():
    text = (
        '#EXTM3U\n'
        '#EXTINF:-1 tvg-name="Fallback Name",\n'
        'http://example.com/two\n'
    )
    entry = m3u.parse(text).entries[0]
    assert entry['name'] == 'Fallback Name'


def test_missing_group_title_is_none():
    text = '#EXTM3U\n#EXTINF:-1,No Group\nhttp://example.com/x\n'
    entry = m3u.parse(text).entries[0]
    assert entry['group_title'] is None


def test_non_numeric_tvg_chno_is_none():
    text = '#EXTM3U\n#EXTINF:-1 tvg-chno="abc",X\nhttp://example.com/x\n'
    entry = m3u.parse(text).entries[0]
    assert entry['tvg_chno'] is None


def test_entry_without_url_is_skipped():
    text = '#EXTM3U\n#EXTINF:-1,Orphan\n#EXTINF:-1,Real\nhttp://example.com/real\n'
    entries = m3u.parse(text).entries
    assert len(entries) == 1
    assert entries[0]['name'] == 'Real'


def test_pipe_suffix_headers_removed_from_url_and_parsed():
    text = (
        '#EXTM3U\n'
        '#EXTINF:-1,Piped\n'
        'http://example.com/piped|User-Agent=Mozilla%2F5.0&Referer=http%3A%2F%2Fexample.com%2F\n'
    )
    entry = m3u.parse(text).entries[0]
    assert entry['url'] == 'http://example.com/piped'
    assert entry['headers']['User-Agent'] == 'Mozilla%2F5.0'
    assert entry['headers']['Referer'] == 'http%3A%2F%2Fexample.com%2F'


def test_extvlcopt_headers_merged():
    text = (
        '#EXTM3U\n'
        '#EXTINF:-1,VLC\n'
        '#EXTVLCOPT:http-user-agent=MyUA\n'
        '#EXTVLCOPT:http-referrer=http://ref/\n'
        'http://example.com/vlc\n'
    )
    entry = m3u.parse(text).entries[0]
    assert entry['headers'] == {'User-Agent': 'MyUA', 'Referer': 'http://ref/'}


def test_kodiprop_stream_headers_merged():
    text = (
        '#EXTM3U\n'
        '#EXTINF:-1,Kodi\n'
        '#KODIPROP:inputstream.adaptive.stream_headers=User-Agent=KUA&Origin=http://o/\n'
        'http://example.com/kodi\n'
    )
    entry = m3u.parse(text).entries[0]
    assert entry['headers']['User-Agent'] == 'KUA'
    assert entry['headers']['Origin'] == 'http://o/'


def test_pipe_suffix_overrides_extvlcopt():
    text = (
        '#EXTM3U\n'
        '#EXTINF:-1,Both\n'
        '#EXTVLCOPT:http-user-agent=FromVLC\n'
        'http://example.com/both|User-Agent=FromPipe\n'
    )
    entry = m3u.parse(text).entries[0]
    assert entry['headers']['User-Agent'] == 'FromPipe'


def test_catchup_family_parsed():
    text = (
        '#EXTM3U\n'
        '#EXTINF:-1 catchup="append" catchup-source="?utc={utc}" catchup-days="7" '
        'catchup-correction="1.5",Catchup\n'
        'http://example.com/catchup\n'
    )
    entry = m3u.parse(text).entries[0]
    assert entry['catchup'] == 'append'
    assert entry['catchup_source'] == '?utc={utc}'
    assert entry['catchup_days'] == 7
    assert entry['catchup_correction'] == 1.5
