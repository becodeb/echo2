"""Cuentas individuales, pedidos de plan, consumo y aviso de la muestra de voz."""
import asyncio
import uuid

from conftest import EchoTestUser
from test_levels import _sql

from echo_api.config import get_settings
from echo_api.db import SessionLocal


def _register(client, email: str | None = None, name: str = "Ana Docente") -> dict:
    response = client.post(
        "/api/auth/register",
        json={"email": email or f"ana-{uuid.uuid4().hex[:8]}@test.echo", "password": "supersegura123", "name": name},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _headers(session: dict, org_id: str | None = None) -> dict:
    org_id = org_id or session["organizations"][0]["id"]
    return {"Authorization": f"Bearer {session['access_token']}", "X-Organization-Id": org_id}


def test_someone_without_a_school_gets_an_individual_account_on_the_base_plan(client):
    session = _register(client, name="Ana Docente")
    [org] = session["organizations"]
    assert org["is_personal"] is True and org["role"] == "owner"
    assert org["name"] == "Cuenta de Ana"
    billing = client.get("/api/billing/me", headers=_headers(session)).json()
    assert (billing["org_plan"], billing["user_plan"], billing["is_personal"]) == ("base", "base", True)
    assert billing["people"]["credits_left"] == 4 and billing["people"]["mode"] == "credits"
    # Cortesía no se ofrece; Instituciones sin precio ("Contact sales").
    codes = {plan["code"]: plan for plan in billing["plans"]}
    assert "cortesia" not in codes
    assert codes["institucion"]["price_usd"] is None
    assert codes["individual"]["price_usd"] == 5 and codes["individual_voz"]["price_usd"] == 10


def test_someone_from_a_school_domain_does_not_get_a_personal_account(client):
    admin = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    domain = f"colegio{uuid.uuid4().hex[:6]}.edu.ar"
    _sql("UPDATE organizations SET join_rules = CAST(:rules AS jsonb) WHERE id = :id",
         rules=f'["{domain}"]', id=admin.org_id)
    session = _register(client, email=f"maestra@{domain}")
    # Con contraseña no entra sola al colegio (hace falta Google): tampoco se le
    # inventa una cuenta individual; la pantalla le pide entrar con Google.
    assert session["organizations"] == []


def test_meeting_keeps_what_the_ai_was_asked_to_do(client):
    user = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    meeting = client.post(
        "/api/meetings", json={"title": "x", "level": "primaria", "people": True, "minors": True},
        headers=user.headers,
    ).json()
    assert meeting["meta"]["people"] is True and meeting["meta"]["minors"] is True
    plain = client.post("/api/meetings", json={"title": "y", "level": "primaria"}, headers=user.headers).json()
    assert "people" not in plain["meta"] and "minors" not in plain["meta"]


def test_asking_for_a_plan_warns_becode_without_showing_the_mail(client, monkeypatch):
    import echo_api.routers.billing as billing_module

    sent: list[tuple[str, str, str]] = []

    async def fake_mail(to, subject, body):
        sent.append((to, subject, body))
        return True

    monkeypatch.setattr(billing_module, "send_mail", fake_mail)
    admin = EchoTestUser(client, org_name="Becode")
    _sql("UPDATE users SET is_superadmin = true WHERE id = :id", id=admin.user_id)
    session = _register(client, name="Ana Docente")
    headers = _headers(session)

    assert client.post("/api/billing/requests", json={"plan": "cortesia"}, headers=headers).status_code == 422
    first = client.post("/api/billing/requests", json={"plan": "individual", "message": "Llamame a la tarde"}, headers=headers)
    assert first.status_code == 201, first.text
    again = client.post("/api/billing/requests", json={"plan": "individual"}, headers=headers)
    assert again.json()["id"] == first.json()["id"]
    assert [(to, "Ana Docente" in subject) for to, subject, _ in sent] == [("becodestudio@gmail.com", True)]
    assert "Llamame a la tarde" in sent[0][2]
    # La respuesta no trae ningún mail de Becode.
    assert "becodestudio" not in first.text

    admin_headers = {"Authorization": f"Bearer {admin.token}", "X-Organization-Id": session["organizations"][0]["id"]}
    notes = client.get("/api/notifications", headers=admin_headers).json()["notifications"]
    assert any(note["kind"] == "plan_request" and "Ana Docente" in note["title"] for note in notes)
    listed = client.get("/api/admin/plan-requests", headers=admin.headers).json()
    mine = next(item for item in listed if item["id"] == first.json()["id"])
    assert (mine["plan"], mine["status"], mine["user_name"]) == ("individual", "new", "Ana Docente")
    updated = client.put(f"/api/admin/plan-requests/{mine['id']}", json={"status": "contacted"}, headers=admin.headers)
    assert updated.json()["status"] == "contacted"
    billing = client.get("/api/billing/me", headers=headers).json()
    assert billing["requests"][0]["status"] == "contacted"


def _usage(user: EchoTestUser, **fields):
    defaults = dict(kind="stt_final", provider="elevenlabs", model="scribe_v2", unit="audio_seconds",
                    quantity=1800, cost=0.11, credits=1)
    defaults.update(fields)
    _sql(
        "INSERT INTO usage_events (id, organization_id, user_id, kind, provider, model, unit, quantity, cost_usd,"
        " credits, created_at, updated_at) VALUES (:id, :org, :user, :kind, :provider, :model, :unit, :quantity,"
        " :cost, :credits, now(), now())",
        id=str(uuid.uuid4()), org=user.org_id, user=user.user_id, **defaults,
    )


def test_usage_per_person_and_per_school(client):
    owner = EchoTestUser(client, name="Directora", org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    _usage(owner)
    _usage(owner, kind="stt_live", provider="groq", model="whisper-large-v3-turbo", quantity=1800, cost=0.02, credits=0)
    _usage(owner, kind="llm", provider="openai", model="gpt-6-luna", unit="tokens", quantity=12000, cost=0, credits=0)

    mine = client.get("/api/billing/usage", headers=owner.headers).json()
    [me] = mine["people"]
    assert me["name"] == "Directora" and me["credits"] == 1
    assert me["audio_seconds"] == 3600 and me["tokens"] == 12000
    assert round(mine["total_cost_usd"], 2) == 0.13

    # Una docente del colegio: ve lo suyo, no lo de todos.
    teacher_session = _register(client, name="Maestra")
    _sql("INSERT INTO organization_members (id, organization_id, user_id, role, created_at, updated_at)"
         " VALUES (:id, :org, :user, 'member', now(), now())",
         id=str(uuid.uuid4()), org=owner.org_id, user=teacher_session["user"]["id"])
    teacher_headers = _headers(teacher_session, owner.org_id)
    assert client.get("/api/billing/usage?scope=org", headers=teacher_headers).status_code == 403

    school = client.get("/api/billing/usage?scope=org", headers=owner.headers).json()
    names = {person["name"]: person for person in school["people"]}
    assert names["Directora"]["credits"] == 1 and names["Maestra"]["cost_usd"] == 0
    # Otro mes: vacío.
    assert client.get("/api/billing/usage?month=2020-01", headers=owner.headers).json()["total_cost_usd"] == 0
    assert client.get("/api/billing/usage?month=enero", headers=owner.headers).status_code == 422


def test_superadmin_sees_every_school_and_the_individual_plans(client):
    admin = EchoTestUser(client, org_name="Becode")
    _sql("UPDATE users SET is_superadmin = true WHERE id = :id", id=admin.user_id)
    school = EchoTestUser(client, name="Directora", org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    _usage(school, cost=0.5)
    paying = EchoTestUser(client, name="Paga Individual", org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    _sql("UPDATE users SET plan = 'individual' WHERE id = :id", id=paying.user_id)
    _usage(paying, cost=0.25)

    everything = client.get("/api/admin/usage", headers=admin.headers).json()
    by_org = {org["id"]: org for org in everything["organizations"]}
    assert by_org[school.org_id]["cost_usd"] == 0.5
    individuals = {person["name"]: person for person in everything["individuals"]}
    assert individuals["Paga Individual"]["cost_usd"] == 0.25 and "Directora" not in individuals
    assert client.get("/api/admin/usage", headers=school.headers).status_code == 404


def test_ai_tokens_are_counted_for_whoever_asked(client):
    from echo_api.services.llm.base import LLMProvider, note_usage
    from echo_api.services.privacy import protect

    user = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")

    class Counting(LLMProvider):
        name = "openai"
        model = "gpt-4o-mini"

        async def chat(self, system, messages, temperature=0.2, max_tokens=4096):
            note_usage("openai", "gpt-4o-mini", 1000, 500)
            return "ok"

    async def run():
        async with SessionLocal() as db:
            provider = await protect(db, uuid.UUID(user.org_id), Counting(), None, uuid.UUID(user.user_id))
        return await provider.chat("hola", [{"role": "user", "content": "hola"}])

    assert asyncio.run(run()) == "ok"
    [me] = client.get("/api/billing/usage", headers=user.headers).json()["people"]
    [line] = me["lines"]
    assert (line["kind"], line["model"], line["quantity"]) == ("llm", "gpt-4o-mini", 1500)
    assert line["cost_usd"] == round((1000 * 0.15 + 500 * 0.60) / 1_000_000, 6)


def test_voice_invitation_is_shown_once(client):
    session = _register(client)
    auth = {"Authorization": f"Bearer {session['access_token']}"}
    assert client.get("/api/me/voice", headers=auth).json() == {
        "has_sample": False, "duration_ms": None, "recorded_at": None, "prompt_seen": False,
        "learn_from_meetings": True, "learned_count": 0, "warning": None,
    }
    assert client.post("/api/me/voice/prompt-seen", headers=auth).status_code == 204
    assert client.get("/api/me/voice", headers=auth).json()["prompt_seen"] is True


def test_billing_says_if_people_can_be_separated(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "elevenlabs_api_key", "")
    user = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    assert client.get("/api/billing/me", headers=user.headers).json()["people"]["available"] is False


def test_superadmin_sees_plan_requests_from_any_campus(client, monkeypatch):
    import echo_api.routers.billing as billing_module

    async def no_mail(*args):
        return True

    monkeypatch.setattr(billing_module, "send_mail", no_mail)
    admin = EchoTestUser(client, org_name="Becode")
    _sql("UPDATE users SET is_superadmin = true WHERE id = :id", id=admin.user_id)
    session = _register(client, name="Pide Plan")
    assert client.post("/api/billing/requests", json={"plan": "individual"}, headers=_headers(session)).status_code == 201
    # En su propia organización, no en la de quien pidió.
    notes = client.get("/api/notifications", headers=admin.headers).json()["notifications"]
    assert any(note["kind"] == "plan_request" and "Pide Plan" in note["title"] for note in notes)


def test_a_double_click_on_subscribe_does_not_break_the_request(client):
    session = _register(client)
    headers = _headers(session)
    # Dos pedidos que quedaron iguales (como pasaba con un doble clic): el siguiente igual responde.
    for _ in range(2):
        _sql(
            "INSERT INTO plan_requests (id, user_id, plan, status, created_at, updated_at)"
            " VALUES (:id, :u, 'individual', 'new', now(), now())",
            id=str(uuid.uuid4()), u=session["user"]["id"],
        )
    again = client.post("/api/billing/requests", json={"plan": "individual"}, headers=headers)
    assert again.status_code == 201, again.text
    count = asyncio.run(_count_requests(session["user"]["id"]))
    assert count == 2


async def _count_requests(user_id: str) -> int:
    from sqlalchemy import func, select

    from echo_api.models import PlanRequest

    async with SessionLocal() as db:
        return (await db.execute(select(func.count()).where(PlanRequest.user_id == uuid.UUID(user_id)))).scalar_one()


def test_the_chat_index_is_recorded_as_usage(client):
    from echo_api.services.ai_settings import EmbeddingsConfig
    from echo_api.services.rag import embed_meeting_segments

    user = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    meeting_id = client.post("/api/meetings", json={"title": "Índice", "level": "primaria"}, headers=user.headers).json()["id"]
    _sql("INSERT INTO transcript_segments (id, meeting_id, organization_id, seq, start_ms, end_ms, text, is_final,"
         " edited, created_at, updated_at) VALUES (:id, :m, :o, 1, 0, 1000, :t, true, false, now(), now())",
         id=str(uuid.uuid4()), m=meeting_id, o=user.org_id, t="x" * 400)
    config = EmbeddingsConfig(provider="fake", model="text-embedding-3-small", api_key="x")
    assert asyncio.run(embed_meeting_segments(uuid.UUID(meeting_id), config)) == 1

    async def usage():
        from sqlalchemy import select

        from echo_api.models import UsageEvent

        async with SessionLocal() as db:
            return (await db.execute(select(UsageEvent).where(UsageEvent.meeting_id == uuid.UUID(meeting_id)))).scalars().all()

    [event] = asyncio.run(usage())
    assert (event.kind, event.unit, event.quantity, str(event.user_id)) == ("embeddings", "tokens", 100, user.user_id)


def test_usage_month_is_validated_and_the_org_panel_shows_only_members(client):
    admin = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    for bad in ("9999-12", "2026-13", "2026-9", "abc"):
        assert client.get(f"/api/billing/usage?month={bad}", headers=admin.headers).status_code == 422, bad
    visitor = EchoTestUser(client, org_name="Becode")
    for who, cost in ((admin.user_id, 0.5), (visitor.user_id, 9.0)):
        _sql("INSERT INTO usage_events (id, kind, provider, unit, quantity, cost_usd, credits, user_id, organization_id,"
             " created_at) VALUES (gen_random_uuid(), 'llm', 'openai', 'tokens', 100, :c, 0, :u, :o, now())",
             c=cost, u=who, o=admin.org_id)
    panel = client.get("/api/billing/usage?scope=org", headers=admin.headers).json()
    assert [p["user_id"] for p in panel["people"]] == [admin.user_id]
    assert panel["total_cost_usd"] == 0.5
