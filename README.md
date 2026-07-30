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
| Ideas, lyrics, Suno prompts, titles, descriptions, tags | Gemini `gemini-flash-latest`, or Groq Llama 3.3 70B | free tier | offline template fallback needs no key at all |
| Music | Suno, browser-driven | your existing plan | no public API exists; paid plan also gives commercial-use rights |
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

## Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium      # only needed for the Suno stage
sudo apt-get install -y ffmpeg   # ffmpeg + ffprobe must be on PATH
python -m ytmusic doctor         # verifies binaries and API keys
```

Keys are read from the environment:

```bash
export GEMINI_API_KEY=...   # https://aistudio.google.com/apikey  (free)
export GROQ_API_KEY=...     # https://console.groq.com/keys       (free, fallback)
```

Neither is mandatory: with no keys the planner falls back to built-in templates.

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
