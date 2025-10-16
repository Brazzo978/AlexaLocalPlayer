"""Example helper script that simulates the download of a song file."""

from __future__ import annotations

import argparse
import time
from pathlib import Path


def sanitize_filename(name: str) -> str:
    return "-".join(part for part in name.strip().split() if part)


def main() -> None:
    parser = argparse.ArgumentParser(description="Simula il download di una canzone")
    parser.add_argument("-S", "--song", required=True, help="Nome della canzone richiesta")
    parser.add_argument(
        "--temp-dir",
        default="/temp",
        help="Cartella dove salvare il file fittizio",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Tempo (in secondi) da attendere prima di creare il file",
    )
    args = parser.parse_args()

    temp_dir = Path(args.temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{sanitize_filename(args.song) or 'song'}.mp3"
    file_path = temp_dir / filename

    time.sleep(max(0, args.delay))
    file_path.write_bytes(b"Simulated audio data")

    print(f"File creato: {file_path}")


if __name__ == "__main__":
    main()
