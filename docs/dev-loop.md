# Local dev loop (Kodi 21.3, macOS)

## Paths

- Kodi app: `/Applications/Kodi.app`
- Kodi addons dir: `~/Library/Application Support/Kodi/addons/`
- Kodi log: `~/Library/Logs/kodi.log` (rotates to `kodi.old.log` on start)
- Addon in this repo: `script.kodimate` (repo root doubles as the addon dir)

## Ports

- `127.0.0.1:9090` TCP — JSON-RPC. No auth. Kodi JSON-RPC API v13.5.
- `127.0.0.1:9777` UDP — EventServer. Used to send `PT_ACTION`/`ACTION_EXECBUILTIN`
  packets (stdlib-only client in `scripts/dev/builtin.py`), since JSON-RPC has
  no way to call arbitrary builtins or install-from-zip.
- HTTP webserver (8080) is NOT enabled/needed for this loop.

## Required Kodi settings

- [ ] Settings -> Services -> Control -> "Allow remote control from
      applications on this system" — ON (required for the JSON-RPC TCP
      socket and EventServer).
- [ ] Settings -> Services -> Control -> "Allow remote control via HTTP" —
      not required for this loop (HTTP webserver is unused).

## Scripts (`scripts/dev/`)

- `rpc.py <Method> ['<json params>']` — JSON-RPC call over TCP 9090. Prints
  the response JSON; exits nonzero if the response has an `error` member.
  Env overrides: `KODI_HOST`, `KODI_RPC_PORT`.
- `builtin.py '<Builtin()>'` — sends a builtin (e.g. `UpdateLocalAddons()`,
  `Notification(...)`) to Kodi over the EventServer. Env overrides:
  `KODI_HOST`, `KODI_EVENT_PORT`.
- `link.sh` — symlinks `~/Library/Application Support/Kodi/addons/script.kodimate`
  to the repo root (idempotent; refuses if a real directory already exists
  there), then runs `UpdateLocalAddons()` and enables the addon.
- `reload.sh` — `UpdateLocalAddons()` -> enable addon -> `Addons.ExecuteAddon`.
  Use after editing `default.py`/`service.py` via the symlink.
- `deploy.sh [--install]` — builds `dist/script.kodimate-<version>.zip` (top
  folder `script.kodimate/`, excludes `.git`, `.claude`, `docs`, `scripts`,
  `dist`, `tests`, `__pycache__`, `.gitignore`, `CLAUDE.md`, `CONTEXT.md`,
  `README.md`). With `--install`, replaces
  the addons-dir entry with the zip contents and reloads — refuses if that
  entry is currently a symlink (use `link.sh` for symlink-based dev instead).
- `log.sh [grep-pattern]` — tails `kodi.log` (`-F`, last 200 lines), optional
  arg is passed to `grep -E` as a filter.

## Starting/stopping Kodi

- Start: `open -a Kodi`
- Quit: `python3 scripts/dev/rpc.py Application.Quit`

## Caveats

- JSON-RPC has no install-from-zip method; installs/enables go through
  `UpdateLocalAddons()` (EventServer builtin) + `Addons.SetAddonEnabled`.
- HTTP webserver is not running and is not needed for this loop.
- With the symlink in place (`link.sh`), edits to `default.py`/`service.py`
  take effect on the next script launch / service restart — no reload needed
  for the file contents themselves, but Kodi's addon cache still needs
  `UpdateLocalAddons()` if `addon.xml` changed (version bump, new deps, etc).
  WindowXML changes (none yet in this addon) take effect on next window open.

## Verified (2026-09-15, Kodi 21.3, xbmc.python 3.0.1)

- `rpc.py JSONRPC.Ping` -> `{"result": "pong"}`.
- `link.sh` symlinked the addon dir; `UpdateLocalAddons()` + `SetAddonEnabled`
  succeeded once the addon was discoverable.
- `rpc.py Addons.GetAddonDetails` -> `enabled: true`, `version: "0.0.1"`.
- `reload.sh` -> log shows `Kodimate script started` and (from Kodi's own
  service startup) `Kodimate service started`.
- `deploy.sh` built `dist/script.kodimate-0.0.1.zip` with top-level
  `script.kodimate/` folder containing only `addon.xml`, `default.py`,
  `service.py`.
- `builtin.py 'Notification(Kodimate,builtin ok)'` -> log shows
  `ES: Incoming connection from kodimate-dev` with no error afterward.

### Gotcha found during verification

`deploy.sh`'s version extraction must anchor on a line that starts with
`version="..."` (the addon's own attribute on its own line) — a naive
`.*version="..."` match instead grabs `<?xml version="1.0" ...?>` from the
first line of `addon.xml`.
