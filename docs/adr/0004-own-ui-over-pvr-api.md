# Own WindowXML UI instead of Kodi PVR / IPTV Simple Client

Kodimate's goal is a TiviMate-style IPTV client on Kodi 21 Omega / 22 Piers, with full control over the channel list, Guide, OSD, and Zapping across multiple Providers. We decided Kodimate is an `xbmc.python.script` addon with its own WindowXML skin (BaseWindow over WindowXML, ManagedControlList, skin under `resources/skins/Main/1080i`) plus a `service` extension for background Refresh, and it does not use the Kodi PVR API, `pvr.iptvsimple`, or a `pluginsource` extension. The PVR API is C++ binary addon only with no Python surface, IPTV Simple Client gives no control over channel list/Guide/OSD/Zapping UX or multi-Provider handling, and a `pluginsource` addon forces Kodi's directory-listing UI onto the client.

## Considered Options

- `pvr.iptvsimple` plus skin tweaks — no UX control, single-Provider EPG matching, not TiviMate-like.
- Binary PVR addon in C++ — out of reach for a Python project, needs per-platform builds.
- `pluginsource` with Kodi directory lists — no Guide grid, no OSD Zapping.

## Consequences

Kodimate reimplements channel list, Guide, OSD, Favourites, and search itself. Kodi-native PVR features (timeshift buffer, recordings, PVR settings, skin PVR windows) are unavailable. Multi-view/PiP is out of scope. The skin must be maintained per Kodi version.
