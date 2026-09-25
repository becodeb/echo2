"""Acta de entrevista: formulario completado por la IA, confirmado por quien grabó."""
import time
import uuid
from datetime import UTC, date, datetime

from conftest import EchoTestUser
from test_e2e_flow import _record_meeting

from echo_api.services import acta_entrevista

TEMPLATE = "# ACTA DE ENTREVISTA\n\n**Nombre del alumno:** {{alumno}}\n\n{{desarrollo}}\n"


def _join_as_member(client, owner: EchoTestUser) -> EchoTestUser:
    email = f"docente-{uuid.uuid4().hex[:8]}@test.echo"
    token = client.post(
        "/api/org/invites", json={"email": email, "role": "member"}, headers=owner.headers
    ).json()["token"]
    member = EchoTestUser.__new__(EchoTestUser)
    member.client = client
    registered = client.post(
        "/api/auth/register", json={"email": email, "password": "password123", "name": "Docente"}
    ).json()
    member.token = registered["access_token"]
    member.user_id = registered["user"]["id"]
    accepted = client.post(
        "/api/auth/invites/accept",
        json={"token": token},
        headers={"Authorization": f"Bearer {member.token}"},
    )
    assert accepted.status_code == 200, accepted.text
    member.org_id = owner.org_id
    # Docente de primaria con acceso total, como lo dejaría dirección.
    granted = client.put(
        "/api/org/access",
        json={"user_id": member.user_id, "level": "primaria", "access": "total"},
        headers=owner.headers,
    )
    assert granted.status_code == 200, granted.text
    return member


def _finished_meeting(client, recorder: EchoTestUser) -> str:
    meeting_id = client.post("/api/meetings", json={"title": "Entrevista"}, headers=recorder.headers).json()["id"]
    client.post(f"/api/meetings/{meeting_id}/start", headers=recorder.headers)
    _record_meeting(client, recorder, meeting_id)
    client.post(f"/api/meetings/{meeting_id}/finish", headers=recorder.headers)
    deadline = time.time() + 30
    while time.time() < deadline:
        meeting = client.get(f"/api/meetings/{meeting_id}", headers=recorder.headers).json()
        if meeting["status"] in ("completed", "failed"):
            break
        time.sleep(0.4)
    assert meeting["status"] == "completed", meeting["processing_state"]
    return meeting_id


def test_interview_acta_fields_and_confirmation_by_recorder(client, fake_ai):
    owner = EchoTestUser(client, name="Directora", org_name="Colegio Entrevistas")
    saved = client.put(
        "/api/org/minutes-template",
        json={"name": "Acta de entrevista", "body_markdown": TEMPLATE},
        headers=owner.headers,
    )
    assert saved.status_code == 200, saved.text
    recorder = _join_as_member(client, owner)
    other = _join_as_member(client, owner)

    meeting_id = _finished_meeting(client, recorder)
    minutes = client.get(f"/api/meetings/{meeting_id}/minutes", headers=recorder.headers).json()
    fields = minutes["version"]["blocks"]["fields"]
    assert fields["alumno"] == "PEREZ, Tomás"
    assert fields["solicitada_por"] == "colegio"  # normalizado
    # La fecha sale de la reunión, no de lo que diga el modelo.
    assert fields["fecha"] != "1999-01-01"
    assert "PEREZ, Tomás" in minutes["version"]["body_markdown"]
    assert minutes["can_confirm"] is True

    # Otro miembro que no grabó no puede confirmar.
    assert client.get(f"/api/meetings/{meeting_id}/minutes", headers=other.headers).json()["can_confirm"] is False
    denied = client.patch(
        f"/api/meetings/{meeting_id}/minutes/status", json={"status": "approved"}, headers=other.headers
    )
    assert denied.status_code == 403

    # Quien grabó corrige un campo y confirma, sin ser admin.
    edited = client.post(
        f"/api/meetings/{meeting_id}/minutes/versions",
        json={"fields": {**fields, "curso": "4N EP"}},
        headers=recorder.headers,
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["version"]["blocks"]["fields"]["curso"] == "4N EP"
    confirmed = client.patch(
        f"/api/meetings/{meeting_id}/minutes/status", json={"status": "approved"}, headers=recorder.headers
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "approved"


class TestCampos:
    def test_normaliza_tipos_y_valores(self):
        out = acta_entrevista.normalize_fields(
            {"alumno": " Ana ", "curso": None, "solicitada_por": "ambos", "fecha": "no-es-fecha", "extra": 1},
            date(2026, 9, 22),
        )
        assert out == {
            "alumno": "Ana", "curso": "", "motivo": "", "reunen": "", "con": "", "desarrollo": "",
            "solicitada_por": "", "fecha": "2026-09-22",
        }

    def test_fecha_en_hora_argentina(self):
        # 01:30 UTC del 23 es todavía el 22 en Argentina.
        assert acta_entrevista.meeting_date(datetime(2026, 9, 23, 1, 30, tzinfo=UTC)) == date(2026, 9, 22)

    def test_markdown_con_fecha_escrita(self):
        fields = acta_entrevista.normalize_fields({"alumno": "Ana", "fecha": "2026-03-06"}, date(2026, 1, 1))
        assert "A los 6 días del mes de marzo de 2026" in acta_entrevista.render_markdown(fields)

    def test_detecta_el_modelo_de_entrevista(self):
        assert acta_entrevista.is_interview_template(TEMPLATE)
        assert not acta_entrevista.is_interview_template("# ACTA\n{{desarrollo}}")
