"""Lista de reuniones: cada fila trae familia, alumno (solo iniciales), motivo y acta.

Y se puede filtrar por familia y por estado del acta con la lista paginada.
"""
from conftest import EchoTestUser


def _setup(client):
    owner = EchoTestUser(client, name="Dirección", org_name="Colegio lista")
    family = client.post("/api/families", json={"name": "Familia Pérez"}, headers=owner.headers).json()
    other = client.post("/api/families", json={"name": "Familia Gómez"}, headers=owner.headers).json()
    kid = client.post(
        f"/api/families/{family['id']}/members",
        json={"name": "Allegra Pérez", "relationship_type": "estudiante", "level": "primaria"},
        headers=owner.headers,
    ).json()
    reason = next(r for r in client.get("/api/org/meeting-reasons", headers=owner.headers).json() if r["name"] == "Conducta")

    def meeting(title, family_id=None, students=None):
        created = client.post("/api/meetings", json={"title": title, "level": "primaria"}, headers=owner.headers).json()
        if family_id:
            saved = client.put(
                f"/api/meetings/{created['id']}/classification",
                json={"family_id": family_id, "reason_id": reason["id"], "student_ids": students or []},
                headers=owner.headers,
            )
            assert saved.status_code == 200, saved.text
        return created["id"]

    def acta(meeting_id, status=None):
        saved = client.post(
            f"/api/meetings/{meeting_id}/minutes/versions",
            json={"body_markdown": "# ACTA\n\nTexto."},
            headers=owner.headers,
        )
        assert saved.status_code == 200, saved.text
        if status:
            changed = client.patch(
                f"/api/meetings/{meeting_id}/minutes/status", json={"status": status}, headers=owner.headers
            )
            assert changed.status_code == 200, changed.text

    return owner, family, other, kid, meeting, acta


def test_rows_say_family_student_initials_reason_and_acta(client):
    owner, family, _, kid, meeting, acta = _setup(client)
    with_kid = meeting("Con alumno", family["id"], [kid["id"]])
    meeting("Sin familia")
    acta(with_kid)

    rows = {r["title"]: r for r in client.get("/api/meetings?kind=familia", headers=owner.headers).json()}
    row = rows["Con alumno"]
    assert row["family_id"] == family["id"]
    assert row["family_name"] == "Familia Pérez"
    assert row["student_initials"] == ["A. P."]
    assert "Allegra" not in str(row)
    assert row["reason_name"] == "Conducta"
    assert row["minutes_status"] == "draft"

    bare = rows["Sin familia"]
    assert bare["family_name"] is None
    assert bare["student_initials"] == []
    assert bare["minutes_status"] is None


def test_filter_by_family_and_by_acta(client):
    owner, family, other, _, meeting, acta = _setup(client)
    approved = meeting("Aprobada", family["id"])
    acta(approved, "approved")
    pending = meeting("Por confirmar", family["id"])
    acta(pending)
    meeting("Sin acta", family["id"])
    meeting("De otra familia", other["id"])

    def titles(query):
        response = client.get(f"/api/meetings?kind=familia&{query}", headers=owner.headers)
        assert response.status_code == 200, response.text
        return {r["title"] for r in response.json()}

    assert titles(f"family_id={family['id']}") == {"Aprobada", "Por confirmar", "Sin acta"}
    assert titles(f"family_id={family['id']}&minutes=approved") == {"Aprobada"}
    assert titles(f"family_id={family['id']}&minutes=pending") == {"Por confirmar"}
    assert titles(f"family_id={family['id']}&minutes=none") == {"Sin acta"}
    assert titles(f"family_id={other['id']}") == {"De otra familia"}
    assert client.get("/api/meetings?minutes=cualquiera", headers=owner.headers).status_code == 422
