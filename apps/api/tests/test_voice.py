"""Conversación por voz: solo con el plan que la incluye, con tope de minutos y consumo medido."""
import asyncio
import uuid

import httpx
from conftest import EchoTestUser
from test_levels import _sql

from echo_api.config import get_settings
from echo_api.services import voice_agent


class _FakeElevenLabs:
    calls: list[tuple[str, str, dict | None]] = []
    # Conversaciones que "existen" en ElevenLabs: id -> (estado, segundos, dueño, org)
    conversations: dict[str, tuple[str, int, str, str]] = {}

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None, params=None):
        _FakeElevenLabs.calls.append(("GET", url, params))
        request = httpx.Request("GET", url)
        if url.endswith("/get-signed-url"):
            return httpx.Response(200, json={"signed_url": "wss://api.elevenlabs.io/v1/convai/conversation?token=x"}, request=request)
        if "/v1/voices/" in url:
            return httpx.Response(200, json={"voice_id": "ok"}, request=request)
        if url.endswith("/convai/conversations"):
            items = [
                {"conversation_id": cid, "status": state, "call_duration_secs": secs}
                for cid, (state, secs, _, _) in _FakeElevenLabs.conversations.items()
            ]
            return httpx.Response(200, json={"conversations": items, "has_more": False}, request=request)
        if "/convai/conversations/" in url:
            cid = url.rsplit("/", 1)[-1]
            state, secs, owner, org = _FakeElevenLabs.conversations[cid]
            return httpx.Response(200, json={
                "agent_id": "agent_echo", "status": state,
                "metadata": {"call_duration_secs": secs, "charging": {"llm_price": 0.004}},
                "conversation_initiation_client_data": {"dynamic_variables": {"echo_user": owner, "echo_org": org}},
            }, request=request)
        if "/convai/agents/" in url:
            return httpx.Response(200, json={"conversation_config": {
                "tts": {"voice_id": "v", "model_id": "eleven_v4_turbo"}, "agent": {"prompt": {"llm": "gemini-3.5-flash-lite"}},
            }}, request=request)
        return httpx.Response(404, json={}, request=request)

    async def post(self, url, headers=None, json=None):
        _FakeElevenLabs.calls.append(("POST", url, json))
        return httpx.Response(200, json={"agent_id": "agent_echo"}, request=httpx.Request("POST", url))

    async def patch(self, url, headers=None, json=None):
        _FakeElevenLabs.calls.append(("PATCH", url, json))
        return httpx.Response(200, json={}, request=httpx.Request("PATCH", url))


def _sql_rows(statement: str, **params) -> list[tuple]:
    from sqlalchemy import text

    from echo_api.db import SessionLocal

    async def run():
        async with SessionLocal() as db:
            return [tuple(row) for row in (await db.execute(text(statement), params)).all()]

    return asyncio.run(run())


def _setup(monkeypatch):
    monkeypatch.setattr(get_settings(), "elevenlabs_api_key", "xi-test")
    _FakeElevenLabs.calls = []
    _FakeElevenLabs.conversations = {}
    monkeypatch.setattr(httpx, "AsyncClient", _FakeElevenLabs)
    _sql("DELETE FROM server_ai_settings")


