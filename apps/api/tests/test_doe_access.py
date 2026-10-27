"""DOE: cada uno ve lo suyo, lo de sus familias y donde estuvo; tareas por
rango; y tareas para gente de afuera de Echo con un link por mail.

Pedido de Bauti (26/10): que nadie vea las reuniones de los otros. Los
directivos ven todo; el DOE ("limitado") solo las reuniones en las que estuvo
y las de las familias que tiene asignadas.
"""
import uuid

from conftest import EchoTestUser
from test_levels import Member, _grant, _sql_rows


def _sede(client):
    owner = EchoTestUser(client, name="Directora", org_name=f"Sede {uuid.uuid4().hex[:4]}")
    ana = Member(client, owner, "Ana")
    beto = Member(client, owner, "Beto")
    for doe in (ana, beto):
        _grant(client, owner, doe, "primaria", "limitado")
    return owner, ana, beto


def _meeting(client, who, title: str, **extra) -> str:
    created = client.post("/api/meetings", json={"title": title, "level": "primaria", **extra}, headers=who.headers)
    assert created.status_code == 201, created.text
    # Arrancada: un borrador (nunca grabó) no aparece en la lista de los demás.
    assert client.post(f"/api/meetings/{created.json()['id']}/start", headers=who.headers).status_code == 200
    return created.json()["id"]


def _sees(client, who, meeting_id: str) -> bool:
    detail = client.get(f"/api/meetings/{meeting_id}", headers=who.headers).status_code
    listed = meeting_id in {item["id"] for item in client.get("/api/meetings", headers=who.headers).json()}
    assert (detail == 200) == listed, "el detalle y la lista no coinciden"
    return listed


def test_doe_solo_ve_las_reuniones_donde_estuvo(client):
    owner, ana, beto = _sede(client)
    meeting_id = _meeting(client, ana, "Entrevista de Ana")

    assert _sees(client, ana, meeting_id)
    assert not _sees(client, beto, meeting_id)
    assert _sees(client, owner, meeting_id)  # dirección de la sede ve todo

    # Ana marca que Beto estuvo: desde ahí la ve, y le llega el aviso.
    staffed = client.put(f"/api/meetings/{meeting_id}/staff", json={"user_ids": [beto.user_id]}, headers=ana.headers)
    assert staffed.status_code == 200, staffed.text
    assert [p["user_id"] for p in staffed.json()["participants"]] == [beto.user_id]
    assert _sees(client, beto, meeting_id)
    notes = client.get("/api/notifications", headers=beto.headers).json()["notifications"]
    assert any("te sumó" in (note["title"] or "") for note in notes)

    # Sacarlo le saca el acceso.
    client.put(f"/api/meetings/{meeting_id}/staff", json={"user_ids": []}, headers=ana.headers)
    assert not _sees(client, beto, meeting_id)


def test_quienes_estuvieron_al_crear_la_reunion(client):
    owner, ana, beto = _sede(client)
    meeting_id = _meeting(client, ana, "Con Beto", staff_ids=[beto.user_id])
    assert _sees(client, beto, meeting_id)

    # Solo personas de la sede.
    other = EchoTestUser(client, name="De otra sede")
    rejected = client.post(
        "/api/meetings", json={"title": "x", "level": "primaria", "staff_ids": [other.user_id]}, headers=ana.headers
    )
    assert rejected.status_code == 400


def test_familia_asignada_ve_todas_sus_reuniones_menos_las_privadas(client):
    owner, ana, beto = _sede(client)
    family = client.post("/api/families", json={"name": "Familia Pérez"}, headers=owner.headers).json()
    public_id = _meeting(client, ana, "Pérez abierta")
    private_id = _meeting(client, ana, "Pérez privada", visibility="private")
    for meeting_id in (public_id, private_id):
        classified = client.put(
            f"/api/meetings/{meeting_id}/classification", json={"family_id": family["id"]}, headers=ana.headers
        )
        assert classified.status_code == 200, classified.text

    # Un DOE no asigna familias: lo hacen los directivos.
    denied = client.put(f"/api/families/{family['id']}/assignees", json={"user_ids": [beto.user_id]}, headers=ana.headers)
    assert denied.status_code == 403

    assigned = client.put(
        f"/api/families/{family['id']}/assignees", json={"user_ids": [beto.user_id]}, headers=owner.headers
    )
    assert assigned.status_code == 200, assigned.text
    assert [item["name"] for item in assigned.json()] == ["Beto"]
    listed = {f["id"]: f for f in client.get("/api/families", headers=owner.headers).json()}
    assert [a["user_id"] for a in listed[family["id"]]["assignees"]] == [beto.user_id]

    assert _sees(client, beto, public_id)
    assert not _sees(client, beto, private_id)
    family_meetings = client.get(f"/api/families/{family['id']}/meetings", headers=beto.headers).json()
    assert {m["id"] for m in family_meetings} == {public_id}

    client.put(f"/api/families/{family['id']}/assignees", json={"user_ids": []}, headers=owner.headers)
    assert not _sees(client, beto, public_id)


