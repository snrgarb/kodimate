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
  folder `script.kodimate/`, excludes `.git`, `.claude`, `.github`, `docs`,
  `scripts`, `dist`, `tests`, `__pycache__`, `*.pyc`, `.pytest_cache`,
  `.gitignore`, `CLAUDE.md`, `CONTEXT.md`, `README.md`, `.DS_Store`, `site`).
  Set `KODIMATE_DIST_DIR` to build into a different directory (defaults to
  `dist/` at the repo root). With `--install`, replaces
  the addons-dir entry with the zip contents and reloads — refuses if that
  entry is currently a symlink (use `link.sh` for symlink-based dev instead).
- `log.sh [grep-pattern]` — tails `kodi.log` (`-F`, last 200 lines), optional
  arg is passed to `grep -E` as a filter.

## Releasing

1. Bump `version` in `addon.xml` (semver).
2. Commit the bump, then `git tag v<version> && git push origin main v<version>`.
3. The `.github/workflows/release.yml` workflow runs the test suite, builds
   `script.kodimate-<version>.zip` with `deploy.sh`, and builds
   `repository.kodimate-<version>.zip` plus the addons repository site with
   `scripts/release/build_site.py`. It attaches both zips to a GitHub
   Release for the tag and publishes the site to GitHub Pages.

One-time setup: repo Settings -> Pages -> Source "GitHub Actions" (a public
repo, or a paid GitHub plan for a private one, is required for Pages).
The `github-pages` environment only allows deploys from `main` by default,
so the `pages` job fails on a tag push until you add a tag rule: Settings ->
Environments -> github-pages -> Deployment branches and tags -> add `v*`
(or `gh api -X POST repos/snrgarb/kodimate/environments/github-pages/deployment-branch-policies -f name='v*' -f type=tag`).

To install as a Kodi user: Settings -> File manager -> Add source ->
`https://snrgarb.github.io/kodimate/` (name it e.g. `kodimate`) -> Add-ons ->
Install from zip file -> `kodimate` -> `repository.kodimate` -> the zip ->
then Install from repository -> Kodimate Repository -> Video add-ons ->
Kodimate. Updates to Kodimate arrive automatically through the repository.

For a local preview of the site, run `scripts/release/build_site.py
--addon-zip dist/script.kodimate-<version>.zip --out site` and serve it with
`python3 -m http.server -d site`.

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
- Kodi caches an addon's `strings.po` once per process. Adding or fixing the
  language file needs a full Kodi restart (`Application.Quit` then
  `open -a Kodi`); `UpdateLocalAddons()` is not enough. Symptom: every
  `$ADDON[...]` label and `getLocalizedString()` returns an empty string.
- `strings.po` needs a real PO header (Project-Id-Version, Content-Type
  charset=UTF-8, etc.). With only a bare `msgid ""`/`msgstr ""` header,
  `msgfmt -c` reports "PO file header missing or invalid" and Kodi loads no
  strings.
- Real `xbmcgui.WindowXML` drops unknown constructor kwargs;
  `BaseWindow.__init__` copies them onto the instance before calling the
  parent. The test fake mirrors real Kodi (does not store kwargs).
- Kodi cannot read files under the sandboxed scratchpad path; for throwaway
  probe scripts use `~/Library/Application Support/Kodi/temp/` and
  `RunScript(<absolute path>)` via `builtin.py`.
- Screenshots: set `debug.screenshotpath` via `rpc.py
  Settings.SetSettingValue`, then `builtin.py 'TakeScreenshot()'`.

## Verified (2026-09-15, Kodi 21.3, xbmc.python 3.0.1)

- `rpc.py JSONRPC.Ping` -> `{"result": "pong"}`.
- `link.sh` symlinked the addon dir; `UpdateLocalAddons()` + `SetAddonEnabled`
  succeeded once the addon was discoverable.
- `rpc.py Addons.GetAddonDetails` -> `enabled: true`, `version: "0.0.1"` (that
  verification run predates the 0.1.0 version bump below).
- `reload.sh` -> log shows `Kodimate script started` and (from Kodi's own
  service startup) `Kodimate service started`.
- `deploy.sh` built `dist/script.kodimate-0.1.0.zip` with top-level
  `script.kodimate/` folder containing the addon's `addon.xml`, `default.py`,
  `service.py`, `icon.png`/`fanart.jpg`, and `resources/`.
- `builtin.py 'Notification(Kodimate,builtin ok)'` -> log shows
  `ES: Incoming connection from kodimate-dev` with no error afterward.

### Gotcha found during verification

`deploy.sh`'s version extraction must anchor on a line that starts with
`version="..."` (the addon's own attribute on its own line) — a naive
`.*version="..."` match instead grabs `<?xml version="1.0" ...?>` from the
first line of `addon.xml`.
