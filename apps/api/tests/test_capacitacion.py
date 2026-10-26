"""Pedidos de la capacitación de Northfield (26/10).

- El acta nombra al alumno solo con iniciales y lleva su curso; la familia
  puede tener varios hijos y cada reunión dice de cuál es.
- Nada de tareas inventadas: cada una trae la frase que la respalda.
"""
import uuid

from conftest import EchoTestUser

from echo_api.services.acta_entrevista import hide_student_names, initials
from echo_api.services.transcript_util import is_grounded


def test_iniciales_del_alumno():
    assert initials("MUNAFO, Allegra") == "A. M."
    assert initials("Tomás Pérez Gil") == "T. P. G."
    text = "La familia de Allegra Munafo cuenta que Allegra (MUNAFO, Allegra) mejoró."
    assert hide_student_names(text, [("MUNAFO, Allegra", "A. M.")]) == "La familia de A. M. cuenta que A. M. (A. M.) mejoró."
    # No toca palabras que solo contienen el nombre.
    assert hide_student_names("Analía y Ana", [("Ana Ruiz", "A. R.")]) == "Analía y A. R."


def test_tarea_sin_frase_que_la_respalde_no_va():
    lines = [
        {"start_ms": 0, "text": "Hablamos de que le cuesta leer en voz alta."},
        {"start_ms": 30_000, "text": "Yo le mando el informe a la psicopedagoga el lunes."},
    ]
    real = {"text": "Mandar el informe", "quote": "yo le mando el informe a la psicopedagoga", "evidence_start_ms": 30_000}
    invented = {"text": "Practicar lectura en casa", "quote": "van a practicar lectura todos los días", "evidence_start_ms": 0}
    no_quote = {"text": "Seguir trabajando la lectura", "evidence_start_ms": 0}
    assert is_grounded(real, lines)
    assert not is_grounded(invented, lines)
    assert not is_grounded(no_quote, lines)
    # Lejos de su evidencia no vale (otra parte de la reunión).
    far = dict(real, evidence_start_ms=600_000)
    assert not is_grounded(far, lines + [{"start_ms": 600_000, "text": "Bueno, nos vemos."}])


def test_familia_con_varios_hijos_y_de_cual_es_la_reunion(client):
    owner = EchoTestUser(client, name="Directora", org_name=f"Sede {uuid.uuid4().hex[:4]}")
    family = client.post("/api/families", json={"name": "Familia Munafo"}, headers=owner.headers).json()
    kids = {}
    for name, curso in (("MUNAFO, Allegra", "3N EP"), ("MUNAFO, Bruno", "1F EP")):
        created = client.post(
            f"/api/families/{family['id']}/members",
            json={"name": name, "relationship_type": "estudiante", "is_guardian": False, "curso": curso, "level": "primaria"},
            headers=owner.headers,
        )
        assert created.status_code == 201, created.text
        assert created.json()["curso"] == curso
        kids[name] = created.json()["id"]

    meeting_id = client.post("/api/meetings", json={"title": "Entrevista"}, headers=owner.headers).json()["id"]
    classified = client.put(
        f"/api/meetings/{meeting_id}/classification",
        json={"family_id": family["id"], "student_ids": [kids["MUNAFO, Bruno"]]},
        headers=owner.headers,
    )
    assert classified.status_code == 200, classified.text
    assert classified.json()["student_ids"] == [kids["MUNAFO, Bruno"]]

    # Un alumno de otra familia no.
    other = client.post("/api/families", json={"name": "Otra"}, headers=owner.headers).json()
    stranger = client.post(
        f"/api/families/{other['id']}/members", json={"name": "Otro Chico", "relationship_type": "estudiante"},
        headers=owner.headers,
    ).json()["id"]
    rejected = client.put(
        f"/api/meetings/{meeting_id}/classification",
        json={"family_id": family["id"], "student_ids": [stranger]},
        headers=owner.headers,
    )
    assert rejected.status_code == 400

    # Cambiar de familia suelta los hijos elegidos.
    moved = client.put(f"/api/meetings/{meeting_id}/classification", json={"family_id": other["id"]}, headers=owner.headers)
    assert moved.json()["student_ids"] == []


def test_varios_idiomas_no_fuerza_castellano_ni_borra_el_ruso():
    from echo_api.services.insights_prompts import language_name
    from echo_api.services.stt.channels import is_noise_transcript, stt_language

    assert stt_language("multi") is None
    assert stt_language("auto") == "es" and stt_language(None) == "es" and stt_language("en") == "en"
    russian = "Мой сын плохо спит последние недели"
    # En una reunión en castellano el cirílico es ruido del modelo; con varios idiomas es el papá.
    assert is_noise_transcript(russian, "es")
    assert not is_noise_transcript(russian, None)
    assert not is_noise_transcript("He is doing much better in math", None)
    assert is_noise_transcript("مرحبا بكم في الاجتماع", None)  # el árabe sobre ruido sigue afuera
    # El acta sale en el idioma de actas de la sede, nunca "multi".
    assert language_name("multi") == "castellano" and language_name("en") == "inglés"


