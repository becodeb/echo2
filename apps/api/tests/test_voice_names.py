"""Nombres por "Mi voz" y por "hola, soy..." (docs/plan-correcciones.md §7).

Las huellas son vectores fijos: acá se prueba la decisión (quién se nombra,
quién queda como sugerencia), no el modelo. El modelo se mide en
bench/voiceprint_bench.py.
"""
import asyncio
import itertools
import uuid

import numpy as np
from conftest import EchoTestUser
from test_final_pass import _cleanup, _meeting, _setup, _transcript
from test_levels import _sql
from test_voice import _sql_rows

from echo_api.services import diarization, speaker_names, voiceprint
from echo_api.services.speaker_names import Candidate, decide, said_names


def _unit(*values: float) -> np.ndarray:
    vector = np.zeros(voiceprint.DIM, dtype=np.float32)
    vector[: len(values)] = values
    return vector / np.linalg.norm(vector)


BAUTI, LAURA, OTHER = _unit(1, 0, 0), _unit(0, 1, 0), _unit(0, 0, 1)


def _near(vector: np.ndarray, noise: float) -> np.ndarray:
    mixed = vector + noise * OTHER
    return mixed / np.linalg.norm(mixed)


def test_hungarian_finds_the_best_one_to_one():
    rng = np.random.default_rng(7)
    for _ in range(30):
        scores = rng.random((3, 5))
        best = max(itertools.permutations(range(5), 3), key=lambda cols: sum(scores[i, c] for i, c in enumerate(cols)))
        got = voiceprint._hungarian((-scores).tolist())
        assert sum(scores[i, c] for i, c in enumerate(got)) == sum(scores[i, c] for i, c in enumerate(best))


def test_each_voice_gets_its_name_and_nobody_twice():
    bauti = Candidate("Bautista Goñi", uuid.uuid4(), BAUTI)
    laura = Candidate("Laura Belzunce", uuid.uuid4(), LAURA)
    prints = {"speaker_1": _near(BAUTI, 0.2), "speaker_2": _near(LAURA, 0.2)}
    names = decide([], [bauti, laura], prints)
    assert {k: (n.name, n.accepted, n.source) for k, n in names.items()} == {
        "speaker_1": ("Bautista Goñi", True, "voz"), "speaker_2": ("Laura Belzunce", True, "voz"),
    }
    # Dos personas que se parecen a la misma muestra: ninguna se nombra seguro.
    twins = {"speaker_1": _near(BAUTI, 0.3), "speaker_2": _near(BAUTI, 0.35)}
    names = decide([], [bauti], twins)
    assert not any(n.accepted for n in names.values())


def test_a_doubtful_voice_is_only_a_suggestion():
    bauti = Candidate("Bautista Goñi", uuid.uuid4(), BAUTI)
    # Coseno ~0,7: como dos personas distintas en la misma sala (banco del 1/10).
    names = decide([], [bauti], {"speaker_1": _near(BAUTI, 1.0)})
    assert names["speaker_1"].accepted is False
    assert names["speaker_1"].suggestion()["person_name"] == "Bautista Goñi"
    # Muy lejos: ni sugerencia.
    assert decide([], [bauti], {"speaker_1": OTHER}) == {}


def test_what_someone_says_names_them():
    members = [Candidate("Bautista Goñi", uuid.uuid4()), Candidate("Vanina Ríos", uuid.uuid4()),
               Candidate("Martina Pérez"), Candidate("Martina Gómez")]
    rows = [
        ("speaker_0", "Hola, sí, ¿quién es? Yo soy... hola, yo soy Bautista Goñi.", 1000, 5000),
        ("speaker_1", "Hola, hola, soy Vanina.", 5000, 7000),
        ("speaker_2", "Soy Martina.", 8000, 9000),  # hay dos Martinas: no se sabe cuál
        ("speaker_3", "Me llamo Vanina", 4 * 60 * 1000, 4 * 60 * 1000 + 900),  # después de 3 min
    ]
    found = said_names(rows, members)
    assert {k: c.name for k, c in found.items()} == {"speaker_0": "Bautista Goñi", "speaker_1": "Vanina Ríos"}
    # Quien dijo "soy Vanina" tiene la voz de Bautista: gana lo dicho, y la
    # voz queda a la vista para revisar.
    members[0].voice = BAUTI
    names = decide(rows, members, {"speaker_1": _near(BAUTI, 0.1)})
    assert (names["speaker_1"].name, names["speaker_1"].source) == ("Vanina Ríos", "dijo")
    assert names["speaker_1"].extra["voice_says"] == "Bautista Goñi"
    assert names["speaker_0"].name == "Bautista Goñi" and names["speaker_0"].accepted


