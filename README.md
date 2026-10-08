# yt-music-agent

Produces a **daily batch of 5–10 upload-ready YouTube music videos** — music, cover art,
thumbnail, title, description and tags — using free tools plus your existing Suno plan.
You review and upload manually; nothing is published automatically.

```
python -m ytmusic run -n 6
```

```
out/2026-07-30/
├── 01_raindrops-on-midnight-glass/
│   ├── video.mp4        1080p, Ken Burns art + audio visualizer, -14 LUFS
│   ├── thumbnail.jpg    1280x720 with the title burned in
│   ├── cover.jpg        clean artwork (no text)
│   ├── audio.mp3        the Suno track
│   ├── metadata.txt     title / description / tags in upload-form order
│   └── manifest.json
├── 02_.../
├── mix.mp4              optional continuous mix of the whole batch
├── mix_metadata.txt     tracklist with timestamps
├── suno_prompts.txt     copy-paste sheet, in case you'd rather prompt by hand
├── batch.json
└── UPLOAD.md            checklist + summary table
```

## Why this tool chain

| Stage | Tool | Cost | Notes |
| ----- | ---- | ---- | ----- |
| Ideas, lyrics, Suno prompts, titles, descriptions, tags | Gemini `gemini-flash-latest`, Cerebras or Groq Llama 3.3 70B | free tier | tried in that order; offline template fallback needs no key at all |
| Music | Suno, browser-driven | your existing plan | no public API exists; paid plan also gives commercial-use rights |
| Music (cloud, no browser) | ACE-Step 3.5B, Apache-2.0 | free on a Colab GPU | `--music acestep`; great for long instrumentals, weak at Hindi vocals |
| Cover art | Pollinations (Flux) → Nano Banana → local Pillow renderer | free | first provider that answers wins |
| Video | FFmpeg | free | unlimited length, no quota, no watermark |
| Metadata | same LLM | free | written straight into upload-form order |

**Why not Veo / Flow for the video?** Their free allowances are a handful of ~8 second
clips per day, which cannot cover 5–10 videos of several minutes each. FFmpeg gives
unlimited 1080p renders for free, and for background-music videos a slow Ken Burns push
with a reactive visualizer is what the genre actually uses. If you have Google AI Pro,
generate a Veo clip yourself and drop it in as the background — see *Custom backgrounds*.

**Nano Banana caveat.** Gemini image output is not part of the Gemini API free tier: with
a keyless-billing project it returns HTTP 429. Pollinations is therefore first in the
chain by default. Once billing is enabled on your key, reorder `art.providers` to put
`gemini` first.

## Content types and the cinematic thumbnail

`content.mix` is cycled across the batch, so one run can mix formats:

| Type | What the planner writes | Thumbnail extras |
| ---- | ----------------------- | ---------------- |
| `original` | an original song with its own lyrics | – |
| `cover` | a classic film song reimagined in a modern style; credits are filled in and the Suno sheet tells you to paste the original lyrics yourself | original-song credits box + rights disclaimer bar |
| `instrumental` | a long (6–10 min) raga / ambient / meditation piece, curiosity-driven title | length badge |

With `art.thumbnail_style: cinematic` every thumbnail is composited to the same
layout: `AI MUSIC` and quality badges, a kicker, an oversized title (Devanagari
when `content.script: devanagari`), a tagline, the `channel.artist` line, feature
chips and a duration pill. Fonts are pulled once from the Google Fonts mirror
into `~/.cache/yt-music-agent/fonts`; the art prompt is automatically extended to
keep the subject on the right so the type has room on the left.

Set `art.thumbnail_style: simple` for the plain title-over-art thumbnail.

## Fully automatic in the cloud (ACE-Step + Colab)

`notebooks/ytmusic_colab.ipynb` runs the whole batch on Colab's free T4: installs
ACE-Step, generates the tracks, renders artwork/thumbnails/videos/metadata and
zips the output (optionally to Drive). No browser, no login, no Cloudflare.

ACE-Step is Apache-2.0 with open weights, and it is good at instrumental,
ambient and raga material — but it does not sing Hindi lyrics anywhere near Suno
quality. The practical split is: vocal songs on Suno from your own machine,
long instrumentals in Colab.

## Install

One command, macOS or Linux — installs ffmpeg, the virtualenv, Playwright's Chromium and
writes a `.env` stub. Safe to re-run:

```bash
curl -fsSL https://raw.githubusercontent.com/coolcryptomaniac/Yt-music-agent/main/scripts/setup.sh | bash
```

Windows (PowerShell):

```powershell
irm https://raw.githubusercontent.com/coolcryptomaniac/Yt-music-agent/main/scripts/setup.ps1 | iex
```

Then, daily:

```bash
./scripts/suno-chrome.sh    # once per reboot: opens the Chrome the agent drives; log into Suno
./scripts/daily.sh          # YTMUSIC_COUNT=10 ./scripts/daily.sh for a bigger batch
```

