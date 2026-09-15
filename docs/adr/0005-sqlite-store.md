# SQLite as the single store for Providers, Channels, and EPG

XMLTV EPG for a large playlist runs to tens of thousands of Programmes, Channel lists to thousands, Overrides must survive Refresh, and the script and service run as separate Python processes. We decided on one SQLite database in `special://profile/addon_data/script.kodimate/`, using the `sqlite3` module bundled with Kodi's Python 3.11, streamed into via `iterparse` over gzip/lzma XMLTV, holding all Provider config, Channels, Groups, Programmes, Overrides, and meta.

## Considered Options

- JSON/pickle files per Provider — whole-file rewrite on every Refresh, no indexed time-range queries for the Guide, no cross-process safety.
- Kodi `settings.xml` for Providers — fixed slot count, not CRUD-able from Kodimate's own UI.
- In-memory only — EPG re-parse on every start, 10-30 s.

## Consequences

Schema migrations are owned by the addon (see ADR 0003). `-wal`/`-shm` sidecar files sit beside the database. Credentials are stored plaintext (ADR 0002). Tests can run on plain CPython with Kodi stubs since `sqlite3` is stdlib.
