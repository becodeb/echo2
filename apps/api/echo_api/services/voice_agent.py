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
- 30 minutos por mes (tope del plan, ajustable por un superadmin).

Solo cuentas de personas mayores de 18 (términos) y solo planes con
`features.voice`; nunca una organización.
"""
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


def agent_config(voice_id: str | None = None, llm: str = AGENT_LLM) -> dict:
    return {
        "name": "Echo",
        "conversation_config": {
            "agent": {
                "language": "es",
                "first_message": FIRST_MESSAGE,
                "dynamic_variables": {"dynamic_variable_placeholders": {"user_name": ""}},
                "prompt": {
                    "prompt": PROMPT,
                    "llm": llm,
                    "temperature": 0.3,
                    "tools": [CLIENT_TOOL],
                    "built_in_tools": {"end_call": {"name": "end_call", "type": "system", "params": {"system_tool_type": "end_call"}}},
                },
            },
            "tts": {"model_id": TTS_MODEL, "voice_id": voice_id or get_settings().elevenlabs_agent_voice_id or DEFAULT_VOICE_ID},
            "conversation": {"max_duration_seconds": MAX_CONVERSATION_SECONDS},
        },
    }


def _headers() -> dict:
    return {"xi-api-key": get_settings().elevenlabs_api_key}


async def create_or_update_agent(agent_id: str | None = None, voice_id: str | None = None, llm: str = AGENT_LLM) -> str:
    """Crea el agente de Echo (o lo actualiza si ya existe). Devuelve su id."""
    async with httpx.AsyncClient(timeout=60) as client:
        if agent_id:
            response = await client.patch(f"{API}/agents/{agent_id}", headers=_headers(), json=agent_config(voice_id, llm))
            response.raise_for_status()
            return agent_id
        response = await client.post(f"{API}/agents/create", headers=_headers(), json=agent_config(voice_id, llm))
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


def voice_cost(seconds: float) -> float:
    return round(PRICE_PER_MINUTE * seconds / 60, 6)
