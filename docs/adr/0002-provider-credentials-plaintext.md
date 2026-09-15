# Provider credentials stored plaintext in SQLite

Xtream Provider username/password and tokened M3U URLs must persist, Kodi has no keychain, and Kodimate already stores its own config in SQLite under `special://profile/addon_data/script.kodimate/` via its own WindowXML CRUD rather than `settings.xml`. We decided to store these credentials as plaintext in that same SQLite database, protected only by filesystem permissions on the profile directory; they are never logged and never committed to the repo.

## Considered Options

- Kodi `settings.xml` — also plaintext, and its fixed slot count contradicts the already-decided own-CRUD storage model.
- Reversible obfuscation (e.g. base64/XOR) — provides false security without a real secret store.

## Consequences

Anyone with filesystem access to the Kodi profile can read Provider credentials. Any logging of stream or EPG URLs must redact embedded credentials.
