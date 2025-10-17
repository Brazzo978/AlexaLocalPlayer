"""HTTP server entry-point for the Alexa Local Player service."""

from __future__ import annotations

import logging
import os
from urllib.parse import urljoin

import requests
from flask import Flask, Response, abort, jsonify, request, send_file
from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.utils import is_request_type
from ask_sdk_model.interfaces.audioplayer import (
    AudioItem,
    PlayBehavior,
    PlayDirective,
    Stream,
)
from ask_sdk_webservice_support.webservice_handler import (
    WebserviceSkillHandler,
)

from .config import settings
from .song_manager import SongAcquisitionError, SongManager

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
LOGGER = logging.getLogger(__name__)

ASK_SKILL_ID = os.getenv("ASK_SKILL_ID")
PLAYER_API = os.getenv("PLAYER_API", "http://127.0.0.1:8000")

app = Flask(__name__)
manager = SongManager(settings)

skill_builder = SkillBuilder()


@skill_builder.request_handler(can_handle_func=is_request_type("LaunchRequest"))
def launch_handler(handler_input):
    response = requests.post(
        f"{PLAYER_API}/api/v1/songs/request",
        json={"song": "burn-di-ellie-goulding"},
        timeout=10,
    )
    response.raise_for_status()
    stream_url = response.json()["stream_url"]
    stream = Stream(token="burn-token", url=stream_url, offset_in_milliseconds=0)
    handler_input.response_builder.speak("Riproduco Burn di Ellie Goulding").add_directive(
        PlayDirective(
            play_behavior=PlayBehavior.REPLACE_ALL,
            audio_item=AudioItem(stream=stream),
        )
    )
    return handler_input.response_builder.response


skill = skill_builder.create()
alexa_handler = WebserviceSkillHandler(
    skill=skill,
    verify_signature=True,
    verify_timestamp=True,
    supported_application_ids=[ASK_SKILL_ID] if ASK_SKILL_ID else None,
)


@app.post("/")
def alexa_entry():
    body = request.get_data()
    result = alexa_handler.verify_request_and_dispatch(dict(request.headers), body)
    return Response(alexa_handler.serialize_response(result), 200, mimetype="application/json")


@app.get("/health")
def health() -> tuple[str, int]:
    return "ok", 200


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
