# Schema outline

An outline of the Kodimate SQLite tables: columns and keys, not final DDL. See [ADR 0001](../adr/0001-channel-identity-stale-overrides.md) for Channel identity, Stale, and Overrides; [ADR 0002](../adr/0002-provider-credentials-plaintext.md) for credential storage; [ADR 0003](../adr/0003-service-sole-writer-wal.md) for the service/script write split and connection settings.

## Tables

### provider

`id` (PK), `kind` (`'m3u' | 'xtream'`), `name`, `enabled`, `deleted_at` (nullable; set by the script on delete, rows with it set are hidden by every query and purged by the service), `sort_order`, `m3u_url`, `xtream_host`, `xtream_username`, `xtream_password`, `user_agent` (nullable; Provider-wide default User-Agent for playlist/EPG/stream requests, Channel headers override it), `account_expires_at` (nullable, Xtream only, written by the service at Refresh), `max_connections` (nullable, Xtream only, written by the service at Refresh), `allowed_output_formats` (nullable, Xtream only, JSON array string, written by the service at Refresh), `epg_override_url`, `catchup_days_default` (nullable), `catchup_url_form` (`'auto' | 'path' | 'query'`, default `'path'`), `catchup_correction_hours` (default 0, valid range -12..+12), `number_offset`, `stream_format` (`'ts' | 'm3u8' | NULL`), `learned_stream_format` (`'ts' | 'm3u8' | NULL`, set when a Live Form fallback succeeds; cleared when the Provider's host or credentials are edited or when `stream_format` is set; `stream_format` always wins), `last_refresh_at`, `last_error`, `config_version` (int, incremented on every script-side edit of kind/url/host/creds/epg_override_url; the service discards in-flight Refresh results whose start version no longer matches).

### epg_source

`id` (PK), `provider_id` (FK, UNIQUE), `url`, `last_fetched_at`, `etag`/`last_modified`.

### programme_staging

Same columns as `programme`. Created per EPG refresh, dropped by the swap and at service startup.

### epg_channel

`epg_source_id` (FK), `xmltv_channel_id`, `normalised_name` (nullable); PK(`epg_source_id`, `xmltv_channel_id`). Records the channel ids (and normalised first `<display-name>`) seen in the last successfully parsed XMLTV document per EPG Source, so matching can run on every refresh even when the feed returns 304.

### channel_group

`id` (PK), `provider_id` (FK), `name`, `sort_order`; UNIQUE(`provider_id`, `name`).

### channel

`id` (PK), `provider_id` (FK), `channel_key`, `name`, `normalised_name`, `stream_url`, `logo_url`, `group_id` (FK), `provider_number` (nullable), `position`, `epg_channel_id` (nullable, resolved reference into the matched `epg_source`'s channel ids), `catchup_days` (nullable), `catchup_mode`, `catchup_source`, `catchup_correction_hours`, `headers_json` (from `#EXTVLCOPT`/`#KODIPROP`), `stale_since` (nullable), `last_seen_at`; UNIQUE(`provider_id`, `channel_key`).

### channel_override

`provider_id`, `channel_key`, `number` (nullable), `hidden` (bool), `favourite` (bool), `favourite_order` (nullable); PK(`provider_id`, `channel_key`). Deliberately not FK'd to `channel.id`, so Overrides survive the `channel` rows being rebuilt on Refresh.

### programme

`epg_source_id` (FK), `xmltv_channel_id`, `start`, `end`, `title`, `subtitle`, `description`, `icon_url`, `category`, `catchup_id` (nullable); PK(`epg_source_id`, `xmltv_channel_id`, `start`); index on (`xmltv_channel_id`, `end`).

### meta

`key`, `value` — holds `schema_version`.

## Effective Channel Number

`channel_override.number`, else `channel.provider_number + provider.number_offset`, else `channel.position + provider.number_offset`.

## Effective Catch-up Window

`channel.catchup_days`, else `provider.catchup_days_default`. `NULL` at both levels means no Catch-up. Ingest stores an Xtream channel's `tv_archive=0` as `catchup_days = 0` (an explicit "no Catch-up" channel value, which beats the provider default), not `NULL`.

## Live Form

Live Form (Xtream Providers only): `provider.stream_format`, else `provider.learned_stream_format`, else `'ts'`. `'m3u8'` is only used when the Provider's `allowed_output_formats` includes it.

## Catch-up playability

A Programme is playable when its Channel's Effective Catch-up Window is > 0, `programme.start >= now - window_days`, and `programme.start < now`. Requested duration is `min(programme.end, now) - programme.start`. Because `programme` rows older than 7 days are deleted, Catch-up is effectively capped at 7 days.

## Refresh invariants

- `channel` rows for a Provider are rebuilt inside one transaction.
- `stale_since` is set on a Channel absent from the Refresh, and cleared when the Channel is seen again.
- A Channel is purged once `stale_since` is older than 7 days.
- `programme` rows for an `epg_source` are replaced inside one transaction.
- `programme` rows older than 7 days are deleted.
- Rebuild is performed only by the service.
- Programme replacement uses `programme_staging` plus a short swap transaction.
- A Channel's `epg_channel_id` is matched, on every Refresh, against its Provider's `epg_channel` rows: by exact `tvg-id`/`epg_channel_id` (after stripping a trailing `(srcNN)`-style suffix), else by Normalised Name, else left unmatched (`NULL`).
- Providers are refreshed sequentially.
- A Refresh commits nothing if the Provider's `config_version` changed since it started.
- `provider` rows with `deleted_at` set are cascaded (epg_source, channel_group, channel, programme, channel_override) by the service, which then bumps the Generation; leftovers are also purged at service startup.
- Rebuild is skipped for Providers with `enabled = 0`.

## Connections

WAL journal mode, `synchronous=NORMAL`, `busy_timeout` 5 s. Both processes open through one shared helper that also runs schema migrations. See [ADR 0003](../adr/0003-service-sole-writer-wal.md).

## Visibility

A Channel is listable (list, Guide, Zapping) when it is not Stale and not Hidden. Channels of a Disabled or Deleted Provider are never listable.
