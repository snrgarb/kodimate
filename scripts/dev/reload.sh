#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

python3 "$REPO_ROOT/scripts/dev/builtin.py" 'UpdateLocalAddons()'
python3 "$REPO_ROOT/scripts/dev/rpc.py" Addons.SetAddonEnabled '{"addonid":"script.kodimate","enabled":true}'
python3 "$REPO_ROOT/scripts/dev/rpc.py" Addons.ExecuteAddon '{"addonid":"script.kodimate"}'
