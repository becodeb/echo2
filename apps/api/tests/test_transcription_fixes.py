"""Lo que se perdía del transcript, y la reunión real que lo mostró.

Reunión 89ddbc9d ("Prueba", 28 s, participantes Bau y Delfi, grabó Bautista
Goñi): la transcripción final devolvió "Bau, Delfi, Bautista Goñi, Prueba.",
que es la pista de nombres que se le manda, y la red de seguridad llenó el
transcript con el texto flojo de la separación de voces. Se perdieron "Yo
tengo que tener la compu ahí, prendida", "Sí, está" y "Pero nada, al
terminar", y los nombres de la IA salieron cruzados.
"""
import asyncio
import json
import uuid

import httpx
from conftest import EchoTestUser
from test_levels import _sql
from test_speakers import _FakeOpenAI, _silence, _speakers, _tone

from echo_api.services import recording as rec
from echo_api.services.diarization import (
    DiarSegment,
    agreement,
    diarize_meeting,
    fallback_pieces,
    name_speakers,
    strip_prompt_echo,
)
from echo_api.services.stt.base import SttResult, SttSegment
from echo_api.services.stt.channels import is_silent, strip_hallucinations

ECHO = "Bau, Delfi, Bautista Goñi, Prueba."
# Lo que se dijo (referencia, Whisper sobre el audio de la reunión).
SAID = (
    "Yo tengo que tener la compu ahí, prendida. ¿La compu o el celular? Mira, ahora mismo si yo apago "
    "el celular, esto debería estar funcionando. Sí, está funcionando. Una vez termina, te hace toda la "
    "transcripción entera. Esto te va mostrando un poquito, no te muestra todo, porque nada, no detecta "
    "en vivo en vivo, pero después con la grabación hace una segunda pasada, digamos, y transcribió todo "
    "perfecto. Pero nada, al terminar."
)
# Lo que escuchó la separación de voces en esa reunión (el texto que terminó a la vista).
VOICES = [
    {"speaker": "A", "start": 0.4, "end": 2.4, "text": "se supone que lo tengo apagado y prendida"},
    {"speaker": "B", "start": 2.9, "end": 12.0, "text": (
        "o la compu o el celular mira ahora mismo si yo apago el celular esto debería estar funcionando "
        "funcionando nada")},
    {"speaker": "B", "start": 13.3, "end": 27.2, "text": (
        "una vez termina te hace toda la transcripción entera esto te va mostrando un poquito no te muestra "
        "todo porque nada no detectan vivo en vivo pero que después con la grabación hace una segunda pasada "
        "digamos y transcribe todo perfecto")},
]
LIVE = [
    (0, 7000, "Yo tengo que tener la combo ahí, prendida. ¿La combo o el celular? Mira, ahora mismo si yo apago el celular."),
    (7000, 12000, "Esto debería estar funcionando. Sí, está funcionando."),
    (12000, 28800, "Una vez termina, te hace toda la transcripción entera."),
]


