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
A live stream offered by one Provider. The same channel offered by two Providers is two separate Channels; Channels are never merged across Providers.
_Avoid_: Stream

**Group**:
A Provider-supplied category of Channels (M3U `group-title`, Xtream live category).
_Avoid_: Category

**Channel Number**:
The number shown and used for zapping a Channel. Comes from the Provider (tvg-chno / Xtream num) if present, otherwise from Provider order; the user may override it, and Providers may have number offsets applied.

**Guide**:
The EPG grid view showing channels against a timeline.
_Avoid_: EPG grid, TV guide

**Programme**:
One scheduled broadcast on a Channel, with a start and end time, sourced from XMLTV or Xtream EPG.
_Avoid_: Program, show, event

**EPG Source**:
Where Programmes come from for a given Provider: Xtream xmltv, a playlist-declared XMLTV URL, or a user override XMLTV URL.

**Catch-up**:
Playing a past Programme from the Provider's archive. The canonical term for this feature; "archive" and "timeshift" are used only when describing the Provider's own boundary/terminology.
_Avoid_: Archive, timeshift (except when referring to Provider-side terminology)

**Catch-up Window**:
The number of days back a Channel supports Catch-up.

**Favourite**:
A user-marked Channel.
_Avoid_: Bookmark

**Zapping**:
Switching Channels during playback, via up/down navigation or number entry.
_Avoid_: Channel switching

**OSD**:
The on-screen display shown over live video, presenting channel and programme information.

**Refresh**:
Re-fetching a Provider's Channels and EPG.
_Avoid_: Sync, reload
