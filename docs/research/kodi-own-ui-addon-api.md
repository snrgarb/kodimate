# Kodi 21 Omega / 22 Piers Python API for own-UI addons

Research for wayfinder ticket #4 (part of map #1). Target: xbmc.python API v3.0 (Kodi 20 Nexus+, covers 21 Omega and 22 Piers). Primary sources: local install of `script.plexmod` v1.3.19 at `~/Library/Application Support/Kodi/addons/script.plexmod` (a real, shipping WindowXML addon), local Kodi.app 21/22 binary/Python inspection on this Mac, Kodi's official dev-kit docs (`xbmc.github.io/docs.kodi.tv`, `codedocs.xyz`), the Kodi wiki, and the `inputstream.adaptive` addon's own GitHub wiki (the closest thing to primary documentation for inputstream properties, since Kodi's core `ListItem` docs don't enumerate addon-specific property names).

---

## 1. How script.plexmod structures its own UI

### 1.0 addon.xml extension points

`addon.xml` (local install) declares one addon id with four extension points:

- `xbmc.python.script` library=`default.py` — main UI entry point (launched via `RunScript`)
- `xbmc.python.pluginsource` library=`plugin.py` — a `plugin://` endpoint for library-node/browse integration
- `xbmc.ui.screensaver` library=`screensaver.py`
- `xbmc.service` library=`service.py` — background service, auto-started by Kodi

Requires `xbmc.python` v3.0.0 plus vendored `script.module.requests`, `script.module.six`, `script.module.kodi-six`. Code uses `from kodi_six import xbmc, xbmcgui` throughout for py2/py3 compat shimming (a legacy concern not relevant for a new py3-only addon, but explains an import pattern you'll see if reading the source).

### 1.1 WindowXML base classes and window stacking

All defined in the single file `lib/windows/kodigui.py` (~1428 lines):

- **`BaseFunctions`** (`kodigui.py:21`, plain mixin) — provides classmethods `open(**kwargs)` (constructs the window, calls `.modal()`, blocks) and `create(show=True, **kwargs)` (constructs, calls `.show()`, returns immediately — used for non-blocking overlays like the busy spinner). Windows are **instantiated directly** with `xbmcgui.WindowXML`'s usual `(filename, script_path, custom_skin_theme, resolution)` args — there is no central window-ID registry.
  - `activate()` calls `xbmc.executebuiltin('ReplaceWindow({id})')` using the window's last known id.
  - `BaseFunctions.lastWinID` / `lastDialogID` are **class-level** attributes tracking "current window," updated in `_onInit()`.

- **`XMLBase`** (`kodigui.py:127`) — implements `onInit(count=0)`. Every compiled skin XML file is required to contain a sentinel `<control type="label" id="666"><visible>false</visible></control>`; `onInit` calls `self.getControl(666)` to verify the XML actually parsed, retrying up to 8 times (250ms apart) and triggering skin-template recompilation (see §1.3) on persistent failure.

- **`BaseWindow(XMLBase, xbmcgui.WindowXML, BaseFunctions)`** (`kodigui.py:197`) — base for full-screen windows.
  - First-init vs re-init split: on first `onInit`, calls subclass hook `onFirstInit()`; on subsequent inits (Kodi re-inits XML windows on every `ActivateWindow`), calls `onReInit()` instead. This is the primary extension point concrete windows implement.
  - `setProperty(key, value)` (`kodigui.py:319`) writes to **both** `xbmcgui.Window(self._winID)` (global window-id-scoped, readable by skin XML from anywhere) **and** the native `WindowXML.setProperty` — a deliberate dual-write.
  - `show(aggressive=False)` (`kodigui.py:379`) wraps native `show()` with polling/retry against `xbmcgui.getCurrentWindowDialogId()`/`getCurrentWindowId()`, because Kodi silently no-ops `ActivateWindow` when a modal dialog is already active; plexmod loops re-issuing `show()` for ~2-4s to work around it.
  - Registers on a global pub/sub bus (`plexapp.util.APP.on('close.windows', ...)`) so any code can broadcast "close all windows."

- **`BaseDialog(XMLBase, xbmcgui.WindowXMLDialog, BaseFunctions)`** (`kodigui.py:427`) — analogous, for overlay dialogs (13000+ id range) shown on top of the current window (e.g. Busy spinner, OSD). Same dual-property-write and pub/sub pattern via `close.dialogs`.

- **`ControlledBase`** (`kodigui.py:496`) — replaces Kodi's native blocking `doModal()` with a Python-level polling loop:
  ```python
  class ControlledBase:
      def doModal(self, aggressive=False):
          self.show(aggressive=aggressive)
          self.wait()
      def wait(self):
          while not self._closing and not MONITOR.waitFor():
              pass
      def close(self):
          self._closing = True
  ```
  This lets any Python code (event handlers, background threads) request an async close via `doClose()` without needing Kodi's native modal-exit mechanism.

- **`ControlledWindow(ControlledBase, BaseWindow)`** (`kodigui.py:509`) — adds default `onAction`: `ACTION_PREVIOUS_MENU`/`ACTION_NAV_BACK` → `doClose()`. Most ordinary full-screen windows subclass this (e.g. `VideoPlayerWindow`).
- **`ControlledDialog(ControlledBase, BaseDialog)`** (`kodigui.py:521`) — dialog equivalent.

**Window stacking/navigation**: there is **no central window-manager/stack class**. Instead:
- `lib/windows/windowutils.py` has a module-level singleton `HOME = None`, set by `lib/main.py` at startup to the one `HomeWindow` instance; mixins call `HOME.show()` to navigate back to the shell.
- `lib/windows/opener.py`'s `handleOpen(winclass, **kwargs)` does `w = winclass.open(**kwargs)` (blocking modal), then returns `w.exitCommand`. Windows set `self.exitCommand` before closing; if it's a `'HOME...'` string, the caller propagates the close so the whole stack unwinds back to Home. This "exitCommand bubbling" is plexmod's stand-in for a navigation stack, layered on top of native Kodi 12000/13000-range window/dialog show/doModal behavior.

### 1.2 ManagedControlList pattern (dynamic control creation)

Also in `kodigui.py`, this is the reusable core that binds a Python list of rich items to a skin `<control type="list">`/`panel`/`fixedlist`.

- **`ManagedListItem`** (`kodigui.py:557`) — wraps an `xbmcgui.ListItem` plus `label`, `label2`, `iconImage`, `thumbnailImage`, `path`, `dataSource` (arbitrary Python object tied to the row, e.g. a media object), and a `properties` dict. `setProperty`/`setProperties` write into both the Python dict and the underlying `xbmcgui.ListItem`, and register the key into the owning list's tracked property-key set so it gets blanked on other/recycled items (since Kodi list items don't share a schema).

