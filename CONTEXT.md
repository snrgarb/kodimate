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

**Provider Form**:
The screen for adding or editing one Provider. Its fields depend on the Provider's kind, which is chosen when the Provider is created and never changes afterwards.
_Avoid_: settings page, wizard

**Test Connection**:
An action on the Provider Form that checks the entered details against the Provider without saving anything: for an Xtream Provider, that the credentials are accepted; for an M3U Provider, that the playlist can be fetched and parsed. Its outcome never blocks saving.
_Avoid_: verify, validate

**Disabled**:
The state of a Provider the user has switched off. Its Channels are excluded from lists, Guide, Zapping, and Favourites but nothing is deleted; re-enabling triggers a Refresh.
_Avoid_: paused, inactive

**Deleted**:
The state of a Provider the user has removed but whose Channels, Groups, Programmes, and Overrides have not yet been purged. A Deleted Provider and everything under it is invisible everywhere; the purge happens in the background.
_Avoid_: removed, archived

**Channel**:
A live stream offered by one Provider. The same channel offered by two Providers is two separate Channels; Channels are never merged across Providers. Each Channel has a stable **Channel Key** identifying it across Refreshes.
_Avoid_: Stream

**Channel Key**:
The stable identity of a Channel within its Provider. For an Xtream Provider, the provider's stream id. For an M3U Provider, the `tvg-id` when present and unique in the playlist; otherwise the stream URL with scheme and query string stripped (host and path); if that still collides, the full URL.
_Avoid_: id, uid

**Stale**:
The state of a Channel absent from its Provider's latest Refresh. Stale Channels are excluded from lists, Guide, and Zapping but keep their Overrides; a Channel continuously Stale for 7 days is purged during Refresh. A Channel that goes Stale while playing keeps playing until the user leaves it.
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

**Live TV view**:
The screen the addon opens into after startup autoplay: an Icon rail, a slide-out Groups panel, the Guide, and a Programme detail strip above it. Replaces the former separate channel list and home menu.
_Avoid_: channel list, home screen, main menu

**Icon rail**:
The always-visible strip of destinations (Live TV, Catch-up, Settings) at the edge of the Live TV view. Highlights the current destination and never steals focus when the view opens. 150 px wide, icons with labels beneath, never hidden or slid.
_Avoid_: sidebar, home menu

**Groups panel**:
The overlay drawer that slides out on Left from the Live TV view's channel column, over the channel column, dimming the rest of the view (except the rail) while open. Its header shows the active filter's name with a filter glyph; below it lists the active filter's Channels (number, logo, name). OK on a Channel row focuses that Channel in the channel column and closes the panel. OK on the header opens the Groups list: each Provider's Groups under a collapsible header, plus a flat All channels and Favourites at the top and a show-hidden toggle at the foot. Picking a Group re-lists the panel's Channels for that filter without closing it. Back from the Groups list returns to the Channel list (panel stays open); Back from the Channel list closes the panel without changing the filter.
_Avoid_: group picker, Groups pane
Accepted alternate: **Groups drawer**.

**Guide**:
The EPG grid inside the Live TV view, showing Channels down the side against a scrolling timeline of Programmes.
_Avoid_: EPG grid, TV guide

**Channel column**:
The Guide's list of Channels, one per row with number, logo, and name; together with the programme cells it forms the Guide grid.
_Avoid_: Channel list (its name before the Guide and the channel list merged into the Live TV view)

**Programme detail strip**:
The strip across the top of the Live TV view showing the focused Channel's logo and name, the focused Programme's title, times, duration, progress and remaining time, a short description, and LIVE/HD/Catch-up badges; follows the focused row and cursor cell; shows "No information" when there is no Programme.
_Avoid_: Now strip

**Remote-hint bar**:
The bar along the bottom of the Live TV view listing what OK, Back, Left/Right, Info and long-press do in the current focus zone; shown only while browsing, hidden while the Groups drawer or Playback is up.

**Programme**:
One scheduled broadcast on a Channel, keyed by its EPG Source channel id and start time, with title, subtitle, description, start, end, icon, category, and catch-up id, sourced from XMLTV or Xtream EPG.
_Avoid_: Program, show, event

