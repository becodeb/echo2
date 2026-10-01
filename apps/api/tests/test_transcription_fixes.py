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
from test_speakers import _silence, _tone

from echo_api.services import recording as rec
from echo_api.services.diarization import _replace_transcript, name_speakers
from echo_api.services.stt.base import SttResult, SttSegment
from echo_api.services.stt.channels import is_silent, strip_hallucinations

# Lo que se dijo (referencia, Whisper sobre el audio de la reunión).
SAID = (
    "Yo tengo que tener la compu ahí, prendida. ¿La compu o el celular? Mira, ahora mismo si yo apago "
    "el celular, esto debería estar funcionando. Sí, está funcionando. Una vez termina, te hace toda la "
    "transcripción entera. Esto te va mostrando un poquito, no te muestra todo, porque nada, no detecta "
    "en vivo en vivo, pero después con la grabación hace una segunda pasada, digamos, y transcribió todo "
    "perfecto. Pero nada, al terminar."
)


def _prueba_meeting(client):
    """La reunión 89ddbc9d con el texto bien transcripto y dos personas."""
    user = EchoTestUser(client, name="Bautista Goñi", org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    meeting = client.post(
        "/api/meetings",
        json={"title": "Prueba", "level": "primaria", "participants": [{"name": "Bau"}, {"name": "Delfi"}]},
        headers=user.headers,
    ).json()
    meeting_id = uuid.UUID(meeting["id"])
    first, rest = SAID.split(". ", 1)
    rows = [("speaker_1", first + ".", 0, 2400), ("speaker_2", rest, 2900, 27200)]
    asyncio.run(_replace_transcript(meeting_id, rows, {}))
    return user, meeting_id


def test_a_name_nobody_said_is_only_a_suggestion(client):
    user, meeting_id = _prueba_meeting(client)

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


def test_a_name_someone_said_is_applied(client):
    user, meeting_id = _prueba_meeting(client)
    _sql("UPDATE transcript_segments SET text = 'Soy Delfi. ' || text WHERE meeting_id = :id AND seq = 1",
         id=str(meeting_id))

    class FakeLLM:
        async def chat_json(self, system, messages):
            return {"speakers": [{"label": "Persona 1", "name": "Delfi", "role": None, "confidence": 0.9}]}

    assert asyncio.run(name_speakers(meeting_id, FakeLLM())) == 1


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


def test_audio_only_goes_to_groq_whatever_the_campus_saved(monkeypatch):
    """OpenAI no recibe audio: ni por defecto, ni como respaldo, ni porque una
    sede lo haya elegido con su key (los colegios ya no eligen motor)."""
    from types import SimpleNamespace

    from echo_api.config import get_settings
    from echo_api.services import ai_settings, diarization

    picked = SimpleNamespace(stt_provider="openai", stt_model=None, stt_api_key_enc="cifrada")

    async def org_settings(db, org_id):
        return picked

    monkeypatch.setattr(ai_settings, "get_org_ai_settings", org_settings)
    monkeypatch.setattr(ai_settings, "decrypt_secret", lambda value: "sk-propia")
    monkeypatch.setattr(get_settings(), "openai_api_key", "sk-openai")
    monkeypatch.setattr(get_settings(), "groq_api_key", "gsk-groq")
    config = asyncio.run(ai_settings.resolve_stt(None, uuid.uuid4()))
    assert (config.provider, config.api_key) == ("groq", "gsk-groq")
    assert diarization._text_engine(config).name == "groq"
    # Sin Groq no hay transcripción en la nube, en vez de caer en OpenAI.
    monkeypatch.setattr(get_settings(), "groq_api_key", "")
    assert asyncio.run(ai_settings.resolve_stt(None, uuid.uuid4())) is None
    assert diarization._text_engine(None) is None


def test_a_campus_can_only_choose_the_language_of_the_minutes(client):
    admin = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    assert client.get("/api/org/ai-settings", headers=admin.headers).json() == {"minutes_language": "es"}
    saved = client.put("/api/org/ai-settings", json={"minutes_language": "en", "stt_provider": "openai",
                                                     "stt_api_key": "sk-x"}, headers=admin.headers)
    assert saved.status_code == 200 and saved.json() == {"minutes_language": "en"}
    assert client.put("/api/org/ai-settings", json={"minutes_language": "xx"}, headers=admin.headers).status_code == 422


def test_a_superadmin_visiting_a_campus_can_record(client):
    # Bauti entró a Northfield como superadmin (sin ser miembro): el REST lo
    # dejaba, el WebSocket lo rechazaba y la web decía "No se pudo conectar".
    owner = EchoTestUser(client, org_name=f"Northfield {uuid.uuid4().hex[:4]}")
    admin = EchoTestUser(client, org_name="Becode")
    _sql("UPDATE users SET is_superadmin = true WHERE id = :id", id=admin.user_id)
    meeting = client.post("/api/meetings", json={"title": "x", "level": "primaria"}, headers=owner.headers).json()
    with client.websocket_connect(f"/api/meetings/{meeting['id']}/ws?token={admin.token}") as websocket:
        websocket.send_text(json.dumps({"type": "hello", "role": "viewer"}))
        assert json.loads(websocket.receive_text())["type"] == "hello_ack"


def test_if_the_engine_is_down_the_window_goes_to_the_next(monkeypatch):
    from echo_api.services.stt.base import FallbackSttProvider

    class Down:
        name, model = "groq", "whisper-large-v3-turbo"

        async def transcribe_chunk(self, *args, **kwargs):
            raise httpx.ConnectError("groq caído")

    class Up:
        name, model = "openai", "gpt-4o-transcribe"

        async def transcribe_chunk(self, pcm16, sample_rate, language, vocabulary=None, offset_ms=0, context=None):
            return SttResult(segments=[SttSegment("Hola.", offset_ms, offset_ms + 1000)])

    chain = FallbackSttProvider([Down(), Up()])
    result = asyncio.run(chain.transcribe_chunk(bytes(3200), 16000, "es", [], offset_ms=500))
    assert [s.text for s in result.segments] == ["Hola."]
    # El consumo se anota al que respondió.
    assert (chain.name, chain.model) == ("openai", "gpt-4o-transcribe")


def test_an_echo_device_records_like_the_web(client, monkeypatch):
    import time

    import echo_api.routers.device_stream as device_module
    from echo_api.security import hash_refresh_token
    from echo_api.services import recording as rec
    from echo_api.services.ai_settings import SttConfig
    from test_speakers import _tone

    async def fake_resolve_stt(db, org_id):
        return SttConfig(provider="fake", model=None, api_key="x")

    monkeypatch.setattr(device_module, "resolve_stt", fake_resolve_stt)
    owner = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    token = uuid.uuid4().hex
    _sql("INSERT INTO devices (id, organization_id, name, kind, token_hash, created_at, updated_at)"
         " VALUES (:id, :o, 'Sala 1', 'esp32', :h, now(), now())",
         id=str(uuid.uuid4()), o=owner.org_id, h=hash_refresh_token(token))
    meeting = client.post("/api/devices/meetings", json={}, headers={"Authorization": f"Bearer {token}"}).json()
    with client.websocket_connect(f"/api/devices/stream?token={token}&meeting_id={meeting['id']}") as websocket:
        websocket.send_bytes(_tone(3.0))
        websocket.send_text(json.dumps({"type": "flush"}))
        time.sleep(1)
    meeting_id = uuid.UUID(meeting["id"])
    # El audio quedó como audio de trabajo (para la pasada final) y el consumo anotado.
    assert rec.pcm_path(meeting_id).stat().st_size == len(_tone(3.0))
    rows = []

    async def usage():
        from sqlalchemy import select

        from echo_api.db import SessionLocal
        from echo_api.models import UsageEvent

        async with SessionLocal() as db:
            rows.extend((await db.execute(select(UsageEvent).where(UsageEvent.meeting_id == meeting_id))).scalars())

    asyncio.run(usage())
    assert [u.kind for u in rows] == ["stt_live"]
    rec.pcm_path(meeting_id).unlink(missing_ok=True)


def test_a_device_with_minors_marks_the_meeting_it_joins(client, monkeypatch):
    import echo_api.routers.device_stream as device_module
    from echo_api.security import hash_refresh_token
    from echo_api.services.ai_settings import SttConfig

    async def fake_resolve_stt(db, org_id):
        return SttConfig(provider="fake", model=None, api_key="x")

    monkeypatch.setattr(device_module, "resolve_stt", fake_resolve_stt)
    owner = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    plain, classroom = uuid.uuid4().hex, uuid.uuid4().hex
    for token, minors in ((plain, False), (classroom, True)):
        _sql("INSERT INTO devices (id, organization_id, name, kind, token_hash, minors, created_at, updated_at)"
             " VALUES (:id, :o, 'Sala', 'esp32', :h, :m, now(), now())",
             id=str(uuid.uuid4()), o=owner.org_id, h=hash_refresh_token(token), m=minors)
    # La reunión la empezó un dispositivo sin menores...
    meeting = client.post("/api/devices/meetings", json={}, headers={"Authorization": f"Bearer {plain}"}).json()
    assert client.get(f"/api/meetings/{meeting['id']}", headers=owner.headers).json()["meta"].get("minors") is False
    # ...y al sumarse el del aula con menores queda marcada.
    with client.websocket_connect(f"/api/devices/stream?token={classroom}&meeting_id={meeting['id']}"):
        pass
    assert client.get(f"/api/meetings/{meeting['id']}", headers=owner.headers).json()["meta"]["minors"] is True
