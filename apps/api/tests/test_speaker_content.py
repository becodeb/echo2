"""Dos voces parecidas: el contenido corrige lo que la voz confundió (services/speaker_content.py)."""
import asyncio
import json

from echo_api.services import speaker_content
from echo_api.services.final_chunks import CHUNK_MS, Chunk
from echo_api.services.llm.base import LLMProvider
from echo_api.services.stt.base import SttWord
import pytest


@pytest.fixture(autouse=True)
def _encendido(monkeypatch):
    monkeypatch.setattr(speaker_content, "ENABLED", True)


def _turn(start: int, text: str, speaker: str) -> list[SttWord]:
    return [SttWord(word, start + i * 300, start + i * 300 + 250, speaker) for i, word in enumerate(text.split())]


class _Reader(LLMProvider):
    """Decide como lo haría la IA: la docente habla del cole, la mamá de la casa."""

    name = "reader"

    def __init__(self):
        self.prompts: list[str] = []

    async def chat(self, system, messages, temperature=0.2, max_tokens=4096) -> str:
        prompt = messages[0]["content"]
        self.prompts.append(prompt)
        answer = {}
        for line in prompt.split("FRAGMENTOS:")[1].splitlines():
            if not line.startswith('- "'):
                continue
            key = line.split('"')[1]
            answer[key] = "A" if "cole" in line else "B" if "casa" in line else "duda"
        return json.dumps(answer)


def test_la_docente_que_la_voz_puso_como_la_mama_vuelve_a_ser_la_docente():
    chunks = [
        Chunk(0, 0, CHUNK_MS, "elevenlabs", "es",
              _turn(0, "en el cole trabajamos mucho con los chicos", "speaker_1")
              + _turn(20_000, "en casa le cuesta dormirse", "speaker_2"), [], []),
        # La voz de la docente cambió: quedó como la mamá.
        Chunk(1, CHUNK_MS, 2 * CHUNK_MS, "elevenlabs", "es",
              _turn(CHUNK_MS + 1_000, "sepan que en el cole también estamos trabajando", "speaker_1"), [], []),
        # Y algo que no se puede saber: queda lo que dijo la voz.
        Chunk(2, 2 * CHUNK_MS, 3 * CHUNK_MS, "elevenlabs", "es",
              _turn(2 * CHUNK_MS + 1_000, "sí claro", "speaker_1"), [], []),
    ]
    mappings = [
        {"speaker_1": "speaker_0", "speaker_2": "speaker_1"},
        {"speaker_1": "speaker_1"},
        {"speaker_1": "speaker_1"},
    ]
    reader = _Reader()
    fixed = asyncio.run(speaker_content.check(chunks, mappings, [("speaker_0", "speaker_1", 0.15)], reader))
    assert fixed[1] == {"speaker_1": "speaker_0"}
    assert fixed[2] == {"speaker_1": "speaker_1"}
    assert fixed[0] == mappings[0]
    # A la IA le llega qué dice cada una en el tramo donde hablaron las dos.
    assert "PERSONA A (tramo 1): en el cole" in reader.prompts[0]


def test_nunca_deja_a_dos_personas_del_mismo_tramo_como_una():
    chunks = [
        Chunk(0, 0, CHUNK_MS, "elevenlabs", "es",
              _turn(0, "en el cole", "speaker_1") + _turn(9_000, "en casa", "speaker_2"), [], []),
        Chunk(1, CHUNK_MS, 2 * CHUNK_MS, "elevenlabs", "es",
              _turn(CHUNK_MS, "del cole", "speaker_1") + _turn(CHUNK_MS + 9_000, "también del cole", "speaker_2"), [], []),
    ]
    mappings = [{"speaker_1": "speaker_0", "speaker_2": "speaker_1"}, {"speaker_1": "speaker_0", "speaker_2": "speaker_1"}]
    fixed = asyncio.run(speaker_content.check(chunks, mappings, [("speaker_0", "speaker_1", 0.2)], _Reader()))
    assert fixed[1] == mappings[1]
