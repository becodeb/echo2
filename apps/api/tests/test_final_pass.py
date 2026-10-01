"""Pasada final nueva: una sola fuente, turnos desde las palabras, respaldo y reintento.

Los fixtures son respuestas reales (recortadas) de ElevenLabs Scribe v2 y de
Groq whisper-large-v3-turbo sobre las dos reuniones de prueba del banco
(bench/casos/2026-09-30): la del 30/9 (2:15, 5 personas, un celular que se
movía) y la del 27/9 (20 s: Bautista Goñi, Vanina y "el Choto"). Grabadas el
30/9 con las keys de prueba, pidiendo lo mismo que pide producción.
"""
import asyncio
import json
import uuid
from pathlib import Path

import httpx
from conftest import EchoTestUser
from test_levels import _sql
from test_voice import _sql_rows
from test_speakers import _tone

from echo_api.config import get_settings
from echo_api.services import diarization
from echo_api.services import recording as rec
from echo_api.services.stt.base import SttWord

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class _FakeApis:
    """Reemplaza httpx.AsyncClient: ElevenLabs y Groq responden lo grabado."""

    requests: list[tuple[str, dict]] = []
    scribe: dict | None = None
    groq: dict = {}
    scribe_status = 200
    groq_status = 200

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, data=None, files=None):
        _FakeApis.requests.append((url, dict(data or {})))
        request = httpx.Request("POST", url)
        if "elevenlabs" in url:
            if _FakeApis.scribe_status >= 400:
                return httpx.Response(_FakeApis.scribe_status, json={"detail": "quota_exceeded"}, request=request)
            return httpx.Response(200, json=_FakeApis.scribe, request=request)
        if _FakeApis.groq_status >= 400:
            return httpx.Response(_FakeApis.groq_status, json={"error": "down"}, request=request)
        return httpx.Response(200, json=_FakeApis.groq, request=request)


def _setup(monkeypatch, case: str, scribe_status: int = 200):
    monkeypatch.setattr(get_settings(), "elevenlabs_api_key", "xi-test")
    monkeypatch.setattr(get_settings(), "groq_api_key", "gsk-test")
    monkeypatch.setattr(get_settings(), "openai_api_key", "")
    _FakeApis.requests = []
    _FakeApis.scribe = _fixture(f"scribe_{case}.json")
    _FakeApis.groq = _fixture(f"groq_{case}.json")
    _FakeApis.scribe_status = scribe_status
    _FakeApis.groq_status = 200
    monkeypatch.setattr(httpx, "AsyncClient", _FakeApis)


