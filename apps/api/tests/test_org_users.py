"""Usuarios de la sede: quien la administra elige el puesto y los niveles de cada uno.

Pedido de Bauti (27/10). El puesto (DOE, docente, directivo...) se traduce a
lo que ya existía (rol de sede + acceso por nivel + grupo interno), así que
estos tests miran que un DOE o un directivo elegidos así vean solo lo suyo,
igual que si se les hubieran dado los accesos a mano.
"""
import uuid

from conftest import EchoTestUser
from test_doe_access import _meeting, _sees
from test_levels import Member, _sql, _sql_rows


def _sede(client):
    owner = EchoTestUser(client, name="Directora", org_name=f"Sede {uuid.uuid4().hex[:4]}")
    return owner, Member(client, owner, "Ana"), Member(client, owner, "Beto"), Member(client, owner, "Carla")


def _set(client, by, who, position: str, levels: list[str], expect: int = 200) -> dict:
    response = client.put(
        f"/api/org/users/{who.user_id}", json={"position": position, "levels": levels}, headers=by.headers
    )
    assert response.status_code == expect, response.text
    return response.json()


def _users(client, by) -> dict[str, dict]:
    response = client.get("/api/org/users", headers=by.headers)
    assert response.status_code == 200, response.text
    return {user["user_id"]: user for user in response.json()["users"]}


def test_doe_elegido_ve_solo_lo_suyo_y_tambien_el_directivo(client):
    owner, ana, beto, carla = _sede(client)
    doe = _set(client, owner, ana, "doe", ["primaria"])
    assert doe["position"] == "doe" and doe["role"] == "member"
    assert doe["levels"] == {"primaria": "limitado"}
    assert [group["name"] for group in doe["groups"]] == ["DOE"]
    _set(client, owner, beto, "docente", ["primaria"])
    directivo = _set(client, owner, carla, "directivo", ["primaria"])
    assert directivo["levels"] == {"primaria": "direccion"}

    de_beto = _meeting(client, beto, "Entrevista de Beto")
    de_ana = _meeting(client, ana, "Entrevista de Ana")
    secundaria = client.post("/api/meetings", json={"title": "Secundaria", "level": "secundaria"}, headers=owner.headers)
    client.post(f"/api/meetings/{secundaria.json()['id']}/start", headers=owner.headers)

    # El DOE ve lo suyo y nada de los demás.
    assert _sees(client, ana, de_ana)
    assert not _sees(client, ana, de_beto)
    # El directivo ve solo lo suyo, como el DOE: ni lo de primaria ni lo de secundaria.
    assert not _sees(client, carla, de_beto) and not _sees(client, carla, de_ana)
    assert not _sees(client, carla, secundaria.json()["id"])

    # Las tareas siguen yendo a igual o menor rango.
    task = client.post("/api/tasks", json={"text": "Llamar", "meeting_id": de_ana}, headers=ana.headers).json()
    to_carla = client.patch(f"/api/tasks/{task['id']}", json={"assignee_user_id": carla.user_id}, headers=ana.headers)
    assert to_carla.status_code == 403
    to_beto = client.patch(f"/api/tasks/{task['id']}", json={"assignee_user_id": beto.user_id}, headers=ana.headers)
    assert to_beto.status_code == 200


def test_cambiar_de_puesto_cambia_niveles_y_grupo(client):
    owner, ana, *_ = _sede(client)
    _set(client, owner, ana, "doe", ["primaria", "secundaria"])
    docente = _set(client, owner, ana, "docente", ["inicial"])
    # Se le sacan los niveles que no se eligieron y el grupo que le daba ser DOE.
    assert docente["levels"] == {"inicial": "limitado"}
    assert docente["groups"] == []

    # Un grupo al que la sumaron a mano no se toca.
    groups = client.get("/api/internal-groups", headers=owner.headers).json()["groups"]
    directivos = next(group["id"] for group in groups if group["name"] == "Directivos")
    client.put(f"/api/internal-groups/{directivos}/members/{ana.user_id}", headers=owner.headers)
    secretaria = _set(client, owner, ana, "secretaria", ["primaria"])
    assert [group["name"] for group in secretaria["groups"]] == ["Directivos"]

    # Queda en auditoría con el antes y el después.
    rows = _sql_rows(
        "SELECT detail FROM audit_logs WHERE action = 'org.position_changed' AND target_id = :id ORDER BY created_at",
        id=ana.user_id,
    )
    assert [row[0]["to"]["position"] for row in rows] == ["doe", "docente", "secretaria"]
    assert rows[1][0]["from"]["levels"] == {"primaria": "limitado", "secundaria": "limitado"}
    assert rows[1][0]["groups_removed"] == ["DOE"]


