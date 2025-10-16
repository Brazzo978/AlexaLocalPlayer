"""Song management utilities for the Alexa Local Player service."""

from __future__ import annotations

import logging
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from .config import Settings

LOGGER = logging.getLogger(__name__)


class SongAcquisitionError(RuntimeError):
    """Raised when a song cannot be acquired."""


@dataclass
class SongResult:
    """Representation of a fetched song file."""

    title: str
    file_path: Path


class SongManager:
    """Coordinate the song acquisition workflow."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.temp_dir = self.settings.ensure_temp_dir()

    def request_song(self, song_name: str) -> SongResult:
        """Acquire a song file for the given title.

        Args:
            song_name: The title requested by the Alexa skill.

        Returns:
            SongResult: Information about the stored audio file.
        """

        if not song_name or not song_name.strip():
            raise SongAcquisitionError("Il nome della canzone non può essere vuoto.")

        normalized_song = song_name.strip()
        command_str = self.settings.song_command_template.format(song=normalized_song)
        command = shlex.split(command_str)
        LOGGER.info("Esecuzione comando per scaricare la canzone: %s", command_str)

        existing_files = self._snapshot_temp_dir()

        try:
            subprocess.run(command, check=True)
        except subprocess.CalledProcessError as exc:
            raise SongAcquisitionError(
                f"Il comando per ottenere la canzone è fallito con codice {exc.returncode}."
            ) from exc

        try:
            song_file = self._wait_for_song(existing_files)
        except TimeoutError as exc:
            raise SongAcquisitionError(
                "La canzone non è stata trovata nella cartella temporanea entro il tempo limite."
            ) from exc

        LOGGER.info("Canzone salvata in %s", song_file)
        return SongResult(title=normalized_song, file_path=song_file)

    def _snapshot_temp_dir(self) -> Dict[Path, float]:
        """Create a snapshot of the files present in the temp directory."""

        snapshot: Dict[Path, float] = {}
        for item in self.temp_dir.glob("*"):
            if item.is_file():
                snapshot[item.resolve()] = item.stat().st_mtime
        return snapshot

    def _wait_for_song(self, snapshot: Dict[Path, float]) -> Path:
        """Wait until a new or updated audio file is present in the temp directory."""

        deadline = time.monotonic() + self.settings.timeout_seconds
        poll = max(0.1, self.settings.poll_interval_seconds)

        while time.monotonic() < deadline:
            candidate = self._find_candidate(snapshot)
            if candidate:
                return candidate
            time.sleep(poll)

        raise TimeoutError("Timeout in attesa del file audio.")

    def _find_candidate(self, snapshot: Dict[Path, float]) -> Path | None:
        """Look for a new or updated file that matches the allowed extensions."""

        allowed = {ext.lower() for ext in self.settings.allowed_extensions}
        newest_file: tuple[float, Path] | None = None

        for item in self.temp_dir.glob("*"):
            if not item.is_file():
                continue
            if item.suffix.lower() not in allowed:
                continue

            resolved = item.resolve()
            modified = item.stat().st_mtime
            previous = snapshot.get(resolved)

            if previous is None or modified > previous:
                if newest_file is None or modified > newest_file[0]:
                    newest_file = (modified, resolved)

        return newest_file[1] if newest_file else None
