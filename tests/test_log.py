import xbmc
import xbmcaddon

from kodimate import log


def test_redact_live_path_credentials():
    url = "http://host/live/USER/PASS/123.ts"
    assert log.redact(url) == "http://host/live/***/***/123.ts"


def test_redact_movie_series_timeshift_path_variants():
    assert log.redact("http://host/movie/U/P/1.mp4") == "http://host/movie/***/***/1.mp4"
    assert log.redact("http://host/series/U/P/1.mp4") == "http://host/series/***/***/1.mp4"
    assert log.redact("http://host/timeshift/U/P/100/1.ts") == "http://host/timeshift/***/***/100/1.ts"


def test_redact_xmltv_path_credentials():
    url = "http://host/USER/PASS/xmltv.php"
    assert log.redact(url) == "http://host/***/***/xmltv.php"


def test_redact_query_credentials():
    url = "http://host/xmltv.php?username=bob&password=secret&token=abc"
    assert log.redact(url) == "http://host/xmltv.php?username=***&password=***&token=***"


def test_redact_semicolon_separated_query_credentials():
    url = "http://host/get.php?username=u;password=p;type=m3u"
    assert log.redact(url) == "http://host/get.php?username=***;password=***;type=m3u"


def test_redact_leaves_url_without_credentials_unchanged():
    url = "http://host/hls/playlist.m3u8?quality=high"
    assert log.redact(url) == url


def test_debug_emits_only_when_setting_enabled():
    xbmc.log_calls[:] = []
    xbmcaddon._settings['debug'] = False

    log.debug("hidden")
    assert xbmc.log_calls == []

    xbmcaddon._settings['debug'] = True
    log.debug("shown")
    assert any("shown" in msg for msg, level in xbmc.log_calls)
