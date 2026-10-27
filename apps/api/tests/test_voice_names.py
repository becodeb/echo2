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
from test_levels import _sql, _sql_rows

from echo_api.services import diarization, speaker_names, voiceprint
from echo_api.services.speaker_names import Candidate, could_have_been, decide, said_names


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


def test_the_voice_only_suggests_and_nobody_twice():
    bauti = Candidate("Bautista Goñi", uuid.uuid4(), BAUTI)
    laura = Candidate("Laura Belzunce", uuid.uuid4(), LAURA)
    prints = {"speaker_1": _near(BAUTI, 0.2), "speaker_2": _near(LAURA, 0.2)}
    names = decide([], [bauti, laura], prints)
    # Aun con coincidencia altísima, la voz sola no pone el nombre (27/10).
    assert {k: (n.name, n.accepted, n.source) for k, n in names.items()} == {
        "speaker_1": ("Bautista Goñi", False, "voz"), "speaker_2": ("Laura Belzunce", False, "voz"),
    }
    # Sin porcentaje: el parecido no dice qué tan seguro es.
    assert "confidence" not in names["speaker_1"].suggestion()
    # Dos personas que se parecen a la misma muestra: no se sugiere ninguna.
    twins = {"speaker_1": _near(BAUTI, 0.3), "speaker_2": _near(BAUTI, 0.35)}
    assert decide([], [bauti], twins) == {}


def test_without_margin_over_the_second_nothing_is_suggested():
    bauti = Candidate("Bautista Goñi", uuid.uuid4(), BAUTI)
    # Coseno ~0,71: como dos personas distintas en la misma sala. Nada.
    assert decide([], [bauti], {"speaker_1": _near(BAUTI, 1.0)}) == {}
    assert decide([], [bauti], {"speaker_1": OTHER}) == {}
    # Coseno ~0,80 y nadie más parecido: "¿Puede ser Bautista?".
    assert decide([], [bauti], {"speaker_1": _near(BAUTI, 0.75)})["speaker_1"].name == "Bautista Goñi"
    # 7/10: cuatro personas, tres muestras de gente que no estuvo, todas
    # parecidas entre 0,80 y 0,83. El uno a uno le "daba" a cada muestra
    # alguien; sin margen no se sugiere nadie.
    scores = [[0.83, 0.82, 0.80], [0.82, 0.83, 0.81], [0.81, 0.80, 0.82], [0.80, 0.81, 0.80]]
    assert voiceprint.assign(np.array(scores)) == []


def test_only_who_could_have_been_there_is_compared():
    creator, natalia, natalia_b, vanina, laura = (uuid.uuid4() for _ in range(5))
    members = [(creator, "Analía Musso"), (natalia, "Natalia Miranda"), (vanina, "Vanina Gerstner"),
               (laura, "Laura Belzunce")]
    # La creadora, quien figura como que estuvo y "Natalia" (una sola en el colegio).
    assert could_have_been(creator, members, [("Natalia", None), ("Vanina Gerstner", vanina)]) == {
        creator, natalia, vanina}
    # Dos Natalias: no se sabe cuál. Y alguien de afuera del colegio no cuenta.
    members.append((natalia_b, "Natalia Pérez"))
    assert could_have_been(creator, members, [("Natalia", None), ("Otra", uuid.uuid4())]) == {creator}
    assert could_have_been(creator, members, [("Natalia Pérez", None)]) == {creator, natalia_b}


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


def _voice_sample(user_id: str, vector: np.ndarray, duration_ms: int = 9000) -> None:
    _sql("INSERT INTO user_voice_samples (id, user_id, audio_wav, duration_ms, consent_at, sample_embedding,"
         " embedding, embedding_model, created_at, updated_at) VALUES (gen_random_uuid(), :u, '\\x00', :d,"
         " now(), CAST(:v AS vector), CAST(:v AS vector), :m, now(), now())",
         u=user_id, d=duration_ms, v=str(voiceprint.to_list(vector)), m=voiceprint.MODEL_NAME)


def _member(client, meeting_id, name: str) -> EchoTestUser:
    member = EchoTestUser(client, name=name, org_name="x")
    _sql("INSERT INTO organization_members (id, organization_id, user_id, role, created_at, updated_at)"
         " VALUES (gen_random_uuid(), :o, :u, 'member', now(), now())",
         o=_sql_rows("SELECT organization_id::text FROM meetings WHERE id = :m", m=str(meeting_id))[0][0],
         u=member.user_id)
    return member


def _diarize_with(monkeypatch, meeting_id) -> None:
    # En el fixture del 27/9, speaker_1 es Vanina (no grabó su voz) y speaker_2 "el Choto".
    _setup(monkeypatch, "2026-09-27")
    monkeypatch.setattr(voiceprint, "available", lambda: True)
    monkeypatch.setattr(voiceprint, "people_prints", lambda pcm, turns: {
        "speaker_1": _near(LAURA, 0.9), "speaker_2": _near(LAURA, 0.2)})
    assert asyncio.run(diarization.diarize_meeting(meeting_id)) is True
    monkeypatch.undo()


