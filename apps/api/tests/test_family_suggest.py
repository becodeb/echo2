"""Reunión que termina sin familia: Echo sugiere una por el título y avisa."""
import time

from conftest import EchoTestUser
from test_acta_entrevista import _record_meeting

from echo_api.services.family_suggest import title_name


def test_el_nombre_sale_del_titulo():
    assert title_name("Familia Cieri, Salvador · 1/11/2026") == "Cieri, Salvador"
    assert title_name("familia Goñi") == "Goñi"
    assert title_name("Flia. Pérez - 01/11") == "Pérez"
    assert title_name("Reunión 2/11/2026") is None


def _family(client, owner, name, student=None):
    family = client.post("/api/families", json={"name": name}, headers=owner.headers).json()
    if student:
        client.post(
            f"/api/families/{family['id']}/members",
            json={"name": student, "relationship_type": "estudiante", "is_guardian": False},
            headers=owner.headers,
        )
    return family


def _finished(client, owner, title):
    meeting_id = client.post("/api/meetings", json={"title": title}, headers=owner.headers).json()["id"]
    client.post(f"/api/meetings/{meeting_id}/start", headers=owner.headers)
    _record_meeting(client, owner, meeting_id)
    client.post(f"/api/meetings/{meeting_id}/finish", headers=owner.headers)
    deadline = time.time() + 30
    while time.time() < deadline:
        meeting = client.get(f"/api/meetings/{meeting_id}", headers=owner.headers).json()
        if meeting["status"] in ("completed", "failed"):
            break
        time.sleep(0.4)
    assert meeting["status"] == "completed", meeting["processing_state"]
    return meeting


def _avisos(client, owner):
    return [n for n in client.get("/api/notifications", headers=owner.headers).json()["notifications"] if n["kind"] == "family_missing"]


def test_sugiere_la_familia_del_alumno_y_se_acepta(client, fake_ai):
    owner = EchoTestUser(client, name="Directora", org_name="Colegio Sugerencias")
    cieri = _family(client, owner, "Cieri", student="Salvador Cieri")
    _family(client, owner, "Pérez")

    meeting = _finished(client, owner, "Familia Cieri, Salvador · 1/11/2026")
    suggestion = meeting["meta"]["family_suggestion"]
    assert suggestion["family_id"] == cieri["id"] and suggestion["status"] == "pending"
    assert len(suggestion["student_ids"]) == 1
    aviso = _avisos(client, owner)[0]
    assert "Cieri" in aviso["body"] and aviso["link"] == f"/meetings/{meeting['id']}"

    accepted = client.post(
        f"/api/meetings/{meeting['id']}/family-suggestion", json={"action": "accept"}, headers=owner.headers
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["family_id"] == cieri["id"]
    assert accepted.json()["student_ids"] == suggestion["student_ids"]
    again = client.post(f"/api/meetings/{meeting['id']}/family-suggestion", json={"action": "accept"}, headers=owner.headers)
    assert again.status_code == 409


def test_sin_familia_cargada_sugiere_crearla(client, fake_ai):
    owner = EchoTestUser(client, name="Directora", org_name="Colegio Crear")
    meeting = _finished(client, owner, "familia Goñi")
    assert meeting["meta"]["family_suggestion"] == {"create_name": "Familia Goñi", "status": "pending"}

    accepted = client.post(
        f"/api/meetings/{meeting['id']}/family-suggestion", json={"action": "accept"}, headers=owner.headers
    ).json()
    families = client.get("/api/families", headers=owner.headers).json()
    assert [family["name"] for family in families] == ["Familia Goñi"]
    assert accepted["family_id"] == families[0]["id"]


def test_dos_posibles_no_adivina_y_se_descarta(client, fake_ai):
    owner = EchoTestUser(client, name="Directora", org_name="Colegio Dudas")
    _family(client, owner, "Familia Ruiz")
    _family(client, owner, "Ruiz")
    meeting = _finished(client, owner, "Reunión con Ruiz")
    assert meeting["meta"]["family_suggestion"] == {"status": "pending"}
    assert _avisos(client, owner)[0]["body"].startswith("Elegí la familia")

    dismissed = client.post(
        f"/api/meetings/{meeting['id']}/family-suggestion", json={"action": "dismiss"}, headers=owner.headers
    )
    assert dismissed.status_code == 200
    detail = client.get(f"/api/meetings/{meeting['id']}", headers=owner.headers).json()
    assert detail["meta"]["family_suggestion"]["status"] == "dismissed"


def test_con_familia_elegida_no_sugiere_nada(client, fake_ai):
    owner = EchoTestUser(client, name="Directora", org_name="Colegio Con Familia")
    family = _family(client, owner, "Familia Sosa")
    meeting_id = client.post("/api/meetings", json={"title": "Familia Sosa"}, headers=owner.headers).json()["id"]
    client.put(f"/api/meetings/{meeting_id}/classification", json={"family_id": family["id"]}, headers=owner.headers)
    client.post(f"/api/meetings/{meeting_id}/start", headers=owner.headers)
    _record_meeting(client, owner, meeting_id)
    client.post(f"/api/meetings/{meeting_id}/finish", headers=owner.headers)
    deadline = time.time() + 30
    while time.time() < deadline:
        meeting = client.get(f"/api/meetings/{meeting_id}", headers=owner.headers).json()
        if meeting["status"] == "completed":
            break
        time.sleep(0.4)
    assert "family_suggestion" not in meeting["meta"]
    assert _avisos(client, owner) == []
