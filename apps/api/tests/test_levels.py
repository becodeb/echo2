"""Niveles: quién ve qué reunión, en cada lugar por donde se puede ver contenido.

La regla vive en services/access.py. Estos tests la recorren superficie por
superficie (detalle, listas, búsqueda, tareas, reportes, inicio, chat,
avisos) porque cada una tenía su propia consulta y cualquiera que se olvide
del filtro filtra reuniones de otro nivel.
"""
import asyncio
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from conftest import TEST_DATABASE_URL, EchoTestUser


def _sql(statement: str, **params):
    async def run():
        engine = create_async_engine(TEST_DATABASE_URL)
        async with engine.begin() as connection:
            await connection.execute(text(statement), params)
        await engine.dispose()

    asyncio.run(run())


class Member:
    def __init__(self, client, owner: EchoTestUser, name: str):
        email = f"{name.lower()}-{uuid.uuid4().hex[:6]}@test.echo"
        token = client.post("/api/org/invites", json={"email": email, "role": "member"}, headers=owner.headers).json()["token"]
        registered = client.post(
            "/api/auth/register", json={"email": email, "password": "password123", "name": name}
        ).json()
        self.token = registered["access_token"]
        self.user_id = registered["user"]["id"]
        self.headers = {"Authorization": f"Bearer {self.token}", "X-Organization-Id": owner.org_id}
        accepted = client.post("/api/auth/invites/accept", json={"token": token}, headers={"Authorization": f"Bearer {self.token}"})
        assert accepted.status_code == 200, accepted.text


def _grant(client, by, member: Member, level: str, access: str, expect: int = 200):
    response = client.put(
        "/api/org/access", json={"user_id": member.user_id, "level": level, "access": access}, headers=by.headers
    )
    assert response.status_code == expect, response.text
    return response


def _school(client):
    """Una sede con una reunión de primaria y otra de secundaria, cada una con su tarea."""
    owner = EchoTestUser(client, name="Admin Sede", org_name=f"Sede {uuid.uuid4().hex[:4]}")
    ids = {}
    for level, word in (("primaria", "ALFA"), ("secundaria", "BETA")):
        created = client.post(
            "/api/meetings", json={"title": f"Reunión {level} {word}", "level": level}, headers=owner.headers
        )
        assert created.status_code == 201, created.text
        assert created.json()["level"] == level
        ids[level] = created.json()["id"]
        task = client.post(
            "/api/tasks", json={"text": f"Tarea {word}", "meeting_id": ids[level]}, headers=owner.headers
        )
        assert task.status_code == 201, task.text
    return owner, ids


def _titles(response) -> set[str]:
    return {item["title"] for item in response.json()}


def test_total_access_sees_its_level_everywhere_and_nothing_of_the_other(client):
    owner, ids = _school(client)
    teacher = Member(client, owner, "Maestra")
    _grant(client, owner, teacher, "primaria", "total")

    assert _titles(client.get("/api/meetings", headers=teacher.headers)) == {"Reunión primaria ALFA"}
    assert client.get(f"/api/meetings/{ids['primaria']}", headers=teacher.headers).status_code == 200
    assert client.get(f"/api/meetings/{ids['secundaria']}", headers=teacher.headers).status_code == 404

    search = client.get("/api/search?q=BETA", headers=teacher.headers).json()
    assert search["meetings"] == [] and search["tasks"] == []
    assert client.get("/api/search?q=ALFA", headers=teacher.headers).json()["tasks"]

    tasks = {task["text"] for task in client.get("/api/tasks", headers=teacher.headers).json()}
    assert tasks == {"Tarea ALFA"}

    report = client.get("/api/reports/overview", headers=teacher.headers).json()
    assert report["totals"]["meetings"] == 1

    dashboard = client.get("/api/dashboard", headers=teacher.headers).json()
    assert {m["title"] for m in dashboard["recent_meetings"]} == {"Reunión primaria ALFA"}

    # La admin de la sede ve las dos.
    assert _titles(client.get("/api/meetings", headers=owner.headers)) == {
        "Reunión primaria ALFA",
        "Reunión secundaria BETA",
    }


def test_limited_access_sees_only_own_and_shared(client):
    owner, ids = _school(client)
    teacher = Member(client, owner, "Limitada")
    _grant(client, owner, teacher, "primaria", "limitado")

    assert client.get("/api/meetings", headers=teacher.headers).json() == []
    own = client.post("/api/meetings", json={"title": "Mía"}, headers=teacher.headers)
    assert own.status_code == 201 and own.json()["level"] == "primaria"
    # No puede crear en un nivel al que no tiene acceso.
    other_level = client.post("/api/meetings", json={"title": "X", "level": "secundaria"}, headers=teacher.headers)
    assert other_level.status_code == 403

    # Compartir le abre una reunión puntual, aunque sea de otro nivel.
    shared = client.post(
        f"/api/meetings/{ids['secundaria']}/shares", json={"user_id": teacher.user_id, "role": "viewer"}, headers=owner.headers
    )
    assert shared.status_code == 201, shared.text
    assert _titles(client.get("/api/meetings", headers=teacher.headers)) == {"Mía", "Reunión secundaria BETA"}
    assert client.get(f"/api/meetings/{ids['secundaria']}", headers=teacher.headers).status_code == 200


def test_private_meeting_stays_private_inside_its_level(client):
    owner, _ = _school(client)
    teacher = Member(client, owner, "Colega")
    _grant(client, owner, teacher, "primaria", "total")
    private = client.post(
        "/api/meetings", json={"title": "Privada PRIM", "level": "primaria", "visibility": "private"}, headers=owner.headers
    ).json()["id"]

    assert client.get(f"/api/meetings/{private}", headers=teacher.headers).status_code == 404
    assert "Privada PRIM" not in _titles(client.get("/api/meetings", headers=teacher.headers))


