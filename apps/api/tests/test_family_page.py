"""La página de cada familia: ficha, hijos con nivel, filtro por nivel y resumen de IA.

El resumen se arma solo con reuniones que ve quien lo pide: alguien asignado a
la familia no tiene que leer, ni en el resumen, lo que pasó en una reunión
privada.
"""
import asyncio
import json
import uuid

from conftest import EchoTestUser
from sqlalchemy import update

from echo_api.db import SessionLocal
from echo_api.models import ActionItem, Meeting, MeetingSummary
from test_levels import Member


def _family(client, owner, name="Familia Pérez"):
    return client.post("/api/families", json={"name": name, "reference": "L-12"}, headers=owner.headers).json()


def _child(client, owner, family, name, level=None, curso=None):
    response = client.post(
        f"/api/families/{family['id']}/members",
        json={"name": name, "relationship_type": "estudiante", "curso": curso, "level": level},
        headers=owner.headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _meeting(client, owner, family, title, **extra):
    meeting = client.post("/api/meetings", json={"title": title, "level": "primaria", **extra}, headers=owner.headers).json()
    saved = client.put(
        f"/api/meetings/{meeting['id']}/classification", json={"family_id": family["id"]}, headers=owner.headers
    )
    assert saved.status_code == 200, saved.text
    return meeting["id"]


def _with_summary(meeting_id: str, org_id: str, points: list[str], task: str | None = None) -> None:
    async def run():
        async with SessionLocal() as db:
            db.add(
                MeetingSummary(
                    meeting_id=uuid.UUID(meeting_id), organization_id=uuid.UUID(org_id), kind="executive",
                    content={"points": points},
                )
            )
            if task:
                db.add(
                    ActionItem(
                        meeting_id=uuid.UUID(meeting_id), organization_id=uuid.UUID(org_id), text=task,
                        status="pending", source="manual",
                    )
                )
            await db.commit()

    asyncio.run(run())


def _make_private(meeting_id: str) -> None:
    async def run():
        async with SessionLocal() as db:
            await db.execute(
                update(Meeting).where(Meeting.id == uuid.UUID(meeting_id)).values(meta={"visibility": "private"})
            )
            await db.commit()

    asyncio.run(run())


class FamilyLLM:
    name = "fake"
    model = "fake-model"

    def __init__(self):
        self.prompts: list[str] = []

    async def chat(self, system, messages, temperature=0.2, max_tokens=4096):
        self.prompts.append(messages[-1]["content"])
        return json.dumps(
            {
                "overview": "La familia viene a seguimiento por conducta.",
                "working_on": ["Rutina de estudio"],
                "agreements": ["Reunión mensual (10/10)"],
                "pending": ["Mandar el informe"],
                "alerts": [],
            }
        )

    async def chat_json(self, system, messages, temperature=0.1, max_tokens=4096):
        return json.loads(await self.chat(system, messages, temperature, max_tokens))


def _fake_llm(monkeypatch) -> FamilyLLM:
    import echo_api.services.ai_settings as ai_settings
    import echo_api.services.llm as llm
    from echo_api.services.ai_settings import LLMConfig

    fake = FamilyLLM()

    async def resolve(db, org_id):
        return LLMConfig(provider="fake", model="fake-model", api_key="x")

    monkeypatch.setattr(ai_settings, "resolve_llm", resolve)
    monkeypatch.setattr(llm, "get_llm_provider", lambda *args, **kwargs: fake)
    return fake


# ── Hijos ────────────────────────────────────────────────────────


def test_children_with_level_and_one_click_change(client):
    owner = EchoTestUser(client, name="Dirección", org_name="Colegio hijos")
    family = _family(client, owner)
    child = _child(client, owner, family, "Tomás Pérez", level="primaria", curso="3N EP")
    assert (child["level"], child["curso"], child["is_guardian"]) == ("primaria", "3N EP", False)

    # Cambiar el nivel es un PATCH con el integrante entero y el nivel nuevo.
    changed = client.patch(
        f"/api/families/members/{child['id']}", json={**child, "level": "secundaria"}, headers=owner.headers
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["level"] == "secundaria"

    bad = client.patch(f"/api/families/members/{child['id']}", json={**child, "level": "jardin"}, headers=owner.headers)
    assert bad.status_code == 400

    # Un adulto no lleva curso ni nivel, y un hijo nunca cuenta como responsable.
    mother = client.post(
        f"/api/families/{family['id']}/members",
        json={"name": "Laura Pérez", "relationship_type": "madre", "level": "primaria", "curso": "3N"},
        headers=owner.headers,
    ).json()
    assert (mother["level"], mother["curso"], mother["is_guardian"]) == (None, None, True)

    detail = client.get(f"/api/families/{family['id']}", headers=owner.headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert {m["name"] for m in body["members"]} == {"Tomás Pérez", "Laura Pérez"}
    actions = [entry["action"] for entry in body["history"]]
    assert "family.member_add" in actions and "family.member_update" in actions and "family.create" in actions
    level_change = next(e for e in body["history"] if e["action"] == "family.member_update")
    assert level_change["detail"]["level"] == "secundaria"
    assert level_change["actor"] == "Dirección"

    removed = client.delete(f"/api/families/members/{child['id']}", headers=owner.headers)
    assert removed.status_code == 204
    after = client.get(f"/api/families/{family['id']}", headers=owner.headers).json()
    assert [m["name"] for m in after["members"]] == ["Laura Pérez"]


def test_edit_family_data_returns_everything(client):
    owner = EchoTestUser(client, name="Dirección", org_name="Colegio datos")
    family = _family(client, owner)
    _child(client, owner, family, "Tomás Pérez", level="primaria")
    saved = client.patch(
        f"/api/families/{family['id']}",
        json={"name": "Familia Pérez Gómez", "reference": "L-99", "notes": "Hermanos en el colegio", "drive_url": None},
        headers=owner.headers,
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert (body["name"], body["reference"], body["notes"]) == ("Familia Pérez Gómez", "L-99", "Hermanos en el colegio")
    # Antes el PATCH devolvía la familia sin profesionales ni asignadas.
    assert [m["name"] for m in body["members"]] == ["Tomás Pérez"]
    assert "assignees" in body and "professionals" in body
    history = client.get(f"/api/families/{family['id']}", headers=owner.headers).json()["history"]
    update_entry = next(e for e in history if e["action"] == "family.update")
    assert update_entry["detail"]["fields"] == ["name", "notes", "reference"]


def test_family_of_another_school_is_not_found(client):
    owner = EchoTestUser(client, name="Dirección", org_name="Colegio uno")
    other = EchoTestUser(client, name="Otra", org_name="Colegio dos")
    family = _family(client, owner)
    assert client.get(f"/api/families/{family['id']}", headers=other.headers).status_code == 404
    assert client.get(f"/api/families/{family['id']}/summary", headers=other.headers).status_code == 404


# ── Filtro por nivel ─────────────────────────────────────────────


def test_list_filters_by_level_of_children(client):
    owner = EchoTestUser(client, name="Dirección", org_name="Colegio niveles")
    both = _family(client, owner, "Familia Ayala")
    _child(client, owner, both, "Ana Ayala", level="inicial")
    _child(client, owner, both, "Beto Ayala", level="secundaria")
    primary = _family(client, owner, "Familia Bravo")
    _child(client, owner, primary, "Carla Bravo", level="primaria")
    missing = _family(client, owner, "Familia Castro")
    _child(client, owner, missing, "Dani Castro")
    _family(client, owner, "Familia Díaz")  # sin hijos cargados

    def names(level=None):
        url = "/api/families" + (f"?level={level}" if level else "")
        response = client.get(url, headers=owner.headers)
        assert response.status_code == 200, response.text
        return [f["name"] for f in response.json()]

    assert names() == ["Familia Ayala", "Familia Bravo", "Familia Castro", "Familia Díaz"]
    assert names("inicial") == ["Familia Ayala"]
    assert names("primaria") == ["Familia Bravo"]
    assert names("secundaria") == ["Familia Ayala"]
    assert names("sin") == ["Familia Castro"]
    assert client.get("/api/families?level=jardin", headers=owner.headers).status_code == 400


# ── Tareas abiertas ──────────────────────────────────────────────


def test_open_tasks_only_from_meetings_you_see(client):
    owner = EchoTestUser(client, name="Dirección", org_name="Colegio tareas")
    family = _family(client, owner)
    public_id = _meeting(client, owner, family, "Seguimiento")
    private_id = _meeting(client, owner, family, "Reservada")
    _with_summary(public_id, owner.org_id, ["Se acordó una rutina"], task="Mandar el informe")
    _with_summary(private_id, owner.org_id, ["tema reservado zeta"], task="Llamar a la terapeuta")
    _make_private(private_id)

    mine = client.get(f"/api/families/{family['id']}", headers=owner.headers).json()
    assert {t["text"] for t in mine["open_tasks"]} == {"Mandar el informe", "Llamar a la terapeuta"}

    tutor = Member(client, owner, "Tutora")
    assigned = client.put(
        f"/api/families/{family['id']}/assignees", json={"user_ids": [tutor.user_id]}, headers=owner.headers
    )
    assert assigned.status_code == 200, assigned.text
    theirs = client.get(f"/api/families/{family['id']}", headers=tutor.headers).json()
    assert [t["text"] for t in theirs["open_tasks"]] == ["Mandar el informe"]
    assert theirs["open_tasks"][0]["meeting_title"] == "Seguimiento"


# ── Resumen de IA ────────────────────────────────────────────────


def test_summary_follows_what_each_person_sees(client, monkeypatch):
    fake = _fake_llm(monkeypatch)
    owner = EchoTestUser(client, name="Dirección", org_name="Colegio resumen")
    family = _family(client, owner)
    url = f"/api/families/{family['id']}/summary"

    # Sin reuniones con algo para resumir no hay nada que generar.
    assert client.get(url, headers=owner.headers).json()["status"] == "empty"

    public_id = _meeting(client, owner, family, "Seguimiento")
    private_id = _meeting(client, owner, family, "Reservada")
    _with_summary(public_id, owner.org_id, ["Se acordó una rutina de estudio"])
    _with_summary(private_id, owner.org_id, ["tema reservado zeta"])
    _make_private(private_id)

    state = client.get(url, headers=owner.headers).json()
    assert (state["status"], state["meetings_available"], state["ai_configured"]) == ("none", 2, True)

    generated = client.post(url, headers=owner.headers)
    assert generated.status_code == 200, generated.text
    body = generated.json()
    assert body["status"] == "fresh"
    assert body["meetings_used"] == 2
    assert body["summary"]["overview"] == "La familia viene a seguimiento por conducta."
    assert body["summary"]["pending"] == ["Mandar el informe"]
    assert "tema reservado zeta" in fake.prompts[-1]

    # La tutora asignada no ve la privada: el resumen de dirección no es para ella.
    tutor = Member(client, owner, "Tutora")
    client.put(f"/api/families/{family['id']}/assignees", json={"user_ids": [tutor.user_id]}, headers=owner.headers)
    theirs = client.get(url, headers=tutor.headers).json()
    assert (theirs["status"], theirs["summary"], theirs["meetings_available"]) == ("none", None, 1)

    regenerated = client.post(url, headers=tutor.headers).json()
    assert (regenerated["status"], regenerated["meetings_used"]) == ("fresh", 1)
    assert "tema reservado zeta" not in fake.prompts[-1]
    assert "rutina de estudio" in fake.prompts[-1]

    # Dirección sigue viendo el suyo, con las dos reuniones.
    assert client.get(url, headers=owner.headers).json()["meetings_used"] == 2

    # Una reunión nueva deja el resumen viejo hasta regenerarlo.
    new_id = _meeting(client, owner, family, "Otra más")
    _with_summary(new_id, owner.org_id, ["Mejoró la asistencia"])
    stale = client.get(url, headers=owner.headers).json()
    assert (stale["status"], stale["new_meetings"]) == ("stale", 1)
    assert stale["summary"]["overview"]  # mientras tanto se sigue mostrando el anterior
    assert client.post(url, headers=owner.headers).json()["meetings_used"] == 3


def test_summary_without_ai_configured(client, monkeypatch):
    import echo_api.services.ai_settings as ai_settings

    async def nothing(db, org_id):
        return None

    monkeypatch.setattr(ai_settings, "resolve_llm", nothing)
    owner = EchoTestUser(client, name="Dirección", org_name="Colegio sin IA")
    family = _family(client, owner)
    meeting_id = _meeting(client, owner, family, "Seguimiento")
    _with_summary(meeting_id, owner.org_id, ["Algo"])
    state = client.get(f"/api/families/{family['id']}/summary", headers=owner.headers).json()
    assert (state["status"], state["ai_configured"]) == ("none", False)
    assert client.post(f"/api/families/{family['id']}/summary", headers=owner.headers).status_code == 409
