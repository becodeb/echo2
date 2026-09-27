"""Quién habló: cortes en las pausas, separación con la reunión entera y nombres."""
import asyncio
import io
import json
import math
import struct
import uuid
import wave

import httpx

from conftest import EchoTestUser
from test_levels import _sql

from echo_api.services import recording as rec
from echo_api.services.diarization import DiarSegment, assign_speakers, diarize_meeting, name_speakers
from echo_api.services.stt.channels import is_prompt_echo
from echo_api.services.stt.windowing import find_cut

RATE = 16000


def _tone(seconds: float, amplitude: int = 8000, freq: float = 220.0) -> bytes:
    count = int(RATE * seconds)
    return struct.pack(f"<{count}h", *(int(amplitude * math.sin(2 * math.pi * freq * n / RATE)) for n in range(count)))


def _silence(seconds: float) -> bytes:
    return bytes(int(RATE * seconds) * 2)


# ── Cortes en las pausas ─────────────────────────────────────────


def test_short_audio_waits():
    assert find_cut(_tone(1.5)) is None


def test_cut_in_the_middle_of_a_pause():
    audio = _tone(4.5) + _silence(0.6)
    cut = find_cut(audio)
    assert cut is not None
    assert 4.5 * RATE * 2 <= cut <= 5.1 * RATE * 2


def test_a_quieter_voice_is_not_a_pause():
    # Reunión real 99b4b81c: Vanina hablaba más bajo que Bautista y se le
    # cortaba en medio de la frase como si fuera silencio.
    audio = _tone(3.0, amplitude=8000) + _tone(1.5, amplitude=2500)
    assert find_cut(audio) is None


def test_no_cut_while_still_speaking():
    assert find_cut(_tone(5.0)) is None


def test_continuous_speech_is_cut_at_the_quietest_moment():
    # Habla de corrido 12 s con un bajón de volumen a los 10,5 s.
    audio = _tone(10.5) + _tone(0.2, amplitude=900) + _tone(1.5)
    cut = find_cut(audio)
    assert cut is not None
    assert 10.4 * RATE * 2 <= cut <= 10.8 * RATE * 2


def test_noisy_room_still_finds_the_pause():
    noise = _tone(0.6, amplitude=500, freq=50)
    audio = _tone(4.5, amplitude=6000) + noise
    cut = find_cut(audio)
    assert cut is not None and cut > 4.5 * RATE * 2


# ── Asignación de voces al transcript ────────────────────────────


def test_whole_window_of_one_person():
    plan = assign_speakers([(0, 6000, "Buenos días a todos.")], [DiarSegment(200, 5800, "persona_1", "Buenos días a todos.")])
    assert plan == [[("persona_1", "Buenos días a todos.", 0, 6000)]]


def test_window_with_two_people_is_split_by_sentence():
    transcript = [(0, 6000, "Buenos días, soy la directora. Queríamos hablar de Pedro.")]
    diarized = [
        DiarSegment(0, 2500, "persona_1", "Buenos días; soy la directora."),
        DiarSegment(2600, 6000, "persona_2", "Queríamos hablar de Pedro."),
    ]
    [pieces] = assign_speakers(transcript, diarized)
    assert [(label, text) for label, text, _, _ in pieces] == [
        ("persona_1", "Buenos días, soy la directora."),
        ("persona_2", "Queríamos hablar de Pedro."),
    ]
    assert pieces[0][2] == 0 and pieces[1][3] == 6000
    assert pieces[0][3] == pieces[1][2] == 2600


def test_window_without_overlap_takes_the_nearest_voice():
    plan = assign_speakers([(10000, 12000, "Sí.")], [DiarSegment(12500, 14000, "persona_3", "Sí, claro.")])
    assert plan[0][0][0] == "persona_3"


# ── De punta a punta, con la API de OpenAI simulada ──────────────


class _FakeOpenAI:
    requests: list[dict] = []
    segments: list[dict] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, data=None, files=None):
        _FakeOpenAI.requests.append(dict(data or {}))
        return httpx.Response(200, json={"segments": _FakeOpenAI.segments}, request=httpx.Request("POST", url))


