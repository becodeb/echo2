"""Mover una reunión a la sede correcta y rehacer el acta con su formato."""
import asyncio
import time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from conftest import TEST_DATABASE_URL, EchoTestUser
from test_acta_entrevista import TEMPLATE
from test_e2e_flow import _record_meeting


def _sql(statement: str, **params):
    async def run():
        engine = create_async_engine(TEST_DATABASE_URL)
        async with engine.begin() as connection:
            result = await connection.execute(text(statement), params)
            rows = result.all() if result.returns_rows else []
        await engine.dispose()
        return rows

    return asyncio.run(run())


def _wait(client, user, meeting_id, done):
    deadline = time.time() + 30
    while time.time() < deadline:
        value = done()
        if value:
            return value
        time.sleep(0.4)
    raise AssertionError("no terminó a tiempo")


def test_meeting_recorded_in_wrong_org_moves_and_gets_the_campus_acta(client, fake_ai):
    # Graba en una organización que se creó sola, sin estar todavía en su sede.
    stray = EchoTestUser(client, name="Mariana", org_name="Organización de Mariana")
    meeting_id = client.post("/api/meetings", json={"title": "flia prueba"}, headers=stray.headers).json()["id"]
    client.post(f"/api/meetings/{meeting_id}/start", headers=stray.headers)
    _record_meeting(client, stray, meeting_id)
    client.post(f"/api/meetings/{meeting_id}/finish", headers=stray.headers)
    _wait(client, stray, meeting_id, lambda: client.get(f"/api/meetings/{meeting_id}", headers=stray.headers).json()["status"] == "completed")
    first = client.get(f"/api/meetings/{meeting_id}/minutes", headers=stray.headers).json()
    assert first["version"]["blocks"] is None  # acta genérica
    share = client.post(f"/api/meetings/{meeting_id}/share-links", json={"role": "viewer"}, headers=stray.headers).json()

    # La sede tiene su formulario de acta de entrevista.
    campus = EchoTestUser(client, name="Dirección", org_name="Northfield Puertos")
    client.put("/api/org/minutes-template", json={"name": "Acta de entrevista", "body_markdown": TEMPLATE}, headers=campus.headers)

    admin = EchoTestUser(client, name="Superadmin", org_name="Becode")
    _sql("update users set is_superadmin = true where id = :id", id=admin.user_id)
    admin_auth = {"Authorization": f"Bearer {admin.token}"}

    # Solo superadmin puede mover.
    denied = client.post(
        f"/api/admin/meetings/{meeting_id}/move", json={"organization_id": campus.org_id}, headers={"Authorization": f"Bearer {campus.token}"}
    )
    assert denied.status_code == 404

    moved = client.post(
        f"/api/admin/meetings/{meeting_id}/move", json={"organization_id": campus.org_id, "level": "primaria"}, headers=admin_auth
    )
    assert moved.status_code == 200, moved.text

    # Ya no está en la organización vieja y sí en la sede, con todo lo suyo.
    assert client.get(f"/api/meetings/{meeting_id}", headers=stray.headers).status_code == 404
    in_campus = client.get(f"/api/meetings/{meeting_id}", headers=campus.headers).json()
    assert in_campus["level"] == "primaria"
    leftovers = _sql(
        "select count(*) from transcript_segments where meeting_id = :id and organization_id <> :org",
        id=meeting_id, org=campus.org_id,
    )
    assert leftovers[0][0] == 0
    tasks = client.get("/api/tasks", params={"status": "suggested"}, headers=campus.headers).json()
    assert any(task["meeting_id"] == meeting_id for task in tasks)
    minutes = client.get(f"/api/meetings/{meeting_id}/minutes", headers=campus.headers).json()
    assert minutes["number"] is None  # el número era de la otra numeración

    # Regenerada en la sede, sale con el formulario de la sede y el número que
    # se pone al hacerla (la numeración es de la sede nueva).
    assert client.post(f"/api/meetings/{meeting_id}/minutes/generate", json={"number": 1},
                       headers=campus.headers).status_code == 202
    regenerated = _wait(
        client, campus, meeting_id,
        lambda: (lambda m: m if m["version"]["blocks"] else None)(
            client.get(f"/api/meetings/{meeting_id}/minutes", headers=campus.headers).json()
        ),
    )
    assert regenerated["version"]["blocks"]["kind"] == "entrevista"
    assert regenerated["number"] == 1

    # El link compartido sigue andando y muestra el acta nueva.
    shared = client.get(f"/api/shared/{share['token']}").json()
    assert "PEREZ, Tomás" in shared["minutes_markdown"]


