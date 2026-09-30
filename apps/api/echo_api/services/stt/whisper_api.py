"""Provider STT para APIs compatibles con Whisper (OpenAI, Groq).

El audio viaja en memoria (multipart) y no se persiste nunca.

Cada familia de modelos pide cosas distintas (verificado contra la API):
- whisper-1 / whisper-large-v3-turbo: `verbose_json`, con frases y tiempos;
  aceptan idioma y el diccionario como prompt.
- gpt-4o-transcribe / gpt-4o-mini-transcribe / gpt-transcribe: solo `json` o
  `text` (con `verbose_json` la API devuelve 400). Transcriben mejor y aceptan
  idioma y diccionario, pero devuelven el texto sin frases ni tiempos.
- *-transcribe-diarize: `diarized_json`, con frases, tiempos y hablante. NO
  aceptan prompt (400) ni idioma, así que el diccionario no llega.

Por eso el default de OpenAI usa dos modelos: en vivo (tramos de 4 a 12 s, cortados en las pausas) el que
mejor transcribe y respeta el diccionario, y para un archivo entero el que
separa hablantes, que solo es consistente cuando ve todo el audio junto.
"""
import logging
import time

import httpx

from .base import SttResult, SttSegment, TranscriptionProvider, pcm16_to_wav

log = logging.getLogger("echo.stt")

# Modelos que solo devuelven texto plano (`json`), sin frases ni tiempos.
_TEXT_ONLY_PREFIXES = ("gpt-4o-transcribe", "gpt-4o-mini-transcribe", "gpt-transcribe")


def build_prompt(vocabulary: list[str] | None, context: str | None = None) -> str | None:
    """Prompt de transcripción: términos del diccionario y lo último que se dijo."""
    parts = []
    if vocabulary:
        parts.append(", ".join(vocabulary[:80]) + ".")
    if context:
        parts.append(context.strip()[-300:])
    return " ".join(parts) or None


def is_diarize_model(model: str) -> bool:
    return "diarize" in model


def response_format_for(model: str) -> str:
    if is_diarize_model(model):
        return "diarized_json"
    if model.startswith(_TEXT_ONLY_PREFIXES):
        return "json"
    return "verbose_json"


class WhisperApiProvider(TranscriptionProvider):
    supports_streaming = False

    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str,
        model: str,
        file_model: str | None = None,
        temperature: float | None = None,
    ):
        self.name = name
        self.temperature = temperature
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        # Para archivos enteros (importar una grabación) puede convenir otro.
        self.file_model = file_model or model

    @property
    def diarizes(self) -> bool:
        return is_diarize_model(self.model)

    async def _request(
        self,
        data: bytes,
        filename: str,
        language: str | None,
        vocabulary: list[str] | None,
        model: str,
        context: str | None = None,
    ) -> dict:
        form: dict = {"model": model, "response_format": response_format_for(model)}
        if self.temperature is not None:
            form["temperature"] = str(self.temperature)
        if is_diarize_model(model):
            # Sin prompt ni idioma: la API los rechaza. Audio de más de 30 s
            # pide una estrategia de cortes.
            form["chunking_strategy"] = "auto"
        else:
            if language and language != "auto":
                form["language"] = language
            # El diccionario de la sede (apellidos, programas) y lo último que
            # se dijo van como prompt: con tramos cortos, sin ese contexto el
            # modelo "completa" con frases inventadas.
            prompt = build_prompt(vocabulary, context)
            if prompt:
                form["prompt"] = prompt
        started = time.monotonic()
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(
                f"{self.base_url}/audio/transcriptions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                data=form,
                files={"file": (filename, data, "audio/wav")},
            )
        latency_ms = int((time.monotonic() - started) * 1000)
        log.info("stt %s model=%s latency_ms=%d status=%d", self.name, model, latency_ms, response.status_code)
        if response.status_code >= 400:
            log.warning("stt %s rechazó el pedido: %s", self.name, response.text[:300])
        response.raise_for_status()
        return response.json()

    def _parse(self, payload: dict, offset_ms: int, duration_ms: int | None = None) -> SttResult:
        result = SttResult(language=payload.get("language"))
        segments = payload.get("segments") or []
        if segments:
            for seg in segments:
                text = (seg.get("text") or "").strip()
                if not text:
                    continue
                # avg_logprob de whisper ≈ confianza; se mapea a [0,1] aproximado
                confidence = None
                if seg.get("avg_logprob") is not None:
                    confidence = max(0.0, min(1.0, 1.0 + float(seg["avg_logprob"]) / 2.0))
                speaker = seg.get("speaker")
                result.segments.append(
                    SttSegment(
                        text=text,
                        start_ms=offset_ms + int(float(seg.get("start", 0)) * 1000),
                        end_ms=offset_ms + int(float(seg.get("end", 0)) * 1000),
                        confidence=confidence,
                        speaker=f"Speaker {speaker}" if speaker else None,
                    )
                )
        elif payload.get("text"):
            # Modelos de solo texto: una frase que ocupa todo el tramo.
            end_ms = offset_ms + (duration_ms or 0)
            result.segments.append(
                SttSegment(text=" ".join(payload["text"].split()), start_ms=offset_ms, end_ms=end_ms)
            )
        return result

    async def transcribe_chunk(
        self,
        pcm16: bytes,
        sample_rate: int,
        language: str | None,
        vocabulary: list[str] | None = None,
        offset_ms: int = 0,
        context: str | None = None,
    ) -> SttResult:
        wav = pcm16_to_wav(pcm16, sample_rate)
        payload = await self._request(wav, "chunk.wav", language, vocabulary, self.model, context)
        duration_ms = int(len(pcm16) / 2 / sample_rate * 1000)
        return self._parse(payload, offset_ms, duration_ms)

    async def transcribe_file(
        self,
        data: bytes,
        filename: str,
        language: str | None,
        vocabulary: list[str] | None = None,
    ) -> SttResult:
        payload = await self._request(data, filename, language, vocabulary, self.file_model)
        duration = payload.get("duration")
        return self._parse(payload, 0, int(float(duration) * 1000) if duration else None)
