# Kodimate v1 specification

## Problem Statement

A Kodi user has one or more IPTV subscriptions — some given to them as an M3U playlist URL, some as Xtream Codes server/username/password credentials (often pasted as a single `get.php?username=...&password=...` URL). They want to watch live television and catch up on things they missed, entirely from the couch with a remote control or D-pad, the way a TiviMate user on Android TV would: a numbered channel list grouped into categories, an EPG guide grid they can scroll forwards and backwards through, an on-screen display over live video that lets them switch channels without leaving full-screen playback, and the ability to jump into a past programme's recording when their provider supports it.

Kodi's own PVR subsystem and `pvr.iptvsimple` can technically play IPTV, but they impose Kodi's native PVR channel-list/EPG/OSD UI, treat every configured playlist as one merged channel space, and give the addon author no control over layout, zapping feel, or catch-up UX. A `pluginsource` addon forces Kodi's generic directory-listing UI, which has no guide grid or in-player zapping at all. None of Kodi's stock building blocks produce a TiviMate-like experience, and the C++-only PVR API is closed to a Python addon entirely.

The user also has real-world provider quirks to live with: providers rotate stream tokens, rename channels between refreshes, sometimes reject one stream URL format but accept another, sometimes cap concurrent connections, and vary in which M3U catch-up convention (if any) they follow. The addon has to keep working through all of that without losing the user's own channel numbering, hidden channels, and favourites every time the channel list is refreshed.

## Solution

Kodimate (`script.kodimate`) is a Kodi 21 Omega / 22 Piers script addon — not a PVR client, not a plugin source — with its own WindowXML UI (the `script.plexmod` pattern: `BaseWindow` over `WindowXML`, `ManagedControlList`, a single 1080i skin Kodi scales to fit) plus a background `service` extension that owns all provider refreshing. It ingests M3U and Xtream Codes providers, decodes their EPG (XMLTV, Xtream `xmltv.php`, or a user-supplied XMLTV override) into a local SQLite database, and plays live and catch-up streams directly through `xbmc.Player`, letting Kodi's core ffmpeg demux MPEG-TS and HLS with no PVR API, no `inputstream.adaptive`, and no local proxy involved (ADR 0004, ADR 0006).

Multiple providers coexist from day one; the same channel offered by two providers is deliberately never merged, so a provider's own numbering, grouping, and archive behaviour stay intact per provider. Each channel gets a stable Channel Key so that when a provider's channel list is refreshed, channels that vanish go Stale (not deleted) and channels that persist keep the user's number, hidden state, and favourite status — held in a separate Overrides table that survives every refresh (ADR 0001).

A background service refreshes providers on an interval, at startup, and on demand, using SQLite in WAL mode so the UI keeps reading and playing uninterrupted while a refresh writes (ADR 0003, ADR 0005). On startup, only providers not refreshed within the interval are refreshed. Live playback runs through one owned `Player` instance driven by a bounded state machine (Connecting → Playing → Reconnecting → Failed) that classifies stream failures with an out-of-band HTTP probe and falls back between an Xtream provider's `.ts` and `.m3u8` live forms, learning and persisting whichever one works. Catch-up plays past programmes from the provider's archive through the same machine, reached from the Guide, a dedicated Catch-up browser, or the OSD, all funnelled through one Programme info dialog.

The result is a self-contained IPTV client: add a provider, get a numbered, groupable, favouritable channel list with a live EPG guide and TiviMate-style playback controls, entirely inside Kodi's own script-addon sandbox.

## User Stories

Actor is "Kodi user" unless noted otherwise.

### Provider onboarding

1. As a Kodi user, I want to add an M3U provider by pasting a playlist URL, so that I can bring in my subscription's channels.
2. As a Kodi user, I want to add an M3U provider by browsing to a local playlist file, so that I can use a playlist I already downloaded.
3. As a Kodi user, I want to add an Xtream Codes provider by entering server address, username, and password, so that I can bring in an Xtream subscription.
4. As a Kodi user, I want to paste a full `get.php?username=...&password=...` URL into the Xtream server field and have it auto-split into server, username, and password, so that I don't have to copy each field out by hand.
5. As a Kodi user, I want a Test Connection action on the Provider Form that checks my details without saving, so that I can catch a typo or an unreachable server before committing to it.
6. As a Kodi user, I want Test Connection to show me the channel count for an M3U playlist, or my expiry/connection limits for an Xtream account, so that I know what I'm about to add.
7. As a Kodi user, I want provider fields I don't understand tucked under an "Advanced" heading, so that the common case stays simple.
8. As a Kodi user, I want to set a per-provider User-Agent, so that providers that reject Kodi's default User-Agent still work.
9. As a Kodi user, I want to Disable a provider without deleting it, so that I can pause a subscription's channels without losing its configuration.
10. As a Kodi user, I want to Delete a provider, so that I can permanently remove a subscription and everything under it.
11. As a Kodi user, I want a confirmation before deleting a provider that tells me its channels, favourites, and overrides will be removed, so that I don't lose data by accident.
12. As a Kodi user, I want the provider's kind (M3U or Xtream) to be fixed once I've created it, so that I'm not offered a form whose fields don't match how the provider's channels are identified.
13. As a Kodi user, I want to reorder my providers, so that I can control which provider's channels list first.
14. As a Kodi user, I want the Providers list to show each provider's channel count, last refresh time, and any error, so that I can see at a glance whether a provider is healthy.
15. As a Kodi user, I want an Xtream provider's row to warn me when its subscription is expiring within a week, so that I can renew before it lapses.
16. As a Kodi user, I want a first-run experience that opens straight to an empty Providers screen with a hint to add my first provider, so that I'm not staring at an empty channel list with no idea what to do.
17. As a developer, I want provider credentials stored as plaintext SQLite rows rather than obfuscated, so that the storage model is honest about the protection it actually provides (filesystem permissions only).

### Refresh

18. As a Kodi user, I want a background service to refresh my providers automatically on a configurable interval, so that my channel list and EPG stay current without me doing anything.
19. As a Kodi user, I want providers refreshed once at Kodi startup, so that my channel list is current as soon as I open the addon.
20. As a Kodi user, I want a manual "Refresh now" per provider and "Refresh all", so that I can force an update right after my provider adds channels.
21. As a Kodi user, I want to keep watching my current channel uninterrupted while a refresh runs in the background, so that a scheduled refresh never interrupts what I'm doing.
22. As a Kodi user, I want a toast if a manual refresh fails, so that I know it didn't silently work.
23. As a Kodi user, I want a channel I'm currently watching to keep playing even if it goes Stale mid-refresh, so that a transient provider hiccup doesn't cut my stream.
24. As a Kodi user, I want an open channel list or guide to update in place when a refresh completes, so that I don't have to back out and reopen the screen to see new channels.
25. As a Kodi user, I want my focus and scroll position preserved when a screen re-renders after a refresh, so that I'm not thrown back to the top of a long list.
26. As a Kodi user, I want editing a provider's connection details to immediately queue a fresh refresh, so that I don't have to remember to refresh manually after fixing a typo.
27. As a Kodi user, I want to see a "refreshing" indicator on a provider while it's being refreshed, so that I know why my manual refresh button is greyed out.
28. As a developer, I want the service to be the sole writer of channel/group/programme rows so the script only ever writes overrides and provider config, so that there is exactly one writer to reason about for schema-derived data.

