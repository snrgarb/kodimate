# -*- coding: utf-8 -*-
import os
import re
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
    # A positive range shorter than the divisor must still round up to 1,
    # never floor to 0 (a 0-minute duration is rejected by some providers).
    assert urls.substitute_template('{duration:60}', 100, 143, 300) == '1'


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


# ---------------------------------------------------------------------------
# catchup_granularity_seconds
# ---------------------------------------------------------------------------

def test_catchup_granularity_xtream_is_minute_precision():
    snapshot = {'kind': 'xtream'}
    assert urls.catchup_granularity_seconds(snapshot) == 60


def test_catchup_granularity_m3u_xc_shaped_default_is_minute_precision():
    snapshot = {
        'kind': 'm3u',
        'stream_url': 'https://xc.example/live/u/p/1.ts',
        'catchup_mode': 'default',
    }
    assert urls.catchup_granularity_seconds(snapshot) == 60


def test_catchup_granularity_m3u_xc_mode_is_minute_precision():
    snapshot = {
        'kind': 'm3u',
        'stream_url': 'https://xc.example/live/u/p/1.ts',
        'catchup_mode': 'xc',
    }
    assert urls.catchup_granularity_seconds(snapshot) == 60


def test_catchup_granularity_m3u_shift_is_second_precision():
    snapshot = {
        'kind': 'm3u', 'stream_url': 'http://host/live.m3u8', 'catchup_mode': 'shift',
    }
    assert urls.catchup_granularity_seconds(snapshot) == 1


def test_catchup_granularity_m3u_append_default_is_second_precision():
    snapshot = {
        'kind': 'm3u', 'stream_url': 'http://host/live.m3u8', 'catchup_mode': 'append',
    }
    assert urls.catchup_granularity_seconds(snapshot) == 1


def test_catchup_granularity_m3u_flussonic_ts_is_second_precision():
    snapshot = {
        'kind': 'm3u', 'stream_url': 'http://host/151/mpegts', 'catchup_mode': 'flussonic-ts',
    }
    assert urls.catchup_granularity_seconds(snapshot) == 1


def test_catchup_granularity_m3u_flussonic_hls_is_second_precision():
    snapshot = {
        'kind': 'm3u', 'stream_url': 'http://host/151/mpegts', 'catchup_mode': 'flussonic',
    }
    assert urls.catchup_granularity_seconds(snapshot) == 1


def test_catchup_granularity_m3u_custom_source_follows_its_own_tokens():
    minute_precision = {
        'kind': 'm3u', 'stream_url': 'http://host/live.m3u8', 'catchup_mode': 'append',
        'catchup_source': 'http://host/vod?from={Y}{m}{d}{H}{M}',
    }
    second_precision = {
        'kind': 'm3u', 'stream_url': 'http://host/live.m3u8', 'catchup_mode': 'append',
        'catchup_source': 'http://host/vod?from={utc}',
    }
    assert urls.catchup_granularity_seconds(minute_precision) == 60
    assert urls.catchup_granularity_seconds(second_precision) == 1


def test_xc_credentials_matches_xc_shaped_url():
    url = 'https://xc.example/live/u/p/1.ts'
    assert urls.xc_credentials(url) == ('https://xc.example', 'u', 'p')


def test_xc_credentials_none_for_non_xc_url():
    assert urls.xc_credentials('http://host/live.m3u8') is None


# ---------------------------------------------------------------------------
# m3u_catchup_template: pipe-suffix behaviour matches m3u_catchup_url's
# ---------------------------------------------------------------------------

def test_m3u_catchup_template_append_without_source_gets_pipe_suffix():
    channel = {'stream_url': 'http://host/live.m3u8' + PIPE, 'catchup_mode': 'append'}
    template = urls.m3u_catchup_template(channel)
    assert template == 'http://host/live.m3u8?utc={utc}&lutc={lutc}' + PIPE


def test_m3u_catchup_template_source_with_own_pipe_not_duplicated():
    channel = {
        'stream_url': 'http://host/live.m3u8' + PIPE, 'catchup_mode': 'append',
        'catchup_source': '&extra={utc}|Own-Pipe=1',
    }
    template = urls.m3u_catchup_template(channel)
    assert template == 'http://host/live.m3u8&extra={utc}|Own-Pipe=1'


def test_m3u_catchup_template_none_for_unbuildable_default_channel():
    channel = {'stream_url': 'http://host/live.m3u8', 'catchup_mode': 'default'}
    assert urls.m3u_catchup_template(channel) is None


# ---------------------------------------------------------------------------
# to_ffmpegdirect_format
# ---------------------------------------------------------------------------

