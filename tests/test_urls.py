# -*- coding: utf-8 -*-
import os
from datetime import datetime, timezone

from kodimate import urls


# ---------------------------------------------------------------------------
# live_form
# ---------------------------------------------------------------------------

def test_live_form_prefers_provider_stream_format():
    assert urls.live_form({'stream_format': 'm3u8', 'learned_stream_format': 'ts'}) == 'm3u8'


def test_live_form_falls_back_to_learned_then_ts():
    assert urls.live_form({'stream_format': None, 'learned_stream_format': 'm3u8'}) == 'm3u8'
    assert urls.live_form({'stream_format': None, 'learned_stream_format': None}) == 'ts'


def test_live_form_m3u8_requires_allowlist_membership():
    assert urls.live_form({'stream_format': 'm3u8'}, allowed_output_formats=['ts']) == 'ts'
    assert urls.live_form({'stream_format': 'm3u8'}, allowed_output_formats=['ts', 'm3u8']) == 'm3u8'


# ---------------------------------------------------------------------------
# xtream_live_url
# ---------------------------------------------------------------------------

def test_xtream_live_url_ts():
    url = urls.xtream_live_url('http://host:8080', 'u', 'p', 42, 'ts')
    assert url == 'http://host:8080/live/u/p/42.ts'


def test_xtream_live_url_m3u8_strips_trailing_host_slash():
    url = urls.xtream_live_url('http://host:8080/', 'u', 'p', 42, 'm3u8')
    assert url == 'http://host:8080/live/u/p/42.m3u8'


# ---------------------------------------------------------------------------
# xtream_catchup_url
# ---------------------------------------------------------------------------

def test_xtream_catchup_url_path_form():
    start_local = datetime(2024, 3, 5, 20, 30)
    url = urls.xtream_catchup_url('http://host', 'u', 'p', 42, start_local, 120, form='path')
    assert url == 'http://host/timeshift/u/p/120/2024-03-05:20-30/42.ts'


def test_xtream_catchup_url_query_form():
    start_local = datetime(2024, 3, 5, 8, 5)
    url = urls.xtream_catchup_url(
        'http://host/', 'u', 'p', 42, start_local, 60.0, form='query'
    )
    assert url == (
        'http://host/streaming/timeshift.php?username=u&password=p'
        '&stream=42&start=2024-03-05:08-05&duration=60'
    )


# ---------------------------------------------------------------------------
# m3u_live_url
# ---------------------------------------------------------------------------

def test_m3u_live_url_returns_stream_url_verbatim():
    channel = {'stream_url': 'http://host/stream.m3u8|User-Agent=x'}
    assert urls.m3u_live_url(channel) == 'http://host/stream.m3u8|User-Agent=x'


# ---------------------------------------------------------------------------
# substitute_template: one test per placeholder family
# ---------------------------------------------------------------------------

def test_substitute_utc_and_dollar_start():
    assert urls.substitute_template('{utc}', 100, 200, 300) == '100'
    assert urls.substitute_template('${start}', 100, 200, 300) == '100'


def test_substitute_utcend_and_dollar_end():
    assert urls.substitute_template('{utcend}', 100, 200, 300) == '200'
    assert urls.substitute_template('${end}', 100, 200, 300) == '200'


def test_substitute_lutc_now_timestamp():
    assert urls.substitute_template('{lutc}', 100, 200, 300) == '300'
    assert urls.substitute_template('${now}', 100, 200, 300) == '300'
    assert urls.substitute_template('${timestamp}', 100, 200, 300) == '300'


def test_substitute_duration_bare_and_n():
    assert urls.substitute_template('{duration}', 100, 220, 300) == '120'
    assert urls.substitute_template('{duration:60}', 100, 220, 300) == '2'


def test_substitute_offset_bare_and_n():
    assert urls.substitute_template('{offset}', 100, 220, 340) == '240'
    assert urls.substitute_template('{offset:60}', 100, 220, 340) == '4'


def test_substitute_bare_date_components():
    epoch = 1709670615  # 2024-03-05T20:30:15Z
    template = '{Y}{m}{d}{H}{M}{S}'
    assert urls.substitute_template(template, epoch, epoch, epoch) == '20240305203015'


def test_substitute_name_fmt_mini_language():
    epoch = 1709670615  # 2024-03-05T20:30:15Z
    result = urls.substitute_template('{utc:Y-m-d_H:M:S}', epoch, epoch, epoch)
    assert result == '2024-03-05_20:30:15'


