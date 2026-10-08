"""Turns a channel niche into a batch of fully specified track plans."""

from __future__ import annotations

import json
import logging
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

Use exactly this content type per track (index: type): {type_plan}
{type_rules}

For each track return an object with exactly these keys:
- "content_type": the type assigned to that index above
- "title": short evocative track name, 2-4 words, ASCII latin script, no quotes, no emoji
- "title_display": the title as it should appear huge on the thumbnail{script_rule}
- "tagline": one short line under the title, max 45 characters{script_rule}
- "badge": 2-4 word uppercase kicker above the title, e.g. "AI EDM TRANCE REMIX"
  or "8 MINUTE INSTRUMENTAL"
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

TYPE_RULES = {
    "original": (
        'For "original" tracks: an original song, not based on any existing recording. '
        "Write your own lyrics."
    ),
    "cover": (
        'For "cover" tracks: pick a well-known classic film song and reimagine it in a '
        'modern style (EDM trance, lofi, retro disco, reggae). Set "title" and '
        '"title_display" to the original song name, and add a "credits" object with the '
        'keys "Song", "Movie", "Singer", "Music", "Lyricist". Leave "suno_lyrics" empty '
        "- the operator pastes the original lyrics into Suno by hand."
    ),
    "instrumental": (
        'For "instrumental" tracks: a long (6-10 minute) meditative instrumental piece - '
        "raga, flute, ambient, rain. No vocals, no lyrics. Give it a curiosity-driven "
        'youtube_title and a "badge" stating the length.'
    ),
}


def content_types(config: Config, count: int) -> list[str]:
    """Cycle the configured content mix across the batch."""
    mix = [str(item).lower() for item in config.get("content.mix", ["original"]) or ["original"]]
    mix = [item for item in mix if item in TYPE_RULES] or ["original"]
    return [mix[i % len(mix)] for i in range(count)]


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


def _tag_list(raw: Any) -> list[str]:
    """Models answer with either a list or a comma-separated string."""
    if isinstance(raw, str):
        return raw.split(",")
    if isinstance(raw, list):
        return [str(item) for item in raw]
    return []


def _coerce_plan(index: int, raw: dict[str, Any], instrumental: bool, config: Config) -> TrackPlan:  # noqa: C901
    title = str(raw.get("title") or f"Untitled {index}").strip()
    max_title = int(config.get("metadata.max_title_chars", 95))
    max_tags = int(config.get("metadata.max_tags", 25))
    base_tags = [str(tag) for tag in config.get("metadata.base_tags", [])]

    tags: list[str] = []
    for tag in _tag_list(raw.get("tags")) + base_tags:
        tag = str(tag).strip().lower()
        if tag and tag not in tags:
            tags.append(tag)

    youtube_title = str(raw.get("youtube_title") or title).strip()[:max_title]
    content_type = str(raw.get("content_type") or "original").strip().lower()
    if content_type not in TYPE_RULES:
        content_type = "original"
    if content_type == "instrumental":
        instrumental = True
    lyrics = "" if instrumental else str(raw.get("suno_lyrics") or "").strip()

    credits_raw = raw.get("credits")
    credits = (
        {str(k): str(v) for k, v in credits_raw.items()} if isinstance(credits_raw, dict) else {}
    )
    disclaimer = (
        str(config.get("content.disclaimer", "")).strip() if content_type == "cover" else ""
    )

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
        title_display=str(raw.get("title_display") or title).strip(),
        tagline=str(raw.get("tagline") or "").strip(),
        badge=str(raw.get("badge") or "").strip(),
        content_type=content_type,
        credits=credits,
        disclaimer=disclaimer,
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
        # Try the configured provider first, then every other keyed provider.
        chain = [llm] + [
            LLM(config, provider=name) for name in LLM.available_providers() if name != llm.provider
        ]
        types = content_types(config, count)
        script = str(config.get("content.script", "latin")).lower()
        prompt = PROMPT_TEMPLATE.format(
            type_plan=", ".join(f"{i}={t}" for i, t in enumerate(types, start=1)),
            type_rules="\n".join(TYPE_RULES[t] for t in dict.fromkeys(types)),
            script_rule=(" (write it in Devanagari script)" if script == "devanagari" else ""),
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
        for candidate in chain:
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