def test_moving_an_acta_whose_number_already_exists_in_the_campus(client):
    """Las dos sedes tenían su acta N.º 1: mover una no puede chocar con la otra
    (pasó al pasar reuniones de Nordelta a Puertos el 26/10)."""
    stray = EchoTestUser(client, name="Sonia", org_name="Nordelta")
    campus = EchoTestUser(client, name="Dirección", org_name="Puertos")
    moved_id = None
    for who in (stray, campus):
        meeting_id = client.post("/api/meetings", json={"title": "Con acta"}, headers=who.headers).json()["id"]
        saved = client.post(
            f"/api/meetings/{meeting_id}/minutes/versions", json={"body_markdown": "# Acta"}, headers=who.headers
        )
        assert saved.status_code == 200, saved.text
        _sql("update minutes set number = 1, number_series = 'general' where meeting_id = :id", id=meeting_id)
        moved_id = moved_id or meeting_id

    admin = EchoTestUser(client, name="Superadmin", org_name="Becode")
    _sql("update users set is_superadmin = true where id = :id", id=admin.user_id)
    moved = client.post(
        f"/api/admin/meetings/{moved_id}/move",
        json={"organization_id": campus.org_id, "level": "primaria"},
        headers={"Authorization": f"Bearer {admin.token}"},
    )
    assert moved.status_code == 200, moved.text
    assert client.get(f"/api/meetings/{moved_id}/minutes", headers=campus.headers).json()["number"] is None


def test_quien_esta_en_las_dos_sedes_cambia_su_reunion_de_sede(client):
    """Karina graba en Nordelta una reunión que era de Puertos y la pasa ella misma (27/10)."""
    from test_levels import Member, _grant

    nordelta = EchoTestUser(client, name="Dirección Nordelta", org_name="Nordelta")
    puertos = EchoTestUser(client, name="Dirección Puertos", org_name="Puertos")
    karina = Member(client, nordelta, "Karina")
    _grant(client, nordelta, karina, "primaria", "limitado")
    # La suman también a Puertos.
    invite = client.post("/api/org/invites", json={"email": _sql(
        "select email from users where id = :id", id=karina.user_id)[0][0], "role": "member"}, headers=puertos.headers).json()
    accepted = client.post("/api/auth/invites/accept", json={"token": invite["token"]}, headers={"Authorization": f"Bearer {karina.token}"})
    assert accepted.status_code == 200, accepted.text
    _grant(client, puertos, type("M", (), {"user_id": karina.user_id})(), "inicial", "limitado")
    in_puertos = {"Authorization": f"Bearer {karina.token}", "X-Organization-Id": puertos.org_id}

    meeting_id = client.post("/api/meetings", json={"title": "Era de Puertos", "level": "primaria"}, headers=karina.headers).json()["id"]
    otra = Member(client, nordelta, "Otra")
    _grant(client, nordelta, otra, "primaria", "limitado")

    def move(headers, org_id, **extra):
        return client.post(f"/api/meetings/{meeting_id}/sede", json={"organization_id": org_id, **extra}, headers=headers)

    # Grabándose no se mueve.
    client.post(f"/api/meetings/{meeting_id}/start", headers=karina.headers)
    assert move(karina.headers, puertos.org_id).status_code == 409
    _sql("update meetings set status = 'completed' where id = :id", id=meeting_id)

    # A una sede de la que no es parte, no.
    ajena = EchoTestUser(client, name="Otra escuela", org_name="Ajena")
    assert move(karina.headers, ajena.org_id).status_code == 404
    # En Puertos no tiene primaria: con ese nivel, no.
    assert move(karina.headers, puertos.org_id, level="primaria").status_code == 403

    moved = move(karina.headers, puertos.org_id)
    assert moved.status_code == 200, moved.text
    assert moved.json()["level"] == "inicial"  # el único en el que puede crear allá
    assert client.get(f"/api/meetings/{meeting_id}", headers=karina.headers).status_code == 404
    assert client.get(f"/api/meetings/{meeting_id}", headers=in_puertos).json()["level"] == "inicial"
    rows = _sql("select action from audit_logs where target_id = :id and action like 'meeting.moved%'", id=meeting_id)
    assert sorted(r[0] for r in rows) == ["meeting.moved_in", "meeting.moved_out"]
    # Quien no la grabó (y no administra) no la puede mover.
    assert client.post(
        f"/api/meetings/{meeting_id}/sede", json={"organization_id": nordelta.org_id}, headers=otra.headers
    ).status_code == 404
