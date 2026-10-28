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


def _sql_rows(statement: str, **params) -> list[tuple]:
    from echo_api.db import SessionLocal

    async def run():
        async with SessionLocal() as db:
            return [tuple(row) for row in (await db.execute(text(statement), params)).all()]

    return asyncio.run(run())


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
        # Arrancada: un borrador (nunca grabó) solo lo ve quien lo creó.
        assert client.post(f"/api/meetings/{ids[level]}/start", headers=owner.headers).status_code == 200
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

    # Un directivo ve solo lo suyo: ni las reuniones de primaria ni las de secundaria.
    assert _titles(client.get("/api/meetings", headers=director.headers)) == set()

    _grant(client, director, teacher, "primaria", "limitado")
    _grant(client, director, teacher, "primaria", "tutor")
    _grant(client, director, teacher, "primaria", "nulo")
    # Total, adviser y directivo muestran reuniones que un directivo no ve: los da un admin.
    for access in ("total", "adviser", "direccion"):
        _grant(client, director, teacher, "primaria", access, expect=403)
    _grant(client, director, teacher, "secundaria", "limitado", expect=403)
    _grant(client, director, other_director, "primaria", "nulo", expect=403)
    _grant(client, owner, teacher, "primaria", "adviser")
    _grant(client, director, teacher, "primaria", "limitado", expect=403)

    listing = client.get("/api/org/access", headers=director.headers).json()
    assert listing["managed_levels"] == ["primaria"]
    assert listing["can_assign_direction"] is False
    assert listing["assignable"] == ["limitado", "tutor", "nulo"]

    # Mover una reunión de nivel: solo quien dirige los dos niveles (o un admin).
    own = client.post("/api/meetings", json={"title": "De la directora", "level": "primaria"}, headers=director.headers)
    own_id = own.json()["id"]
    moved = client.patch(f"/api/meetings/{own_id}", json={"level": "secundaria"}, headers=director.headers)
    assert moved.status_code == 403
    moved = client.patch(f"/api/meetings/{own_id}", json={"level": "secundaria"}, headers=owner.headers)
    assert moved.status_code == 200 and moved.json()["level"] == "secundaria"
    # La creó ella: la sigue viendo aunque ya no sea de su nivel.
    assert client.get(f"/api/meetings/{own_id}", headers=director.headers).status_code == 200
    # Lo de primaria que no es suyo no lo ve.
    assert client.get(f"/api/meetings/{ids['primaria']}", headers=director.headers).status_code == 404


def test_member_without_direction_cannot_see_the_access_panel(client):
    owner, _ = _school(client)
    teacher = Member(client, owner, "SinPanel")
    _grant(client, owner, teacher, "primaria", "total")
    assert client.get("/api/org/access", headers=teacher.headers).status_code == 403


def test_global_chat_only_sends_visible_meetings_to_the_model(client, fake_ai, monkeypatch):
    from echo_api.services import plans

    monkeypatch.setattr(plans, "is_paid", lambda org, user: True)
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


def _meeting_of(client, who, title: str, level: str = "primaria", **extra) -> str:
    created = client.post("/api/meetings", json={"title": title, "level": level, **extra}, headers=who.headers)
    assert created.status_code == 201, created.text
    # Arrancada: un borrador (nunca grabó) solo lo ve quien lo creó.
    assert client.post(f"/api/meetings/{created.json()['id']}/start", headers=who.headers).status_code == 200
    return created.json()["id"]


def _sees(client, who, meeting_id: str) -> bool:
    """El detalle y la lista tienen que coincidir: son las dos versiones de la regla."""
    detail = client.get(f"/api/meetings/{meeting_id}", headers=who.headers).status_code == 200
    listed = meeting_id in {item["id"] for item in client.get("/api/meetings", headers=who.headers).json()}
    assert detail == listed, "el detalle y la lista no coinciden"
    return listed


