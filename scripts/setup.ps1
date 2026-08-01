# One-command setup for Windows (PowerShell).
#
#   irm https://raw.githubusercontent.com/coolcryptomaniac/Yt-music-agent/main/scripts/setup.ps1 | iex
#
# Installs ffmpeg + Python deps + Playwright's Chromium, writes .env. Safe to re-run.
$ErrorActionPreference = "Stop"

function Say($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

$RepoUrl = "https://github.com/coolcryptomaniac/Yt-music-agent.git"
if (Test-Path "$PSScriptRoot\..\pyproject.toml") {
    $RepoDir = (Resolve-Path "$PSScriptRoot\..").Path
} else {
    $RepoDir = "$HOME\Yt-music-agent"
    if (Test-Path "$RepoDir\.git") { Say "updating $RepoDir"; git -C $RepoDir pull --ff-only }
    else { Say "cloning into $RepoDir"; git clone $RepoUrl $RepoDir }
}
Set-Location $RepoDir

if (Get-Command ffmpeg -ErrorAction SilentlyContinue) { Say "ffmpeg already installed" }
else { Say "installing ffmpeg"; winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements }

Say "creating .venv and installing dependencies"
python -m venv .venv
.\.venv\Scripts\pip.exe install -q --upgrade pip
.\.venv\Scripts\pip.exe install -q -r requirements.txt
.\.venv\Scripts\playwright.exe install chromium

if (-not (Test-Path .env)) {
@"
# Free keys. One is enough; the agent fails over between them.
#   https://aistudio.google.com/apikey   https://cloud.cerebras.ai   https://console.groq.com/keys
GEMINI_API_KEY=
CEREBRAS_API_KEY=
GROQ_API_KEY=
"@ | Set-Content .env
    Say "created .env - paste at least one free API key into it"
}

.\.venv\Scripts\python.exe -m ytmusic doctor

Say "setup complete"
Write-Host @"
Daily use, two commands:

  1) start the Chrome the agent drives, and log into Suno in it - once per reboot:
       .\scripts\suno-chrome.ps1

  2) generate today's batch:
       .\.venv\Scripts\python.exe -m ytmusic run -n 6

Videos land in $RepoDir\out\<today>\ with an UPLOAD.md checklist.
"@