- **`ManagedControlList`** (`kodigui.py:719`) — wraps `window.getControl(control_id)`: `ManagedControlList(window, control_id, max_view_index, data_source=None)`. `__getattr__` proxies to the underlying native control for anything not explicitly defined.
  - `addItem(mli)` / `addItems([...])` — append and push into the native control.
  - `replaceItems(managed_items)` (`kodigui.py:823`) — the "rebind a whole new dataset" method: invalidates old items, resizes the native control up/down to match new length, then patches labels/art/props into (possibly reused) slots — a diff-and-patch approach avoiding a full `control.reset()`.
  - `getSelectedItem()`/`getSelectedPos()`/`setSelectedItem*` — selection/focus tracking via native `control.getSelectedPosition()`/`selectItem()`.
  - `getViewPosition()` reads `xbmc.getInfoLabel('Container({id}).Position')` for viewport-aware paging (used for lazy-loading rows).
  - Behaves like a Python sequence: `size()`/`__len__`/`__iter__`/`__getitem__` (slicing supported).

  Usage convention: one `ManagedControlList` per skin list-control id, constructed in `onFirstInit`, keyed by class-level integer constants (e.g. `home.py`: `self.sectionList = kodigui.ManagedControlList(self, self.SECTION_LIST_ID, 7)`, where `7` is a viewport-size hint).

### 1.3 Skin XML organization

Directory convention: `resources/skins/<skin-name>/<resolution>/`. Here skin name is `Main` (matches `theme = 'Main'` class attr on every window class) and resolution is `1080i` (matches `res = '1080i'`). `resources/skins/Main/skin.xml` declares `<defaultresolution>1080i</defaultresolution>` — the minimal skin manifest WindowXML requires even for a script addon.

File naming: every window/dialog XML is `script-plex-<name>.xml` (e.g. `script-plex-home.xml`, `script-plex-video_player.xml`, `script-plex-busy.xml`), matching each Python class's `xmlFile` attribute exactly. `resources/skins/Main/media/script.plex/` holds textures referenced as `script.plex/<file>`.