def test_new_member_declares_level_and_starts_limited(client):
    owner, _ = _school(client)
    newcomer = Member(client, owner, "Nueva")

    me = client.get("/api/org/access/me", headers=newcomer.headers).json()
    assert me["needs_level"] is True
    assert client.post("/api/meetings", json={"title": "Todavía no"}, headers=newcomer.headers).status_code == 403

    declared = client.post("/api/org/access/me", json={"levels": ["primaria", "secundaria"]}, headers=newcomer.headers)
    assert declared.status_code == 200, declared.text
    assert declared.json()["access"] == {"primaria": "limitado", "secundaria": "limitado"}
    # Nadie se da más acceso eligiendo de nuevo.
    assert client.post("/api/org/access/me", json={"levels": ["primaria"]}, headers=newcomer.headers).status_code == 409
    # Limitado: todavía no ve las reuniones de los demás.
    assert client.get("/api/meetings", headers=newcomer.headers).json() == []


def test_direction_manages_only_its_level(client):
    owner, ids = _school(client)
    director = Member(client, owner, "Directora")
    teacher = Member(client, owner, "Docente")
    other_director = Member(client, owner, "OtraDirectora")
    _grant(client, owner, director, "primaria", "direccion")
    _grant(client, owner, other_director, "primaria", "direccion")

    # Ve todo primaria, nada de secundaria.
    assert _titles(client.get("/api/meetings", headers=director.headers)) == {"Reunión primaria ALFA"}

    _grant(client, director, teacher, "primaria", "total")
    _grant(client, director, teacher, "primaria", "limitado")
    _grant(client, director, teacher, "primaria", "nulo")
    _grant(client, director, teacher, "primaria", "direccion", expect=403)
    _grant(client, director, teacher, "secundaria", "total", expect=403)
    _grant(client, director, other_director, "primaria", "nulo", expect=403)

    listing = client.get("/api/org/access", headers=director.headers).json()
    assert listing["managed_levels"] == ["primaria"]
    assert listing["can_assign_direction"] is False

    # Mover una reunión de nivel: solo quien dirige los dos niveles (o un admin).
    moved = client.patch(f"/api/meetings/{ids['primaria']}", json={"level": "secundaria"}, headers=director.headers)
    assert moved.status_code == 403
    moved = client.patch(f"/api/meetings/{ids['primaria']}", json={"level": "secundaria"}, headers=owner.headers)
    assert moved.status_code == 200 and moved.json()["level"] == "secundaria"
    assert client.get(f"/api/meetings/{ids['primaria']}", headers=director.headers).status_code == 404


def test_member_without_direction_cannot_see_the_access_panel(client):
    owner, _ = _school(client)
    teacher = Member(client, owner, "SinPanel")
    _grant(client, owner, teacher, "primaria", "total")
    assert client.get("/api/org/access", headers=teacher.headers).status_code == 403


def test_global_chat_only_sends_visible_meetings_to_the_model(client, fake_ai):
    owner, _ = _school(client)
    teacher = Member(client, owner, "Pregunta")
    _grant(client, owner, teacher, "primaria", "total")

    answered = client.post("/api/ask", json={"question": "¿Qué reuniones hubo?"}, headers=teacher.headers)
    assert answered.status_code == 200, answered.text
    prompt = fake_ai.calls[-1]["user"]
    assert "ALFA" in prompt
    assert "BETA" not in prompt


def test_superadmin_sees_every_campus_without_being_a_member(client):
    school_owner, ids = _school(client)
    admin = EchoTestUser(client, name="Superadmin", org_name="Becode")
    # Antes de ser superadmin, la sede ajena no existe para esta persona.
    outsider = {"Authorization": f"Bearer {admin.token}", "X-Organization-Id": school_owner.org_id}
    assert client.get(f"/api/meetings/{ids['primaria']}", headers=outsider).status_code == 403

    _sql("update users set is_superadmin = true where id = :id", id=admin.user_id)
    session = client.get("/api/auth/me", headers={"Authorization": f"Bearer {admin.token}"}).json()
    assert school_owner.org_id in {org["id"] for org in session["organizations"]}

    headers = outsider
    assert _titles(client.get("/api/meetings", headers=headers)) == {"Reunión primaria ALFA", "Reunión secundaria BETA"}
    assert client.get("/api/org/access/me", headers=headers).json()["superadmin_visit"] is True


def test_minutes_ready_notification_only_reaches_who_can_see(client, fake_ai):
    from test_e2e_flow import _record_meeting

    owner = EchoTestUser(client, name="Admin Avisos", org_name="Sede Avisos")
    primaria = Member(client, owner, "Prim")
    secundaria = Member(client, owner, "Secu")
    _grant(client, owner, primaria, "primaria", "total")
    _grant(client, owner, secundaria, "secundaria", "total")

    meeting_id = client.post("/api/meetings", json={"title": "Aviso PRIM", "level": "primaria"}, headers=owner.headers).json()["id"]
    client.post(f"/api/meetings/{meeting_id}/start", headers=owner.headers)
    _record_meeting(client, owner, meeting_id)
    client.post(f"/api/meetings/{meeting_id}/finish", headers=owner.headers)

    import time

    deadline = time.time() + 30
    while time.time() < deadline:
        if client.get(f"/api/meetings/{meeting_id}", headers=owner.headers).json()["status"] == "completed":
            break
        time.sleep(0.4)

    def titles(member):
        return [n["title"] for n in client.get("/api/notifications", headers=member.headers).json()["notifications"]]

    assert any("Aviso PRIM" in title for title in titles(primaria))
    assert not any("Aviso PRIM" in title for title in titles(secundaria))