def _roles_school(client):
    """Una sede de primaria con una persona por acceso, y la reunión de cada una."""
    owner = EchoTestUser(client, name="Admin Roles", org_name=f"Sede {uuid.uuid4().hex[:4]}")
    people = {}
    for name, access in (
        ("Total", "total"),
        ("Adviser", "adviser"),
        ("Directivo", "direccion"),
        ("OtroDirectivo", "direccion"),
        ("Doe", "limitado"),
        ("Tutora", "tutor"),
        ("OtroDoe", "limitado"),
    ):
        member = Member(client, owner, name)
        _grant(client, owner, member, "primaria", access)
        people[name] = member
    meetings = {name: _meeting_of(client, member, f"Reunión {name} {name.upper()}") for name, member in people.items()}
    return owner, people, meetings


def test_total_sees_every_meeting_of_the_level(client):
    owner, people, meetings = _roles_school(client)
    assert all(_sees(client, people["Total"], meeting_id) for meeting_id in meetings.values())


def test_adviser_sees_what_doe_and_tutor_create_but_not_directivos(client):
    owner, people, meetings = _roles_school(client)
    adviser = people["Adviser"]

    assert _sees(client, adviser, meetings["Adviser"])  # lo suyo
    assert _sees(client, adviser, meetings["Doe"])
    assert _sees(client, adviser, meetings["Tutora"])
    assert _sees(client, adviser, meetings["OtroDoe"])
    assert not _sees(client, adviser, meetings["Directivo"])
    assert not _sees(client, adviser, meetings["OtroDirectivo"])
    assert not _sees(client, adviser, meetings["Total"])

    # Un directivo no ve lo del DOE.
    assert not _sees(client, people["Directivo"], meetings["Doe"])
    assert not _sees(client, people["Directivo"], meetings["Tutora"])


def test_adviser_sees_doe_meetings_in_search_tasks_and_reports(client):
    owner, people, meetings = _roles_school(client)
    adviser = people["Adviser"]
    created = client.post(
        "/api/tasks", json={"text": "Tarea DOE", "meeting_id": meetings["Doe"]}, headers=people["Doe"].headers
    )
    assert created.status_code == 201, created.text
    created = client.post(
        "/api/tasks",
        json={"text": "Tarea Directivo", "meeting_id": meetings["Directivo"]},
        headers=people["Directivo"].headers,
    )
    assert created.status_code == 201, created.text

    search = client.get("/api/search?q=DOE", headers=adviser.headers).json()
    assert "Reunión Doe DOE" in {m["title"] for m in search["meetings"]}
    assert client.get("/api/search?q=DIRECTIVO", headers=adviser.headers).json()["meetings"] == []
    assert {t["text"] for t in client.get("/api/tasks", headers=adviser.headers).json()} == {"Tarea DOE"}
    # La suya + las de Doe, Tutora y OtroDoe.
    assert client.get("/api/reports/overview", headers=adviser.headers).json()["totals"]["meetings"] == 4


def test_adviser_only_sees_doe_meetings_of_her_level_and_not_private_ones(client):
    owner, people, meetings = _roles_school(client)
    adviser = people["Adviser"]
    doe = people["Doe"]
    private = _meeting_of(client, doe, "Privada DOE", visibility="private")
    assert not _sees(client, adviser, private)

    # El mismo DOE con un nivel donde la adviser no tiene acceso.
    _grant(client, owner, doe, "secundaria", "limitado")
    other_level = _meeting_of(client, doe, "Secundaria DOE", level="secundaria")
    assert not _sees(client, adviser, other_level)

    # Si el DOE pasa a otro acceso en el nivel, lo que creó ya no es "del DOE".
    _grant(client, owner, doe, "primaria", "direccion")
    assert not _sees(client, adviser, meetings["Doe"])


def test_directivo_sees_only_his_own(client):
    owner, people, meetings = _roles_school(client)
    directivo = people["Directivo"]

    assert _sees(client, directivo, meetings["Directivo"])
    for name in ("OtroDirectivo", "Total", "Adviser", "Doe", "Tutora"):
        assert not _sees(client, directivo, meetings[name]), name
    assert client.get("/api/search?q=OTRODIRECTIVO", headers=directivo.headers).json()["meetings"] == []
    assert client.get("/api/reports/overview", headers=directivo.headers).json()["totals"]["meetings"] == 1

    # Donde estuvo y lo compartido siguen valiendo.
    staffed = client.put(
        f"/api/meetings/{meetings['OtroDirectivo']}/staff",
        json={"user_ids": [directivo.user_id]},
        headers=people["OtroDirectivo"].headers,
    )
    assert staffed.status_code == 200, staffed.text
    assert _sees(client, directivo, meetings["OtroDirectivo"])
    shared = client.post(
        f"/api/meetings/{meetings['Total']}/shares",
        json={"user_id": directivo.user_id, "role": "viewer"},
        headers=people["Total"].headers,
    )
    assert shared.status_code == 201, shared.text
    assert _sees(client, directivo, meetings["Total"])


