"""Cover art and thumbnail generation.

Provider chain (all free):
  gemini       - Nano Banana (gemini-2.5-flash-image) via AI Studio free tier.
  pollinations - keyless Flux endpoint at image.pollinations.ai.
  local        - Pillow gradient + grain + vignette, works fully offline.

Whatever produces the cover, the thumbnail is always composited locally so the
title text stays crisp and consistent (models are bad at legible text).
"""

from __future__ import annotations

import base64
import io
import logging
import math
import os
import random
import urllib.parse
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import Config
from .models import TrackPlan

LOGGER = logging.getLogger(__name__)

GEMINI_IMAGE_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
POLLINATIONS_ENDPOINT = "https://image.pollinations.ai/prompt/{prompt}"
TIMEOUT = 180

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    LOGGER.warning("no TrueType font found, falling back to bitmap font")
    return ImageFont.load_default()


def _gemini_image(config: Config, prompt: str, size: tuple[int, int]) -> Image.Image | None:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        return None
    model = str(config.get("llm.gemini_image_model", "gemini-2.5-flash-image"))
    response = requests.post(
        GEMINI_IMAGE_ENDPOINT.format(model=model),
        params={"key": key},
        json={
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE"]},
        },
        timeout=TIMEOUT,
    )
    if response.status_code != 200:
        LOGGER.warning("gemini image %s: %s", response.status_code, response.text[:200])
        return None
    for candidate in response.json().get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                raw = base64.b64decode(inline["data"])
                return (
                    Image.open(io.BytesIO(raw))
                    .convert("RGB")
                    .resize(size, Image.Resampling.LANCZOS)
                )
    LOGGER.warning("gemini image response contained no image part")
    return None