def test_substitute_catchup_id():
    assert urls.substitute_template('{catchup-id}', 1, 2, 3, catchup_id=None) == '{catchup-id}'
    assert urls.substitute_template('{catchup-id}', 1, 2, 3, catchup_id=99) == '99'


def test_substitute_local_offset_shifts_wall_clock_tokens():
    epoch = 1709670615  # 2024-03-05T20:30:15Z
    template = '{Y}{m}{d}{H}{M}{S}'
    # -4h (Toronto EDT-style offset)
    result = urls.substitute_template(template, epoch, epoch, epoch, local_offset_seconds=-14400)
    assert result == '20240305163015'


def test_substitute_local_offset_leaves_epoch_tokens_unchanged():
    epoch = 1709670615
    assert urls.substitute_template(
        '{utc}', epoch, epoch, epoch, local_offset_seconds=-14400
    ) == str(epoch)


# ---------------------------------------------------------------------------
# xc_name_heuristic
# ---------------------------------------------------------------------------

def test_xc_name_heuristic_star_prefix():
    assert urls.xc_name_heuristic('* Channel One') is True


def test_xc_name_heuristic_plus_prefix():
    assert urls.xc_name_heuristic('[+] Channel Two') is True


def test_xc_name_heuristic_no_prefix():
    assert urls.xc_name_heuristic('Channel Three') is False


# ---------------------------------------------------------------------------
# m3u_catchup_url: modes
# ---------------------------------------------------------------------------

START, END, NOW = 1000, 1600, 1700


def test_m3u_catchup_default_with_source():
    channel = {
        'stream_url': 'http://host/live.m3u8',
        'catchup_mode': 'default',
        'catchup_source': 'http://host/vod?from={utc}&to={utcend}',
    }
    assert urls.m3u_catchup_url(channel, START, END, NOW) == 'http://host/vod?from=1000&to=1600'


def test_m3u_catchup_default_without_source_non_xc_url_yields_none():
    channel = {'stream_url': 'http://host/live.m3u8', 'catchup_mode': 'default'}
    result = urls.m3u_catchup_url(channel, START, END, NOW)
    assert result is None


def test_m3u_catchup_default_without_source_xc_shaped_ts_url_builds_timeshift():
    channel = {
        'stream_url': 'https://xc.example/live/u/p/1.ts',
        'catchup_mode': 'default',
    }
    result = urls.m3u_catchup_url(channel, START, 100600, NOW)
    dt = datetime.utcfromtimestamp(START)
    stamp = dt.strftime('%Y-%m-%d:%H-%M')
    assert result == (
        'https://xc.example/timeshift/u/p/1660/{0}/1.ts'.format(stamp)
    )


def test_m3u_catchup_default_without_source_xc_shaped_url_uses_local_offset():
    channel = {
        'stream_url': 'https://xc.example/live/u/p/1.ts',
        'catchup_mode': 'default',
    }
    result = urls.m3u_catchup_url(channel, START, 100600, NOW, local_offset_seconds=-14400)
    dt = datetime.utcfromtimestamp(START - 14400)
    stamp = dt.strftime('%Y-%m-%d:%H-%M')
    assert result == (
        'https://xc.example/timeshift/u/p/1660/{0}/1.ts'.format(stamp)
    )


def test_m3u_catchup_default_with_source_unchanged():
    channel = {
        'stream_url': 'http://host/live.m3u8',
        'catchup_mode': 'default',
        'catchup_source': 'http://host/vod?from={utc}&to={utcend}',
    }
    assert urls.m3u_catchup_url(channel, START, END, NOW) == 'http://host/vod?from=1000&to=1600'


def test_m3u_catchup_append_with_source():
    channel = {
        'stream_url': 'http://host/live.m3u8',
        'catchup_mode': 'append',
        'catchup_source': '&extra={utc}',
    }
    result = urls.m3u_catchup_url(channel, START, END, NOW)
    assert result == 'http://host/live.m3u8&extra=1000'


def test_m3u_catchup_append_without_source():
    channel = {'stream_url': 'http://host/live.m3u8', 'catchup_mode': 'append'}
    result = urls.m3u_catchup_url(channel, START, END, NOW)
    assert result == 'http://host/live.m3u8?utc=1000&lutc=1700'


def test_m3u_catchup_shift_no_existing_query():
    channel = {'stream_url': 'http://host/live.m3u8', 'catchup_mode': 'shift'}
    result = urls.m3u_catchup_url(channel, START, END, NOW)
    assert result == 'http://host/live.m3u8?utc=1000&lutc=1700'


