# Kodimate

Kodimate (`script.kodimate`) is a Kodi addon providing a TiviMate-style IPTV client with its own UI. This context defines the vocabulary for channels, EPG, and playback within that UI.

## Language

**Provider**:
A configured source of Channels and EPG. Two kinds: M3U Provider (playlist URL/file) and Xtream Provider (Xtream Codes server + username + password). Many may be configured at once.
_Avoid_: Source, playlist, account

**M3U Provider**:
A Provider defined by a playlist URL or file.

**Xtream Provider**:
A Provider defined by an Xtream Codes server address, username, and password.

**Channel**:
A live stream offered by one Provider. The same channel offered by two Providers is two separate Channels; Channels are never merged across Providers. Each Channel has a stable **Channel Key** identifying it across Refreshes.
_Avoid_: Stream

**Channel Key**:
The stable identity of a Channel within its Provider. For an Xtream Provider, the provider's stream id. For an M3U Provider, the `tvg-id` when present and unique in the playlist; otherwise the stream URL with scheme and query string stripped (host and path); if that still collides, the full URL.
_Avoid_: id, uid

**Stale**:
The state of a Channel absent from its Provider's latest Refresh. Stale Channels are excluded from lists, Guide, and Zapping but keep their Overrides; a Channel continuously Stale for 7 days is purged during Refresh.
_Avoid_: deleted, orphaned

**Override**:
A user-made change to a Channel that survives Refresh: Channel Number, Hidden, Favourite, and Favourite order. Keyed by Channel Key. There is no custom name or logo.
_Avoid_: customisation, user settings

**Hidden**:
An Override that excludes a Channel from list, Guide, and Zapping while keeping it configured.

**Group**:
A Provider-supplied category of Channels (M3U `group-title`, Xtream live category), identified by (Provider, name). Each Channel belongs to exactly one Group. An M3U `group-title` containing `;` uses only its first segment. A Group with no non-Stale Channels is not shown.
_Avoid_: Category

**Channel Number**:
The number shown and used for zapping a Channel. Comes from the Provider (tvg-chno / Xtream num) if present, otherwise from Provider order; the user may override it, and Providers may have number offsets applied. Numbers are labels, not keys: duplicates are allowed. Number-entry Zapping selects the first Channel in list order (Provider order, then Channel order within Provider).

**Guide**:
The EPG grid view showing channels against a timeline.
_Avoid_: EPG grid, TV guide

**Programme**:
One scheduled broadcast on a Channel, keyed by its EPG Source channel id and start time, with title, subtitle, description, start, end, icon, category, and catch-up id, sourced from XMLTV or Xtream EPG.
_Avoid_: Program, show, event

**EPG Source**:
Where Programmes come from for a given Provider: Xtream xmltv, a playlist-declared XMLTV URL, or a user override XMLTV URL that replaces the Provider's own source. Each EPG Source belongs to exactly one Provider. At Refresh, each Channel is matched to an EPG Source channel by `tvg-id`/`epg_channel_id` first, falling back to **Normalised Name**. A Provider with no EPG Source still shows its Channels in the Guide, with a "No information" placeholder.

**Normalised Name**:
A Channel name lowercased, with non-alphanumeric characters removed and a trailing HD/FHD/UHD/4K suffix stripped. Used only for EPG matching.

**Catch-up**:
Playing a past Programme from the Provider's archive. The canonical term for this feature; "archive" and "timeshift" are used only when describing the Provider's own boundary/terminology.
_Avoid_: Archive, timeshift (except when referring to Provider-side terminology)

**Catch-up Window**:
The number of days back a Channel supports Catch-up. Set per-Channel; if absent, falls back to the Provider's default. An Xtream Provider's `tv_archive=0` means no Catch-up regardless of any duration value. A Channel value always beats the Provider default. There is no user-configurable cap.

**Favourite**:
A user-marked Channel, held in a single flat user-ordered list; there are no multiple lists.
_Avoid_: Bookmark

**Zapping**:
Switching Channels during playback, via up/down navigation or number entry.
_Avoid_: Channel switching

**OSD**:
The on-screen display shown over live video, presenting channel and programme information.

**Refresh**:
Re-fetching a Provider's Channels and EPG.
_Avoid_: Sync, reload
