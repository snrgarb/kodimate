#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="$(sed -n 's/^[[:space:]]*version="\([^"]*\)".*/\1/p' "$REPO_ROOT/addon.xml" | head -1)"
DIST_DIR="${KODIMATE_DIST_DIR:-$REPO_ROOT/dist}"
ZIP_PATH="$DIST_DIR/script.kodimate-${VERSION}.zip"
ADDONS_DIR="$HOME/Library/Application Support/Kodi/addons"
TARGET="$ADDONS_DIR/script.kodimate"

mkdir -p "$DIST_DIR"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

STAGE_ADDON="$STAGE/script.kodimate"
mkdir -p "$STAGE_ADDON"

rsync -a --prune-empty-dirs \
    --exclude '.git' \
    --exclude '.claude' \
    --exclude '.github' \
    --exclude 'docs' \
    --exclude 'scripts' \
    --exclude 'dist' \
    --exclude 'tests' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.pytest_cache' \
    --exclude '.gitignore' \
    --exclude 'CLAUDE.md' \
    --exclude 'CONTEXT.md' \
    --exclude 'README.md' \
    --exclude '.venv' \
    --exclude 'pytest.ini' \
    --exclude 'requirements-dev.txt' \
    --exclude '.DS_Store' \
    --exclude 'site' \
    "$REPO_ROOT/" "$STAGE_ADDON/"

rm -f "$ZIP_PATH"
(cd "$STAGE" && zip -r -q "$ZIP_PATH" "script.kodimate")

echo "built $ZIP_PATH"

if [ "${1:-}" = "--install" ]; then
    if [ -L "$TARGET" ]; then
        echo "refusing --install: $TARGET is a symlink" >&2
        exit 1
    fi
    rm -rf "$TARGET"
    unzip -q "$ZIP_PATH" -d "$ADDONS_DIR"
    python3 "$REPO_ROOT/scripts/dev/builtin.py" 'UpdateLocalAddons()'
    python3 "$REPO_ROOT/scripts/dev/rpc.py" Addons.SetAddonEnabled '{"addonid":"script.kodimate","enabled":true}'
fi
