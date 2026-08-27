"""Provider STT fake — SOLO para tests automatizados.

Nunca se ofrece en la UI de producción: get_stt_provider("fake") se usa
exclusivamente desde la suite de tests para probar el flujo end-to-end
sin depender de un servicio externo.
"""
from .base import SttResult, SttSegment, TranscriptionProvider


class FakeSttProvider(TranscriptionProvider):
    name = "fake"
    supports_streaming = True

    def __init__(self, script: list[str] | None = None):
        self.script = script or []
        self._index = 0

    async def transcribe_chunk(
        self, pcm16, sample_rate, language, vocabulary=None, offset_ms=0
    ) -> SttResult:
        duration_ms = int(len(pcm16) / 2 / sample_rate * 1000)
        if self._index < len(self.script):
            text = self.script[self._index]
            self._index += 1
        else:
            text = f"[audio de {duration_ms} ms]"
        return SttResult(
            segments=[
                SttSegment(text=text, start_ms=offset_ms, end_ms=offset_ms + duration_ms, confidence=0.99)
            ],
            language=language,
        )

    async def transcribe_file(self, data, filename, language, vocabulary=None) -> SttResult:
        return SttResult(
            segments=[
                SttSegment(
                    text=" ".join(self.script) or "[transcripción fake de archivo]",
                    start_ms=0,
                    end_ms=60000,
                    confidence=0.99,
                )
            ],
            language=language,
        )
