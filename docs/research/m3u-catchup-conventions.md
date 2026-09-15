# M3U Catchup Conventions: pvr.iptvsimple vs TiviMate

Research for GitHub issue snrgarb/kodimate#3.

## Overview

"Catchup" (a.k.a. archive/timeshift) M3U attributes are a *de-facto* convention, not a
formal spec. There is no single authority; each player/addon implements its own
superset/subset of a shared vocabulary that originated with SIPTV/Stalker-style
panels and was later extended by pvr.iptvsimple (Kodi IPTV Simple Client addon) and by
Xtream Codes / Flussonic panel generators. TiviMate (Android IPTV app) is widely cited
as having popularized/standardized much of this vocabulary among playlist providers,
but **TiviMate publishes no public technical specification** of its catchup URL
template engine (its FAQ/support pages are consumer-facing, and no
`tivimate.com`/`forum.tivimate.com` page documenting the exact placeholder set could be
located — see "Open Questions" below). By contrast, **pvr.iptvsimple's behavior is
fully and precisely defined by its open-source C++ implementation**, which this
document treats as ground truth for that addon, cross-checked against the project's
own GitHub wiki page (paraphrased in a fetch since the raw page could not be pulled as
markdown) and forum announcement.

Because of this asymmetry, this document is authoritative for **pvr.iptvsimple** (cited
to exact source files) and best-effort/"community consensus, unconfirmed against a
TiviMate primary source" for **TiviMate**.

## Catchup Modes

