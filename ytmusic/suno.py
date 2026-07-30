"""Suno automation over the Chrome DevTools Protocol.

Suno has no public API, so the agent drives a real, already-logged-in Chrome.
Two things make this survivable long-term despite Suno reshuffling its UI:

  1. Every selector is a *list* of candidates (role/placeholder/text/CSS), tried in
     order, and overridable from config.yaml under `suno.selectors`.
  2. Audio is never scraped from the DOM download menu. Instead we listen to the
     network and harvest `audio_url` fields out of Suno's own JSON responses, which
     have been stable far longer than the markup.

If automation still fails, `write_manual_prompts()` leaves a copy-paste file so a
batch is never lost.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .config import Config
from .models import TrackPlan

LOGGER = logging.getLogger(__name__)

CREATE_URL = "https://suno.com/create"
CDP_ENDPOINT = "http://localhost:29229"

# Suno's own API responses carry these keys; we mine them regardless of endpoint shape.
_AUDIO_KEYS = ("audio_url", "audioUrl")
_ID_KEYS = ("id", "clip_id")

DEFAULT_SELECTORS: dict[str, list[str]] = {
    "custom_toggle": [
        'button:has-text("Custom")',
        '[role="tab"]:has-text("Custom")',
        'text="Custom Mode"',
    ],
    "instrumental_toggle": [
        'button:has-text("Instrumental")',
        'label:has-text("Instrumental")',
        '[data-testid="instrumental-toggle"]',
    ],
    "style_input": [
        'textarea[placeholder*="style" i]',
        'textarea[placeholder*="genre" i]',
        'div[contenteditable="true"][data-placeholder*="style" i]',
        'textarea[data-testid="tag-input-textarea"]',
    ],
    "lyrics_input": [
        'textarea[placeholder*="lyric" i]',
        'textarea[data-testid="lyrics-input-textarea"]',
        'div[contenteditable="true"][data-placeholder*="lyric" i]',
    ],
    "title_input": [
        'input[placeholder*="title" i]',
        'textarea[placeholder*="title" i]',
        '[data-testid="title-input"]',
    ],
    "create_button": [
        'button:has-text("Create")',
        'button[data-testid="create-button"]',
        'button:has-text("Generate")',
    ],
}


class SunoError(RuntimeError):
    pass


def _selectors(config: Config, name: str) -> list[str]:
    override = config.get(f"suno.selectors.{name}")
    if isinstance(override, list) and override:
        return [str(item) for item in override]
    return DEFAULT_SELECTORS[name]


def _walk(node: Any) -> Iterable[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _harvest_clips(payload: Any) -> list[dict[str, str]]:
    """Pull {id, audio_url, title, status} records out of any Suno JSON body."""
    clips: list[dict[str, str]] = []
    for node in _walk(payload):
        audio = next((node[key] for key in _AUDIO_KEYS if node.get(key)), None)
        if not audio or not isinstance(audio, str) or not audio.startswith("http"):
            continue
        clip_id = next((str(node[key]) for key in _ID_KEYS if node.get(key)), audio)
        clips.append(
            {
                "id": clip_id,
                "audio_url": audio,
                "title": str(node.get("title") or ""),
                "status": str(node.get("status") or ""),
            }
        )
    return clips


class SunoSession:
    """Wraps a Playwright page attached to the user's logged-in Chrome."""

    def __init__(self, config: Config, headless: bool = False) -> None:
        self.config = config
        self.headless = headless
        # Playwright objects are only typed at runtime; the import is lazy so the rest of
        # the package stays importable without a browser installed.
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self.page: Any = None
        self._clips: dict[str, dict[str, str]] = {}

    def __enter__(self) -> SunoSession:
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        endpoint = str(self.config.get("suno.cdp_endpoint", CDP_ENDPOINT))
        try:
            self._browser = self._playwright.chromium.connect_over_cdp(endpoint)
            self._context = self._browser.contexts[0] if self._browser.contexts else None
            if self._context is None:
                self._context = self._browser.new_context()
            LOGGER.info("attached to existing Chrome at %s", endpoint)
        except Exception as exc:  # noqa: BLE001 - any CDP failure means "no browser there"
            LOGGER.warning("CDP attach failed (%s); launching a standalone browser", exc)
            profile = Path(
                str(self.config.get("suno.user_data_dir", "~/.config/yt-music-agent/chrome"))
            ).expanduser()
            profile.mkdir(parents=True, exist_ok=True)
            self._context = self._playwright.chromium.launch_persistent_context(
                str(profile), headless=self.headless
            )
        self.page = self._context.pages[0] if self._context.pages else self._context.new_page()
        self.page.on("response", self._on_response)
        return self

    def __exit__(self, *_exc: object) -> None:
        # The browser belongs to the user's session; never close it, only detach.
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:  # noqa: BLE001
                pass

    @property
    def known_clip_ids(self) -> set[str]:
        return set(self._clips)

    @property
    def clips(self) -> dict[str, dict[str, str]]:
        return dict(self._clips)

    def _on_response(self, response: Any) -> None:
        url = response.url
        if "suno" not in url or "/api/" not in url:
            return
        try:
            if "application/json" not in (response.header_value("content-type") or ""):
                return
            payload = response.json()
        except Exception:  # noqa: BLE001 - streaming/aborted responses are expected
            return
        for clip in _harvest_clips(payload):
            existing = self._clips.get(clip["id"], {})
            merged = {**existing, **{k: v for k, v in clip.items() if v}}
            self._clips[clip["id"]] = merged

    # ---------------------------------------------------------------- interaction

    def _first(self, name: str, timeout: float = 8000):
        assert self.page is not None
        errors: list[str] = []
        for selector in _selectors(self.config, name):
            locator = self.page.locator(selector).first
            try:
                locator.wait_for(state="visible", timeout=timeout)
                return locator
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{selector}: {type(exc).__name__}")
        raise SunoError(f"no selector matched for '{name}': {'; '.join(errors)}")

    def _fill(self, name: str, value: str) -> None:
        locator = self._first(name)
        locator.click()
        try:
            locator.fill("")
            locator.fill(value)
        except Exception:  # noqa: BLE001 - contenteditable divs reject fill()
            assert self.page is not None
            self.page.keyboard.press("Control+A")
            self.page.keyboard.press("Delete")
            self.page.keyboard.type(value, delay=8)

    def ensure_logged_in(self) -> bool:
        assert self.page is not None
        self.page.goto(CREATE_URL, wait_until="domcontentloaded", timeout=90000)
        self.page.wait_for_timeout(3000)
        body = (self.page.inner_text("body") or "").lower()
        if "sign in" in body and "create" not in body:
            return False
        return True

    def open_create(self) -> None:
        assert self.page is not None
        if not self.page.url.startswith(CREATE_URL):
            self.page.goto(CREATE_URL, wait_until="domcontentloaded", timeout=90000)
        self.page.wait_for_timeout(2000)
        try:
            self._first("custom_toggle", timeout=5000).click()
            self.page.wait_for_timeout(800)
        except SunoError:
            LOGGER.info("custom mode toggle not found; assuming custom mode is already active")

    def submit(self, plan: TrackPlan) -> None:
        """Fill the create form and hit Create."""
        assert self.page is not None

        if plan.instrumental:
            try:
                self._first("instrumental_toggle", timeout=4000).click()
                self.page.wait_for_timeout(500)
            except SunoError:
                LOGGER.info("instrumental toggle not found; relying on prompt wording")
        else:
            self._fill("lyrics_input", plan.suno_lyrics)

        self._fill("style_input", plan.suno_style)
        try:
            self._fill("title_input", plan.title)
        except SunoError:
            LOGGER.info("title field not found; Suno will auto-name the clip")

        self._first("create_button").click()
        LOGGER.info("track %02d: submitted to Suno", plan.index)
        self.page.wait_for_timeout(4000)

    def wait_for_audio(
        self, exclude: Iterable[str], timeout: float = 420.0
    ) -> list[dict[str, str]]:
        """Poll until new, streamable clips show up. Returns newest-first records."""
        assert self.page is not None
        exclude = set(exclude)
        deadline = time.time() + timeout
        while time.time() < deadline:
            ready = [
                clip
                for clip_id, clip in self._clips.items()
                if clip_id not in exclude and clip.get("audio_url")
            ]
            if len(ready) >= 2:
                return ready
            # Nudge the SPA so it re-polls its feed endpoint.
            self.page.wait_for_timeout(5000)
            self.page.mouse.wheel(0, 200)
        ready = [
            clip
            for clip_id, clip in self._clips.items()
            if clip_id not in exclude and clip.get("audio_url")
        ]
        if not ready:
            raise SunoError("timed out waiting for Suno to return audio")
        return ready

    def download(self, url: str, destination: Path) -> Path:
        assert self._context is not None
        response = self._context.request.get(url, timeout=180000)
        if not response.ok:
            raise SunoError(f"download failed {response.status} for {url}")
        suffix = ".wav" if ".wav" in url.lower() else ".mp3"
        destination = destination.with_suffix(suffix)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(response.body())
        return destination

    def screenshot(self, destination: Path) -> Path | None:
        if self.page is None:
            return None
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.page.screenshot(path=str(destination), full_page=False)
            return destination
        except Exception:  # noqa: BLE001
            return None


def write_manual_prompts(plans: list[TrackPlan], destination: Path) -> Path:
    """Copy-paste sheet so a failed automation run is still usable by hand."""
    blocks: list[str] = []
    for plan in plans:
        blocks.append(
            "\n".join(
                [
                    f"### {plan.index:02d} - {plan.title}",
                    "",
                    "[Style of Music]",
                    plan.suno_style,
                    "",
                    "[Title]",
                    plan.title,
                    "",
                    "[Lyrics]",
                    plan.suno_lyrics or "(instrumental - enable the Instrumental toggle)",
                    "",
                ]
            )
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(blocks), encoding="utf-8")
    return destination


def dump_state(clips: dict[str, dict[str, str]], destination: Path) -> Path:
    destination.write_text(json.dumps(clips, indent=2), encoding="utf-8")
    return destination


_DURATION_RE = re.compile(r"(\d+):(\d{2})")


def parse_duration_label(label: str) -> float | None:
    match = _DURATION_RE.search(label or "")
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))
