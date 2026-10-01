"""Conversación por voz: solo con el plan que la incluye, con tope de minutos y consumo medido."""
import asyncio
import time
import uuid

import httpx
from conftest import EchoTestUser
from test_levels import _sql

from echo_api.config import get_settings
from echo_api.services import voice_agent


class _FakeElevenLabs:
    calls: list[tuple[str, str, dict | None]] = []
    # Conversaciones que "existen" en ElevenLabs: id -> datos.
    conversations: dict[str, dict] = {}
    created = 0

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
            agent = (params or {}).get("agent_id")
            return httpx.Response(200, json={"signed_url": f"wss://api.elevenlabs.io/v1/convai/conversation?agent={agent}"}, request=request)
        if "/v1/voices/" in url:
            return httpx.Response(200, json={"voice_id": "ok"}, request=request)
        if url.endswith("/convai/conversations"):
            agent = (params or {}).get("agent_id")
            items = [
                {"conversation_id": cid, "status": c["status"], "call_duration_secs": c["secs"]}
                for cid, c in _FakeElevenLabs.conversations.items() if c["agent"] == agent
            ]
            return httpx.Response(200, json={"conversations": items, "has_more": False}, request=request)
        if "/convai/conversations/" in url:
            c = _FakeElevenLabs.conversations[url.rsplit("/", 1)[-1]]
            return httpx.Response(200, json={
                "agent_id": c["agent"], "status": c["status"],
                "metadata": {"call_duration_secs": c["secs"], "charging": {"llm_price": 0.004},
                             "start_time_unix_secs": c.get("start", time.time())},
                "conversation_initiation_client_data": {"dynamic_variables": {"echo_session": c["session"]}},
            }, request=request)
        if "/convai/agents/" in url:
            return httpx.Response(200, json={"conversation_config": {
                "tts": {"voice_id": "v", "model_id": "eleven_v4_turbo"}, "agent": {"prompt": {"llm": "gemini-3.5-flash-lite"}},
            }}, request=request)
        return httpx.Response(404, json={}, request=request)

    async def post(self, url, headers=None, json=None):
        _FakeElevenLabs.calls.append(("POST", url, json))
        _FakeElevenLabs.created += 1
        return httpx.Response(200, json={"agent_id": f"agent_{_FakeElevenLabs.created}"}, request=httpx.Request("POST", url))

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
    _sql("DELETE FROM voice_sessions")
    _sql("DELETE FROM server_ai_settings")