**No traditional Kodi `Includes.xml`/`Font.xml`/`Variables.xml` at skin root.** Instead plexmod compiles its skin XML from a template pipeline: `resources/skins/Main/1080i/templates/*.xml.tpl`, written using the vendored **`ibis`** templating engine (`lib/_included_packages/ibis/`), with Jinja2-like `{% extends %}`/`{% block %}`/`{% include %}` and resolution-scaling helper calls (`{{ vperc(vscale(150)) }}`). `templates/includes/*.xml.tpl` hold reusable fragments. These compile at build/startup time into the flat XML Kodi actually loads; `XMLBase.onInit`'s failure path explicitly triggers recompilation if a compiled XML is stale/broken (control 666 missing). **This is an addon-specific build step, not a Kodi platform feature** — a new addon can skip it and hand-write flat XML with native Kodi `<include>`/`<font>` mechanisms instead.

Control-id convention: skin XML control ids are plain integers chosen by convention per window (e.g. list ids `400`-`423` for home hub rows, `101` for the section list — see `script-plex-home.xml`), and the **Python window class re-declares each id as a class constant** (`home.py`: `SECTION_LIST_ID = 101`, `HUB_AR16X9_00 = 400`, `HUB_POSTER_01 = 401`, …). There is no codegen linking skin XML to Python — this is manual convention (e.g. `HUB_POSTER_NN = 4NN` makes the offset visually obvious), and every window XML ends its `<controls>` block with the `id=666` sentinel described in §1.1.

### 1.4 Player wrapper around xbmc.Player

`lib/player.py` (2822 lines). **`PlexPlayer(xbmc.Player, signalsmixin.SignalsMixin)`** (`player.py:1869`) is a single global singleton (`player.PLAYER`). It multiply-inherits `xbmc.Player` (for native `on*` callback overrides) and a custom `SignalsMixin` (vendored `plexnet.signalsmixin`) giving it `.on(event, cb)`/`.off(...)`/`.trigger(event, **kwargs)` — an **internal pub/sub event bus independent of Kodi's callback mechanism**. This bus, not direct method calls, is the real integration seam other windows use.