def test_las_tareas_de_echo_se_confirman_o_se_descartan(client):
    import asyncio
    from datetime import date

    from echo_api.services.pipeline import _persist_insights

    owner = EchoTestUser(client, name="Karina", org_name=f"Sede {uuid.uuid4().hex[:4]}")
    meeting_id = client.post("/api/meetings", json={"title": "Equipo"}, headers=owner.headers).json()["id"]
    insights = {"tasks": [{"text": "Mandar el informe"}, {"text": "Algo que la IA entendió mal"}]}
    asyncio.run(_persist_insights(uuid.UUID(meeting_id), insights, date(2026, 10, 26)))

    def by_text():
        items = client.get(f"/api/meetings/{meeting_id}/insights", headers=owner.headers).json()["action_items"]
        return {t["text"]: t for t in items}

    tasks = by_text()
    assert {t["status"] for t in tasks.values()} == {"suggested"}
    assert client.get("/api/tasks", headers=owner.headers).json() == []  # no cuentan todavía
    notes = client.get("/api/notifications", headers=owner.headers).json()["notifications"]
    assert any(note["kind"] == "tasks_suggested" for note in notes)

    client.patch(f"/api/tasks/{tasks['Mandar el informe']['id']}", json={"status": "pending"}, headers=owner.headers)
    client.patch(f"/api/tasks/{tasks['Algo que la IA entendió mal']['id']}", json={"status": "dismissed"}, headers=owner.headers)
    assert [t["text"] for t in client.get("/api/tasks", headers=owner.headers).json()] == ["Mandar el informe"]

    # Rehacer la pasada final no revive la descartada ni duplica la confirmada.
    asyncio.run(_persist_insights(uuid.UUID(meeting_id), insights, date(2026, 10, 26)))
    tasks = by_text()
    assert len(tasks) == 2 and tasks["Algo que la IA entendió mal"]["status"] == "dismissed"


def test_intersede_sale_sin_el_formato_de_la_sede(client):
    import asyncio

    from echo_api.db import SessionLocal
    from echo_api.models import Meeting
    from echo_api.services.minutes_gen import DEFAULT_TEMPLATE, template_for
    from test_acta_entrevista import TEMPLATE

    owner = EchoTestUser(client, name="Karina", org_name=f"Puertos {uuid.uuid4().hex[:4]}")
    client.put("/api/org/minutes-template", json={"name": "Acta de entrevista", "body_markdown": TEMPLATE}, headers=owner.headers)
    normal = client.post("/api/meetings", json={"title": "De la sede"}, headers=owner.headers).json()
    between = client.post("/api/meetings", json={"title": "Entre sedes", "intersede": True}, headers=owner.headers).json()
    assert between["meta"]["intersede"] is True

    async def bodies():
        async with SessionLocal() as db:
            return [
                (await template_for(db, await db.get(Meeting, uuid.UUID(m["id"])))).body_markdown
                for m in (normal, between)
            ]

    sede, intersede = asyncio.run(bodies())
    assert "{{alumno}}" in sede
    assert intersede == DEFAULT_TEMPLATE


def test_importar_alumnos_y_familias_desde_csv(client):
    owner = EchoTestUser(client, name="Secretaría", org_name=f"Sede {uuid.uuid4().hex[:4]}")
    csv_text = (
        "Apellido;Nombre;Curso;Madre;Email\n"
        "PÉREZ;Tomás;3N EP;Ana Gómez;ana@x.com\n"
        "PÉREZ;Lucía;Sala 5;Ana Gómez;ana@x.com\n"
        "PÉREZ;Juan;2do año;Laura Ruiz;\n"
        ";;4B EP;;\n"  # sin nombre: se saltea
        ";;;;\n"  # vacía: ni cuenta
        "Gil;Sol;1F ES;;\n"
    ).encode("latin-1")  # como lo guarda Excel en castellano

    def upload(preview: bool):
        return client.post(
            "/api/families/import", params={"preview": str(preview).lower()},
            files={"file": ("alumnos.csv", csv_text, "text/csv")}, headers=owner.headers,
        )

    preview = upload(True)
    assert preview.status_code == 200, preview.text
    assert preview.json()["families_created"] == 3 and preview.json()["students"] == 4
    assert preview.json()["skipped_rows"] == 1
    assert client.get("/api/families", headers=owner.headers).json() == []  # la vista previa no guarda

    assert upload(False).json()["students"] == 4
    families = {f["name"]: f for f in client.get("/api/families", headers=owner.headers).json()}
    hermanos = families["Familia Pérez (Ana Gómez)"]
    kids = {m["name"]: m for m in hermanos["members"] if m["relationship_type"] == "estudiante"}
    assert kids["PÉREZ, Lucía"]["curso"] == "Sala 5" and kids["PÉREZ, Lucía"]["level"] == "inicial"
    assert kids["PÉREZ, Tomás"]["level"] == "primaria"
    assert families["Familia Gil"]["members"][0]["level"] == "secundaria"

    # Subirlo de nuevo no duplica nada.
    again = upload(False).json()
    assert again["families_created"] == 0 and again["students"] == 0

    # Un DOE no importa.
    from test_levels import Member, _grant

    doe = Member(client, owner, "Flor")
    _grant(client, owner, doe, "primaria", "limitado")
    denied = client.post(
        "/api/families/import", files={"file": ("a.csv", csv_text, "text/csv")}, headers=doe.headers
    )
    assert denied.status_code == 403