def test_to_ffmpegdirect_format_start_variants():
    assert urls.to_ffmpegdirect_format('{start}') == '{utc}'
    assert urls.to_ffmpegdirect_format('${start}') == '{utc}'
    assert urls.to_ffmpegdirect_format('${utc}') == '{utc}'
    assert urls.to_ffmpegdirect_format('{utc}') == '{utc}'


def test_to_ffmpegdirect_format_end_variants():
    assert urls.to_ffmpegdirect_format('{end}') == '{utcend}'
    assert urls.to_ffmpegdirect_format('${end}') == '{utcend}'
    assert urls.to_ffmpegdirect_format('${utcend}') == '{utcend}'


def test_to_ffmpegdirect_format_now_variants():
    assert urls.to_ffmpegdirect_format('{now}') == '{lutc}'
    assert urls.to_ffmpegdirect_format('${now}') == '{lutc}'
    assert urls.to_ffmpegdirect_format('{timestamp}') == '{lutc}'
    assert urls.to_ffmpegdirect_format('${timestamp}') == '{lutc}'
    assert urls.to_ffmpegdirect_format('${lutc}') == '{lutc}'


def test_to_ffmpegdirect_format_offset_variants():
    assert urls.to_ffmpegdirect_format('{offset}') == '${offset}'
    assert urls.to_ffmpegdirect_format('${offset}') == '${offset}'
    assert urls.to_ffmpegdirect_format('${offset:60}') == '{offset:60}'
    assert urls.to_ffmpegdirect_format('{offset:60}') == '{offset:60}'


def test_to_ffmpegdirect_format_duration_variants():
    assert urls.to_ffmpegdirect_format('${duration}') == '{duration}'
    assert urls.to_ffmpegdirect_format('{duration}') == '{duration}'
    assert urls.to_ffmpegdirect_format('${duration:60}') == '{duration:60}'
    assert urls.to_ffmpegdirect_format('{duration:60}') == '{duration:60}'


def test_to_ffmpegdirect_format_dollarless_fmt_gets_dollar():
    assert urls.to_ffmpegdirect_format('{start:Y-m-d}') == '${start:Y-m-d}'
    assert urls.to_ffmpegdirect_format('{end:Y-m-d}') == '${end:Y-m-d}'
    assert urls.to_ffmpegdirect_format('{now:Y-m-d}') == '${now:Y-m-d}'
    assert urls.to_ffmpegdirect_format('{timestamp:Y-m-d}') == '${now:Y-m-d}'


def test_to_ffmpegdirect_format_dollar_fmt_loses_dollar():
    assert urls.to_ffmpegdirect_format('${utc:Y-m-d}') == '{utc:Y-m-d}'
    assert urls.to_ffmpegdirect_format('${utcend:Y-m-d}') == '{utcend:Y-m-d}'
    assert urls.to_ffmpegdirect_format('${lutc:Y-m-d}') == '{lutc:Y-m-d}'
    assert urls.to_ffmpegdirect_format('{utc:Y-m-d}') == '{utc:Y-m-d}'


def test_to_ffmpegdirect_format_date_components():
    assert urls.to_ffmpegdirect_format('${Y}${m}${d}${H}${M}${S}') == '{Y}{m}{d}{H}{M}{S}'
    assert urls.to_ffmpegdirect_format('{Y}{m}{d}{H}{M}{S}') == '{Y}{m}{d}{H}{M}{S}'


def test_to_ffmpegdirect_format_catchup_id():
    assert urls.to_ffmpegdirect_format('${catchup-id}') == '{catchup-id}'
    assert urls.to_ffmpegdirect_format('{catchup-id}') == '{catchup-id}'


def test_to_ffmpegdirect_format_leaves_other_text_untouched():
    assert urls.to_ffmpegdirect_format('http://host/vod?x=1&y=2') == 'http://host/vod?x=1&y=2'


def test_to_ffmpegdirect_format_idempotent():
    template = (
        '${start}{end}{now}${timestamp}{offset}${offset:60}${duration}'
        '{start:Y-m-d}${utc:H-M}${Y}${catchup-id}'
    )
    once = urls.to_ffmpegdirect_format(template)
    twice = urls.to_ffmpegdirect_format(once)
    assert once == twice


# ---------------------------------------------------------------------------
# ffmpegdirect_expand: a test-local mirror of FFmpegCatchupStream.cpp's own
# expansion, used below to prove catchup_format_spec's format strings
# expand to the same URLs the existing builders produce today.
# ---------------------------------------------------------------------------

_FFMPEGDIRECT_TOKEN_RE = re.compile(
    r'(?P<dollar>\$)?\{(?P<name>utc|utcend|lutc|start|end|now|timestamp'
    r'|duration|offset|catchup-id|Y|m|d|H|M|S)(?::(?P<fmt>[^}]*))?\}'
)