def test_the_final_pass_suggests_people_by_their_voice(client, monkeypatch):
    _setup(monkeypatch, "2026-09-27")
    user, meeting_id = _meeting(client, 20.4, [(0, 20400, "hola", None)], people=True)
    monkeypatch.undo()
    laura = _member(client, meeting_id, "Laura Belzunce")
    # Emma grabó su voz pero no figura en la reunión: no se compara con ella.
    emma = _member(client, meeting_id, "Emma Esposito")
    _voice_sample(user.user_id, BAUTI)
    _voice_sample(laura.user_id, LAURA)
    _voice_sample(emma.user_id, _near(LAURA, 0.05))
    _sql("INSERT INTO meeting_participants (id, meeting_id, name, created_at, updated_at)"
         " VALUES (gen_random_uuid(), :m, 'Laura', now(), now())", m=str(meeting_id))
    _diarize_with(monkeypatch, meeting_id)
    rows, meeting = _transcript(client, user, meeting_id)
    # Bautista se nombra porque lo dijo ("yo soy Bautista Goñi"); a Laura se
    # la sugiere por su voz, sin porcentaje.
    assert [s["display_name"] for s in meeting["speakers"] if s["display_name"]] == ["Bautista Goñi"]
    [suggested] = [s for s in meeting["speakers"] if s["identity_suggestion"]]
    assert suggested["identity_suggestion"] == {
        "person_name": "Laura Belzunce", "user_id": laura.user_id, "source": "voz"}
    stored = dict(_sql_rows("SELECT display_name, name_source FROM speakers WHERE meeting_id = :m AND display_name"
                            " IS NOT NULL", m=str(meeting_id)))
    assert stored == {"Bautista Goñi": "dijo"}

    # "No es Laura": no se le vuelve a sugerir aunque se procese de nuevo.
    url = f"/api/meetings/{meeting_id}/speakers/{suggested['id']}/reject-suggestion"
    assert client.post(url, headers=user.headers).status_code == 200
    assert _sql_rows("SELECT meta->'voice_rejected' FROM meetings WHERE id = :m", m=str(meeting_id)) == [
        ([laura.user_id],)]
    _diarize_with(monkeypatch, meeting_id)
    _, again = _transcript(client, user, meeting_id)
    assert {s["id"] for s in again["speakers"]}.isdisjoint(s["id"] for s in meeting["speakers"])
    assert not [s for s in again["speakers"] if (s["identity_suggestion"] or {}).get("source") == "voz"]
    _cleanup(meeting_id)


def test_a_short_sample_is_not_compared(client):
    from echo_api.db import SessionLocal
    from echo_api.models import Meeting

    user = EchoTestUser(client, name="Analía Musso", org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    meeting_id = client.post("/api/meetings", json={"title": "x", "level": "primaria"}, headers=user.headers).json()["id"]
    _voice_sample(user.user_id, BAUTI, duration_ms=4700)

    async def voices():
        async with SessionLocal() as db:
            meeting = await db.get(Meeting, uuid.UUID(meeting_id))
            return [c.voice for c in await speaker_names._candidates(db, meeting)]

    assert asyncio.run(voices()) == [None]
    assert client.get("/api/me/voice", headers=user.headers).json()["warning"] == "corta"
    _sql("UPDATE user_voice_samples SET duration_ms = 9000 WHERE user_id = :u", u=user.user_id)
    [voice] = asyncio.run(voices())
    assert voice is not None
    assert client.get("/api/me/voice", headers=user.headers).json()["warning"] is None


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
        out.writeframes(_tone(10.0))
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


def test_naming_someone_else_counts_as_not_this_person(client):
    owner = EchoTestUser(client, name="Mariana Gibson", org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    meeting_id = client.post("/api/meetings", json={"title": "x", "level": "primaria"}, headers=owner.headers).json()["id"]
    laura = str(uuid.uuid4())

    def speaker() -> str:
        speaker_id = str(uuid.uuid4())
        _sql("INSERT INTO speakers (id, meeting_id, label, color, identity_suggestion, created_at, updated_at) VALUES"
             " (:id, :m, 'Persona 1', '#000', CAST(:s AS jsonb), now(), now())", id=speaker_id, m=meeting_id,
             s=f'{{"person_name": "Laura Belzunce", "user_id": "{laura}", "source": "voz"}}')
        return f"/api/meetings/{meeting_id}/speakers/{speaker_id}"

    def rejected():
        return _sql_rows("SELECT meta->'voice_rejected' FROM meetings WHERE id = :m", m=meeting_id)[0][0]

    # Escribir a mano el mismo nombre no es un "no".
    client.patch(speaker(), json={"display_name": "laura belzunce"}, headers=owner.headers)
    assert rejected() is None
    client.patch(speaker(), json={"display_name": "Vanina"}, headers=owner.headers)
    assert rejected() == [laura]