def test_the_final_pass_names_people_by_their_voice(client, monkeypatch):
    _setup(monkeypatch, "2026-09-27")
    user, meeting_id = _meeting(client, 20.4, [(0, 20400, "hola", None)], people=True)
    laura = EchoTestUser(client, name="Laura Belzunce", org_name="x")
    _sql("INSERT INTO organization_members (id, organization_id, user_id, role, created_at, updated_at)"
         " VALUES (gen_random_uuid(), :o, :u, 'member', now(), now())",
         o=_sql_rows("SELECT organization_id::text FROM meetings WHERE id = :m", m=str(meeting_id))[0][0], u=laura.user_id)
    for who, vector in ((user.user_id, BAUTI), (laura.user_id, LAURA)):
        _sql("INSERT INTO user_voice_samples (id, user_id, audio_wav, duration_ms, consent_at, sample_embedding,"
             " embedding, embedding_model, created_at, updated_at) VALUES (gen_random_uuid(), :u, '\\x00', 9000,"
             " now(), CAST(:v AS vector), CAST(:v AS vector), :m, now(), now())",
             u=who, w=b"RIFF", v=str(voiceprint.to_list(vector)), m=voiceprint.MODEL_NAME)
    # En el fixture del 27/9, speaker_1 es Vanina (no grabó su voz) y speaker_2 "el Choto".
    monkeypatch.setattr(voiceprint, "available", lambda: True)
    monkeypatch.setattr(voiceprint, "people_prints", lambda pcm, turns: {
        "speaker_1": _near(LAURA, 0.9), "speaker_2": _near(LAURA, 0.2)})
    assert asyncio.run(diarization.diarize_meeting(meeting_id)) is True
    monkeypatch.undo()
    rows, meeting = _transcript(client, user, meeting_id)
    by_label = {s["label"]: s for s in meeting["speakers"]}
    named = {s["display_name"]: s for s in meeting["speakers"] if s["display_name"]}
    # Bautista se nombra porque lo dijo ("yo soy Bautista Goñi"); "Laura" por su voz.
    assert set(named) == {"Bautista Goñi", "Laura Belzunce"}
    assert len(by_label) == 3
    stored = dict(_sql_rows("SELECT display_name, name_source FROM speakers WHERE meeting_id = :m AND display_name"
                            " IS NOT NULL", m=str(meeting_id)))
    assert stored == {"Bautista Goñi": "dijo", "Laura Belzunce": "voz"}
    _cleanup(meeting_id)


def test_a_sure_match_teaches_the_profile_only_with_permission(client):
    from echo_api.db import SessionLocal
    from echo_api.models import UserVoiceSample

    def sample(learn: bool) -> tuple[uuid.UUID, uuid.UUID]:
        user = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")
        sample_id = uuid.uuid4()
        _sql("INSERT INTO user_voice_samples (id, user_id, audio_wav, duration_ms, consent_at, sample_embedding,"
             " embedding, embedding_model, learn_from_meetings, created_at, updated_at) VALUES (:s, :u, :w,"
             " 9000, now(), CAST(:v AS vector), CAST(:v AS vector), :m, :l, now(), now())",
             s=str(sample_id), u=user.user_id, w=b"RIFF", v=str(voiceprint.to_list(BAUTI)), m=voiceprint.MODEL_NAME,
             l=learn)
        return uuid.UUID(user.user_id), sample_id

    async def learned(user_id, sample_id, learn: bool) -> int:
        candidate = Candidate("Ana", user_id, BAUTI, sample_id, learn)
        prints = {"speaker_1": _near(BAUTI, 0.1)}
        await speaker_names._learn(decide([], [candidate], prints), prints, [candidate])
        async with SessionLocal() as db:
            return (await db.get(UserVoiceSample, sample_id)).learned_count

    assert asyncio.run(learned(*sample(True), True)) == 1
    assert asyncio.run(learned(*sample(False), False)) == 0


def test_saving_my_voice_keeps_its_print_and_learning_can_be_turned_off(client, monkeypatch):
    import io
    import wave

    from test_speakers import _tone

    monkeypatch.setattr(voiceprint, "embed", lambda samples: BAUTI)
    user = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(_tone(5.0))
    auth = {"Authorization": f"Bearer {user.token}"}
    saved = client.post("/api/me/voice", files={"audio": ("voz.wav", buffer.getvalue(), "audio/wav")},
                        data={"consent": "true"}, headers=auth).json()
    assert saved["has_sample"] and saved["learn_from_meetings"] is True
    [(model, learn)] = _sql_rows("SELECT embedding_model, learn_from_meetings FROM user_voice_samples WHERE user_id = :u",
                                 u=user.user_id)
    assert model == voiceprint.MODEL_NAME and learn is True
    _sql("UPDATE user_voice_samples SET learned_count = 3 WHERE user_id = :u", u=user.user_id)
    off = client.patch("/api/me/voice", json={"learn_from_meetings": False}, headers=auth).json()
    assert off["learn_from_meetings"] is False and off["learned_count"] == 0


def test_confirming_a_suggestion_links_the_person_to_the_member(client):
    owner = EchoTestUser(client, name="Mariana Gibson", org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    outsider = EchoTestUser(client, org_name="Otro")
    meeting_id = client.post("/api/meetings", json={"title": "x", "level": "primaria"}, headers=owner.headers).json()["id"]
    speaker_id = str(uuid.uuid4())
    _sql("INSERT INTO speakers (id, meeting_id, label, color, identity_suggestion, created_at, updated_at) VALUES"
         " (:id, :m, 'Persona 1', '#000', CAST(:s AS jsonb), now(), now())", id=speaker_id, m=meeting_id,
         s='{"person_name": "Mariana Gibson", "source": "voz"}')
    url = f"/api/meetings/{meeting_id}/speakers/{speaker_id}"
    client.patch(url, json={"display_name": "Mariana Gibson", "user_id": owner.user_id}, headers=owner.headers)
    [(user_id, source, suggestion)] = _sql_rows(
        "SELECT user_id::text, name_source, identity_suggestion FROM speakers WHERE id = :id", id=speaker_id)
    assert (user_id, source, suggestion) == (owner.user_id, "manual", None)
    # Alguien de otra organización no queda vinculado.
    client.patch(url, json={"display_name": "X", "user_id": outsider.user_id}, headers=owner.headers)
    assert _sql_rows("SELECT user_id FROM speakers WHERE id = :id", id=speaker_id) == [(None,)]
