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


def _finished_meeting(client, recorder: EchoTestUser, level: str | None = None) -> str:
    body = {"title": "Entrevista", **({"level": level} if level else {})}
    meeting_id = client.post("/api/meetings", json=body, headers=recorder.headers).json()["id"]
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
            "solicitada_por": "", "fecha": "2026-09-22", "formato": "entrevista",
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
        assert acta_entrevista.template_format(TEMPLATE) == "entrevista"
        assert acta_entrevista.template_format(TEMPLATE_REUNION) == "reunion"


class TestActaDeReunion:
    def test_hora_valida_o_la_de_la_reunion(self):
        base = {"formato": "reunion", "fecha": "2026-10-06"}
        assert acta_entrevista.normalize_fields({**base, "hora": "9:05"}, date(2026, 1, 1))["hora"] == "09:05"
        assert acta_entrevista.normalize_fields({**base, "hora": "25:00"}, date(2026, 1, 1), "11:30")["hora"] == "11:30"
        # El acta de entrevista no lleva hora.
        assert "hora" not in acta_entrevista.normalize_fields({"hora": "10:00"}, date(2026, 1, 1))

    def test_hora_en_hora_argentina(self):
        assert acta_entrevista.meeting_time(datetime(2026, 10, 6, 14, 30, tzinfo=UTC)) == "11:30"

    def test_markdown_con_el_parrafo_y_el_cierre_del_modelo(self):
        fields = acta_entrevista.normalize_fields(
            {
                "formato": "reunion", "hora": "11:30", "fecha": "2026-10-06",
                "con": "Roxana Pérez, madre del estudiante", "reunen": "Natalia Miranda, Directora del Nivel",
                "desarrollo": "En el día de la fecha, se convoca a la familia.",
            },
            date(2026, 1, 1),
        )
        markdown = acta_entrevista.render_markdown(fields)
        assert markdown.startswith("# ACTA DE REUNIÓN")
        assert (
            "A los 6 días del mes de octubre del 2026 en la sede de la institución, siendo las 11:30 hs, "
            "se reúnen Roxana Pérez, madre del estudiante con Natalia Miranda, Directora del Nivel."
        ) in markdown
        assert markdown.rstrip().endswith("se firma el presente documento.")
        assert "Solicitada por" not in markdown


TEMPLATE_REUNION = "# ACTA DE REUNIÓN\n\nA las {{hora}} se reúnen {{con}} con {{reunen}} por {{alumno}}.\n\n{{desarrollo}}\n"

FRASE_INICIAL = "del Colegio Campo del Norte Nordelta registro de DIEGEP N° 8335 de nivel inicial"


class TestPorNivel:
    FIELDS = {
        "alumno": "R. C.", "curso": "3 F", "solicitada_por": "colegio", "motivo": "Adaptación",
        "reunen": "la docente Laura Pérez", "con": "la Sra. Ana, madre del alumno",
        "desarrollo": "Se acuerda un seguimiento.", "fecha": "2026-10-28",
    }

    def _fields(self, **extra):
        return acta_entrevista.normalize_fields({**self.FIELDS, **extra}, date(2026, 1, 1))

    def test_inicial_con_frase_sale_como_la_planilla(self):
        letterhead = {"levels": {"inicial": {"format": "entrevista", "school": FRASE_INICIAL}}}
        markdown = acta_entrevista.render_markdown(self._fields(nivel="inicial"), letterhead)
        assert "**Nombre del alumno:** R. C.   **Kinder:** 3 F" in markdown
        assert "**Solicitada por:** Escuela" in markdown
        assert (
            f"A los 28 días del mes de octubre de 2026, se reúnen la docente Laura Pérez {FRASE_INICIAL} "
            "con: la Sra. Ana, madre del alumno"
        ) in markdown
        # Como en el papel, el motivo va después del párrafo.
        assert markdown.index("A los 28") < markdown.index("**Motivo de la reunión:** Adaptación")
        assert "la institución" not in markdown

    def test_sin_configuracion_igual_que_antes(self):
        fields = self._fields()
        assert "nivel" not in fields
        expected = acta_entrevista.render_markdown(fields)
        # Un nivel sin nada cargado, o la frase de otro nivel, no cambian nada.
        assert acta_entrevista.render_markdown(self._fields(nivel="primaria"), {"levels": {}}) == expected
        assert acta_entrevista.render_markdown(
            fields, {"levels": {"inicial": {"school": FRASE_INICIAL}}}
        ) == expected
        assert "**Curso:** 3 F" in expected
        assert "**Solicitada por:** Colegio" in expected
        assert "en las instalaciones de la institución, se reúnen la docente Laura Pérez con la Sra. Ana" in expected

    def test_equipo_de_profesionales(self):
        fields = self._fields(solicitada_por="equipo")
        assert fields["solicitada_por"] == "equipo"
        assert "**Solicitada por:** Equipo de profesionales" in acta_entrevista.render_markdown(fields)

    def test_el_texto_nombra_el_lugar_de_la_sede(self):
        place = "la sede del COLEGIO CAMPO DEL NORTE NORDELTA"
        letterhead = {"interview_place": place}
        assert f"en las instalaciones de {place}, se reúnen" in acta_entrevista.render_markdown(self._fields(), letterhead)
        reunion = self._fields(formato="reunion", hora="10:00")
        assert f"en {place}, siendo las 10:00 hs" in acta_entrevista.render_markdown(reunion, letterhead)
        # La frase del nivel manda sobre el lugar de la sede.
        letterhead["levels"] = {"primaria": {"school": "la sede de primaria"}}
        assert "en la sede de primaria, siendo" in acta_entrevista.render_markdown(
            self._fields(formato="reunion", hora="10:00", nivel="primaria"), letterhead
        )

    def test_niveles_normalizados(self):
        levels = acta_entrevista.normalize_levels(
            {"inicial": {"format": "REUNION", "school": "  del  Colegio "}, "primaria": {"format": "otro"}, "x": {}}
        )
        assert levels["inicial"] == {"format": "reunion", "school": "del Colegio"}
        assert levels["primaria"] == {"format": "", "school": ""}
        assert set(levels) == {"inicial", "primaria", "secundaria"}
        assert acta_entrevista.configured_level({"levels": {"primaria": {"school": "x"}}}, "inicial") == ""
        assert acta_entrevista.configured_level({"levels": {"primaria": {"school": "x"}}}, "primaria") == "primaria"
        assert acta_entrevista.configured_level(None, "inicial") == ""


