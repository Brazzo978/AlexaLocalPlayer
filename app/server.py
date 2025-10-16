"""HTTP server entry-point for the Alexa Local Player service."""

from __future__ import annotations

import logging
import os
from urllib.parse import urljoin

from flask import Flask, abort, jsonify, request, send_file

from .config import settings
from .song_manager import SongAcquisitionError, SongManager

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
LOGGER = logging.getLogger(__name__)

app = Flask(__name__)
manager = SongManager(settings)


@app.post("/api/v1/songs/request")
def request_song() -> tuple[dict, int]:
    """Endpoint to request a song by name."""

    payload = request.get_json(silent=True) or {}
    song_name = payload.get("song") or payload.get("song_name")

    if not song_name:
        return jsonify({"error": "Il campo 'song' è obbligatorio."}), 400

    try:
        result = manager.request_song(song_name)
    except SongAcquisitionError as exc:
        LOGGER.error("Errore durante l'acquisizione della canzone: %s", exc)
        return jsonify({"error": str(exc)}), 500

    stream_url = _build_stream_url(result.file_path.name)

    return (
        jsonify(
            {
                "song": result.title,
                "file_name": result.file_path.name,
                "stream_url": stream_url,
            }
        ),
        200,
    )


@app.get("/songs/<path:filename>")
def stream_song(filename: str):
    """Serve a downloaded song file."""

    safe_path = (settings.temp_dir / filename).resolve()
    temp_dir = settings.temp_dir.resolve()

    if not str(safe_path).startswith(str(temp_dir)):
        abort(404)

    if not safe_path.exists() or not safe_path.is_file():
        abort(404)

    return send_file(safe_path, as_attachment=False)


def _build_stream_url(filename: str) -> str:
    base_url = settings.public_base_url
    if not base_url:
        scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
        base_url = f"{scheme}://{request.host}" if request.host else ""

    return urljoin(f"{base_url.rstrip('/')}/", f"songs/{filename}")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")
    LOGGER.info("Avvio del server sulla porta %s", port)
    app.run(host=host, port=port)