### Channel list

29. As a Kodi user, I want a channel list grouped into the provider's own categories, so that I can browse by genre or bundle the way my provider organised them.
30. As a Kodi user, I want channels numbered from the provider's own numbering (or provider order if it has none), so that the list matches numbers I'm used to from other apps.
31. As a Kodi user, I want to renumber a channel myself, so that I can put my favourite channels at low numbers.
32. As a Kodi user, I want to hide a channel I never watch, so that it stops cluttering my list.
33. As a Kodi user, I want a "show hidden" toggle so that I can still find and unhide a channel I hid by mistake.
34. As a Kodi user, I want to mark a channel as a favourite, so that it shows up in one flat Favourites list regardless of its provider or group.
35. As a Kodi user, I want to reorder my Favourites list by hand, so that my most-watched channels sit at the top.
36. As a Kodi user, I want to reset a channel's overrides back to what the provider supplied, so that I can undo my own customisations without deleting the channel.
37. As a Kodi user, I want all of these edits reachable from a single context menu on a focused channel row, so that I don't have to learn a separate editing mode.
38. As a Kodi user, I want a channel that disappears from a provider's list to stay in place with its overrides intact for a week before being purged, so that a transient playlist error doesn't wipe out my customisations.
39. As a Kodi user, I want the same channel offered by two different providers to appear as two separate rows, so that each provider's own numbering, archive support, and reliability stay visible to me.
40. As a Kodi user, I want a channel's logo shown next to its name, sourced straight from the provider, so that I can recognise channels visually.
41. As a Kodi user, I want a channel with a broken or missing logo to fall back to a bundled placeholder image, so that the list never shows a broken image icon.

### EPG / Guide

42. As a Kodi user, I want a guide grid showing channels down the side and a scrolling timeline of programmes across, so that I can see what's on now and later across all my channels at once.
43. As a Kodi user, I want a now-line marking the current time on the guide, so that I can tell at a glance what's live.
44. As a Kodi user, I want to move the guide cursor left/right within a channel's row to select adjacent programmes, and up/down to move to the next channel at the same time position, so that browsing feels natural on a D-pad.
45. As a Kodi user, I want programme cells sized proportionally to their duration, so that a 30-minute show and a 3-hour film are visually distinguishable.
46. As a Kodi user, I want a channel with no EPG data to show clearly as having no programme information rather than an empty or broken cell, so that I'm not confused about whether something is wrong.
47. As a Kodi user, I want OK on a past programme cell to show me its details and, if catch-up is available, let me play it, so that browsing the guide is how I discover catch-up content.
48. As a Kodi user, I want OK on the currently-airing cell to offer both "watch live" and "start over from the beginning", so that I can choose either.
49. As a developer, I want the guide grid built from a control pool of reusable programme cells rather than adding/removing controls per move, so that scrolling and cursor movement stay smooth on real hardware.

### Playback OSD and zapping

50. As a Kodi user, I want the last channel I was watching to autoplay when I start the addon, so that I land straight back in live TV.
51. As a Kodi user, I want the channel list to optionally overlay on top of autoplay, so that I can immediately switch away if autoplay picked the wrong channel.
52. As a Kodi user, I want Up/Down or OK on bare video to open a channel list without changing the stream, so that browsing channels never zaps by accident.
53. As a Kodi user, I want the channel list split into a Groups pane and a Channels pane side by side, so that I can narrow down by group before picking a channel.
54. As a Kodi user, I want OK on a channel in that list to actually zap to it and close the list, so that confirming a choice is a single deliberate action.
55. As a Kodi user, I want to type a channel number directly during playback and have it zap once I stop typing or press OK, so that I can jump straight to a known channel number.
56. As a Kodi user, I want an on-screen info bar showing the channel number, logo, name, current programme with progress, and the next programme, so that I always know what I'm watching and what's coming up.
57. As a Kodi user, I want that info bar to auto-hide after a few seconds and be summonable again with OK, so that it doesn't stay in my way.
58. As a Kodi user, I want the screen to go black with a spinner and immediately show the new channel's name while it's connecting, so that zapping feels responsive even during a slow provider handshake.
59. As a Kodi user, I want Back during playback to close whatever overlay is open first, and only leave playback once nothing is open, so that Back behaves predictably layer by layer.
60. As a developer, I want a single owned `xbmc.Player` instance for the whole addon, so that no stale player instance keeps a provider connection open after I've moved away from a channel.

### Stream failure handling

61. As a Kodi user, I want the app to automatically retry a channel a few times if the stream drops mid-play, so that a brief network blip doesn't force me to zap the channel myself.
62. As a Kodi user, I want the app to try an alternate stream format automatically if the first one is rejected on an Xtream provider, so that a provider that only serves `.m3u8` (or only `.ts`) still works without me configuring anything.
63. As a Kodi user, I want the app to remember which stream format worked for a provider, so that it doesn't have to rediscover it on every channel.
64. As a Kodi user, I want a clear message telling me whether a channel failed because my login was rejected, because I've hit my provider's connection limit, or because the stream just wasn't available, so that I know whether the problem is on my end or the provider's.
65. As a Kodi user, I want the channel list to open automatically when a channel fails for good, so that I can immediately try something else.
66. As a Kodi user, I want to retry a failed channel from scratch with OK, so that I can try again after a provider issue clears up.
67. As a Kodi user, I want any zap, number entry, or Back press to immediately cancel a channel that's still trying to connect, so that the app never fights me for control while it's retrying.
68. As a developer, I want every playback attempt logged at INFO with channel, provider, attempt number, format, and outcome, with credentials redacted, so that stream failures are diagnosable from `kodi.log` without exposing secrets.

### Catch-up

69. As a Kodi user, I want to open a past programme cell in the guide and play it from the beginning, so that I can catch up on something I missed.
70. As a Kodi user, I want a dedicated Catch-up browser listing channels that support it, with their past programmes grouped by day, so that I can browse catch-up content without going through the guide.
71. As a Kodi user, I want Left/Right on the playback OSD to step to the previous or next programme on the current channel, playing past ones via catch-up, so that I can move through a channel's schedule without leaving playback.
72. As a Kodi user, I want a single consistent "Programme info" dialog no matter which of these three ways I got there, so that the catch-up experience feels like one feature.
73. As a Kodi user, I want to start the currently-airing programme over from the beginning, so that I can watch something I tuned into partway through.
74. As a Kodi user, I want the guide to visually mark past programmes I can actually play versus ones I can't, so that I don't try to catch up on something outside my provider's archive window.
75. As a Kodi user, I want the next programme to auto-play after a short countdown when a catch-up programme ends, so that I can binge through a channel's schedule without extra button presses.
76. As a Kodi user, I want to cancel that auto-play countdown and go back to where I came from, so that I'm not forced into something I didn't ask for.
77. As a Kodi user, I want catch-up start times corrected for my provider's timezone, so that "8pm" in the guide actually plays the 8pm programme.
78. As a Kodi user, I want to zap away from a catch-up programme to a live channel at any time, exactly like normal zapping, so that catch-up doesn't feel like a separate, more restrictive mode.
79. As a Kodi user, I want a clear message and a return to where I came from if a catch-up programme's stream fails to start, so that I'm not stuck staring at a black screen.
80. As a developer, I want catch-up URLs built per the exact convention my provider uses (Xtream timeshift path/query forms, or one of the M3U catchup modes), so that catch-up works across the range of real-world providers.