def test_m3u_catchup_timeshift_existing_query():
    channel = {'stream_url': 'http://host/live.m3u8?token=x', 'catchup_mode': 'timeshift'}
    result = urls.m3u_catchup_url(channel, START, END, NOW)
    assert result == 'http://host/live.m3u8?token=x&utc=1000&lutc=1700'


def test_m3u_catchup_flussonic_ts():
    channel = {
        'stream_url': 'http://ch01.spr24.net/151/mpegts?token=x',
        'catchup_mode': 'flussonic-ts',
    }
    result = urls.m3u_catchup_url(channel, START, END, NOW)
    assert result == 'http://ch01.spr24.net/151/timeshift_abs-1000.ts?token=x'


def test_m3u_catchup_fs_alias():
    channel = {
        'stream_url': 'http://ch01.spr24.net/151/mpegts?token=x',
        'catchup_mode': 'fs',
    }
    result = urls.m3u_catchup_url(channel, START, END, NOW)
    assert result == 'http://ch01.spr24.net/151/timeshift_abs-1000.ts?token=x'


def test_m3u_catchup_flussonic_hls():
    channel = {
        'stream_url': 'http://ch01.spr24.net/151/index.m3u8',
        'catchup_mode': 'flussonic-hls',
    }
    result = urls.m3u_catchup_url(channel, START, END, NOW)
    assert result == 'http://ch01.spr24.net/151/timeshift_rel-700.m3u8'


def test_m3u_catchup_flussonic_bare():
    channel = {
        'stream_url': 'http://ch01.spr24.net/151/index.m3u8',
        'catchup_mode': 'flussonic',
    }
    result = urls.m3u_catchup_url(channel, START, END, NOW)
    assert result == 'http://ch01.spr24.net/151/timeshift_rel-700.m3u8'


def test_m3u_catchup_xc():
    channel = {
        'stream_url': 'http://host/live/u/p/42.ts',
        'catchup_mode': 'xc',
    }
    result = urls.m3u_catchup_url(channel, START, 100600, NOW)
    dt = datetime.utcfromtimestamp(START)
    stamp = dt.strftime('%Y-%m-%d:%H-%M')
    assert result == 'http://host/timeshift/u/p/1660/{0}/42.ts'.format(stamp)


def test_m3u_catchup_xc_falls_back_to_default_mode_when_url_does_not_match():
    channel = {
        'stream_url': 'http://host/notxtreamshape' + PIPE,
        'catchup_mode': 'xc',
    }
    result = urls.m3u_catchup_url(channel, START, END, NOW)
    assert result is None


def test_m3u_catchup_flussonic_falls_back_to_default_mode_when_url_does_not_match():
    channel = {
        'stream_url': 'http://host' + PIPE,
        'catchup_mode': 'flussonic-ts',
    }
    result = urls.m3u_catchup_url(channel, START, END, NOW)
    assert result is None


def test_m3u_catchup_vod_with_source():
    channel = {
        'stream_url': 'http://host/live.m3u8',
        'catchup_mode': 'vod',
        'catchup_source': 'http://host/vod/{catchup-id}',
    }
    result = urls.m3u_catchup_url(channel, START, END, NOW, catchup_id='abc')
    assert result == 'http://host/vod/abc'


def test_m3u_catchup_vod_without_source_no_catchup_id():
    channel = {'stream_url': 'http://host/live.m3u8', 'catchup_mode': 'vod'}
    result = urls.m3u_catchup_url(channel, START, END, NOW)
    assert result == '{catchup-id}'


def test_m3u_catchup_vod_without_source_with_catchup_id():
    channel = {'stream_url': 'http://host/live.m3u8', 'catchup_mode': 'vod'}
    result = urls.m3u_catchup_url(channel, START, END, NOW, catchup_id='xyz')
    assert result == 'xyz'


# ---------------------------------------------------------------------------
# Pipe-suffix survives every mode
# ---------------------------------------------------------------------------

PIPE = '|User-Agent=x&Referer=y'


def test_pipe_survives_default_mode():
    channel = {
        'stream_url': 'http://host/live.m3u8' + PIPE,
        'catchup_mode': 'default',
        'catchup_source': 'http://host/vod?from={utc}',
    }
    result = urls.m3u_catchup_url(channel, START, END, NOW)
    assert result.endswith(PIPE)


def test_pipe_survives_append_mode():
    channel = {'stream_url': 'http://host/live.m3u8' + PIPE, 'catchup_mode': 'append'}
    result = urls.m3u_catchup_url(channel, START, END, NOW)
    assert result.endswith(PIPE)