def _meeting_with_audio(client, seconds: float = 12.0):
    user = EchoTestUser(client, name="Mariana Gibson", org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    saved = client.put(
        "/api/org/ai-settings", json={"stt_provider": "openai", "stt_api_key": "sk-test"}, headers=user.headers
    )
    assert saved.status_code == 200, saved.text
    meeting = client.post("/api/meetings", json={"title": "Entrevista", "level": "primaria"}, headers=user.headers).json()
    meeting_id = uuid.UUID(meeting["id"])
    for seq, (start, end, text) in enumerate(
        [(0, 6000, "Buenos días, soy la directora. Queríamos hablar de Pedro."), (6000, 12000, "Está muy callado.")],
        start=1,
    ):
        _sql(
            "INSERT INTO transcript_segments (id, meeting_id, organization_id, seq, start_ms, end_ms, text, is_final, edited,"
            " created_at, updated_at) VALUES (:id, :m, :o, :seq, :s, :e, :t, true, false, now(), now())",
            id=str(uuid.uuid4()), m=str(meeting_id), o=user.org_id, seq=seq, s=start, e=end, t=text,
        )
    rec.pcm_path(meeting_id).write_bytes(_tone(seconds))
    return user, meeting_id


def _speakers(client, user, meeting_id):
    meeting = client.get(f"/api/meetings/{meeting_id}", headers=user.headers).json()
    names = {s["id"]: s["display_name"] or s["label"] for s in meeting["speakers"]}
    segments = client.get(f"/api/meetings/{meeting_id}/transcript", headers=user.headers).json()["segments"]
    return [(names.get(seg["speaker_id"]), seg["text"]) for seg in segments]


def test_diarization_assigns_people_and_splits_turns(client, monkeypatch):
    user, meeting_id = _meeting_with_audio(client)
    _FakeOpenAI.requests = []
    _FakeOpenAI.segments = [
        {"speaker": "A", "start": 0.0, "end": 2.5, "text": "Buenos días; soy la directora."},
        {"speaker": "B", "start": 2.6, "end": 6.0, "text": "Queríamos hablar de Pedro."},
        {"speaker": "B", "start": 6.2, "end": 11.5, "text": "Está muy callado."},
    ]
    monkeypatch.setattr(httpx, "AsyncClient", _FakeOpenAI)
    assert asyncio.run(diarize_meeting(meeting_id)) is True
    monkeypatch.undo()

    form = _FakeOpenAI.requests[0]
    assert form["model"] == "gpt-4o-transcribe-diarize"
    assert "prompt" not in form
    assert _speakers(client, user, meeting_id) == [
        ("Persona 1", "Buenos días, soy la directora."),
        ("Persona 2", "Queríamos hablar de Pedro."),
        ("Persona 2", "Está muy callado."),
    ]


def test_known_voice_comes_out_with_its_name(client, monkeypatch):
    user, meeting_id = _meeting_with_audio(client)
    # La persona que graba cargó su voz en Ajustes → Mi voz.
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(_silence(0.5) + _tone(5.0) + _silence(0.5))
    saved = client.post(
        "/api/me/voice",
        files={"audio": ("voz.wav", buffer.getvalue(), "audio/wav")},
        data={"consent": "true"},
        headers={"Authorization": f"Bearer {user.token}"},
    )
    assert saved.status_code == 200, saved.text
    assert 4000 <= saved.json()["duration_ms"] <= 6000

    _FakeOpenAI.requests = []
    _FakeOpenAI.segments = [
        {"speaker": "voz_1", "start": 0.0, "end": 2.5, "text": "Buenos días, soy la directora."},
        {"speaker": "A", "start": 2.6, "end": 11.5, "text": "Queríamos hablar de Pedro. Está muy callado."},
    ]
    monkeypatch.setattr(httpx, "AsyncClient", _FakeOpenAI)
    assert asyncio.run(diarize_meeting(meeting_id)) is True
    monkeypatch.undo()

    form = _FakeOpenAI.requests[0]
    assert form["known_speaker_names[]"] == ["voz_1"]
    assert form["known_speaker_references[]"][0].startswith("data:audio/wav;base64,")
    people = [name for name, _ in _speakers(client, user, meeting_id)]
    assert people[0] == "Mariana Gibson"
    assert people[1] == "Persona 1"


def test_ai_names_the_rest_or_leaves_a_suggestion(client, monkeypatch):
    user, meeting_id = _meeting_with_audio(client)
    _FakeOpenAI.segments = [
        {"speaker": "A", "start": 0.0, "end": 2.5, "text": "Buenos días, soy la directora."},
        {"speaker": "B", "start": 2.6, "end": 11.5, "text": "Queríamos hablar de Pedro. Está muy callado."},
    ]
    monkeypatch.setattr(httpx, "AsyncClient", _FakeOpenAI)
    asyncio.run(diarize_meeting(meeting_id))
    monkeypatch.undo()

    class FakeLLM:
        async def chat_json(self, system, messages):
            assert "Persona 1" in messages[0]["content"]
            return {"speakers": [
                {"label": "Persona 1", "name": None, "role": "directora", "confidence": 0.9},
                {"label": "Persona 2", "name": "Laura", "role": "madre de Pedro", "confidence": 0.5},
            ]}

    assert asyncio.run(name_speakers(meeting_id, FakeLLM())) == 1
    meeting = client.get(f"/api/meetings/{meeting_id}", headers=user.headers).json()
    by_label = {s["label"]: s for s in meeting["speakers"]}
    assert by_label["Persona 1"]["display_name"] == "directora"
    assert by_label["Persona 2"]["display_name"] is None
    assert by_label["Persona 2"]["identity_suggestion"]["person_name"] == "Laura (madre de Pedro)"


def test_without_openai_nothing_changes(client):
    user = EchoTestUser(client, org_name="Colegio sin OpenAI")
    meeting = client.post("/api/meetings", json={"title": "x", "level": "primaria"}, headers=user.headers).json()
    meeting_id = uuid.UUID(meeting["id"])
    rec.pcm_path(meeting_id).write_bytes(_tone(8))
    assert asyncio.run(diarize_meeting(meeting_id)) is False
    rec.pcm_path(meeting_id).unlink()


def test_voice_sample_needs_consent_and_voice(client):
    user = EchoTestUser(client, org_name="Colegio voz")
    auth = {"Authorization": f"Bearer {user.token}"}

    def upload(pcm: bytes, consent: str):
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(RATE)
            out.writeframes(pcm)
        return client.post("/api/me/voice", files={"audio": ("v.wav", buffer.getvalue(), "audio/wav")},
                           data={"consent": consent}, headers=auth)

    assert upload(_tone(5), "false").status_code == 400
    assert upload(_silence(5), "true").status_code == 400
    assert upload(_tone(5), "true").status_code == 200
    assert client.get("/api/me/voice", headers=auth).json()["has_sample"] is True
    assert client.delete("/api/me/voice", headers=auth).status_code == 204
    assert client.get("/api/me/voice", headers=auth).json()["has_sample"] is False


def test_dictionary_echo_is_not_speech():
    vocabulary = ["Mariana Gibson", "Glifing", "Trinity"]
    assert is_prompt_echo("Gibson", vocabulary)
    assert is_prompt_echo("Glifing, Trinity.", vocabulary)
    assert not is_prompt_echo("Sigue con Glifing", vocabulary)
    assert not is_prompt_echo("Gibson", [])


# ── Basura sobre ruido y una sola grabadora ──────────────────────


def test_noise_transcripts_are_dropped():
    from echo_api.services.stt.channels import is_noise_transcript

    # Salidas reales del modelo sobre audio mezclado (reunión 6282254e).
    for text in ("مردمیت", "වඳලා.", "可是。", "תודה רבה.", "はい。", "выпадков.", "click", "crackling", "。"):
        assert is_noise_transcript(text, "es"), text
    for text in ("Hola.", "Hola, ¿cómo estás?", "Sí, mi nombre es Bautista.", "Pedro está en quinto grado."):
        assert not is_noise_transcript(text, "es"), text
    # En una reunión en japonés el japonés es habla.
    assert not is_noise_transcript("はい。", "ja")


def test_gpt6_is_treated_like_gpt5():
    from echo_api.services.llm.base import is_reasoning_model

    assert is_reasoning_model("gpt-6-luna")
    assert is_reasoning_model("gpt-5.6-luna")
    assert not is_reasoning_model("gpt-4o-mini")


def test_second_recorder_takes_over_and_the_first_is_closed(client):
    import pytest
    from starlette.websockets import WebSocketDisconnect

    user = EchoTestUser(client, org_name="Colegio dos pestañas")
    meeting = client.post("/api/meetings", json={"title": "x", "level": "primaria"}, headers=user.headers).json()
    url = f"/api/meetings/{meeting['id']}/ws?token={user.token}"
    hello = json.dumps({"type": "hello", "role": "recorder", "sample_rate": 16000, "transcribe": False})
    with client.websocket_connect(url) as first:
        first.send_text(hello)
        first.receive_text()
        with client.websocket_connect(url) as second:
            second.send_text(hello)
            assert json.loads(second.receive_text())["type"] == "hello_ack"
            with pytest.raises(WebSocketDisconnect) as closed:
                first.receive_text()
            assert closed.value.code == 4409
    rec.pcm_path(uuid.UUID(meeting["id"])).unlink(missing_ok=True)


# ── Transcripción final con la reunión entera ────────────────────


def test_final_text_takes_speakers_and_times_from_the_voices():
    from echo_api.services.diarization import merge_text_with_voices

    # El texto final (bien escrito) y la separación (con errores) de la reunión real 99b4b81c.
    text = "Hola, yo soy Bautista Goñi. Hola, hola, hola. Soy Vanina. Ok, ¿y vos quién sos? El Choto."
    voices = [
        DiarSegment(3000, 5500, "voz_1", "Hola, yo soy Bautista Goñi."),
        DiarSegment(5600, 7200, "persona_1", "hola, hola, hola, soy Vanina,"),
        DiarSegment(8000, 10300, "voz_1", "Ok, ¿y vos quién sos?"),
        DiarSegment(10800, 11500, "persona_1", "El Choto."),
    ]
    pieces = merge_text_with_voices(text, voices, 3000, 12000)
    assert [(label, piece) for label, piece, _, _ in pieces] == [
        ("voz_1", "Hola, yo soy Bautista Goñi."),
        ("persona_1", "Hola, hola, hola. Soy Vanina."),
        ("voz_1", "Ok, ¿y vos quién sos?"),
        ("persona_1", "El Choto."),
    ]
    starts = [start for _, _, start, _ in pieces]
    assert starts == sorted(starts) and starts[0] == 3000
    assert pieces[-1][3] == 12000
    assert all(pieces[i][3] == pieces[i + 1][2] for i in range(len(pieces) - 1))


def test_meeting_is_retranscribed_whole_and_replaces_live_text(client, monkeypatch):
    user, meeting_id = _meeting_with_audio(client)

    class FakeBoth(_FakeOpenAI):
        async def post(self, url, headers=None, data=None, files=None):
            _FakeOpenAI.requests.append(dict(data or {}))
            if data["model"] == "gpt-4o-transcribe":
                body = {"text": "Buenos días, soy la directora. Queríamos hablar de Pedro. Está muy callado."}
            else:
                body = {"segments": [
                    {"speaker": "A", "start": 0.0, "end": 2.5, "text": "Buenos días soy la directora"},
                    {"speaker": "B", "start": 2.6, "end": 11.5, "text": "queríamos hablar de Pedro está muy callado"},
                ]}
            return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    _FakeOpenAI.requests = []
    monkeypatch.setattr(httpx, "AsyncClient", FakeBoth)
    assert asyncio.run(diarize_meeting(meeting_id)) is True
    monkeypatch.undo()

    full = next(form for form in _FakeOpenAI.requests if form["model"] == "gpt-4o-transcribe")
    assert full["language"] == "es"
    assert "Mariana Gibson" in full["prompt"]  # quien grabó va como pista de nombres
    assert _speakers(client, user, meeting_id) == [
        ("Persona 1", "Buenos días, soy la directora."),
        ("Persona 2", "Queríamos hablar de Pedro. Está muy callado."),
    ]