### Search

81. As a Kodi user, I want to search across both channel names and programme titles, so that I can find something without knowing which channel it's on.
82. As a Kodi user, I want search results split into a Channels section (OK plays) and a Programmes section (OK opens the Programme info dialog), so that the two kinds of result behave the way I'd expect.
83. As a Kodi user, I want search to ignore case and match partial text, so that I don't need to type an exact channel or programme title.
84. As a Kodi user, I want search to exclude hidden and stale channels and programmes on channels I can't otherwise see, so that results only ever point at things I could actually watch anyway.

### Settings and globals

85. As a Kodi user, I want to control the refresh interval, whether refresh runs at startup, autoplay behaviour, OSD auto-hide timing, and number-entry commit delay from Kodi's own settings screen, so that I can tune the addon without a dedicated screen for every knob.
86. As a Kodi user, I want a "Manage providers" button in Kodi's settings that jumps straight to the Providers screen, so that provider management is reachable from the place I'd naturally look for it.
87. As a Kodi user, I want a debug logging toggle, so that I can turn on verbose logs only when I need to report a problem.

### Packaging, i18n, and dev workflow

88. As a developer, I want every user-facing string sourced from `strings.po` ids from day one, so that translation is never a retrofit.
89. As a Kodi user, I want the addon shipped in British English, so that spelling matches the rest of Kodi's own UI on my system.
90. As a developer, I want a single 1080i skin that Kodi scales to other resolutions, so that I don't maintain multiple skin resolutions in v1.
91. As a developer, I want the addon's version tracked in `addon.xml` using semantic versioning, so that installs and updates are unambiguous.
92. As a developer, I want a deploy script that builds an installable zip, so that I can produce a release artefact without manual packaging steps.
93. As a developer, I want tagged GitHub releases carrying that zip as an asset, so that users have a stable place to download a given version.
94. As a developer, I want a symlink-based local dev loop against a real Kodi install, so that I can iterate on the addon without repackaging on every change.
95. As a developer, I want a log-tailing helper, so that I can watch `kodi.log` while exercising the addon live.

## Implementation Decisions

### Addon shape and packaging

Kodimate is a single addon, id `script.kodimate`, licensed GPL-2.0-or-later, built as an `xbmc.python.script` extension point (its own WindowXML UI, entered via the main menu / `RunScript`) plus a `service` extension point that runs continuously in the background for Refresh. There is no `pluginsource` extension and no dependency on the Kodi PVR API or `pvr.iptvsimple` (ADR 0004): Kodimate never appears in Kodi's native PVR channel list, EPG window, or PVR settings, and none of that native PVR UI is reused.

The UI follows the `script.plexmod` reference pattern: `BaseWindow`/`BaseDialog` wrapping `xbmcgui.WindowXML`/`WindowXMLDialog`, `ManagedControlList`/`ManagedListItem` for binding Python-side lists to native list/panel controls, and a single skin under `resources/skins/Main/1080i` that Kodi scales to other resolutions rather than shipping multiple resolution variants. All user-facing strings are sourced from `strings.po` ids from the start; v1 ships British English (en_GB) only, with no other language files yet.

Packaging uses semantic versioning in `addon.xml`. `scripts/dev/deploy.sh` builds the installable zip (top-level `script.kodimate/` folder, excluding dev/test/doc scaffolding), and tagged GitHub Releases carry that zip as a release asset. The local dev loop (for development only, not part of the shipped addon) symlinks the repo root into the local Kodi install's addons directory, drives Kodi over JSON-RPC (TCP 9090, no auth) for RPC calls and the EventServer (UDP 9777) for builtins such as `UpdateLocalAddons()` — since JSON-RPC itself has no install-from-zip or arbitrary-builtin method — and tails `kodi.log` for diagnosis. `scripts/dev/deploy.sh --install` is the fallback path for testing a real zip install rather than the symlink.

### Storage and schema

All addon state — provider configuration, channels, groups, programmes, overrides, and metadata — lives in one SQLite database under `special://profile/addon_data/script.kodimate/`, opened via the `sqlite3` module bundled with Kodi's Python 3.11 (ADR 0005). There is no separate keychain or secret store: Xtream credentials and tokened M3U URLs are stored as plaintext columns, protected only by filesystem permissions on the Kodi profile directory; they are never logged and never committed to the repository, and any logging of stream or EPG URLs must redact embedded credentials (ADR 0002).

The schema outline (from `docs/design/schema.md`, trimmed to the decision-bearing columns):

- **provider** — `id`, `kind` (`'m3u' | 'xtream'`), `name`, `enabled`, `deleted_at` (nullable, soft-delete marker), `sort_order`, `m3u_url`, `xtream_host`, `xtream_username`, `xtream_password`, `user_agent` (nullable), `account_expires_at` (nullable, Xtream, service-written), `max_connections` (nullable, Xtream, service-written), `epg_override_url`, `catchup_days_default` (nullable), `catchup_url_form` (`'path' | 'query'`, default `'path'`), `catchup_correction_hours` (default 0), `number_offset`, `stream_format` (`'ts' | 'm3u8' | NULL`), `learned_stream_format` (`'ts' | 'm3u8' | NULL`, set on a successful fallback; cleared on host/credential edit or when `stream_format` is set; `stream_format` always wins), `last_refresh_at`, `last_error`, `config_version` (bumped on every script-side edit to kind/url/host/creds/epg_override_url; the service discards in-flight refresh results started against a stale version).
- **epg_source** — `id`, `provider_id` (FK, UNIQUE), `url`, `last_fetched_at`, `etag`/`last_modified`.
- **programme_staging** — same shape as `programme`; exists only mid-refresh, dropped at service startup if left over from a crash.
- **channel_group** — `id`, `provider_id` (FK), `name`, `sort_order`; UNIQUE(`provider_id`, `name`).
- **channel** — `id`, `provider_id` (FK), `channel_key`, `name`, `normalised_name`, `stream_url`, `logo_url`, `group_id` (FK), `provider_number` (nullable), `position`, `epg_channel_id` (nullable), `catchup_days` (nullable), `catchup_mode`, `catchup_source`, `catchup_correction_hours`, `headers_json`, `stale_since` (nullable), `last_seen_at`; UNIQUE(`provider_id`, `channel_key`).
- **channel_override** — `provider_id`, `channel_key`, `number` (nullable), `hidden` (bool), `favourite` (bool), `favourite_order` (nullable); PK(`provider_id`, `channel_key`); deliberately not FK'd to `channel.id` so overrides outlive the channel rows being rebuilt on every refresh.
- **programme** — `epg_source_id` (FK), `xmltv_channel_id`, `start`, `end`, `title`, `subtitle`, `description`, `icon_url`, `category`, `catchup_id` (nullable); PK(`epg_source_id`, `xmltv_channel_id`, `start`); index on (`xmltv_channel_id`, `end`).
- **meta** — `key`/`value`, holding `schema_version`.

