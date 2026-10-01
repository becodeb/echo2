"""Planes, créditos y consumo (docs/plan-transcripcion-y-planes.md, §5)."""
import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

from conftest import EchoTestUser
from test_levels import _sql
from test_speakers import _silence, _tone

from echo_api.config import get_settings
from echo_api.db import SessionLocal
from echo_api.models import Meeting, Organization, UsageEvent, User
from echo_api.services import plans
from echo_api.services import recording as rec


def _run(coro):
    return asyncio.run(coro)


def _meeting(client, user: EchoTestUser, **meta) -> uuid.UUID:
    meeting = client.post("/api/meetings", json={"title": "x", "level": "primaria"}, headers=user.headers).json()
    meeting_id = uuid.UUID(meeting["id"])
    if meta:
        _sql("UPDATE meetings SET meta = CAST(:meta AS jsonb) WHERE id = :id", meta=json.dumps(meta), id=str(meeting_id))
    return meeting_id


def _spend_credits(user: EchoTestUser, credits: int, when: datetime | None = None) -> None:
    _sql(
        "INSERT INTO usage_events (id, organization_id, user_id, kind, provider, model, unit, quantity, cost_usd,"
        " credits, meta, created_at, updated_at) VALUES (:id, :org, :user, 'stt_final', 'elevenlabs', 'scribe_v2',"
        " 'audio_seconds', 1800, 0.11, :credits, '{\"covered_by\": \"credits\"}', :when, :when)",
        id=str(uuid.uuid4()), org=user.org_id, user=user.user_id, credits=credits, when=when or datetime.now(UTC),
    )


async def _access(user: EchoTestUser):
    async with SessionLocal() as db:
        org = await db.get(Organization, uuid.UUID(user.org_id))
        person = await db.get(User, uuid.UUID(user.user_id))
        return await plans.people_access(db, org, person)


async def _final_pass(meeting_id: uuid.UUID, seconds: float):
    async with SessionLocal() as db:
        meeting = await db.get(Meeting, meeting_id)
        return await plans.final_pass_for(db, meeting, seconds)


def test_a_meeting_costs_one_credit_per_started_hour():
    assert plans.credits_for(0) == 1
    assert plans.credits_for(30 * 60) == 1
    assert plans.credits_for(3600) == 1
    assert plans.credits_for(61 * 60) == 2
    assert plans.credits_for(3 * 3600) == 3


def test_base_plan_has_four_credits_a_month_per_teacher(client):
    user = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    access = _run(_access(user))
    assert (access.mode, access.source, access.credits_per_month, access.credits_left) == ("credits", "credits", 4, 4)

    # Lo gastado el mes pasado no cuenta: se renuevan, no se acumulan.
    _spend_credits(user, 3, datetime.now(UTC) - timedelta(days=40))
    _spend_credits(user, 3)
    access = _run(_access(user))
    assert (access.credits_used, access.credits_left) == (3, 1)

    _spend_credits(user, 1)
    assert _run(_access(user)).mode == "none"


def test_final_pass_follows_the_plan(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "elevenlabs_api_key", "xi-test")
    user = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")

    # Base sin pedir "quién habló": no gasta nada, solo texto con Groq.
    plain = _run(_final_pass(_meeting(client, user), 1800))
    assert (plain.provider, plain.credits, plain.reason) == ("groq", 0, "not_requested")

    # Base pidiéndolo: ElevenLabs, y una reunión de 70 min gasta 2 créditos.
    people = _run(_final_pass(_meeting(client, user, people=True), 70 * 60))
    assert (people.provider, people.credits, people.covered_by) == ("elevenlabs", 2, "credits")

    # Con menores nunca va a ElevenLabs, aunque el colegio pague.
    _sql("UPDATE organizations SET plan = 'institucion' WHERE id = :id", id=user.org_id)
    minors = _run(_final_pass(_meeting(client, user, people=True, minors=True), 600))
    assert (minors.provider, minors.reason) == ("groq", "minors")

    # Institución: siempre con personas, sin créditos.
    school = _run(_final_pass(_meeting(client, user), 600))
    assert (school.provider, school.credits, school.covered_by) == ("elevenlabs", 0, "organization")