def _prueba_meeting(client):
    user = EchoTestUser(client, name="Bautista Goñi", org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    saved = client.put(
        "/api/org/ai-settings", json={"stt_provider": "openai", "stt_api_key": "sk-test"}, headers=user.headers
    )
    assert saved.status_code == 200, saved.text
    meeting = client.post(
        "/api/meetings",
        json={"title": "Prueba", "level": "primaria", "participants": [{"name": "Bau"}, {"name": "Delfi"}]},
        headers=user.headers,
    ).json()
    meeting_id = uuid.UUID(meeting["id"])
    for seq, (start, end, text) in enumerate(LIVE, start=1):
        _sql(
            "INSERT INTO transcript_segments (id, meeting_id, organization_id, seq, start_ms, end_ms, text, is_final, edited,"
            " created_at, updated_at) VALUES (:id, :m, :o, :seq, :s, :e, :t, true, false, now(), now())",
            id=str(uuid.uuid4()), m=str(meeting_id), o=user.org_id, seq=seq, s=start, e=end, t=text,
        )
    rec.pcm_path(meeting_id).write_bytes(_tone(28.8))
    return user, meeting_id


def _fake_openai(final_with_prompt: str, final_without_prompt: str):
    class Fake(_FakeOpenAI):
        async def post(self, url, headers=None, data=None, files=None):
            _FakeOpenAI.requests.append(dict(data or {}))
            if data["model"] == "gpt-4o-transcribe":
                body = {"text": final_with_prompt if "prompt" in data else final_without_prompt}
            else:
                body = {"segments": VOICES}
            return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    return Fake


# ── La transcripción final no puede ser la pista ─────────────────


def test_the_prompt_echo_is_retried_without_the_hint(client, monkeypatch):
    user, meeting_id = _prueba_meeting(client)
    _FakeOpenAI.requests = []
    monkeypatch.setattr(httpx, "AsyncClient", _fake_openai(ECHO, SAID))
    assert asyncio.run(diarize_meeting(meeting_id)) is True
    monkeypatch.undo()

    finals = [form for form in _FakeOpenAI.requests if form["model"] == "gpt-4o-transcribe"]
    assert len(finals) == 2
    # La pista son los nombres de la reunión: lo mismo que volvió como "texto".
    assert finals[0]["prompt"].startswith("Bau, Delfi, Bautista Goñi")
    assert "prompt" not in finals[1]

    lines = _speakers(client, user, meeting_id)
    text = " ".join(piece for _, piece in lines)
    assert "Bau, Delfi" not in text
    assert text == SAID  # nada se perdió: ni el principio, ni "Sí, está", ni el final
    assert lines[0] == ("Persona 1", "Yo tengo que tener la compu ahí, prendida.")
    assert {name for name, _ in lines[1:]} == {"Persona 2"}
    rec.pcm_path(meeting_id).unlink(missing_ok=True)


def test_when_the_final_text_is_not_trustworthy_the_live_text_stays(client, monkeypatch):
    user, meeting_id = _prueba_meeting(client)
    _FakeOpenAI.requests = []
    monkeypatch.setattr(httpx, "AsyncClient", _fake_openai(ECHO, "Gracias."))
    assert asyncio.run(diarize_meeting(meeting_id)) is True
    monkeypatch.undo()

    lines = _speakers(client, user, meeting_id)
    text = " ".join(piece for _, piece in lines)
    # Antes: "Bau, Delfi, Bautista Goñi, Prueba." + el texto de la separación.
    assert text == " ".join(live for _, _, live in LIVE)
    assert all(name is not None for name, _ in lines)
    rec.pcm_path(meeting_id).unlink(missing_ok=True)


def test_the_hint_is_stripped_wherever_it_shows_up():
    vocabulary = ["Bau", "Delfi", "Bautista Goñi", "Prueba"]
    assert strip_prompt_echo(ECHO, vocabulary) == ""
    assert strip_prompt_echo(ECHO + " Hola, ¿cómo están?", vocabulary) == "Hola, ¿cómo están?"
    assert strip_prompt_echo("Hola Delfi, ¿cómo estás?", vocabulary) == "Hola Delfi, ¿cómo estás?"
    assert strip_prompt_echo("Hola.", []) == "Hola."


def test_agreement_with_what_the_voices_heard():
    voices = [DiarSegment(0, 27000, "persona_1", " ".join(seg["text"] for seg in VOICES))]
    assert agreement(SAID, voices) > 0.6
    assert agreement("Gracias.", voices) < 0.1
    # Con muy poco para comparar no se juzga.
    assert agreement("Gracias.", [DiarSegment(0, 1000, "persona_1", "hola")]) == 1.0


def test_a_part_without_final_text_keeps_its_live_text_and_nothing_else():
    live = [(0, 5000, "Primera parte."), (600_000, 605_000, "Segunda parte, en vivo.")]
    voices = [DiarSegment(600_500, 604_000, "persona_2", "segunda parte en vivo")]
    pieces = fallback_pieces(live, voices, 600_000, 1_200_000)
    assert pieces == [("persona_2", "Segunda parte, en vivo.", 600_000, 605_000)]
    # Sin transcript en vivo en esa parte, queda lo que escuchó la separación.
    assert fallback_pieces([], voices, 600_000, 1_200_000) == [
        ("persona_2", "Segunda parte en vivo", 600_500, 604_000)
    ]


def test_a_name_nobody_said_is_only_a_suggestion(client, monkeypatch):
    user, meeting_id = _prueba_meeting(client)
    monkeypatch.setattr(httpx, "AsyncClient", _fake_openai(ECHO, SAID))
    asyncio.run(diarize_meeting(meeting_id))
    monkeypatch.undo()

    class FakeLLM:
        async def chat_json(self, system, messages):
            return {"speakers": [
                {"label": "Persona 1", "name": "Bau", "role": None, "confidence": 0.9},
                {"label": "Persona 2", "name": "Delfi", "role": None, "confidence": 0.9},
            ]}

    assert asyncio.run(name_speakers(meeting_id, FakeLLM())) == 0
    speakers = client.get(f"/api/meetings/{meeting_id}", headers=user.headers).json()["speakers"]
    by_label = {s["label"]: s for s in speakers}
    assert by_label["Persona 1"]["display_name"] is None
    assert by_label["Persona 1"]["identity_suggestion"]["person_name"] == "Bau"
    rec.pcm_path(meeting_id).unlink(missing_ok=True)


def test_a_name_someone_said_is_applied(client, monkeypatch):
    user, meeting_id = _prueba_meeting(client)
    said = SAID.replace("Yo tengo", "Soy Delfi, yo tengo")
    monkeypatch.setattr(httpx, "AsyncClient", _fake_openai(ECHO, said))
    asyncio.run(diarize_meeting(meeting_id))
    monkeypatch.undo()

    class FakeLLM:
        async def chat_json(self, system, messages):
            return {"speakers": [{"label": "Persona 1", "name": "Delfi", "role": None, "confidence": 0.9}]}

    assert asyncio.run(name_speakers(meeting_id, FakeLLM())) == 1
    rec.pcm_path(meeting_id).unlink(missing_ok=True)


# ── En vivo ──────────────────────────────────────────────────────


def _tone_pcm(ms: int, amplitude: int) -> bytes:
    return _tone(ms / 1000, amplitude=amplitude)


def test_a_short_answer_in_a_long_window_is_not_silence():
    # "Sí, de acuerdo" (1 s, voz baja) en un tramo de 4 s: el promedio del
    # tramo entero daba ~195 y se tiraba sin transcribir.
    chunk = _tone_pcm(1000, 550) + _silence(3.0)
    assert is_silent(chunk) is False
    assert is_silent(_silence(4.0)) is True
    # Un clic suelto no es habla.
    assert is_silent(_tone_pcm(100, 9000) + _silence(3.9)) is True


def test_a_hallucinated_credit_does_not_take_the_real_speech_with_it():
    text = "Mañana traigo el informe de Pedro. Subtítulos realizados por la comunidad de Amara.org"
    assert strip_hallucinations(text) == "Mañana traigo el informe de Pedro."
    assert strip_hallucinations("¡Gracias por ver el video!") == ""


def test_live_audio_is_retried_and_the_flush_is_confirmed(client, monkeypatch):
    import echo_api.routers.live as live_module
    from echo_api.services.ai_settings import SttConfig

    calls: list[int] = []

    class FlakySTT:
        async def transcribe_chunk(self, pcm16, sample_rate, language, vocabulary, offset_ms=0, context=None):
            calls.append(offset_ms)
            if len(calls) == 1:
                raise httpx.ConnectTimeout("timeout")
            duration = len(pcm16) // 32
            return SttResult(segments=[SttSegment(text="Hola, soy la directora.", start_ms=offset_ms,
                                                  end_ms=offset_ms + duration)])

    async def fake_resolve_stt(db, org_id):
        return SttConfig(provider="openai", model=None, api_key="x")

    monkeypatch.setattr(live_module, "resolve_stt", fake_resolve_stt)
    monkeypatch.setattr(live_module, "get_stt_provider", lambda *args, **kwargs: FlakySTT())

    user = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    meeting = client.post("/api/meetings", json={"title": "x", "level": "primaria"}, headers=user.headers).json()
    meeting_id = uuid.UUID(meeting["id"])
    audio = _tone(5.0) + _silence(1.0)
    with client.websocket_connect(f"/api/meetings/{meeting_id}/ws?token={user.token}") as websocket:
        websocket.send_text(json.dumps({"type": "hello", "role": "recorder", "sample_rate": 16000}))
        assert json.loads(websocket.receive_text())["type"] == "hello_ack"
        for start in range(0, len(audio), 3200):
            websocket.send_bytes(audio[start:start + 3200])
        websocket.send_text(json.dumps({"type": "flush"}))
        seen = []
        while "flushed" not in seen or "segment" not in seen:
            seen.append(json.loads(websocket.receive_text())["type"])
    # El primer intento falló y se reintentó: el tramo no se perdió.
    assert calls[:2] == [0, 0]
    segments = client.get(f"/api/meetings/{meeting_id}/transcript", headers=user.headers).json()["segments"]
    assert [seg["text"] for seg in segments] == ["Hola, soy la directora."]
    # Y el audio de trabajo quedó entero en disco antes del aviso.
    assert rec.pcm_path(meeting_id).stat().st_size == len(audio)
    rec.pcm_path(meeting_id).unlink(missing_ok=True)


def test_live_sends_no_hint_and_drops_a_window_that_repeats_the_last_one(client, monkeypatch):
    # Reunión eb3ce903, 02:10: sobre un tramo casi mudo el modelo devolvió
    # lo último dicho (la pista que se le mandaba) y quedó un turno gigante
    # repetido. Ahora no se manda pista, y si igual vuelve lo anterior, se tira.
    import echo_api.routers.live as live_module
    from echo_api.services.ai_settings import SttConfig

    said = "Uno dos tres probando, esto es una prueba de Echo."
    replies = [said, said, "Ahora sí, arrancamos la reunión."]
    calls: list[dict] = []

    class EchoingSTT:
        async def transcribe_chunk(self, pcm16, sample_rate, language, vocabulary, offset_ms=0, context=None):
            calls.append({"language": language, "context": context})
            duration = len(pcm16) // 32
            text = replies[min(len(calls) - 1, len(replies) - 1)]
            return SttResult(segments=[SttSegment(text=text, start_ms=offset_ms, end_ms=offset_ms + duration)])

    async def fake_resolve_stt(db, org_id):
        return SttConfig(provider="groq", model=None, api_key="x")

    monkeypatch.setattr(live_module, "resolve_stt", fake_resolve_stt)
    monkeypatch.setattr(live_module, "get_stt_provider", lambda *args, **kwargs: EchoingSTT())

    user = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    meeting = client.post(
        "/api/meetings", json={"title": "x", "level": "primaria", "language": "auto"}, headers=user.headers
    ).json()
    meeting_id = uuid.UUID(meeting["id"])
    # Tres tramos: habla, pausa (corte), habla, pausa, habla.
    audio = (_tone(5.0) + _silence(1.0)) * 3
    with client.websocket_connect(f"/api/meetings/{meeting_id}/ws?token={user.token}") as websocket:
        websocket.send_text(json.dumps({"type": "hello", "role": "recorder", "sample_rate": 16000}))
        assert json.loads(websocket.receive_text())["type"] == "hello_ack"
        for start in range(0, len(audio), 3200):
            websocket.send_bytes(audio[start:start + 3200])
        websocket.send_text(json.dumps({"type": "flush"}))
        while json.loads(websocket.receive_text())["type"] != "flushed":
            pass
    assert len(calls) == 3
    assert all(call["context"] is None for call in calls)
    # Idioma fijo aunque la reunión diga "auto": sin eso Whisper inventa idiomas.
    assert all(call["language"] == "es" for call in calls)
    segments = client.get(f"/api/meetings/{meeting_id}/transcript", headers=user.headers).json()["segments"]
    assert [seg["text"] for seg in segments] == [said, "Ahora sí, arrancamos la reunión."]
    rec.pcm_path(meeting_id).unlink(missing_ok=True)


def test_a_short_answer_said_twice_is_kept():
    from echo_api.services.stt.channels import repeats_previous

    assert repeats_previous("Sí, dale.", "Sí, dale.") is False
    assert repeats_previous("Uno dos tres probando.", "uno, dos, tres, probando") is True
    assert repeats_previous("Uno dos tres probando.", "Uno dos tres.") is False


def test_groq_transcribes_before_openai_when_both_keys_are_there(monkeypatch):
    from echo_api.config import get_settings
    from echo_api.services import ai_settings

    async def no_org_settings(db, org_id):
        return None

    monkeypatch.setattr(ai_settings, "get_org_ai_settings", no_org_settings)
    monkeypatch.setattr(get_settings(), "openai_api_key", "sk-openai")
    monkeypatch.setattr(get_settings(), "groq_api_key", "gsk-groq")
    config = asyncio.run(ai_settings.resolve_stt(None, uuid.uuid4()))
    assert (config.provider, config.api_key) == ("groq", "gsk-groq")