Overridden native callbacks (`player.py:2512-2660`): `onPrePlayStarted`, `onPlayBackStarted`, `onAVChange`, `onAVStarted`, `onPlayBackPaused`, `onPlayBackResumed`, `onPlayBackStopped`, `onPlayBackEnded`, `onPlayBackSeek(time, offset)`, `onPlayBackError`, `onPlayBackFailed`, plus custom (non-native) events `onVideoWindowOpened`/`onVideoWindowClosed`/`onVideoOSD`. Each override: early-returns if `not self.sessionID` (ignore playback plexmod didn't initiate), logs, `self.trigger('<event>')` on the internal bus (e.g. `'playback.started'`, `'av.started'`, `'playback.failed'`), then delegates to `self.handler` — a strategy-pattern object (`BasePlayerHandler` base, concrete `SeekPlayerHandler` for video, `AudioPlayerHandler`, `BGMPlayerHandler`) swapped depending on current playback mode.

**OSD/video-window coordination is signal-based, not window-property polling**: `VideoPlayerWindow` (`lib/windows/videoplayer.py:85`, a `ControlledWindow`) subscribes in init:
```python
player.PLAYER.on('session.ended', self.sessionEnded)
player.PLAYER.on('videowindow.closed', self.videoWindowClosed)
player.PLAYER.on('av.started', self.playerPlaybackStarted)
player.PLAYER.on('starting.video', self.onVideoStarting)
player.PLAYER.on('started.video', self.onVideoStarted)
player.PLAYER.on('changed.video', self.onVideoChanged)
player.PLAYER.on('post.play', self.postPlay)
player.PLAYER.on('playback.failed', self.setPlaybackFailed)
```
and unsubscribes symmetrically at close. The window calls `player.PLAYER.playVideo(...)` to start playback, then reacts to emitted signals to update OSD state/trigger next-episode UI. **Architectural lesson: decouple the `xbmc.Player` subclass from specific window instances via an internal pub/sub bus**, since multiple windows (Home included, for a "now playing" status button) need to react to the same playback events.

### 1.5 Service lifecycle and script↔service IPC

`service.py` is a thin bootstrap loop calling `lib/service_runner.py:main()`; if that returns truthy (code-update detected) it does a live `importlib.reload(runner)` and loops again — a self-updating service pattern.

`service_runner.py:main()`: creates `xbmc.Monitor()`, sets a global "service.started" flag (see IPC below), optionally auto-launches the script (`xbmc.executebuiltin('RunScript(script.plexmod,...)')`) for kiosk mode, then runs `while not MONITOR.abortRequested(): ...` — the classic Kodi service main-loop shape.

`lib/monitor.py`'s **`UtilityMonitor(xbmc.Monitor, signalsmixin.SignalsMixin)`** is the script-side (not service-side) monitor singleton (`MONITOR`), used throughout the UI for `waitFor()`/`abortRequested()` polling, and overrides `onNotification` to detect a custom `NotifyAll('script.plexmod', 'RESTORE', ...)` broadcast (sent when a second launch attempt detects the addon already running) to refocus the running instance instead of duplicating it. Also overrides `onScreensaverActivated/Deactivated`, `System.OnSleep/OnWake/OnQuit` to react to system events.

**Script↔service IPC mechanism**: `lib/properties_core.py` implements the cross-process channel via **`xbmcgui.Window(10000)`** (Kodi's Home window, alive for the whole GUI session) properties:
```python
def _getGlobalProperty(key, base='script.plex.{0}'):
    return xbmc.getInfoLabel('Window(10000).Property({0})'.format(base.format(key)))
def _setGlobalProperty(key, val, base='script.plex.{0}'):
    xbmcgui.Window(10000).setProperty(base.format(key), val)
```
Window 10000 properties are process-wide/global — the standard Kodi trick for cross-addon-process shared state (script.py and service.py run as separate Python interpreters). `lib/properties.py` builds a richer blocking wait-for-value API on top (`setGlobalProperty(..., wait=True)`, `getGlobalProperty(..., wait=True, timeout=...)`) using a `MONITOR.waitForAbort(interval)` poll loop as a crude condition-variable, used for startup handshakes between the kiosk-launched service and the script instance. Keys are namespaced `script.plex.<key>` to avoid collisions with other addons.

Note: `BaseWindow.setProperty` (§1.1) uses the same `xbmcgui.Window(<id>).setProperty` pattern but scoped to the **window's own id** (UI state, read by that window's own skin XML) — a second, separate tier from the globally-scoped Window(10000) IPC tier. No sqlite or file-based IPC was found in use between service and script; sqlite (where used) is for local caching only, not cross-process coordination.

### Summary — directly reusable patterns for a new own-UI addon

1. A `BaseWindow`/`BaseDialog`/`ControlledWindow`/`ControlledDialog` hierarchy in one `kodigui.py`-style module is worth adapting near-verbatim: it solves real WindowXML pain points (first-init vs re-init, Monitor-driven modal wait instead of relying on native `doModal`, dual window/control property writes, the control-id-666 load-integrity check).
2. `ManagedControlList`/`ManagedListItem` is a clean, general-purpose "bind a Python list to a native Kodi list/panel control" abstraction worth lifting wholesale.
3. Skin XML organization (`resources/skins/<skin>/<res>/script-<addon>-<window>.xml`, class-constant control ids mirroring skin ids) is straightforward to replicate without adopting the `ibis` template-compilation step, which is an addon-specific optimization, not a Kodi requirement.
4. Player integration should go through an internal pub/sub bus (`on`/`off`/`trigger`) rather than tight-coupling the `xbmc.Player` subclass to specific windows.
5. Service↔script IPC via `xbmcgui.Window(10000).setProperty/getProperty` (namespaced keys) with polled wait-loops is the standard, low-dependency coordination mechanism; no dedicated Kodi "IPC API" exists beyond this convention.

---

## 2. xbmc.Player().play() and stream setup

Source: [Kodi dev-kit Player docs](https://xbmc.github.io/docs.kodi.tv/master/kodi-dev-kit/group__python___player.html), [ListItem class docs](https://xbmc.github.io/docs.kodi.tv/master/kodi-base/d4/d73/class_x_b_m_c_addon_1_1xbmcgui_1_1_list_item.html), [inputstream.adaptive Integration wiki](https://github.com/xbmc/inputstream.adaptive/wiki/Integration) (addon-maintainer documentation; the core ListItem API docs don't themselves enumerate inputstream-specific property names).

### 2.1 play() signature

`xbmc.Player().play(item='', listitem=None, windowed=False, startpos=-1)`:
- `item` — filename/URL/playlist (optional; if omitted, plays current playlist item)
- `listitem` — `xbmcgui.ListItem` carrying infolabels/properties for the played item
- `windowed` — play windowed vs. user preference (default False)
- `startpos` — starting playlist position (default -1)

### 2.2 Custom HTTP headers — two mechanisms

- **Legacy pipe-suffix on the URL**: `"{url}|User-Agent={value}&Referer={value}"` passed to `ListItem.setPath()`/the play item string. Still works in Kodi 21/22 for plain FFmpeg-demuxed HTTP playback (no inputstream.adaptive), but the inputstream.adaptive wiki explicitly discourages it for adaptive-manifest playback: *"Never use pipe '|' char to inject HTTP headers along an URL address such as the manifest... it may work in some cases, [but] it is NOT supported."*
- **inputstream.adaptive property-based headers (current mechanism)**: `listitem.setProperty('inputstream.adaptive.stream_headers', 'headername=encoded_value&...')`, values URL-encoded. Version differences (per the Integration wiki):
  - Kodi ≤19: `stream_headers` applies to both manifest and segment requests.
  - Kodi 20: `stream_headers` still applies to both, but a new `manifest_headers` property is added and preferred for manifest requests.
  - Kodi 21+ (our target): `stream_headers` applies to stream/segment requests only; use `manifest_headers` for the manifest request.
  - Kodi 22+ (our target): a new `common_headers` property applies headers to *all* requests (manifest + streams) — simplest option going forward.

### 2.3 inputstream / manifest_type / mimetype properties

```python
listitem = xbmcgui.ListItem(path=url)
listitem.setProperty('inputstream', 'inputstream.adaptive')        # Kodi 19+ (property name simplified from 'inputstreamaddon')
listitem.setProperty('inputstream.adaptive.manifest_type', 'hls')  # or 'mpd' (DASH), 'ism' (Smooth Streaming)
listitem.setMimeType('application/vnd.apple.mpegurl')              # HLS; 'application/dash+xml' for MPD
listitem.setContentLookup(False)                                    # disable HTTP HEAD probing so setMimeType is trusted
```
- `inputstream` property: since Kodi 19 just the addon id string (`'inputstream.adaptive'`); older `inputstreamaddon`/`inputstreamclass` names are deprecated.
- `manifest_type`: mandatory through Kodi 20, **deprecated in 21**, and no longer required in **22** (auto-derived from mimetype in newer versions) — for a 21/22-targeting addon, set it defensively for 21 but it can be omitted on 22.
- STRM-file equivalent (useful for reference/testing): `#KODIPROP:inputstream=inputstream.adaptive`, `#KODIPROP:inputstream.adaptive.manifest_type=mpd`, `#KODIPROP:mimetype=application/dash+xml` lines before the URL.

### 2.4 Detecting playback failure/stop

Source: [Player callback docs](https://xbmc.github.io/docs.kodi.tv/master/kodi-dev-kit/group__python___player_c_b.html).

- `onPlayBackStarted()` — fires when the play command is issued; video/audio may not be available yet.
- `onAVStarted()` (API v18+) — fires when Kodi actually has a decoding video/audio stream; this is the reliable "playback is really happening" signal, not `onPlayBackStarted`.
- `onAVChange()` (v18+) — fires when video/audio/subtitle streams change.
- `onPlayBackEnded()` — natural end of file.
- `onPlayBackStopped()` — user-initiated stop.
- `onPlayBackError()` — playback stopped due to an error; the current, recommended failure-detection callback.
- `onPlayBackFailed` — not present in current (22/master) docs; older Kodi versions had it, superseded by `onPlayBackError`.

Practical guidance: override `onPlayBackError` + `onPlayBackStopped`/`onPlayBackEnded` for failure/stop detection, and use `onAVStarted` rather than `onPlayBackStarted` to confirm a stream is actually decoding before assuming success. (This exactly matches the pattern `lib/player.py` in plexmod uses — see §1.4.)

### 2.5 Can HLS/TS play via core ffmpeg without inputstream.adaptive?

**Yes.** Kodi's core player has a built-in FFmpeg-based HLS demuxer that opens and plays `.m3u8` URLs directly with no inputstream addon required, for plain non-DRM, non-adaptive-switching HLS or MPEG-TS. Point the ListItem/URL at the `.m3u8` (optionally with `|User-Agent=...` pipe headers, since this path is the generic FFmpeg/cURL demuxer) and Kodi's internal demuxer handles segment fetching.

Sources: [inputstream.adaptive issue #129](https://github.com/xbmc/inputstream.adaptive/issues/129) ("HLS played by ffmpeg, not inputstream.adaptive"); the Integration wiki confirms `.strm` files default to FFmpeg-based playback unless `#KODIPROP:inputstream=...` is explicitly set.

**inputstream.adaptive is actually required when:**
- The stream is **DRM-protected** (Widevine/PlayReady) — the addon is the only supported CDM-decryption path.
- Advanced/multi-period adaptive bitrate switching across DASH or complex multi-variant HLS that FFmpeg's simpler parser doesn't fully support.
- Certain live-HLS edge cases (some encrypted/keyed live channels, or streams that trip up FFmpeg's demuxer) — e.g. a documented Kodi 21.3/FFmpeg 8 regression rejecting non-standard segment extensions that inputstream.adaptive's own HLS parser handles fine ([team-crew issue #215](https://github.com/team-crew/team-crew.github.io/issues/215); [inputstream.adaptive issue #89](https://github.com/xbmc/inputstream.adaptive/issues/89)).

For a straightforward IPTV/live-TV use case with plain HLS/TS streams and no DRM, **core ffmpeg playback without inputstream.adaptive is the simpler default**; reach for inputstream.adaptive only if a specific stream needs it.

---

## 3. Service addon lifecycle

Source: [xbmc.Monitor codedocs](https://codedocs.xyz/xbmc/xbmc/classXBMCAddon_1_1xbmc_1_1Monitor.html), local plexmod (§1.5 above).

### 3.1 xbmc.Monitor

- `xbmc.Monitor()` — constructor, "Creates a new monitor to notify addon about changes."
- `waitForAbort(timeout=-1)` → blocks until Kodi's Abort flag is set or `timeout` seconds elapse. Returns `True` if the Abort flag was set (Kodi shutting down / addon should exit), `False` if the timeout elapsed with no abort. This boolean semantics is standard, well-established Kodi API behavior across versions (confirmed by the doxygen signature; canonical usage pattern below is universal).
- `abortRequested()` → non-blocking check of the abort flag.
- `onSettingsChanged()` — virtual/no-op in the base class; override in a subclass to receive notification when the user changes addon settings via the Settings dialog.

Canonical service main loop:
```python
monitor = xbmc.Monitor()
while not monitor.abortRequested():
    if monitor.waitForAbort(5):
        break
    # periodic service work here
```

### 3.2 Sharing state between service and script

No single formalized "IPC API" exists on the Kodi wiki; the following are documented building blocks used by convention (confirmed in practice by plexmod, §1.5):

- **(a) Home window (id 10000) properties** — `xbmcgui.Window(10000).setProperty(key, value)` / `.getProperty(key)`, documented on the Python `Window` class API. Values are **strings only**, in-memory (not persisted across a Kodi restart), and global to the whole GUI process — readable by any addon or skin infolabel. This is the closest thing to an official cross-addon-process IPC mechanism, and is exactly what plexmod uses (namespaced key prefix, e.g. `script.plex.<key>`).
- **(b) sqlite3 file** under the addon's profile/userdata path (`xbmcvfs.translatePath('special://profile/addon_data/<id>/...')`) — plain stdlib `sqlite3` usage, not a dedicated wiki-documented IPC API, but a normal and confirmed-working option (see §5).
- **(c) Plain files** under the same `special://profile/addon_data/<id>/` path, resolved via `xbmcvfs.translatePath()`.

Recommendation matching plexmod's own design: use (a) for small flags/handshake state (startup coordination, "is the service alive" checks) and (b)/(c) only for larger structured data (e.g. a parsed EPG cache) that doesn't need cross-process signaling semantics.

---

## 4. Local dev loop on the Mac

### 4.1 Enabling JSON-RPC over HTTP

Source: [Settings/Services/Control wiki](https://kodi.wiki/view/Settings/Services/Control).

Settings → Services → Control:
- **"Allow remote control via HTTP"** — enables the built-in web server (JSON-RPC over HTTP). Wiki warns: never expose this port to the internet.
- **Port** — default **8080**, configurable.
- Username/Password — optional but recommended when enabled; both become required once authentication is on.

### 4.2 JSON-RPC API version and useful methods

Kodi 21 Omega uses JSON-RPC API **v13.5**; Kodi 22 Piers uses **v13.11** — both are point releases of the stable v13 API documented at [JSON-RPC API/v13](https://kodi.wiki/view/JSON-RPC_API/v13). Call `JSONRPC.Introspect` against your running instance for the authoritative, build-exact method/type schema (the wiki recommends this over any static doc).

Confirmed-present v13 methods useful for a dev loop:
- `Addons.SetAddonEnabled(addonid, enabled)` → `"OK"`
- `Addons.ExecuteAddon(addonid, [params], [wait=False])`
- `Addons.GetAddonDetails(addonid, [properties])`
- `Application.Quit()`

**`Addons.Install` does not exist** in the JSON-RPC API — the `Addons` namespace only has `ExecuteAddon`, `GetAddonDetails`, `GetAddons`, `SetAddonEnabled`. **There is no JSON-RPC method to install directly from a local zip path.** The practical local-dev pattern is:
1. Copy/symlink the addon folder directly into Kodi's `addons` directory (`~/Library/Application Support/Kodi/addons/<addon-id>/`).
2. Trigger a rescan via the builtin function `UpdateLocalAddons` — not a JSON-RPC method, invoke it via `xbmc.executebuiltin('UpdateLocalAddons')` locally, or remotely via `xbmc-send -a "UpdateLocalAddons()"`, or JSON-RPC `Input.ExecuteAction`/a helper addon that calls the builtin (see below).
3. An addon picked up this way may install disabled by default from Kodi 17+ — follow with `Addons.SetAddonEnabled(addonid, true)` over JSON-RPC to be safe (secondary/community-sourced caveat, worth confirming via `JSONRPC.Introspect` + manual test on this install).

**Reloading the skin**: the builtin function `ReloadSkin()` (documented on [List of built-in functions](https://kodi.wiki/view/List_of_built-in_functions)) reloads the current skin without a full restart. **No direct JSON-RPC equivalent exists** — the JSON-RPC `GUI` namespace only has `ActivateWindow`, `GetProperties`, `GetStereoscopicModes`, `SetFullscreen`, `SetStereoscopicMode`, `ShowNotification`; `ReloadSkin` is not an `Input.Action` value either. The common workaround is invoking the builtin locally (keymap/skin `<onclick>`), via `xbmc-send`, or through a small helper addon triggered by `Addons.ExecuteAddon`.

Practical remote dev-loop recipe on this Mac, given the above:
```bash
# after copying updated addon files into ~/Library/Application Support/Kodi/addons/<id>/
curl -s http://localhost:8080/jsonrpc -H 'Content-Type: application/json' -d \
  '{"jsonrpc":"2.0","method":"Addons.SetAddonEnabled","params":{"addonid":"script.<id>","enabled":true},"id":1}'
xbmc-send -a "UpdateLocalAddons()"
xbmc-send -a "NotifyAll(script.<id>,RELOAD)"   # if the addon listens for it, as plexmod does for RESTORE
```
(`xbmc-send` requires the addon-provided CLI tool, or an equivalent `xbmc.executebuiltin` call issued from within a running addon/keymap.)

### 4.3 kodi.log location on macOS

Source: [Log file wiki](https://kodi.wiki/view/Log_file), confirmed locally.

Per the wiki's platform table, macOS uses `/Users/<username>/Library/Logs/kodi.log` — distinct from the `.../temp/kodi.log` convention on Linux/Android. **Confirmed directly on this machine**: `~/Library/Logs/kodi.log` (current) and `~/Library/Logs/kodi.old.log` (previous run, rotated on each Kodi start) both exist. A third-party claim of `~/Library/Application Support/Kodi/kodi.log` found during research is incorrect/outdated — the wiki table and local filesystem evidence agree on `~/Library/Logs/kodi.log`.

---

## 5. XMLTV parsing at scale inside Kodi Python

### 5.1 Streaming parse with iterparse

Source: [xml.etree.ElementTree docs](https://docs.python.org/3/library/xml.etree.elementtree.html#xml.etree.ElementTree.iterparse).

Standard incremental-parse-and-clear idiom (the docs note trees build incrementally but are **not freed** incrementally — you must clear processed elements yourself to bound memory):
```python
import xml.etree.ElementTree as ET
for event, elem in ET.iterparse(source, events=('start', 'end')):
    if event == 'end' and elem.tag == 'programme':
        process(elem)
        elem.clear()
```
For XMLTV's flat `<programme>`/`<channel>` records under `<tv>`, a `start`/`end` variant tracking the parent and calling `parent.remove(elem)` after processing additionally frees the parent's child-list memory (plain `elem.clear()` leaves emptied elements attached to the tree). If no tree at all is needed, a custom `XMLParser` target avoids tree-building entirely — worth considering given XMLTV's flat record shape.

### 5.2 Feeding compressed files directly

Source: [gzip docs](https://docs.python.org/3/library/gzip.html), [lzma docs](https://docs.python.org/3/library/lzma.html).

Both `gzip.open()`/`gzip.GzipFile` and `lzma.open()`/`LZMAFile` return `io.BufferedIOBase`-compatible file objects, so they can be passed **directly** to `iterparse()` — no separate decompress-to-disk step:
```python
import gzip, lzma
opener = gzip.open if path.endswith('.gz') else lzma.open   # .xz uses lzma.open (FORMAT_XZ default)
with opener(path, 'rb') as f:
    for event, elem in ET.iterparse(f, events=('start', 'end')):
        ...
```
Sniff actual content/magic bytes rather than trusting the filename extension, since real-world XMLTV sources vary (`.xml.gz` is the common gzip form; `.xml.xz` for xz/lzma2).

### 5.3 sqlite3 availability in Kodi's bundled Python on macOS

**Confirmed directly on this machine** (stronger evidence than what the background research turned up from Kodi wiki/forum, which could not authoritatively confirm this):
```
/Applications/Kodi.app/Contents/Libraries/lib/python3.11/sqlite3/__init__.py   (and dbapi2.py, dump.py — the stdlib sqlite3 package is bundled)
```
`nm` on `libpython3.11.a` shows an undefined reference to `_sqlite3_open_v2` (the C extension's binding surface), and `nm -g` on the Kodi binary itself (`/Applications/Kodi.app/Contents/MacOS/Kodi`) shows **`_sqlite3_libversion`/`_sqlite3_libversion_number` symbols statically linked directly into the executable** — i.e. Kodi's macOS build statically links libsqlite3 into the main binary and the bundled CPython's `_sqlite3` extension binds against it. This confirms `import sqlite3` works in Kodi's addon-facing Python on macOS 21/22 with no separate dependency. (Kodi's desktop builds embed a full CPython with most of the stdlib, unlike some restricted mobile builds — this is consistent with that.)

### 5.4 Bulk-insert performance tips

Sources: [sqlite3 module docs — executemany](https://docs.python.org/3/library/sqlite3.html#sqlite3.Cursor.executemany), [SQLite FAQ #19](https://www.sqlite.org/faq.html#q19), [SQLite PRAGMA docs](https://www.sqlite.org/pragma.html).

- **`executemany()` over a loop of `execute()`** — a single prepared statement executed once per parameter set, avoiding repeated SQL-parse overhead:
  ```python
  cur.executemany("INSERT INTO programme VALUES(?, ?, ?, ?)", rows)
  con.commit()
  ```
- **Batch commits, not per-row** — SQLite FAQ #19: "SQLite will easily do 50,000 or more INSERT statements per second... but it will only do a few dozen *transactions* per second," because each commit costs a disk sync. Wrap many inserts in one transaction (`executemany()` in one implicit transaction, or an explicit `with con:` block), then commit once.
- **`PRAGMA journal_mode=WAL` + `PRAGMA synchronous=NORMAL`** — per SQLite's own PRAGMA docs, this combination is "the best balance between performance and safety for most applications running in WAL mode" and avoids most fsyncs while remaining crash-safe. Prefer this over `synchronous=OFF` unless the data is trivially re-derivable (an XMLTV cache arguably is, since you can just re-parse the source — `OFF` is a defensible choice specifically for that reason, per the same FAQ page).
- **Create indexes after bulk insert, not before** — building indexes incrementally during `executemany()` costs a B-tree update per row per index; building them once after all rows land is a single bulk index build. This is the standard corollary of the same batching principle in the FAQ/PRAGMA docs, though not a single verbatim quote.

Cross-reference (context only, not proof of Python behavior): [kodi-pvr/pvr.iptvsimple](https://github.com/kodi-pvr/pvr.iptvsimple) (C++, not Python) documents support for both gzip and xz-compressed XMLTV in the Kodi PVR ecosystem, confirming these are the two compression formats worth handling.

---

## Open follow-ups / caveats

- kodi.wiki blocks direct automated fetching (Cloudflare challenge) from this environment; wiki citations above were retrieved via a reader-proxy pass and cross-checked against WebSearch snippets. If page-exact wording matters later, spot-check the v13 JSON-RPC page and Settings/Services/Control page from a normal browser.
- The `HOW-TO:Modify the User Interface via Keymap or JSON-RPC` wiki page could not be located with content under the titles tried; flagged as unconfirmed rather than guessed.
- `Addons.SetAddonEnabled` default-disabled-after-manual-copy behavior (Kodi 17+) is sourced from community/forum discussion, not the wiki API reference itself — worth a quick manual test against this Mac's actual Kodi 21/22 install before relying on it in tooling.
