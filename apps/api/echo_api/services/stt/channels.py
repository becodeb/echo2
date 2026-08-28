"""Atribución de hablante por canal y filtro de alucinaciones de Whisper.

Cuando el navegador captura micrófono + audio del sistema (Meet, Zoom, Teams,
Discord), manda PCM16 intercalado con L=micrófono y R=sistema. Tener las dos
fuentes separadas hace que saber quién habló sea una medición de energía, no
una predicción: es estable entre chunks y no depende de ningún modelo de
diarización. Si se mezclaran antes de enviarlas, esa información se pierde y
no hay forma de recuperarla.
"""
from __future__ import annotations

import array

# Etiquetas que consume el pipeline: "speaker_N" → "Speaker N".
MIC_SPEAKER = "speaker_1"
SYSTEM_SPEAKER = "speaker_2"

# Debajo de esto un canal se considera en silencio. PCM16 va de 0 a 32767;
# 300 deja pasar habla suave y corta el ruido de fondo de un micrófono abierto.
SILENCE_RMS = 300.0

# Un canal gana solo si domina claramente; con ambos parecidos (diafonía del
# parlante entrando al micrófono) no se arriesga una atribución.
DOMINANCE_RATIO = 1.6

# Whisper fue entrenado con subtítulos y sobre silencio devuelve créditos de
# comunidades de subtitulado. Son alucinaciones, no habla.
HALLUCINATION_MARKERS = (
    "amara.org",
    "subtítulos realizados por",
    "subtitulos realizados por",
    "subtítulos por la comunidad",
    "subtitulado por",
    "www.subtitulamos.tv",
    "subscribe to my channel",
    "thanks for watching",
    "gracias por ver el video",
    "¡gracias por ver el video!",
)


def split_channels(pcm16_stereo: bytes) -> tuple[bytes, bytes]:
    """Separa PCM16 intercalado (L,R,L,R…) en dos buffers mono."""
    samples = array.array("h")
    samples.frombytes(pcm16_stereo[: len(pcm16_stereo) // 4 * 4])
    left = array.array("h", samples[0::2])
    right = array.array("h", samples[1::2])
    return left.tobytes(), right.tobytes()


def downmix(left: bytes, right: bytes) -> bytes:
    """Promedia los dos canales para mandar UN audio al motor de STT."""
    a = array.array("h")
    a.frombytes(left)
    b = array.array("h")
    b.frombytes(right)
    size = min(len(a), len(b))
    mixed = array.array("h", (0,) * size)
    for index in range(size):
        mixed[index] = int((a[index] + b[index]) / 2)
    return mixed.tobytes()


def rms(pcm16: bytes, start_ms: int = 0, end_ms: int | None = None, sample_rate: int = 16000) -> float:
    """RMS de una ventana del audio (en ms relativos al buffer)."""
    samples = array.array("h")
    samples.frombytes(pcm16[: len(pcm16) // 2 * 2])
    first = max(0, int(start_ms * sample_rate / 1000))
    last = len(samples) if end_ms is None else min(len(samples), int(end_ms * sample_rate / 1000))
    if last <= first:
        return 0.0
    total = 0.0
    for index in range(first, last):
        value = samples[index]
        total += value * value
    return (total / (last - first)) ** 0.5


def attribute_speaker(
    mic: bytes,
    system: bytes,
    start_ms: int,
    end_ms: int,
    sample_rate: int = 16000,
) -> str | None:
    """Quién habló en esa ventana, comparando energía de cada canal.

    Devuelve None cuando ninguno domina: es preferible dejar el segmento sin
    hablante a etiquetarlo mal.
    """
    mic_level = rms(mic, start_ms, end_ms, sample_rate)
    system_level = rms(system, start_ms, end_ms, sample_rate)
    if mic_level < SILENCE_RMS and system_level < SILENCE_RMS:
        return None
    if mic_level >= system_level * DOMINANCE_RATIO:
        return MIC_SPEAKER
    if system_level >= mic_level * DOMINANCE_RATIO:
        return SYSTEM_SPEAKER
    return None


def is_silent(pcm16: bytes, sample_rate: int = 16000) -> bool:
    """Ventana sin habla: no tiene sentido gastar una llamada de STT."""
    return rms(pcm16, sample_rate=sample_rate) < SILENCE_RMS


def is_hallucination(text: str) -> bool:
    """Texto que Whisper inventa sobre silencio, no algo que alguien dijo."""
    normalized = text.strip().lower().strip(".!¡¿? ")
    if not normalized:
        return True
    return any(marker in normalized for marker in HALLUCINATION_MARKERS)
