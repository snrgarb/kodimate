# Schema outline

An outline of the Kodimate SQLite tables: columns and keys, not final DDL. See [ADR 0001](../adr/0001-channel-identity-stale-overrides.md) for Channel identity, Stale, and Overrides; [ADR 0002](../adr/0002-provider-credentials-plaintext.md) for credential storage.

## Tables

### provider

`id` (PK), `kind` (`'m3u' | 'xtream'`), `name`, `enabled`, `sort_order`, `m3u_url`, `xtream_host`, `xtream_username`, `xtream_password`, `epg_override_url`, `catchup_days_default` (nullable), `number_offset`, `stream_format` (`'ts' | 'm3u8' | NULL`), `last_refresh_at`, `last_error`.

### epg_source

`id` (PK), `provider_id` (FK, UNIQUE), `url`, `last_fetched_at`, `etag`/`last_modified`.

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

`channel.catchup_days`, else `provider.catchup_days_default`. `NULL` at both levels means no Catch-up.

## Refresh invariants

- `channel` rows for a Provider are rebuilt inside one transaction.
- `stale_since` is set on a Channel absent from the Refresh, and cleared when the Channel is seen again.
- A Channel is purged once `stale_since` is older than 7 days.
- `programme` rows for an `epg_source` are replaced inside one transaction.
- `programme` rows older than 7 days are deleted.

## Visibility

A Channel is listable (list, Guide, Zapping) when it is not Stale and not Hidden.
