"""Audio acquisition.

Providers:
  suno  - drives suno.com in a real logged-in Chrome via Playwright/CDP.
  inbox - consumes audio files you dropped in ./inbox (any Suno/DAW export).
  synth - ffmpeg-generated ambient pad, for offline pipeline smoke tests.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from .config import Config
from .models import TrackPlan

LOGGER = logging.getLogger(__name__)

AUDIO_SUFFIXES = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".opus"}


class AudioError(RuntimeError):
    pass


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        raise AudioError(f"could not read duration of {path}: {result.stderr.strip()}") from None


def inbox_candidates(config: Config) -> list[Path]:
    inbox = config.resolve_path("paths.inbox")
    if not inbox.exists():
        return []
    return sorted(
        item for item in inbox.iterdir() if item.is_file() and item.suffix.lower() in AUDIO_SUFFIXES
    )


def take_from_inbox(config: Config, plan: TrackPlan, destination: Path) -> Path | None:
    """Claim the next unused inbox file for this plan (moved, not copied)."""
    candidates = inbox_candidates(config)
    if not candidates:
        return None
    source = candidates[0]
    destination = destination.with_suffix(source.suffix.lower())
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), destination)
    LOGGER.info("track %02d: claimed %s from inbox", plan.index, source.name)
    return destination


def synth_placeholder(plan: TrackPlan, destination: Path, seconds: int = 120) -> Path:
    """Deterministic ambient pad so the video/metadata stages can be tested offline.

    Builds a detuned minor-9 chord from the plan's bpm-derived root, adds a soft
    tremolo and a filtered noise bed, then fades in/out.
    """
    root = 110.0 * (2 ** ((plan.bpm % 12) / 12.0))
    voices = [root, root * 1.5, root * 2.0 * 1.19, root * 2.5]
    inputs: list[str] = []
    for index, freq in enumerate(voices):
        inputs.extend(
            [
                "-f",
                "lavfi",
                "-t",
                str(seconds),
                "-i",
                f"sine=frequency={freq:.2f}:sample_rate=44100",
            ]
        )
        del index
    inputs.extend(["-f", "lavfi", "-t", str(seconds), "-i", "anoisesrc=color=brown:amplitude=0.25"])

    mix_inputs = "".join(f"[{i}:a]" for i in range(len(voices) + 1))
    filter_complex = (
        f"{mix_inputs}amix=inputs={len(voices) + 1}:duration=longest:weights='1 0.7 0.5 0.4 0.6'"
        ",tremolo=f=0.25:d=0.35,lowpass=f=1800,highpass=f=60"
        f",afade=t=in:st=0:d=4,afade=t=out:st={seconds - 5}:d=5,volume=0.6[out]"
    )
    destination = destination.with_suffix(".mp3")
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        *inputs,
        "-filter_complex",
        filter_complex,
        "-map",
        "[out]",
        "-c:a",
        "libmp3lame",
        "-b:a",
        "192k",
        str(destination),
    ]
    subprocess.run(command, check=True)
    LOGGER.info("track %02d: synthesised placeholder audio (%ds)", plan.index, seconds)
    return destination