def test_tareas_solo_a_igual_o_menor_rango(client):
    owner, ana, beto = _sede(client)
    directivo = Member(client, owner, "Vani")
    _grant(client, owner, directivo, "primaria", "total")
    meeting_id = _meeting(client, ana, "Tareas")
    task = client.post("/api/tasks", json={"text": "Llamar a la familia", "meeting_id": meeting_id}, headers=ana.headers)
    task_id = task.json()["id"]

    def assign(by, to) -> int:
        return client.patch(f"/api/tasks/{task_id}", json={"assignee_user_id": to}, headers=by.headers).status_code

    assert assign(ana, beto.user_id) == 200  # DOE → DOE
    assert assign(ana, directivo.user_id) == 403  # DOE → directivo, no
    assert assign(ana, owner.user_id) == 403  # DOE → dirección de la sede, no
    assert assign(ana, ana.user_id) == 200  # a sí misma, siempre
    assert assign(owner, beto.user_id) == 200  # dirección → DOE

    people = {p["id"]: p for p in client.get("/api/people", headers=ana.headers).json()}
    assert people[beto.user_id]["assignable"] and not people[owner.user_id]["assignable"]
    assert people[directivo.user_id]["rank_label"] == "Directivo"
    me = client.get("/api/org/access/me", headers=ana.headers).json()
    assert me["rank"] == 1


def test_tarea_para_alguien_de_afuera_con_lo_que_elija_quien_asigna(client):
    owner, ana, _ = _sede(client)
    meeting_id = _meeting(client, ana, "Con la terapeuta")
    saved = client.post(
        f"/api/meetings/{meeting_id}/minutes/versions", json={"body_markdown": "# Acta\n\nSe acordó el plan."},
        headers=ana.headers,
    )
    assert saved.status_code == 200, saved.text
    task_id = client.post(
        "/api/tasks", json={"text": "Mandar el informe", "meeting_id": meeting_id}, headers=ana.headers
    ).json()["id"]

    def assign(scope: str) -> dict:
        response = client.post(
            f"/api/tasks/{task_id}/external",
            json={"email": "Terapeuta@Afuera.com", "name": "Laura Terapeuta", "scope": scope},
            headers=ana.headers,
        )
        assert response.status_code == 201, response.text
        return response.json()

    only_task = assign("task")
    assert only_task["link"] and not only_task["mail_sent"]  # sin Resend en los tests: se copia a mano
    token = only_task["link"].rsplit("/", 1)[1]
    view = client.get(f"/api/external/{token}").json()
    assert view["task"]["text"] == "Mandar el informe" and view["assigned_by"] == "Ana"
    assert view["minutes_markdown"] is None and view["transcript"] is None

    tasks = {t["id"]: t for t in client.get("/api/tasks", headers=ana.headers).json()}
    assert tasks[task_id]["assignee_email"] == "terapeuta@afuera.com"
    assert tasks[task_id]["assignee_user_id"] is None

    # Reasignar a la misma persona con más acceso reemplaza el link anterior.
    with_acta = assign("acta")
    assert client.get(f"/api/external/{token}").status_code == 404
    token = with_acta["link"].rsplit("/", 1)[1]
    view = client.get(f"/api/external/{token}").json()
    assert "Se acordó el plan" in view["minutes_markdown"] and view["transcript"] is None

    whole = assign("meeting")
    token = whole["link"].rsplit("/", 1)[1]
    assert client.get(f"/api/external/{token}").json()["transcript"] == []

    # Marca la tarea como hecha desde el link y le avisa a quien se la asignó.
    assert client.post(f"/api/external/{token}/status", json={"status": "done"}).status_code == 200
    tasks = {t["id"]: t for t in client.get("/api/tasks", headers=ana.headers).json()}
    assert tasks[task_id]["status"] == "done"
    rows = _sql_rows("SELECT kind FROM notifications WHERE user_id = :id AND kind = 'task_done'", id=ana.user_id)
    assert rows

    listed = client.get(f"/api/tasks/{task_id}/external", headers=ana.headers).json()
    assert len(listed) == 1 and listed[0]["link"] is None  # el token no se puede volver a armar
    assert client.delete(f"/api/external-access/{listed[0]['id']}", headers=ana.headers).status_code == 204
    assert client.get(f"/api/external/{token}").status_code == 404


def test_tarea_suelta_solo_se_comparte_la_tarea(client):
    owner, ana, _ = _sede(client)
    task_id = client.post("/api/tasks", json={"text": "Suelta"}, headers=ana.headers).json()["id"]
    response = client.post(
        f"/api/tasks/{task_id}/external", json={"email": "x@afuera.com", "scope": "acta"}, headers=ana.headers
    )
    assert response.status_code == 400


def test_drive_vuelve_por_el_callback_registrado_del_login(client, monkeypatch):
    """redirect_uri_mismatch: Drive usaba /api/org/drive/callback, que no está
    registrada en Google. Ahora usa la del login y el login la deriva."""
    from echo_api.config import get_settings
    from echo_api.routers import drive

    settings = get_settings()
    monkeypatch.setattr(settings, "google_client_id", "cid")
    monkeypatch.setattr(settings, "google_client_secret", "secret")
    assert drive._callback_url() == settings.google_callback_url
    assert drive._callback_url().endswith("/api/auth/google/callback")

    # Con la cookie de estado de Drive, el callback del login lo manda al de Drive
    # (que rechaza este estado inventado y vuelve a Ajustes → Drive, no al login).
    client.cookies.set(drive.STATE_COOKIE, "estado-x", path="/api")
    response = client.get(
        "/api/auth/google/callback", params={"code": "c", "state": "estado-x"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert "/settings/drive?error=estado" in response.headers["location"]
    client.cookies.clear()
