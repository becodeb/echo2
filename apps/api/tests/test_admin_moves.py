"""Mover a alguien de sede: desde el panel y pidiéndoselo a Echo."""
import json

from conftest import EchoTestUser
from test_levels import _sql, _sql_rows


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {user.token}"}


def _superadmin(client) -> EchoTestUser:
    admin = EchoTestUser(client, name="Becode", org_name="Sede Becode")
    _sql("UPDATE users SET is_superadmin = true WHERE id = :id", id=admin.user_id)
    return admin


def _join(user_id: str, org_id: str, role="member", position=None, levels: dict | None = None) -> None:
    _sql(
        "INSERT INTO organization_members (id, organization_id, user_id, role, position, created_at, updated_at) "
        "VALUES (gen_random_uuid(), :org, :user, :role, :position, now(), now())",
        org=org_id, user=user_id, role=role, position=position,
    )
    for level, access in (levels or {}).items():
        _sql(
            "INSERT INTO member_level_access (id, organization_id, user_id, level, access, created_at, updated_at) "
            "VALUES (gen_random_uuid(), :org, :user, :level, :access, now(), now())",
            org=org_id, user=user_id, level=level, access=access,
        )


def _membership(user_id: str, org_id: str) -> list:
    return _sql_rows(
        "SELECT role, position FROM organization_members WHERE user_id = :user AND organization_id = :org",
        user=user_id, org=org_id,
    )


def _levels(user_id: str, org_id: str) -> dict:
    return dict(
        _sql_rows(
            "SELECT level, access FROM member_level_access WHERE user_id = :user AND organization_id = :org",
            user=user_id, org=org_id,
        )
    )


def _move(client, admin, user_id, source, target):
    return client.post(
        f"/api/admin/people/{user_id}/move",
        json={"from_organization_id": source, "to_organization_id": target},
        headers=_auth(admin),
    )


def test_solo_el_superadmin_mueve(client):
    person = EchoTestUser(client)
    other = EchoTestUser(client, org_name="Otra sede")
    assert _move(client, person, person.user_id, person.org_id, other.org_id).status_code == 404
    assert client.get(
        f"/api/admin/people/{person.user_id}/move",
        params={"from_organization_id": person.org_id, "to_organization_id": other.org_id},
        headers=_auth(person),
    ).status_code == 404


