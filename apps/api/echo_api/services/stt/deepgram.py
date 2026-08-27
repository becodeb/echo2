"""Provider STT Deepgram (REST prerecorded; el audio viaja y se descarta)."""
import logging

import httpx

from .base import SttResult, SttSegment, TranscriptionProvider, pcm16_to_wav

log = logging.getLogger("echo.stt")


class DeepgramProvider(TranscriptionProvider):
    name = "deepgram"
    supports_streaming = False  # streaming WS de Deepgram: previsto a futuro

    def __init__(self, api_key: str, model: str = "nova-2"):
        self.api_key = api_key
        self.model = model

    async def _request(self, data: bytes, content_type: str, language: str | None, vocabulary) -> dict:
        params = {
            "model": self.model,
            "smart_format": "true",
            "utterances": "true",
            "punctuate": "true",
        }
        if language and language != "auto":
            params["language"] = language
        else:
            params["detect_language"] = "true"
        if vocabulary:
            params["keywords"] = [f"{term}:2" for term in vocabulary[:50]]
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                "https://api.deepgram.com/v1/listen",
                params=params,
                headers={"Authorization": f"Token {self.api_key}", "Content-Type": content_type},
                content=data,
            )
        response.raise_for_status()
        return response.json()

    def _parse(self, payload: dict, offset_ms: int) -> SttResult:
        result = SttResult()
        utterances = (payload.get("results") or {}).get("utterances") or []
        if utterances:
            for utt in utterances:
                text = (utt.get("transcript") or "").strip()
                if not text:
                    continue
                result.segments.append(
                    SttSegment(
                        text=text,
                        start_ms=offset_ms + int(float(utt.get("start", 0)) * 1000),
                        end_ms=offset_ms + int(float(utt.get("end", 0)) * 1000),
                        confidence=utt.get("confidence"),
                    )
                )
        else:
            channels = (payload.get("results") or {}).get("channels") or []
            if channels:
                alt = (channels[0].get("alternatives") or [{}])[0]
                text = (alt.get("transcript") or "").strip()
                if text:
                    result.segments.append(
                        SttSegment(
                            text=text,
                            start_ms=offset_ms,
                            end_ms=offset_ms,
                            confidence=alt.get("confidence"),
                        )
                    )
        return result

    async def transcribe_chunk(
        self, pcm16, sample_rate, language, vocabulary=None, offset_ms=0
    ) -> SttResult:
        wav = pcm16_to_wav(pcm16, sample_rate)
        payload = await self._request(wav, "audio/wav", language, vocabulary)
        return self._parse(payload, offset_ms)

    async def transcribe_file(self, data, filename, language, vocabulary=None) -> SttResult:
        content_type = "audio/wav"
        lowered = filename.lower()
        if lowered.endswith(".mp3"):
            content_type = "audio/mpeg"
        elif lowered.endswith(".m4a") or lowered.endswith(".mp4"):
            content_type = "audio/mp4"
        elif lowered.endswith(".webm"):
            content_type = "audio/webm"
        payload = await self._request(data, content_type, language, vocabulary)
        return self._parse(payload, 0)
