"""Provider STT para APIs compatibles con Whisper (OpenAI, Groq).

El audio viaja en memoria (multipart) y no se persiste nunca.
"""
import logging
import time

import httpx

from .base import SttResult, SttSegment, TranscriptionProvider, pcm16_to_wav

log = logging.getLogger("echo.stt")


class WhisperApiProvider(TranscriptionProvider):
    supports_streaming = False

    def __init__(self, name: str, base_url: str, api_key: str, model: str):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    async def _request(
        self,
        data: bytes,
        filename: str,
        language: str | None,
        vocabulary: list[str] | None,
    ) -> dict:
        form: dict = {"model": self.model, "response_format": "verbose_json"}
        if language and language != "auto":
            form["language"] = language
        if vocabulary:
            # vocabulary bias vía prompt (soportado por la API de Whisper)
            form["prompt"] = ", ".join(vocabulary[:80])
        started = time.monotonic()
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{self.base_url}/audio/transcriptions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                data=form,
                files={"file": (filename, data, "audio/wav")},
            )
        latency_ms = int((time.monotonic() - started) * 1000)
        log.info("stt %s latency_ms=%d status=%d", self.name, latency_ms, response.status_code)
        response.raise_for_status()
        return response.json()

    def _parse(self, payload: dict, offset_ms: int) -> SttResult:
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
                result.segments.append(
                    SttSegment(
                        text=text,
                        start_ms=offset_ms + int(float(seg.get("start", 0)) * 1000),
                        end_ms=offset_ms + int(float(seg.get("end", 0)) * 1000),
                        confidence=confidence,
                    )
                )
        elif payload.get("text"):
            result.segments.append(
                SttSegment(text=payload["text"].strip(), start_ms=offset_ms, end_ms=offset_ms)
            )
        return result

    async def transcribe_chunk(
        self,
        pcm16: bytes,
        sample_rate: int,
        language: str | None,
        vocabulary: list[str] | None = None,
        offset_ms: int = 0,
    ) -> SttResult:
        wav = pcm16_to_wav(pcm16, sample_rate)
        payload = await self._request(wav, "chunk.wav", language, vocabulary)
        return self._parse(payload, offset_ms)

    async def transcribe_file(
        self,
        data: bytes,
        filename: str,
        language: str | None,
        vocabulary: list[str] | None = None,
    ) -> SttResult:
        payload = await self._request(data, filename, language, vocabulary)
        return self._parse(payload, 0)