**EPG Source**:
Where Programmes come from for a given Provider: Xtream xmltv, a playlist-declared XMLTV URL, or a user override XMLTV URL that replaces the Provider's own source. Each EPG Source belongs to exactly one Provider. At Refresh, each Channel is matched to an EPG Source channel by `tvg-id`/`epg_channel_id` first, falling back to **Normalised Name**. A Provider with no EPG Source still shows its Channels in the Guide, with a "No information" placeholder.

**Normalised Name**:
A Channel name lowercased, with non-alphanumeric characters removed and a trailing HD/FHD/UHD/4K suffix stripped. Used only for EPG matching.

**Catch-up**:
Playing a past Programme from the Provider's archive. The canonical term for this feature; "archive" and "timeshift" are used only when describing the Provider's own boundary/terminology. A Programme is playable via Catch-up when its Channel has a Catch-up Window, it started within that window, and it has started (in-progress Programmes play as Start Over). Catch-up is programme-driven: a Channel with no Programmes offers no Catch-up.
_Avoid_: Archive, timeshift (except when referring to Provider-side terminology)

**Catch-up Window**:
The number of days back a Channel supports Catch-up. Set per-Channel; if absent, falls back to the Provider's default. An Xtream Provider's `tv_archive=0` means no Catch-up regardless of any duration value. A Channel value always beats the Provider default. There is no user-configurable cap.

**Behind live**:
A live Playback Session's position lagging real time, whether inside the player's own buffer (native seek/pause) or via Catch-up. A seek or pause-resume that lands beyond the buffer rebuilds a Catch-up URL at the target position.

**Start Over**:
Playing the currently airing Programme from its beginning via Catch-up. A special case of Catch-up, not a separate feature.
_Avoid_: restart, replay

**Programme info dialog**:
The single dialog showing a Programme's title, times, and description with actions (Play Catch-up, Watch live). Opened from the Guide, the Catch-up browser, and the OSD.
_Avoid_: details popup, EPG popup

**Catch-up browser**:
The screen listing past Programmes per Channel, grouped by day, for Channels with a Catch-up Window.
_Avoid_: archive browser, replay list

**Origin screen**:
The screen a playback session was started from (Live TV view, Catch-up browser); Back from playback returns there.

**Favourite**:
A user-marked Channel, held in a single flat user-ordered list; there are no multiple lists.
_Avoid_: Bookmark

**Zapping**:
Switching Channels during playback, via up/down navigation or number entry.
_Avoid_: Channel switching

**OSD**:
The on-screen display shown over live video, presenting channel and programme information.

**Playback Session**:
One Channel's playback from the moment it is selected (by Zapping, Catch-up, or startup autoplay) until the user leaves it or selects another Channel. Moves through the states Connecting, Playing, Reconnecting, and Failed. A Playback Session keeps the Channel as it was when the session started; a Refresh never changes or interrupts a running session.
_Avoid_: stream session, play session

**Connecting**:
The Playback Session state from selection until video is confirmed to be playing. Shown as black video with a spinner and the OSD bar for the selected Channel.

**Playing**:
The Playback Session state in which video is confirmed to be playing.

**Reconnecting**:
The Playback Session state entered when a Playing session's stream stops without user action. A bounded number of Attempts are made to resume; if none succeeds the session becomes Failed.

**Failed**:
The terminal Playback Session state after every Attempt (including any Live Form fallback) has failed. The user stays in the player with the Failure Reason shown and the channel list open; selecting the same Channel again starts a fresh Playback Session.

**Attempt**:
One try at starting a Channel's stream within a Playback Session. Attempts differ only by Live Form and timing; the Channel's headers are applied afresh on every Attempt.

**Live Form**:
The stream URL variant used for an Xtream Provider's live Channels: `ts` or `m3u8`. Each Xtream Provider has one Live Form in effect: the user's override if set, otherwise the form learned from a successful fallback, otherwise `ts`. M3U Providers have no Live Form.
_Avoid_: stream format, output format, container

**Failure Reason**:
The user-facing category of a Failed Playback Session: Unavailable (stream could not be started or resumed), Login rejected (the Provider refused the credentials), or Connection limit (the Provider refused because too many connections are in use).
_Avoid_: error code, HTTP status

**Refresh**:
Re-fetching a Provider's Channels and EPG.
_Avoid_: Sync, reload

**Generation**:
A counter that advances each time a Refresh commits new Channels or Programmes. Screens re-render when the Generation they were drawn from is no longer current.
_Avoid_: version, revision, timestamp
