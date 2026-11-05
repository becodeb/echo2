"""Panel de Becode: todos los usuarios, editar sus permisos, y los popups de opinión."""
from conftest import EchoTestUser
from test_levels import _sql, _sql_rows


def _superadmin(client) -> EchoTestUser:
    admin = EchoTestUser(client, name="Becode", org_name="Sede Becode")
    _sql("UPDATE users SET is_superadmin = true WHERE id = :id", id=admin.user_id)
    return admin


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {user.token}"}


def _in_org(user, org_id: str) -> dict:
    return {**_auth(user), "X-Organization-Id": org_id}


def _old_account(user) -> None:
    _sql("UPDATE users SET created_at = now() - interval '30 days' WHERE id = :id", id=user.user_id)


def _person(client, admin, user_id: str) -> dict:
    response = client.get("/api/admin/people", headers=_auth(admin))
    assert response.status_code == 200, response.text
    return next(row for row in response.json() if row["id"] == user_id)


def test_solo_el_superadmin_ve_a_todos(client):
    person = EchoTestUser(client)
    for path in ("/api/admin/people", "/api/admin/feedback"):
        assert client.get(path, headers=_auth(person)).status_code == 404
    assert client.post(
        f"/api/admin/people/{person.user_id}/memberships",
        json={"organization_id": person.org_id},
        headers=_auth(person),
    ).status_code == 404
    assert client.put(
        "/api/admin/feedback/prompts/stars", json={"enabled": True}, headers=_auth(person)
    ).status_code == 404


def test_lista_a_todos_con_sus_sedes_puesto_y_niveles(client):
    admin = _superadmin(client)
    owner = EchoTestUser(client, name="Dueña", org_name="Sede Uno")
    other = EchoTestUser(client, name="Otra", org_name="Sede Dos")

    row = _person(client, admin, owner.user_id)
    assert row["email"] == owner.email
    # Al registrarse cada uno tiene además su cuenta individual; esa viene marcada.
    membership = next(m for m in row["memberships"] if m["organization_id"] == owner.org_id)
    assert membership["organization"] == "Sede Uno" and membership["is_personal"] is False
    assert any(m["is_personal"] for m in row["memberships"])
    assert membership["role"] == "owner"
    # Nadie le eligió el puesto: se muestra el que parece.
    assert membership["guessed"] is True and membership["position"] == "Dirección de la sede"
    assert other.org_id in {m["organization_id"] for m in _person(client, admin, other.user_id)["memberships"]}


def test_suma_a_una_sede_y_edita_con_las_reglas_de_la_sede(client):
    admin = _superadmin(client)
    owner = EchoTestUser(client, name="Dueña", org_name="Sede Reglas")
    person = EchoTestUser(client, name="Docente", org_name="Otra Sede")

    add = client.post(
        f"/api/admin/people/{person.user_id}/memberships",
        json={"organization_id": owner.org_id},
        headers=_auth(admin),
    )
    assert add.status_code == 201, add.text
    member_id = add.json()["member_id"]
    assert client.post(
        f"/api/admin/people/{person.user_id}/memberships",
        json={"organization_id": owner.org_id},
        headers=_auth(admin),
    ).status_code == 409
    logged = _sql_rows(
        "SELECT actor_id::text FROM audit_logs WHERE action = 'admin.member_added' AND organization_id = :o",
        o=owner.org_id,
    )
    assert logged == [(admin.user_id,)]

    # Puesto y niveles, por la misma API de la sede.
    headers = _in_org(admin, owner.org_id)
    assert client.put(
        f"/api/org/users/{person.user_id}", json={"position": "doe", "levels": ["primaria"]}, headers=headers
    ).status_code == 200
    membership = next(
        m for m in _person(client, admin, person.user_id)["memberships"] if m["organization_id"] == owner.org_id
    )
    assert membership["position"] == "DOE" and membership["guessed"] is False
    assert membership["levels"] == {"primaria": "limitado"}

    # Rol de sede.
    assert client.patch(f"/api/org/members/{member_id}", json={"role": "viewer"}, headers=headers).status_code == 200

    # A quien creó la sede no se le baja el puesto ni se lo saca.
    assert client.put(
        f"/api/org/users/{owner.user_id}", json={"position": "doe", "levels": ["primaria"]}, headers=headers
    ).status_code == 400
    owner_member = next(
        m for m in _person(client, admin, owner.user_id)["memberships"] if m["organization_id"] == owner.org_id
    )
    assert client.delete(f"/api/org/members/{owner_member['member_id']}", headers=headers).status_code == 400

    # Sacarlo de la sede.
    assert client.delete(f"/api/org/members/{member_id}", headers=headers).status_code == 204
    orgs = {m["organization_id"] for m in _person(client, admin, person.user_id)["memberships"]}
    assert owner.org_id not in orgs and person.org_id in orgs


def test_no_suma_a_una_cuenta_individual(client):
    admin = _superadmin(client)
    person = EchoTestUser(client)
    _sql("UPDATE organizations SET is_personal = true WHERE id = :id", id=person.org_id)
    other = EchoTestUser(client)
    assert client.post(
        f"/api/admin/people/{other.user_id}/memberships",
        json={"organization_id": person.org_id},
        headers=_auth(admin),
    ).status_code == 400