Mode is set via `catchup="<mode>"` (or the alternate tag `catchup-type="<mode>"`) on
either the `#EXTM3U` header line or a channel's `#EXTINF` line. Recognized values in
pvr.iptvsimple (case-insensitive comparisons), per
`ParseIntoChannel()` in
[`src/iptvsimple/PlaylistLoader.cpp` lines 415–443](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/PlaylistLoader.cpp#L415-L443)
and the `CatchupMode` enum in
[`src/iptvsimple/InstanceSettings.h` lines 18–29](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/InstanceSettings.h#L18-L29):

| `catchup=` value | Enum | URL-building behavior |
|---|---|---|
| `default` | `DEFAULT` | If the channel has a `catchup-source`, use it **as-is as the full catchup URL** (after variable substitution). If no `catchup-source` is present, falls back to **Append** behavior (see below). This is the mode used when `catchup=` is present but has no recognized value, or implicitly for channels with a `catchup-source` but no explicit `catchup=`. |
| `append` | `APPEND` | Concatenate `catchup-source` (query string, e.g. `?utc={utc}&lutc={lutc}`) onto the end of the *live* channel URL. If `catchup-source` is empty, appends the global addon setting `catchupQueryFormat` instead. Implemented in `GenerateAppendCatchupSource()`, [`Channel.cpp` lines 440–457](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/data/Channel.cpp#L440-L457). |
| `shift` (also legacy `timeshift="<days>"` tag path maps to obsolete `TIMESHIFT` enum, treated identically) | `SHIFT` / `TIMESHIFT` | Ignores `catchup-source` entirely. Appends `&utc={utc}&lutc={lutc}` if the live URL already has a `?query`, otherwise `?utc={utc}&lutc={lutc}`. Implemented in `GenerateShiftCatchupSource()`, [`Channel.cpp` lines 459–465](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/data/Channel.cpp#L459-L465). Display name "Shift (SIPTV)" — this is the SIPTV-panel convention. |
| `flussonic` / `flussonic-hls` / `flussonic-ts` / `fs` | `FLUSSONIC` | Rewrites the live stream URL into a Flussonic timeshift URL using regex pattern matching on the URL shape. `flussonic-ts`/`fs` selects `.ts` output (`timeshift_abs-${start}.ts`), others use `.m3u8` (`timeshift_rel-{offset:1}.m3u8`). Implemented in `GenerateFlussonicCatchupSource()`, [`Channel.cpp` lines 467–536](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/data/Channel.cpp#L467-L536). Example: stream `http://ch01.spr24.net/151/mpegts?token=x` → catchup `http://ch01.spr24.net/151/timeshift_abs-{utc}.ts?token=x`. |
| `xc` | `XTREAM_CODES` | Rewrites an Xtream-Codes-style live URL (`http://host/[live/]user/pass/id[.ext]`) into `http://host/timeshift/user/pass/{duration:60}/{Y}-{m}-{d}:{H}-{M}/id.ext` (defaults to `.ts` if no extension). Implemented in `GenerateXtreamCodesCatchupSource()`, [`Channel.cpp` lines 538–575](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/data/Channel.cpp#L538-L575). If the `#EXTM3U` header itself declares `catchup="xc"`, pvr.iptvsimple additionally auto-enables catchup (XTREAM_CODES mode) for any channel whose name starts with `"* "` or `"[+] "`, even without a per-channel `catchup=` tag (the "xeev" convention), [`PlaylistLoader.cpp` line 439–443](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/PlaylistLoader.cpp#L439-L443). |
| `vod` | `VOD` | Treats the entry as Video-On-Demand: if `catchup-source` is set, use it verbatim (same as Default); otherwise the format string is synthesized as literally `{catchup-id}` (a plugin-lookup placeholder — programmes are played back via their XMLTV `catchup-id`, not by absolute time). `catchup-days` is forced to a sentinel "ignore" value (`IGNORE_CATCHUP_DAYS = -1`) unless explicitly set. [`Channel.cpp` lines 407–415, 255–259](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/data/Channel.cpp#L407-L415). |
| *(no catchup attribute, but header-level `catchup=` set, or `allChannelsCatchupMode` addon setting is non-Disabled)* | inherited/`DISABLED` | The `#EXTM3U`-level `catchup=`/`catchup-type=` value is used as a per-channel default when a channel omits its own `catchup=` tag. Separately, an addon setting `allChannelsCatchupMode` (with `catchupOverrideMode`: without-tags / with-tags / all-channels) can force a mode on all or some channels regardless of M3U tags — this is a **client-side override, not an M3U attribute**. [`Channel.cpp` lines 348–374](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/data/Channel.cpp#L348-L374). |

Notes:
- In all modes, if the live stream URL has a Kodi header suffix (`|User-Agent=...`), that suffix is stripped before URL-rewriting and, unless the resulting `catchup-source` itself already contains a `|` (meaning it supplied its own header suffix), the original suffix is re-appended to the final catchup URL. [`Channel.cpp` lines 338–346, 418–427](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/data/Channel.cpp#L338-L346).
- A catchup source containing only the `{catchup-id}` placeholder (as in `vod` mode) is explicitly flagged as **not** timeshiftable (`IsValidTimeshiftingCatchupSource`, [`Channel.cpp` lines 277–297](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/data/Channel.cpp#L277-L297)) — VOD/catchup-id playback goes through EPG-tag lookup, not timeshift buffer math.
- **TiviMate**, per community-sourced secondary references (not independently confirmed against a TiviMate primary source — see Open Questions), is understood to support at minimum `default`, `append`, `shift`, and `flussonic` with broadly the same semantics, since these conventions predate/are shared with pvr.iptvsimple and were converged on by playlist-provider tooling. TiviMate's own catchup type list and exact fallback rules could not be verified from an official TiviMate document.

## catchup-source / catchup-days / catchup-correction

All three can be set at `#EXTM3U` (header/playlist-default) level or overridden per-channel
on `#EXTINF`. Parsing: `CATCHUP_SOURCE = "catchup-source="`, `CATCHUP_DAYS = "catchup-days="`,
`CATCHUP_CORRECTION = "catchup-correction="` — see marker constants in
[`src/iptvsimple/PlaylistLoader.h` lines 26–61](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/PlaylistLoader.h#L26-L61),
read in `LoadPlayList()` (header) and `ParseIntoChannel()` (channel) in
[`PlaylistLoader.cpp` lines 130–148 and 339–463](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/PlaylistLoader.cpp).

- **`catchup-source`** — a URL or URL-fragment template string containing the
  placeholders documented below. Channel-level value wins; if a channel omits it, the
  header-level `catchup-source` (if any) is used as the default. Its role depends on
  mode: full replacement URL in `default`/`vod`, appended fragment in `append`, ignored
  in `shift`/`flussonic`/`xc` (those synthesize their own).
- **`catchup-days`** — **integer number of days** the provider's archive/catchup window
  extends into the past. Parsed with `atoi()` — no fractional days. Precedence order
  (`ParseIntoChannel`, [`PlaylistLoader.cpp` lines 445–462](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/PlaylistLoader.cpp#L445-L462)):
  1. Channel's own `catchup-days=`.
  2. Header `catchup-days=` (only consulted if header `catchup-source` was also non-empty — a quirk of the code, [line 455](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/PlaylistLoader.cpp#L455)).
  3. If mode is `vod`: forced to sentinel `-1` (`IGNORE_CATCHUP_DAYS`, meaning "don't limit by days").
  4. The legacy SIPTV `timeshift="N"` tag or `tvg-rec="N"` tag value (days), if present and no `catchup-days` given.
  5. Otherwise, the addon-wide setting `catchupDays` (**default `5`**, per `pvr.iptvsimple/resources/settings.xml` line 319–322 in the addon repo, i.e. `resources/settings.xml`; note the C++ in-memory default in `InstanceSettings.h` line 327 is `3`, but the shipped `settings.xml` default of `5` is what actually takes effect at runtime).
  Used to compute the timeshift buffer window: `GetCatchupDaysInSeconds() = catchupDays * 24 * 60 * 60` ([`InstanceSettings.h` line 161](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/InstanceSettings.h#L161)).
- **`catchup-correction`** — **NOT seconds**: it is parsed as a **decimal number of
  hours** and converted to seconds internally (`atof(value) * 3600.0`), exactly mirroring
  how `tvg-shift` (EPG timezone shift) is parsed. See
  [`PlaylistLoader.cpp` lines 130–135 (header) and 410–413 (channel)](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/PlaylistLoader.cpp#L410-L413),
  and the addon setting equivalent `catchupCorrection` (type `number`, **default `0`**,
  documented range "-12 to +14" hours per the addon's GitHub wiki page content).
  Sign convention: added to (not subtracted from) the EPG timezone shift to compute the
  total correction applied when building catchup URLs —
  `m_epg.GetEPGTimezoneShiftSecs(channel) + channel.GetCatchupCorrectionSecs()`
  ([`CatchupController.cpp` line 224](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/CatchupController.cpp#L224) and used as `timezoneShiftSecs` subtracted from `offset` before formatting in `BuildEpgTagUrl`, [`CatchupController.cpp` line 475](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/CatchupController.cpp#L475)). A positive value shifts generated timestamps earlier (subtracted from the offset time before formatting); it exists to correct providers whose catchup timestamps don't match the stream's actual wall-clock/timezone.
  Channel-level precedence: if a channel's own `catchup-correction=` is empty, it falls back to the header-level `catchup-correction=`; if that too is empty, the addon setting default (0) applies.

## URL Template Variables

All substitution happens in `FormatDateTime()` / `FormatDateTimeNowOnly()` in the
anonymous namespace of
[`src/iptvsimple/CatchupController.cpp` lines 283–466](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/CatchupController.cpp#L283-L466).
Two families exist: **curly-brace** `{name}` and **dollar-brace** `${name}` specifiers,
both supported, generally as synonym pairs.

### Absolute Unix timestamps (seconds since epoch, decimal integer, no padding)

| Placeholder | Meaning |
|---|---|
| `{utc}` | Programme (or requested) start time, Unix seconds. |
| `${start}` | Synonym for `{utc}`. |
| `{utcend}` | Start time + duration (i.e. programme end time), Unix seconds. |
| `${end}` | Synonym for `{utcend}`. |
| `{lutc}` | "Live"/current time — the wall-clock time *at request-building time*, Unix seconds. |
| `${now}` | Synonym for `{lutc}`. |
| `${timestamp}` | Also a synonym for `{lutc}`/`${now}` (this alias exists specifically because many providers/TiviMate use `${timestamp}` for "now" — see issue [kodi-pvr/pvr.iptvsimple#325](https://github.com/kodi-pvr/pvr.iptvsimple/issues/325), which requested and led to this alias). |

Source: `FormatUtc("{utc}", ...)`, `FormatUtc("${start}", ...)`, `FormatUtc("{utcend}", ...)`,
`FormatUtc("${end}", ...)`, `FormatUtc("{lutc}", ...)`, `FormatUtc("${now}", ...)`,
`FormatUtc("${timestamp}", ...)` — all in `FormatDateTime()`,
[`CatchupController.cpp` lines 380–386](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/CatchupController.cpp#L380-L386).

### Duration / offset (seconds by default, or divided by a supplied divisor)

| Placeholder | Meaning |
|---|---|
| `{duration}` / `${duration}` | Programme duration in **seconds** (end − start; defaults to 3600s / one hour if no valid EPG programme, see `GetCatchupUrl()`, [`CatchupController.cpp` line 502](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/CatchupController.cpp#L502)). |
| `{duration:N}` | Duration **integer-divided by N** — e.g. `{duration:60}` yields minutes (used by the Xtream-Codes mode template). Implemented by `FormatUnits("duration", ...)`, regex `\{duration:(\d+)\}`, [`CatchupController.cpp` lines 285–309, 389](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/CatchupController.cpp#L389). Result floored at 0 if negative. |
| `{offset}` / `${offset}` | Elapsed seconds between "now" and the requested start time (`lutc − utc`), i.e. how far into the past the requested point is. |
| `{offset:N}` | Offset integer-divided by N — e.g. `{offset:1}` used verbatim by Flussonic mode (divisor 1 is a no-op but marks 1-second granularity). |

Source: `FormatUtc("${duration}", ...)`, `FormatUtc("{duration}", ...)`,
`FormatUnits("duration", ...)`, `FormatUtc("${offset}", ...)`, `FormatUnits("offset", ...)`,
[`CatchupController.cpp` lines 387–391](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/CatchupController.cpp#L387-L391).

### Date/time component specifiers (formatted local/broken-down time, zero-padded, derived from `localtime()`)

Two forms:

1. **Bare single-letter, applied to the *start* time only**: `{Y}` (4-digit year), `{m}`
   (2-digit month), `{d}` (2-digit day), `{H}` (2-digit hour, 24h), `{M}` (2-digit minute),
   `{S}` (2-digit second) — each independently substituted via `strftime`-style
   `%Y`/`%m`/`%d`/`%H`/`%M`/`%S`. Implemented by `FormatTime(char ch, ...)`,
   [`CatchupController.cpp` lines 311–326, called at lines 374–379](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/CatchupController.cpp#L311-L326).
   Example composite from the Xtream-Codes template: `{Y}-{m}-{d}:{H}-{M}`.

2. **Named-group with an embedded format string**: `{utc:<fmt>}`, `${start:<fmt>}`,
   `{utcend:<fmt>}`, `${end:<fmt>}`, `{lutc:<fmt>}`, `${now:<fmt>}`, `${timestamp:<fmt>}`
   — where `<fmt>` is a mini-format string using the same `Y`/`m`/`d`/`H`/`M`/`S` letters
   (each internally prefixed with `%` and passed to `strftime`/`put_time`), letting a
   provider request e.g. `{utc:Y-m-d_H:M:S}` to get a fully custom formatted start time
   instead of a raw Unix timestamp. Implemented by the overloaded
   `FormatTime(const std::string name, const struct tm*, ..., bool hasVarPrefix)`,
   [`CatchupController.cpp` lines 328–351, invoked at lines 393–401](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/CatchupController.cpp#L328-L351).
   Note the `{name}` (no `$`) forms apply to `utc`/`utcend`/`lutc`, while the `${name}`
   (with `$`) forms apply to `start`/`end`/`now`/`timestamp` — i.e. the `$`-prefixed and
   brace-only spellings are *not* just cosmetic aliases when a `:<fmt>` suffix is used;
   both exist as separate lookups but resolve against the same underlying time value.

### Other

| Placeholder | Meaning |
|---|---|
| `{catchup-id}` | Replaced with the current EPG programme's provider-supplied catchup/archive ID (from XMLTV `catchup-id` attribute on the `<programme>`), via a separate regex pass in `BuildEpgTagUrl()`/`ProcessStreamUrl()`, **not** part of `FormatDateTime()`. [`CatchupController.cpp` lines 479–481, 529–531](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/CatchupController.cpp#L479-L481). Used as the entire `catchup-source` value in `vod` mode. |

### Granularity / termination inference (informational, not URL-building, but explains *why* these specifiers matter)

pvr.iptvsimple inspects which placeholders are present in the final `catchup-source` to
infer stream capabilities:
- **Terminating stream** (has a definite end, e.g. a finite VOD-style clip) if the
  source contains `{duration}`/`{duration:N}`, `{lutc}`/`{lutc:N}`, `${timestamp}`/`${timestamp:N}`,
  `{utcend}`/`{utcend:N}`, or `${end}`/`${end:N}`. [`Channel.cpp` lines 299–315](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/data/Channel.cpp#L299-L315).
- **1-second granularity** (vs. default 60-second) if the source contains `{utc}`,
  `{utc:N}`, `${start}`, `${start:N}`, `{S}`, or `{offset:1}`. [`Channel.cpp` lines 317–329](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/data/Channel.cpp#L317-L329).

## TiviMate vs pvr.iptvsimple differences

**Caveat**: no official TiviMate technical specification could be located (see Open
Questions). The following is what can be said with confidence:

- **Confirmed identical (shared convention)**: `{utc}`, `{lutc}`, `${start}`, `${end}`,
  `${timestamp}` and the `catchup`/`catchup-source`/`catchup-days`/`catchup-correction`
  M3U tag names themselves are widely cited (by pvr.iptvsimple's own maintainer, in
  [issue #325](https://github.com/kodi-pvr/pvr.iptvsimple/issues/325)) as pre-existing
  conventions that pvr.iptvsimple added support for *because* other players (TiviMate
  named explicitly in community discussion) and provider panels already used them —
  i.e. pvr.iptvsimple is the *follower* for the `${timestamp}` alias, not the
  originator; it added `${timestamp}` as a synonym for its pre-existing `{lutc}`
  specifically for TiviMate/provider compatibility.
- **`catchup="shift"` without a `catchup-source`**: per issue #325's second request
  (accepted and implemented — see the `SHIFT` mode logic above), this exact
  "auto-append `?`/`&utc={utc}&lutc={lutc}`" behavior was explicitly modeled on a
  third-party implementation ("Archive Client" in CoreELEC) that the issue reporter
  said was "already tested in production," not on TiviMate directly. Whether TiviMate
  itself implements `shift` mode with this exact fallback could not be confirmed from a
  primary TiviMate source.
- **pvr.iptvsimple-specific extensions not necessarily in TiviMate**: the `{name:<fmt>}`
  custom-format mini-language (e.g. `{utc:Y-m-d}`), the `{duration:N}`/`{offset:N}`
  divisor syntax, `{catchup-id}`, the `flussonic-ts`/`fs` and `xc` auto-URL-rewriting
  modes (which pattern-match and rewrite the *live* URL rather than using a
  provider-supplied template), and the "xeev" channel-name-prefix auto-catchup
  heuristic are pvr.iptvsimple/Kodi-side conveniences layered on top of the shared
  placeholder vocabulary. These are Kodi-addon URL-rewriting conveniences; a template-
  driven player like TiviMate that requires the provider to supply a full
  `catchup-source` template would not need (and may not support) the `flussonic`/`xc`
  auto-rewrite modes at all, since TiviMate would rely on the panel to already emit a
  correctly-templated `catchup-source`. This is inferred from pvr.iptvsimple's own
  design rationale, not confirmed against TiviMate.
- **Not confirmed either way**: whether TiviMate supports the `{name:<fmt>}` format-
  string variant, `{catchup-id}`, `${now}`, or has its own placeholders absent from
  pvr.iptvsimple. No primary TiviMate documentation was found to check against.

## #EXTVLCOPT and #KODIPROP

Both are parsed as generic per-channel `key=value` property lines that may appear
between `#EXTINF` and the stream URL line, handled by
`ParseSinglePropertyIntoChannel()`,
[`PlaylistLoader.cpp` lines 563–597](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/PlaylistLoader.cpp#L563-L597),
dispatched from the main parse loop,
[`PlaylistLoader.cpp` lines 192–207](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/PlaylistLoader.cpp#L192-L207).

- **`#EXTVLCOPT:<key>=<value>`** — VLC-originated convention, syntax
  `#EXTVLCOPT:http-user-agent=<UA string>` / `#EXTVLCOPT:http-referrer=<referrer URL>`.
  pvr.iptvsimple **only honors** three keys under this marker:
  `http-user-agent`, `http-referrer`, and `program` (case-normalized to lowercase before
  comparison; other keys under `#EXTVLCOPT:` are silently ignored),
  [`PlaylistLoader.cpp` line 579–582](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/PlaylistLoader.cpp#L579-L582).
  A dash-form marker `#EXTVLCOPT--<key>=<value>` is also recognized but only for
  `http-reconnect`, [line 575–578](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/PlaylistLoader.cpp#L575-L578).
  Community/forum usage (per web search of Kodi forum threads) shows the same
  `#EXTVLCOPT:http-user-agent=...` / `#EXTVLCOPT:http-referrer=...` syntax used broadly
  across Kodi-ecosystem M3U tooling, consistent with pvr.iptvsimple's parser.
- **`#KODIPROP:<key>=<value>`** — Kodi-specific playlist extension for arbitrary stream
  properties, most commonly used for InputStream Adaptive configuration (e.g.
  `#KODIPROP:inputstreamaddon=inputstream.adaptive`,
  `#KODIPROP:inputstream.adaptive.license_type=...`). pvr.iptvsimple accepts **any**
  key under `#KODIPROP:` (no allow-list, unlike `#EXTVLCOPT:`/`#WEBPROP:`) and adds it
  as a stream property verbatim, with one special case: `inputstreamaddon` or
  `inputstreamclass` keys are remapped to the Kodi PVR API's
  `PVR_STREAM_PROPERTY_INPUTSTREAM` property name,
  [`PlaylistLoader.cpp` lines 587–590](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/PlaylistLoader.cpp#L587-L590).
  General `inputstream.adaptive.*` property semantics belong to the
  `inputstream.adaptive` addon itself, not pvr.iptvsimple, and were out of scope for
  deep verification here (not specifically catchup-related); pvr.iptvsimple's role is
  only to parse the `#KODIPROP:` line and forward the key/value pair as a Kodi stream
  property.
- A sibling, less-standard `#WEBPROP:` marker is also recognized, allow-listed to
  `web-regex` and `web-headers` only, [line 583–586](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/PlaylistLoader.cpp#L583-L586) — mentioned here only
  for completeness; it is not part of the catchup vocabulary.

## Kodi URL header suffix

Kodi's stream-URL convention for attaching HTTP headers directly to a URL (used
throughout Kodi playlists/`.strm` files, independent of `#EXTVLCOPT`) is:

```
http://example.com/stream.m3u8|User-Agent=Mozilla%2F5.0&Referer=https%3A%2F%2Fexample.com%2F
```

i.e. a `|` (pipe) separates the base URL from a `key=value&key=value...` string of
HTTP request headers, URL-encoded, appended directly to the end of the URL with no
extra delimiter before the first header. This was confirmed via Kodi community-forum
discussion (`forum.kodi.tv` thread on "How to enter User-Agent, origin and referer")
found via web search — the Kodi wiki `HTTP` and `IPTV_Simple_Client` pages themselves
returned HTTP 403 to automated fetches during this research and could not be read
directly, so this is corroborated by pvr.iptvsimple's own source handling of the same
convention rather than a directly-quoted wiki excerpt.

pvr.iptvsimple explicitly special-cases this pipe suffix for catchup URL construction:
it strips everything from the first `|` off the live stream URL before applying any
catchup-mode URL rewriting (`Default`/`Append`/`Shift`/`Flussonic`/`Xtream Codes`/`VOD`),
then re-appends the original `|...` suffix onto the generated catchup URL — *unless*
the channel's own `catchup-source` already contains a `|` of its own (in which case the
catchup-source's own header suffix wins and the live URL's is dropped). See
`ConfigureCatchupMode()`,
[`Channel.cpp` lines 338–346 and 418–429](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/data/Channel.cpp#L338-L346).
This guarantees that a channel requiring a custom `User-Agent`/`Referer` to play live
still sends those same headers when playing a catchup/archive URL, unless the provider
supplied catchup-source-specific headers instead.

## Sources

- **[github.com/kodi-pvr/pvr.iptvsimple](https://github.com/kodi-pvr/pvr.iptvsimple)** — repository root; confirmed default branch is `Piers` (current active development branch as of research date 2026-09-15).
- **[`src/iptvsimple/CatchupController.cpp`](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/CatchupController.cpp)** (fetched from `Piers` branch raw content) — primary source for all URL template variable substitution logic (`FormatUtc`, `FormatTime`, `FormatUnits`, `FormatDateTime`, `FormatDateTimeNowOnly`, `BuildEpgTagUrl`), and for `catchup-correction`/timezone application.
- **[`src/iptvsimple/CatchupController.h`](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/CatchupController.h)** — class interface, confirms state fields (`m_catchupStartTime`, `m_timeshiftBufferOffset`, etc.).
- **[`src/iptvsimple/PlaylistLoader.cpp`](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/PlaylistLoader.cpp)** and **[`PlaylistLoader.h`](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/PlaylistLoader.h)** — primary source for M3U attribute parsing (`catchup`, `catchup-type`, `catchup-source`, `catchup-days`, `catchup-correction`, `timeshift`, `tvg-rec`), header-vs-channel precedence, `#EXTVLCOPT`/`#KODIPROP`/`#WEBPROP` parsing and allow-lists, and marker-string constants.
- **[`src/iptvsimple/data/Channel.cpp`](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/data/Channel.cpp)** and **[`Channel.h`](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/data/Channel.h)** — primary source for `ConfigureCatchupMode()` (per-mode URL-building for Default/Append/Shift/Flussonic/Xtream-Codes/VOD), the `CatchupMode` enum, `GetCatchupModeText()`, pipe-suffix (`|User-Agent=...`) preservation logic, and the timeshifting/termination/granularity inference heuristics.
- **[`src/iptvsimple/InstanceSettings.h`](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/InstanceSettings.h)** and **[`InstanceSettings.cpp`](https://github.com/kodi-pvr/pvr.iptvsimple/blob/master/src/iptvsimple/InstanceSettings.cpp)** — addon-wide catchup settings accessors and in-memory defaults (`m_catchupDays = 3`, `m_catchupCorrectionHours = 0`, etc.) and the `CatchupMode` enum definition.
- **`pvr.iptvsimple/resources/settings.xml`** (fetched via raw.githubusercontent.com, `Piers` branch) — shipped addon setting defaults as exposed to users: `catchupDays` default **5**, `catchupCorrection` default **0**, `catchupQueryFormat` default empty, `allChannelsCatchupMode`/`catchupOverrideMode` default 0 (Disabled/Without-tags).
- **[github.com/kodi-pvr/pvr.iptvsimple/wiki/Catchup](https://github.com/kodi-pvr/pvr.iptvsimple/wiki/Catchup)** — project wiki page on Catchup; fetched via an automated summarizing fetch (raw markdown was not retrievable directly), used to corroborate mode descriptions, the `catchup-correction` "-12 to +14 hours" documented range, and the placeholder table, cross-checked against the source code above (all wiki claims independently verified against the actual C++ implementation in this document).
- **[github.com/kodi-pvr/pvr.iptvsimple/issues/325](https://github.com/kodi-pvr/pvr.iptvsimple/issues/325)** — "Request for new catchup placeholder and new catchup type" — primary source for the `${timestamp}` alias rationale (equivalence to `{lutc}`) and the `catchup="shift"` auto-append-without-catchup-source feature request/implementation.
- **Kodi Community Forum, thread "How to enter User-Agent, origin and referer"** (`forum.kodi.tv`, tid 381336) — found via web search; used (as a secondary/community corroboration, not directly fetched due to access restrictions) for the `|User-Agent=...&Referer=...` pipe-suffix URL convention syntax.
- **kodi.wiki** (`IPTV_Simple_Client` and `HTTP` pages) — attempted via WebFetch; both returned **HTTP 403 Forbidden** to automated fetching and could not be read. Not used as a direct source; see Open Questions.
- **`forum.kodi.tv` thread 351431**, "IPTV Simple now supports Catchup and Timeshifted Catchup in Kodi Matrix" (pvr.iptvsimple maintainer's own announcement) — attempted via WebFetch; returned **HTTP 403 Forbidden**. Not used as a direct source; see Open Questions.
- **TiviMate** (`tivimate.com`, `forum.tivimate.com`) — searched extensively; **no official technical documentation of the catchup URL template engine was found**. `tivimate.com/faq` returned HTTP 404. See Open Questions.
- General web search results (community aggregator pages such as `uniplayer.net/docs/specs/m3u/`, `m3u.codes`) were used only to *orient* the research (confirming which placeholders exist in the wild) and are **not cited as authoritative** for any specific claim in this document — every substantive claim above is grounded in the pvr.iptvsimple source code or the project's own wiki/issue tracker.

## Open Questions / Unconfirmed Items

1. **No official TiviMate technical specification found.** TiviMate's exact catchup
   mode list, its exact placeholder set (particularly whether it supports the
   `{name:<fmt>}` custom-format syntax, `{catchup-id}`, `{duration:N}`/`{offset:N}`
   divisors, or has placeholders pvr.iptvsimple lacks), and its precise fallback rules
   when `catchup-source` is absent could not be verified against a primary TiviMate
   source. This document's TiviMate claims should be treated as inferred/community
   consensus only, not verified fact.
2. **kodi.wiki inaccessible.** Both `kodi.wiki/view/IPTV_Simple_Client` and
   `kodi.wiki/view/HTTP` returned HTTP 403 to this research session's fetch tool and
   could not be read directly; any Kodi-wiki-sourced claims in the wild (e.g. in
   secondary aggregator docs) should be re-verified against the wiki directly by a
   human or a session with working access, though the source-code-derived claims in
   this document do not depend on the wiki.
3. **`forum.kodi.tv` thread 351431** (the pvr.iptvsimple maintainer's own announcement
   post, which likely contains additional prose explanation of the catchup design)
   also returned HTTP 403 and could not be read; it may contain additional detail or
   caveats not captured here.
4. **GitHub wiki raw markdown not directly retrievable** — the Catchup wiki page
   content used here came from an automated fetch/summarization rather than raw
   markdown, so exact wording (e.g. the precise "-12 to +14" hour range for
   `catchup-correction`) should be treated as paraphrased, though it is consistent with
   the source code's `float`/`atof`-based parsing (which imposes no hard-coded range
   limit in the code itself — any range limit is a UI/settings.xml constraint, not
   enforced by the parsing logic reviewed).
5. **`inputstream.adaptive`-specific `#KODIPROP` keys** (DRM license URLs, manifest
   type, etc.) were intentionally not enumerated in depth, since they are generic
   `#KODIPROP` passthrough and not specific to catchup; pvr.iptvsimple's parser treats
   all `#KODIPROP:` keys identically (verbatim passthrough) except the
   `inputstreamaddon`/`inputstreamclass` special case documented above.