def ffmpegdirect_expand(format_string, offset, duration, now, timezone_shift, host_offset, catchup_id=None):
    epoch = offset - timezone_shift

    def local(t):
        return datetime.utcfromtimestamp(t + host_offset)

    def _repl(m):
        name = m.group('name')
        fmt = m.group('fmt')
        if name == 'catchup-id':
            return str(catchup_id) if catchup_id is not None else '{catchup-id}'
        if name in ('Y', 'm', 'd', 'H', 'M', 'S'):
            return local(epoch).strftime('%' + name)
        if name == 'duration':
            return str(duration // int(fmt)) if fmt is not None else str(duration)
        if name == 'offset':
            diff = now - epoch
            return str(diff // int(fmt)) if fmt is not None else str(diff)
        value = {
            'utc': epoch, 'start': epoch,
            'utcend': epoch + duration, 'end': epoch + duration,
            'lutc': now, 'now': now, 'timestamp': now,
        }[name]
        if fmt is not None:
            strftime_fmt = re.sub(r'[YmdHMS]', lambda mm: '%' + mm.group(0), fmt)
            return local(value).strftime(strftime_fmt)
        return str(value)

    return _FFMPEGDIRECT_TOKEN_RE.sub(_repl, format_string)


# ---------------------------------------------------------------------------
# catchup_format_spec: Xtream (path and query, correction 0 and 1.0h)
# ---------------------------------------------------------------------------

def test_catchup_format_spec_xtream_path_matches_xtream_catchup_url():
    server_offset = -14400  # America/Toronto, September (EDT)
    host_offset = 3600
    start, end, now = 1_700_000_000, 1_700_003_600, 1_700_007_200
    snapshot = {
        'kind': 'xtream',
        'xtream_host': 'http://host:8080', 'xtream_username': 'u', 'xtream_password': 'p',
        'channel_key': 42, 'stream_format': 'ts', 'learned_stream_format': None,
        'allowed_output_formats': None,
    }
    spec = urls.catchup_format_spec(snapshot, form='path')
    assert spec['granularity'] == 60
    assert spec['wall_clock'] is True
    for correction_hours in (0, 1.0):
        shift = host_offset - server_offset + int(correction_hours * 3600)
        expanded = ffmpegdirect_expand(spec['format_string'], start, end - start, now, shift, host_offset)
        provider = {'catchup_correction_hours': correction_hours}
        expected = urls.xtream_catchup_url(
            'http://host:8080', 'u', 'p', 42,
            urls.xtream_local_start(start, server_offset, provider),
            (end - start) // 60, form='path', ext='ts',
        )
        assert expanded == expected


def test_catchup_format_spec_xtream_query_matches_xtream_catchup_url():
    server_offset = -14400
    host_offset = 3600
    start, end, now = 1_700_000_000, 1_700_003_600, 1_700_007_200
    snapshot = {
        'kind': 'xtream',
        'xtream_host': 'http://host:8080', 'xtream_username': 'u', 'xtream_password': 'p',
        'channel_key': 42, 'stream_format': 'm3u8', 'learned_stream_format': None,
        'allowed_output_formats': ['m3u8'],
    }
    spec = urls.catchup_format_spec(snapshot, form='query')
    for correction_hours in (0, 1.0):
        shift = host_offset - server_offset + int(correction_hours * 3600)
        expanded = ffmpegdirect_expand(spec['format_string'], start, end - start, now, shift, host_offset)
        provider = {'catchup_correction_hours': correction_hours}
        expected = urls.xtream_catchup_url(
            'http://host:8080', 'u', 'p', 42,
            urls.xtream_local_start(start, server_offset, provider),
            (end - start) // 60, form='query', ext='m3u8',
        )
        assert expanded == expected


# ---------------------------------------------------------------------------
# catchup_format_spec: M3U, every catch-up mode
# ---------------------------------------------------------------------------

def _m3u_expand_matches(channel, start, end, now, server_offset=0, host_offset=0, correction=0, catchup_id=None):
    """(expanded, expected) pair: `ffmpegdirect_expand` of the format
    string `catchup_format_spec` builds for `channel`, versus what
    `m3u_catchup_url` itself builds for the corrected start."""
    snapshot = dict(channel, kind='m3u')
    spec = urls.catchup_format_spec(snapshot, form='path')
    corrected = start - correction
    shift = (host_offset - server_offset + correction) if spec['wall_clock'] else correction
    duration_param = end - corrected
    expanded = ffmpegdirect_expand(
        spec['format_string'], start, duration_param, now, shift, host_offset, catchup_id=catchup_id
    )
    expected = urls.m3u_catchup_url(channel, corrected, end, now, catchup_id, local_offset_seconds=server_offset)
    return expanded, expected


def test_catchup_format_spec_m3u_append_with_source_matches():
    channel = {
        'stream_url': 'http://host/live.m3u8', 'catchup_mode': 'append',
        'catchup_source': '&extra={utc}&lutc={lutc}&d={duration}&o={offset}',
    }
    expanded, expected = _m3u_expand_matches(
        channel, 1_700_000_000, 1_700_003_600, 1_700_007_200, correction=1800,
    )
    assert expanded == expected


def test_catchup_format_spec_m3u_append_without_source_matches():
    channel = {'stream_url': 'http://host/live.m3u8', 'catchup_mode': 'append'}
    expanded, expected = _m3u_expand_matches(channel, 1_700_000_000, 1_700_003_600, 1_700_007_200)
    assert expanded == expected


def test_catchup_format_spec_m3u_shift_matches():
    channel = {'stream_url': 'http://host/live.m3u8', 'catchup_mode': 'shift'}
    expanded, expected = _m3u_expand_matches(channel, 1_700_000_000, 1_700_003_600, 1_700_007_200)
    assert expanded == expected


def test_catchup_format_spec_m3u_flussonic_ts_matches():
    channel = {'stream_url': 'http://ch01.spr24.net/151/mpegts?token=x', 'catchup_mode': 'flussonic-ts'}
    expanded, expected = _m3u_expand_matches(channel, 1_700_000_000, 1_700_003_600, 1_700_007_200)
    assert expanded == expected


def test_catchup_format_spec_m3u_flussonic_hls_matches():
    channel = {'stream_url': 'http://ch01.spr24.net/151/index.m3u8', 'catchup_mode': 'flussonic-hls'}
    expanded, expected = _m3u_expand_matches(channel, 1_700_000_000, 1_700_003_600, 1_700_007_200)
    assert expanded == expected


def test_catchup_format_spec_m3u_xc_matches():
    channel = {'stream_url': 'http://host/live/u/p/42.ts', 'catchup_mode': 'xc'}
    expanded, expected = _m3u_expand_matches(
        channel, 1_700_000_000, 1_700_003_600, 1_700_007_200,
        server_offset=-14400, host_offset=3600, correction=1800,
    )
    assert expanded == expected


def test_catchup_format_spec_m3u_default_with_source_epoch_tokens_matches():
    channel = {
        'stream_url': 'http://host/live.m3u8', 'catchup_mode': 'default',
        'catchup_source': 'http://host/vod?from={utc}&to={lutc}&d={duration}&o={offset}',
    }
    expanded, expected = _m3u_expand_matches(
        channel, 1_700_000_000, 1_700_003_600, 1_700_007_200,
        server_offset=-14400, host_offset=3600, correction=1800,
    )
    assert expanded == expected


def test_catchup_format_spec_m3u_vod_matches():
    channel = {
        'stream_url': 'http://host/live.m3u8', 'catchup_mode': 'vod',
        'catchup_source': 'http://host/vod/{catchup-id}',
    }
    expanded, expected = _m3u_expand_matches(
        channel, 1_700_000_000, 1_700_003_600, 1_700_007_200, catchup_id='abc',
    )
    assert expanded == expected


def test_catchup_format_spec_returns_none_for_unbuildable_m3u_channel():
    snapshot = {'kind': 'm3u', 'stream_url': 'http://host/live.m3u8', 'catchup_mode': 'default'}
    assert urls.catchup_format_spec(snapshot, form='path') is None


# ---------------------------------------------------------------------------
# catchup_terminates
# ---------------------------------------------------------------------------

def test_catchup_terminates_true_for_xtream_format():
    fmt = urls.xtream_catchup_format('http://host', 'u', 'p', 1)
    assert urls.catchup_terminates(fmt) is True


def test_catchup_terminates_true_for_xc_format():
    template = urls.m3u_catchup_template({'stream_url': 'http://host/live/u/p/42.ts', 'catchup_mode': 'xc'})
    assert urls.catchup_terminates(urls.to_ffmpegdirect_format(template)) is True


def test_catchup_terminates_false_for_append():
    template = urls.m3u_catchup_template({'stream_url': 'http://host/live.m3u8', 'catchup_mode': 'append'})
    assert urls.catchup_terminates(urls.to_ffmpegdirect_format(template)) is False


def test_catchup_terminates_false_for_flussonic():
    template = urls.m3u_catchup_template({
        'stream_url': 'http://ch01.spr24.net/151/mpegts?token=x', 'catchup_mode': 'flussonic-ts',
    })
    assert urls.catchup_terminates(urls.to_ffmpegdirect_format(template)) is False


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
