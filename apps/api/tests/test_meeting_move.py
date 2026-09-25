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
    tasks = client.get("/api/tasks", headers=campus.headers).json()
    assert any(task["meeting_id"] == meeting_id for task in tasks)
    minutes = client.get(f"/api/meetings/{meeting_id}/minutes", headers=campus.headers).json()
    assert minutes["number"] is None  # el número era de la otra numeración

    # Regenerada en la sede, sale con el formulario de la sede y numeración nueva.
    assert client.post(f"/api/meetings/{meeting_id}/minutes/generate", headers=campus.headers).status_code == 202
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
