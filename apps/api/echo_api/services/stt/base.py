"""Abstracción TranscriptionProvider.

Dos modos de uso:
  - transcribe_chunk(pcm16, ...): transcripción incremental de una ventana de
    audio en RAM (modo live cloud). El audio se descarta al retornar.
  - transcribe_file(data, ...): transcripción de un archivo importado. El
    caller es responsable de borrar el archivo/bytes después.

El provider "bridge" NO existe del lado del servidor: en modo bridge el audio
nunca llega al API (el browser habla con Echo Bridge en localhost y sube solo
texto). Acá viven los providers cloud y el fake para tests.
"""
from __future__ import annotations

import io
import struct
from dataclasses import dataclass, field


@dataclass
class SttSegment:
    text: str
    start_ms: int
    end_ms: int
    confidence: float | None = None
    # Etiqueta de hablante del motor ("A", "B", "speaker_0"…). El pipeline la
    # agrupa en filas Speaker. None = el motor no diariza.
    speaker: str | None = None


@dataclass
class SttResult:
    segments: list[SttSegment] = field(default_factory=list)
    language: str | None = None

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.segments).strip()


class TranscriptionProvider:
    name = "base"
    supports_streaming = False

    async def transcribe_chunk(
        self,
        pcm16: bytes,
        sample_rate: int,
        language: str | None,
        vocabulary: list[str] | None = None,
        offset_ms: int = 0,
        context: str | None = None,
    ) -> SttResult:
        raise NotImplementedError

    async def transcribe_file(
        self,
        data: bytes,
        filename: str,
        language: str | None,
        vocabulary: list[str] | None = None,
    ) -> SttResult:
        raise NotImplementedError


def pcm16_to_wav(pcm16: bytes, sample_rate: int, channels: int = 1) -> bytes:
    """Empaqueta PCM16 crudo como WAV en memoria (sin tocar disco)."""
    buffer = io.BytesIO()
    data_size = len(pcm16)
    byte_rate = sample_rate * channels * 2
    buffer.write(b"RIFF")
    buffer.write(struct.pack("<I", 36 + data_size))
    buffer.write(b"WAVEfmt ")
    buffer.write(struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, channels * 2, 16))
    buffer.write(b"data")
    buffer.write(struct.pack("<I", data_size))
    buffer.write(pcm16)
    return buffer.getvalue()


OPENAI_LIVE_MODEL = "gpt-4o-transcribe"
OPENAI_FILE_MODEL = "gpt-4o-transcribe-diarize"


def get_stt_provider(provider: str, api_key: str, model: str | None = None) -> TranscriptionProvider:
    from .fake import FakeSttProvider
    from .whisper_api import WhisperApiProvider

    provider = (provider or "").lower()
    if provider == "openai":
        # Sin modelo elegido por la sede: en vivo el que mejor transcribe y
        # respeta el diccionario; un archivo entero, el que separa hablantes
        # (ver whisper_api.py). Un modelo elegido a mano se usa para los dos.
        return WhisperApiProvider(
            name="openai",
            base_url="https://api.openai.com/v1",
            api_key=api_key,
            model=model or OPENAI_LIVE_MODEL,
            file_model=model or OPENAI_FILE_MODEL,
        )
    if provider == "groq":
        return WhisperApiProvider(
            name="groq",
            base_url="https://api.groq.com/openai/v1",
            api_key=api_key,
            model=model or "whisper-large-v3-turbo",
        )
    if provider == "deepgram":
        from .deepgram import DeepgramProvider

        return DeepgramProvider(api_key=api_key, model=model or "nova-2")
    if provider == "fake":
        return FakeSttProvider()
    raise ValueError(f"Proveedor STT desconocido: {provider}")