def test_voice_needs_the_plan_and_creates_the_agent_on_the_first_use(client, monkeypatch):
    _setup(monkeypatch)
    user = EchoTestUser(client, name="Laura Pérez", org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    # Plan Gratis: no hay voz.
    assert client.post("/api/voice/sessions", headers=user.headers).status_code == 403
    _sql("UPDATE users SET plan = 'individual_voz' WHERE id = :id", id=user.user_id)

    session = client.post("/api/voice/sessions", headers=user.headers)
    assert session.status_code == 200, session.text
    body = session.json()
    assert body["signed_url"].startswith("wss://") and body["user_name"] == "Laura"
    assert body["dynamic_variables"] == {"user_name": "Laura", "echo_user": user.user_id, "echo_org": user.org_id}
    assert body["seconds_left"] == 30 * 60 and body["max_seconds"] == voice_agent.MAX_CONVERSATION_SECONDS
    [(_, _, created)] = [call for call in _FakeElevenLabs.calls if call[0] == "POST" and call[1].endswith("/agents/create")]
    config = created["conversation_config"]
    assert config["tts"]["model_id"] == "eleven_v4_turbo" and config["agent"]["language"] == "es"
    assert config["agent"]["prompt"]["tools"][0]["name"] == "consultar_reuniones"
    assert "echo_user" in config["agent"]["dynamic_variables"]["dynamic_variable_placeholders"]
    # La segunda sesión usa el mismo agente: no crea otro.
    client.post("/api/voice/sessions", headers=user.headers)
    assert sum(1 for call in _FakeElevenLabs.calls if call[1].endswith("/agents/create")) == 1


def test_an_open_conversation_is_not_charged_until_it_ends(client, monkeypatch):
    _setup(monkeypatch)
    user = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    _sql("UPDATE users SET plan = 'individual_voz' WHERE id = :id", id=user.user_id)
    client.post("/api/voice/sessions", headers=user.headers)

    # Cortar "de mentira" a los pocos segundos con la charla todavía abierta: no se anota.
    _FakeElevenLabs.conversations["conv_1"] = ("in-progress", 5, user.user_id, user.org_id)
    early = client.post("/api/voice/sessions/end", json={"conversation_id": "conv_1", "seconds": 5}, headers=user.headers)
    assert early.json()["pending"] is True and early.json()["seconds"] == 0

    _FakeElevenLabs.conversations["conv_1"] = ("done", 125, user.user_id, user.org_id)
    ended = client.post("/api/voice/sessions/end", json={"conversation_id": "conv_1"}, headers=user.headers)
    assert ended.json() == {"seconds": 125.0, "seconds_left": 30 * 60 - 125, "pending": False}
    # El LLM del agente, que ElevenLabs cobra aparte, entra en el costo.
    [(cost, meta)] = _sql_rows("SELECT cost_usd, meta FROM usage_events WHERE user_id = :u AND kind = 'voice'", u=user.user_id)
    assert meta["llm_usd"] == 0.004 and float(cost) == round(voice_agent.voice_cost(125) + 0.004, 6)
    again = client.post("/api/voice/sessions/end", json={"conversation_id": "conv_1"}, headers=user.headers)
    assert again.json()["seconds"] == 0

    # La conversación de otra persona no se puede cerrar a nombre propio.
    other = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    _sql("UPDATE users SET plan = 'individual_voz' WHERE id = :id", id=other.user_id)
    _FakeElevenLabs.conversations["conv_2"] = ("done", 60, user.user_id, user.org_id)
    assert client.post("/api/voice/sessions/end", json={"conversation_id": "conv_2"}, headers=other.headers).status_code == 404


def test_a_conversation_nobody_closed_is_charged_anyway(client, monkeypatch):
    from echo_api.routers.voice import reconcile_voice_usage

    _setup(monkeypatch)
    user = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    _sql("UPDATE users SET plan = 'individual_voz' WHERE id = :id", id=user.user_id)
    client.post("/api/voice/sessions", headers=user.headers)
    # Cerró la pestaña: el navegador nunca avisó.
    _FakeElevenLabs.conversations["conv_tab"] = ("done", 30 * 60, user.user_id, user.org_id)
    assert asyncio.run(reconcile_voice_usage()) == 1
    assert asyncio.run(reconcile_voice_usage()) == 0
    # Con el mes gastado no abre otra.
    assert client.post("/api/voice/sessions", headers=user.headers).status_code == 409


def test_the_panel_shows_how_the_agent_is(client, monkeypatch):
    _setup(monkeypatch)
    admin = EchoTestUser(client, org_name="Becode")
    _sql("UPDATE users SET is_superadmin = true WHERE id = :id", id=admin.user_id)
    before = client.get("/api/admin/voice-agent", headers=admin.headers).json()
    assert before["ok"] is False and "Todavía no" in before["detail"]
    created = client.post("/api/admin/voice-agent", headers=admin.headers).json()
    assert created["agent_id"] == "agent_echo" and created["ok"] is True
    assert "eleven_v4_turbo" in created["detail"]


def test_the_voice_agent_never_reads_meetings_with_minors(client, monkeypatch):
    import echo_api.routers.chat as chat_module

    seen: list[list] = []

    async def spy_retrieve(db, org_id, question, embeddings_config, meeting_id=None, limit=12, visible_ids=None):
        seen.append(list(visible_ids or []))
        return []

    async def some_llm(db, org_id):
        from echo_api.services.ai_settings import LLMConfig

        return LLMConfig("openai", "gpt-4o-mini", "sk-test")

    monkeypatch.setattr(chat_module, "retrieve_context", spy_retrieve)
    monkeypatch.setattr(chat_module, "resolve_llm", some_llm)
    user = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    with_minors = client.post("/api/meetings", json={"title": "Con alumnos", "level": "primaria", "minors": True},
                              headers=user.headers).json()["id"]
    adults = client.post("/api/meetings", json={"title": "Equipo", "level": "primaria"}, headers=user.headers).json()["id"]
    client.post("/api/ask", json={"question": "¿Qué pasó?", "voice": True}, headers=user.headers)
    client.post("/api/ask", json={"question": "¿Qué pasó?"}, headers=user.headers)
    assert len(seen) == 2
    voice_ids = {str(mid) for mid in seen[0]}
    assert with_minors not in voice_ids and adults in voice_ids
    assert with_minors in {str(mid) for mid in seen[1]}
