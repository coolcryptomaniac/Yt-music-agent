"""FFmpeg video rendering.

One track -> one 1080p video: slow Ken Burns push-in over the cover art, an
audio-reactive visualizer strip along the bottom, and loudness-normalised audio.
Optionally the whole batch is also concatenated into a single long "mix" video
with chapter timestamps.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Sequence
from pathlib import Path

from .audio import probe_duration
from .config import Config

LOGGER = logging.getLogger(__name__)


class RenderError(RuntimeError):
    pass


def _run(command: Sequence[str]) -> None:
    LOGGER.debug("ffmpeg: %s", " ".join(command))
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        tail = "\n".join(result.stderr.strip().splitlines()[-15:])
        raise RenderError(f"ffmpeg failed ({result.returncode}):\n{tail}")


def _visualizer_filter(config: Config, width: int, height: int, fps: int) -> str | None:
    kind = str(config.get("video.visualizer", "showcqt")).lower()
    if kind in {"none", "", "off"}:
        return None
    strip_height = int(config.get("video.visualizer_height", 220))
    opacity = float(config.get("video.visualizer_opacity", 0.7))
    if kind == "showwaves":
        generator = (
            f"showwaves=s={width}x{strip_height}:mode=cline:rate={fps}:colors=white|0x88aaff"
        )
    else:
        generator = (
            f"showcqt=s={width}x{strip_height}:fps={fps}:count=2:bar_g=2:sono_g=3"
            ":axisfile=:axis_h=0:sono_h=0"
        )
    del height
    return f"[1:a]{generator},format=rgba,colorchannelmixer=aa={opacity}[vis]"


def render_track(
    config: Config,
    art: Path,
    audio: Path,
    destination: Path,
    duration: float | None = None,
) -> tuple[Path, float]:
    """Render a single track video. Returns (path, duration_seconds)."""
    width = int(config.get("video.width", 1920))
    height = int(config.get("video.height", 1080))
    fps = int(config.get("video.fps", 24))
    seconds = duration if duration is not None else probe_duration(audio)
    frames = max(fps, int(seconds * fps))

    zoom_rate = float(config.get("video.zoom_per_second", 0.012)) / fps
    # Oversample the still before zoompan so the push-in stays sharp.
    background = (
        f"[0:v]scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,"
        f"crop={width * 2}:{height * 2},"
        f"zoompan=z='min(1+{zoom_rate:.8f}*on,1.25)'"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d=1:s={width}x{height}:fps={fps},"
        f"trim=duration={seconds:.3f},setsar=1[bg]"
    )

    visualizer = _visualizer_filter(config, width, height, fps)
    if visualizer:
        filter_complex = (
            f"{background};{visualizer};[bg][vis]overlay=x=0:y=H-h:format=auto:shortest=1[v]"
        )
    else:
        filter_complex = f"{background.replace('[bg]', '[v]')}"

    audio_chain = "anull"
    if bool(config.get("video.loudnorm", True)):
        audio_chain = "loudnorm=I=-14:TP=-1.5:LRA=11"

    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-loop",
        "1",
        "-framerate",
        str(fps),
        "-t",
        f"{seconds:.3f}",
        "-i",
        str(art),
        "-i",
        str(audio),
        "-filter_complex",
        filter_complex,
        "-map",
        "[v]",
        "-map",
        "1:a",
        "-af",
        audio_chain,
        "-frames:v",
        str(frames),
        "-c:v",
        "libx264",
        "-preset",
        str(config.get("video.preset", "veryfast")),
        "-crf",
        str(config.get("video.crf", 20)),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-c:a",
        "aac",
        "-b:a",
        str(config.get("video.audio_bitrate", "320k")),
        "-shortest",
        str(destination),
    ]
    _run(command)
    LOGGER.info("rendered %s (%.1fs)", destination.name, seconds)
    return destination, seconds


def concat_audio(
    config: Config, tracks: Sequence[Path], destination: Path
) -> tuple[Path, list[float]]:
    """Concatenate track audio with a configurable gap. Returns (path, start_offsets)."""
    gap = float(config.get("video.mix_gap_seconds", 1.0))
    inputs: list[str] = []
    parts: list[str] = []
    offsets: list[float] = []
    cursor = 0.0
    for index, track in enumerate(tracks):
        inputs.extend(["-i", str(track)])
        parts.append(f"[{index}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo")
        offsets.append(cursor)
        cursor += probe_duration(track) + gap

    silence = f"anullsrc=r=44100:cl=stereo:d={gap}"
    chain: list[str] = []
    for index, part in enumerate(parts):
        chain.append(f"{part}[a{index}]")
        if index < len(parts) - 1:
            chain.append(f"aevalsrc=0:s=44100:c=stereo:d={gap}[g{index}]")
    del silence

    stream_order = "".join(
        f"[a{i}]" + (f"[g{i}]" if i < len(parts) - 1 else "") for i in range(len(parts))
    )
    total_streams = len(parts) * 2 - 1
    filter_complex = (
        ";".join(chain) + f";{stream_order}concat=n={total_streams}:v=0:a=1,volume=1.0[out]"
    )

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
        "320k",
        str(destination),
    ]
    _run(command)
    return destination, offsets
