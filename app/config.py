"""Application configuration helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Tuple


DEFAULT_ALLOWED_EXTENSIONS = (".mp3", ".m4a", ".wav", ".flac")


def _parse_extensions(raw: str | None) -> Tuple[str, ...]:
    if not raw:
        return DEFAULT_ALLOWED_EXTENSIONS
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    return tuple(part if part.startswith(".") else f".{part}" for part in parts) or DEFAULT_ALLOWED_EXTENSIONS


@dataclass(frozen=True)
class Settings:
    """Container for runtime configuration values."""

    temp_dir: Path = field(default_factory=lambda: Path(os.environ.get("TEMP_DIR", "/temp")))
    song_command_template: str = os.environ.get("SONG_COMMAND", "python3 scripts/XYZ.py -S {song}")
    poll_interval_seconds: float = float(os.environ.get("POLL_INTERVAL", "1.0"))
    timeout_seconds: float = float(os.environ.get("TIMEOUT_SECONDS", "120"))
    allowed_extensions: Tuple[str, ...] = field(
        default_factory=lambda: _parse_extensions(os.environ.get("ALLOWED_EXTENSIONS"))
    )
    public_base_url: str | None = os.environ.get("PUBLIC_BASE_URL") or None

    def ensure_temp_dir(self) -> Path:
        """Ensure the temporary directory exists and return it."""
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        return self.temp_dir


settings = Settings()
