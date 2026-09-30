"""Quién habló: cortes en las pausas, muestras de voz y nombres con la IA.

La pasada final con la reunión entera está en test_final_pass.py.
"""
import asyncio
import io
import json
import math
import struct
import uuid
import wave


from conftest import EchoTestUser

from echo_api.services import recording as rec
from echo_api.services.diarization import _replace_transcript, diarize_meeting, name_speakers
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


# ── Nombres con la IA ────────────────────────────────────────────


def _meeting_with_people(client):
    user = EchoTestUser(client, name="Mariana Gibson", org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    meeting = client.post("/api/meetings", json={"title": "Entrevista", "level": "primaria"}, headers=user.headers).json()
    meeting_id = uuid.UUID(meeting["id"])
    rows = [
        ("speaker_1", "Buenos días, soy la directora.", 0, 2500),
        ("speaker_2", "Queríamos hablar de Pedro. Está muy callado.", 2600, 11500),
    ]
    asyncio.run(_replace_transcript(meeting_id, rows, {}))
    return user, meeting_id


def _speakers(client, user, meeting_id):
    meeting = client.get(f"/api/meetings/{meeting_id}", headers=user.headers).json()
    names = {s["id"]: s["display_name"] or s["label"] for s in meeting["speakers"]}
    segments = client.get(f"/api/meetings/{meeting_id}/transcript", headers=user.headers).json()["segments"]
    return [(names.get(seg["speaker_id"]), seg["text"]) for seg in segments]


def test_ai_names_the_rest_or_leaves_a_suggestion(client):
    user, meeting_id = _meeting_with_people(client)
    assert _speakers(client, user, meeting_id) == [
        ("Persona 1", "Buenos días, soy la directora."),
        ("Persona 2", "Queríamos hablar de Pedro. Está muy callado."),
    ]

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


def test_without_transcription_keys_nothing_changes(client, monkeypatch):
    from echo_api.config import get_settings

    for field in ("openai_api_key", "groq_api_key", "elevenlabs_api_key", "deepgram_api_key"):
        monkeypatch.setattr(get_settings(), field, "")
    user = EchoTestUser(client, org_name="Colegio sin keys")
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
