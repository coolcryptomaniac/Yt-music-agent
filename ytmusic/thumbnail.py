"""Cinematic thumbnail composer.

Reproduces the layout used by big AI-music channels: photographic art on the
right, a dark scrim and a typographic stack on the left (kicker, oversized
title, tagline, artist line), corner badges, and - for covers/remixes - an
original-song credits box plus a rights disclaimer bar.

Text is always drawn locally: image models still cannot spell, and Devanagari
titles need real shaping (Pillow does this through libraqm).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import fonts
from .config import Config
from .models import TrackPlan

W, H = 1280, 720
MARGIN = 46
COLUMN = 660  # width available to the text stack on the left

Color = tuple[int, int, int, int]


def _rgba(value: str, alpha: int = 255) -> Color:
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), alpha)


def _cover_crop(path: Path) -> Image.Image:
    image = Image.open(path).convert("RGB")
    scale = max(W / image.width, H / image.height)
    resized = image.resize(
        (max(W, int(image.width * scale)), max(H, int(image.height * scale))),
        Image.Resampling.LANCZOS,
    )
    left = (resized.width - W) // 2
    top = (resized.height - H) // 2
    return resized.crop((left, top, left + W, top + H))


def _scrims(image: Image.Image, strength: int) -> Image.Image:
    """Darken the left column (text) and the very bottom (disclaimer bar)."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    edge = int(W * 0.72)
    for x in range(edge):
        alpha = int(strength * ((edge - x) / edge) ** 1.25)
        draw.line([(x, 0), (x, H)], fill=(4, 6, 12, alpha))
    for y in range(H - 150, H):
        alpha = int(120 * ((y - (H - 150)) / 150) ** 1.5)
        draw.line([(0, y), (W, y)], fill=(0, 0, 0, alpha))
    return Image.alpha_composite(image.convert("RGBA"), layer)


def _vignette(image: Image.Image) -> Image.Image:
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).ellipse([-W * 0.22, -H * 0.3, W * 1.22, H * 1.3], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=110))
    dark = Image.new("RGB", (W, H), (0, 0, 0))
    return Image.composite(image.convert("RGB"), dark, mask).convert("RGBA")


def _tracked(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: Color,
    tracking: float = 0.0,
) -> float:
    """Draw letter-spaced text, returning the width consumed."""
    x, y = xy
    for char in text:
        draw.text((x, y), char, font=font, fill=fill)
        x += draw.textlength(char, font=font) + tracking
    return x - xy[0]


def _tracked_width(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, tracking: float
) -> float:
    return sum(draw.textlength(c, font=font) for c in text) + tracking * max(0, len(text) - 1)


def _wrap(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int
) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _fit_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    max_height: int,
    start: int = 112,
    minimum: int = 40,
) -> tuple[list[str], ImageFont.FreeTypeFont]:
    """Largest display size that wraps into <= 3 lines and fits the height budget."""
    size = start
    while size > minimum:
        font = fonts.display_font(text, size)
        lines = _wrap(draw, text, font, max_width)
        fits_width = all(draw.textlength(line, font=font) <= max_width for line in lines)
        if len(lines) <= 3 and fits_width and len(lines) * size * 1.16 <= max_height:
            return lines, font
        size -= 4
    font = fonts.display_font(text, minimum)
    return _wrap(draw, text, font, max_width)[:3], font


def _chip(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fg: Color,
    bg: Color | None,
    outline: Color | None,
    pad: tuple[int, int] = (14, 8),
    tracking: float = 1.6,
) -> tuple[int, int]:
    width = _tracked_width(draw, text, font, tracking)
    box = (xy[0], xy[1], int(xy[0] + width + pad[0] * 2), int(xy[1] + font.size + pad[1] * 2))
    draw.rounded_rectangle(box, radius=8, fill=bg, outline=outline, width=2)
    _tracked(draw, (xy[0] + pad[0], xy[1] + pad[1] - 2), text, font, fg, tracking)
    return box[2] - box[0], box[3] - box[1]