def test_without_elevenlabs_key_there_is_no_people_pass(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "elevenlabs_api_key", "")
    user = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    result = _run(_final_pass(_meeting(client, user, people=True), 600))
    assert (result.provider, result.reason) == ("groq", "no_provider")


def test_last_credit_covers_a_long_meeting(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "elevenlabs_api_key", "xi-test")
    user = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    _spend_credits(user, 3)
    result = _run(_final_pass(_meeting(client, user, people=True), 2 * 3600 + 60))
    assert (result.provider, result.credits) == ("elevenlabs", 1)
    _spend_credits(user, 1)
    empty = _run(_final_pass(_meeting(client, user, people=True), 600))
    assert (empty.provider, empty.reason) == ("groq", "no_credits")


def test_individual_plan_has_its_hours_and_then_uses_credits(client):
    user = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    _sql("UPDATE users SET plan = 'individual' WHERE id = :id", id=user.user_id)
    access = _run(_access(user))
    assert (access.mode, access.source, access.people_hours_left) == ("always", "individual", 5.0)

    _sql(
        "INSERT INTO usage_events (id, organization_id, user_id, kind, provider, unit, quantity, cost_usd, credits,"
        " meta, created_at, updated_at) VALUES (:id, :org, :user, 'stt_final', 'elevenlabs', 'audio_seconds', 18000,"
        " 1.1, 0, '{\"covered_by\": \"individual\"}', now(), now())",
        id=str(uuid.uuid4()), org=user.org_id, user=user.user_id,
    )
    after = _run(_access(user))
    assert (after.mode, after.source, after.credits_left) == ("credits", "credits", 4)


def test_superadmin_sets_plans_and_limits(client):
    admin = EchoTestUser(client, org_name=f"Becode {uuid.uuid4().hex[:4]}")
    school = EchoTestUser(client, org_name=f"Northfield {uuid.uuid4().hex[:4]}")
    # Para quien no es superadmin el panel no existe.
    assert client.put(f"/api/admin/organizations/{school.org_id}/plan", json={"plan": "cortesia"},
                      headers=admin.headers).status_code == 404
    _sql("UPDATE users SET is_superadmin = true WHERE id = :id", id=admin.user_id)

    saved = client.put(f"/api/admin/organizations/{school.org_id}/plan", json={"plan": "cortesia"}, headers=admin.headers)
    assert saved.status_code == 200, saved.text
    assert saved.json()["plan"] == "cortesia"
    assert _run(_access(school)).mode == "always"
    listed = {org["id"]: org for org in client.get("/api/admin/organizations", headers=admin.headers).json()}
    assert listed[school.org_id]["plan"] == "cortesia"

    # Topes: por organización pisan al plan; un tope desconocido o negativo no entra.
    teacher = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    assert client.put(f"/api/admin/organizations/{teacher.org_id}/plan", json={"limits": {"credits_per_month": 10}},
                      headers=admin.headers).status_code == 200
    assert _run(_access(teacher)).credits_left == 10
    # Vaciar el campo vuelve al valor del plan; nunca deja la organización sin tope.
    cleared = client.put(f"/api/admin/organizations/{teacher.org_id}/plan",
                         json={"limits": {"credits_per_month": None}}, headers=admin.headers)
    assert cleared.json()["limits"] == {}
    assert _run(_access(teacher)).credits_left == 4
    _sql("UPDATE organizations SET limits = CAST('{\"credits_per_month\": null}' AS jsonb) WHERE id = :id",
         id=teacher.org_id)
    assert _run(_access(teacher)).credits_left == 4
    client.put(f"/api/admin/organizations/{teacher.org_id}/plan", json={"limits": {"credits_per_month": 10}},
               headers=admin.headers)
    assert client.put(f"/api/admin/organizations/{teacher.org_id}/plan", json={"limits": {"inventado": 1}},
                      headers=admin.headers).status_code == 422
    assert client.put(f"/api/admin/users/{teacher.user_id}/plan", json={"limits": {"credits_per_month": -1}},
                      headers=admin.headers).status_code == 422
    # Por persona pisan a la organización.
    assert client.put(f"/api/admin/users/{teacher.user_id}/plan", json={"plan": "individual_voz",
                      "limits": {"credits_per_month": 2}}, headers=admin.headers).status_code == 200
    found = client.get(f"/api/admin/users?q={teacher.email[:12]}", headers=admin.headers).json()
    assert [(u["plan"], u["limits"]) for u in found] == [("individual_voz", {"credits_per_month": 2})]
    assert client.put(f"/api/admin/users/{teacher.user_id}/plan", json={"plan": "institucion"},
                      headers=admin.headers).status_code == 422

    # El plan en sí se ajusta sin deploy.
    base = client.put("/api/admin/plans/base", json={"limits": {"credits_per_month": 6}}, headers=admin.headers)
    assert base.status_code == 200 and base.json()["limits"]["credits_per_month"] == 6
    assert _run(_access(EchoTestUser(client, org_name="Otro"))).credits_left == 6
    client.put("/api/admin/plans/base", json={"limits": {"credits_per_month": 4}}, headers=admin.headers)


