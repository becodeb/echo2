"""Cada modelo de transcripción recibe lo que acepta y se lee lo que devuelve.

Verificado contra la API real (2026-09-26): gpt-4o-transcribe rechaza
`verbose_json`, y los *-diarize rechazan el prompt (diccionario) y el idioma.
Mandarles lo que no aceptan es un 400 por cada tramo de la reunión.
"""
import asyncio
import uuid

import httpx

from conftest import EchoTestUser
from test_levels import _sql

from echo_api.services.stt.base import OPENAI_FILE_MODEL, OPENAI_LIVE_MODEL, get_stt_provider
from echo_api.services.stt.whisper_api import response_format_for


class _Capture:
    """Reemplaza httpx.AsyncClient: guarda el formulario y responde `payload`."""

    sent: list[dict] = []
    payload: dict = {}

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, data=None, files=None):
        _Capture.sent.append(dict(data or {}))
        return httpx.Response(200, json=_Capture.payload, request=httpx.Request("POST", url))


def _run(monkeypatch, payload, call):
    _Capture.sent = []
    _Capture.payload = payload
    monkeypatch.setattr(httpx, "AsyncClient", _Capture)
    return asyncio.run(call)


def test_response_formats():
    assert response_format_for("whisper-1") == "verbose_json"
    assert response_format_for("whisper-large-v3-turbo") == "verbose_json"
    assert response_format_for("gpt-4o-transcribe") == "json"
    assert response_format_for("gpt-4o-mini-transcribe") == "json"
    assert response_format_for("gpt-transcribe") == "json"
    assert response_format_for("gpt-4o-transcribe-diarize") == "diarized_json"


def test_openai_default_live_model_gets_dictionary_and_fills_the_window(monkeypatch):
    provider = get_stt_provider("openai", "k")
    assert provider.model == OPENAI_LIVE_MODEL == "gpt-4o-transcribe"
    six_seconds = bytes(16000 * 2 * 6)
    result = _run(
        monkeypatch,
        {"text": "Buenos días,  soy la directora."},
        provider.transcribe_chunk(six_seconds, 16000, "es", ["Arroyo Arzubi", "Glifing"], offset_ms=12000),
    )
    form = _Capture.sent[0]
    assert form["model"] == "gpt-4o-transcribe"
    assert form["response_format"] == "json"
    assert form["language"] == "es"
    assert "Arroyo Arzubi" in form["prompt"]
    [segment] = result.segments
    assert segment.text == "Buenos días, soy la directora."
    assert (segment.start_ms, segment.end_ms) == (12000, 18000)


def test_openai_default_file_model_separates_speakers_without_prompt(monkeypatch):
    provider = get_stt_provider("openai", "k")
    assert provider.file_model == OPENAI_FILE_MODEL
    payload = {
        "duration": 9.0,
        "segments": [
            {"speaker": "A", "start": 0.0, "end": 3.0, "text": " Buenos días."},
            {"speaker": "B", "start": 3.5, "end": 9.0, "text": " Venimos por Pedro."},
        ],
    }
    result = _run(monkeypatch, payload, provider.transcribe_file(b"RIFF", "a.wav", "es", ["Glifing"]))
    form = _Capture.sent[0]
    assert form["model"] == "gpt-4o-transcribe-diarize"
    assert form["response_format"] == "diarized_json"
    assert form["chunking_strategy"] == "auto"
    assert "prompt" not in form and "language" not in form
    assert [s.speaker for s in result.segments] == ["Speaker A", "Speaker B"]
    assert result.segments[1].end_ms == 9000


def test_model_chosen_by_the_school_is_used_for_everything(monkeypatch):
    provider = get_stt_provider("openai", "k", "whisper-1")
    assert provider.model == provider.file_model == "whisper-1"
    _run(monkeypatch, {"segments": []}, provider.transcribe_chunk(bytes(3200), 16000, "es", ["x"]))
    assert _Capture.sent[0]["response_format"] == "verbose_json"