def test_mover_lleva_rol_puesto_y_niveles_y_sale_de_la_otra(client):
    admin = _superadmin(client)
    origin = EchoTestUser(client, org_name="Sede Origen")
    target = EchoTestUser(client, org_name="Sede Destino")
    person = EchoTestUser(client, name="Ana Gómez")
    _join(person.user_id, origin.org_id, position="docente", levels={"primaria": "limitado", "inicial": "limitado"})

    preview = client.get(
        f"/api/admin/people/{person.user_id}/move",
        params={"from_organization_id": origin.org_id, "to_organization_id": target.org_id},
        headers=_auth(admin),
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["already_there"] is False
    # Mirar no cambia nada.
    assert _membership(person.user_id, origin.org_id) and not _membership(person.user_id, target.org_id)

    moved = _move(client, admin, person.user_id, origin.org_id, target.org_id)
    assert moved.status_code == 200, moved.text
    assert moved.json()["levels"] == {"inicial": "limitado", "primaria": "limitado"}
    assert not _membership(person.user_id, origin.org_id)
    assert not _levels(person.user_id, origin.org_id)
    assert [tuple(row) for row in _membership(person.user_id, target.org_id)] == [("member", "docente")]
    assert _levels(person.user_id, target.org_id) == {"primaria": "limitado", "inicial": "limitado"}
    # En las dos sedes queda en el historial.
    for org_id, action in ((origin.org_id, "admin.member_moved_out"), (target.org_id, "admin.member_moved_in")):
        assert _sql_rows("SELECT 1 FROM audit_logs WHERE organization_id = :org AND action = :action", org=org_id, action=action)


def test_si_ya_era_de_la_otra_conserva_lo_de_ahi(client):
    """El caso real: estaba en las dos sedes, con permisos distintos en cada una."""
    admin = _superadmin(client)
    origin = EchoTestUser(client, org_name="Sede Origen")
    target = EchoTestUser(client, org_name="Sede Destino")
    person = EchoTestUser(client, name="Ana Gómez")
    _join(person.user_id, origin.org_id, levels={"primaria": "limitado"})
    _join(person.user_id, target.org_id, levels={"primaria": "total", "inicial": "direccion"})

    moved = _move(client, admin, person.user_id, origin.org_id, target.org_id)
    assert moved.status_code == 200, moved.text
    assert moved.json()["already_there"] is True
    assert not _membership(person.user_id, origin.org_id)
    assert _levels(person.user_id, target.org_id) == {"primaria": "total", "inicial": "direccion"}


def test_lo_que_no_se_puede_mover(client):
    admin = _superadmin(client)
    origin = EchoTestUser(client, org_name="Sede Origen")
    target = EchoTestUser(client, org_name="Sede Destino")
    person = EchoTestUser(client, name="Ana Gómez")

    # Quien creó la sede no se toca.
    assert _move(client, admin, origin.user_id, origin.org_id, target.org_id).status_code == 400
    # No es de esa sede.
    assert _move(client, admin, person.user_id, origin.org_id, target.org_id).status_code == 404
    # Misma sede.
    _join(person.user_id, origin.org_id)
    assert _move(client, admin, person.user_id, origin.org_id, origin.org_id).status_code == 400
    # A una cuenta individual, no.
    personal = _sql_rows(
        "SELECT o.id FROM organizations o JOIN organization_members m ON m.organization_id = o.id "
        "WHERE m.user_id = :user AND o.is_personal", user=target.user_id,
    )[0][0]
    assert _move(client, admin, person.user_id, origin.org_id, str(personal)).status_code == 400
    assert _membership(person.user_id, origin.org_id)


def test_no_mueve_a_quien_esta_grabando(client):
    admin = _superadmin(client)
    origin = EchoTestUser(client, org_name="Sede Origen")
    target = EchoTestUser(client, org_name="Sede Destino")
    person = EchoTestUser(client, name="Ana Gómez")
    _join(person.user_id, origin.org_id, levels={"primaria": "limitado"})
    meeting = client.post("/api/meetings", json={"title": "En vivo"}, headers={**_auth(person), "X-Organization-Id": origin.org_id})
    assert meeting.status_code in (200, 201), meeting.text
    _sql("UPDATE meetings SET status = 'live', updated_at = now() WHERE id = :id", id=meeting.json()["id"])

    blocked = _move(client, admin, person.user_id, origin.org_id, target.org_id)
    assert blocked.status_code == 409 and "en curso" in blocked.json()["detail"]
    assert _membership(person.user_id, origin.org_id)


def _llm_says(fake_ai, **parsed):
    calls = []

    async def chat(system, messages, temperature=0.2, max_tokens=4096):
        calls.append(system)
        return json.dumps(parsed)

    fake_ai.chat = chat
    return calls


def _ask(client, user, question):
    response = client.post("/api/ask", json={"question": question}, headers=user.headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_echo_propone_y_no_mueve_hasta_confirmar(client, fake_ai):
    admin = _superadmin(client)
    origin = EchoTestUser(client, org_name="Sede Nordelta")
    target = EchoTestUser(client, org_name="Sede Puertos")
    person = EchoTestUser(client, name="Analía Oliver")
    _join(person.user_id, origin.org_id)
    _llm_says(fake_ai, move=True, person="aoliver", to="Sede Puertos")

    # "aoliver" es inicial + apellido; la sede de origen sale de dónde está.
    answer = _ask(client, admin, "podés mover a aoliver a sede puertos?")
    assert answer["move"]["user_id"] == person.user_id
    assert answer["move"]["from_id"] == origin.org_id and answer["move"]["to_id"] == target.org_id
    assert _membership(person.user_id, origin.org_id) and not _membership(person.user_id, target.org_id)

    assert _move(client, admin, person.user_id, answer["move"]["from_id"], answer["move"]["to_id"]).status_code == 200
    assert _membership(person.user_id, target.org_id) and not _membership(person.user_id, origin.org_id)


def test_echo_pregunta_cuando_hay_dudas(client, fake_ai):
    admin = _superadmin(client)
    one = EchoTestUser(client, org_name="Sede Uno")
    two = EchoTestUser(client, org_name="Sede Dos")
    three = EchoTestUser(client, org_name="Sede Tres")
    tocayo = EchoTestUser(client, name="Zulema Quiroga Primera")
    otra = EchoTestUser(client, name="Zulema Quiroga Segunda")
    _join(tocayo.user_id, one.org_id)
    _join(tocayo.user_id, two.org_id)
    _join(otra.user_id, one.org_id)

    _llm_says(fake_ai, move=True, person="Zulema Quiroga", to="Sede Tres")
    answer = _ask(client, admin, "mové a Zulema Quiroga a sede tres")
    assert answer["move"] is None
    assert {option["label"].split(" · ")[0] for option in answer["options"]} == {"Zulema Quiroga Primera", "Zulema Quiroga Segunda"}

    # Está en dos sedes y no dijo de cuál.
    _llm_says(fake_ai, move=True, person=tocayo.email, to="Sede Tres")
    answer = _ask(client, admin, f"mové a {tocayo.email} a sede tres")
    assert answer["move"] is None and {option["label"] for option in answer["options"]} == {"Sede Uno", "Sede Dos"}

    # Nadie con ese nombre.
    _llm_says(fake_ai, move=True, person="Nadie Inexistente", to="Sede Tres")
    assert "No encontré" in _ask(client, admin, "mové a Nadie Inexistente a sede tres")["answer"]
    # Un motivo por el que no se puede.
    _llm_says(fake_ai, move=True, person=three.email, **{"from": "Sede Tres"}, to="Sede Uno")
    assert "creó" in _ask(client, admin, f"mové a {three.email} de sede tres a sede uno")["answer"]


def test_echo_sigue_contestando_lo_demas(client, fake_ai):
    admin = _superadmin(client)
    EchoTestUser(client, org_name="Sede Puertos")

    # Sin verbo de mover ni sede, ni siquiera se le pregunta al modelo.
    calls = _llm_says(fake_ai, move=False)
    answer = _ask(client, admin, "¿Qué tareas siguen pendientes?")
    assert answer["move"] is None
    assert not any("mover (pasar" in system for system in calls)

    # Parece, pero el modelo dice que no: va como pregunta común.
    calls = _llm_says(fake_ai, move=False)
    answer = _ask(client, admin, "¿Qué pasó en sede puertos?")
    assert answer["move"] is None
    assert any("mover (pasar" in system for system in calls)


def test_a_nadie_mas_le_propone_mover(client, fake_ai):
    origin = EchoTestUser(client, org_name="Sede Origen")
    origin.make_paid()
    person = EchoTestUser(client, name="Ana Gómez")
    calls = _llm_says(fake_ai, move=True, person="Ana Gómez", to="Sede Origen")
    answer = _ask(client, origin, "mové a Ana Gómez a sede origen")
    assert answer["move"] is None and answer["options"] == []
    assert not any("mover (pasar" in system for system in calls)
    assert not _membership(person.user_id, origin.org_id)
