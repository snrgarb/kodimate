#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ADDONS_DIR="$HOME/Library/Application Support/Kodi/addons"
TARGET="$ADDONS_DIR/script.kodimate"

if [ -e "$TARGET" ] && [ ! -L "$TARGET" ]; then
    echo "refusing to overwrite non-symlink at $TARGET" >&2
    exit 1
fi

if [ -L "$TARGET" ]; then
    CURRENT="$(readlink "$TARGET")"
    if [ "$CURRENT" != "$REPO_ROOT" ]; then
        rm "$TARGET"
        ln -s "$REPO_ROOT" "$TARGET"
    fi
else
    ln -s "$REPO_ROOT" "$TARGET"
fi

python3 "$REPO_ROOT/scripts/dev/builtin.py" 'UpdateLocalAddons()'
python3 "$REPO_ROOT/scripts/dev/rpc.py" Addons.SetAddonEnabled '{"addonid":"script.kodimate","enabled":true}'
