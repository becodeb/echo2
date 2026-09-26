"""Reuniones de una familia: lo que muestra el panel de Familias.

Tiene que traer la clasificación de cada reunión (motivo, gravedad,
asistencia) y respetar la misma regla de visibilidad que el resto: alguien
con acceso limitado no ve, desde la familia, reuniones ajenas.
"""
from conftest import EchoTestUser
from test_levels import Member, _grant


def _family_with_meetings(client):
    owner = EchoTestUser(client, name="Dirección", org_name="Colegio familias")
    family = client.post("/api/families", json={"name": "Familia Pérez"}, headers=owner.headers).json()
    mother = client.post(
        f"/api/families/{family['id']}/members",
        json={"name": "Laura Pérez", "relationship_type": "madre"},
        headers=owner.headers,
    ).json()
    father = client.post(
        f"/api/families/{family['id']}/members",
        json={"name": "Juan Pérez", "relationship_type": "padre"},
        headers=owner.headers,
    ).json()
    reasons = client.get("/api/org/meeting-reasons", headers=owner.headers).json()
    conduct = next(r for r in reasons if r["name"] == "Conducta")

    ids = []
    for title, severity, attended in (
        ("Primera entrevista", "amarillo", [mother["id"]]),
        ("Seguimiento", "rojo", [mother["id"], father["id"]]),
    ):
        meeting = client.post(
            "/api/meetings", json={"title": title, "level": "primaria"}, headers=owner.headers
        ).json()
        saved = client.put(
            f"/api/meetings/{meeting['id']}/classification",
            json={
                "family_id": family["id"],
                "reason_id": conduct["id"],
                "severity": severity,
                "audience": "familia",
                "attended_member_ids": attended,
            },
            headers=owner.headers,
        )
        assert saved.status_code == 200, saved.text
        ids.append(meeting["id"])
    # Una reunión de otra familia (sin familia) no aparece.
    client.post("/api/meetings", json={"title": "Otra cosa", "level": "primaria"}, headers=owner.headers)
    return owner, family, ids, conduct


def test_family_meetings_bring_their_classification(client):
    owner, family, ids, conduct = _family_with_meetings(client)
    response = client.get(f"/api/families/{family['id']}/meetings", headers=owner.headers)
    assert response.status_code == 200, response.text
    rows = {row["title"]: row for row in response.json()}
    assert set(rows) == {"Primera entrevista", "Seguimiento"}

    first = rows["Primera entrevista"]
    assert first["severity"] == "amarillo"
    assert first["reason_id"] == conduct["id"]
    assert first["reason_name"] == "Conducta"
    assert first["audience"] == "familia"
    assert first["all_guardians_present"] is False
    assert first["attended"] == ["Laura Pérez"]

    second = rows["Seguimiento"]
    assert second["severity"] == "rojo"
    assert second["all_guardians_present"] is True
    assert sorted(second["attended"]) == ["Juan Pérez", "Laura Pérez"]


def test_family_meetings_respect_level_access(client):
    owner, family, ids, _ = _family_with_meetings(client)
    teacher = Member(client, owner, "Docente")
    _grant(client, owner, teacher, "primaria", "limitado")
    response = client.get(f"/api/families/{family['id']}/meetings", headers=teacher.headers)
    assert response.status_code == 200, response.text
    assert response.json() == []

    _grant(client, owner, teacher, "primaria", "total")
    response = client.get(f"/api/families/{family['id']}/meetings", headers=teacher.headers)
    assert {row["id"] for row in response.json()} == set(ids)


def test_family_meetings_of_another_organization_is_404(client):
    _, family, _, _ = _family_with_meetings(client)
    stranger = EchoTestUser(client, name="Otra sede", org_name="Otro colegio")
    response = client.get(f"/api/families/{family['id']}/meetings", headers=stranger.headers)
    assert response.status_code == 404
