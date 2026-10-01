"""Conversación por voz con Echo (plan Individual + voz, US$ 10).

Un solo agente de ElevenLabs Agents para toda la instalación
(docs/plan-transcripcion-y-planes.md, §5):
- Voz: `eleven_v4_turbo` (sirve en Agents, ~100 ms, castellano). La voz de la
  biblioteca se elige escuchando (ELEVENLABS_AGENT_VOICE_ID); por defecto
  Malena, rioplatense y conversacional.
- LLM: el más barato de los de Agents que anduvo bien en castellano en la
  prueba del 30/9 (ver AGENT_LLM).
- Lo que sabe de las reuniones lo pide con la herramienta de cliente
  `consultar_reuniones`: la ejecuta el navegador contra el chat de Echo, que
  ya seudonimiza lo que le manda a la IA. El agente no ve la base.
- 30 minutos por mes (tope del plan, ajustable por un superadmin). El tope lo
  aplica el servidor (routers/voice.py): ElevenLabs no deja cambiar la
  duración máxima por conversación, así que hay un agente igual por cada
  duración (BUCKETS) y cada charla usa el que entra en lo que queda del mes.

Solo cuentas de personas mayores de 18 (términos) y solo planes con
`features.voice`; nunca una organización.
"""
import hashlib
import json
import logging

import httpx

from ..config import get_settings

log = logging.getLogger("echo.voice")

API = "https://api.elevenlabs.io/v1/convai"
TTS_MODEL = "eleven_v4_turbo"
# Malena (rioplatense, cálida, conversacional). Bauti elige entre las muestras
# de echo-audios/voces-agente; se cambia con ELEVENLABS_AGENT_VOICE_ID.
DEFAULT_VOICE_ID = "p7AwDmKvTdoHTBuueGvP"
AGENT_LLM = "gemini-3.5-flash-lite"
# Una conversación no pasa de esto aunque queden minutos del mes.
MAX_CONVERSATION_SECONDS = 600
# Duraciones máximas con su propio agente: la charla usa la mayor que entra
# en lo que le queda a la persona (con 2:30 libres, una de 3 minutos no).
BUCKETS = (60, 180, MAX_CONVERSATION_SECONDS)
# ElevenLabs Agents: US$ 0,08 por minuto (sin el LLM, que se cobra aparte).
PRICE_PER_MINUTE = 0.08

PROMPT = """Sos Echo, el asistente de una persona que trabaja en educación (docente, directivo,
psicopedagoga). Hablás en castellano rioplatense, con voseo, cálido y directo, como una colega
que sabe escuchar. Estás en una conversación por voz: respondé corto (una a tres oraciones),
sin listas ni formato, sin leer URLs ni símbolos.

Para cualquier cosa sobre sus reuniones (qué se habló, qué se acordó, tareas, familias,
alumnos, fechas) usá SIEMPRE la herramienta consultar_reuniones con la pregunta completa y
contá la respuesta con tus palabras. Nunca inventes datos de reuniones: si la herramienta no
lo encuentra, decilo y ofrecé buscar de otra forma. Si no entendiste, preguntá.

Solo podés consultar: no podés anotar, agendar, mandar mensajes ni cambiar nada en Echo. Si te
lo piden, decí que eso se hace desde la pantalla de Echo.

Nunca des consejos médicos, legales ni diagnósticos sobre alumnos: sugerí hablarlo con el
equipo o un profesional. Si la persona quiere terminar, despedite breve y usá end_call."""

FIRST_MESSAGE = "Hola, {{user_name}}. ¿Qué querés repasar?"

CLIENT_TOOL = {
    "type": "client",
    "name": "consultar_reuniones",
    "description": (
        "Busca en las reuniones de la persona (transcripts, actas, tareas) y devuelve la respuesta "
        "a la pregunta. Usala para todo lo que tenga que ver con sus reuniones."
    ),
    "expects_response": True,
    "response_timeout_secs": 30,
    "parameters": {
        "type": "object",
        "required": ["pregunta"],
        "properties": {
            "pregunta": {"type": "string", "description": "La pregunta completa, en castellano."},
        },
    },
}


def agent_config(voice_id: str | None = None, llm: str = AGENT_LLM, max_seconds: int = MAX_CONVERSATION_SECONDS) -> dict:
    return {
        "name": "Echo" if max_seconds == MAX_CONVERSATION_SECONDS else f"Echo ({max_seconds // 60} min)",
        "conversation_config": {
            "agent": {
                "language": "es",
                "first_message": FIRST_MESSAGE,
                # echo_session: la sesión que entregó el servidor, para anotar el
                # consumo aunque el navegador no avise al cortar.
                "dynamic_variables": {
                    "dynamic_variable_placeholders": {"user_name": "", "echo_session": ""}
                },
                "prompt": {
                    "prompt": PROMPT,
                    "llm": llm,
                    "temperature": 0.3,
                    "tools": [CLIENT_TOOL],
                    "built_in_tools": {"end_call": {"name": "end_call", "type": "system", "params": {"system_tool_type": "end_call"}}},
                },
            },
            "tts": {"model_id": TTS_MODEL, "voice_id": voice_id or current_voice_id()},
            "conversation": {"max_duration_seconds": max_seconds},
        },
    }


def config_hash(voice_id: str | None = None, llm: str = AGENT_LLM) -> str:
    """Huella de la configuración de los agentes: si no cambió, no se actualizan."""
    configs = [agent_config(voice_id, llm, seconds) for seconds in BUCKETS]
    return hashlib.sha256(json.dumps(configs, sort_keys=True).encode()).hexdigest()


