# Refresh signalling between service and script

How the service and script coordinate Refresh over `Window(10000)` properties, all keys prefixed `script.kodimate.`. See [ADR 0003](../adr/0003-service-sole-writer-wal.md).

## Properties

- `refresh_request`: comma-list of provider ids or `all`. Written by the script, read and cleared by the service each 1 s poll tick, then merged into the service queue; a Provider already refreshing or queued is not queued twice. The script sets it after creating or editing a Provider, and on manual Refresh.
- `refreshing`: comma-list of provider ids currently in flight (empty when idle). The UI shows an indicator and disables manual Refresh for those Providers. If `refreshing` has not changed 10 s after a request, the script toasts "Kodimate service not running".
- `db_generation`: integer, incremented by the service after every committed Refresh (not on failure). In-memory only; the script treats a missing value as 0 and always re-queries when a window opens.
- `refresh_result.<provider_id>`: `ok` or `error:<message>`, written only for requests that carried `requested_by=ui` (request value form `ids;ui`); the script toasts once then clears it. Background failures are silent; `provider.last_error` is visible in provider settings. Failure leaves `last_refresh_at` unchanged and does not bump the generation.

## Push wake-up

The service also sends `NotifyAll('script.kodimate', 'refreshed', {"generation": n, "providers": [...]})`; the script's Monitor overrides `onNotification`. The generation property is the durable state; NotifyAll is only the wake-up.

## Live re-render rule

On a generation change, the open channel list / Guide re-query and re-render in place: focus is kept by Channel Key (nearest row if it went Stale), scroll offset is kept, and the Guide re-renders only the visible viewport. Re-render is deferred while a modal (Programme info dialog, context menu, number entry) is open, and applied when it closes. If the focused Group or Provider vanished, the groups pane falls to "All channels" (or Favourites if that was active) and the channel pane to the first listable row, with no toast. The OSD now/next re-reads Programmes by Channel Key on generation change; the stream itself is untouched.