<details><summary>Manual install</summary>

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium      # only needed for the Suno stage
sudo apt-get install -y ffmpeg   # ffmpeg + ffprobe must be on PATH
python -m ytmusic doctor         # verifies binaries and API keys
```

</details>

Keys are read from the environment (or a `.env` file next to the repo, which
`scripts/daily.sh` sources automatically):

```bash
export GEMINI_API_KEY=...     # https://aistudio.google.com/apikey  (free)
export CEREBRAS_API_KEY=...   # https://cloud.cerebras.ai           (free, fastest)
export GROQ_API_KEY=...       # https://console.groq.com/keys       (free)
```

None are mandatory: with no keys the planner falls back to built-in templates. With
several, the others act as automatic failover when one is rate-limited or down
(both happen regularly on free tiers).

## Suno login

Automation attaches to a **real Chrome you are already logged into**, so no Suno
credentials are ever stored:

```bash
google-chrome --remote-debugging-port=29229 &   # log into suno.com in this window
python -m ytmusic login                          # confirms the session is live
```

Set `suno.cdp_endpoint` in `config.yaml` if you use a different port. With no debuggable
Chrome available, the agent launches its own persistent profile
(`~/.config/yt-music-agent/chrome`) — log in there once and it is remembered.

### Run the Suno stage from your own machine

Pressing **Create** triggers a Cloudflare Turnstile check. On a normal home connection it
passes invisibly; on a cloud VM, VPN or datacenter IP it shows the "Verify you are human"
checkbox and — verified on a Devin VM — keeps re-issuing the challenge no matter how many
times it is clicked, by hand or otherwise. That is an IP-reputation gate, not something the
selectors can work around, so run `--music suno` on the computer you normally browse Suno
on. The agent pauses up to `suno.human_check_timeout` seconds for a challenge to be cleared
before failing with a clear error.

Cloud/CI hosts should use the two-step split instead:

```bash
python -m ytmusic plan -n 6                # prompts -> suno_prompts.txt, paste into suno.com
# drop the downloaded mp3/wav files into ./inbox
python -m ytmusic run -n 6 --music inbox   # art, video, thumbnails, metadata
```

## Daily use

```bash
python -m ytmusic plan -n 6          # dry run: see the ideas and prompts, generate nothing
python -m ytmusic run -n 6           # the full batch
python -m ytmusic run -n 8 --music inbox   # skip Suno, use audio you already exported
python -m ytmusic run -n 3 --music synth   # offline smoke test, placeholder audio
python -m ytmusic run --no-mix --visualizer showwaves
```

`scripts/daily.sh` is a cron-ready wrapper:

```cron
0 7 * * * /home/you/yt-music-agent/scripts/daily.sh >> /home/you/ytmusic.log 2>&1
```

Then each morning open today's `out/<date>/UPLOAD.md` and upload.

## Tuning the channel

Almost everything worth changing lives in `config.yaml`:

* `channel.niche` — the single highest-leverage field. It steers ideas, prompts, art and
  metadata. Rewrite it for sleep music, dark ambient, synthwave, Indian classical fusion, etc.
* `batch.count` — 5–10 recommended.
* `music.instrumental` — set `false` to get Suno lyrics generated as well.
* `video.visualizer` — `showcqt` (bars), `showwaves` (waveform), `none`.
* `video.render_mix` — the long mix usually out-performs single tracks on watch time.
* `metadata.base_tags` — tags appended to every video.

`state.json` remembers used titles so later batches don't repeat themselves.

## Custom backgrounds

To use your own visual (a Veo clip, a looping video, a photo) for one track, drop it into
the track folder as `cover.jpg` and re-run just the render stage:

```python
from ytmusic.config import load_config
from ytmusic.video import render_track
config = load_config()
render_track(config, Path("out/2026-07-30/01_x/cover.jpg"),
             Path("out/2026-07-30/01_x/audio.mp3"),
             Path("out/2026-07-30/01_x/video.mp4"))
```

## When Suno's UI changes

Selectors are lists of candidates in `suno.py` and overridable in `config.yaml`:

```yaml
suno:
  cdp_endpoint: "http://localhost:29229"
  selectors:
    create_button: ['button:has-text("Create")', "#new-create-btn"]
```

Audio itself is harvested from Suno's JSON traffic rather than the download menu, which
is far more stable. If a run still fails, `suno_prompts.txt` holds every prompt for
manual entry and the pipeline continues with art, video and metadata for whatever audio
did arrive.

## Compliance notes

* Suno's commercial-use rights come with **paid** plans; free-tier output is
  non-commercial. Keep the paid plan active while monetising.
* Music is regenerated per batch rather than reused, which keeps uploads from being
  flagged as repetitious.
* Upload manually and review each video before publishing — automated bulk publishing is
  what gets channels penalised, not AI-assisted production.