def _meeting(client, seconds: float, live: list[tuple[int, int, str, str | None]] | None = None, **meta):
    user = EchoTestUser(client, name="Bautista Goñi", org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    meeting = client.post("/api/meetings", json={"title": "Prueba", "level": "primaria"}, headers=user.headers).json()
    meeting_id = uuid.UUID(meeting["id"])
    if meta:
        _sql("UPDATE meetings SET meta = CAST(:meta AS jsonb) WHERE id = :id", meta=json.dumps(meta), id=str(meeting_id))
    for seq, (start, end, text, hint) in enumerate(live or [], start=1):
        _sql(
            "INSERT INTO transcript_segments (id, meeting_id, organization_id, seq, start_ms, end_ms, text, is_final,"
            " edited, speaker_hint, created_at, updated_at) VALUES (:id, :m, :o, :seq, :s, :e, :t, true, false, :h,"
            " now(), now())",
            id=str(uuid.uuid4()), m=str(meeting_id), o=user.org_id, seq=seq, s=start, e=end, t=text, h=hint,
        )
    rec.pcm_path(meeting_id).write_bytes(_tone(seconds))
    return user, meeting_id


def _transcript(client, user, meeting_id):
    meeting = client.get(f"/api/meetings/{meeting_id}", headers=user.headers).json()
    names = {s["id"]: s["display_name"] or s["label"] for s in meeting["speakers"]}
    segments = client.get(f"/api/meetings/{meeting_id}/transcript", headers=user.headers).json()["segments"]
    return [(names.get(seg["speaker_id"]), seg["text"]) for seg in segments], meeting


def _usage(meeting_id):
    rows = []

    async def run():
        from sqlalchemy import select

        from echo_api.db import SessionLocal
        from echo_api.models import UsageEvent

        async with SessionLocal() as db:
            rows.extend((await db.execute(select(UsageEvent).where(UsageEvent.meeting_id == meeting_id))).scalars())

    asyncio.run(run())
    return rows


def _cleanup(meeting_id):
    rec.pcm_path(meeting_id).unlink(missing_ok=True)
    diarization.people_path(meeting_id).unlink(missing_ok=True)
    diarization.text_retry_path(meeting_id).unlink(missing_ok=True)


def test_meeting_of_the_27th_comes_out_with_its_three_people(client, monkeypatch):
    _setup(monkeypatch, "2026-09-27")
    live = [(0, 7000, "Hola, sí, quién es yo soy Bautista Goñi.", None), (7000, 20400, "Hola, soy Vanina.", None)]
    user, meeting_id = _meeting(client, 20.4, live, people=True)
    assert asyncio.run(diarization.diarize_meeting(meeting_id)) is True
    monkeypatch.undo()

    [(url, form)] = _FakeApis.requests
    assert "elevenlabs" in url and form["diarize"] == "true" and form["language_code"] == "spa"
    # El nombre de quien grabó va como término del diccionario.
    assert "Bautista Goñi" in form["keyterms"]
    rows, meeting = _transcript(client, user, meeting_id)
    assert [name for name, _ in rows] == [
        "Persona 1", "Persona 2", "Persona 1", "Persona 3", "Persona 1", "Persona 3", "Persona 1", "Persona 2",
    ]
    assert rows[1] == ("Persona 2", "Hola, hola, hola, soy Vanina.")
    assert rows[5] == ("Persona 3", "El Choto.")
    assert rows[-1] == ("Persona 2", "Vanina, ya dije.")
    # El texto en vivo se reemplazó entero: nada duplicado.
    texts = [text for _, text in rows]
    assert len(texts) == len(set(texts))
    assert meeting["meta"]["people_status"] == "done"
    assert {"text": "Vanina", "type": "name"} in meeting["meta"]["detected_entities"]
    [usage] = _usage(meeting_id)
    assert (usage.kind, usage.provider, usage.credits, usage.meta) == (
        "stt_final", "elevenlabs", 1, {"covered_by": "credits"}
    )
    _cleanup(meeting_id)


def test_meeting_of_the_30th_has_no_orphan_turns_or_hint_echo(client, monkeypatch):
    _setup(monkeypatch, "2026-09-30")
    # Lo que quedó en producción: el turno gigante de las 02:10 era la pista.
    hint = "Uno, dos, tres, probando. Hola, sí, uno, dos, tres, probando. Estamos probando. Buenas, ¿cómo va?"
    live = [(0, 5000, "Uno, dos, tres, probando.", None), (130400, 135300, hint, None)]
    user, meeting_id = _meeting(client, 135.3, live)
    _sql("UPDATE organizations SET plan = 'institucion' WHERE id = :id", id=user.org_id)
    assert asyncio.run(diarization.diarize_meeting(meeting_id)) is True
    monkeypatch.undo()

    rows, _ = _transcript(client, user, meeting_id)
    assert rows and all(name and name.startswith("Persona") for name, _ in rows)
    assert hint not in [text for _, text in rows]
    assert len({name for name, _ in rows}) >= 3
    # Una institución no gasta créditos.
    assert [u.credits for u in _usage(meeting_id)] == [0]
    _cleanup(meeting_id)


def test_with_minors_it_never_goes_to_elevenlabs(client, monkeypatch):
    _setup(monkeypatch, "2026-09-27")
    user, meeting_id = _meeting(client, 20.4, [(0, 20400, "hola", None)], people=True, minors=True)
    _sql("UPDATE organizations SET plan = 'institucion' WHERE id = :id", id=user.org_id)
    assert asyncio.run(diarization.diarize_meeting(meeting_id)) is False
    monkeypatch.undo()

    assert [url for url, _ in _FakeApis.requests] == ["https://api.groq.com/openai/v1/audio/transcriptions"]
    rows, _ = _transcript(client, user, meeting_id)
    # Texto de Groq sobre el audio entero, sin personas.
    assert rows[0][1].startswith("Hola, sí")
    assert len(rows) == 10
    assert [(u.provider, u.credits) for u in _usage(meeting_id)] == [("groq", 0)]
    _cleanup(meeting_id)


def test_if_groq_fails_the_audio_never_goes_to_openai_and_is_retried(client, monkeypatch):
    _setup(monkeypatch, "2026-09-27")
    # Aunque haya key de OpenAI en el servidor: OpenAI no recibe audio.
    monkeypatch.setattr(get_settings(), "openai_api_key", "sk-openai")
    _FakeApis.groq_status = 503
    user, meeting_id = _meeting(client, 20.4, [(0, 20400, "hola en vivo", None)], minors=True)
    assert asyncio.run(diarization.diarize_meeting(meeting_id)) is False
    assert all("openai.com" not in url for url, _ in _FakeApis.requests)
    rows, meeting = _transcript(client, user, meeting_id)
    # Queda el en vivo, la copia para reintentar y el aviso a quien grabó.
    assert [text for _, text in rows] == ["hola en vivo"]
    assert meeting["meta"]["text_status"] == "pending"
    assert diarization.text_retry_path(meeting_id).exists()
    [(title,)] = _sql_rows("SELECT title FROM notifications WHERE user_id = :u AND kind = 'transcript_status'",
                           u=user.user_id)
    assert "se demora" in title

    _sql("UPDATE meetings SET status = 'completed' WHERE id = :id", id=str(meeting_id))
    _FakeApis.groq_status = 200
    assert asyncio.run(diarization.retry_pending_text()) == 1
    monkeypatch.undo()
    rows, meeting = _transcript(client, user, meeting_id)
    assert rows[0][1].startswith("Hola, sí") and len(rows) == 10
    assert meeting["meta"]["text_status"] == "done" and "text_retry" not in meeting["meta"]
    assert not diarization.text_retry_path(meeting_id).exists()
    assert [u.provider for u in _usage(meeting_id)] == ["groq"]
    assert all("openai.com" not in url for url, _ in _FakeApis.requests)
    _cleanup(meeting_id)


def test_a_call_with_channels_keeps_its_live_people(client, monkeypatch):
    _setup(monkeypatch, "2026-09-27")
    live = [(0, 5000, "Hola, ¿me escuchan?", "speaker_1"), (5000, 9000, "Sí, perfecto.", "speaker_2")]
    user, meeting_id = _meeting(client, 20.4, live)
    assert asyncio.run(diarization.diarize_meeting(meeting_id)) is False
    monkeypatch.undo()
    assert _FakeApis.requests == []
    rows, _ = _transcript(client, user, meeting_id)
    assert [text for _, text in rows] == ["Hola, ¿me escuchan?", "Sí, perfecto."]
    _cleanup(meeting_id)


def test_if_elevenlabs_fails_people_stay_pending_and_are_retried(client, monkeypatch):
    _setup(monkeypatch, "2026-09-27", scribe_status=429)
    user, meeting_id = _meeting(client, 20.4, [(0, 20400, "Hola, soy Vanina.", None)], people=True)
    assert asyncio.run(diarization.diarize_meeting(meeting_id)) is False
    rows, meeting = _transcript(client, user, meeting_id)
    # Mientras tanto: el texto de Groq, sin etiquetar a nadie, y el crédito
    # reservado (así otra reunión no lo gasta mientras tanto).
    assert all(name is None for name, _ in rows) and len(rows) == 10
    assert meeting["meta"]["people_status"] == "pending"
    held = [u for u in _usage(meeting_id) if u.provider == "elevenlabs"]
    assert [(u.credits, u.quantity, (u.meta or {}).get("hold")) for u in held] == [(1, 0, True)]
    assert diarization.people_path(meeting_id).exists()

    _sql("UPDATE meetings SET status = 'completed' WHERE id = :id", id=str(meeting_id))
    _FakeApis.scribe_status = 200
    assert asyncio.run(diarization.retry_pending_people()) == 1
    monkeypatch.undo()
    rows, meeting = _transcript(client, user, meeting_id)
    assert len({name for name, _ in rows}) == 3 and all(rows[i][0] for i in range(len(rows)))
    assert meeting["meta"]["people_status"] == "done" and "people_retry" not in meeting["meta"]
    assert sorted(u.credits for u in _usage(meeting_id)) == [0, 1]
    [charged] = [u for u in _usage(meeting_id) if u.provider == "elevenlabs"]
    assert charged.quantity > 20 and charged.meta == {"covered_by": "credits"}
    assert not diarization.people_path(meeting_id).exists()
    _cleanup(meeting_id)


def test_a_transcript_corrected_by_hand_is_not_overwritten_by_the_retry(client, monkeypatch):
    _setup(monkeypatch, "2026-09-27", scribe_status=500)
    user, meeting_id = _meeting(client, 20.4, [(0, 20400, "Hola.", None)], people=True)
    asyncio.run(diarization.diarize_meeting(meeting_id))
    _sql("UPDATE meetings SET status = 'completed' WHERE id = :id", id=str(meeting_id))
    _sql("UPDATE transcript_segments SET edited = true, text = 'Hola, soy Vanina (corregido).' WHERE meeting_id = :id"
         " AND seq = 1", id=str(meeting_id))
    _FakeApis.scribe_status = 200
    assert asyncio.run(diarization.retry_pending_people()) == 0
    monkeypatch.undo()
    rows, meeting = _transcript(client, user, meeting_id)
    assert rows[0][1] == "Hola, soy Vanina (corregido)."
    assert meeting["meta"]["people_status"] == "skipped"
    # No se cobró: la reserva del crédito volvió.
    assert [u.provider for u in _usage(meeting_id)] == ["groq"]
    _cleanup(meeting_id)


def test_a_correction_made_while_scribe_works_is_not_lost(client, monkeypatch):
    _setup(monkeypatch, "2026-09-27", scribe_status=500)
    user, meeting_id = _meeting(client, 20.4, [(0, 20400, "Hola.", None)], people=True)
    asyncio.run(diarization.diarize_meeting(meeting_id))
    _sql("UPDATE meetings SET status = 'completed' WHERE id = :id", id=str(meeting_id))
    _FakeApis.scribe_status = 200
    real_scribe = diarization._scribe

    async def slow_scribe(*args):
        # Alguien corrige el texto mientras ElevenLabs procesa.
        result = await real_scribe(*args)
        await asyncio.to_thread(
            _sql, "UPDATE transcript_segments SET edited = true, text = 'Corregido.' WHERE meeting_id = :id AND seq = 1",
            id=str(meeting_id),
        )
        return result

    monkeypatch.setattr(diarization, "_scribe", slow_scribe)
    assert asyncio.run(diarization.retry_pending_people()) == 0
    monkeypatch.undo()
    rows, meeting = _transcript(client, user, meeting_id)
    assert rows[0][1] == "Corregido."
    assert meeting["meta"]["people_status"] == "skipped"
    assert [u.provider for u in _usage(meeting_id)] == ["groq"]
    _cleanup(meeting_id)


def test_if_scribe_hears_nothing_the_live_text_stays_and_nothing_is_charged(client, monkeypatch):
    _setup(monkeypatch, "2026-09-27")
    _FakeApis.scribe = {**_FakeApis.scribe, "words": [], "text": ""}
    _FakeApis.groq = {"text": "", "segments": []}
    user, meeting_id = _meeting(client, 20.4, [(0, 20400, "Hola, soy Vanina.", None)], people=True)
    assert asyncio.run(diarization.diarize_meeting(meeting_id)) is False
    monkeypatch.undo()
    rows, meeting = _transcript(client, user, meeting_id)
    assert rows == [(None, "Hola, soy Vanina.")]
    assert meeting["meta"]["people_status"] == "failed"
    assert all(u.credits == 0 for u in _usage(meeting_id))
    _cleanup(meeting_id)


def test_the_last_credit_is_spent_once_when_two_meetings_end_together(client, monkeypatch):
    _setup(monkeypatch, "2026-09-27")
    user, first = _meeting(client, 20.4, [(0, 20400, "Hola.", None)], people=True)
    second = uuid.UUID(client.post("/api/meetings", json={"title": "Otra", "level": "primaria"},
                                   headers=user.headers).json()["id"])
    _sql("UPDATE meetings SET meta = CAST('{\"people\": true}' AS jsonb) WHERE id = :id", id=str(second))
    rec.pcm_path(second).write_bytes(_tone(20.4))
    # Le queda un solo crédito de los 4.
    _sql("INSERT INTO usage_events (id, kind, provider, unit, quantity, cost_usd, credits, user_id, organization_id,"
         " created_at) VALUES (:id, 'stt_final', 'elevenlabs', 'audio_seconds', 0, 0, 3, :u, :o, now())",
         id=str(uuid.uuid4()), u=user.user_id, o=user.org_id)

    async def both():
        return await asyncio.gather(diarization.diarize_meeting(first), diarization.diarize_meeting(second))

    results = asyncio.run(both())
    monkeypatch.undo()
    assert sorted(results) == [False, True]
    spent = [u.credits for m in (first, second) for u in _usage(m)]
    assert sum(spent) == 1
    _cleanup(first)
    _cleanup(second)


def test_lines_after_the_audio_keep_no_live_label():
    live = [(0, 1000, "dentro", "speaker_1"), (30000, 31000, "después", "speaker_1")]
    assert diarization._after_audio(live, 20000) == [(None, "después", 30000, 31000)]


def test_the_voice_sample_in_front_names_that_person():
    voice = diarization.KnownVoice("voz_1", uuid.uuid4(), "Mariana Gibson", b"")
    other = diarization.KnownVoice("voz_2", uuid.uuid4(), "Laura Pérez", b"")
    windows = [(voice, 1500, 6500), (other, 8000, 13000)]
    words = [
        SttWord("Hola", 2000, 2500, "speaker_1"), SttWord("soy", 2600, 2900, "speaker_1"),
        SttWord("Mariana", 3000, 3500, "speaker_1"),
        # La segunda muestra cayó en la misma persona: no se nombra a nadie por ella.
        SttWord("Soy", 8500, 9000, "speaker_1"), SttWord("Laura", 9000, 9500, "speaker_1"),
        SttWord("Buenos", 15000, 15400, "speaker_2"), SttWord("días.", 15400, 15800, "speaker_2"),
        SttWord("Hola.", 16000, 16400, "speaker_1"),
    ]
    meeting_words, known = diarization.assign_known_voices(words, windows, 14500)
    assert known == {}
    assert [(w.text, w.start_ms) for w in meeting_words] == [("Buenos", 500), ("días.", 900), ("Hola.", 1500)]

    words[3] = SttWord("Soy", 8500, 9000, "speaker_3")
    words[4] = SttWord("Laura", 9000, 9500, "speaker_3")
    _, known = diarization.assign_known_voices(words, windows, 14500)
    assert {label: v.name for label, v in known.items()} == {"speaker_1": "Mariana Gibson", "speaker_3": "Laura Pérez"}


def test_known_voices_are_off_in_the_final_pass():
    # En la reunión del 27/9 empeoraba la separación: apagado hasta probarlo más.
    assert diarization.KNOWN_VOICES_IN_FINAL_PASS is False


def test_known_voice_goes_in_front_of_the_meeting_audio(client, monkeypatch):
    import io
    import wave

    _setup(monkeypatch, "2026-09-27")
    monkeypatch.setattr(diarization, "KNOWN_VOICES_IN_FINAL_PASS", True)
    user, meeting_id = _meeting(client, 20.4, [(0, 20400, "hola", None)], people=True)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(_tone(5.0))
    saved = client.post(
        "/api/me/voice", files={"audio": ("voz.wav", buffer.getvalue(), "audio/wav")}, data={"consent": "true"},
        headers={"Authorization": f"Bearer {user.token}"},
    )
    assert saved.status_code == 200, saved.text
    # Scribe oye primero la muestra (1,5 s de silencio, la voz, 1,5 s) y después la reunión:
    # la persona de la muestra es la speaker_0 del fixture (Bautista).
    fixture = _fixture("scribe_2026-09-27.json")
    shift = (1.5 + 5.0 + 1.5)
    for word in fixture["words"]:
        word["start"] += shift
        word["end"] += shift
    fixture["words"][:0] = [
        {"text": "Hola,", "start": 2.0, "end": 2.4, "type": "word", "speaker_id": fixture["words"][0]["speaker_id"]},
        {"text": "soy", "start": 2.5, "end": 2.8, "type": "word", "speaker_id": fixture["words"][0]["speaker_id"]},
    ]
    _FakeApis.scribe = fixture
    assert asyncio.run(diarization.diarize_meeting(meeting_id)) is True
    monkeypatch.undo()
    rows, _ = _transcript(client, user, meeting_id)
    assert rows[0] == ("Bautista Goñi", "Hola, sí, ¿quién es? Yo soy-- hola, yo soy Bautista Goñi.")
    assert {name for name, _ in rows} == {"Bautista Goñi", "Persona 1", "Persona 2"}
    _cleanup(meeting_id)


def test_an_imported_audio_goes_through_the_final_pass(client, monkeypatch, tmp_path):
    import io
    import wave

    from echo_api.routers import imports
    from echo_api.services import pipeline

    async def nothing(db, org_id):
        return None

    _setup(monkeypatch, "2026-09-27")
    # Sin IA: acá importa la transcripción, no el acta.
    monkeypatch.setattr(pipeline, "resolve_llm", nothing)
    monkeypatch.setattr(pipeline, "resolve_embeddings", nothing)
    user = EchoTestUser(client, name="Bautista Goñi", org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    meeting_id = uuid.UUID(client.post("/api/meetings", json={"title": "Importada", "level": "primaria", "people": True},
                                       headers=user.headers).json()["id"])
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(_tone(20.4))
    source = tmp_path / "subido.wav"
    source.write_bytes(buffer.getvalue())
    _sql("UPDATE meetings SET status = 'processing', audio_source = 'import' WHERE id = :id", id=str(meeting_id))

    asyncio.run(imports._process_import(str(meeting_id), str(source)))
    monkeypatch.undo()

    rows, meeting = _transcript(client, user, meeting_id)
    # Como una reunión en vivo: ElevenLabs con sus tres personas y un crédito.
    assert meeting["status"] == "completed"
    assert len({name for name, _ in rows}) == 3 and all(name for name, _ in rows)
    assert [(u.provider, u.credits) for u in _usage(meeting_id)] == [("elevenlabs", 1)]
    # Ni el archivo subido ni el audio de trabajo quedan en el disco.
    assert not source.exists() and not rec.pcm_path(meeting_id).exists()
