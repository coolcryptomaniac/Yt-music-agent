"""Turns a channel niche into a batch of fully specified track plans."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import requests

from .config import Config
from .llm import LLM, LLMError, offline_plans
from .models import TrackPlan

LOGGER = logging.getLogger(__name__)

SYSTEM = (
    "You are a music A&R and YouTube growth strategist producing a daily batch of "
    "royalty-free background-music videos. You write Suno prompts that generate clean, "
    "loopable, broadcast-quality instrumentals, and YouTube metadata that ranks for "
    "search intent without clickbait or keyword stuffing."
)

PROMPT_TEMPLATE = """\
Channel: {channel_name}
Niche: {niche}
Language for all copy: {language}

Design {count} DISTINCT tracks for today's upload batch.
Avoid any of these already-used titles: {used_titles}

For each track return an object with exactly these keys:
- "title": short evocative track name, 2-4 words, no quotes, no emoji
- "mood": one or two words
- "genre": specific sub-genre
- "bpm": integer between 60 and 100
- "suno_style": a comma-separated Suno "Style of Music" prompt. Include sub-genre,
  mood, instrumentation, production texture, bpm and mix notes. 25-45 words.
  {vocal_rule}
- "suno_lyrics": {lyrics_rule}
- "art_prompt": a text-to-image prompt for a 16:9 cover illustration matching the track.
  Describe scene, lighting, colour palette and art style. End with
  "no text, no watermark, no logo". 25-45 words.
- "youtube_title": <= {max_title} characters, front-loads the search intent
  (what the listener wants to do while listening), then the track name. No ALL CAPS.
- "description": 90-160 words. First two lines must work as a search snippet.
  Then a short mood paragraph, then a "Best for:" list of 3-4 use cases.
- "tags": {max_tags} or fewer lowercase YouTube tags, ordered most to least relevant.

Return a JSON array of {count} objects. No prose, no markdown.
"""


def _used_titles(state_path: Path, limit: int = 120) -> list[str]:
    if not state_path.exists():
        return []
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        LOGGER.warning("could not read state file %s, ignoring history", state_path)
        return []
    titles = state.get("titles", [])
    return [str(title) for title in titles][-limit:]


def remember_titles(state_path: Path, titles: list[str]) -> None:
    state: dict[str, Any] = {"titles": []}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            state = {"titles": []}
    known = list(state.get("titles", []))
    known.extend(titles)
    state["titles"] = known[-500:]
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _coerce_plan(index: int, raw: dict[str, Any], instrumental: bool, config: Config) -> TrackPlan:
    title = str(raw.get("title") or f"Untitled {index}").strip()
    max_title = int(config.get("metadata.max_title_chars", 95))
    max_tags = int(config.get("metadata.max_tags", 25))
    base_tags = [str(tag) for tag in config.get("metadata.base_tags", [])]

    tags: list[str] = []
    for tag in list(raw.get("tags") or []) + base_tags:
        tag = str(tag).strip().lower()
        if tag and tag not in tags:
            tags.append(tag)

    youtube_title = str(raw.get("youtube_title") or title).strip()[:max_title]
    lyrics = "" if instrumental else str(raw.get("suno_lyrics") or "").strip()

    try:
        bpm = int(raw.get("bpm") or 75)
    except (TypeError, ValueError):
        bpm = 75

    return TrackPlan(
        index=index,
        title=title,
        mood=str(raw.get("mood") or "calm").strip(),
        genre=str(raw.get("genre") or "lofi hip hop").strip(),
        bpm=max(40, min(160, bpm)),
        suno_style=str(raw.get("suno_style") or "").strip(),
        suno_lyrics=lyrics,
        instrumental=instrumental,
        art_prompt=str(raw.get("art_prompt") or "").strip(),
        youtube_title=youtube_title,
        description=str(raw.get("description") or "").strip(),
        tags=tags[:max_tags],
    )


def build_plans(config: Config, count: int | None = None) -> list[TrackPlan]:
    count = int(count or config.get("batch.count", 6))
    seed = config.get("batch.seed")
    instrumental = bool(config.get("music.instrumental", True))
    state_path = config.resolve_path("paths.state")
    used = _used_titles(state_path)

    llm = LLM(config)
    raw_plans: list[dict[str, Any]]
    if llm.offline:
        LOGGER.info("planning %d tracks with offline templates", count)
        raw_plans = offline_plans(config, count, seed if seed is None else int(seed))
    else:
        fallback_config = None
        alternate = "groq" if llm.provider == "gemini" else "gemini"
        if os.environ.get(f"{alternate.upper()}_API_KEY", "").strip():
            fallback_config = Config(data=config.data, path=config.path)
            fallback_config.set("llm.provider", alternate)

        prompt = PROMPT_TEMPLATE.format(
            channel_name=config.get("channel.name", "Music Channel"),
            niche=" ".join(str(config.get("channel.niche", "")).split()),
            language=config.get("channel.language", "English"),
            count=count,
            used_titles=", ".join(used[-40:]) or "(none yet)",
            vocal_rule=(
                'End the prompt with "instrumental, no vocals".'
                if instrumental
                else "Describe the intended vocal delivery."
            ),
            lyrics_rule=(
                'empty string ""'
                if instrumental
                else "full song lyrics using [Verse] / [Chorus] section tags"
            ),
            max_title=int(config.get("metadata.max_title_chars", 95)),
            max_tags=int(config.get("metadata.max_tags", 25)),
        )
        LOGGER.info("planning %d tracks with %s", count, llm.provider)
        payload: Any = None
        for candidate in [llm] + ([LLM(fallback_config)] if fallback_config else []):
            try:
                payload = candidate.json(prompt, system=SYSTEM)
                break
            except (LLMError, requests.RequestException, json.JSONDecodeError) as exc:
                LOGGER.warning("%s planning failed: %s", candidate.provider, exc)
        if payload is None:
            LOGGER.warning("all LLM providers failed, using offline templates")
            payload = offline_plans(config, count, seed if seed is None else int(seed))
        raw_plans = payload if isinstance(payload, list) else payload.get("tracks", [])

    plans = [
        _coerce_plan(i, raw, instrumental, config)
        for i, raw in enumerate(raw_plans[:count], start=1)
        if isinstance(raw, dict)
    ]
    if not plans:
        raise RuntimeError("planner produced no usable tracks")
    return plans
