"""Font resolution for thumbnails.

The cinematic thumbnail needs a heavy Latin display face and a Devanagari face,
and neither ships with most Linux/macOS boxes or Colab. Rather than vendoring
binaries into the repo we pull the OFL originals from the google/fonts mirror
once and cache them under ~/.cache/yt-music-agent/fonts. Everything degrades to
whatever system font exists if there is no network.
"""

from __future__ import annotations

import logging
from pathlib import Path

import requests
from PIL import ImageFont

LOGGER = logging.getLogger(__name__)

CACHE_DIR = Path.home() / ".cache" / "yt-music-agent" / "fonts"
_BASE = "https://raw.githubusercontent.com/google/fonts/main"

# role -> (filename, path in the google/fonts repo)
REMOTE_FONTS: dict[str, tuple[str, str]] = {
    "display": ("Anton-Regular.ttf", "ofl/anton/Anton-Regular.ttf"),
    "display_deva": ("Kalam-Bold.ttf", "ofl/kalam/Kalam-Bold.ttf"),
    "body": ("Montserrat.ttf", "ofl/montserrat/Montserrat%5Bwght%5D.ttf"),
    "body_deva": (
        "NotoSansDevanagari.ttf",
        "ofl/notosansdevanagari/NotoSansDevanagari%5Bwdth,wght%5D.ttf",
    ),
}

SYSTEM_FALLBACKS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
)

_MISSING: set[str] = set()


def font_file(role: str) -> Path | None:
    """Path to a cached font for `role`, downloading it the first time."""
    if role in _MISSING or role not in REMOTE_FONTS:
        return None
    name, remote = REMOTE_FONTS[role]
    target = CACHE_DIR / name
    if target.exists():
        return target
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        response = requests.get(f"{_BASE}/{remote}", timeout=60)
        response.raise_for_status()
    except requests.RequestException as exc:
        LOGGER.warning("could not fetch %s font: %s", role, exc)
        _MISSING.add(role)
        return None
    target.write_bytes(response.content)
    LOGGER.info("cached font %s", name)
    return target


def load(role: str, size: int, weight: int | None = None) -> ImageFont.FreeTypeFont:
    """Load a font by role, falling back to any usable system face."""
    path = font_file(role)
    candidates = [path] if path else []
    candidates += [Path(p) for p in SYSTEM_FALLBACKS]
    for candidate in candidates:
        if candidate and candidate.exists():
            font = ImageFont.truetype(str(candidate), size)
            if weight is not None:
                try:  # variable fonts only
                    font.set_variation_by_axes([weight])
                except (OSError, AttributeError):
                    pass
            return font
    raise RuntimeError("no usable TrueType font found")


def is_devanagari(text: str) -> bool:
    return any("\u0900" <= ch <= "\u097f" for ch in text)


def display_font(text: str, size: int) -> ImageFont.FreeTypeFont:
    return load("display_deva" if is_devanagari(text) else "display", size)


def body_font(text: str, size: int, weight: int = 600) -> ImageFont.FreeTypeFont:
    role = "body_deva" if is_devanagari(text) else "body"
    return load(role, size, weight=weight)
