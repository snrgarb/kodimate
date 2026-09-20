# Direct `xbmc.Player` playback of TS/HLS, no inputstream addon or local proxy

> Superseded in part by the [Amended 2026-09-20](#amended-2026-09-20) section below.

Live streams are MPEG-TS or HLS from Xtream or M3U Providers, and Catch-up is a URL to a Provider-side archive segment. We decided to play stream URLs directly with a single owned `xbmc.Player` instance, letting Kodi's core ffmpeg demux TS and HLS; per-Channel headers (User-Agent, Referer from `#EXTVLCOPT`/`#KODIPROP`) are applied via ListItem properties, the Xtream Live Form defaults to `ts` with `m3u8` fallback, and there is no `inputstream.adaptive`, `inputstream.ffmpegdirect`, or local HTTP proxy. Core ffmpeg already plays plain TS/HLS on Kodi 21+, this avoids a binary addon dependency and per-platform availability concerns, and it keeps the pure-Python core testable.

## Considered Options

- `inputstream.adaptive` — built for DASH/HLS with DRM, adds a dependency with no gain for plain TS.
- `inputstream.ffmpegdirect` — would enable live timeshift buffering, but adds a binary dependency and extra failure surface; timeshift is out of scope.
- Local proxy process — would allow pause/timeshift and header injection, but adds a long-lived socket server inside Kodi and doubles buffering.

## Consequences

A local timeshift proxy and stream failover are out of scope. Seeking and pause/resume stay native inside the player's own buffer; a target beyond the buffer is served by rebuilding a fresh Catch-up URL at that position rather than a local proxy. Stream failure detection relies on `onPlayBackError`/`onAVStarted` callbacks and timeouts (Playback Session state machine). Reconnect Attempts re-issue the same URL.

## Amended 2026-09-18

The player renders inside the addon's own `WindowXML` (`PlaybackWindow`) via a fullscreen `videowindow` control, played windowed (`xbmc.Player.play(..., windowed=True)`), instead of switching Kodi to its `fullscreenvideo` window. This keeps Kodi's own player OSD dialogs (DialogSeekBar, the pause OSD) from ever appearing over our OSD, since they are only auto-shown while `fullscreenvideo` is the active window. Known caveat: on some platforms a hardware-accelerated video path can ignore the `videowindow` control's rectangle and always render fullscreen regardless of its configured size/position; harmless here since our control is already sized to the full screen. Because `fullscreenvideo` is never active, Kodi does not suppress the screensaver on its own, so `PlaybackWindow` inhibits it itself via `InhibitScreensaver` for the lifetime of the window.

## Amended 2026-09-20

Direct `xbmc.Player` play remains, but the stream is now handed to `inputstream.ffmpegdirect` (via ListItem inputstream properties) rather than played as a plain TS/HLS URL: live sessions use ffmpegdirect's timeshift mode, Catch-up sessions use its catchup mode. A prototype confirmed native pause holds the frame and resumes from the paused point.

Accepted trade-offs:

- A binary addon dependency (`inputstream.ffmpegdirect`, official Kodi repo, available on all platforms).
- The timeshift disk buffer is wiped at Kodi start.
- The buffer costs roughly 130 MB/min at 1080p; the user-configurable size cap lives in ffmpegdirect's own settings, not Kodimate's.

This supersedes the "Considered Options" rejection of `inputstream.ffmpegdirect` and the "Consequences" paragraph above about rebuilding a Catch-up URL beyond the buffer: seeking inside a Catch-up programme is now addon-driven via ffmpegdirect's catchup mode, not a Kodimate URL rebuild.