def test_acta_de_inicial_por_nivel_en_el_membrete(client, fake_ai):
    owner = EchoTestUser(client, name="Directora", org_name="Colegio Niveles")
    # El modelo de la sede es el de reunión; inicial pide la entrevista.
    saved = client.put(
        "/api/org/minutes-template",
        json={"name": "Acta de reunión", "body_markdown": TEMPLATE_REUNION},
        headers=owner.headers,
    )
    assert saved.status_code == 200, saved.text
    # Sin configurar nada el membrete devuelve los tres niveles vacíos.
    letterhead = client.get("/api/org/letterhead", headers=owner.headers).json()
    assert letterhead["levels"]["inicial"] == {"format": "", "school": ""}
    before = _finished_meeting(client, owner, "inicial")
    before_fields = client.get(f"/api/meetings/{before}/minutes", headers=owner.headers).json()["version"]["blocks"]["fields"]
    assert before_fields["formato"] == "reunion"
    assert "nivel" not in before_fields

    levels = {"inicial": {"format": "entrevista", "school": FRASE_INICIAL}}
    put = client.put(
        "/api/org/letterhead", json={**letterhead, "levels": levels}, headers=owner.headers
    )
    assert put.status_code == 200, put.text
    assert put.json()["levels"]["inicial"] == levels["inicial"]
    # Guardar el membrete sin `levels` no los borra.
    kept = client.put(
        "/api/org/letterhead", json={"institution": "Colegio Niveles"}, headers=owner.headers
    )
    assert kept.json()["levels"]["inicial"] == levels["inicial"]

    meeting_id = _finished_meeting(client, owner, "inicial")
    minutes = client.get(f"/api/meetings/{meeting_id}/minutes", headers=owner.headers).json()
    fields = minutes["version"]["blocks"]["fields"]
    assert fields["formato"] == "entrevista"
    assert fields["nivel"] == "inicial"
    assert fields["solicitada_por"] == "colegio"
    markdown = minutes["version"]["body_markdown"]
    assert "**Kinder:** 3N EP" in markdown
    assert f"se reúnen la Directora Ana {FRASE_INICIAL} con: Marcos, padre del alumno" in markdown

    # Editarla (también por la API, sin nivel en los campos) conserva el nivel y la frase.
    edited = client.post(
        f"/api/meetings/{meeting_id}/minutes/versions",
        json={"fields": {**{k: v for k, v in fields.items() if k != "nivel"}, "curso": "3 F", "solicitada_por": "equipo"}},
        headers=owner.headers,
    )
    assert edited.status_code == 200, edited.text
    version = edited.json()["version"]
    assert version["blocks"]["fields"]["nivel"] == "inicial"
    assert "**Kinder:** 3 F" in version["body_markdown"]
    assert "**Solicitada por:** Equipo de profesionales" in version["body_markdown"]


def test_reunion_acta_generada_con_hora_y_editable(client, fake_ai):
    owner = EchoTestUser(client, name="Directora", org_name="Colegio Reuniones")
    saved = client.put(
        "/api/org/minutes-template",
        json={"name": "Acta de reunión", "body_markdown": TEMPLATE_REUNION},
        headers=owner.headers,
    )
    assert saved.status_code == 200, saved.text
    meeting_id = _finished_meeting(client, owner)
    minutes = client.get(f"/api/meetings/{meeting_id}/minutes", headers=owner.headers).json()
    fields = minutes["version"]["blocks"]["fields"]
    assert fields["formato"] == "reunion"
    assert len(fields["hora"]) == 5
    assert minutes["version"]["body_markdown"].startswith("# ACTA DE REUNIÓN")

    edited = client.post(
        f"/api/meetings/{meeting_id}/minutes/versions",
        json={"fields": {**fields, "hora": "11:30"}},
        headers=owner.headers,
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["version"]["blocks"]["fields"]["hora"] == "11:30"
    assert "siendo las 11:30 hs" in edited.json()["version"]["body_markdown"]
