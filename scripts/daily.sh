#!/usr/bin/env bash
# Cron-ready daily batch. Assumes .venv exists and a logged-in Chrome is reachable
# on the CDP endpoint configured in config.yaml.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  set -a && source .env && set +a
fi

PYTHON="$REPO_DIR/.venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON="python3"

COUNT="${YTMUSIC_COUNT:-6}"

echo "=== yt-music-agent $(date -Is) : batch of $COUNT ==="
"$PYTHON" -m ytmusic doctor || true
"$PYTHON" -m ytmusic run -n "$COUNT"

BATCH_DIR="$REPO_DIR/out/$(date +%F)"
echo "=== done: $BATCH_DIR ==="
[[ -f "$BATCH_DIR/UPLOAD.md" ]] && cat "$BATCH_DIR/UPLOAD.md"