def render(
    config: Config,
    plan: TrackPlan,
    cover: Path,
    destination: Path,
    duration: float | None = None,
) -> Path:
    accent = _rgba(str(config.get("art.accent_color", "#F2C879")))
    title_color = _rgba(str(config.get("art.title_color", "#F8EEDC")))
    white = (255, 255, 255, 255)
    artist = str(config.get("channel.artist", config.get("channel.name", ""))).upper()

    image = _vignette(_scrims(_cover_crop(cover), int(config.get("art.scrim", 205))))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    # Frame.
    draw.rounded_rectangle(
        [14, 14, W - 15, H - 15], radius=10, outline=(255, 255, 255, 55), width=2
    )

    small = fonts.load("body", 20, weight=700)
    tiny = fonts.load("body", 16, weight=600)

    # Corner badges.
    _chip(draw, (MARGIN, MARGIN - 8), "AI MUSIC", tiny, white, (0, 0, 0, 150), (255, 255, 255, 90))
    quality = str(config.get("art.quality_badge", "4K ULTRA HD"))
    q_font = fonts.load("body", 18, weight=800)
    q_width = _tracked_width(draw, quality, q_font, 1.6) + 28
    _chip(
        draw,
        (int(W - MARGIN - q_width), MARGIN - 8),
        quality,
        q_font,
        (18, 14, 6, 255),
        accent,
        None,
    )

    # Everything below the title is laid out against a hard floor: the credits box
    # (covers only) or the chip row, so long Devanagari titles shrink instead of
    # colliding with them.
    credits_lines = [f"{key}: {value}" for key, value in plan.credits.items()][:6]
    show_credits = plan.content_type == "cover" and bool(credits_lines)
    floor = H - (112 + 26 + len(credits_lines) * 20) if show_credits else H - 116

    # Kicker (genre / remix badge).
    kicker = (plan.badge or plan.genre).upper()
    y = 84 if show_credits else 118
    if kicker:
        _tracked(draw, (MARGIN + 4, y), kicker, small, accent, 4.0)
        y += 44

    tagline_height = 74 if plan.tagline else 0
    artist_height = 100 if artist else 0

    # Title.
    headline = plan.title_display or plan.title
    lines, title_font = _fit_lines(
        draw, headline, COLUMN, max(80, floor - y - tagline_height - artist_height)
    )
    for line in lines:
        draw.text((MARGIN + 6, y + 4), line, font=title_font, fill=(0, 0, 0, 150))
        draw.text((MARGIN + 2, y), line, font=title_font, fill=title_color)
        y += int(title_font.size * 1.16)

    # Tagline under a hairline rule.
    if plan.tagline:
        y += 18
        draw.line([(MARGIN + 4, y), (MARGIN + 190, y)], fill=(255, 255, 255, 110), width=2)
        y += 16
        tag_font = fonts.body_font(plan.tagline, 28, weight=500)
        draw.text((MARGIN + 4, y), plan.tagline, font=tag_font, fill=(238, 230, 214, 235))
        y += 44

    # Artist block.
    if artist:
        y += 8
        _tracked(draw, (MARGIN + 6, y), "ARTIST", tiny, (226, 226, 226, 220), 6.0)
        y += 30
        name_font = fonts.load("body", 46, weight=800)
        name_width = _tracked_width(draw, artist, name_font, 3.0)
        _tracked(draw, (MARGIN + 4, y), artist, name_font, accent, 3.0)
        rule_y = int(y + name_font.size * 0.6)
        draw.line(
            [(MARGIN + 14 + name_width, rule_y), (MARGIN + 74 + name_width, rule_y)],
            fill=accent,
            width=3,
        )
        y += 74

    # Feature chips (skipped when the credits/disclaimer furniture owns the bottom).
    chips = [str(c).upper() for c in config.get("art.chips", ["FEEL IT", "LOVE IT", "LIVE IT"])]
    if chips and not show_credits and not plan.disclaimer:
        x = float(MARGIN + 4)
        for position, chip in enumerate(chips):
            width = _tracked(draw, (x, H - 92), chip, small, (240, 240, 240, 235), 2.5)
            x += width + 20
            if position < len(chips) - 1:
                draw.ellipse([x, H - 84, x + 7, H - 77], fill=accent)
                x += 24

    # Duration pill.
    if duration:
        minutes, seconds = divmod(int(duration), 60)
        label = f"{minutes}:{seconds:02d}"
        pill_font = fonts.load("body", 34, weight=800)
        pill_width = _tracked_width(draw, label, pill_font, 1.0) + 44
        _chip(
            draw,
            (int(W - MARGIN - pill_width), H - 108),
            label,
            pill_font,
            (18, 14, 6, 255),
            accent,
            None,
            pad=(22, 10),
            tracking=1.0,
        )

    if show_credits:
        _credits_box(draw, credits_lines, accent)
    if plan.disclaimer:
        _disclaimer(draw, plan.disclaimer)

    out = Image.alpha_composite(image, layer).convert("RGB")
    destination.parent.mkdir(parents=True, exist_ok=True)
    out.save(destination, quality=92)
    return destination


def _credits_box(draw: ImageDraw.ImageDraw, lines: list[str], accent: Color) -> None:
    """Original-song credits, as every cover channel is expected to show."""
    font = fonts.body_font(" ".join(lines), 16, weight=500)
    head = fonts.load("body", 16, weight=800)
    height = 26 + len(lines) * 20
    top = H - 112 - height
    draw.rounded_rectangle(
        [MARGIN, top, MARGIN + 470, top + height],
        radius=10,
        fill=(0, 0, 0, 165),
        outline=(255, 255, 255, 60),
        width=1,
    )
    draw.text((MARGIN + 16, top + 8), "ORIGINAL SONG CREDITS", font=head, fill=accent)
    y = top + 30
    for line in lines:
        draw.text((MARGIN + 16, y), line, font=font, fill=(226, 226, 226, 235))
        y += 20


def _disclaimer(draw: ImageDraw.ImageDraw, text: str) -> None:
    font = fonts.load("body", 17, weight=600)
    width = _tracked_width(draw, text.upper(), font, 1.2)
    draw.rounded_rectangle([MARGIN, H - 56, W - MARGIN, H - 22], radius=8, fill=(0, 0, 0, 150))
    _tracked(
        draw,
        ((W - width) / 2, H - 50),
        text.upper(),
        font,
        (222, 222, 222, 230),
        1.2,
    )
