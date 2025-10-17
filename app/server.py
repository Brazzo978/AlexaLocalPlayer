"""HTTP server entry-point for the Alexa Local Player service."""

from __future__ import annotations

import logging
import os
from urllib.parse import urljoin

import requests
from flask import Flask, Response, abort, jsonify, request, send_file
from ask_sdk_core.exceptions import AskSdkException
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
VERIFY_ALEXA = os.getenv("VERIFY_ALEXA", "true").lower() == "true"
PLAYER_API = os.getenv("PLAYER_API", "http://127.0.0.1:8000")

app = Flask(__name__)
app.logger.setLevel(logging.INFO)
manager = SongManager(settings)

skill_builder = SkillBuilder()


@skill_builder.request_handler(can_handle_func=is_request_type("LaunchRequest"))
def launch_handler(handler_input):
    app.logger.info("LaunchRequest")
    url = f"{PLAYER_API}/api/v1/songs/request"
    payload = {"song": "burn-di-ellie-goulding"}

    try:
        response = requests.post(url, json=payload, timeout=10)
        app.logger.info(
            "Player API status=%s body=%s", response.status_code, response.text[:1000]
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        app.logger.error("Player API request failed: %s", exc, exc_info=True)
        return (
            handler_input.response_builder.speak(
                "Al momento non riesco a riprodurre musica. Riprova tra qualche minuto."
            )
            .set_should_end_session(True)
            .response
        )

    try:
        payload = response.json()
    except ValueError:
        app.logger.error("Player API returned invalid JSON: %s", response.text[:1000])
        return (
            handler_input.response_builder.speak(
                "C'è stato un problema con il player. Riprova più tardi."
            )
            .set_should_end_session(True)
            .response
        )

    stream_url = payload.get("stream_url")
    if not stream_url:
        app.logger.error("Player API response missing stream_url: %s", payload)
        return (
            handler_input.response_builder.speak(
                "Non riesco a riprodurre il brano richiesto in questo momento."
            )
            .set_should_end_session(True)
            .response
        )

    stream = Stream(token="burn-token", url=stream_url, offset_in_milliseconds=0)
    handler_input.response_builder \
        .speak("Riproduco Burn di Ellie Goulding") \
        .set_should_end_session(True) \
        .add_directive(
            PlayDirective(
                play_behavior=PlayBehavior.REPLACE_ALL,
                audio_item=AudioItem(stream=stream),
            )
        )
    return handler_input.response_builder.response


def _register_noop(event_type: str):

    @skill_builder.request_handler(can_handle_func=is_request_type(event_type))
    def _noop(handler_input):
        return handler_input.response_builder.response

    return _noop


for event_type in [
    "AudioPlayer.PlaybackStarted",
    "AudioPlayer.PlaybackFinished",
    "AudioPlayer.PlaybackStopped",
    "AudioPlayer.PlaybackNearlyFinished",
    "AudioPlayer.PlaybackFailed",
    "SessionEndedRequest",
]:
    _register_noop(event_type)


@skill_builder.exception_handler(can_handle_func=lambda handler_input, exception: True)
def _on_error(handler_input, exception):
    app.logger.error("ASK ERROR: %s", exception, exc_info=True)
    return handler_input.response_builder.speak(
        "Errore temporaneo del player. Riprova."
    ).response


skill = skill_builder.create()
alexa_handler = WebserviceSkillHandler(
    skill=skill,
    verify_signature=VERIFY_ALEXA,
    verify_timestamp=VERIFY_ALEXA,
)


def _extract_application_id(handler_input) -> str | None:
    envelope = handler_input.request_envelope

    if envelope.session and envelope.session.application:
        return envelope.session.application.application_id

    system = envelope.context.system if envelope.context else None
    if system and system.application:
        return system.application.application_id

    return None


if VERIFY_ALEXA and ASK_SKILL_ID:

    @skill_builder.global_request_interceptor()
    def _verify_application_id(handler_input):
        application_id = _extract_application_id(handler_input)

        if application_id != ASK_SKILL_ID:
            raise AskSdkException(
                f"Unexpected Alexa skill id '{application_id}'"
            )


@app.post("/")
def alexa_entry():
    hdrs = dict(request.headers)
    masked = {
        key: (
            "***redacted***"
            if key.lower()
            in {"signature", "signature-256", "signaturecertchainurl", "authorization"}
            else value
        )
        for key, value in hdrs.items()
    }
    body_str = request.get_data(as_text=True)

    app.logger.info("ASK req headers: %s", masked)
    app.logger.info("ASK req body: %s", body_str[:2000])

    resp_str = alexa_handler.verify_request_and_dispatch(hdrs, body_str)

    app.logger.info("ASK resp: %s", resp_str)
    return Response(resp_str, 200, mimetype="application/json")


@app.after_request
def _log_ask_response(resp):
    if request.path == "/":
        app.logger.info("ASK resp body: %s", resp.get_data(as_text=True)[:2000])
    return resp


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
