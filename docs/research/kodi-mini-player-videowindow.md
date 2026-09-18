# Mini-player / PiP: keep live TV playing in a top-right box while the Guide is shown

Date: 2026-09-18

Question: can Kodimate show a "mini player" — the current live stream kept playing in a small
box hovering top-right while the addon's own Live TV Guide window (a Python `WindowXML`) is on
screen — so that Back from `PlaybackWindow` doesn't stop the stream, only shrinks it? Primary
sources: Kodi C++ source (`xbmc/xbmc`, `master`, which is the active development line Omega/Piers
ship from — no divergent Omega/Piers branches exist for the files below, confirmed by their
absence from `git branch -r` equivalents returned by the GitHub API), the Kodi wiki/docs-kit
skinning pages, Estuary's shipped skin XML (both fetched from the local Kodi 21/22 install on
this Mac and cross-checked against the addon's own architecture docs), and the addon's own
`playback.py`/`player.py`/skin XML.

## Verified against

- [`xbmc/guilib/GUIVideoControl.cpp`](https://github.com/xbmc/xbmc/blob/master/xbmc/guilib/GUIVideoControl.cpp) (master, fetched 2026-09-18)
- [`xbmc/application/Application.cpp`](https://github.com/xbmc/xbmc/blob/master/xbmc/application/Application.cpp) (master, fetched 2026-09-18, local raw fetch + grep)
- [`xbmc/application/ApplicationPlayerCallback.cpp`](https://github.com/xbmc/xbmc/blob/master/xbmc/application/ApplicationPlayerCallback.cpp) (master, fetched 2026-09-18, local raw fetch + read)
- [`xbmc/cores/VideoPlayer/VideoPlayer.cpp`](https://github.com/xbmc/xbmc/blob/master/xbmc/cores/VideoPlayer/VideoPlayer.cpp) (master, fetched 2026-09-18, local raw fetch + grep, lines ~4190-4210)
- [`xbmc/pvr/guilib/PVRGUIActionsPlayback.cpp`](https://github.com/xbmc/xbmc/blob/master/xbmc/pvr/guilib/PVRGUIActionsPlayback.cpp) (master, fetched 2026-09-18) — PVR-specific fullscreen-switch policy, for contrast; not in Kodimate's code path (ADR 0004: no PVR API)
- Kodi wiki, via WebSearch snippet (direct fetch blocked by Cloudflare from this environment, consistent with the note already on file in `docs/research/kodi-own-ui-addon-api.md`): [Video Window Control](https://kodi.wiki/view/Video_Window_Control)
- [Kodi dev-kit docs — Video Control](https://xbmc.github.io/docs.kodi.tv/master/kodi-base/df/d07/_video__control.html) (fetched 2026-09-18)
- Local Kodi 21/22 install, `skin.estuary`: `/Applications/Kodi.app/Contents/Resources/Kodi/addons/skin.estuary/xml/Includes.xml`, `MyWeather.xml`, `MyPVRGuide.xml`, `MyPVRChannels.xml`, `Home.xml`, `DialogPVRChannelGuide.xml`, `DialogSeekBar.xml` (read directly on disk, 2026-09-18)
- `/Users/gabe/Projects/kodimate/resources/lib/kodimate/windows/playback.py`, `resources/skins/Main/1080i/script-kodimate-playback.xml`, `resources/lib/kodimate/player.py`, `resources/lib/kodimate/playback.py`, `docs/adr/0006-xbmc-player-direct.md`, `docs/adr/0004-own-ui-over-pvr-api.md` (read directly, 2026-09-18)

---

## 1. `<control type="videowindow">` inside a Python WindowXML

**It works exactly the way Kodimate already uses it, and it is not tied to `fullscreenvideo`.**
Kodimate's own `PlaybackWindow` already proves this: `script-kodimate-playback.xml:14-19` has a
full-screen `videowindow` control with an OSD group drawn on top, and per
`docs/adr/0006-xbmc-player-direct.md` (2026-09-18 amendment) it is deliberately used so that
"our own `WindowXML` stays active instead of Kodi's `fullscreenvideo` window."

Render gating, from source: `CGUIVideoControl::Render()` (`GUIVideoControl.cpp`) is gated purely
on `appPlayer->IsRenderingVideo()` — a player-state check, not a window-identity check:
```cpp
if (appPlayer->IsRenderingVideo())
{
  if (!appPlayer->IsPausedPlayback())
    appPower->ResetScreenSaver();
  // ... sets viewport to the control's CRect, clears scissor, then:
  appPlayer->Render(false, alpha);
}
```
`Process()` marks the control dirty whenever `appPlayer->IsRenderingGuiLayer()` is true, i.e. every
frame the GUI (not just fullscreenvideo) is drawing. There is no check anywhere in this file for
"is `WINDOW_FULLSCREEN_VIDEO` the active window" — the control renders the live frame at its own
`<posx>/<posy>/<width>/<height>` rectangle in *whatever* window currently hosts it, as long as a
player is actively rendering video. Source: [`GUIVideoControl.cpp`](https://github.com/xbmc/xbmc/blob/master/xbmc/guilib/GUIVideoControl.cpp).

Wiki/dev-kit confirm the control's contract precisely: "The videowindow control is used for
displaying the currently playing video elsewhere in the Kodi GUI. You can choose the position and
size of the video displayed... Note that the control is only rendered if video is being played...
Only the default control tags are applicable to this control" (no `<onclick>`/focus-specific
tags — it is a passive/non-interactive control by design). Sources:
[Video Window Control](https://kodi.wiki/view/Video_Window_Control) (via WebSearch, direct fetch
Cloudflare-blocked), [dev-kit Video Control page](https://xbmc.github.io/docs.kodi.tv/master/kodi-base/df/d07/_video__control.html).

**Requirements/caveats:**
- The hosting window need not be, and normally is not, `fullscreenvideo` — that is exactly how
  `PlaybackWindow` already avoids it (ADR 0006).
- **If the control is absent from a window's XML**, video is simply not drawn in that window (no
  fallback to fullscreen-behind-GUI): `GUIVideoControl::Render()` is the only render path for a
  `videowindow` control instance, and there is no other code that paints the live picture into an
  arbitrary WindowXML without one. A window with no `videowindow` control shows nothing of the
  video (the Guide today has none, so playback going on "behind" it is currently invisible, not
  merely occluded).
- `<allowoverlay>` is a `<window>`-level tag controlling whether Kodi's own OSD dialogs
  (`DialogSeekBar`, volume, etc.) may overlay this window — those dialogs are themselves gated by
  `Window.IsActive(fullscreenvideo)` visibility conditions in Estuary (see `DialogSeekBar.xml:3`,
  `DialogVolumeBar.xml:23`), so on a non-fullscreenvideo window they won't appear regardless of
  `<allowoverlay>`; this is already exploited by `PlaybackWindow` per the ADR 0006 amendment
  ("this keeps Kodi's own player OSD dialogs... from ever appearing").
- Z-order/compositing: `GUIVideoControl` participates in the normal control depth-order like any
  other control — declare it before (behind) the Guide's opaque background elements if any, or
  simply position it inside a `<group>` on top since it is drawn at its own rect and won't paint
  over pixels outside that rect.
- Known hardware caveat already documented in ADR 0006: "on some platforms a hardware-accelerated
  video path can ignore the `videowindow` control's rectangle and always render fullscreen
  regardless of its configured size/position" — this is a real risk for a *small* top-right box
  (unlike the full-screen `PlaybackWindow` case, where it was harmless). No primary source narrows
  which platforms/renderers hit this; it is stated as a known caveat in the addon's own ADR, not
  something this research could further pin down from Kodi upstream docs. **Must be verified
  empirically on Kodimate's real target hardware before shipping.**

## 2. What stops/continues playback when the hosting WindowXML closes

**`xbmc.Player`/the native player is architecturally independent of any window.** Confirmed at the
call-site level: `CApplication::PlayFile()` calls `appPlayer->OpenFile(...)` (`Application.cpp:2131`)
with no window parameter at all — playback is owned by `CApplicationPlayer`/`VideoPlayer`, a
process-wide component, not by any `CGUIWindow`. Closing a `WindowXML` only calls
`xbmgui.WindowXML.close()`, which is pure GUI-window teardown; nothing about it touches
`CApplicationPlayer`. Concretely, in Kodimate's own code, playback only stops when something
explicitly calls `self.player.stop()` — verified in `resources/lib/kodimate/playback.py`, where
`PlaybackSession.abort()` (line 185-194) is the only path that calls `self.player.stop()` in the
"go back / close" flow, and it is invoked from `PlaybackWindow._abort_current_session()` /
`_abort_and_close()` (`resources/lib/kodimate/windows/playback.py:383-401`, `1468-1470`) — i.e.
**today, Back always calls `session.abort()` → `player.stop()` before `self.close()`.** This is a
Kodimate design choice, not something Kodi forces: nothing stops `PlaybackWindow.close()` from
running with the session left alive.

**What the GUI shows once a hosting window closes with playback still running, if no other window
takes over hosting:** nothing renders the video — no window currently on screen has a
`videowindow` control watching it, per §1. Kodi does **not** auto-activate `WINDOW_FULLSCREEN_VIDEO`
on its own when a window closes; it only auto-activates fullscreenvideo at *playback start time*,
and only when `PlayerOptions.fullscreen` is true (see below) — a currently-playing stream losing
its `videowindow` host is not itself a trigger Kodi source ever branches on. `Player.HasVideo`
remains true in the info-manager regardless (it reflects live player state, not GUI window state),
so any window's skin conditions keyed off `Player.HasVideo` (like Estuary's own
`DefaultBackground` include, §3) will react correctly the instant such a control appears in the
active window again.

**How Kodi decides to switch to `WINDOW_FULLSCREEN_VIDEO` at playback start, and how
`windowed=True` suppresses it** — this is the mechanism Kodimate's `player.py` already relies on
(ADR 0006), now traced to source:
- `xbmc.Player().play(..., windowed=True)` sets `CMediaSettings::GetMediaStartWindowed()` (Python
  legacy binding), read once by `CApplication::PlayFile()` and folded into `PlayerOptions.fullscreen`
  (`appPlay.GetPlayerOptions()`, `Application.cpp:2131`; the temp setting is reset to `false`
  immediately after being read, `Application.cpp:2112`, so it doesn't leak into the next Play call).
- The actual GUI-fullscreen-video activation gate lives in `CVideoPlayer::OpenStream()`
  (`VideoPlayer.cpp` ~line 4197):
  ```cpp
  case StreamType::VIDEO:
    res = OpenVideoStream(hint, reset);
    // Set the m_bFullScreenVideo flag now, before streamsReady, so the
    // renderer's Configure() sees a valid viewport via GetViewWindow().
    // The WINDOW_FULLSCREEN_VIDEO skin activation is deferred to
    // HandlePlaySpeed after streamsReady.
    if (res && m_playerOptions.fullscreen &&
        !CServiceBroker::GetWinSystem()->GetGfxContext().IsFullScreenVideo())
    {
      gfx.SetFullScreenVideo(true);
      ...
    }
  ```
  i.e. the fullscreen-video switch is gated on `m_playerOptions.fullscreen`, which is exactly the
  inverse of the `windowed` flag passed from Python. With `windowed=True` (what Kodimate already
  does), this branch never executes, `SetFullScreenVideo(true)` is never called, and the deferred
  `WINDOW_FULLSCREEN_VIDEO` skin activation in `HandlePlaySpeed` (referenced by the comment above,
  not independently re-verified line-by-line here since the `windowed=True` path already proves it
  never fires in Kodimate's current shipped behaviour) never runs. This is a pure "which window did
  Kodi's core-driven GUI decide to activate" mechanism, keyed only on the `windowed` flag from the
  original `play()` call — **it is a one-time decision at playback start**, not something that
  re-fires later, so closing/reopening `PlaybackWindow` (or replacing it with `GuideWindow`) has no
  bearing on it as long as the stream itself is never restarted with `windowed=False`.
- `CApplicationPlayerCallback::OnPlayBackStarted()` (`ApplicationPlayerCallback.cpp:74-112`) — the
  callback that fires `onAVStarted`/`onPlayBackStarted` toward `xbmc.Player` subclasses — does
  *not* itself call any fullscreen-switch logic; it only pauses low-priority jobs, updates the
  stack helper, and posts `GUI_MSG_PLAYBACK_STARTED`. Confirms the fullscreen decision is made
  entirely inside `VideoPlayer::OpenStream`, upstream of any Python-visible callback, and is not
  something a script window can intercept or suppress after the fact — it can only be steered by
  the `windowed` flag passed to `play()` in the first place, which Kodimate already controls.
- Contrast: `CPVRGUIActionsPlayback::CheckAndSwitchToFullscreen()` in
  `PVRGUIActionsPlayback.cpp` implements a *different*, PVR-API-specific policy driven by the
  setting `CSettings::SETTING_PVRPLAYBACK_SWITCHTOFULLSCREENCHANNELTYPES` (never/TV/radio/all).
  This is irrelevant to Kodimate, which per ADR 0004 does not use the PVR API or PVR `CFileItem`s
  at all — Kodimate's stream is a plain `xbmc.Player().play()` call, governed only by the
  `windowed`/`PlayerOptions.fullscreen` mechanism above.

Net effect for the mini-player idea: **the stream will keep playing with no special handling
needed when `PlaybackWindow` closes**, as long as Kodimate stops calling `player.stop()` on that
path. What's *shown* on screen after the close is purely a function of which currently-active
window's XML happens to contain a `videowindow` control — nothing automatic re-shows it.

## 3. How Estuary's PVR Guide/Channels windows show a live preview

**Not via a small top-right box — Estuary uses a full-screen, semi-obscured `videowindow` as the
window background**, shared by nearly every non-video window in the skin, gated by
`Player.HasVideo`. From `Includes.xml` (`include name="DefaultBackground"`, confirmed on disk):
```xml
<include name="DefaultBackground">
  <definition>
    <control type="videowindow">
      <depth>DepthBackground</depth>
      <include>FullScreenDimensions</include>
      <visible>Player.HasVideo</visible>
      <visible>!Slideshow.IsActive</visible>
    </control>
    <control type="visualisation">
      <include>FullScreenDimensions</include>
      <visible>Player.HasAudio + ...</visible>
    </control>
    <!-- ... fanart/dim overlay group drawn on top when video isn't playing/visible ... -->
  </definition>
</include>
```
`MyPVRGuide.xml:8` and `MyPVRChannels.xml:8` (and `Home.xml:20`) each start their `<controls>`
block with `<include>DefaultBackground</include>` — confirmed by direct grep on this Mac's local
skin install (`/Applications/Kodi.app/Contents/Resources/Kodi/addons/skin.estuary/xml/`). There is
**no dedicated small preview box control** anywhere in `MyPVRGuide.xml`/`MyPVRChannels.xml`
themselves (grepped for `videowindow`/`Player.HasVideo` directly in those two files: zero matches
outside the shared include). The "preview" effect in stock Estuary is: video plays full-screen
behind the Guide/Channels grid, and the grid's own opaque panel backgrounds (`dialog-bg-nobo.png`
etc., drawn at `<depth>DepthContentPanel</depth>`, above `DepthBackground`) visually cover most of
it, leaving only edges/corners of the live picture visible around the UI chrome — this is a
"video-as-ambient-background" pattern, not a bounded PiP rectangle. `MyWeather.xml` does the same
thing standalone (full-screen `videowindow`, `visible>Player.HasVideo<`).

Conclusion: **stock Kodi/Estuary ships no precedent for a small bounded PiP box** — every
first-party usage of `videowindow` found (`DefaultBackground`, `MyWeather.xml`) is full-screen.
A top-right *box* is a legitimate, supported use of the same control (§1 shows the control honours
an arbitrary rect), just not a pattern Estuary itself demonstrates. `DialogPVRChannelGuide.xml`
(the little channel-info popup while zapping) instead uses `<visible>!Window.IsActive(fullscreenvideo)</visible>`
purely to hide itself in fullscreenvideo, and has no video-preview control of its own.

## 4. Input focus, audio, and performance while the Guide has focus

**Input**: `videowindow` is documented as accepting "only the default control tags" (§1) — no
`<onclick>`/`<onfocus>`/action-handler semantics of its own beyond the universal
default-control set (visible/animation/etc.), and it is not a `focusable` control class the way
buttons/lists are. As long as Kodimate never places its `id` into the Guide window's focus chain
(no `<onup>`/`<ondown>`/`<onleft>`/`<onright>` pointing at it and no `<defaultcontrol>` targeting
it — the same convention already used for its purely-decorative image controls in
`script-kodimate-playback.xml`), it cannot receive focus and steals no keys; D-pad/remote input
stays entirely with the Guide grid's existing controls. This matches how `PlaybackWindow` already
treats its own full-screen `videowindow` (never referenced by any `onup`/`ondown`/`onleft`/`onright`
in the XML read above).

**Audio**: unaffected either way — audio output is driven by the same `CApplicationPlayer`/`VideoPlayer`
pipeline regardless of which window (or no window) currently hosts a `videowindow` control (§2);
there is no code path in `GUIVideoControl.cpp` or `VideoPlayer.cpp` that ties audio routing to GUI
control visibility.

**Performance**: no primary source gives numbers for "one small `videowindow` control plus ~250
Python-created controls in one WindowXML frame." What source *does* establish: `GUIVideoControl`'s
per-frame cost is a viewport set + scissor clear + one `appPlayer->Render()` call into a rect —
independent of the rect's size (the renderer still decodes/uploads the same full source frame each
tick; only the destination viewport differs) — so shrinking the box does **not** reduce GPU/CPU
decode cost, only blit-target size. This means a top-right mini-player is not meaningfully cheaper
to render than today's full-screen `PlaybackWindow` video from the player's perspective; the
incremental cost specific to this feature is entirely the Guide's own ~250-control frame staying
active concurrently with active video decode/render, which is exactly the same combination Estuary
ships by default (`DefaultBackground`'s `videowindow` is live and rendering under `MyPVRGuide.xml`'s
own grid controls whenever `Player.HasVideo`) — i.e. **stock Kodi already renders a Guide-sized
control grid over a live-rendering `videowindow` in normal PVR use**, which is reasonable
first-party precedent that the combination is supported, though not a benchmark. **This must be
verified empirically on Kodimate's real target hardware/data volumes** — no primary source
quantifies frame time for either Estuary's or Kodimate's grid sizes.

## 5. Any true OS-level PiP (floating over other apps)?

**No, confirmed by architecture, not merely absence of a flag.** `GUIVideoControl::Render()` (§1)
draws into the *same* graphics context/viewport system (`CServiceBroker::GetWinSystem()->GetGfxContext()`)
that every other GUI control uses — there is exactly one Kodi window/surface per platform (one
SDL/GBM/DirectX/EGL surface), and all controls, including `videowindow`, composite into it via the
same `CGUIWindowManager`-driven render loop (`CApplication::Render()`, which flips one
`GetWinSystem()->GetGfxContext()` surface — confirmed reading `Application.cpp` around the render
loop, line ~975 area, `GetWinSystem()->GetGfxContext().Flip(...)`). Nothing in `xbmcgui`'s Python
API (`Window`, `WindowXML`, `WindowDialog`) exposes a second OS-level window, floating surface, or
always-on-top compositor layer — every Python window class ultimately maps to a `CGUIWindow`
composited inside that single surface. A "hover over other apps" PiP (the OS-level sense) is not
something Kodi's architecture supports at all; the best available approximation is exactly what
this document covers — a `videowindow` control inside Kodi's own currently-active window.

## 6. Applying this to Kodimate's actual code

Read: `resources/lib/kodimate/windows/playback.py` (1490 lines), `script-kodimate-playback.xml`,
`resources/lib/kodimate/player.py`, `resources/lib/kodimate/playback.py` (`PlaybackSession`).

Current behaviour, precisely:
- `player.py`'s `KodimatePlayer.play()` already calls `xbmc.Player.play(..., windowed=True)` (ADR
  0006), so fullscreenvideo is never engaged — good, no change needed there.
- `PlaybackWindow` is the **only** window with a `videowindow` control today
  (`script-kodimate-playback.xml:14-19`, full-screen). The Guide (`GuideWindow`, referenced in the
  task but not read here since out of the requested write-set) has none — so today, if
  `PlaybackWindow` closed without stopping the session, the stream would keep decoding/playing
  audio but show **no picture anywhere**, until some window with a `videowindow` control became
  active again.
- Every "leave playback" path in `PlaybackWindow` currently stops the session first:
  `_on_back()` → `_abort_and_close()` → `_abort_current_session()` → `session.abort()` →
  `self.player.stop()` (`windows/playback.py:1468-1470`, `383-401`; `playback.py:185-194`). This is
  the single behaviour that must change for a mini-player.

**Minimal change list for "Back from PlaybackWindow leaves the stream running small, top-right,
while GuideWindow is shown":**

1. **`GuideWindow`'s skin XML gains a `videowindow` control**, positioned top-right, *not* in the
   focus chain (see §4), e.g. (concrete snippet, 1920x1080 base resolution matching
   `script-kodimate-playback.xml`'s own coordinate system):
   ```xml
   <control type="group">
       <visible>Player.HasVideo</visible>
       <control type="videowindow">
           <posx>1536</posx>
           <posy>60</posy>
           <width>320</width>
           <height>180</height>
       </control>
       <control type="image">
           <!-- optional 2px border so the box reads clearly over the grid -->
           <posx>1534</posx>
           <posy>58</posy>
           <width>324</width>
           <height>184</height>
           <texture>white.png</texture>
           <colordiffuse>ff3a6ea5</colordiffuse>
           <depth>DepthBackground</depth>
       </control>
   </control>
   ```
   (320x180 = 16:9 at a corner-box scale consistent with Estuary's own PiP-adjacent proportions
   elsewhere in the skin; adjust to taste. `Player.HasVideo` gate means the box only appears while
   something is actually playing, matching Estuary's own `DefaultBackground` convention, §3.)

2. **`PlaybackWindow`'s "leave to Guide" path must stop calling `session.abort()`/`player.stop()`**
   — a new Back/action path (distinct from today's Stop/`_abort_and_close`) that only calls
   `self.close()` (or opens `GuideWindow` directly) while leaving `self.session`/`self.player`
   alone. Concretely this means introducing a second exit path in `_on_back()`
   (`windows/playback.py:1441-1466`) alongside the existing stop-and-close one — the existing
   `ACTION_STOP` binding (`onAction`, line 1350-1352) should keep calling `_abort_and_close()`
   verbatim (explicit Stop still stops), while plain Back when nothing else is open becomes the
   new "minimize" exit instead of falling into `_abort_and_close()`.
   - Housekeeping needed on this new "minimize" path: `PlaybackWindow.close()` (line 1472-1489)
     currently always calls `xbmc.executebuiltin('InhibitScreensaver(false)')` when
     `_screensaver_inhibited`. If the stream is meant to keep the screensaver suppressed while
     mini-played, `GuideWindow` (or whatever window is active) needs its own inhibit for as long as
     `Player.HasVideo` — `PlaybackWindow` closing should not re-enable the screensaver out from
     under a still-playing stream. This is a real, code-level consequence of the change, not
     speculative.
   - The `_progress_loop` background thread, OSD property state, Up-next/catchup machinery, etc.
     are all `PlaybackWindow`-instance-owned and get torn down by `close()` as today (stop event
     set, thread joined) — none of that is Player-owned, so none of it needs to survive; only
     `self.player`/`self.session` must be *not* torn down on this path (i.e. skip
     `_abort_current_session()`/`session.abort()` specifically).
3. **Re-entering playback from the Guide** ("un-minimize"): needs a new entry path that, given a
   still-live `session`/`player`, re-opens `PlaybackWindow` around the *existing* session instead
   of `_start_new_session()`'s connect-from-scratch flow — `PlaybackWindow.open()`/`__init__()`
   currently always builds a fresh `PlaybackSession` in `onInit()`/`_start_new_session()`
   (`windows/playback.py:216, 287-311`). This is real new code, not a config change: either (a)
   pass the live `session`/`player`/`snapshot` into a reconstructed `PlaybackWindow` and skip
   `_start_new_session()`'s session-creation half while still doing its OSD/UI setup, or (b) keep
   `PlaybackWindow` alive-but-hidden instead of closed (bigger change, touches the
   `ControlledWindow`-style show/hide lifecycle this addon doesn't currently have — plexmod's
   `BaseWindow`/`show()`/`ReplaceWindow` pattern, `docs/research/kodi-own-ui-addon-api.md` §1.1, is
   the closest existing model for that route if chosen instead of close+reopen).
4. **What Back from the Guide itself should do** is a product decision this research cannot settle
   from source alone (Kodi imposes no rule either way — see §2, nothing auto-stops on window close).
   Two consistent, implementable options:
   - Back from Guide **stops the stream** (same "Back = stop" mental model Kodimate already uses
     elsewhere) — call `session.abort()`/`player.stop()` explicitly in `GuideWindow`'s Back handler
     whenever a mini-player session is attached.
   - Back from Guide **leaves it running under Kodi Home** (true "PiP persists past this addon")
     — requires *something* with a `videowindow` control to still be the active window after Guide
     closes; Kodi's own Home window has no such control by default (Kodimate doesn't own Estuary),
     so without further work the picture would vanish (audio would keep playing) the moment Guide
     closes, even though the stream itself is still alive per §2. Making video visibly continue
     over Kodi's actual Home would require either patching a `videowindow` control into a window
     Kodimate doesn't own (not viable/appropriate), or keeping some minimal owned window
     (transparent full-screen, `videowindow`-only) alive/topmost after Guide closes — extra
     scope, not implied by "Back leaves it running."

## Recommendation

**Feasibility: yes, a bounded top-right `videowindow` mini-player while `GuideWindow` is active is
straightforwardly supported by Kodi's control model** (§1, §3) — it is the same control Kodimate
already uses full-screen in `PlaybackWindow`, just resized and hosted in a second window. The only
real engineering work is **application-level session lifecycle**, not any missing Kodi capability:
Kodi does not stop playback when a window closes (§2), so "Back doesn't stop the stream" is already
true at the platform level — Kodimate's own `PlaybackWindow._abort_and_close()` is what currently
stops it, by choice. There is no OS-level floating-over-other-apps PiP (§5) — this is strictly a
"video box inside one of Kodimate's own windows" feature, matching the question as scoped.

Minimal change list (see §6 for detail):
1. Add a small, non-focusable `<control type="videowindow">` (+ optional frame) to `GuideWindow`'s
   skin XML, gated on `Player.HasVideo`.
2. Add a "minimize" exit path from `PlaybackWindow` (Back, when not already handled by an existing
   nested-state Back branch) that closes the window **without** calling
   `session.abort()`/`player.stop()`, and stop that path from re-enabling the screensaver while
   `Player.HasVideo` is still true.
2b. Keep the existing explicit `ACTION_STOP` path calling `_abort_and_close()` (full stop)
   unchanged.
3. Add a "resume/un-minimize" entry path (from the Guide, e.g. select the currently-playing
   channel or a dedicated "Now Playing" affordance) that reconstructs `PlaybackWindow` around the
   still-live `session`/`player` instead of starting a new session.
4. Decide and implement what Back-from-Guide does to the mini-played stream (stop it outright vs.
   leave it running with only audio surviving past Guide, per the two options in §6.4) — this is a
   product decision, not a technical constraint.

Everything above is additive to the existing `PlaybackWindow`/`GuideWindow`/`player.py` design; no
part of it requires the PVR API, `inputstream.adaptive`, or anything ADR 0004/0006 already ruled
out.
