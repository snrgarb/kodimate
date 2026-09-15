# Direct `xbmc.Player` playback of TS/HLS, no inputstream addon or local proxy

Live streams are MPEG-TS or HLS from Xtream or M3U Providers, and Catch-up is a URL to a Provider-side archive segment. We decided to play stream URLs directly with a single owned `xbmc.Player` instance, letting Kodi's core ffmpeg demux TS and HLS; per-Channel headers (User-Agent, Referer from `#EXTVLCOPT`/`#KODIPROP`) are applied via ListItem properties, the Xtream Live Form defaults to `ts` with `m3u8` fallback, and there is no `inputstream.adaptive`, `inputstream.ffmpegdirect`, or local HTTP proxy. Core ffmpeg already plays plain TS/HLS on Kodi 21+, this avoids a binary addon dependency and per-platform availability concerns, and it keeps the pure-Python core testable.

## Considered Options

- `inputstream.adaptive` — built for DASH/HLS with DRM, adds a dependency with no gain for plain TS.
- `inputstream.ffmpegdirect` — would enable live timeshift buffering, but adds a binary dependency and extra failure surface; timeshift is out of scope.
- Local proxy process — would allow pause/timeshift and header injection, but adds a long-lived socket server inside Kodi and doubles buffering.

## Consequences

Live pause/timeshift buffering and stream failover are out of scope. Catch-up seeking is native player seek only; a position beyond the buffer needs a fresh URL (deferred). Stream failure detection relies on `onPlayBackError`/`onAVStarted` callbacks and timeouts (Playback Session state machine). Reconnect Attempts re-issue the same URL.
