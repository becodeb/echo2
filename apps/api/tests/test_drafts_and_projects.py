"""Borradores ajenos fuera de las listas, borradores abandonados que se borran
solos, y borrar proyectos (27/10)."""
import asyncio
import uuid

from conftest import EchoTestUser
from test_levels import Member, _grant, _sql

from echo_api.services.drafts import cleanup_drafts


def test_borradores_ajenos_no_aparecen_y_los_viejos_se_borran(client):
    owner = EchoTestUser(client, name="Directora", org_name=f"Sede {uuid.uuid4().hex[:4]}")
    ana = Member(client, owner, "Ana")
    _grant(client, owner, ana, "primaria", "limitado")
    draft = client.post("/api/meetings", json={"title": "Borrador de Ana", "level": "primaria"}, headers=ana.headers).json()
    started = client.post("/api/meetings", json={"title": "Grabada por Ana", "level": "primaria"}, headers=ana.headers).json()
    assert client.post(f"/api/meetings/{started['id']}/start", headers=ana.headers).status_code == 200

    def titles(who):
        return {m["title"] for m in client.get("/api/meetings", headers=who.headers).json()}

    # La directora ve todo menos el borrador ajeno; Ana ve los suyos.
    assert "Borrador de Ana" not in titles(owner) and "Grabada por Ana" in titles(owner)
    assert {"Borrador de Ana", "Grabada por Ana"} <= titles(ana)
    recent = {m["title"] for m in client.get("/api/dashboard", headers=owner.headers).json()["recent_meetings"]}
    assert "Borrador de Ana" not in recent

    # A las 24 h sin audio, el borrador se borra solo; la grabada no.
    _sql("update meetings set created_at = now() - interval '25 hours' where id in (:a, :b)", a=draft["id"], b=started["id"])
    assert asyncio.run(cleanup_drafts()) >= 1
    assert client.get(f"/api/meetings/{draft['id']}", headers=ana.headers).status_code == 404
    assert client.get(f"/api/meetings/{started['id']}", headers=ana.headers).status_code == 200


def test_borrar_un_proyecto_deja_sus_reuniones(client):
    owner = EchoTestUser(client, name="Directora", org_name=f"Sede {uuid.uuid4().hex[:4]}")
    doe = Member(client, owner, "Flor")
    _grant(client, owner, doe, "primaria", "limitado")
    project = client.post("/api/projects", json={"name": "Proyecto lectura"}, headers=owner.headers).json()
    meeting = client.post(
        "/api/meetings", json={"title": "Con proyecto", "project_id": project["id"]}, headers=owner.headers
    ).json()

    assert client.delete(f"/api/projects/{project['id']}", headers=doe.headers).status_code == 403
    assert client.delete(f"/api/projects/{project['id']}", headers=owner.headers).status_code == 204
    assert client.get("/api/projects", headers=owner.headers).json() == []
    assert client.get(f"/api/meetings/{meeting['id']}", headers=owner.headers).status_code == 200
    assert client.delete(f"/api/projects/{project['id']}", headers=owner.headers).status_code == 404
