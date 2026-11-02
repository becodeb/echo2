"""Agenda: agendar reuniones para un día y empezarlas con todo cargado."""
from datetime import date, timedelta

from conftest import EchoTestUser
from test_levels import Member, _grant

HOY = date(2026, 11, 2)


def _family(client, owner):
    family = client.post("/api/families", json={"name": "Fernández"}, headers=owner.headers)
    assert family.status_code == 201, family.text
    family = family.json()
    student = client.post(
        f"/api/families/{family['id']}/members",
        json={"name": "Lucas Fernández", "relationship_type": "estudiante", "curso": "5B", "is_guardian": False},
        headers=owner.headers,
    )
    assert student.status_code == 201, student.text
    family["members"] = [student.json()]
    return family


def _agendar(client, who, **extra):
    body = {"date": HOY.isoformat(), **extra}
    response = client.post("/api/agenda", json=body, headers=who.headers)
    assert response.status_code == 201, response.text
    return response.json()


def _dia(client, who, scope="mine", day=HOY):
    response = client.get(
        f"/api/agenda?start={day.isoformat()}&end={day.isoformat()}&scope={scope}", headers=who.headers
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_agendar_y_ver_quien_la_ve(client):
    owner = EchoTestUser(client, name="Directora", org_name="Colegio Agenda")
    docente = Member(client, owner, "Docente")
    otra = Member(client, owner, "Otra")
    _grant(client, owner, docente, "primaria", "limitado")
    _grant(client, owner, otra, "primaria", "limitado")
    family = _family(client, owner)
    student = family["members"][0]["id"]

    item = _agendar(
        client, docente, family_id=family["id"], student_ids=[student], level="primaria",
        staff_ids=[owner.user_id], note="Traer el informe", time="",
    )
    assert item["time"] is None
    assert item["family_name"] == "Fernández"
    assert item["students"] == [{"id": student, "name": "Lucas Fernández", "curso": "5B"}]
    assert [person["name"] for person in item["staff"]] == ["Directora"]
    assert item["status"] == "agendada" and item["meeting_id"] is None

    # La ve quien la agendó y a quien sumaron; otra docente del nivel, no.
    assert [row["id"] for row in _dia(client, docente)] == [item["id"]]
    assert [row["id"] for row in _dia(client, owner)] == [item["id"]]
    assert _dia(client, otra) == []
    assert _dia(client, otra, scope="nivel") == []
    # Quien ve todo el nivel la ve con "Todo mi nivel".
    _grant(client, owner, otra, "primaria", "total")
    assert [row["id"] for row in _dia(client, otra, scope="nivel")] == [item["id"]]
    # Otro día no aparece.
    assert _dia(client, docente, day=HOY + timedelta(days=1)) == []

    # Con hora va antes que las que no tienen.
    temprano = _agendar(client, docente, time="08:30", title="Temprano")
    assert [row["id"] for row in _dia(client, docente)] == [temprano["id"], item["id"]]


def test_empezar_enlaza_la_reunion_y_pendientes(client):
    owner = EchoTestUser(client, name="Directora", org_name="Colegio Empezar")
    family = _family(client, owner)
    ayer = _agendar(client, owner, date=(HOY - timedelta(days=1)).isoformat(), family_id=family["id"])
    hoy = _agendar(client, owner, family_id=family["id"])

    # Lo de días anteriores que no se hizo queda pendiente.
    pending = client.get(f"/api/agenda/pending?today={HOY.isoformat()}", headers=owner.headers).json()
    assert [row["id"] for row in pending] == [ayer["id"]]
    moved = client.patch(f"/api/agenda/{ayer['id']}", json={"date": (HOY + timedelta(days=3)).isoformat()}, headers=owner.headers)
    assert moved.json()["date"] == (HOY + timedelta(days=3)).isoformat()
    assert client.get(f"/api/agenda/pending?today={HOY.isoformat()}", headers=owner.headers).json() == []
    skipped = client.patch(f"/api/agenda/{ayer['id']}", json={"status": "no_se_hizo"}, headers=owner.headers)
    assert skipped.json()["status"] == "no_se_hizo"

    meeting = client.post(
        "/api/meetings", json={"title": "Fernández", "scheduled_id": hoy["id"]}, headers=owner.headers
    )
    assert meeting.status_code in (200, 201), meeting.text
    linked = _dia(client, owner)[0]
    assert linked["meeting_id"] == meeting.json()["id"]
    assert linked["meeting_status"] == "draft"

    # Otra reunión con el mismo id agendado no la pisa.
    other = client.post("/api/meetings", json={"title": "Otra", "scheduled_id": hoy["id"]}, headers=owner.headers)
    assert _dia(client, owner)[0]["meeting_id"] == meeting.json()["id"] != other.json()["id"]


def test_solo_cambia_quien_corresponde(client):
    owner = EchoTestUser(client, name="Directora", org_name="Colegio Permisos")
    docente = Member(client, owner, "Docente")
    otra = Member(client, owner, "Otra")
    item = _agendar(client, docente, title="Reunión")

    body = {"date": HOY.isoformat(), "title": "Cambiada", "note": "nota"}
    assert client.put(f"/api/agenda/{item['id']}", json=body, headers=otra.headers).status_code == 403
    changed = client.put(f"/api/agenda/{item['id']}", json=body, headers=docente.headers)
    assert changed.status_code == 200 and changed.json()["title"] == "Cambiada"
    assert client.delete(f"/api/agenda/{item['id']}", headers=otra.headers).status_code == 403
    # La administración de la sede también puede.
    assert client.delete(f"/api/agenda/{item['id']}", headers=owner.headers).status_code == 204
    assert _dia(client, docente) == []

    # Interna: solo para un grupo del que se es parte.
    groups = client.get("/api/internal-groups", headers=owner.headers).json()["groups"]
    grupo = groups[0]["id"]
    denied = client.post("/api/agenda", json={"date": HOY.isoformat(), "kind": "interna", "group_id": grupo}, headers=otra.headers)
    assert denied.status_code == 403
    # Rango demasiado largo.
    far = client.get(f"/api/agenda?start={HOY.isoformat()}&end={(HOY + timedelta(days=90)).isoformat()}", headers=owner.headers)
    assert far.status_code == 422


def test_la_agenda_en_el_calendario_de_cada_uno(client):
    owner = EchoTestUser(client, name="Directora", org_name="Colegio Calendario")
    docente = Member(client, owner, "Docente")
    family = _family(client, owner)
    manana = date.today() + timedelta(days=1)
    _agendar(
        client, docente, date=manana.isoformat(), time="10:30", family_id=family["id"],
        student_ids=[family["members"][0]["id"]], note="Traer el informe; y la carpeta",
    )
    sin_hora = _agendar(client, docente, date=manana.isoformat(), title="Familia Pérez")
    descartada = _agendar(client, docente, date=manana.isoformat(), title="No va")
    client.patch(f"/api/agenda/{descartada['id']}", json={"status": "no_se_hizo"}, headers=docente.headers)
    _agendar(client, owner, date=manana.isoformat(), title="De la directora")

    assert client.get("/api/agenda/calendar", headers=docente.headers).json() == {"path": None}
    path = client.post("/api/agenda/calendar", headers=docente.headers).json()["path"]
    assert path.startswith("/api/agenda/feed/") and path.endswith(".ics")
    assert client.get("/api/agenda/calendar", headers=docente.headers).json()["path"] == path

    # Sin sesión: el enlace es la llave. Trae lo suyo, no lo de la directora ni lo descartado.
    feed = client.get(path)
    assert feed.status_code == 200, feed.text
    assert feed.headers["content-type"].startswith("text/calendar")
    text = feed.text.replace("\r\n ", "")
    assert text.count("BEGIN:VEVENT") == 2
    assert f"DTSTART;TZID=America/Argentina/Buenos_Aires:{manana:%Y%m%d}T103000" in text
    assert f"DTEND;TZID=America/Argentina/Buenos_Aires:{manana:%Y%m%d}T111500" in text
    assert "SUMMARY:Fernández" in text and r"Lucas Fernández\, 5B" in text
    assert r"Traer el informe\; y la carpeta" in text
    assert f"UID:{sin_hora['id']}@echo" in text and f"DTSTART;VALUE=DATE:{manana:%Y%m%d}" in text
    assert "De la directora" not in text and "No va" not in text
    assert all(len(line.encode()) <= 75 for line in feed.text.split("\r\n"))

    # Un enlace nuevo corta el anterior; desconectar corta todo.
    nuevo = client.post("/api/agenda/calendar", headers=docente.headers).json()["path"]
    assert nuevo != path
    assert client.get(path).status_code == 404
    assert client.get(nuevo).status_code == 200
    client.delete("/api/agenda/calendar", headers=docente.headers)
    assert client.get(nuevo).status_code == 404
    assert client.get("/api/agenda/feed/" + "0" * 64 + ".ics").status_code == 404
    assert client.get("/api/agenda/feed/nada.ics").status_code == 404
