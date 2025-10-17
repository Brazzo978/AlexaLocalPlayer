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
PLAYER_API = os.getenv("PLAYER_API", "http://127.0.0.1:8000")
VERIFY_ALEXA = os.getenv("VERIFY_ALEXA", "true").lower() == "true"

app = Flask(__name__)
app.logger.setLevel(logging.INFO)
manager = SongManager(settings)

skill_builder = SkillBuilder()


@skill_builder.request_handler(can_handle_func=is_request_type("LaunchRequest"))
def launch_handler(handler_input):
    LOGGER.info("LaunchRequest")
    url = f"{PLAYER_API}/api/v1/songs/request"
    payload = {"song": "burn-di-ellie-goulding"}

    try:
        response = requests.post(url, json=payload, timeout=10)
        LOGGER.info(
            "Player API status=%s body=%s", response.status_code, response.text[:1000]
        )
        response.raise_for_status()
        payload = response.json()
        stream_url = payload["stream_url"]
    except Exception as exc:  # noqa: BLE001 - log and return a valid response to Alexa
        LOGGER.exception("Errore player API: %s", exc, exc_info=True)
        handler_input.response_builder.speak(
            "C'è stato un problema con il player. Riprova più tardi."
        ).set_should_end_session(True)
        return handler_input.response_builder.response

    stream = Stream(token="burn-token", url=stream_url, offset_in_milliseconds=0)
    handler_input.response_builder.speak("Riproduco Burn di Ellie Goulding").add_directive(
        PlayDirective(
            play_behavior=PlayBehavior.REPLACE_ALL,
            audio_item=AudioItem(stream=stream),
        )
    ).set_should_end_session(True)
    return handler_input.response_builder.response


@skill_builder.request_handler(can_handle_func=is_request_type("AudioPlayer.PlaybackStarted"))
def on_playback_started(handler_input):
    LOGGER.info("AudioPlayer.PlaybackStarted")
    return handler_input.response_builder.response


@skill_builder.request_handler(can_handle_func=is_request_type("AudioPlayer.PlaybackFinished"))
def on_playback_finished(handler_input):
    LOGGER.info("AudioPlayer.PlaybackFinished")
    return handler_input.response_builder.response


@skill_builder.request_handler(can_handle_func=is_request_type("AudioPlayer.PlaybackStopped"))
def on_playback_stopped(handler_input):
    LOGGER.info("AudioPlayer.PlaybackStopped")
    return handler_input.response_builder.response


@skill_builder.request_handler(
    can_handle_func=is_request_type("AudioPlayer.PlaybackNearlyFinished")
)
def on_playback_nearly_finished(handler_input):
    LOGGER.info("AudioPlayer.PlaybackNearlyFinished")
    return handler_input.response_builder.response


@skill_builder.request_handler(can_handle_func=is_request_type("AudioPlayer.PlaybackFailed"))
def on_playback_failed(handler_input):
    request_envelope = handler_input.request_envelope.request
    LOGGER.error(
        "AudioPlayer.PlaybackFailed: error=%s state=%s",
        getattr(request_envelope, "error", None),
        getattr(request_envelope, "current_playback_state", None),
    )
    return handler_input.response_builder.response


@skill_builder.request_handler(can_handle_func=is_request_type("SessionEndedRequest"))
def on_session_ended(handler_input):
    LOGGER.info("SessionEndedRequest: %s", handler_input.request_envelope.request.reason)
    return handler_input.response_builder.response


@skill_builder.exception_handler(can_handle_func=lambda handler_input, exception: True)
def all_exception_handler(handler_input, exception):
    LOGGER.exception("Alexa exception: %s", exception, exc_info=True)
    handler_input.response_builder.speak("Si è verificato un errore inatteso. Riprovo.")
    return handler_input.response_builder.response


skill = skill_builder.create()
alexa_handler = WebserviceSkillHandler(
    skill=skill,
    verify_signature=VERIFY_ALEXA,
    verify_timestamp=VERIFY_ALEXA,
    supported_application_ids=[ASK_SKILL_ID] if ASK_SKILL_ID else None,
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
    body = request.get_data()
    hdrs = {k: v for k, v in request.headers.items()}

    LOGGER.info("ASK req headers: %s", hdrs)
    LOGGER.info("ASK req body: %s", body.decode("utf-8", errors="ignore"))

    result = alexa_handler.verify_request_and_dispatch(hdrs, body)
    resp_body = alexa_handler.serialize_response(result)

    LOGGER.info("ASK resp: %s", result)
    try:
        LOGGER.info(
            "ASK resp body: %s",
            "".join(result.response.__dict__.keys()) if result.response else resp_body,
        )
    except Exception:  # noqa: BLE001 - defensive logging
        pass

    return Response(resp_body, 200, mimetype="application/json")


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
