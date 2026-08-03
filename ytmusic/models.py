"""Data structures passed between pipeline stages."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_len: int = 48) -> str:
    slug = _SLUG_RE.sub("-", text.lower()).strip("-")
    return slug[:max_len].strip("-") or "track"


@dataclass
class TrackPlan:
    """Everything the agent decides *before* any media exists."""

    index: int
    title: str
    mood: str
    genre: str
    bpm: int
    # Suno "Style of Music" box (paid plans accept long, comma-separated descriptors).
    suno_style: str
    # Suno lyrics box; empty string means instrumental.
    suno_lyrics: str = ""
    instrumental: bool = True
    art_prompt: str = ""
    # Thumbnail typography. `title_display` may be Devanagari (or any script);
    # `title` stays ASCII-ish because it is used for folder slugs.
    title_display: str = ""
    tagline: str = ""
    badge: str = ""
    # original | cover | instrumental - drives prompts, metadata and thumbnail extras.
    content_type: str = "original"
    credits: dict[str, str] = field(default_factory=dict)
    disclaimer: str = ""
    youtube_title: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)

    @property
    def slug(self) -> str:
        return slugify(self.title)

    def folder_name(self) -> str:
        return f"{self.index:02d}_{self.slug}"


@dataclass
class TrackArtifacts:
    """Files produced for a single track."""

    plan: TrackPlan
    directory: Path
    audio: Path | None = None
    art: Path | None = None
    thumbnail: Path | None = None
    video: Path | None = None
    duration: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self.plan)
        payload.update(
            {
                "directory": str(self.directory),
                "audio": str(self.audio) if self.audio else None,
                "art": str(self.art) if self.art else None,
                "thumbnail": str(self.thumbnail) if self.thumbnail else None,
                "video": str(self.video) if self.video else None,
                "duration": round(self.duration, 2),
                "notes": self.notes,
            }
        )
        return payload

    def write_manifest(self) -> Path:
        target = self.directory / "manifest.json"
        target.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return target
