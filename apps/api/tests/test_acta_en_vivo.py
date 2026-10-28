"""El acta mientras se escribe: streaming de la IA, borrador con nombres de verdad y sin marcadores a medias."""
import asyncio
import json
import uuid

import httpx

from echo_api.services import minutes_gen
from echo_api.services.llm import get_llm_provider
from echo_api.services.llm.base import LLMProvider, current_on_text, streaming
from echo_api.services.minutes_gen import partial_json_strings
from echo_api.services.privacy import Person, PrivateLLMProvider, Pseudonymizer


def test_los_textos_de_un_json_que_todavia_esta_llegando():
    assert partial_json_strings('{"markdown": "# ACTA\\n\\nSe re') == {"markdown": "# ACTA\n\nSe re"}
    # Anidado (el acta de entrevista) y con el último campo a medias.
    text = '{"fields": {"alumno": "A. M.", "curso": "1N EP", "desarrollo": "La familia cuenta que'
    assert partial_json_strings(text) == {"alumno": "A. M.", "curso": "1N EP", "desarrollo": "La familia cuenta que"}
    # Un escape cortado al final espera al próximo pedazo.
    assert partial_json_strings('{"markdown": "comillas \\') == {"markdown": "comillas "}
    assert partial_json_strings('{"markdown": "acento \\u00e') == {"markdown": "acento "}
    assert partial_json_strings('{"markdown": "acento \\u00e1"}') == {"markdown": "acento á"}
    # Todavía sin valor: nada.
    assert partial_json_strings('{"mark') == {}
    assert partial_json_strings('{"markdown": ') == {}


def _sse(parts: list[str]) -> bytes:
    lines = [f"data: {json.dumps({'choices': [{'delta': {'content': part}}]})}" for part in parts]
    lines.append(f"data: {json.dumps({'choices': [], 'usage': {'prompt_tokens': 10, 'completion_tokens': 5}})}")
    lines.append("data: [DONE]")
    return ("\n\n".join(lines) + "\n\n").encode()


def _with_transport(monkeypatch, handler) -> None:
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs))


def test_la_ia_va_pasando_el_texto_mientras_escribe(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, content=_sse(['{"markdown": "Hola', " que", ' tal"}']))

    _with_transport(monkeypatch, handler)
    seen: list[str] = []
    provider = get_llm_provider("openai", "k", "gpt-6-luna")
    with streaming(seen.append):
        answer = asyncio.run(provider.chat("sys", [{"role": "user", "content": "x"}], 0.2, 100))
    assert answer == '{"markdown": "Hola que tal"}'
    assert seen == ['{"markdown": "Hola', '{"markdown": "Hola que', '{"markdown": "Hola que tal"}']


def test_si_no_acepta_streaming_pide_de_la_forma_de_siempre(monkeypatch):
    calls: list[bool] = []

    def handler(request: httpx.Request) -> httpx.Response:
        stream = bool(json.loads(request.content).get("stream"))
        calls.append(stream)
        if stream:
            return httpx.Response(400, text="stream no soportado")
        return httpx.Response(200, json={"choices": [{"message": {"content": "listo"}}]})

    _with_transport(monkeypatch, handler)
    provider = get_llm_provider("openai", "k", "gpt-6-luna")
    with streaming(lambda text: None):
        assert asyncio.run(provider.chat("sys", [{"role": "user", "content": "x"}], 0.2, 100)) == "listo"
    assert calls == [True, False]


class _Writer(LLMProvider):
    """Escribe el acta de a pedazos, cortando un marcador a la mitad."""

    name = "writer"

    async def chat(self, system, messages, temperature=0.2, max_tokens=4096) -> str:
        on_text = current_on_text()
        parts = ["La Sra. [MAD", "La Sra. [MADRE_1] dijo que ALUM", "La Sra. [MADRE_1] dijo que ALUMNO_1 llega triste"]
        for part in parts:
            if on_text:
                on_text(part)
        return parts[-1]


def test_el_borrador_trae_los_nombres_y_nunca_un_marcador_a_medias():
    group = "FLIA. MUNAFO"
    pseudo = Pseudonymizer([Person.parse("MUNAFO, Allegra", "alumno", group), Person.parse("LARRUBIA, Melina", "madre", group)])
    pseudo.apply("Melina contó que Allegra llega triste.")
    seen: list[str] = []
    provider = PrivateLLMProvider(_Writer(), pseudo)
    with streaming(seen.append):
        final = asyncio.run(provider.chat("sys", [{"role": "user", "content": "Melina"}]))
    assert seen[0] == "La Sra. "
    assert seen[1] == "La Sra. Melina Larrubia dijo que "
    assert seen[2] == final == "La Sra. Melina Larrubia dijo que Allegra Munafo llega triste"
    assert not any("[" in text or "_" in text for text in seen)


def test_con_la_primera_linea_la_pantalla_pasa_al_acta(monkeypatch):
    announced: list[str] = []

    def fake_spawn(coroutine, name=None):
        coroutine.close()
        announced.append(name)

    monkeypatch.setattr("echo_api.services.background.spawn", fake_spawn)
    meeting_id = uuid.uuid4()
    on_text = minutes_gen._drafter(meeting_id, lambda values: values.get("markdown", ""))
    on_text('{"mark')
    assert minutes_gen.draft_for(meeting_id) is None and not announced
    on_text('{"markdown": "# ACTA')
    on_text('{"markdown": "# ACTA\\n\\nSe reúnen')
    assert minutes_gen.draft_for(meeting_id) == "# ACTA\n\nSe reúnen"
    assert len(announced) == 1
    minutes_gen._drafts.pop(meeting_id, None)
