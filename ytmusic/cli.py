"""Command line entrypoint: `python -m ytmusic ...`."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from .config import Config, load_config
from .models import TrackPlan
from .pipeline import batch_directory, produce_batch
from .planner import build_plans
from .suno import SunoSession, write_manual_prompts


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def _apply_overrides(config: Config, args: argparse.Namespace) -> None:
    if args.count is not None:
        config.set("batch.count", args.count)
    if args.music is not None:
        config.set("music.provider", args.music)
    if args.llm is not None:
        config.set("llm.provider", args.llm)
    if args.niche is not None:
        config.set("channel.niche", args.niche)
    if args.channel is not None:
        config.set("channel.name", args.channel)
    if args.no_mix:
        config.set("video.render_mix", False)
    if args.visualizer is not None:
        config.set("video.visualizer", args.visualizer)
    if args.seed is not None:
        config.set("batch.seed", args.seed)


def _print_plans(plans: Sequence[TrackPlan]) -> None:
    for plan in plans:
        print(f"\n[{plan.index:02d}] {plan.title}  ({plan.genre}, {plan.mood}, {plan.bpm} bpm)")
        print(f"  youtube : {plan.youtube_title}")
        print(f"  suno    : {plan.suno_style}")
        print(f"  art     : {plan.art_prompt}")
        print(f"  tags    : {', '.join(plan.tags[:8])}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ytmusic",
        description="Generate a daily batch of upload-ready YouTube music videos.",
    )
    parser.add_argument("command", choices=["run", "plan", "login", "doctor"], help="what to do")
    parser.add_argument("-c", "--config", default=None, help="path to config.yaml")
    parser.add_argument("-n", "--count", type=int, default=None, help="tracks in this batch")
    parser.add_argument(
        "--music", choices=["suno", "inbox", "synth"], default=None, help="audio source"
    )
    parser.add_argument("--llm", choices=["gemini", "cerebras", "groq", "offline"], default=None)
    parser.add_argument("--niche", default=None, help="override the channel niche for this run")
    parser.add_argument("--channel", default=None, help="override the channel name")
    parser.add_argument("--label", default=None, help="output folder name (default: today)")
    parser.add_argument("--visualizer", choices=["showcqt", "showwaves", "none"], default=None)
    parser.add_argument("--no-mix", action="store_true", help="skip the long-mix render")
    parser.add_argument("--seed", type=int, default=None, help="deterministic offline planning")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    _configure_logging(args.verbose)
    config = load_config(args.config)
    _apply_overrides(config, args)

    if args.command == "doctor":
        return _doctor(config)

    if args.command == "login":
        with SunoSession(config) as session:
            ok = session.ensure_logged_in()
            print("suno: logged in" if ok else "suno: NOT logged in - sign in, then re-run")
            shot = session.screenshot(Path("suno_login.png"))
            if shot:
                print(f"screenshot: {shot}")
        return 0 if ok else 1

    if args.command == "plan":
        plans = build_plans(config, args.count)
        _print_plans(plans)
        target = batch_directory(config, args.label) / "suno_prompts.txt"
        write_manual_prompts(plans, target)
        print(f"\nprompt sheet: {target}")
        return 0

    artifacts = produce_batch(config, count=args.count, label=args.label)
    ready = [item for item in artifacts if item.video]
    batch_dir = artifacts[0].directory.parent if artifacts else batch_directory(config, args.label)
    print(f"\n{len(ready)}/{len(artifacts)} videos rendered -> {batch_dir}")
    print(f"upload checklist: {batch_dir / 'UPLOAD.md'}")
    return 0 if ready else 1


def _doctor(config: Config) -> int:
    import os
    import shutil

    print("== yt-music-agent doctor ==")
    ok = True
    for binary in ("ffmpeg", "ffprobe"):
        path = shutil.which(binary)
        print(f"{binary:10s}: {path or 'MISSING'}")
        ok = ok and bool(path)

    for name in ("GEMINI_API_KEY", "CEREBRAS_API_KEY", "GROQ_API_KEY"):
        print(f"{name:16s}: {'set' if os.environ.get(name) else 'not set'}")

    try:
        import playwright  # noqa: F401

        print("playwright     : installed")
    except ImportError:
        print("playwright     : MISSING (pip install playwright && playwright install chromium)")
        ok = False

    print(f"music provider : {config.get('music.provider')}")
    print(f"llm provider   : {config.get('llm.provider')}")
    print(f"output dir     : {config.resolve_path('paths.out')}")
    print(f"inbox dir      : {config.resolve_path('paths.inbox')}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