def test_la_lista_muestra_todo_y_solo_la_ve_quien_administra(client):
    owner, ana, beto, _ = _sede(client)
    _set(client, owner, ana, "doe", ["secundaria"])
    users = _users(client, owner)
    assert len(users) == 4
    assert users[owner.user_id]["position"] is None
    assert users[owner.user_id]["guessed_position"] == "direccion_sede"
    assert users[owner.user_id]["is_owner"]
    assert users[ana.user_id]["position"] == "doe"
    assert users[ana.user_id]["has_voice"] is False
    assert users[ana.user_id]["last_seen_at"] is not None  # se registró y entró
    assert users[beto.user_id]["guessed_position"] is None  # todavía no dijo su nivel

    # Un DOE o un docente no ve la lista ni cambia a nadie.
    assert client.get("/api/org/users", headers=ana.headers).status_code == 403
    _set(client, ana, beto, "directivo", ["primaria"], expect=403)


def test_nadie_se_sube_solo_ni_deja_la_sede_sin_admin(client):
    owner, ana, beto, _ = _sede(client)
    admin = _set(client, owner, ana, "direccion_sede", [])
    assert admin["role"] == "admin" and admin["levels"] == {}

    # El dueño sigue siendo Dirección de la sede.
    _set(client, ana, owner, "docente", ["primaria"], expect=400)
    # Un admin no se suma solo a un grupo nuevo (abre reuniones internas)...
    _set(client, ana, ana, "doe", ["primaria"], expect=403)
    # ...pero puede bajarse, si queda alguien que administre.
    _set(client, ana, ana, "docente", ["primaria"])
    assert client.get("/api/org/users", headers=ana.headers).status_code == 403

    # Sede sin dueño (como las que armó un superadmin): el único admin no se baja.
    _sql("UPDATE organization_members SET role = 'admin' WHERE user_id = :id", id=owner.user_id)
    _set(client, owner, owner, "docente", ["primaria"], expect=409)
    members = {m["user_id"]: m for m in client.get("/api/org/members", headers=owner.headers).json()}
    demoted = client.patch(f"/api/org/members/{members[owner.user_id]['id']}", json={"role": "member"}, headers=owner.headers)
    assert demoted.status_code == 409
    # Y un miembro no se sube a admin por la otra puerta.
    promoted = client.patch(f"/api/org/members/{members[beto.user_id]['id']}", json={"role": "admin"}, headers=beto.headers)
    assert promoted.status_code == 403


def test_puesto_sin_nivel_o_desconocido(client):
    owner, ana, *_ = _sede(client)
    _set(client, owner, ana, "doe", [], expect=400)
    _set(client, owner, ana, "rector", ["primaria"], expect=400)
    _set(client, owner, ana, "doe", ["universidad"], expect=400)


def test_puestos_adviser_y_tutor(client):
    owner, ana, beto, _ = _sede(client)
    adviser = _set(client, owner, ana, "adviser", ["primaria"])
    assert adviser["levels"] == {"primaria": "adviser"} and adviser["role"] == "member"
    tutor = _set(client, owner, beto, "tutor", ["primaria"])
    assert tutor["levels"] == {"primaria": "tutor"}
    assert [group["name"] for group in tutor["groups"]] == ["DOE"]  # igual que el DOE

    de_beto = _meeting(client, beto, "Entrevista de la tutora")
    assert _sees(client, ana, de_beto)  # la adviser ve lo que crea el tutor
    assert not _sees(client, beto, _meeting(client, ana, "De la adviser"))

    users = _users(client, owner)
    assert users[ana.user_id]["guessed_position"] == "adviser"
    assert users[beto.user_id]["guessed_position"] == "tutor"
