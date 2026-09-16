# -*- coding: utf-8 -*-
"""Pure URL builders for live playback and catch-up (timeshift) links.

No xbmc* imports, no DB access, no I/O: every function here takes plain
dicts/primitives and returns a string. Callers (player/service code) own
all Kodi and database interaction.

Timezone convention: wherever a Unix timestamp is broken down into
Y/m/d/H/M/S components (bare `{Y}{m}{d}...` tokens and the `{name:<fmt>}`
mini-language in `substitute_template`), the breakdown uses UTC
(`datetime.utcfromtimestamp`), never the host machine's local timezone.
This keeps template expansion deterministic and testable regardless of
where the addon runs; any provider-local wall-clock adjustment is applied
explicitly beforehand via `corrected_start`/`xtream_local_start`.
"""
import re
from datetime import datetime

_KNOWN_MODES = {
    'default', 'append', 'shift', 'timeshift',
    'flussonic', 'flussonic-hls', 'flussonic-ts', 'fs',
    'xc', 'vod',
}

# Matches {name}, {name:fmt}, ${name}, ${name:fmt} for every supported
# placeholder family (date-value names, duration/offset, catchup-id, and
# the bare single-letter date components).
_TOKEN_RE = re.compile(
    r'\$?\{(?P<name>utc|utcend|lutc|start|end|now|timestamp'
    r'|duration|offset|catchup-id|Y|m|d|H|M|S)(?::(?P<fmt>[^}]*))?\}'
)

_DATE_VALUE_NAMES = {
    'utc': 'start', 'start': 'start',
    'utcend': 'end', 'end': 'end',
    'lutc': 'now', 'now': 'now', 'timestamp': 'now',
}


def live_form(provider, allowed_output_formats=None):
    """Resolve the stream container ('ts' or 'm3u8') for live playback."""
    fmt = provider.get('stream_format') or provider.get('learned_stream_format') or 'ts'
    if fmt == 'm3u8' and (allowed_output_formats is None or 'm3u8' in allowed_output_formats):
        return 'm3u8'
    return 'ts'


def _strip_trailing_slash(host):
    if host.endswith('/'):
        return host[:-1]
    return host


def xtream_live_url(host, username, password, stream_id, form):
    """Build the Xtream live-stream URL for a channel."""
    host = _strip_trailing_slash(host)
    return '{0}/live/{1}/{2}/{3}.{4}'.format(host, username, password, stream_id, form)


def xtream_catchup_url(host, username, password, stream_id, start_local,
                        duration_minutes, form='path', ext='ts'):
    """Build the Xtream catch-up (timeshift) URL, path or query form."""
    host = _strip_trailing_slash(host)
    minutes = int(duration_minutes)
    stamp = start_local.strftime('%Y-%m-%d:%H-%M')
    if form == 'query':
        return (
            '{0}/streaming/timeshift.php?username={1}&password={2}'
            '&stream={3}&start={4}&duration={5}'
        ).format(host, username, password, stream_id, stamp, minutes)
    return '{0}/timeshift/{1}/{2}/{3}/{4}/{5}.{6}'.format(
        host, username, password, minutes, stamp, stream_id, ext
    )


def m3u_live_url(channel):
    """Return the M3U channel's live stream URL verbatim."""
    return channel['stream_url']