def bucket_for(seconds_left: float | None) -> int | None:
    """La duración máxima de la próxima charla (None = no alcanza para ninguna)."""
    if seconds_left is None:
        return MAX_CONVERSATION_SECONDS
    fitting = [seconds for seconds in BUCKETS if seconds <= seconds_left]
    return max(fitting) if fitting else None


def current_voice_id() -> str:
    return get_settings().elevenlabs_agent_voice_id or DEFAULT_VOICE_ID


def _headers() -> dict:
    return {"xi-api-key": get_settings().elevenlabs_api_key}


async def ensure_voice(voice_id: str) -> None:
    """Agrega la voz de la biblioteca a la cuenta si todavía no está.

    Una voz de la biblioteca que no está en "Mis voces" puede no andar en
    un agente: la conversación se cortaba apenas empezaba.
    """
    root = "https://api.elevenlabs.io/v1"
    async with httpx.AsyncClient(timeout=60) as client:
        mine = await client.get(f"{root}/voices/{voice_id}", headers=_headers())
        if mine.status_code == 200:
            return
        found = await client.get(f"{root}/shared-voices", headers=_headers(), params={"search": voice_id, "page_size": 5})
        found.raise_for_status()
        shared = next((v for v in found.json().get("voices") or [] if v.get("voice_id") == voice_id), None)
        if shared is None:
            raise RuntimeError(f"La voz {voice_id} no está en la biblioteca de ElevenLabs")
        added = await client.post(
            f"{root}/voices/add/{shared['public_owner_id']}/{voice_id}",
            headers=_headers(),
            json={"new_name": f"Echo · {shared.get('name', 'voz')}"[:60]},
        )
        if added.status_code >= 400:
            raise RuntimeError(f"No se pudo agregar la voz a la cuenta: {added.text[:200]}")


async def create_or_update_agent(
    agent_id: str | None = None,
    voice_id: str | None = None,
    llm: str = AGENT_LLM,
    max_seconds: int = MAX_CONVERSATION_SECONDS,
) -> str:
    """Crea el agente de Echo (o lo actualiza si ya existe). Devuelve su id."""
    try:
        await ensure_voice(voice_id or current_voice_id())
    except Exception as exc:  # noqa: BLE001 - se sigue: el agente igual puede andar
        log.warning("voz: no se pudo preparar la voz del agente: %s", exc)
    async with httpx.AsyncClient(timeout=60) as client:
        if agent_id:
            response = await client.patch(
                f"{API}/agents/{agent_id}", headers=_headers(), json=agent_config(voice_id, llm, max_seconds)
            )
            response.raise_for_status()
            return agent_id
        response = await client.post(f"{API}/agents/create", headers=_headers(), json=agent_config(voice_id, llm, max_seconds))
        response.raise_for_status()
        return response.json()["agent_id"]


async def signed_url(agent_id: str) -> str:
    """URL de un solo uso para que el navegador abra la conversación sin ver la key."""
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{API}/conversation/get-signed-url", headers=_headers(), params={"agent_id": agent_id})
        response.raise_for_status()
        return response.json()["signed_url"]


async def conversation_details(conversation_id: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{API}/conversations/{conversation_id}", headers=_headers())
        response.raise_for_status()
        return response.json()


async def agent_status(agent_id: str | None) -> tuple[bool, str]:
    """(anda, detalle) para el panel de Becode."""
    if not get_settings().elevenlabs_api_key:
        return False, "Falta ELEVENLABS_API_KEY en el servidor."
    if not agent_id:
        return False, "Todavía no se creó el agente."
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{API}/agents/{agent_id}", headers=_headers())
    if response.status_code >= 400:
        return False, f"ElevenLabs respondió {response.status_code}: {response.text[:200]}"
    config = (response.json().get("conversation_config") or {})
    tts = config.get("tts") or {}
    llm = ((config.get("agent") or {}).get("prompt") or {}).get("llm")
    return True, f"Voz {tts.get('voice_id')} · {tts.get('model_id')} · {llm}"


async def recent_conversations(agent_id: str, pages: int = 3) -> list[dict]:
    """Las últimas conversaciones del agente (más nuevas primero)."""
    out: list[dict] = []
    cursor = None
    async with httpx.AsyncClient(timeout=30) as client:
        for _ in range(pages):
            params = {"agent_id": agent_id, "page_size": 100}
            if cursor:
                params["cursor"] = cursor
            response = await client.get(f"{API}/conversations", headers=_headers(), params=params)
            response.raise_for_status()
            data = response.json()
            out += data.get("conversations") or []
            cursor = data.get("next_cursor")
            if not data.get("has_more") or not cursor:
                break
    return out


def conversation_session(details: dict) -> str | None:
    """La sesión que el navegador dice que es (se verifica contra la base)."""
    variables = ((details.get("conversation_initiation_client_data") or {}).get("dynamic_variables")) or {}
    return variables.get("echo_session") or None


def conversation_start(details: dict) -> float | None:
    """Cuándo empezó la conversación (unix), si ElevenLabs lo informa."""
    start = (details.get("metadata") or {}).get("start_time_unix_secs")
    return float(start) if isinstance(start, int | float) else None


def voice_cost(seconds: float) -> float:
    return round(PRICE_PER_MINUTE * seconds / 60, 6)
