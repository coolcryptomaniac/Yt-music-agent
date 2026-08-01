#!/usr/bin/env bash
# Starts the Chrome the agent drives, in a dedicated profile, with remote debugging on.
# Log into suno.com in the window it opens; the login is remembered across reboots.
set -euo pipefail

PORT="${YTMUSIC_CDP_PORT:-29229}"
PROFILE="${YTMUSIC_CHROME_PROFILE:-$HOME/.config/yt-music-agent/chrome}"
mkdir -p "$PROFILE"

if curl -fsS "http://localhost:$PORT/json/version" >/dev/null 2>&1; then
  echo "Chrome is already listening on port $PORT - nothing to do."
  exit 0
fi

if [[ "$OSTYPE" == darwin* ]]; then
  CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
else
  CHROME="$(command -v google-chrome || command -v google-chrome-stable || command -v chromium || true)"
fi
[[ -x "$CHROME" ]] || { echo "Google Chrome not found - install it first."; exit 1; }

"$CHROME" --remote-debugging-port="$PORT" --user-data-dir="$PROFILE" https://suno.com/create \
  >/dev/null 2>&1 &

echo "Chrome starting on port $PORT (profile: $PROFILE)."
echo "Sign into Suno in that window, then run ./scripts/daily.sh"