def test_announcement_is_shown_once_per_person_across_schools(client):
    user = EchoTestUser(client, org_name="Sede uno")
    second = client.post(
        "/api/auth/organizations", json={"name": "Sede dos"}, headers={"Authorization": f"Bearer {user.token}"}
    ).json()["id"]
    kind = "announcement:prueba"
    for org_id in (user.org_id, second):
        _sql(
            "INSERT INTO notifications (id, user_id, organization_id, kind, title, created_at, updated_at) "
            "VALUES (:id, :user, :org, :kind, 'Aviso', now(), now())",
            id=str(uuid.uuid4()), user=user.user_id, org=org_id, kind=kind,
        )
    unread = client.get("/api/notifications?unread_only=true", headers=user.headers).json()["notifications"]
    [announcement] = [item for item in unread if item["kind"] == kind]
    assert client.post(f"/api/notifications/{announcement['id']}/read", headers=user.headers).status_code == 204

    other_headers = {**user.headers, "X-Organization-Id": second}
    unread_other = client.get("/api/notifications?unread_only=true", headers=other_headers).json()["notifications"]
    assert not [item for item in unread_other if item["kind"] == kind]


def test_groq_is_deterministic_and_whisper_turbo(monkeypatch):
    provider = get_stt_provider("groq", "k")
    assert provider.model == "whisper-large-v3-turbo"
    _run(monkeypatch, {"segments": []}, provider.transcribe_chunk(bytes(3200), 16000, "es", ["Glifing"]))
    form = _Capture.sent[0]
    assert form["temperature"] == "0.0"
    assert form["language"] == "es"
    assert form["response_format"] == "verbose_json"
    assert form["prompt"] == "Glifing."


# Respuesta de Scribe v2 recortada con la forma real de la API: palabras con
# espacios intercalados, speaker_id desde speaker_0 y entidades.
SCRIBE_PAYLOAD = {
    "language_code": "spa",
    "text": "Hola, soy Vanina. ¿Cómo están? Bien.",
    "words": [
        {"text": "Hola,", "start": 0.1, "end": 0.4, "type": "word", "speaker_id": "speaker_3", "logprob": -0.1},
        {"text": " ", "start": 0.4, "end": 0.45, "type": "spacing", "speaker_id": "speaker_3"},
        {"text": "soy", "start": 0.45, "end": 0.6, "type": "word", "speaker_id": "speaker_3"},
        {"text": " ", "start": 0.6, "end": 0.62, "type": "spacing"},
        {"text": "Vanina.", "start": 0.62, "end": 1.1, "type": "word", "speaker_id": None},
        {"text": "(risas)", "start": 1.1, "end": 1.5, "type": "audio_event"},
        {"text": "¿Cómo", "start": 3.0, "end": 3.2, "type": "word", "speaker_id": "speaker_3"},
        {"text": "están?", "start": 3.2, "end": 3.6, "type": "word", "speaker_id": "speaker_3"},
        {"text": "Bien.", "start": 4.0, "end": 4.3, "type": "word", "speaker_id": "speaker_0"},
    ],
    "entities": [{"text": "Vanina", "entity_type": "person_name", "start_char": 10, "end_char": 16}],
}


def test_elevenlabs_request_asks_for_words_speakers_and_entities(monkeypatch):
    provider = get_stt_provider("elevenlabs", "k")
    vocabulary = ["Glifing", "x" * 60, "uno dos tres cuatro cinco seis", "Glifing"]
    _run(monkeypatch, SCRIBE_PAYLOAD, provider.transcribe_file(b"RIFF", "a.wav", "es", vocabulary))
    form = _Capture.sent[0]
    assert form["model_id"] == "scribe_v2"
    assert form["language_code"] == "spa"
    assert form["diarize"] == "true"
    assert form["timestamps_granularity"] == "word"
    assert form["tag_audio_events"] == "false"
    # Los términos que la API rechazaría (largos o de más de 5 palabras) no van.
    assert form["keyterms"] == ["Glifing"]
    assert form["entity_detection"] == ["pii", "phi"]
    assert "enable_logging" not in form


def test_elevenlabs_words_become_turns_with_a_person_each(monkeypatch):
    provider = get_stt_provider("elevenlabs", "k")
    result = _run(monkeypatch, SCRIBE_PAYLOAD, provider.transcribe_file(b"RIFF", "a.wav", "es"))
    assert [w.text for w in result.words] == ["Hola,", "soy", "Vanina.", "¿Cómo", "están?", "Bien."]
    # Nadie queda sin persona: "Vanina." hereda la de la palabra de al lado.
    assert all(w.speaker for w in result.words)
    assert [(s.speaker, s.text) for s in result.segments] == [
        ("speaker_1", "Hola, soy Vanina."),
        ("speaker_1", "¿Cómo están?"),
        ("speaker_2", "Bien."),
    ]
    assert (result.segments[0].start_ms, result.segments[0].end_ms) == (100, 1100)
    assert [(e.text, e.entity_type) for e in result.entities] == [("Vanina", "person_name")]
