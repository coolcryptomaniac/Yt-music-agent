"""Configuration loading and lightweight typed access."""

from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config.yaml"


@dataclass
class Config:
    """Dict-backed config with dotted lookups, so new YAML keys need no code change."""

    data: dict[str, Any] = field(default_factory=dict)
    path: Path = DEFAULT_CONFIG_PATH

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def require(self, dotted: str) -> Any:
        value = self.get(dotted, None)
        if value is None:
            raise KeyError(f"missing required config key: {dotted}")
        return value

    def set(self, dotted: str, value: Any) -> None:
        parts = dotted.split(".")
        node = self.data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    def resolve_path(self, dotted: str) -> Path:
        raw = str(self.require(dotted))
        candidate = Path(raw).expanduser()
        return candidate if candidate.is_absolute() else (REPO_ROOT / candidate)


def load_config(path: str | os.PathLike[str] | None = None) -> Config:
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        raise FileNotFoundError(f"config file not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"config root must be a mapping, got {type(data).__name__}")
    return Config(data=copy.deepcopy(data), path=config_path)