Derived values are computed, not stored: **Effective Channel Number** = `channel_override.number`, else `channel.provider_number + provider.number_offset`, else `channel.position + provider.number_offset`. **Effective Catch-up Window** = `channel.catchup_days`, else `provider.catchup_days_default`; `NULL` at both levels means no catch-up. **Live Form** (Xtream only) = `provider.stream_format`, else `provider.learned_stream_format`, else `'ts'`; `'m3u8'` is used only when the account's `allowed_output_formats` includes it. A channel is **listable** (shown in list, Guide, Zapping) only when it is not Stale, not Hidden, and its provider is neither Disabled nor Deleted.

Channel identity (ADR 0001): the **Channel Key** is the Xtream provider's `stream_id`, or for M3U the `tvg-id` when present and unique in the playlist, else the stream URL with scheme and query string stripped, else the full URL. Channel rows are fully rebuilt from each Refresh; a channel absent from a refresh is marked **Stale** (excluded from list/Guide/Zapping, overrides kept) rather than deleted, and purged only after 7 continuous days Stale. Overrides (Channel Number, Hidden, Favourite, Favourite order) live in `channel_override`, keyed by `(provider_id, channel_key)` rather than as columns on `channel`, specifically so they survive the channel table being rebuilt wholesale on every refresh. There is no custom channel name or logo override in v1.

### Providers and ingest

Multiple providers are supported from day one; the same real-world channel appearing under two providers produces two separate Channel rows that are never merged, matched, or deduplicated across providers — each provider's own numbering, grouping, and catch-up behaviour stays independent.

M3U ingest reads `tvg-id`, `tvg-name`, `tvg-logo`, `group-title` (first segment only when it contains `;`), `tvg-chno`, the `catchup`/`catchup-source`/`catchup-days`/`catchup-correction` attribute family, and `#EXTVLCOPT`/`#KODIPROP` header lines plus the `|User-Agent=`/`|Referer=` URL pipe-suffix convention. Xtream ingest calls `player_api.php` (`get_live_categories`, `get_live_streams` once, un-scoped by category) for channels, reading `num`, `stream_icon`, `epg_channel_id`, `tv_archive`, `tv_archive_duration` per stream, and `user_info` for `exp_date`/`max_connections`/`allowed_output_formats`, persisting the account fields to `provider.account_expires_at`/`max_connections` at each Refresh.

A Group is a per-provider `(provider, name)` pair; every channel belongs to exactly one Group; a Group with no non-Stale channels is not shown. Channel Number is a label, not a key — duplicates across channels are allowed — sourced from `tvg-chno`/Xtream `num` when present, else provider list order, with a per-provider numeric offset applicable on top; number-entry Zapping resolves to the first channel in list order (provider order, then channel order within provider) when a number matches more than one channel.

Every value either parser accepts is validated only insofar as it's used, not against a strict conformance check: M3U playlists vary across panels in exactly which catchup attributes and header lines they emit (per `docs/research/m3u-catchup-conventions.md`), and Xtream panels vary in field typing — numeric fields such as `num`/`tv_archive`/`tv_archive_duration` arriving as strings rather than numbers across panel forks (per `docs/research/xtream-codes-api.md`) — and Kodimate tolerates both rather than rejecting a playlist or account for minor non-conformance.

### EPG

Three EPG Source kinds exist, one per provider: an Xtream provider's own `xmltv.php` bulk feed, an M3U playlist's declared `url-tvg`/`x-tvg-url` XMLTV URL, or a user-supplied XMLTV override URL that replaces whichever the provider would otherwise use. XMLTV is streamed via `xml.etree.ElementTree.iterparse` directly over `gzip`/`lzma` file objects (no separate decompress step), calling `elem.clear()` per element to bound memory; a real ~9.5k-programme feed parsed in roughly 230ms inside Kodi's bundled Python, which is acceptable at Refresh time but must never run on the UI's critical path.

At Refresh, each channel is matched to an EPG Source channel id by `tvg-id`/`epg_channel_id` first, falling back to **Normalised Name** — the channel name lowercased, non-alphanumeric characters stripped, and a trailing HD/FHD/UHD/4K suffix removed. Real-world `tvg-id` values sometimes carry a source-disambiguation suffix (observed: `FoxCricket.au (src05)`) that must be stripped before matching against XMLTV ids; without it, channels with such suffixes simply have no EPG match. A provider with no EPG Source at all still shows its channels in the Guide, with a "No information" placeholder cell rather than an empty or broken one.

Programme rows are keyed `(epg_source_id, xmltv_channel_id, start)` and replaced wholesale per EPG Source on each Refresh (see Refresh and concurrency below). Programme retention is fixed at 7 days in v1 (not user-configurable), which in turn caps how far back Catch-up can reach regardless of a provider's own larger archive window.

### Refresh and concurrency

The service (not the script/UI) is the sole writer of `channel`, `channel_group`, `programme`, `epg_source`, and `provider.last_refresh_at`/`last_error`; the script writes only `channel_override`, provider CRUD/config columns, and `provider.learned_stream_format`. A manual "Refresh now"/"Refresh all" from the UI is always a request routed to the service, never run inline in the script process (ADR 0003).

Every connection, in both processes, opens through one shared helper that sets `PRAGMA journal_mode=WAL`, `PRAGMA synchronous=NORMAL`, `PRAGMA busy_timeout=5000`, and runs idempotent schema migrations under `BEGIN IMMEDIATE` guarded by `meta.schema_version` (whichever process opens first migrates; there is no startup handshake between script and service). The script keeps a single connection and always `fetchall()`s reads rather than holding a cursor across UI frames, since a held cursor would pin WAL frames and block checkpointing; script-side writes retry up to 3 times on `database is locked`. The service runs `PRAGMA wal_checkpoint(TRUNCATE)` after each Refresh.

Programme replacement parses into a `programme_staging` table outside any long-running transaction, then applies a single short transaction — delete by `epg_source_id`, `INSERT ... SELECT` from staging, drop staging — keeping the write lock held for well under a second; any staging table left over from a crash is dropped at service startup. Channel rebuild per provider stays a plain delete+insert inside one transaction (small enough not to need staging). Providers are refreshed strictly sequentially, never in parallel, one at a time.

Editing a provider's connection-identifying fields (kind/URL/host/credentials/EPG override) bumps `provider.config_version`; the service records that version when a Refresh starts and, at its final swap transaction, rolls back and discards the fetched results if the version has since changed or the provider row is gone, re-queuing a fresh Refresh if the provider still exists. Deleting a provider (soft-delete via `deleted_at`) is cascaded by the service across `epg_source`/`channel_group`/`channel`/`programme`/`channel_override` for that provider, after which the service bumps the Generation; every query filters out `deleted_at` rows regardless of whether the cascade has run yet, and leftover soft-deleted rows are also swept at service startup.

Script/service coordination runs entirely over `xbmcgui.Window(10000)` properties, all keyed `script.kodimate.<name>` (`docs/design/refresh-ipc.md`):