def test_directivo_sees_the_meetings_of_his_assigned_families(client):
    owner, people, _ = _roles_school(client)
    directivo = people["Directivo"]
    family = client.post("/api/families", json={"name": "Familia Pérez"}, headers=owner.headers).json()
    meeting_id = _meeting_of(client, people["Doe"], "De la familia FAM")
    classified = client.put(
        f"/api/meetings/{meeting_id}/classification", json={"family_id": family["id"]}, headers=people["Doe"].headers
    )
    assert classified.status_code == 200, classified.text
    assert not _sees(client, directivo, meeting_id)

    assigned = client.put(
        f"/api/families/{family['id']}/assignees", json={"user_ids": [directivo.user_id]}, headers=owner.headers
    )
    assert assigned.status_code == 200, assigned.text
    assert _sees(client, directivo, meeting_id)


def test_tutor_and_doe_see_only_their_own(client):
    owner, people, meetings = _roles_school(client)
    for name in ("Doe", "Tutora"):
        who = people[name]
        assert _sees(client, who, meetings[name])
        others = [meeting_id for other, meeting_id in meetings.items() if other != name]
        assert not any(_sees(client, who, meeting_id) for meeting_id in others), name
        assert client.get("/api/reports/overview", headers=who.headers).json()["totals"]["meetings"] == 1


def test_adviser_is_notified_of_what_the_doe_creates_but_not_a_directivo(client):
    from echo_api.db import SessionLocal
    from echo_api.models import Meeting
    from echo_api.services.access import users_who_can_see

    owner, people, meetings = _roles_school(client)

    async def audience(meeting_id: str) -> set[str]:
        async with SessionLocal() as db:
            meeting = await db.get(Meeting, uuid.UUID(meeting_id))
            return {str(user_id) for user_id in await users_who_can_see(db, meeting)}

    doe_audience = asyncio.run(audience(meetings["Doe"]))
    assert people["Adviser"].user_id in doe_audience and people["Total"].user_id in doe_audience
    assert people["Directivo"].user_id not in doe_audience
    directivo_audience = asyncio.run(audience(meetings["Directivo"]))
    assert people["Adviser"].user_id not in directivo_audience
    assert people["OtroDirectivo"].user_id not in directivo_audience


def test_ranks_for_tasks(client):
    owner, people, _ = _roles_school(client)

    def rank(who) -> int:
        return client.get("/api/org/access/me", headers=who.headers).json()["rank"]

    assert [rank(people[name]) for name in ("Total", "Adviser", "Directivo", "Doe", "Tutora")] == [3, 2, 2, 1, 1]
    assert rank(owner) == 4


