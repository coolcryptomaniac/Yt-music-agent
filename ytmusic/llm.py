"""Text generation across free LLM tiers, with an offline template fallback.

Providers:
  * gemini   - Google AI Studio free tier (GEMINI_API_KEY), strongest copywriting.
  * cerebras - Cerebras Cloud free tier (CEREBRAS_API_KEY), by far the fastest.
  * groq     - Groq free tier (GROQ_API_KEY), fast, generous limits.
  * offline  - deterministic templates, no network, no keys. Always available.

When the configured provider has no key, or fails after retries, the planner walks the
remaining keyed providers before finally dropping to offline templates.
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
# Groq and Cerebras are both OpenAI-chat-compatible, so they share one code path.
OPENAI_COMPATIBLE = {
    "groq": ("https://api.groq.com/openai/v1/chat/completions", "llm.groq_model"),
    "cerebras": ("https://api.cerebras.ai/v1/chat/completions", "llm.cerebras_model"),
}
KEY_ENV = {
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
}
# Preference order used when the configured provider is unusable.
PROVIDER_ORDER = ("gemini", "cerebras", "groq")
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

    def __init__(self, config: Config, provider: str | None = None) -> None:
        self.config = config
        self.temperature = float(config.get("llm.temperature", 1.0))
        requested = str(provider or config.get("llm.provider", "gemini")).lower()
        self.provider = self._resolve_provider(requested)

    @staticmethod
    def key_for(provider: str) -> str:
        return os.environ.get(KEY_ENV.get(provider, ""), "").strip()

    @classmethod
    def available_providers(cls) -> list[str]:
        return [name for name in PROVIDER_ORDER if cls.key_for(name)]

    def _resolve_provider(self, requested: str) -> str:
        if requested == "offline" or self.key_for(requested):
            return requested
        alternatives = self.available_providers()
        if alternatives:
            LOGGER.warning(
                "%s missing, using %s instead", KEY_ENV.get(requested, requested), alternatives[0]
            )
            return alternatives[0]
        LOGGER.warning("no LLM API keys found, using offline templates")
        return "offline"

    @property
    def offline(self) -> bool:
        return self.provider == "offline"

    @property
    def key(self) -> str:
        return self.key_for(self.provider)

    def text(self, prompt: str, system: str | None = None) -> str:
        """Generate text, retrying transient rate limits and 5xx responses with backoff."""
        last: BaseException | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                if self.provider == "gemini":
                    return self._gemini_text(prompt, system)
                if self.provider in OPENAI_COMPATIBLE:
                    return self._openai_compatible_text(prompt, system)
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
            params={"key": self.key},
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

    def _openai_compatible_text(self, prompt: str, system: str | None) -> str:
        endpoint, model_key = OPENAI_COMPATIBLE[self.provider]
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {self.key}"},
            json={
                "model": str(self.config.require(model_key)),
                "messages": messages,
                "temperature": self.temperature,
            },
            timeout=TIMEOUT,
        )
        if response.status_code != 200:
            raise LLMError(
                f"{self.provider} {response.status_code}: {response.text[:400]}",
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
