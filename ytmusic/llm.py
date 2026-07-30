"""Text generation across free LLM tiers, with an offline template fallback.

Providers, in order of quality:
  * gemini  - Google AI Studio free tier (GEMINI_API_KEY), generous daily quota.
  * groq    - Groq free tier (GROQ_API_KEY), very fast Llama 3.3 70B.
  * offline  - deterministic templates, no network, no keys. Always available.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from typing import Any

import requests

from .config import Config

LOGGER = logging.getLogger(__name__)

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GROQ_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
TIMEOUT = 120
RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3

_JSON_BLOCK_RE = re.compile(r"\{.*\}|\[.*\]", re.DOTALL)


class LLMError(RuntimeError):
    """Raised when a provider cannot produce usable output."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


def _extract_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"```$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        match = _JSON_BLOCK_RE.search(text)
        if not match:
            raise LLMError(f"model did not return JSON: {text[:400]}") from exc
        return json.loads(match.group(0))


class LLM:
    """Thin wrapper exposing a single `json_list` call used by the planner."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.provider = str(config.get("llm.provider", "gemini")).lower()
        self.temperature = float(config.get("llm.temperature", 1.0))
        self.gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
        self.groq_key = os.environ.get("GROQ_API_KEY", "").strip()
        self.provider = self._resolve_provider()

    def _resolve_provider(self) -> str:
        if self.provider == "gemini" and not self.gemini_key:
            if self.groq_key:
                LOGGER.warning("GEMINI_API_KEY missing, falling back to groq")
                return "groq"
            LOGGER.warning("GEMINI_API_KEY missing, falling back to offline templates")
            return "offline"
        if self.provider == "groq" and not self.groq_key:
            if self.gemini_key:
                LOGGER.warning("GROQ_API_KEY missing, falling back to gemini")
                return "gemini"
            LOGGER.warning("GROQ_API_KEY missing, falling back to offline templates")
            return "offline"
        return self.provider

    @property
    def offline(self) -> bool:
        return self.provider == "offline"

    def text(self, prompt: str, system: str | None = None) -> str:
        """Generate text, retrying transient rate limits and 5xx responses with backoff."""
        last: BaseException | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                if self.provider == "gemini":
                    return self._gemini_text(prompt, system)
                if self.provider == "groq":
                    return self._groq_text(prompt, system)
                raise LLMError("offline provider cannot generate free-form text")
            except (LLMError, requests.RequestException) as exc:
                last = exc
                if not getattr(exc, "retryable", True) or attempt == MAX_ATTEMPTS:
                    break
                delay = 3 * attempt
                LOGGER.warning(
                    "%s attempt %d/%d failed (%s); retrying in %ds",
                    self.provider,
                    attempt,
                    MAX_ATTEMPTS,
                    exc,
                    delay,
                )
                time.sleep(delay)
        assert last is not None
        raise last

    def json(self, prompt: str, system: str | None = None) -> Any:
        raw = self.text(prompt + "\n\nReturn only raw JSON, no prose, no markdown fences.", system)
        return _extract_json(raw)

    def _gemini_text(self, prompt: str, system: str | None) -> str:
        model = str(self.config.get("llm.gemini_model", "gemini-2.5-flash"))
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": self.temperature},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        response = requests.post(
            GEMINI_ENDPOINT.format(model=model),
            params={"key": self.gemini_key},
            json=payload,
            timeout=TIMEOUT,
        )
        if response.status_code != 200:
            raise LLMError(
                f"gemini {response.status_code}: {response.text[:400]}",
                retryable=response.status_code in RETRY_STATUSES,
            )
        candidates = response.json().get("candidates") or []
        if not candidates:
            raise LLMError(f"gemini returned no candidates: {response.text[:400]}")
        parts = candidates[0].get("content", {}).get("parts") or []
        return "".join(part.get("text", "") for part in parts)

    def _groq_text(self, prompt: str, system: str | None) -> str:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = requests.post(
            GROQ_ENDPOINT,
            headers={"Authorization": f"Bearer {self.groq_key}"},
            json={
                "model": str(self.config.get("llm.groq_model", "llama-3.3-70b-versatile")),
                "messages": messages,
                "temperature": self.temperature,
            },
            timeout=TIMEOUT,
        )
        if response.status_code != 200:
            raise LLMError(
                f"groq {response.status_code}: {response.text[:400]}",
                retryable=response.status_code in RETRY_STATUSES,
            )
        return response.json()["choices"][0]["message"]["content"]


# --------------------------------------------------------------------------------------
# Offline template generator: keeps the pipeline usable with zero API keys.
# --------------------------------------------------------------------------------------

_TIME_WORDS = ["Midnight", "3AM", "Dusk", "Rainy", "Sunday", "Winter", "Neon", "Slow"]
_NOUN_WORDS = [
    "Commute",
    "Window",
    "Cassette",
    "Rooftop",
    "Letters",
    "Static",
    "Tea",
    "Streetlight",
]
_MOODS = ["nostalgic", "sleepy", "bittersweet", "warm", "hazy", "melancholic", "hopeful", "calm"]
_TEXTURES = [
    "dusty vinyl crackle, tape saturation, muted jazz guitar",
    "rhodes piano, soft brushed drums, distant rain",
    "warm upright bass, felt piano, room reverb",
    "boom bap drums, mellow sax samples, sidechained pads",
    "analog synth pads, gentle hiss, filtered strings",
]
_SCENES = [
    "a rain-streaked apartment window overlooking a neon city at night",
    "an empty late-night train carriage lit by warm sodium lamps",
    "a cluttered desk with a cassette deck, steaming mug and stacked books",
    "a rooftop at blue hour with laundry lines and distant skyline",
    "a small ramen shop glowing in the rain on a quiet street",
]


def offline_plans(config: Config, count: int, seed: int | None) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    genre = "lofi hip hop"
    plans: list[dict[str, Any]] = []
    for _ in range(count):
        title = f"{rng.choice(_TIME_WORDS)} {rng.choice(_NOUN_WORDS)}"
        mood = rng.choice(_MOODS)
        texture = rng.choice(_TEXTURES)
        bpm = rng.choice([68, 72, 74, 78, 82, 85, 90])
        plans.append(
            {
                "title": title,
                "mood": mood,
                "genre": genre,
                "bpm": bpm,
                "suno_style": f"{genre}, {mood}, {texture}, {bpm} bpm, instrumental, no vocals",
                "suno_lyrics": "",
                "art_prompt": (
                    f"{rng.choice(_SCENES)}, {mood} mood, anime-inspired illustration, "
                    "soft grain, cinematic lighting, muted teal and amber palette, "
                    "16:9 album cover, no text, no watermark"
                ),
                "youtube_title": f"{title} \u2014 {mood} lofi beats to relax / study to",
                "description": (
                    f"{title}: a {mood} {genre} beat at {bpm} bpm. {texture}.\n\n"
                    "Perfect for studying, coding, reading or falling asleep."
                ),
                "tags": [genre, mood, "study beats", "chill", "instrumental", "focus music"],
            }
        )
    return plans