def test_puesto_propio_que_ve_las_reuniones_de_un_grupo(client):
    """Adviser: un puesto propio que ve las reuniones no privadas de los del DOE."""
    from test_doe_access import _meeting, _sees

    owner = EchoTestUser(client, name="Admin Sede", org_name=f"Sede {uuid.uuid4().hex[:4]}")
    doe, docente, adviser, colega = (Member(client, owner, name) for name in ("Doe", "Docente", "Adviser", "Colega"))
    for who, position in ((doe, "doe"), (docente, "docente"), (colega, "doe")):
        put = client.put(
            f"/api/org/users/{who.user_id}", json={"position": position, "levels": ["primaria"]}, headers=owner.headers
        )
        assert put.status_code == 200, put.text
    groups = {g["name"]: g["id"] for g in client.get("/api/org/users", headers=owner.headers).json()["groups"]}

    created = client.post(
        "/api/org/positions",
        json={"name": "Jefa DOE", "description": "Jefa del DOE", "access": "limitado", "watch_group_ids": [groups["DOE"]]},
        headers=owner.headers,
    )
    assert created.status_code == 201, created.text
    position_id = created.json()["id"]
    assert client.put(
        f"/api/org/users/{adviser.user_id}", json={"position": position_id, "levels": ["primaria"]}, headers=owner.headers
    ).status_code == 200

    del_doe = _meeting(client, doe, "Del DOE")
    privada = _meeting(client, doe, "Privada del DOE", visibility="private")
    del_docente = _meeting(client, docente, "De la docente")
    con_doe = _meeting(client, docente, "La docente con el DOE")
    staffed = client.put(f"/api/meetings/{con_doe}/staff", json={"user_ids": [colega.user_id]}, headers=docente.headers)
    assert staffed.status_code == 200, staffed.text

    assert _sees(client, adviser, del_doe)
    assert _sees(client, adviser, con_doe)  # estuvo alguien del DOE
    assert not _sees(client, adviser, privada)
    assert not _sees(client, adviser, del_docente)
    # El DOE no ve lo de otro DOE: el permiso es del puesto, no del grupo.
    assert not _sees(client, doe, con_doe)
    # A la Adviser le llegan los avisos de lo que ve.
    from echo_api.db import SessionLocal
    from echo_api.models import Meeting
    from echo_api.services.access import users_who_can_see

    async def who_sees(meeting_id):
        async with SessionLocal() as db:
            return {str(u) for u in await users_who_can_see(db, await db.get(Meeting, uuid.UUID(meeting_id)))}

    assert adviser.user_id in asyncio.run(who_sees(del_doe))
    assert adviser.user_id in asyncio.run(who_sees(con_doe))
    assert adviser.user_id not in asyncio.run(who_sees(del_docente))
    assert adviser.user_id not in asyncio.run(who_sees(privada))

    # Editar el puesto se aplica a quien lo tiene: sin grupos, deja de verlas.
    edited = client.put(
        f"/api/org/positions/{position_id}",
        json={"name": "Jefa DOE", "access": "total", "watch_group_ids": []},
        headers=owner.headers,
    )
    assert edited.status_code == 200, edited.text
    users = {u["user_id"]: u for u in client.get("/api/org/users", headers=owner.headers).json()["users"]}
    assert users[adviser.user_id]["levels"] == {"primaria": "total"}
    assert _sees(client, adviser, del_docente)  # ahora por el nivel

    # Borrarlo en uso pide a qué puesto pasar a esa gente.
    assert client.delete(f"/api/org/positions/{position_id}", headers=owner.headers).status_code == 409
    assert client.delete(f"/api/org/positions/{position_id}?move_to=docente", headers=owner.headers).status_code == 204
    users = {u["user_id"]: u for u in client.get("/api/org/users", headers=owner.headers).json()["users"]}
    assert users[adviser.user_id]["position"] == "docente"
    assert users[adviser.user_id]["levels"] == {"primaria": "limitado"}
    assert not _sees(client, adviser, del_docente)


def test_puesto_propio_lo_arma_solo_quien_administra_y_nadie_se_da_mas(client):
    owner = EchoTestUser(client, name="Admin Sede", org_name=f"Sede {uuid.uuid4().hex[:4]}")
    doe = Member(client, owner, "Doe")
    assert client.post("/api/org/positions", json={"name": "X"}, headers=doe.headers).status_code == 403
    # Ni repetir el nombre de un fijo.
    assert client.post("/api/org/positions", json={"name": "docente"}, headers=owner.headers).status_code == 409
    other = EchoTestUser(client, name="Otra", org_name=f"Sede {uuid.uuid4().hex[:4]}")
    put = client.put(f"/api/org/users/{owner.user_id}", json={"position": "doe", "levels": ["primaria"]}, headers=other.headers)
    assert put.status_code in (403, 404)
    foreign = client.get("/api/org/users", headers=other.headers).json()["groups"]
    if foreign:
        bad = client.post(
            "/api/org/positions", json={"name": "Y", "watch_group_ids": [foreign[0]["id"]]}, headers=owner.headers
        )
        assert bad.status_code == 400
