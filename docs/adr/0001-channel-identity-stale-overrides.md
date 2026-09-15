# Channel identity, Stale channels, and Overrides table

Playlists and Xtream channel lists change between Refreshes, M3U has no stable channel id, and users renumber and favourite Channels that must survive those changes. We decided: each Channel gets a **Channel Key** (Xtream: provider's stream id; M3U: `tvg-id` if present and unique, else the stream URL with scheme and query string stripped, else the full URL); Channel rows are rebuilt from each Refresh; a Channel absent from a Refresh is marked **Stale** rather than deleted and is purged only after 7 continuous days Stale; and user **Overrides** (Channel Number, Hidden, Favourite, Favourite order) live in a separate `channel_override` table keyed by `(provider_id, channel_key)` rather than as columns on the channel row.

## Considered Options

- URL-only key — breaks when a Provider rotates auth tokens in the stream URL.
- `tvg-id` + name composite — breaks when a Provider renames a channel.
- Fuzzy matching with migration — too complex for the payoff.
- Hard delete on absence — loses Overrides on any transient Provider hiccup.
- Overrides as columns on `channel` — fragile to merge correctly when channel rows are rebuilt on every Refresh.

## Consequences

SD/HD channel variants sharing one `tvg-id` collide and fall back to the URL key. Renames don't lose Overrides, since the Channel Key is stable across them. Purge after 7 days Stale is irreversible.
