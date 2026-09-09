"""Abstracción LLMProvider.

Un solo cliente OpenAI-compatible cubre OpenAI, Groq, OpenRouter, GMI Cloud,
Ollama y Gemini (endpoint compatible); Anthropic tiene cliente propio. El modelo NUNCA
está hardcodeado: viene de la configuración de la organización.
"""
from __future__ import annotations

import json
import logging
import re
import time

import httpx

log = logging.getLogger("echo.llm")


class LLMError(Exception):
    pass


class LLMProvider:
    name = "base"

    async def chat(
        self,
        system: str,
        messages: list[dict],
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> str:
        raise NotImplementedError

    async def chat_json(
        self,
        system: str,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> dict | list:
        """Pide JSON y lo parsea tolerando fences de markdown."""
        text = await self.chat(
            system + "\n\nRespondé ÚNICAMENTE con JSON válido, sin texto adicional.",
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return parse_json_loose(text)


def parse_json_loose(text: str) -> dict | list:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # último recurso: primer objeto/array balanceado
        for open_char, close_char in (("{", "}"), ("[", "]")):
            start = text.find(open_char)
            if start == -1:
                continue
            depth = 0
            for index in range(start, len(text)):
                if text[index] == open_char:
                    depth += 1
                elif text[index] == close_char:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start : index + 1])
                        except json.JSONDecodeError:
                            break
        raise LLMError("El modelo no devolvió JSON válido")


class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str,
        model: str,
        omit_max_tokens: bool = False,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        # Sin techo de salida el modelo corta por finish_reason en vez de
        # truncar a mitad de frase (necesario para minutas largas en GMI).
        self.omit_max_tokens = omit_max_tokens

    async def chat(self, system, messages, temperature=0.2, max_tokens: int | None = 4096) -> str:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "temperature": temperature,
        }
        if not self.omit_max_tokens and max_tokens is not None:
            payload["max_tokens"] = max_tokens
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions", json=payload, headers=headers
                )
        except httpx.HTTPError as exc:
            raise LLMError(f"Error de red con {self.name}: {exc}") from exc
        latency_ms = int((time.monotonic() - started) * 1000)
        log.info("llm %s model=%s latency_ms=%d status=%d", self.name, self.model, latency_ms, response.status_code)
        if response.status_code == 401:
            raise LLMError(f"API key inválida para {self.name}")
        if response.status_code == 429:
            raise LLMError(f"Rate limit de {self.name}; probá de nuevo en unos segundos")
        if response.status_code >= 400:
            raise LLMError(f"{self.name} devolvió {response.status_code}: {response.text[:300]}")
        data = response.json()
        try:
            choice = data["choices"][0]
            content = choice["message"]["content"] or ""
        except (KeyError, IndexError) as exc:
            raise LLMError(f"Respuesta inesperada de {self.name}") from exc
        if not content.strip():
            # Los modelos razonadores pueden gastar todo el presupuesto pensando
            # y devolver 200 con contenido vacío. Tratarlo como éxito produce
            # actas en blanco sin que nadie se entere; es una falla y como tal
            # tiene que poder disparar el siguiente modelo de la cadena.
            reason = choice.get("finish_reason")
            detail = " (se quedó sin tokens razonando)" if reason == "length" else ""
            raise LLMError(f"{self.name} devolvió una respuesta vacía{detail}")
        return content


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    async def chat(self, system, messages, temperature=0.2, max_tokens=4096) -> str:
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.model,
                        "system": system,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                )
        except httpx.HTTPError as exc:
            raise LLMError(f"Error de red con Anthropic: {exc}") from exc
        latency_ms = int((time.monotonic() - started) * 1000)
        log.info("llm anthropic model=%s latency_ms=%d status=%d", self.model, latency_ms, response.status_code)
        if response.status_code == 401:
            raise LLMError("API key de Anthropic inválida")
        if response.status_code == 429:
            raise LLMError("Rate limit de Anthropic; probá de nuevo en unos segundos")
        if response.status_code >= 400:
            raise LLMError(f"Anthropic devolvió {response.status_code}: {response.text[:300]}")
        data = response.json()
        parts = [block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"]
        return "".join(parts)


class FakeLLMProvider(LLMProvider):
    """SOLO para tests. Devuelve respuestas registradas por la suite."""

    name = "fake"

    def __init__(self, responses: list[str] | None = None):
        self.responses = responses or []
        self.calls: list[dict] = []
        self._index = 0

    async def chat(self, system, messages, temperature=0.2, max_tokens=4096) -> str:
        self.calls.append({"system": system, "messages": messages})
        if self._index < len(self.responses):
            response = self.responses[self._index]
            self._index += 1
            return response
        return "{}"


class FallbackLLMProvider(LLMProvider):
    """Prueba varios modelos en orden hasta que uno responda.

    Los modelos gratuitos se caen, se saturan o devuelven vacío con más
    frecuencia que los pagos. Con una sola opción, cada una de esas veces es
    un acta que no sale; con la cadena, es un reintento que nadie nota.

    Solo cubre fallas del modelo. Si ninguno responde, propaga el error del
    último para no esconder el motivo real.
    """

    name = "fallback"

    def __init__(self, providers: list[LLMProvider]):
        if not providers:
            raise ValueError("La cadena de modelos no puede estar vacía")
        self.providers = providers
        self.model = ", ".join(getattr(p, "model", p.name) for p in providers)

    async def chat(self, system, messages, temperature=0.2, max_tokens: int | None = 4096) -> str:
        last: Exception | None = None
        for index, provider in enumerate(self.providers):
            try:
                return await provider.chat(system, messages, temperature, max_tokens)
            except LLMError as exc:
                last = exc
                log.warning(
                    "llm: %s (%s) fallo, %s",
                    getattr(provider, "model", provider.name),
                    provider.name,
                    "probando el siguiente" if index + 1 < len(self.providers) else "no quedan más",
                )
        raise LLMError(str(last))


def get_llm_provider(provider: str, api_key: str, model: str, base_url: str | None = None) -> LLMProvider:
    # Varios modelos separados por coma = cadena con reserva, en ese orden.
    if "," in (model or ""):
        chain = [
            _single_provider(provider, api_key, name.strip(), base_url)
            for name in model.split(",")
            if name.strip()
        ]
        if len(chain) > 1:
            return FallbackLLMProvider(chain)
        if chain:
            return chain[0]
    return _single_provider(provider, api_key, model, base_url)


def _single_provider(provider: str, api_key: str, model: str, base_url: str | None = None) -> LLMProvider:
    provider = (provider or "").lower()
    if provider == "anthropic":
        return AnthropicProvider(api_key, model)
    if provider == "openai":
        return OpenAICompatibleProvider("openai", base_url or "https://api.openai.com/v1", api_key, model)
    if provider == "groq":
        return OpenAICompatibleProvider("groq", base_url or "https://api.groq.com/openai/v1", api_key, model)
    if provider == "openrouter":
        return OpenAICompatibleProvider("openrouter", base_url or "https://openrouter.ai/api/v1", api_key, model)
    if provider == "orcarouter":
        return OpenAICompatibleProvider(
            "orcarouter", base_url or "https://api.orcarouter.ai/v1", api_key, model
        )
    if provider == "gmi":
        return OpenAICompatibleProvider(
            "gmi",
            base_url or "https://api.gmi-serving.com/v1",
            api_key,
            model,
            omit_max_tokens=True,
        )
    if provider == "gemini":
        return OpenAICompatibleProvider(
            "gemini",
            base_url or "https://generativelanguage.googleapis.com/v1beta/openai",
            api_key,
            model,
        )
    if provider == "ollama":
        return OpenAICompatibleProvider("ollama", (base_url or "http://localhost:11434") + "/v1", api_key, model)
    if provider == "fake":
        return FakeLLMProvider()
    raise ValueError(f"Proveedor LLM desconocido: {provider}")
