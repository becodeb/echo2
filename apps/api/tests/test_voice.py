"""Conversación por voz: solo con el plan que la incluye, con tope de minutos y consumo medido."""
import uuid

import httpx
from conftest import EchoTestUser
from test_levels import _sql

from echo_api.config import get_settings
from echo_api.services import voice_agent


class _FakeElevenLabs:
    calls: list[tuple[str, str, dict | None]] = []
    duration = 125

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
        return httpx.Response(200, json={"agent_id": "agent_echo", "metadata": {"call_duration_secs": _FakeElevenLabs.duration}}, request=request)

    async def post(self, url, headers=None, json=None):
        _FakeElevenLabs.calls.append(("POST", url, json))
        return httpx.Response(200, json={"agent_id": "agent_echo"}, request=httpx.Request("POST", url))

    async def patch(self, url, headers=None, json=None):
        _FakeElevenLabs.calls.append(("PATCH", url, json))
        return httpx.Response(200, json={}, request=httpx.Request("PATCH", url))


def test_voice_needs_the_plan_the_agent_and_minutes_left(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "elevenlabs_api_key", "xi-test")
    _FakeElevenLabs.calls = []
    monkeypatch.setattr(httpx, "AsyncClient", _FakeElevenLabs)
    admin = EchoTestUser(client, org_name="Becode")
    _sql("UPDATE users SET is_superadmin = true WHERE id = :id", id=admin.user_id)
    _sql("DELETE FROM server_ai_settings")
    user = EchoTestUser(client, name="Laura Pérez", org_name=f"Colegio {uuid.uuid4().hex[:4]}")

    # Plan Gratis: no hay voz.
    assert client.post("/api/voice/sessions", headers=user.headers).status_code == 403
    _sql("UPDATE users SET plan = 'individual_voz' WHERE id = :id", id=user.user_id)
    # Con el plan pero sin agente creado todavía.
    assert client.post("/api/voice/sessions", headers=user.headers).status_code == 503

    created = client.post("/api/admin/voice-agent", headers=admin.headers)
    assert created.status_code == 200, created.text
    assert created.json()["agent_id"] == "agent_echo"
    [(method, url, body)] = [call for call in _FakeElevenLabs.calls if call[0] == "POST"]
    config = body["conversation_config"]
    assert config["tts"]["model_id"] == "eleven_v4_turbo" and config["agent"]["language"] == "es"
    assert config["agent"]["prompt"]["tools"][0]["name"] == "consultar_reuniones"
    # La segunda vez actualiza el mismo agente, no crea otro.
    client.post("/api/admin/voice-agent", headers=admin.headers)
    assert [call[0] for call in _FakeElevenLabs.calls].count("PATCH") == 1

    session = client.post("/api/voice/sessions", headers=user.headers)
    assert session.status_code == 200, session.text
    body = session.json()
    assert body["signed_url"].startswith("wss://") and body["user_name"] == "Laura"
    assert body["seconds_left"] == 30 * 60 and body["max_seconds"] == voice_agent.MAX_CONVERSATION_SECONDS

    # Al cortar se anota lo que midió ElevenLabs, no lo que dice el navegador; una sola vez.
    ended = client.post("/api/voice/sessions/end", json={"conversation_id": "conv_1", "seconds": 5}, headers=user.headers)
    assert ended.json() == {"seconds": 125.0, "seconds_left": 30 * 60 - 125}
    again = client.post("/api/voice/sessions/end", json={"conversation_id": "conv_1", "seconds": 5}, headers=user.headers)
    assert again.json()["seconds"] == 0
    usage = client.get("/api/billing/usage", headers=user.headers).json()["people"][0]["lines"]
    [voice] = [line for line in usage if line["kind"] == "voice"]
    assert voice["quantity"] == 125 and voice["cost_usd"] == round(0.08 * 125 / 60, 6)

    # Se terminaron los minutos del mes.
    _FakeElevenLabs.duration = 30 * 60
    client.post("/api/voice/sessions/end", json={"conversation_id": "conv_2"}, headers=user.headers)
    assert client.post("/api/voice/sessions", headers=user.headers).status_code == 409
    _FakeElevenLabs.duration = 125
