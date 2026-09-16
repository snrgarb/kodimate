# Service is the sole writer of Provider-derived tables; SQLite WAL; live Playback Session holds a Channel snapshot

The script (UI) and service run as separate Python interpreters sharing one SQLite database in `special://profile/addon_data/script.kodimate/`. Refresh rebuilds `channel` rows per Provider and `programme` rows per EPG Source, and the UI may be open and playing during a Refresh. We decided:

- The service is the only process that writes `channel`, `channel_group`, `programme`, `epg_source`, and `provider.last_refresh_at`/`last_error`/`account_expires_at`/`max_connections`/`allowed_output_formats`. The script writes only `channel_override`, `provider` CRUD/config columns, and `provider.learned_stream_format`. A manual Refresh from the UI is a request to the service, never run inline in the script.
- Every connection, in both processes, opens through one shared helper that sets `PRAGMA journal_mode=WAL`, `PRAGMA synchronous=NORMAL`, `PRAGMA busy_timeout=5000`, and runs idempotent schema migrations under `BEGIN IMMEDIATE` checking `meta.schema_version` (whichever process opens first migrates; no startup handshake).
- The script keeps one connection and `fetchall()`s every read, so no cursor is held across UI frames (a held cursor would pin WAL frames and block checkpoint). Script writes retry up to 3 times on `database is locked`.
- Programme replacement parses into a `programme_staging` table outside any long transaction, then one short transaction: delete by `epg_source_id`, `INSERT ... SELECT` from staging, drop staging. Channel rebuild stays plain delete+insert in one transaction (small). The service runs `PRAGMA wal_checkpoint(TRUNCATE)` after each Refresh and drops any leftover staging table at startup.
- Provider config edits bump `provider.config_version`; the service records it at fetch start and, in the swap transaction, rolls back and discards results if the version changed or the row is gone; if the Provider still exists it re-queues a Refresh.
- Providers are refreshed sequentially, one at a time.
- A live Playback Session holds a snapshot of its Channel (key, name, stream URL, headers, number, Live Form) taken at start; Refresh never touches a live session; reconnect Attempts reuse the snapshot; a Channel going Stale mid-playback keeps playing. Zapping from a Stale Channel goes to the nearest listable Channel by Effective Channel Number. Startup autoplay of a Stale last Channel falls back to the first listable Channel.

## Considered Options

- Script runs Refresh inline — two writers, duplicated logic, lock contention.
- Default rollback journal — UI reads stall during Refresh.
- Single long transaction for programmes — write lock 10-30 s; script writes time out.
- Chunked commits — breaks the one-transaction invariant, readers see partial EPG.
- Stop playback when a Channel goes Stale — interrupts a working stream over metadata.

## Consequences

`-wal`/`-shm` files sit beside the DB. The script must tolerate service absence (see design doc). UI re-renders are driven by a generation signal.