- `refresh_request` — comma-list of provider ids, or `all`; a `;ui` suffix (e.g. `"3;ui"`) marks a manual request. Written by the script, polled and cleared by the service on a 1s tick and merged into its queue (a provider already refreshing or queued is not queued twice).
- `refreshing` — comma-list of provider ids currently in flight; the UI shows an indicator against those providers and disables their manual-refresh action. If this hasn't changed 10 seconds after a request was made, the script toasts "Kodimate service not running".
- `db_generation` — an integer the service increments after every committed Refresh (never on failure). It is in-memory only; the script treats a missing value as 0 and always re-queries fresh when a window opens.
- `refresh_result.<provider_id>` — `ok` or `error:<message>`, written only for requests carrying `;ui`; the script toasts once and clears it. Background (non-manual) refresh failures never toast; `provider.last_error` remains visible on the Providers screen.

The service additionally sends `NotifyAll('script.kodimate', 'refreshed', {"generation": n, "providers": [...]})`, caught by the script's `Monitor.onNotification` override, purely as a wake-up; `db_generation` is the durable state the UI actually trusts.

On a Generation change, an open channel list or Guide re-queries and re-renders in place: focus is kept by Channel Key (falling to the nearest row if that channel went Stale), scroll offset is preserved, and the Guide re-renders only its visible viewport. Re-render is deferred while any modal (Programme info dialog, context menu, number entry) is open and applied once it closes; if the focused Group or Provider vanished entirely, the Groups pane falls back to "All channels" (or Favourites, if that was active) with no toast, and the Channels pane falls to its first listable row. The OSD's now/next display re-reads programmes by Channel Key on a Generation change without touching the running stream.

A running Playback Session holds a snapshot of its Channel (key, name, stream URL, headers, number, Live Form) taken at start; Refresh never touches or interrupts a live session, and reconnect Attempts reuse that snapshot rather than re-reading the (possibly changed) channel row. A channel going Stale mid-playback keeps playing until the user leaves it; zapping away from a Stale channel lands on the nearest listable channel by Effective Channel Number, and startup autoplay of a last-played channel that has since gone Stale falls back to the first listable channel instead.

### Playback and stream failure

Playback is direct: a single owned `xbmc.Player` instance plays the channel's or programme's stream URL, letting Kodi's core ffmpeg demux TS/HLS with no `inputstream.adaptive`, no `inputstream.ffmpegdirect`, and no local proxy (ADR 0006). Per-channel headers (`#EXTVLCOPT`/`#KODIPROP`-derived User-Agent/Referer) are applied via ListItem properties and rebuilt fresh from the channel row on every Attempt — there is no header "re-injection" step distinct from a normal Attempt. Xtream's Live Form defaults to `.ts` with `.m3u8` fallback only when the account's `allowed_output_formats` permits it; M3U providers have no Live Form concept.