def _voice_user(client, used_seconds: float = 0):
    user = EchoTestUser(client, name="Laura Pérez", org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    _sql("UPDATE users SET plan = 'individual_voz' WHERE id = :id", id=user.user_id)
    if used_seconds:
        _sql("INSERT INTO usage_events (id, kind, provider, unit, quantity, cost_usd, credits, user_id, organization_id,"
             " created_at, updated_at) VALUES (gen_random_uuid(), 'voice', 'elevenlabs', 'voice_seconds', :q, 0, 0, :u,"
             " :o, now(), now())", q=used_seconds, u=user.user_id, o=user.org_id)
    return user


def _talk(session: dict, cid: str, secs: int, status: str = "done", claimed: str | None = None) -> None:
    agent = session["signed_url"].rsplit("agent=", 1)[-1]
    _FakeElevenLabs.conversations[cid] = {
        "status": status, "secs": secs, "agent": agent,
        "session": session["session_id"] if claimed is None else claimed,
    }


def test_voice_needs_the_plan_and_creates_the_agents_once(client, monkeypatch):
    _setup(monkeypatch)
    user = EchoTestUser(client, name="Laura Pérez", org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    # Plan Gratis: no hay voz.
    assert client.post("/api/voice/sessions", headers=user.headers).status_code == 403
    _sql("UPDATE users SET plan = 'individual_voz' WHERE id = :id", id=user.user_id)

    session = client.post("/api/voice/sessions", headers=user.headers)
    assert session.status_code == 200, session.text
    body = session.json()
    assert body["signed_url"].startswith("wss://") and body["user_name"] == "Laura"
    assert body["dynamic_variables"] == {"user_name": "Laura", "echo_session": body["session_id"]}
    assert body["seconds_left"] == 30 * 60 and body["max_seconds"] == voice_agent.MAX_CONVERSATION_SECONDS
    created = [call[2] for call in _FakeElevenLabs.calls if call[0] == "POST" and call[1].endswith("/agents/create")]
    durations = sorted(c["conversation_config"]["conversation"]["max_duration_seconds"] for c in created)
    assert durations == list(voice_agent.BUCKETS)
    config = created[0]["conversation_config"]
    assert config["tts"]["model_id"] == "eleven_v4_turbo" and config["agent"]["language"] == "es"
    assert config["agent"]["prompt"]["tools"][0]["name"] == "consultar_reuniones"
    assert "echo_session" in config["agent"]["dynamic_variables"]["dynamic_variable_placeholders"]
    # Cortar sin haber conectado libera la sesión; la siguiente no crea ni actualiza agentes.
    client.post("/api/voice/sessions/end", json={"session_id": body["session_id"]}, headers=user.headers)
    _FakeElevenLabs.calls = []
    assert client.post("/api/voice/sessions", headers=user.headers).status_code == 200
    assert not [c for c in _FakeElevenLabs.calls if c[0] in ("POST", "PATCH")]


def test_only_one_conversation_at_a_time(client, monkeypatch):
    _setup(monkeypatch)
    user = _voice_user(client)
    first = client.post("/api/voice/sessions", headers=user.headers)
    second = client.post("/api/voice/sessions", headers=user.headers)
    assert first.status_code == 200 and second.status_code == 409
    # La que nadie cerró vence sola.
    _sql("UPDATE voice_sessions SET expires_at = now() - interval '1 minute' WHERE user_id = :u", u=user.user_id)
    assert client.post("/api/voice/sessions", headers=user.headers).status_code == 200


def test_each_conversation_lasts_at_most_what_is_left(client, monkeypatch):
    _setup(monkeypatch)
    # Le quedan 2:30: la charla usa el agente de 1 minuto, no el de 3.
    user = _voice_user(client, used_seconds=30 * 60 - 150)
    assert client.post("/api/voice/sessions", headers=user.headers).json()["max_seconds"] == 60
    status = client.get("/api/voice/status", headers=user.headers).json()
    assert status["seconds_left"] == 150 and status["max_conversation_seconds"] == 60
    # Menos de un minuto: no se abre.
    spent = _voice_user(client, used_seconds=30 * 60 - 40)
    assert client.post("/api/voice/sessions", headers=spent.headers).status_code == 409


def test_an_open_conversation_is_not_charged_until_it_ends(client, monkeypatch):
    _setup(monkeypatch)
    user = _voice_user(client)
    session = client.post("/api/voice/sessions", headers=user.headers).json()

    # Cortar "de mentira" a los pocos segundos con la charla todavía abierta: no se anota.
    _talk(session, "conv_1", 5, status="in-progress")
    end = {"session_id": session["session_id"], "conversation_id": "conv_1", "seconds": 5}
    early = client.post("/api/voice/sessions/end", json=end, headers=user.headers)
    assert early.json()["pending"] is True and early.json()["seconds"] == 0

    _talk(session, "conv_1", 125)
    ended = client.post("/api/voice/sessions/end", json=end, headers=user.headers)
    assert ended.json() == {"seconds": 125.0, "seconds_left": 30 * 60 - 125, "pending": False}
    # El LLM del agente, que ElevenLabs cobra aparte, entra en el costo.
    [(cost, meta)] = _sql_rows("SELECT cost_usd, meta FROM usage_events WHERE user_id = :u AND kind = 'voice'", u=user.user_id)
    assert meta["llm_usd"] == 0.004 and meta["session_id"] == session["session_id"]
    assert float(cost) == round(voice_agent.voice_cost(125) + 0.004, 6)
    again = client.post("/api/voice/sessions/end", json=end, headers=user.headers)
    assert again.json()["seconds"] == 0

    # La sesión de otra persona no se puede cerrar a nombre propio.
    other = _voice_user(client)
    assert client.post("/api/voice/sessions/end", json=end, headers=other.headers).status_code == 404
    # Ni anotar a la sesión propia una conversación de otra sesión.
    mine = client.post("/api/voice/sessions", headers=other.headers).json()
    _talk(session, "conv_ajena", 60)
    stolen = {"session_id": mine["session_id"], "conversation_id": "conv_ajena"}
    assert client.post("/api/voice/sessions/end", json=stolen, headers=other.headers).status_code == 404


def test_a_conversation_nobody_closed_is_charged_to_its_session(client, monkeypatch):
    from echo_api.routers.voice import reconcile_voice_usage

    _setup(monkeypatch)
    user = _voice_user(client)
    session = client.post("/api/voice/sessions", headers=user.headers).json()
    # Cerró la pestaña: el navegador nunca avisó.
    _talk(session, "conv_tab", 9 * 60)
    assert asyncio.run(reconcile_voice_usage()) == 1
    assert asyncio.run(reconcile_voice_usage()) == 0
    [(seconds,)] = _sql_rows("SELECT seconds FROM voice_sessions WHERE id = :s", s=session["session_id"])
    assert seconds == 9 * 60


def test_a_tampered_conversation_is_charged_to_the_last_session_and_alerted(client, monkeypatch):
    from echo_api.routers.voice import reconcile_voice_usage

    _setup(monkeypatch)
    admin = EchoTestUser(client, org_name="Becode")
    _sql("UPDATE users SET is_superadmin = true WHERE id = :id", id=admin.user_id)
    user = _voice_user(client)
    session = client.post("/api/voice/sessions", headers=user.headers).json()
    # El navegador borró la variable (o puso la sesión de otro): igual se cobra.
    _talk(session, "conv_trucha", 300, claimed=str(uuid.uuid4()))
    assert asyncio.run(reconcile_voice_usage()) == 1
    [(owner,)] = _sql_rows("SELECT user_id::text FROM usage_events WHERE meta->>'conversation_id' = 'conv_trucha'")
    assert owner == user.user_id
    alerts = _sql_rows("SELECT title FROM notifications WHERE user_id = :u AND kind = 'voice_unmatched'", u=admin.user_id)
    assert alerts and "conciliada" in alerts[-1][0]
    # Con el mes gastado, no abre otra.
    _sql("UPDATE usage_events SET quantity = 1800 WHERE meta->>'conversation_id' = 'conv_trucha'")
    assert client.post("/api/voice/sessions", headers=user.headers).status_code == 409


def test_the_panel_shows_how_the_agent_is(client, monkeypatch):
    _setup(monkeypatch)
    admin = EchoTestUser(client, org_name="Becode")
    _sql("UPDATE users SET is_superadmin = true WHERE id = :id", id=admin.user_id)
    before = client.get("/api/admin/voice-agent", headers=admin.headers).json()
    assert before["ok"] is False and "Todavía no" in before["detail"]
    created = client.post("/api/admin/voice-agent", headers=admin.headers).json()
    assert created["agent_id"].startswith("agent_") and created["ok"] is True
    assert sorted(created["agents"], key=int) == [str(seconds) for seconds in voice_agent.BUCKETS]
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
    user.make_paid()
    with_minors = client.post("/api/meetings", json={"title": "Con alumnos", "level": "primaria", "minors": True},
                              headers=user.headers).json()["id"]
    adults = client.post("/api/meetings", json={"title": "Equipo", "level": "primaria"}, headers=user.headers).json()["id"]
    client.post("/api/ask", json={"question": "¿Qué pasó?", "voice": True}, headers=user.headers)
    client.post("/api/ask", json={"question": "¿Qué pasó?"}, headers=user.headers)
    assert len(seen) == 2
    voice_ids = {str(mid) for mid in seen[0]}
    assert with_minors not in voice_ids and adults in voice_ids
    assert with_minors in {str(mid) for mid in seen[1]}


def test_the_voice_prompt_has_nothing_from_meetings_with_minors(client, monkeypatch):
    """Ni el título ni las decisiones, tareas, preguntas, riesgos o resúmenes de
    una reunión con menores llegan al LLM cuando pregunta la voz."""
    import echo_api.routers.chat as chat_module

    prompts: list[str] = []

    async def no_chunks(*args, **kwargs):
        return []

    async def some_llm(db, org_id):
        from echo_api.services.ai_settings import LLMConfig

        return LLMConfig("openai", "gpt-4o-mini", "sk-test")

    class _SpyProvider:
        async def chat(self, system, messages, temperature=None):
            prompts.append(messages[-1]["content"])
            return "ok"

    async def no_protect(db, org_id, provider, meeting_id, user_id):
        return _SpyProvider()

    monkeypatch.setattr(chat_module, "retrieve_context", no_chunks)
    monkeypatch.setattr(chat_module, "resolve_llm", some_llm)
    monkeypatch.setattr(chat_module, "protect", no_protect)
    user = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    user.make_paid()
    with_minors = client.post("/api/meetings", json={"title": "Entrevista Tobías", "level": "primaria", "minors": True},
                              headers=user.headers).json()["id"]
    adults = client.post("/api/meetings", json={"title": "Equipo directivo", "level": "primaria"},
                         headers=user.headers).json()["id"]
    for meeting, label in ((with_minors, "MENOR"), (adults, "ADULTOS")):
        args = {"m": meeting, "o": user.org_id}
        _sql("INSERT INTO decisions (id, meeting_id, organization_id, text, status, source, created_at, updated_at) "
             f"VALUES (gen_random_uuid(), :m, :o, 'decision {label}', 'active', 'ai', now(), now())", **args)
        _sql("INSERT INTO action_items (id, meeting_id, organization_id, text, status, source, created_at, updated_at) "
             f"VALUES (gen_random_uuid(), :m, :o, 'tarea {label}', 'pending', 'ai', now(), now())", **args)

    client.post("/api/ask", json={"question": "¿Qué decidimos?", "voice": True}, headers=user.headers)
    client.post("/api/ask", json={"question": "¿Qué decidimos?"}, headers=user.headers)
    voice_prompt, text_prompt = prompts
    assert "Equipo directivo" in voice_prompt and "decision ADULTOS" in voice_prompt and "tarea ADULTOS" in voice_prompt
    for leaked in ("Entrevista Tobías", "decision MENOR", "tarea MENOR"):
        assert leaked not in voice_prompt
    # Por escrito, quien puede ver la reunión la sigue consultando.
    assert "Entrevista Tobías" in text_prompt and "decision MENOR" in text_prompt


def test_voice_comes_only_with_the_paid_voice_plan(client, monkeypatch):
    """Ni Cortesía ni Instituciones dan voz (Bauti, 1/10): botón y sesión con la misma regla."""
    _setup(monkeypatch)
    user = EchoTestUser(client, org_name=f"Colegio {uuid.uuid4().hex[:4]}")
    _sql("UPDATE organizations SET plan = 'cortesia' WHERE id = :id", id=user.org_id)
    status = client.get("/api/voice/status", headers=user.headers).json()
    assert status["allowed"] is False
    assert client.get("/api/billing/me", headers=user.headers).json()["features"]["voice"] is False
    assert client.post("/api/voice/sessions", headers=user.headers).status_code == 403

    _sql("UPDATE users SET plan = 'individual_voz' WHERE id = :id", id=user.user_id)
    status = client.get("/api/voice/status", headers=user.headers).json()
    assert status["allowed"] is True and status["seconds_left"] == status["seconds_total"] == 30 * 60
    assert client.get("/api/billing/me", headers=user.headers).json()["features"]["voice"] is True
