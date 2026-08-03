"""ACE-Step music generation - the fully-automatable alternative to Suno.

ACE-Step is Apache-2.0 (weights included), so unlike MusicGen its output can be
monetised, and unlike Suno it needs no browser, no login and no Cloudflare check:
a batch can run unattended on any GPU box or a free Colab runtime.

The model is heavy (3.5B, ~8GB of weights) and torch is not a dependency of this
package, so everything is imported lazily and the pipeline is cached across the
tracks of a batch - loading it once per run instead of once per track is the
difference between a 6-track batch taking 5 minutes and taking half an hour.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .config import Config
from .models import TrackPlan

LOGGER = logging.getLogger(__name__)

_PIPELINE: Any = None


class AceStepError(RuntimeError):
    pass


def _pipeline(config: Config) -> Any:
    """Load (once) and return the ACE-Step pipeline."""
    global _PIPELINE
    if _PIPELINE is not None:
        return _PIPELINE
    try:
        from acestep.pipeline_ace_step import ACEStepPipeline
    except ImportError as exc:  # noqa: BLE001 - optional heavy dependency
        raise AceStepError(
            "ACE-Step is not installed. Run: "
            "pip install git+https://github.com/ace-step/ACE-Step.git "
            "(needs a GPU; see notebooks/ytmusic_colab.ipynb for a free one)"
        ) from exc

    checkpoint = config.get("acestep.checkpoint_dir")
    LOGGER.info("loading ACE-Step (first run downloads ~8GB of weights)")
    _PIPELINE = ACEStepPipeline(
        checkpoint_dir=str(checkpoint) if checkpoint else None,
        dtype=str(config.get("acestep.dtype", "bfloat16")),
        torch_compile=bool(config.get("acestep.torch_compile", False)),
        cpu_offload=bool(config.get("acestep.cpu_offload", False)),
        overlapped_decode=bool(config.get("acestep.overlapped_decode", False)),
    )
    return _PIPELINE


def prompt_for(plan: TrackPlan) -> str:
    """ACE-Step wants comma-separated tags, not prose."""
    tags = [plan.suno_style.rstrip(". ")]
    if plan.instrumental:
        tags.append("instrumental")
    return ", ".join(tags)


def generate(config: Config, plan: TrackPlan, destination: Path) -> Path:
    """Render one track to `destination` (suffix chosen from acestep.format)."""
    pipeline = _pipeline(config)
    fmt = str(config.get("acestep.format", "wav")).lower()
    target = destination.with_suffix(f".{fmt}")
    target.parent.mkdir(parents=True, exist_ok=True)

    duration = float(config.get("acestep.duration", config.get("music.min_duration", 120)))
    seed = config.get("batch.seed")
    LOGGER.info("track %02d: generating %.0fs with ACE-Step", plan.index, duration)
    pipeline(
        format=fmt,
        audio_duration=duration,
        prompt=prompt_for(plan),
        lyrics="" if plan.instrumental else plan.suno_lyrics,
        infer_step=int(config.get("acestep.infer_step", 60)),
        guidance_scale=float(config.get("acestep.guidance_scale", 15.0)),
        scheduler_type=str(config.get("acestep.scheduler", "euler")),
        manual_seeds=None if seed is None else [int(seed) + plan.index],
        save_path=str(target),
        batch_size=1,
    )
    if not target.exists():
        raise AceStepError(f"ACE-Step produced no file at {target}")
    return target
