"""Aislamiento por organización: la regla más importante del sistema."""
from conftest import EchoTestUser


def test_cannot_use_foreign_org_header(client):
    user_a = EchoTestUser(client, name="Ana A", org_name="Org A")
    user_b = EchoTestUser(client, name="Beto B", org_name="Org B")

    # B intenta usar el org de A en el header → 403
    response = client.get(
        "/api/meetings",
        headers={"Authorization": f"Bearer {user_b.token}", "X-Organization-Id": user_a.org_id},
    )
    assert response.status_code == 403


def test_meetings_are_isolated(client):
    user_a = EchoTestUser(client, name="Ana A", org_name="Org A")
    user_b = EchoTestUser(client, name="Beto B", org_name="Org B")

    created = client.post(
        "/api/meetings", json={"title": "Reunión secreta de A"}, headers=user_a.headers
    )
    assert created.status_code == 201
    meeting_id = created.json()["id"]

    # B no la ve en su lista
    listing = client.get("/api/meetings", headers=user_b.headers)
    assert all(meeting["id"] != meeting_id for meeting in listing.json())

    # B no puede acceder por id (404, ni siquiera 403: no debe filtrar existencia)
    direct = client.get(f"/api/meetings/{meeting_id}", headers=user_b.headers)
    assert direct.status_code == 404

    # B no puede editarla ni finalizarla
    assert (
        client.patch(
            f"/api/meetings/{meeting_id}", json={"title": "hackeada"}, headers=user_b.headers
        ).status_code
        == 404
    )
    assert (
        client.post(f"/api/meetings/{meeting_id}/finish", headers=user_b.headers).status_code == 404
    )


def test_private_meeting_hidden_from_other_members(client):
    owner = EchoTestUser(client, name="Dueña", org_name="Org Privada")
    created = client.post(
        "/api/meetings",
        json={"title": "Privada", "visibility": "private"},
        headers=owner.headers,
    )
    meeting_id = created.json()["id"]

    # otro miembro de la MISMA org (role member) no la ve
    invite = client.post(
        "/api/org/invites",
        json={"email": "colega@test.echo", "role": "member"},
        headers=owner.headers,
    )
    token = invite.json()["token"]

    colleague = EchoTestUser.__new__(EchoTestUser)
    colleague.client = client
    response = client.post(
        "/api/auth/register",
        json={"email": "colega@test.echo", "password": "password123", "name": "Colega"},
    )
    colleague.token = response.json()["access_token"]
    accept = client.post(
        "/api/auth/invites/accept",
        json={"token": token},
        headers={"Authorization": f"Bearer {colleague.token}"},
    )
    assert accept.status_code == 200
    colleague.org_id = owner.org_id

    hidden = client.get(
        f"/api/meetings/{meeting_id}",
        headers={"Authorization": f"Bearer {colleague.token}", "X-Organization-Id": owner.org_id},
    )
    assert hidden.status_code == 404


def test_search_and_tasks_are_org_scoped(client, fake_ai):
    user_a = EchoTestUser(client, name="Ana A", org_name="Org Search A")
    user_b = EchoTestUser(client, name="Beto B", org_name="Org Search B")

    client.post(
        "/api/tasks",
        json={"text": "Tarea confidencial ALFA"},
        headers=user_a.headers,
    )
    results = client.get("/api/search?q=ALFA", headers=user_b.headers).json()
    assert results["tasks"] == []
    tasks_b = client.get("/api/tasks", headers=user_b.headers).json()
    assert all("ALFA" not in task["text"] for task in tasks_b)
