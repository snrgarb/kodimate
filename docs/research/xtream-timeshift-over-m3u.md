# Xtream timeshift over M3U: catchup="default" with an XC-shaped live URL

Research question: for an aggregator (e.g. m3u4u) M3U line with `catchup="default"`,
no `catchup-source`, and a live URL shaped like an Xtream-Codes stream URL, should
Kodimate auto-detect and prefer the XC `/timeshift/...` path over the
pvr.iptvsimple `?utc=&lutc=` append convention, and how should it get the timezone
needed to build a correct timeshift stamp. Builds on
`docs/research/m3u-catchup-conventions.md` (pvr.iptvsimple catchup modes) and
`docs/research/xtream-codes-api.md` (Xtream Codes API surface) — not repeated here.

## Summary

1. pvr.iptvsimple never auto-upgrades `catchup="default"` to `xc` by sniffing the
   live URL's shape; `xc` only activates via an explicit `catchup="xc"` tag, the
   narrower "xeev" name-prefix heuristic, or a manual "All channels catchup mode"
   override setting.
2. `catchup="default"` with empty `catchup-source` falls back to Append mode,
   which is a no-op (catchup disabled) with stock settings — it does **not**
   default to `?utc={utc}&lutc={lutc}`; that template is hardcoded only in
   `SHIFT` mode.
3. pvr.iptvsimple's `{Y}-{m}-{d}:{H}-{M}` stamp uses `localtime_r`/`localtime_s` —
   the Kodi device's OS timezone, not UTC and not the provider's server
   timezone; `catchup-correction` is the only (non-DST-aware) reconciliation
   lever.
4. Its `xc` URL-rewrite regex cannot match a live URL ending in `.ts` (only
   extensionless or `.m3u8`) — the exact shape in this research question's
   example — so pvr.iptvsimple's own `xc` mode could not handle this provider.
5. Xtream Codes' `timeshift.php`/`/timeshift/` semantics are de-facto, with no
   authoritative spec; no primary source states `start` is local-vs-UTC or that
   it matches `server_info.timezone` — that link is convention/inference only.
6. Kodi 21 "Omega" bundles Python 3.11.x (stdlib `zoneinfo`), but Kodi's own
   official add-on repo ships `script.module.tzdata` for Omega/Piers, implying
   `zoneinfo` cannot be trusted to resolve IANA names unassisted on all
   platforms.

## 1. pvr.iptvsimple: when `xc` mode is actually selected

