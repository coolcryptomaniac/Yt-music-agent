#!/usr/bin/env bash
# One-command setup for macOS and Linux.
#
#   curl -fsSL https://raw.githubusercontent.com/coolcryptomaniac/Yt-music-agent/main/scripts/setup.sh | bash
#
# Installs ffmpeg + a virtualenv + Playwright's Chromium, writes .env, and prints the
# two commands you need daily. Safe to re-run.
set -euo pipefail

REPO_URL="https://github.com/coolcryptomaniac/Yt-music-agent.git"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

# --- locate (or clone) the repo -------------------------------------------------
if [[ -f "$(dirname "${BASH_SOURCE[0]}")/../pyproject.toml" ]]; then
  REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
else
  REPO_DIR="$HOME/Yt-music-agent"
  if [[ -d "$REPO_DIR/.git" ]]; then
    say "updating $REPO_DIR"
    git -C "$REPO_DIR" pull --ff-only
  else
    say "cloning into $REPO_DIR"
    git clone "$REPO_URL" "$REPO_DIR"
  fi
fi
cd "$REPO_DIR"

# --- ffmpeg ---------------------------------------------------------------------
if command -v ffmpeg >/dev/null 2>&1; then
  say "ffmpeg already installed"
elif [[ "$OSTYPE" == darwin* ]]; then
  command -v brew >/dev/null 2>&1 || {
    echo "Homebrew is required: https://brew.sh"; exit 1;
  }
  say "installing ffmpeg via Homebrew"
  brew install ffmpeg
else
  say "installing ffmpeg via apt"
  sudo apt-get update -qq && sudo apt-get install -y ffmpeg python3-venv
fi

# --- python env -----------------------------------------------------------------
say "creating .venv and installing dependencies"
python3 -m venv .venv
./.venv/bin/pip install -q --upgrade pip
./.venv/bin/pip install -q -r requirements.txt
./.venv/bin/playwright install chromium

# --- api keys -------------------------------------------------------------------
if [[ ! -f .env ]]; then
  cat > .env <<'EOF'
# Free keys. One is enough; the agent fails over between them.
#   https://aistudio.google.com/apikey   https://cloud.cerebras.ai   https://console.groq.com/keys
GEMINI_API_KEY=
CEREBRAS_API_KEY=
GROQ_API_KEY=
EOF
  say "created .env - paste at least one free API key into it"
fi

./.venv/bin/python -m ytmusic doctor || true

cat <<EOF

$(say "setup complete")
Repo:   $REPO_DIR
Keys:   $REPO_DIR/.env   (add at least one, they are free)

Daily use, two commands:

  1) start a Chrome the agent can drive, and log into Suno in it - once per reboot:
       ./scripts/suno-chrome.sh

  2) generate today's batch:
       ./scripts/daily.sh              # or: YTMUSIC_COUNT=10 ./scripts/daily.sh

Videos land in $REPO_DIR/out/\$(date +%F)/ with a printed upload checklist.
EOF