def test_live_audio_is_recorded_as_usage(client, monkeypatch):
    import echo_api.routers.live as live_module
    from echo_api.services.ai_settings import SttConfig
    from echo_api.services.stt.base import SttResult, SttSegment

    class GroqLike:
        name = "groq"
        model = "whisper-large-v3-turbo"

        async def transcribe_chunk(self, pcm16, sample_rate, language, vocabulary, offset_ms=0, context=None):
            return SttResult(segments=[SttSegment("Hola, buen día.", offset_ms, offset_ms + len(pcm16) // 32)])

    async def fake_resolve_stt(db, org_id):
        return SttConfig(provider="groq", model=None, api_key="x")

    monkeypatch.setattr(live_module, "resolve_stt", fake_resolve_stt)
    monkeypatch.setattr(live_module, "get_stt_provider", lambda *args, **kwargs: GroqLike())
    user = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    meeting_id = _meeting(client, user)
    audio = _tone(5.0) + _silence(1.0)
    with client.websocket_connect(f"/api/meetings/{meeting_id}/ws?token={user.token}") as websocket:
        websocket.send_text(json.dumps({"type": "hello", "role": "recorder", "sample_rate": 16000}))
        assert json.loads(websocket.receive_text())["type"] == "hello_ack"
        for start in range(0, len(audio), 3200):
            websocket.send_bytes(audio[start:start + 3200])
        websocket.send_text(json.dumps({"type": "flush"}))
        while json.loads(websocket.receive_text())["type"] != "flushed":
            pass
    rec.pcm_path(meeting_id).unlink(missing_ok=True)

    async def events():
        from sqlalchemy import select

        async with SessionLocal() as db:
            return (await db.execute(select(UsageEvent).where(UsageEvent.meeting_id == meeting_id))).scalars().all()

    rows = _run(events())
    assert {(row.kind, row.provider, row.model, row.unit) for row in rows} == {
        ("stt_live", "groq", "whisper-large-v3-turbo", "audio_seconds")
    }
    seconds = sum(row.quantity for row in rows)
    # Lo que se mandó: la voz y media pausa; el resto mudo no se transcribe ni se cobra.
    assert 5.0 <= seconds <= 6.1
    # Groq cobra 10 s como mínimo por pedido.
    assert float(sum(row.cost_usd for row in rows)) == round(0.04 * 10 / 3600, 6) * len(rows)
    assert str(rows[0].user_id) == user.user_id


def test_becode_accounts_have_everything_everywhere(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "elevenlabs_api_key", "xi-test")
    user = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    _sql("UPDATE users SET is_superadmin = true WHERE id = :id", id=user.user_id)
    assert _run(_access(user)).mode == "always"
    billing = client.get("/api/billing/me", headers=user.headers).json()
    assert billing["features"]["voice"] is True
