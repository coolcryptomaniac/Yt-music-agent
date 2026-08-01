# Starts the Chrome the agent drives, in a dedicated profile, with remote debugging on.
# Log into suno.com in the window it opens; the login is remembered across reboots.
$ErrorActionPreference = "Stop"

$Port = if ($env:YTMUSIC_CDP_PORT) { $env:YTMUSIC_CDP_PORT } else { 29229 }
$Profile = if ($env:YTMUSIC_CHROME_PROFILE) { $env:YTMUSIC_CHROME_PROFILE } else { "$HOME\.yt-music-agent\chrome" }
New-Item -ItemType Directory -Force -Path $Profile | Out-Null

try {
    Invoke-RestMethod "http://localhost:$Port/json/version" -TimeoutSec 2 | Out-Null
    Write-Host "Chrome is already listening on port $Port - nothing to do."
    exit 0
} catch {}

$Chrome = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Chrome) { throw "Google Chrome not found - install it first." }

Start-Process $Chrome -ArgumentList "--remote-debugging-port=$Port", "--user-data-dir=`"$Profile`"", "https://suno.com/create"
Write-Host "Chrome starting on port $Port (profile: $Profile)."
Write-Host "Sign into Suno in that window, then run: .\.venv\Scripts\python.exe -m ytmusic run -n 6"