Playback is governed by the **Playback Session** state machine (glossary and design settled in issue #10, `CONTEXT.md`):

- **Connecting** — entered on channel selection (zap, catch-up, or startup autoplay). Any current stream is stopped first; the screen shows black + spinner with the OSD bar already updated to the newly selected channel. Attempt 1 uses the effective Live Form.
- **Start failure** is any of: `onPlayBackError`; `onPlayBackStopped`/`onPlayBackEnded` before `onAVStarted`; no `onAVStarted` within 30 seconds of `play()`; or a drop within 5 seconds of `onAVStarted`. On a start failure, an out-of-band probe (`urllib` `GET` with `Range: bytes=0-0`, 5s timeout, same headers, following redirects) classifies the failure: 401/403 → **Login rejected** (stop, no further Attempts); 429/509/406 → **Connection limit** (stop; message includes `max_connections` when known); 404 → transient for Xtream (the URL form may simply differ) but **Unavailable** for M3U (stop); timeout/connection error/5xx → transient. A transient classification triggers Attempt 2: for Xtream, the other Live Form (only if allowed); for M3U, one retry of the same URL. After Attempt 2 fails, the session moves to **Failed**. A successful fallback persists as `provider.learned_stream_format`, cleared only when the provider's host/credentials are edited or the user sets an explicit `stream_format` (which always wins over the learned value), and never reset by an ordinary Refresh.
- **Playing** — entered on `onAVStarted`.
- **Drop**: `onPlayBackEnded`/`onPlayBackStopped` more than 5 seconds into Playing with no user action (a live stream never legitimately ends on its own). Enters **Reconnecting**: same URL, same Live Form, no probe, up to 3 Attempts at 0s/3s/6s backoff, with the bar reading "Reconnecting…" over the spinner. A reconnect Attempt that itself fails to start is treated as a start failure but skips form fallback (the form already worked once), landing directly on **Unavailable**.
- **Failed** — the terminal state, reached in-player (not by leaving playback): black video, OSD bar shows the channel and its Failure Reason (Unavailable / Login rejected / Connection limit), and the Groups+Channels list opens automatically so the user can zap elsewhere immediately. OK on bare video from this state starts a brand-new Playback Session from Attempt 1 (with a fresh probe on any new failure), clearing the shown reason.
- Any zap, number-entry digit, or Back press during Connecting or Reconnecting aborts the machine outright: pending timers and any in-flight probe are cancelled and the Player is stopped before the new action proceeds.

Catch-up uses the same state machine with two differences: a start failure runs the probe plus (Xtream only) one alternate-URL-form retry, then goes straight to a toast ("Catch-up unavailable from <Provider>") and a return to the Origin screen — there is no in-player Failed state or "zap elsewhere" affordance for catch-up. A Drop mid-programme reconnects up to 3 times with the requested start time recomputed to the current playback position (programme start + elapsed), falling back to the same toast+Origin behaviour if reconnection is exhausted.

Logging: one INFO line per Attempt in `kodi.log` — channel key, provider id, attempt number/max, Live Form, outcome, probe status, elapsed time — with Xtream username/password path segments and query parameters redacted to `***`. DEBUG logging (toggle in settings) adds the full player-callback trace. No failure state is persisted to SQLite in v1; a per-channel "last failed" indicator is deferred (see Out of Scope).

Stream-stall detection (playing but frozen, no callback firing) is explicitly out of scope for v1; only the failure classes above are handled.

### Catch-up

Catch-up is **programme-driven**: a channel with no Programme rows offers no Catch-up regardless of its provider-declared archive support, and there is no arbitrary-time-of-day picker in v1. A Programme is playable via Catch-up when its channel's Effective Catch-up Window is greater than 0, `programme.start >= now - window_days`, and `programme.start < now`; an in-progress programme (start ≤ now ≤ end) plays as **Start Over** rather than being excluded. Requested playback duration is `min(programme.end, now) - programme.start`. Because Programme rows are retained for only 7 days, Catch-up is effectively capped at 7 days regardless of a provider declaring a longer archive window (e.g. Xtream `tv_archive_duration`).

Three entry points, one shared **Programme info dialog** (title, HH:MM–HH:MM, description, and *Play Catch-up*/*Watch live* actions as applicable):

- **Guide**: OK on a past cell opens the dialog; playable past cells carry a catch-up glyph, unplayable ones are greyed with an info-only dialog.
- **Catch-up browser**: a dedicated screen, left pane = channels with an Effective Catch-up Window (Favourites first), right pane = that channel's past Programmes grouped by day, newest first; OK opens the same dialog.
- **OSD**: Left/Right on bare video during live playback steps to the previous/next Programme on the current channel; stepping to a past one plays it via Catch-up; OK on the info bar opens the dialog for the currently-referenced programme.

There is no channel-list context-menu entry point for Catch-up in v1.

URL construction, from the prototype/research artefacts:

- **Xtream**: primary path form `{host}/timeshift/{user}/{pass}/{minutes}/{Y}-{m}-{d}:{H}-{M}/{stream_id}{ext}` (local wall-clock start time, duration in minutes, extension mirroring the live URL with `.ts` fallback); the query-string form `streaming/timeshift.php?...&stream=&start=&duration=` is the alternate. Whichever form last succeeded is persisted per-provider as `provider.catchup_url_form` (`path`|`query`, default `path`), user-editable in the Provider Form as an "Auto" (learned) vs. pinned choice.
- **M3U**: per `channel.catchup_mode`, matching `pvr.iptvsimple`'s six modes exactly — `default` (use `catchup-source` verbatim, else fall back to `append`), `append` (concatenate `catchup-source`/the global catchup query format onto the live URL), `shift`/legacy `timeshift=` (auto-appends `?`/`&utc={utc}&lutc={lutc}`, ignoring `catchup-source`), `flussonic`/`flussonic-hls`/`flussonic-ts`/`fs` (regex-rewrites the live URL into a Flussonic timeshift path), `xc` (regex-rewrites Xtream-Codes-style URLs, including an "xeev" channel-name-prefix heuristic), and `vod` (treated as `default` in v1). The full template-variable table (from `docs/research/m3u-catchup-conventions.md`) is honoured: `{utc}`/`${start}` and `{utcend}`/`${end}` (Unix seconds), `{lutc}`/`${now}`/`${timestamp}` (now, Unix seconds — `${timestamp}` is a TiviMate-compatibility alias), `{duration}`/`${duration}` and `{duration:N}` (seconds, optionally divided by N), `{offset}`/`${offset}` and `{offset:N}`, bare `{Y}{m}{d}{H}{M}{S}` start-time date/time components, the `{name:<fmt>}` custom-format mini-language, and `{catchup-id}` (the XMLTV programme id, used verbatim by `vod` mode). `catchup-days` is an integer number of days and `catchup-correction` is decimal hours (`atof(value) * 3600`), not seconds. `#EXTVLCOPT` is allow-listed to `http-user-agent`/`http-referrer`/`program`(/`http-reconnect`); `#KODIPROP` is accepted verbatim (with an `inputstreamaddon`/`inputstreamclass` special-case remap); Kodi's `|User-Agent=...&Referer=...` pipe-suffix convention is preserved across catch-up URL rewriting. Note: TiviMate's own template engine has no public specification, so any TiviMate-specific behaviour beyond the `${timestamp}` alias is community-inferred, not confirmed against a primary source.
- **Timezone**: the catch-up start time is corrected by an auto-derived offset (Xtream `server_info.timezone`, or M3U `catchup-correction`) plus a per-provider user correction on top (`provider.catchup_correction_hours`, editable in the Provider Form, −12..+12 hours).

Playback behaviour: seeking is native Kodi player seek only — no URL-rebuild seeking beyond the stream's own buffer, and no seek offered at all if the stream reports no duration. At the end of a catch-up programme, a 5-second "Up next" countdown plays the next Programme on the same channel; the player is always stopped and `onPlayBackStopped` awaited before the next `play()` (important for single-connection accounts); if the next Programme is airing now, the live URL is used instead and the catch-up badge drops. Back during the countdown cancels it and returns to the Origin screen. The OSD during Catch-up shows the same bar plus a CATCH-UP badge, with position/duration replacing wall-clock progress; Up/Down still opens the channel list, and OK on any channel there leaves Catch-up for live playback of that channel (as does number entry). Back returns to the Origin screen — the screen the Playback Session was started from (Guide, Catch-up browser, or channel list). There is no resume position in v1.

On provider refusal: Xtream gets one retry with the alternate URL form, then fails; M3U gets no retry. Any failure surfaces as a toast ("Catch-up unavailable from <Provider>") and a return to the Origin screen — never a silent fallback to live playback, and Catch-up is never auto-disabled on the channel as a result.

### UI windows

The v1 surface comprises: a channel list (Groups pane + Channels pane, grouping/numbering/hide/favourite/move/reset via context menu), the EPG guide grid, the playback OSD with in-player zapping and number entry, the Catch-up browser and its shared Programme info dialog, the Providers list and Provider Form, and search.

**Guide grid**: built as a hybrid — a native `<control type="list">` drives the channel column's vertical navigation and scrolling, while programme cells are Python-created `ControlImage`/`ControlLabel` pairs positioned proportionally to duration from a reusable control pool (created once, relaid out via `setPosition`/`setWidth`/`setLabel`/`setImage`/`setVisible` rather than added/removed per move, which measured 1–9ms for a full relayout versus visible flicker under add/remove). A fixed 30-minute slot grid and an all-native-button approach were both prototyped and rejected (the former loses programme boundaries, the latter can't retain list focus semantics without flicker). The guide cursor is an on-screen "travel axis" time column, set only by Left/Right and the skip/jump actions below and rendered by swapping the focused cell's texture/label colour rather than moving native list focus; Up/Down resolve the target row's cell against the travel axis and never scroll the viewport, while Left/Right move to the adjacent cell in the row's layout — every gap between (or before/after) programmes is itself a "No information" filler cell, so a row is always a contiguous run of cells to move over — scrolling the viewport by 30 minutes (one slot) only once the cursor cell touches the viewport's edge in that direction. A ±12-hour skip (next/prev-item actions) and a jump-to-now action (`REMOTE_0`) are also available, both clamped to the EPG retention/horizon range; past cells (end time already passed) render with dimmed label text. Python-created controls need absolute texture paths after any add/remove cycle (bare skin texture names stop resolving); draw order follows creation order with Python controls always on top of XML and no clipping, so the now-line is drawn last. Relayout — for a horizontal (time) scroll, a vertical (row) scroll, or a cursor move that needs a full rebuild — is always instant (no slide or fade animation: an earlier vertical slide/fade was dropped after user feedback that it felt like rubber-banding), following a hide→update→show sequence so no frame exposes stale text; the native channel list at id 500 keeps its own scroll behaviour. A target viewport of 10 rows × 3 hours at 1080p was validated against a real ~200-channel/6-hour dataset.

**Playback OSD and zapping**: a top-aligned info bar (channel number, logo, name, now-programme + progress + HH:MM–HH:MM, next-programme title) combined with a left-aligned two-pane Groups/Channels list (TiviMate layout); a zap-first variant with no list was prototyped and rejected. Up/Down (and Left/Right) on bare video open the list without changing the stream — there is no zap without an explicit OK on a channel row. Number entry zaps directly and commits after a 1.5-second idle timeout or OK, with digits shown large while entering. OK on bare video toggles the info bar, which auto-hides after 3 seconds. Back closes the list if open, else hides the bar if shown, else leaves playback. Script-driven playback with an own dialog on top requires `ActivateWindow(fullscreenvideo)` after `play()` (a short sleep first), or the dialog renders invisibly behind Home; the OSD is a `WindowXMLDialog` over the fullscreen-video window with translucent tinted-PNG panels leaving the video visible, and polls player-callback-set flags on a 1Hz thread for progress rather than relying on player events alone. Digit input is accepted via keyboard codes 0xF030-39, `ACTION_JUMP_SMS2..9` (142-149), and `ACTION_REMOTE_0..9` (58-67); EventServer numeric-action delivery was found unreliable in testing and JSON-RPC `Input.ExecuteAction` was used instead for prototype verification, but the shipped addon reads native input actions directly. A benign `Control N ... can't [focus]` log line appears whenever `<defaultcontrol>` points at a hidden list on load; the window must explicitly refocus the list when it opens.

**Channel overrides UX**: a context menu (Menu/context key) on a focused channel row — chosen over an inline "edit mode" toggle or a slide-in side panel, both prototyped and rejected, because the context-menu affordance is the one already native to Kodi and needs no new interaction model to learn. Menu entries: Renumber… (native numeric dialog; empty/cancel keeps the current value), Hide/Unhide, Add to/Remove from Favourites, Move (Favourites group only), Reset to provider default. A "Show hidden" toggle sits at the top of the Groups pane; when off, hidden rows are filtered from view entirely, when on they render dimmed with a marker. Favourites reordering is pick-up/drop: OK on Move starts it, Up/Down shift the row live, OK drops it in place, Back restores the original order. Every action applies immediately (no save step) and focus is explicitly returned to the edited row afterward, since Kodi's native context-menu handling otherwise resets focus to the window's default control.

**Providers and Provider Form**: two windows — a Providers list and a Provider Form used for both add and edit. Add Provider opens a native select dialog for kind (M3U playlist / Xtream Codes) before the kind-shaped form; kind is immutable once created (channel identity differs by kind) and shown read-only on edit. The Provider Form is a flat row list with an "Advanced" non-focusable heading separating advanced rows; each row shows a label and current value, and OK opens the appropriate native dialog (`xbmc.Keyboard` for text, masked for password; `Dialog().numeric` for numbers; `Dialog().select` for enums; `Dialog().browse` for local files). M3U rows: Name, Playlist (URL or local file), EPG URL override, Catch-up days default; Advanced: User-Agent, Catch-up correction, Number offset; Enabled. Xtream rows: Name, Server URL, Username, Password, EPG URL override, Catch-up days default; Advanced: Live Form (Auto/ts/m3u8), Catch-up URL form (Auto/path/query), User-Agent, Catch-up correction, Number offset; Enabled. Pasting a full `get.php?username=...&password=...` URL into the Xtream Server field auto-splits it into Server/Username/Password with a confirming toast. Buttons: Test connection, Save, Cancel (plus Delete when editing).

Validation runs only on Save and on Test: focus jumps to the first invalid row with hint text and a toast names the first error. Name auto-fills when blank (Xtream: host; M3U: last path segment sans extension, else host, else filename); duplicate names are allowed. M3U Playlist must be an `http(s)://` URL or an existing file path; Xtream Server must be `http(s)://host[:port]` with any path stripped; Username/Password are required; integer rows must be ≥ 0; correction hours are bounded −12..+12.

Test Connection runs on a background thread in the script process under a cancellable progress dialog with a 15-second timeout, and persists nothing regardless of outcome — Save never requires a passed Test. Xtream Test performs the real `player_api.php` login and shows status/expiry/max-and-active-connections/`allowed_output_formats`/live category count; M3U Test fetches and fully parses the real playlist and shows the exact channel count and whether an EPG URL was declared. A shared error catalogue (also used for `provider.last_error`) covers: Unreachable, Login rejected, Not an Xtream server, Not an M3U playlist, Timed out, File not found, HTTP `<code>`.

Save writes the row and returns to the Providers list. `config_version` is bumped, and a `refresh_request` queued, only for edits to kind/URL/host/credentials/EPG override or a disabled→enabled transition; edits to offsets, catch-up defaults, correction, Live Form, User-Agent, or name trigger no Refresh and simply re-render the list on return. Disabling a provider triggers no Refresh either — its channels drop from every listing immediately because queries filter on `provider.enabled` — and deletes nothing. Editing a provider that is mid-refresh is allowed; the `config_version` guard discards the stale in-flight result. A dirty form's Cancel/Back asks to discard changes; a clean form closes silently.

The Providers list shows, per row: name, kind badge, listable channel count, last-refresh relative time (or the `last_error` snippet), dimmed when disabled, and a refreshing indicator; Xtream rows additionally show an expiry date with a warning tint under 7 days remaining. OK edits; the context menu offers Refresh now, Enable/Disable, Move (pick-up/drop, writing `sort_order`), and Delete; top-level buttons are Add Provider and Refresh all.

Deleting a provider asks for confirmation naming what will be removed (channels, favourites, channel edits), then soft-deletes (`enabled=0` + `deleted_at`) and queues a Refresh so the service performs the cascade and Generation bump; a running Playback Session on that provider's channel is unaffected until the user leaves it (per the snapshot rule), and every query already hides `deleted_at` rows regardless of when the cascade actually runs.

First run (zero enabled providers, including immediately after deleting the last one) opens directly to the Providers list in an empty state with hint text and focus on Add Provider; Back exits the addon; startup autoplay is skipped when there are no listable channels.

**Search**: entered via Kodi's native keyboard dialog; results render on one screen with a Channels section (OK plays) and a Programmes section (OK opens the Programme info dialog). Matching is case-insensitive substring over Normalised Name (channels) and Programme title, restricted to listable channels — Stale and Hidden channels are excluded outright, and Programmes belonging to a non-listable channel never appear even if their title matches.

**Channel logos**: `logo_url` is passed straight through as ListItem art; Kodi's own texture cache handles caching. A missing or failed logo shows a bundled placeholder PNG. Kodimate does not maintain its own logo cache and never prefetches logos ahead of a screen needing them.

### Settings

Global, addon-wide knobs live in Kodi's own `settings.xml`-backed settings screen (opened via `Addon().openSettings()` from the main menu), not a bespoke WindowXML screen: Refresh interval (hours, default 12), Refresh on startup (on), Autoplay last channel (on), Channel-list overlay on autoplay (on), OSD auto-hide seconds (default 3), Number-entry commit delay (default 1.5s), Timezone correction (auto), Debug logging (off), and a "Manage providers…" button that opens the Providers window directly. Everything CRUD-shaped — providers themselves, and per-channel overrides — lives in Kodimate's own WindowXML screens instead, specifically because Kodi settings has a fixed slot count and no native list-CRUD affordance. EPG retention (fixed at 7 days) is not exposed as a setting in v1.

### Logging / i18n

All user-facing text is sourced from `strings.po` string ids from the first commit, even though only en_GB ships in v1 — there is no separate "add i18n later" step. Logging is split between the addon's normal operational log lines (visible at INFO) and a DEBUG tier (toggled in settings) that adds full player-callback traces; credentials are redacted in every log line that could otherwise expose them (Xtream username/password path segments and any embedded query parameters become `***`).

## Testing Decisions

The standing testing preference for Kodimate is a pure-Python core exercised with `pytest`, using hand-written fakes for `xbmc`/`xbmcgui`/`xbmcaddon` rather than real Kodi. Kodi-side automated JSON-RPC smoke tests are explicitly out of scope for v1 (per the map): there is no CI step that drives a live Kodi instance. This is a greenfield repository — there is no existing test suite or prior art to build on yet; the seams below are a proposal for the user to confirm before `to-tickets` decomposes them into concrete test tasks.

Proposed seams, highest-value first, kept to as few as possible:

1. **Ingest seam** — feed raw M3U text, a mocked Xtream `player_api.php` JSON response, and an XMLTV document (plain and gzip/lzma-wrapped) into the parsing/ingest functions, and assert on the resulting SQLite rows by querying the database directly (channel identity/Channel Key derivation, group assignment, Normalised Name computation, EPG match resolution, Stale marking across a second refresh with a channel removed, Effective Channel Number and Effective Catch-up Window computation). This is the highest-value seam because nearly every domain rule in the spec (Channel Key derivation, Stale/Override survival, EPG matching, catch-up window fallback) is expressible as pure data transformation observable purely through the database.
2. **Playback Session state machine** — drive the state machine with a fake `Player` that emits `onPlayBackError`/`onPlayBackStopped`/`onAVStarted`/`onPlayBackEnded` callbacks on a controlled schedule, and a fake HTTP probe returning a scripted status/timeout/exception, asserting on the sequence of Attempts, the resulting Failure Reason, and any persisted `learned_stream_format` change. This is the seam with the most subtle timing/ordering logic (30s/5s/3-attempt/backoff timers, probe-vs-no-probe branching, form-fallback persistence) and the one most likely to regress silently.
3. **Catch-up and Live URL builders** — pure functions taking a channel/provider row (or an equivalent plain dict) plus a requested time and returning the built URL string, covering every M3U catchup mode (`default`/`append`/`shift`/`flussonic`/`xc`/`vod`) and both Xtream forms (path and query), including timezone correction and template-variable substitution. These functions have no Kodi dependency at all and are the cheapest, highest-confidence tests to write.
4. **Refresh IPC / Generation handling** — a fake `Window`-property store standing in for `xbmcgui.Window(10000)`, driving the service's request/queue/complete cycle and asserting on the resulting `refreshing`/`db_generation`/`refresh_result.<id>` property values and on `config_version`-guarded discard-and-requeue behaviour, without a real second process.

A good test at any of these seams asserts on observable behaviour at the seam's boundary — rows a query returns, a URL string, a state-machine outcome, a property value — never on private internals (a specific SQL statement issued, a specific timer object, a specific thread). Fixtures are M3U files, XMLTV documents, and mocked Xtream JSON payloads checked into the repository; real provider credentials or real playlist URLs are never used as fixtures or committed anywhere.

## Out of Scope

Carried forward verbatim from the map (issue #1) plus its noted follow-up items:

- Kodi-side automated JSON-RPC smoke tests (the test strategy is pytest-with-stubs only).
- Live pause / timeshift buffering (would require a local proxy, which ADR 0006 explicitly avoids).
- Xtream VOD / Series browsing.
- Local recording (DVR).
- Multi-view / picture-in-picture; parental lock.
- Cross-provider channel merge and stream failover.
- Kodi 20 Nexus and older; `kodi-six` compatibility shims.
- IPTV Simple Client / Kodi PVR API integration of any kind.

Post-v1 follow-up items noted on the map for a future map, not this effort:

- Stream stall detection (playing, no callback firing, `getTime()` frozen) and a per-channel "last failed" badge.
- Catch-up extras: URL-rebuild seeking when the underlying stream is otherwise unseekable, per-programme resume position, and an arbitrary-time picker for archive content on channels without matching EPG data.

## Further Notes

**ADR index** (`docs/adr/`):
- 0001 — Channel identity, Stale channels, and Overrides table
- 0002 — Provider credentials stored plaintext in SQLite
- 0003 — Service is the sole writer of Provider-derived tables; SQLite WAL; live Playback Session holds a Channel snapshot
- 0004 — Own WindowXML UI instead of Kodi PVR / IPTV Simple Client
- 0005 — SQLite as the single store for Providers, Channels, and EPG
- 0006 — Direct `xbmc.Player` playback of TS/HLS, no inputstream addon or local proxy

**Reference material** (not merged, kept as throwaway prototypes/research to consult during implementation, not to build on top of directly):
- `proto/epg-guide-grid` — the guide grid rendering prototype (hybrid control-pool approach) referenced under UI windows above.
- `proto/playback-osd` — the OSD/zapping prototype (top bar + Groups/Channels pane) referenced under UI windows above.
- `proto/channel-overrides` — the three renumber/favourites UX variants (A/B/C), of which variant A (context menu) was adopted.
- `research/xtream-codes-api` (`docs/research/xtream-codes-api.md`) — Xtream Codes `player_api.php`/`xmltv.php`/timeshift API surface.
- `research/m3u-catchup-conventions` (`docs/research/m3u-catchup-conventions.md`) — M3U catchup attribute semantics and template-variable table, `pvr.iptvsimple`-sourced; TiviMate-specific claims flagged there as inferred, not confirmed.
- `research/kodi-own-ui-addon-api` (`docs/research/kodi-own-ui-addon-api.md`) — `script.plexmod` structure, `xbmc.Player`/ListItem header behaviour, service lifecycle, dev-loop JSON-RPC/EventServer facts, XMLTV-at-scale and `sqlite3` availability confirmation.
- `docs/dev-loop.md` — the full local dev-loop reference (paths, ports, `scripts/dev/*` commands, verified facts, and one gotcha in `deploy.sh`'s version-extraction regex).
- `script.plexmod` (installed locally, `github.com/pannal/plex-for-kodi`) is the reference pattern Kodimate's own-UI approach is built on and should be consulted directly for any WindowXML/kodigui-pattern implementation questions not already answered by the research above.

**Conflicts/ambiguities resolved while assembling this spec:**
- Issue #4's research proposed enabling Kodi's HTTP webserver/remote-control-via-HTTP for the dev loop; issue #5's actual resolution instead uses the JSON-RPC TCP port (9090) and the EventServer UDP port (9777), with the HTTP webserver left disabled throughout. The later, more specific ticket (#5) wins; this spec's dev-loop description follows #5.
- Issue #7's OSD prototype leaves Back's exact behaviour on bare video (with no list or bar open) as an explicit assumption ("returns to the previous screen... not explicitly asked"), not a confirmed decision; this spec states it as the intended v1 behaviour but flags it here as the one interaction rule that was never independently grilled.
- Issue #9 (Catch-up UX) and issue #14 (Provider onboarding) both mention `catchup_url_form`; #14 additionally exposes it as a user-editable Auto/path/query field on the Provider Form, refining #9's "persisted whichever last succeeded" description. Both are consistent; #14's UI-facing detail is treated as the more specific elaboration, not a conflict.
- No other decisions across the map, the twelve resolved tickets, the ADRs, and the design docs were found to conflict; where a topic is covered in more than one place (e.g. Stale-channel behaviour appears in both #8 and #13), this spec reconciles them as the same decision restated at different levels of detail rather than treating them as competing answers.
