"""Upload-ready metadata files.

Each track folder gets a `metadata.txt` laid out in the exact order of the YouTube
upload form, so uploading is copy-paste with no thinking. The batch folder gets an
`UPLOAD.md` checklist plus `batch.json` for programmatic use later.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from .config import Config
from .models import TrackArtifacts, TrackPlan


def _timestamp(seconds: float) -> str:
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def full_description(config: Config, plan: TrackPlan, extra: str = "") -> str:
    parts: list[str] = [plan.description.strip()]
    if extra.strip():
        parts.append(extra.strip())
    hashtags = " ".join(f"#{tag.replace(' ', '')}" for tag in plan.tags[:3])
    if hashtags:
        parts.append(hashtags)
    cta = str(config.get("channel.cta", "") or "").strip()
    legal = str(config.get("channel.legal", "") or "").strip()
    if cta:
        parts.append(cta)
    if legal:
        parts.append(legal)
    return "\n\n".join(part for part in parts if part).strip() + "\n"


def write_track_metadata(config: Config, artifacts: TrackArtifacts) -> Path:
    plan = artifacts.plan
    target = artifacts.directory / "metadata.txt"
    body = "\n".join(
        [
            "==================== TITLE ====================",
            plan.youtube_title or plan.title,
            "",
            "================= DESCRIPTION =================",
            full_description(config, plan),
            "==================== TAGS =====================",
            ", ".join(plan.tags),
            "",
            "=================== UPLOAD ====================",
            f"video      : {artifacts.video.name if artifacts.video else '(missing)'}",
            f"thumbnail  : {artifacts.thumbnail.name if artifacts.thumbnail else '(missing)'}",
            f"duration   : {_timestamp(artifacts.duration)}",
            "visibility : Public",
            "category   : Music",
            "audience   : Not made for kids",
            "playlist   : " + str(config.get("channel.name", "")),
            "",
            "=============== SOURCE PROMPTS ================",
            f"suno style : {plan.suno_style}",
            f"art prompt : {plan.art_prompt}",
            "",
        ]
    )
    target.write_text(body, encoding="utf-8")
    return target


def mix_description(
    config: Config,
    artifacts: Sequence[TrackArtifacts],
    offsets: Sequence[float],
) -> str:
    lines = [
        f"{config.get('channel.name', 'Mix')} \u2014 {len(artifacts)} track continuous mix.",
        "",
        "Tracklist:",
    ]
    for artifact, offset in zip(artifacts, offsets, strict=False):
        lines.append(f"{_timestamp(offset)} {artifact.plan.title}")
    cta = str(config.get("channel.cta", "") or "").strip()
    legal = str(config.get("channel.legal", "") or "").strip()
    if cta:
        lines.extend(["", cta])
    if legal:
        lines.extend(["", legal])
    return "\n".join(lines) + "\n"


def write_batch_summary(
    config: Config,
    batch_dir: Path,
    artifacts: Sequence[TrackArtifacts],
    mix_video: Path | None = None,
) -> Path:
    rows = [
        "| # | title | duration | video | thumbnail |",
        "| - | ----- | -------- | ----- | --------- |",
    ]
    for artifact in artifacts:
        rows.append(
            "| {idx} | {title} | {dur} | {video} | {thumb} |".format(
                idx=artifact.plan.index,
                title=artifact.plan.title,
                dur=_timestamp(artifact.duration),
                video=artifact.video.name if artifact.video else "-",
                thumb=artifact.thumbnail.name if artifact.thumbnail else "-",
            )
        )

    checklist = [
        f"# Upload batch {date.today().isoformat()} \u2014 {config.get('channel.name', '')}",
        "",
        f"{len(artifacts)} videos ready. Each folder contains `video.mp4`, `thumbnail.jpg` "
        "and `metadata.txt` (title / description / tags in upload-form order).",
        "",
        *rows,
        "",
        "## Steps",
        "1. youtube.com/upload \u2014 drag in `video.mp4`.",
        "2. Paste TITLE, DESCRIPTION and TAGS from `metadata.txt`.",
        "3. Upload `thumbnail.jpg`.",
        "4. Set 'Not made for kids', category Music, add to playlist.",
        "5. Schedule ~1 upload per day rather than publishing all at once.",
        "",
    ]
    if mix_video:
        checklist.extend(
            [
                "## Long mix",
                f"`{mix_video.name}` is the full-batch continuous mix; its description "
                "with timestamps is in `mix_metadata.txt`. Upload it last.",
                "",
            ]
        )

    notes = [artifact for artifact in artifacts if artifact.notes]
    if notes:
        checklist.append("## Notes")
        for artifact in notes:
            for note in artifact.notes:
                checklist.append(f"- {artifact.plan.index:02d} {artifact.plan.title}: {note}")
        checklist.append("")

    target = batch_dir / "UPLOAD.md"
    target.write_text("\n".join(checklist), encoding="utf-8")

    (batch_dir / "batch.json").write_text(
        json.dumps([artifact.to_dict() for artifact in artifacts], indent=2),
        encoding="utf-8",
    )
    return target