def substitute_template(template, start, end, now, catchup_id=None):
    """Expand catch-up placeholder tokens in `template` against start/end/now."""
    def _repl(m):
        name = m.group('name')
        fmt = m.group('fmt')

        if name == 'catchup-id':
            return str(catchup_id) if catchup_id is not None else '{catchup-id}'

        if name == 'duration':
            diff = end - start
            if fmt is not None:
                n = int(fmt)
                divided = diff // n
                return str(divided if divided >= 0 else 0)
            return str(diff)

        if name == 'offset':
            diff = now - start
            if fmt is not None:
                n = int(fmt)
                return str(diff // n)
            return str(diff)

        if name in ('Y', 'm', 'd', 'H', 'M', 'S'):
            dt = datetime.utcfromtimestamp(start)
            return dt.strftime('%' + name)

        value_name = _DATE_VALUE_NAMES[name]
        value = {'start': start, 'end': end, 'now': now}[value_name]
        if fmt is not None:
            dt = datetime.utcfromtimestamp(value)
            strftime_fmt = re.sub(r'[YmdHMS]', lambda mm: '%' + mm.group(0), fmt)
            return dt.strftime(strftime_fmt)
        return str(value)

    return _TOKEN_RE.sub(_repl, template)


def xc_name_heuristic(name):
    """True iff `name` follows the "xeev" auto-catchup naming convention."""
    return bool(name) and (name.startswith('* ') or name.startswith('[+] '))


def _split_pipe(url):
    idx = url.find('|')
    if idx == -1:
        return url, ''
    return url[:idx], url[idx:]


def _finish(result, template_has_pipe, pipe):
    if not template_has_pipe and pipe:
        return result + pipe
    return result


def _append_mode(live_url, source, start, end, now, catchup_id, pipe):
    if source:
        appended = substitute_template(source, start, end, now, catchup_id)
        has_own_pipe = '|' in source
    else:
        appended = substitute_template('?utc={utc}&lutc={lutc}', start, end, now, catchup_id)
        has_own_pipe = False
    return _finish(live_url + appended, has_own_pipe, pipe)


# Xtream-Codes-style live URL: http://host/[live/]user/pass/id[.ext]
_XC_LIVE_RE = re.compile(
    r'^(?P<host>https?://[^/]+)/(?:live/)?(?P<user>[^/]+)/(?P<pass>[^/]+)'
    r'/(?P<id>[^./?]+)(?:\.(?P<ext>[a-zA-Z0-9]+))?$'
)


def _xc_template(live_url):
    m = _XC_LIVE_RE.match(live_url)
    if m is None:
        return None
    host, user, pw, stream_id = m.group('host'), m.group('user'), m.group('pass'), m.group('id')
    ext = m.group('ext') or 'ts'
    return '{0}/timeshift/{1}/{2}/{{duration:60}}/{{Y}}-{{m}}-{{d}}:{{H}}-{{M}}/{3}.{4}'.format(
        host, user, pw, stream_id, ext
    )


# Drops the last path segment (the stream filename) of a URL, keeping any
# query string, so a flussonic timeshift path segment can be inserted in
# its place: http://host/151/mpegts?token=x -> base=http://host/151,
# query=?token=x.
_LAST_SEGMENT_RE = re.compile(r'^(?P<base>https?://[^?]*?)/(?P<last>[^/?]+)(?P<query>\?.*)?$')


def _flussonic_template(live_url, mode):
    m = _LAST_SEGMENT_RE.match(live_url)
    if m is None:
        return None
    base = m.group('base')
    query = m.group('query') or ''
    if mode in ('flussonic-ts', 'fs'):
        suffix = '/timeshift_abs-{utc}.ts'
    else:
        suffix = '/timeshift_rel-{offset:1}.m3u8'
    return base + suffix + query


def _default_mode(live_url, source, start, end, now, catchup_id, pipe):
    if source:
        result = substitute_template(source, start, end, now, catchup_id)
        return _finish(result, '|' in source, pipe)
    return _append_mode(live_url, source, start, end, now, catchup_id, pipe)


def m3u_catchup_url(channel, start, end, now, catchup_id=None):
    """Build the catch-up URL for an M3U channel, dispatching on catchup_mode."""
    stream_url = channel.get('stream_url') or ''
    live_url, pipe = _split_pipe(stream_url)

    mode = (channel.get('catchup_mode') or 'default').strip().lower()
    if mode not in _KNOWN_MODES:
        mode = 'default'
    source = channel.get('catchup_source')

    if mode == 'append':
        return _append_mode(live_url, source, start, end, now, catchup_id, pipe)

    if mode in ('shift', 'timeshift'):
        sep = '&' if '?' in live_url else '?'
        template = live_url + sep + 'utc={utc}&lutc={lutc}'
        result = substitute_template(template, start, end, now, catchup_id)
        return _finish(result, False, pipe)

    if mode in ('flussonic', 'flussonic-hls', 'flussonic-ts', 'fs'):
        template = _flussonic_template(live_url, mode)
        if template is None:
            return _default_mode(live_url, source, start, end, now, catchup_id, pipe)
        result = substitute_template(template, start, end, now, catchup_id)
        return _finish(result, '|' in template, pipe)

    if mode == 'xc':
        template = _xc_template(live_url)
        if template is None:
            return _default_mode(live_url, source, start, end, now, catchup_id, pipe)
        result = substitute_template(template, start, end, now, catchup_id)
        return _finish(result, '|' in template, pipe)

    if mode == 'vod':
        if source:
            result = substitute_template(source, start, end, now, catchup_id)
            return _finish(result, '|' in source, pipe)
        result = substitute_template('{catchup-id}', start, end, now, catchup_id)
        return _finish(result, False, pipe)

    # 'default' (and anything unrecognized, normalized above)
    return _default_mode(live_url, source, start, end, now, catchup_id, pipe)


def correction_seconds(channel_correction_hours, provider_correction_hours):
    """Net correction in seconds from channel + provider decimal-hour offsets."""
    return int((float(channel_correction_hours or 0) + float(provider_correction_hours or 0)) * 3600)


def corrected_start(start_epoch, channel, provider):
    """Corrected epoch for catch-up offset math.

    The net correction (channel + provider, decimal hours) is subtracted
    from the offset before formatting: a positive correction shifts the
    resulting timestamp earlier, a negative correction shifts it later.
    """
    return start_epoch - correction_seconds(
        channel.get('catchup_correction_hours'),
        provider.get('catchup_correction_hours'),
    )


def xtream_local_start(start_epoch, tz_offset_seconds, provider):
    """Naive datetime representing provider-local wall-clock start time."""
    corrected = (
        start_epoch
        + (tz_offset_seconds or 0)
        - int(float(provider.get('catchup_correction_hours') or 0) * 3600)
    )
    return datetime.utcfromtimestamp(corrected)