def _pollinations_image(prompt: str, size: tuple[int, int]) -> Image.Image | None:
    url = POLLINATIONS_ENDPOINT.format(prompt=urllib.parse.quote(prompt[:1200]))
    try:
        response = requests.get(
            url,
            params={"width": size[0], "height": size[1], "nologo": "true", "model": "flux"},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        LOGGER.warning("pollinations request failed: %s", exc)
        return None
    if response.status_code != 200 or not response.content:
        LOGGER.warning("pollinations %s", response.status_code)
        return None
    try:
        return (
            Image.open(io.BytesIO(response.content))
            .convert("RGB")
            .resize(size, Image.Resampling.LANCZOS)
        )
    except OSError as exc:
        LOGGER.warning("pollinations returned non-image data: %s", exc)
        return None


def _local_image(plan: TrackPlan, size: tuple[int, int]) -> Image.Image:
    """Deterministic per-title gradient artwork with grain, glow and vignette."""
    rng = random.Random(plan.title)
    width, height = size
    hue = rng.randint(0, 359)
    top = _hsv_to_rgb(hue, 0.55, 0.28)
    bottom = _hsv_to_rgb((hue + rng.randint(20, 70)) % 360, 0.65, 0.08)

    base = Image.new("RGB", size)
    draw = ImageDraw.Draw(base)
    for y in range(height):
        blend = y / max(1, height - 1)
        draw.line(
            [(0, y), (width, y)],
            fill=tuple(int(top[i] + (bottom[i] - top[i]) * blend) for i in range(3)),
        )

    glow = Image.new("RGB", size, (0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    accent = _hsv_to_rgb((hue + 180) % 360, 0.45, 1.0)
    for _ in range(rng.randint(2, 4)):
        cx, cy = rng.randint(0, width), rng.randint(0, int(height * 0.7))
        radius = rng.randint(int(width * 0.12), int(width * 0.3))
        glow_draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=accent)
    glow = glow.filter(ImageFilter.GaussianBlur(radius=width // 12))
    base = Image.blend(base, glow, 0.28)

    grain = Image.effect_noise(size, 22).convert("RGB")
    base = Image.blend(base, grain, 0.07)

    vignette = Image.new("L", size, 0)
    vignette_draw = ImageDraw.Draw(vignette)
    vignette_draw.ellipse([-width * 0.15, -height * 0.15, width * 1.15, height * 1.15], fill=255)
    vignette = vignette.filter(ImageFilter.GaussianBlur(radius=width // 10))
    black = Image.new("RGB", size, (0, 0, 0))
    return Image.composite(base, black, vignette)


def _hsv_to_rgb(hue: int, saturation: float, value: float) -> tuple[int, int, int]:
    chroma = value * saturation
    secondary = chroma * (1 - abs(((hue / 60.0) % 2) - 1))
    rgb: tuple[float, float, float]
    match int(hue // 60) % 6:
        case 0:
            rgb = (chroma, secondary, 0.0)
        case 1:
            rgb = (secondary, chroma, 0.0)
        case 2:
            rgb = (0.0, chroma, secondary)
        case 3:
            rgb = (0.0, secondary, chroma)
        case 4:
            rgb = (secondary, 0.0, chroma)
        case _:
            rgb = (chroma, 0.0, secondary)
    offset = value - chroma
    red, green, blue = (max(0, min(255, int((c + offset) * 255))) for c in rgb)
    return red, green, blue


def generate_cover(config: Config, plan: TrackPlan, destination: Path) -> tuple[Path, str]:
    """Render cover art to `destination`. Returns (path, provider_used)."""
    size = (int(config.get("art.width", 1280)), int(config.get("art.height", 720)))
    prompt = plan.art_prompt or (
        f"{plan.genre} album cover, {plan.mood} atmosphere, cinematic lighting, "
        "no text, no watermark, no logo"
    )
    providers: list[str] = [str(p).lower() for p in config.get("art.providers", ["local"])]

    image: Image.Image | None = None
    used = "local"
    for provider in providers:
        try:
            if provider == "gemini":
                image = _gemini_image(config, prompt, size)
            elif provider == "pollinations":
                image = _pollinations_image(prompt, size)
            elif provider == "local":
                image = _local_image(plan, size)
        except requests.RequestException as exc:
            LOGGER.warning("art provider %s failed: %s", provider, exc)
            image = None
        if image is not None:
            used = provider
            break
    if image is None:
        image = _local_image(plan, size)
        used = "local"

    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, quality=95)
    LOGGER.info("cover art via %s -> %s", used, destination.name)
    return destination, used


def _wrap(text: str, font, max_width: int, draw: ImageDraw.ImageDraw) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:3]


def make_thumbnail(config: Config, plan: TrackPlan, cover: Path, destination: Path) -> Path:
    """Composite the title (and mood/bpm strap) over the cover for a 1280x720 thumbnail."""
    image = Image.open(cover).convert("RGB").resize((1280, 720), Image.Resampling.LANCZOS)
    if not bool(config.get("art.thumbnail_text", True)):
        image.save(destination, quality=92)
        return destination

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    # Bottom-up scrim so text stays readable over busy artwork.
    for y in range(360, 720):
        alpha = int(200 * ((y - 360) / 360) ** 1.4)
        draw.line([(0, y), (1280, y)], fill=(0, 0, 0, alpha))

    size = int(config.get("art.thumbnail_font_size", 72))
    font = _load_font(size)
    small = _load_font(max(20, size // 3))
    lines = _wrap(plan.title.upper(), font, 1120, draw)

    line_height = int(size * 1.18)
    total = line_height * len(lines)
    y = 690 - total - int(size * 0.9)
    for line in lines:
        draw.text((72 + 3, y + 3), line, font=font, fill=(0, 0, 0, 170))
        draw.text((72, y), line, font=font, fill=(255, 255, 255, 255))
        y += line_height

    strap = f"{plan.genre.upper()}  \u2022  {plan.mood.upper()}  \u2022  {plan.bpm} BPM"
    draw.text((74, y + 10), strap, font=small, fill=(0, 0, 0, 160))
    draw.text((72, y + 8), strap, font=small, fill=(235, 235, 235, 255))

    combined = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    destination.parent.mkdir(parents=True, exist_ok=True)
    combined.save(destination, quality=92)
    return destination


def make_mix_thumbnail(config: Config, titles: list[str], cover: Path, destination: Path) -> Path:
    """Thumbnail for the long-mix video: cover + channel name + track count."""
    image = Image.open(cover).convert("RGB").resize((1280, 720), Image.Resampling.LANCZOS)
    image = image.filter(ImageFilter.GaussianBlur(radius=2))
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 110))
    draw = ImageDraw.Draw(overlay)
    title_font = _load_font(96)
    sub_font = _load_font(40)
    channel = str(config.get("channel.name", "Music Mix")).upper()
    lines = _wrap(channel, title_font, 1120, draw)
    y = 260
    for line in lines:
        width = draw.textlength(line, font=title_font)
        draw.text(((1280 - width) / 2, y), line, font=title_font, fill=(255, 255, 255, 255))
        y += 110
    sub = f"{len(titles)} TRACK MIX  \u2022  {math.ceil(len(titles) * 2.5)} MIN"
    width = draw.textlength(sub, font=sub_font)
    draw.text(((1280 - width) / 2, y + 10), sub, font=sub_font, fill=(225, 225, 225, 255))
    combined = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    destination.parent.mkdir(parents=True, exist_ok=True)
    combined.save(destination, quality=92)
    return destination
