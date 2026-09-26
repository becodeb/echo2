"""Reuniones internas por grupo y grabación del audio completo.

Una reunión interna la ve su grupo, quien la creó y a quien se la compartan.
Ser admin u owner de la sede NO alcanza: ese es el punto de separarlas de las
reuniones con familias. La grabación queda de paso en el servidor y se borra.
"""
import asyncio
import json
import uuid

from conftest import EchoTestUser
from test_levels import Member

from echo_api.services import recording as rec


def _groups(client, user):
    response = client.get("/api/internal-groups", headers=user.headers)
    assert response.status_code == 200, response.text
    return response.json()


def _group_id(client, user, name="Directivos"):
    return next(group["id"] for group in _groups(client, user)["groups"] if group["name"] == name)


def _join(client, admin, group_id, user_id):
    response = client.put(f"/api/internal-groups/{group_id}/members/{user_id}", headers=admin.headers)
    assert response.status_code == 204, response.text


def _school_with_internal_meeting(client):
    owner = EchoTestUser(client, name="Secretaria Admin", org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    director = Member(client, owner, "Director")
    directivos = _group_id(client, owner)
    _join(client, owner, directivos, director.user_id)
    created = client.post(
        "/api/meetings",
        json={"title": "Directivos: IA en el aula", "kind": "interna", "group_id": directivos},
        headers=director.headers,
    )
    assert created.status_code == 201, created.text
    return owner, director, directivos, created.json()


def test_default_groups_exist_and_admin_can_manage(client):
    owner = EchoTestUser(client, org_name="Colegio grupos")
    data = _groups(client, owner)
    assert data["can_manage"] is True
    assert {group["name"] for group in data["groups"]} == {"Directivos", "Coordinadores"}


def test_internal_meeting_is_visible_only_to_its_group(client):
    owner, director, directivos, meeting = _school_with_internal_meeting(client)
    assert meeting["kind"] == "interna"
    assert meeting["level"] is None
    assert meeting["group_name"] == "Directivos"

    # El director (del grupo) la ve en la lista interna y en el detalle.
    listed = client.get("/api/meetings?kind=interna", headers=director.headers).json()
    assert [item["id"] for item in listed] == [meeting["id"]]
    assert client.get(f"/api/meetings/{meeting['id']}", headers=director.headers).status_code == 200

    # La admin de la sede no: no es del grupo.
    assert client.get("/api/meetings", headers=owner.headers).json() == []
    assert client.get(f"/api/meetings/{meeting['id']}", headers=owner.headers).status_code == 404

    # Un docente con acceso total a primaria tampoco.
    teacher = Member(client, owner, "Docente")
    client.put(
        "/api/org/access", json={"user_id": teacher.user_id, "level": "primaria", "access": "total"},
        headers=owner.headers,
    )
    assert client.get(f"/api/meetings/{meeting['id']}", headers=teacher.headers).status_code == 404

    # Si la admin se suma al grupo, la ve.
    _join(client, owner, directivos, owner.user_id)
    assert client.get(f"/api/meetings/{meeting['id']}", headers=owner.headers).status_code == 200


def test_family_meetings_list_does_not_mix_internal(client):
    owner, director, _, internal = _school_with_internal_meeting(client)
    client.put(
        "/api/org/access", json={"user_id": director.user_id, "level": "primaria", "access": "limitado"},
        headers=owner.headers,
    )
    family = client.post(
        "/api/meetings", json={"title": "Familia Gómez", "level": "primaria"}, headers=director.headers
    )
    assert family.status_code == 201, family.text
    family_ids = [item["id"] for item in client.get("/api/meetings?kind=familia", headers=director.headers).json()]
    assert family_ids == [family.json()["id"]]


def test_only_group_members_create_internal_meetings(client):
    owner = EchoTestUser(client, org_name="Colegio alta")
    directivos = _group_id(client, owner)
    response = client.post(
        "/api/meetings", json={"title": "x", "kind": "interna", "group_id": directivos}, headers=owner.headers
    )
    assert response.status_code == 403
    response = client.post("/api/meetings", json={"title": "x", "kind": "interna"}, headers=owner.headers)
    assert response.status_code == 400


def test_member_without_direction_cannot_manage_groups(client):
    owner = EchoTestUser(client, org_name="Colegio permisos")
    teacher = Member(client, owner, "Docente")
    directivos = _group_id(client, owner)
    assert _groups(client, teacher)["can_manage"] is False
    response = client.put(f"/api/internal-groups/{directivos}/members/{teacher.user_id}", headers=teacher.headers)
    assert response.status_code == 403


def test_recording_is_written_while_live_and_left_for_download(client):
    owner, director, _, meeting = _school_with_internal_meeting(client)
    meeting_id = meeting["id"]
    enabled = client.put(f"/api/meetings/{meeting_id}/recording", json={"enabled": True}, headers=director.headers)
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["status"] == "pending"

    # El navegador en modo bridge: manda audio solo para grabar.
    second_of_audio = bytes(3200) * 10
    with client.websocket_connect(f"/api/meetings/{meeting_id}/ws?token={director.token}") as websocket:
        websocket.send_text(json.dumps({"type": "hello", "role": "recorder", "sample_rate": 16000, "transcribe": False}))
        assert json.loads(websocket.receive_text())["type"] == "hello_ack"
        websocket.send_bytes(second_of_audio)
        websocket.send_text(json.dumps({"type": "ping"}))
        assert json.loads(websocket.receive_text())["type"] == "pong"
    assert rec.pcm_path(uuid.UUID(meeting_id)).stat().st_size == len(second_of_audio)

    # Sin Drive conectado queda como mp3 para descargar, y el PCM se borra.
    asyncio.run(rec.finalize_recording(uuid.UUID(meeting_id)))
    state = client.get(f"/api/meetings/{meeting_id}", headers=director.headers).json()["recording"]
    assert state["status"] == "download"
    assert state["expires_at"]
    assert state["duration_seconds"] == 1
    assert not rec.pcm_path(uuid.UUID(meeting_id)).exists()

    downloaded = client.get(f"/api/meetings/{meeting_id}/recording/file", headers=director.headers)
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"] == "audio/mpeg"
    # Quien no ve la reunión tampoco baja el audio.
    assert client.get(f"/api/meetings/{meeting_id}/recording/file", headers=owner.headers).status_code == 404

    # Mandarlo a Drive sin Drive conectado se rechaza y no borra el archivo.
    assert client.post(f"/api/meetings/{meeting_id}/recording/drive", headers=director.headers).status_code == 409
    assert rec.mp3_path(uuid.UUID(meeting_id)).exists()

    discarded = client.delete(f"/api/meetings/{meeting_id}/recording/file", headers=director.headers)
    assert discarded.json()["status"] == "discarded"
    assert client.get(f"/api/meetings/{meeting_id}/recording/file", headers=director.headers).status_code == 404


def test_expired_recordings_are_cleaned(client):
    _, director, _, meeting = _school_with_internal_meeting(client)
    meeting_id = uuid.UUID(meeting["id"])
    client.put(f"/api/meetings/{meeting_id}/recording", json={"enabled": True}, headers=director.headers)
    rec.mp3_path(meeting_id).write_bytes(b"ID3")
    asyncio.run(rec.update_state(meeting_id, status="download", expires_at="2000-01-01T00:00:00+00:00"))
    assert asyncio.run(rec.cleanup_recordings()) >= 1
    assert not rec.mp3_path(meeting_id).exists()
    state = client.get(f"/api/meetings/{meeting_id}", headers=director.headers).json()["recording"]
    assert state["status"] == "expired"


def test_without_recording_nothing_is_written(client):
    _, director, _, meeting = _school_with_internal_meeting(client)
    with client.websocket_connect(f"/api/meetings/{meeting['id']}/ws?token={director.token}") as websocket:
        websocket.send_text(json.dumps({"type": "hello", "role": "recorder", "sample_rate": 16000, "transcribe": False}))
        websocket.receive_text()
        websocket.send_bytes(bytes(3200))
        websocket.send_text(json.dumps({"type": "ping"}))
        websocket.receive_text()
    assert not rec.pcm_path(uuid.UUID(meeting["id"])).exists()
