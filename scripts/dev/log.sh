#!/usr/bin/env bash
set -euo pipefail

LOG="$HOME/Library/Logs/kodi.log"

if [ "${1:-}" != "" ]; then
    tail -n 200 -F "$LOG" | grep -E --line-buffered "$1"
else
    tail -n 200 -F "$LOG"
fi