def _enable(client, admin, kind: str, **extra) -> dict:
    response = client.put(
        f"/api/admin/feedback/prompts/{kind}", json={"enabled": True, **extra}, headers=_auth(admin)
    )
    assert response.status_code == 200, response.text
    return response.json()


def _prompt(client, user) -> dict | None:
    response = client.get("/api/feedback/prompt", headers=_auth(user))
    assert response.status_code == 200, response.text
    return response.json()


def _clear_prompts() -> None:
    _sql("DELETE FROM feedback_prompts")


def test_los_popups_arrancan_apagados_y_se_prenden_desde_el_panel(client):
    _clear_prompts()
    admin = _superadmin(client)
    person = EchoTestUser(client)
    _old_account(person)
    assert _prompt(client, person) is None

    overview = client.get("/api/admin/feedback", headers=_auth(admin)).json()
    assert [(p["kind"], p["enabled"]) for p in overview["prompts"]] == [("stars", False), ("suggestion", False)]

    _enable(client, admin, "stars")
    prompt = _prompt(client, person)
    assert prompt["kind"] == "stars" and prompt["title"] == "Queremos saber tu opinión"

    # Una cuenta recién creada todavía no.
    assert _prompt(client, EchoTestUser(client)) is None

    edited = client.put(
        "/api/admin/feedback/prompts/stars", json={"question": "¿Qué tal?", "enabled": False}, headers=_auth(admin)
    ).json()
    assert edited["question"] == "¿Qué tal?" and edited["enabled"] is False
    assert _prompt(client, person) is None
    _clear_prompts()


def test_responder_o_decir_ahora_no_frena_la_proxima_pregunta(client):
    _clear_prompts()
    admin = _superadmin(client)
    _enable(client, admin, "stars", every_days=30)
    _enable(client, admin, "suggestion", every_days=30)

    person = EchoTestUser(client, name="Responde", org_name="Sede Opinión")
    _old_account(person)
    assert _prompt(client, person)["kind"] == "stars"

    response = client.post(
        "/api/feedback", json={"kind": "stars", "stars": 4, "text": "  Muy útil  "}, headers=person.headers
    )
    assert response.status_code == 201, response.text
    # Nunca dos popups seguidos, aunque el otro esté pendiente.
    assert _prompt(client, person) is None

    # Pasada la semana, viene el otro.
    _sql("UPDATE feedback_responses SET created_at = now() - interval '8 days' WHERE user_id = :id", id=person.user_id)
    assert _prompt(client, person)["kind"] == "suggestion"

    assert client.post("/api/feedback/dismiss", json={"kind": "suggestion"}, headers=_auth(person)).status_code == 204
    assert _prompt(client, person) is None

    # Vencido el plazo de cada uno, se vuelve a preguntar.
    _sql("UPDATE feedback_responses SET created_at = now() - interval '31 days' WHERE user_id = :id", id=person.user_id)
    assert _prompt(client, person)["kind"] == "stars"

    overview = client.get("/api/admin/feedback", headers=_auth(admin)).json()
    mine = [row for row in overview["responses"] if row["user_email"] == person.email]
    # El "Ahora no" no es una respuesta.
    assert len(mine) == 1
    assert mine[0]["stars"] == 4 and mine[0]["text"] == "Muy útil"
    assert mine[0]["organization"] == "Sede Opinión" and mine[0]["user_name"] == "Responde"
    assert overview["distribution"][3] >= 1 and overview["dismissed"] >= 1
    _clear_prompts()


def test_valida_lo_que_se_responde(client):
    person = EchoTestUser(client)
    post = lambda **body: client.post("/api/feedback", json=body, headers=person.headers)  # noqa: E731
    assert post(kind="stars").status_code == 400
    assert post(kind="stars", stars=0).status_code == 422
    assert post(kind="stars", stars=6).status_code == 422
    assert post(kind="suggestion").status_code == 400
    assert post(kind="suggestion", text="   ").status_code == 400
    assert post(kind="suggestion", text="x" * 2001).status_code == 422
    assert post(kind="otra", stars=3).status_code == 422
    assert post(kind="suggestion", text="Que el acta salga más rápido").status_code == 201

    # Una sede ajena en el header no queda anotada.
    other = EchoTestUser(client)
    assert client.post(
        "/api/feedback",
        json={"kind": "suggestion", "text": "Otra"},
        headers=_in_org(person, other.org_id),
    ).status_code == 201
    rows = _sql_rows(
        "SELECT organization_id::text FROM feedback_responses WHERE user_id = :id ORDER BY created_at",
        id=person.user_id,
    )
    assert rows == [(person.org_id,), (None,)]


def test_el_promedio_y_la_distribucion(client):
    _sql("DELETE FROM feedback_responses")
    admin = _superadmin(client)
    empty = client.get("/api/admin/feedback", headers=_auth(admin)).json()
    assert empty["average"] is None and empty["distribution"] == [0, 0, 0, 0, 0]

    person = EchoTestUser(client)
    for stars in (5, 5, 2):
        client.post("/api/feedback", json={"kind": "stars", "stars": stars}, headers=person.headers)
    client.post("/api/feedback", json={"kind": "suggestion", "text": "Algo"}, headers=person.headers)
    overview = client.get("/api/admin/feedback", headers=_auth(admin)).json()
    assert overview["distribution"] == [0, 1, 0, 0, 2]
    assert overview["average"] == 4.0
    assert overview["suggestions"] == 1
