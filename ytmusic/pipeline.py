"""Batch orchestration: plan -> music -> art -> video -> metadata."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from . import art as art_mod
from . import audio as audio_mod
from . import metadata as meta_mod
from . import video as video_mod
from .config import Config
from .models import TrackArtifacts, TrackPlan
from .planner import build_plans, remember_titles
from .suno import SunoError, SunoSession, write_manual_prompts

LOGGER = logging.getLogger(__name__)


def batch_directory(config: Config, label: str | None = None) -> Path:
    root = config.resolve_path("paths.out")
    target = root / (label or date.today().isoformat())
    target.mkdir(parents=True, exist_ok=True)
    return target


def _pick_variant(config: Config, clips: Sequence[dict], session: SunoSession, dest: Path) -> Path:
    """Download Suno variants and keep the preferred one."""
    strategy = str(config.get("music.variant_pick", "longest")).lower()
    downloaded: list[Path] = []
    for index, clip in enumerate(clips[:2]):
        candidate = session.download(clip["audio_url"], dest.with_name(f"{dest.stem}_v{index + 1}"))
        downloaded.append(candidate)
    if not downloaded:
        raise SunoError("no clips downloaded")
    if strategy == "longest" and len(downloaded) > 1:
        chosen = max(downloaded, key=audio_mod.probe_duration)
    else:
        chosen = downloaded[0]
    for extra in downloaded:
        if extra != chosen:
            extra.unlink(missing_ok=True)
    final = dest.with_suffix(chosen.suffix)
    chosen.rename(final)
    return final


def acquire_audio(
    config: Config,
    plan: TrackPlan,
    directory: Path,
    session: SunoSession | None,
    notes: list[str],
) -> Path | None:
    provider = str(config.get("music.provider", "suno")).lower()
    target = directory / "audio"
    min_duration = float(config.get("music.min_duration", 90))

    if provider == "synth":
        return audio_mod.synth_placeholder(plan, target)

    if provider == "inbox":
        claimed = audio_mod.take_from_inbox(config, plan, target)
        if claimed is None:
            notes.append("no audio left in ./inbox")
        return claimed

    if provider == "suno":
        if session is None:
            notes.append("suno session unavailable")
            return None
        try:
            before = session.known_clip_ids
            session.submit(plan)
            clips = session.wait_for_audio(exclude=before)
            audio_path = _pick_variant(config, clips, session, target)
        except SunoError as exc:
            LOGGER.warning("track %02d: suno failed: %s", plan.index, exc)
            notes.append(f"suno failed: {exc}")
            return None
        duration = audio_mod.probe_duration(audio_path)
        if duration < min_duration:
            notes.append(f"short track ({duration:.0f}s < {min_duration:.0f}s)")
        return audio_path

    raise ValueError(f"unknown music provider: {provider}")


def produce_batch(
    config: Config,
    count: int | None = None,
    label: str | None = None,
    plans: list[TrackPlan] | None = None,
) -> list[TrackArtifacts]:
    plans = plans or build_plans(config, count)
    batch_dir = batch_directory(config, label)
    write_manual_prompts(plans, batch_dir / "suno_prompts.txt")

    provider = str(config.get("music.provider", "suno")).lower()
    session: SunoSession | None = None
    results: list[TrackArtifacts] = []

    def run_all() -> None:
        for plan in plans:
            directory = batch_dir / plan.folder_name()
            directory.mkdir(parents=True, exist_ok=True)
            artifacts = TrackArtifacts(plan=plan, directory=directory)
            LOGGER.info("=== track %02d/%02d: %s", plan.index, len(plans), plan.title)

            artifacts.audio = acquire_audio(config, plan, directory, session, artifacts.notes)

            cover, used = art_mod.generate_cover(config, plan, directory / "cover.jpg")
            artifacts.art = cover
            if used == "local":
                artifacts.notes.append("cover art used the offline fallback renderer")
            artifacts.thumbnail = art_mod.make_thumbnail(
                config, plan, cover, directory / "thumbnail.jpg"
            )

            if artifacts.audio is not None:
                try:
                    video, duration = video_mod.render_track(
                        config, cover, artifacts.audio, directory / "video.mp4"
                    )
                    artifacts.video = video
                    artifacts.duration = duration
                except video_mod.RenderError as exc:
                    LOGGER.error("track %02d: render failed: %s", plan.index, exc)
                    artifacts.notes.append(f"render failed: {exc}")
            else:
                artifacts.notes.append("no audio, video not rendered")

            meta_mod.write_track_metadata(config, artifacts)
            artifacts.write_manifest()
            results.append(artifacts)

    if provider == "suno":
        with SunoSession(config) as active:
            if not active.ensure_logged_in():
                raise SunoError(
                    "Suno is not logged in. Open https://suno.com in the browser, sign in, "
                    "then re-run. Prompts were saved to suno_prompts.txt."
                )
            active.open_create()
            session = active
            run_all()
    else:
        run_all()

    mix_video: Path | None = None
    renderable = [item for item in results if item.audio and item.video]
    if bool(config.get("video.render_mix", True)) and len(renderable) > 1:
        try:
            mix_audio, offsets = video_mod.concat_audio(
                config, [item.audio for item in renderable if item.audio], batch_dir / "mix.mp3"
            )
            mix_cover = renderable[0].art
            assert mix_cover is not None
            mix_thumb = art_mod.make_mix_thumbnail(
                config,
                [item.plan.title for item in renderable],
                mix_cover,
                batch_dir / "mix_thumbnail.jpg",
            )
            mix_video, _ = video_mod.render_track(
                config, mix_cover, mix_audio, batch_dir / "mix.mp4"
            )
            (batch_dir / "mix_metadata.txt").write_text(
                meta_mod.mix_description(config, renderable, offsets), encoding="utf-8"
            )
            LOGGER.info("mix video ready: %s (thumb %s)", mix_video.name, mix_thumb.name)
        except (video_mod.RenderError, audio_mod.AudioError) as exc:
            LOGGER.warning("mix render skipped: %s", exc)

    meta_mod.write_batch_summary(config, batch_dir, results, mix_video)
    remember_titles(config.resolve_path("paths.state"), [plan.title for plan in plans])
    return results