def test_pipe_survives_shift_mode():
    channel = {'stream_url': 'http://host/live.m3u8' + PIPE, 'catchup_mode': 'shift'}
    result = urls.m3u_catchup_url(channel, START, END, NOW)
    assert result.endswith(PIPE)


def test_pipe_survives_flussonic_mode():
    channel = {
        'stream_url': 'http://ch01.spr24.net/151/mpegts?token=x' + PIPE,
        'catchup_mode': 'flussonic-ts',
    }
    result = urls.m3u_catchup_url(channel, START, END, NOW)
    assert result.endswith(PIPE)


def test_pipe_survives_xc_mode():
    channel = {'stream_url': 'http://host/live/u/p/42.ts' + PIPE, 'catchup_mode': 'xc'}
    result = urls.m3u_catchup_url(channel, START, 100600, NOW)
    assert result.endswith(PIPE)


def test_pipe_survives_vod_mode():
    channel = {'stream_url': 'http://host/live.m3u8' + PIPE, 'catchup_mode': 'vod'}
    result = urls.m3u_catchup_url(channel, START, END, NOW, catchup_id='abc')
    assert result.endswith(PIPE)


# ---------------------------------------------------------------------------
# correction_seconds / corrected_start
# ---------------------------------------------------------------------------

def test_correction_seconds_net_decimal_hours():
    assert urls.correction_seconds(-1.5, 1) == -1800


def test_corrected_start_applies_net_correction():
    start_epoch = 1_700_000_000
    channel = {'catchup_correction_hours': -1.5}
    provider = {'catchup_correction_hours': 1}
    assert urls.corrected_start(start_epoch, channel, provider) == start_epoch + 1800


def test_corrected_start_resolves_8pm_programme_to_wallclock():
    start_epoch = datetime(2024, 3, 5, 20, 0).replace(tzinfo=timezone.utc).timestamp()
    channel = {'catchup_correction_hours': -1.5}
    provider = {'catchup_correction_hours': 1}
    corrected = urls.corrected_start(start_epoch, channel, provider)
    corrected_dt = datetime.utcfromtimestamp(corrected)
    assert corrected_dt.hour == 20
    assert corrected_dt.minute == 30


def test_xtream_local_start_applies_tz_and_correction():
    start_epoch = 1_700_000_000
    provider = {'catchup_correction_hours': -0.5}
    dt = urls.xtream_local_start(start_epoch, 7200, provider)
    expected = datetime.utcfromtimestamp(start_epoch + 9000)
    assert dt == expected


# ---------------------------------------------------------------------------
# m3u_catchup_supported / xc_credentials
# ---------------------------------------------------------------------------

def test_m3u_catchup_supported_true_for_default_with_source():
    channel = {
        'stream_url': 'http://host/live.m3u8',
        'catchup_mode': 'default',
        'catchup_source': 'http://host/vod?from={utc}',
    }
    assert urls.m3u_catchup_supported(channel) is True


def test_m3u_catchup_supported_true_for_default_no_source_xc_shaped():
    channel = {
        'stream_url': 'https://xc.example/live/u/p/1.ts',
        'catchup_mode': 'default',
    }
    assert urls.m3u_catchup_supported(channel) is True


def test_m3u_catchup_supported_false_for_default_no_source_non_xc():
    channel = {'stream_url': 'http://host/live.m3u8', 'catchup_mode': 'default'}
    assert urls.m3u_catchup_supported(channel) is False


def test_m3u_catchup_supported_true_for_other_modes():
    channel = {'stream_url': 'http://host/live.m3u8', 'catchup_mode': 'append'}
    assert urls.m3u_catchup_supported(channel) is True


def test_xc_credentials_matches_xc_shaped_url():
    url = 'https://xc.example/live/u/p/1.ts'
    assert urls.xc_credentials(url) == ('https://xc.example', 'u', 'p')


def test_xc_credentials_none_for_non_xc_url():
    assert urls.xc_credentials('http://host/live.m3u8') is None


# ---------------------------------------------------------------------------
# Purity
# ---------------------------------------------------------------------------

def test_module_does_not_import_xbmc_or_db():
    source = open(
        os.path.join(os.path.dirname(__file__), '..', 'resources', 'lib', 'kodimate', 'urls.py')
    ).read()
    import_lines = [
        line.strip() for line in source.splitlines()
        if line.strip().startswith('import ') or line.strip().startswith('from ')
    ]
    assert not any('xbmc' in line for line in import_lines)
    assert not any('db' in line for line in import_lines)