**Mode selection is tag-driven, not URL-shape-driven.** `ParseIntoChannel()` sets
`XTREAM_CODES` only from the literal tag:
```cpp
else if (StringUtils::EqualsNoCase(strCatchup, "xc"))
  channel.SetCatchupMode(CatchupMode::XTREAM_CODES);
```
[`PlaylistLoader.cpp` L431-432](https://github.com/kodi-pvr/pvr.iptvsimple/blob/Piers/src/iptvsimple/PlaylistLoader.cpp#L431-L432)
(`Piers` branch, fetched 2026-09-17). Nothing inspects the live URL to pick a
mode. **Confirmed: `catchup="default"` with no `catchup-source` is never
auto-upgraded to `xc` from URL shape alone.**

**"xeev" heuristic is narrower than the question implies.** It requires
*header-level* `catchup="xc"` plus a `"* "`/`"[+] "` channel-name prefix:
```cpp
if (m_m3uHeaderStrings.m_catchup == "xc") xeevCatchup = true;   // L142
...
if (!channel.HasCatchup() && xeevCatchup &&
    (StringUtils::StartsWith(channelName, "* ") || StringUtils::StartsWith(channelName, "[+] ")))
{ channel.SetHasCatchup(true); channel.SetCatchupMode(CatchupMode::XTREAM_CODES); }
```
[`PlaylistLoader.cpp` L141-143, L439-443](https://github.com/kodi-pvr/pvr.iptvsimple/blob/Piers/src/iptvsimple/PlaylistLoader.cpp#L439-L443).
Does not apply to a plain `catchup="default"` channel.

**`DEFAULT` + empty `catchup-source` → Append fallback, usually disables
catchup.** `ConfigureCatchupMode()`'s `DEFAULT` case falls through to
`GenerateAppendCatchupSource()`:
```cpp
bool Channel::GenerateAppendCatchupSource(const std::string& url)
{
  if (!m_catchupSource.empty()) { m_catchupSource = url + m_catchupSource; return true; }
  else if (!m_settings->GetCatchupQueryFormat().empty())
  { m_catchupSource = url + m_settings->GetCatchupQueryFormat(); return true; }
  return false;
}
```
[`Channel.cpp` L456-471](https://github.com/kodi-pvr/pvr.iptvsimple/blob/Piers/src/iptvsimple/data/Channel.cpp#L456-L471). The addon's `catchupQueryFormat`
setting ships empty (`<default></default>`,
[`settings.xml` L312-318](https://github.com/kodi-pvr/pvr.iptvsimple/blob/Piers/pvr.iptvsimple/resources/settings.xml#L312-L318)), so with stock settings this
returns `false`, and `ConfigureCatchupMode()` then **disables catchup entirely**
for the channel (`invalidCatchupSource` → `m_catchupMode = DISABLED`,
[`Channel.cpp` L419-423](https://github.com/kodi-pvr/pvr.iptvsimple/blob/Piers/src/iptvsimple/data/Channel.cpp#L419-L423)) — it does not silently build a
`?utc=&lutc=` URL. That exact template is hardcoded only in `SHIFT` mode:
```cpp
void Channel::GenerateShiftCatchupSource(const std::string& url)
{
  if (url.find('?') != std::string::npos) m_catchupSource = url + "&utc={utc}&lutc={lutc}";
  else m_catchupSource = url + "?utc={utc}&lutc={lutc}";
}
```
[`Channel.cpp` L434-439](https://github.com/kodi-pvr/pvr.iptvsimple/blob/Piers/src/iptvsimple/data/Channel.cpp#L434-L439). **This corrects the question's
premise**: pvr.iptvsimple itself would not, out of the box, generate the
`?utc=&lutc=` request the provider silently no-ops on for a `catchup="default"`
channel — that behaviour must come from a different client (e.g. TiviMate,
undocumented per prior research) or a manually configured
`catchupQueryFormat`/`catchup-source`. Not resolved from primary sources.

**`catchupOverrideMode` is the real per-provider override lever.**
```cpp
enum class CatchupOverrideMode : int { WITHOUT_TAGS = 0, WITH_TAGS, ALL_CHANNELS };
```
[`InstanceSettings.h` L74-79](https://github.com/kodi-pvr/pvr.iptvsimple/blob/Piers/src/iptvsimple/InstanceSettings.h#L74-L79), applied in
`ConfigureCatchupMode()` [`Channel.cpp` L335-360](https://github.com/kodi-pvr/pvr.iptvsimple/blob/Piers/src/iptvsimple/data/Channel.cpp#L335-L360): if the addon
setting `allChannelsCatchupMode` (default `0`=`DISABLED`) is non-disabled, it can
force a mode onto channels lacking tags (`WITHOUT_TAGS`), having any tag
(`WITH_TAGS`), or unconditionally (`ALL_CHANNELS`). Both settings default off
(`settings.xml` L323-330). `CatchupMode` enum values: `DISABLED=0, DEFAULT=1,
APPEND=2, SHIFT=3, FLUSSONIC=4, XTREAM_CODES=5, TIMESHIFT=6, VOD=7`
([`data/Channel.h` L18-29](https://github.com/kodi-pvr/pvr.iptvsimple/blob/Piers/src/iptvsimple/data/Channel.h#L18-L29)).

**The `xc` regex cannot match a `.ts`-suffixed live URL.**
```cpp
static std::regex xcRegex("^(http[s]?://[^/]+)/(?:live/)?([^/]+)/([^/]+)/([^/\\.]+)(\\.m3u[8]?)?$");
```
[`Channel.cpp` L540](https://github.com/kodi-pvr/pvr.iptvsimple/blob/Piers/src/iptvsimple/data/Channel.cpp#L540) (`GenerateXtreamCodesCatchupSource`, L538-575).
The id-capture group `([^/\.]+)` excludes dots, and the only optional suffix is
`(\.m3u[8]?)?` — there is no `.ts` alternative. A `std::regex_match` (whole-string)
against `https://xc.example/live/u/p/1.ts` (this
question's example) fails: the trailing `.ts` cannot be consumed by either group.
So `GenerateXtreamCodesCatchupSource()` returns `false` and pvr.iptvsimple would
treat this exact channel's catchup as invalid even with `catchup="xc"` forced on
it. Verified by reading the regex, not by running the addon.

**Timezone of `{Y}-{m}-{d}:{H}-{M}` — local machine time, confirmed.**
```cpp
inline std::tm SafeLocaltime(const std::time_t& time)
{
#if (defined(WIN32) || defined(_WIN32) || defined(__WIN32__))
  localtime_s(&tm_snapshot, &time);
#else
  localtime_r(&time, &tm_snapshot); // POSIX
#endif
  return tm_snapshot;
}
```
[`utilities/TimeUtils.h` L14-23](https://github.com/kodi-pvr/pvr.iptvsimple/blob/Piers/src/iptvsimple/utilities/TimeUtils.h#L14-L23), used exclusively (no
`gmtime`/`gmtime_r` anywhere in `CatchupController.cpp`) for every
`{Y}{m}{d}{H}{M}{S}` substitution in `FormatDateTime()`
([`CatchupController.cpp` L365-380](https://github.com/kodi-pvr/pvr.iptvsimple/blob/Piers/src/iptvsimple/CatchupController.cpp#L365-L380)). This is the OS/process
local timezone of the Kodi device — pvr.iptvsimple never calls
`player_api.php` and has no notion of the provider's `server_info.timezone`. If
the two differ, the stamp is wrong and the request 404s, matching this
question's own UTC-stamp probe.

**`catchup-correction` application.**
```cpp
return BuildEpgTagUrl(m_catchupStartTime, duration, channel, m_timeshiftBufferOffset,
    m_programmeCatchupId, m_epg.GetEPGTimezoneShiftSecs(channel) + channel.GetCatchupCorrectionSecs());
...
startTimeUrl = FormatDateTime(offset - timezoneShiftSecs, duration, channel.GetCatchupSource());
```
[`CatchupController.cpp` L518, L468-475](https://github.com/kodi-pvr/pvr.iptvsimple/blob/Piers/src/iptvsimple/CatchupController.cpp#L468-L475). The combined
`tvg-shift` + `catchup-correction` (both seconds; correction parsed as decimal
hours × 3600, per `m3u-catchup-conventions.md`) is subtracted from the offset
*before* `localtime`-formatting — a flat, non-DST-aware hour adjustment, the only
lever pvr.iptvsimple gives to reconcile device-local vs. provider-server time.

## 2. Xtream Codes `timeshift.php` / `/timeshift/` — no authoritative spec

No official Xtream Codes documentation could be located (company defunct, per
`xtream-codes-api.md`). The fullest third-party reference,
**worldofiptvcom/xtream-codes-api-documentation**
(`XTREAM_CODES_API_DOCUMENTATION.md`, fetched via summarizing fetch 2026-09-17 —
treat quotes below as faithful paraphrase, not byte-exact), gives:

- Pattern: `/timeshift/{username}/{password}/{duration}/{start}/{stream_id}`
- `duration`: "Duration in minutes"; `start`: "Start time (format:
  YYYY-MM-DD:HH-MM or YYYYMMDD-HH)"
- Example: `http://server:25461/timeshift/user1/pass123/60/2025-12-24:10-00/123`
- Appendix: `timeshift.php | wwwdir/streaming/ | Timeshift Handler` — corroborates
  the `{host}/streaming/timeshift.php?...` query form.

Critically, **this document does not state whether `start` is local server time
or UTC** — the same gap the research question flags. `server_info.timezone` /
`time_now` / `timestamp_now` from `player_api.php` are documented (per
`xtream-codes-api.md` §1, re-confirmed here) as the client's reference for the
backend's wall clock, but **no primary source states `timeshift.php`'s `start` is
interpreted in that same zone** — that link is inference (from pvr.iptvsimple's
convention and this question's own empirical probes), not documentation.

**chazlarson/py-xtream-codes** (`xtream.py`, `master`, fetched 2026-09-17)
implements auth/live/VOD/series/EPG calls but **has no timeshift/catchup
function at all** — confirming timeshift is left to the player/addon layer, not
wrapped by client libraries.

**TiviMate "Catchup type: Xtream codes"**: no primary TiviMate source found,
consistent with `m3u-catchup-conventions.md`'s existing conclusion; not
re-verified further here.

**MuxTV/Muxtv issue #315 / PR #319** and **Jellyfin-Xtream-Library issue #108**
(fetched 2026-09-17): both independently converge on the same
`/timeshift/{user}/{pass}/{duration}/{start}/{streamId}.{ext}` shape but
explicitly leave "exact duration unit/start formatting" to be "locked by
repository tests from cited prior art" — peer implementations converging
empirically, not a new authority on local-vs-UTC.

## 3. How other clients decide `?utc=` append vs XC timeshift

No primary source among those checked states a general "if URL is XC-shaped,
prefer timeshift" rule — every client that supports `xc` treats it as an
explicit provider-declared mode, not URL-shape auto-detection:

- **Threadfin/xTeVe**: direct Go source for catchup/XC decision logic could not
  be fetched in this session; unconfirmed.
- **m3u4u.com/faq**: fetched but returned no substantive content beyond a page
  title — m3u4u does not appear to publish a reachable catchup specification,
  corroborating the question's framing of it as silent on mechanism.
- **pvr.iptvsimple README** "Catchup" section (`Piers` branch, summarizing
  fetch) confirms the mode list and `catchup-correction`'s stated purpose
  ("geo-mismatched streams"), adding nothing beyond §1's source-code findings.
- **iptv-org tooling**: not investigated (out of scope for this session).

## Empirical evidence (dated 2026-09-17, this provider only)

Session's own probes against one m3u4u/Xtream-Codes-backed provider
(`xc.example`), not a documented spec:

- M3U line: `catchup="default" tv_archive="1" tv_archive_duration="3"
  catchup-days="3"` → live `https://xc.example/live/u/p/1.ts`
- `?utc={utc}&lutc={lutc}` appended to the live `.ts` URL → redirects to plain
  live (silent fallback, no error).
- `/timeshift/{user}/{pass}/{minutes}/{YYYY-MM-DD:HH-MM}/{id}.ts` with a stamp in
  `server_info.timezone` (America/Toronto) → HTTP 206, `video/mp2t`.
- Same path form, stamp in UTC → HTTP 404.
- `/streaming/timeshift.php?username=&password=&stream=&start=&duration=` with
  the local stamp → also works.

This corroborates §1's finding that XC-convention timestamps are server-local
wall clock, not UTC — but note this provider's `.ts`-suffixed live URL would
*not* actually be matched by pvr.iptvsimple's own `xcRegex` (§1), so this
provider requires a client-side implementation that doesn't inherit
pvr.iptvsimple's regex restriction.

## Open questions / uncertainties

1. Which client actually performs the plain `?utc=&lutc=` append this provider
   silently no-ops on — not pvr.iptvsimple's stock fallback (§1). Unresolved.
2. No primary Xtream Codes source confirms `server_info.timezone` is the zone
   `timeshift.php`'s `start` is interpreted in — inferred only.
3. Threadfin/xTeVe catchup-mode decision logic not directly fetched.
4. TiviMate's XC catchup-type setting has no located primary documentation.
5. The `xcRegex` `.ts`-exclusion (§1) was verified by reading the pattern, not
   by running the addon.

## Recommendation for Kodimate

**(a) Detect XC-shaped URLs to set a per-provider default; keep an explicit
override, never silently fall back to `?utc=` append.**

- When a channel declares `catchup="default"` (or `tv_archive="1"` with no
  usable `catchup-source`) and its live URL matches an XC shape
  (`.../live/{user}/{pass}/{id}[.ext]` or `.../{user}/{pass}/{id}[.ext]`,
  **including a `.ts` extension** — deliberately broader than pvr.iptvsimple's
  own regex, per §1), prefer building the XC `/timeshift/...` URL over any
  `?utc=` append. This is a deliberate divergence from pvr.iptvsimple (which
  never auto-detects from URL shape) justified by this provider's own empirical
  behaviour: `?utc=` silently degrades to plain live, while XC-timeshift works.
- Do not fall back to `?utc=&lutc=` append when no `catchup-source`/query format
  is configured — per §1, that fallback is meaningless without a
  provider-supplied template and this provider's probe shows it fails silently
  rather than loudly. Prefer: XC-timeshift if the URL matches, else no catchup
  offered (surfaced as such in the UI), consistent with the map's existing
  per-provider override philosophy.
- Still provide a **per-provider "Catch-up mode override" setting**, mirroring
  pvr.iptvsimple's `catchupOverrideMode`/`allChannelsCatchupMode` (§1) — every
  primary source agrees this manual escape hatch is needed for providers whose
  tags lie or whose URLs don't match the (necessarily heuristic) auto-detection.

**(b) Server-local timezone: call `player_api.php` once per provider, cache
`server_info.timezone`, do IANA/DST-aware date math — not a flat offset alone.**

- `{host}/player_api.php?username={user}&password={pass}` (credentials
  extracted from the live URL's path segments) returning `server_info.timezone`
  is the correct field (`xtream-codes-api.md` §1, re-confirmed §2 here) — no
  source contradicts using it as the reference zone, and it is strictly better
  than pvr.iptvsimple's approach of trusting the Kodi device's own OS timezone
  (§1), which is wrong whenever device and backend differ (the exact class of
  bug `catchup-correction` exists to patch manually).
- Convert the programme's UTC start time to the IANA zone named in
  `server_info.timezone`, DST-aware, at the programme's actual date — a fixed
  offset computed once is wrong across DST transitions. Kodi 21 "Omega" bundles
  Python 3.11.7 (per the `21.0`/`21.0b2`/`21.0a3-Omega` GitHub release notes),
  so stdlib `zoneinfo` (available since 3.9) is the right API, **but it depends
  on IANA tzdata being present on the host, which is not guaranteed** — Kodi's
  own official add-on repo ships both `script.module.tzdata` and
  `script.module.backports.zoneinfo` for the Omega and Piers repos (confirmed
  via `kodi.tv/addons/omega/script.module.tzdata/` search-result snippets and
  `mirrors.mit.edu/kodi/addons/{omega,piers}/` listings), which only makes sense
  if stdlib `zoneinfo` cannot be trusted to resolve names unassisted on every
  platform (matches the general Python caveat that on Windows `TZPATH` is
  typically empty and the `tzdata` package becomes the fallback source).
  **Recommendation: depend on `script.module.tzdata` explicitly** and use
  `zoneinfo` for the UTC→server-zone conversion.
- Still expose a manual correction-hours field (matching pvr.iptvsimple's
  `catchup-correction`) as a last-resort per-provider override for when
  `server_info.timezone` is missing or wrong — but don't make it the primary
  mechanism, since a flat offset silently breaks across DST transitions twice a
  year, which `zoneinfo`-based conversion avoids.

## Sources

- **kodi-pvr/pvr.iptvsimple**, `Piers` branch (fetched 2026-09-17): `Channel.cpp`
  (`ConfigureCatchupMode`, `GenerateAppendCatchupSource`,
  `GenerateShiftCatchupSource`, `GenerateXtreamCodesCatchupSource`, `xcRegex`),
  `Channel.h` (`CatchupMode` enum), `PlaylistLoader.cpp` (`ParseIntoChannel`,
  xeev heuristic), `CatchupController.cpp` (`FormatDateTime`, `BuildEpgTagUrl`,
  `GetCatchupUrl`), `utilities/TimeUtils.h` (`SafeLocaltime`),
  `InstanceSettings.h` (`CatchupOverrideMode`), `pvr.iptvsimple/resources/settings.xml`
  (setting defaults). All quotes above permalinked to exact `Piers`-branch lines.
- **github.com/kodi-pvr/pvr.iptvsimple/blob/Piers/README.md** — summarizing
  fetch; corroborates mode list and `catchup-correction` framing.
- **worldofiptvcom/xtream-codes-api-documentation**
  (`XTREAM_CODES_API_DOCUMENTATION.md`, `master`) — summarizing fetch
  2026-09-17; `/timeshift/...` pattern, `timeshift.php` location, confirms no
  local-vs-UTC statement exists in this doc.
- **chazlarson/py-xtream-codes**, `xtream.py` (`master`, fetched 2026-09-17) —
  confirms absence of any timeshift/catchup function.
- **MuxTV/Muxtv issue #315 and PR #319**,
  **firestaerter3/Jellyfin-Xtream-Library issue #108** (fetched 2026-09-17) —
  peer implementations converging on the same URL shape; not authoritative on
  local-vs-UTC.
- **kodi.tv add-on listings**: `script.module.tzdata`,
  `script.module.backports.zoneinfo` for Omega/Piers (direct WebFetch returned
  HTTP 403; existence/target repos confirmed via web-search snippets and
  `mirrors.mit.edu/kodi/addons/{omega,piers}/` listings) — used only to confirm
  these add-ons exist, not for exact description text.
- **github.com/xbmc/xbmc releases** (`21.0-Omega`, `21.0b2-Omega`,
  `21.0a3-Omega`, via search snippets) — Python 3.11.7 bundled in final 21.0
  "Omega".
- **m3u4u.com/faq** — fetched 2026-09-17; no substantive catchup content found.
- Threadfin/xTeVe, iptv-org tooling — searched but no primary source fetched
  this session; see Open Questions.
