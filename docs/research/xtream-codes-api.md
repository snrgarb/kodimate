# Xtream Codes API surface for Kodimate

Research for [issue #2](https://github.com/snrgarb/kodimate/issues/2) (part of map issue #1).
Question: what a client needs from `player_api.php` to list live categories/streams
(numbering, logos), fetch EPG (`xmltv.php`, `get_short_epg`, `get_simple_data_table`),
build live stream URLs (`.ts` vs `.m3u8`), and build catch-up URLs
(`timeshift.php` / `streaming/timeshift.php`) from `tv_archive` /
`tv_archive_duration` — plus auth/expiry, rate-limit etiquette, and provider quirks.

There is no single official Xtream Codes spec (the original Xtream Codes company's
docs are largely gone); the API is a de-facto standard reverse-engineered and
reimplemented by many panels (XUI.one, Xtream-UI, Xtream Codes forks) and consumed
identically by third-party clients. Findings below are cross-checked against:

- **kodi-pvr/pvr.iptvsimple** source (`Omega` branch), the closest thing to an
  "official Kodi ecosystem" implementation of Xtream-style catch-up URL synthesis.
- **worldofiptvcom/xtream-codes-api-documentation** — community-maintained but the
  most complete field-level writeup available.
- **chazlarson/py-xtream-codes** (`xtream.py`) — a working Python client, useful to
  confirm exact endpoint URL shapes.
- Community write-ups (UniPlayer M3U/catch-up spec, GridStreamr catch-up guide) used
  only to corroborate, not as primary authority.

## 1. Authentication and session info

Auth is implicit: hitting `player_api.php` with credentials and no `action` param
(or `action=get_account_info`, depending on panel) returns the account/session
payload. No separate login/token step; every subsequent call repeats
`username`/`password` as query params.

```
GET {host}/player_api.php?username={user}&password={pass}
```

Response shape (`user_info` + `server_info`):

```jsonc
{
  "user_info": {
    "username": "...",
    "password": "...",
    "message": "...",
    "auth": 1,                 // 1 = authenticated, 0 = failed
    "status": "Active",        // account state string
    "exp_date": "1735689600",  // unix timestamp, string; absent/null = no expiry
    "is_trial": "0",
    "active_cons": "0",        // current concurrent connections
    "created_at": "1700000000",
    "max_connections": "1",    // concurrent stream ceiling
    "allowed_output_formats": ["m3u8", "ts"]
  },
  "server_info": {
    "url": "example.com",
    "port": "80",
    "https_port": "443",
    "server_protocol": "http",
    "rtmp_port": "25462",
    "timezone": "Europe/London",
    "timestamp_now": 1737000000,
    "time_now": "2026-01-16 12:00:00"
  }
}
```

Client-relevant fields: `auth` (gate everything else on this being `1`),
`status` (some panels return `"Banned"`/`"Expired"`/`"Disabled"` strings instead of
just flipping `auth`), `exp_date` (surface to the user, poll/refresh before it
lapses), `max_connections`/`active_cons` (respect this — do not open a second
stream/preview while one is already playing on the same account), and
`server_protocol`/`port`/`https_port` (build stream URLs from these rather than
assuming the panel base URL's own scheme/port, since providers commonly serve the
API over one port and streams over another).

Numeric-looking fields (`auth`, `exp_date`, `is_trial`, `active_cons`,
`max_connections`) are inconsistently typed as string vs int across panel forks —
parse defensively (accept either).

## 2. Live categories and streams (numbering + logos)

```
GET {host}/player_api.php?username={u}&password={p}&action=get_live_categories
GET {host}/player_api.php?username={u}&password={p}&action=get_live_streams
GET {host}/player_api.php?username={u}&password={p}&action=get_live_streams&category_id={id}
```

`get_live_categories` → array of:

```jsonc
{ "category_id": "5", "category_name": "News", "parent_id": 0 }
```

`get_live_streams` → array of, per channel:

```jsonc
{
  "num": 101,                    // provider-assigned display/zap number
  "name": "BBC News HD",
  "stream_type": "live",
  "stream_id": 12345,
  "stream_icon": "http://.../logos/bbcnews.png",  // channel logo URL
  "epg_channel_id": "bbcnews.uk", // ties to xmltv.php <channel id=…> and to
                                   // get_short_epg/get_simple_data_table lookups
  "added": "1700000000",
  "category_id": "5",
  "custom_sid": "",
  "tv_archive": 1,                // 1 = catch-up available for this channel
  "direct_source": "",            // usually empty; some panels put an alt URL here
  "tv_archive_duration": 7        // **days** of catch-up retained (not hours/minutes)
}
```

For the ticket's "numbering" requirement: `num` is the provider's own channel
number and is the right default sort/zap key; it is per-provider and not globally
stable, matching the map's decision to keep same channel from two providers
separate and to support per-provider offsets. `stream_icon` is the logo; treat it
as an ordinary HTTP(S) image URL (cache/texture it, no auth needed beyond
provider being publicly reachable — some providers hotlink-protect it, see quirks
below).

`epg_channel_id` is the join key to `xmltv.php`/`get_short_epg`/
`get_simple_data_table` results — matches this repo's map decision to key EPG by
`tvg-id`-equivalent then fall back to normalised name.

## 3. EPG

### 3a. Bulk XMLTV

```
GET {host}/xmltv.php?username={u}&password={p}
```

Returns a standard XMLTV document (gzip sometimes applied server-side; honor
`Content-Encoding`). `<channel id="...">` matches `epg_channel_id` from
`get_live_streams`. This is the bulk/offline path — pull once per refresh cycle
and store into SQLite per the map's design, not per-channel.

### 3b. Short EPG (now/next, per channel)

```
GET {host}/player_api.php?username={u}&password={p}&action=get_short_epg&stream_id={id}
GET {host}/player_api.php?username={u}&password={p}&action=get_short_epg&stream_id={id}&limit={n}
```

```jsonc
{
  "epg_listings": [
    {
      "id": "123456",
      "epg_id": "789",
      "title": "QmVlYm94",          // base64-encoded
      "lang": "en",
      "start": "2026-01-16 18:00:00", // local server time, not UTC
      "end": "2026-01-16 19:00:00",
      "description": "U29tZSBzaG93",  // base64-encoded
      "channel_id": "bbcnews.uk",
      "start_timestamp": "1737050400",
      "stop_timestamp": "1737054000",
      "now_playing": 1,
      "has_archive": 1
    }
  ]
}
```

`title`/`description` are base64 — decode client-side. `limit` bounds how many
upcoming entries return (defaults vary by panel, typically 4). Useful for
OSD/now-next widgets without pulling the whole XMLTV doc.

### 3c. get_simple_data_table

```
GET {host}/player_api.php?username={u}&password={p}&action=get_simple_data_table&stream_id={id}
```

Same `epg_listings` shape as `get_short_epg` but returns the full day's schedule
for that channel (not just the next few entries) — this is the source for a
per-channel guide column view without waiting on the full XMLTV pull.

## 4. Live stream URLs

```
{host}/live/{username}/{password}/{stream_id}.ts
{host}/live/{username}/{password}/{stream_id}.m3u8
```

`.ts` is raw MPEG-TS (what most panels default to and what `pvr.iptvsimple`
treats as the fallback when it can't detect `.m3u8`); `.m3u8` requests an HLS
variant playlist from the panel. Matches the map's settled decision: `.ts`
default, `.m3u8` fallback, per-provider override. `allowed_output_formats` in
`user_info` is the authoritative list of what the account is permitted to
request — don't assume `.m3u8` is available just because the panel serves it for
some channels.

Some panels also accept a bare `{host}/{username}/{password}/{stream_id}` form
(implicit `.ts`); treat `.ts`/`.m3u8` as the two to actually support.

## 5. Catch-up / timeshift URLs

Two URL forms are in circulation and both are considered "the Xtream Codes
catch-up API":

**Path form** (confirmed verbatim in `pvr.iptvsimple`'s Xtream Codes catch-up
generator, `src/iptvsimple/data/Channel.cpp`, `Omega` branch — it builds this
exact template when a channel's `catchup="xc"` is set in the M3U):

```
{host}/timeshift/{username}/{password}/{duration}/{Y}-{m}-{d}:{H}-{M}/{stream_id}{ext}
```

i.e. concretely:

```
http://host:port/timeshift/user/pass/60/2026-01-16:18-00/12345.ts
```

- `{duration}` is minutes, computed from the programme's duration in seconds
  divided by 60 (`pvr.iptvsimple` literally uses the token `{duration:60}` — its
  generic placeholder syntax for "seconds value / 60").
- Start time `{Y}-{m}-{d}:{H}-{M}` is **local/server wall-clock time**, not UTC —
  this is the single biggest source of off-by-timezone catch-up bugs, since XMLTV
  programme times are typically UTC or carry their own offset.
- `{ext}` mirrors whatever extension the channel's live URL used (`.ts` default,
  `.m3u8` if the live entry was `.m3u8`) — `pvr.iptvsimple` explicitly falls back
  to `.ts` when it can't detect `.m3u8` from the source URL.

**Query-string form** (same semantics, different panel/wrapper):

```
{host}/streaming/timeshift.php?username={u}&password={p}&stream={stream_id}&start={YYYY-MM-DD:HH-MM}&duration={minutes}
```

Both forms are produced by different Xtream panel forks/versions for the same
underlying feature; a client should treat them as interchangeable given the same
inputs and default to the path form (`/timeshift/...`) since that's what the
primary Kodi-ecosystem source actually implements, with the query-string form as
a documented fallback if a provider only serves that shape.

Eligibility and window come from `get_live_streams`:
- `tv_archive == 1` → channel has catch-up.
- `tv_archive_duration` → **days** of catch-up retained (community docs consistently
  describe this in days, e.g. `7` = 7-day catch-up window), used to bound how far
  back a catch-up/EPG browser lets the user seek — matches this repo's map
  decision to key catch-up off Xtream `tv_archive`/`tv_archive_duration` alongside
  the M3U `catchup`/`catchup-days` template family.

## 6. Rate-limit etiquette and connection limits

No formally documented client-side rate limit exists in the primary sources
above; the numbers below come from operator-side nginx configs referenced in
community docs and should be treated as reasonable defaults to self-impose, not
a guaranteed provider contract:

- Treat `max_connections`/`active_cons` from `user_info` as authoritative: never
  open a second live/catch-up stream (including a "preview" or logo-probe
  request against `/live/...`) while one is already open on the same account if
  `max_connections` is `1`, which is common for single-connection IPTV plans.
  Exceeding it typically returns an explicit `"User already has an active
  connection"` style error or the panel force-kills the existing stream.
  Kodimate's XC client should serialize its own connection use accordingly (stop
  the previous player before starting a new channel — Kodi's `xbmc.Player`
  handoff already does this naturally).
- Repeated failed-auth attempts get IP-blocked by many panels (a
  `blocked_ips`-style lockout referenced in community panel docs) — retry auth
  failures with backoff, not tight loops, and don't hammer `player_api.php`
  speculatively (e.g. don't poll `get_live_streams` on a timer; refresh on the
  service interval / manual refresh per the map's settled design).
- Community-documented nginx defaults for panel API endpoints cite a ballpark of
  ~20 req/s per IP; Kodimate's own refresh cadence (12h + startup + manual, per
  the map) is far under any such ceiling, so no explicit client-side throttling
  logic is needed beyond "don't poll in a loop."
- `get_short_epg`/`get_simple_data_table` are per-channel calls — don't fan these
  out for every channel on every guide open; prefer the bulk `xmltv.php` pull for
  populating the full guide grid and reserve `get_short_epg` for on-demand
  now/next lookups (e.g. OSD), matching the map's XMLTV-to-SQLite design.

## 7. Known provider quirks

- **Field typing is inconsistent across panel forks.** `auth`, `tv_archive`,
  `is_trial`, `active_cons`, `max_connections`, `category_id` etc. show up as
  either JSON strings or JSON numbers depending on the panel software/version.
  Parse leniently (coerce, don't assume a JSON type).
- **`exp_date` can be `null`, `"0"`, or absent** for unlimited/reseller accounts —
  don't treat "unparseable" as "expired"; treat missing/zero as "no expiry".
- **Timezone mismatch between EPG and catch-up.** XMLTV/`get_short_epg` timestamps
  are commonly UTC (or carry an explicit offset); the Xtream catch-up URL's
  `{Y}-{m}-{d}:{H}-{M}` is local server wall-clock time. Getting this wrong is the
  most common real-world catch-up bug — community docs converge on needing an
  explicit timezone-correction step (equivalent to M3U's `catchup-correction`)
  when deriving catch-up start times from EPG programme start times.
  `server_info.timezone`/`timestamp_now` from the auth response is the reference
  point to reconcile against.
- **`stream_icon` / logo URLs are sometimes hotlink- or referer-protected**, or
  point to a different host/port than the panel API — don't assume the same auth
  context applies; treat logo fetch failures as expected/non-fatal and fall back
  to a placeholder, consistent with the map's "missing-logo fallback" open
  question.
- **`.m3u8` availability is not universal** even when a provider nominally
  supports HLS — `allowed_output_formats` is the account-level signal, but some
  channels within an otherwise-HLS-capable account are TS-only. Per-provider (and
  ideally per-channel) override, as already decided in the map, is the correct
  mitigation rather than a single global toggle.
- **`num` (channel number) is not guaranteed unique or contiguous**, and some
  panels renumber on every category filter (i.e. `num` may be category-relative,
  not global) — confirms the map's decision to not rely on it as a global key and
  to support user renumbering/provider order as fallback.
- **Two catch-up URL shapes in the wild** (`/timeshift/...` path form vs
  `/streaming/timeshift.php?...` query form) with no way to discover which one a
  given panel wants from `player_api.php` metadata alone — a client generally has
  to try the path form (matching `pvr.iptvsimple`'s implementation) and treat the
  query-string form as a manual per-provider override if catch-up 404s, similar
  to how M3U catch-up already needs a `catchup-type` override per provider.
- **Some providers require a `User-Agent` header** (blocking default/empty UAs) on
  both API and stream requests — send a real UA string consistently across
  `player_api.php`, `xmltv.php`, and stream/timeshift URLs.

## Sources

- kodi-pvr/pvr.iptvsimple, `Omega` branch:
  `src/iptvsimple/PlaylistLoader.cpp` (catchup mode `"xc"` detection →
  `CatchupMode::XTREAM_CODES`),
  `src/iptvsimple/data/Channel.cpp` (Xtream Codes catchup-source template
  generation: `{host}/timeshift/{user}/{pass}/{duration:60}/{Y}-{m}-{d}:{H}-{M}/{id}{ext}`,
  `.ts`/`.m3u8` extension detection),
  `src/iptvsimple/CatchupController.cpp` (generic placeholder substitution:
  `{utc}`, `{Y}{m}{d}{H}{M}{S}`, `{duration}`, `{offset}`, `{catchup-id}`),
  `README.md` (`catchup="xc"` M3U convention, placeholder token reference).
  https://github.com/kodi-pvr/pvr.iptvsimple
- worldofiptvcom/xtream-codes-api-documentation (`XTREAM_CODES_API_DOCUMENTATION.md`) —
  community field-level reference for `user_info`/`server_info`, `get_live_streams`,
  `get_short_epg`, `xmltv.php`, stream/timeshift URL shapes, and nginx-level rate
  limiting notes. https://github.com/worldofiptvcom/xtream-codes-api-documentation
- chazlarson/py-xtream-codes, `xtream.py` — confirms exact `player_api.php`
  endpoint URL construction for auth, categories, streams, EPG actions, and
  `xmltv.php`. https://github.com/chazlarson/py-xtream-codes
- UniPlayer M3U/catch-up spec (community, corroborating only) —
  catchup-type values (`default`/`append`/`shift`/`flussonic`/`xc`) and
  placeholder token table. https://uniplayer.net/docs/specs/m3u/
- GridStreamr catch-up/timeshift guide (community, corroborating only, low
  technical detail). https://www.gridstreamr.com/guides/iptv-catchup-timeshift
