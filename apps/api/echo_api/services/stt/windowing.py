"""Dónde cortar el audio en vivo antes de mandarlo a transcribir.

Antes se cortaba cada 6 s exactos, aunque alguien estuviera a mitad de una
palabra: el modelo recibía media palabra en cada tramo y la perdía (en una
prueba real se perdió "Gracias por venir" entero). Ahora se corta en una pausa
de verdad; si la persona habla de corrido, en el momento más callado de los
últimos segundos. De yapa, un tramo cortado en una pausa suele ser de una sola
persona, que es lo que después permite asignarle hablante.
"""
import numpy as np

FRAME_MS = 100
MIN_MS = 4000  # un tramo más corto transcribe peor: el modelo inventa para completar
MAX_MS = 12000  # más largo demora el texto en vivo
PAUSE_MS = 500  # silencio que cuenta como pausa
SEARCH_MS = 3000  # al llegar al máximo, se busca el corte en los últimos 3 s
MIN_SPEECH_MS = 700  # sin esto de habla no hay nada que mandar todavía
# Piso absoluto de "silencio" en PCM16 (0-32767); el umbral real se adapta al
# ruido de fondo de cada micrófono.
ABS_SILENCE_RMS = 250.0


def _frame_rms(buffer: bytes, sample_rate: int, channels: int) -> np.ndarray:
    samples = np.frombuffer(buffer[: len(buffer) // 2 * 2], dtype=np.int16).astype(np.float32)
    per_frame = sample_rate * channels * FRAME_MS // 1000
    count = len(samples) // per_frame
    if count == 0:
        return np.zeros(0, dtype=np.float32)
    frames = samples[: count * per_frame].reshape(count, per_frame)
    return np.sqrt((frames * frames).mean(axis=1))


def silence_threshold(rms: np.ndarray) -> float:
    """Por debajo de esto es silencio: un poco sobre el ruido de fondo, pero
    muy por debajo del volumen típico de la voz: con la mitad, una persona que
    habla más bajo o más lejos del micrófono contaba como silencio y se le
    cortaba en medio de la frase (pasó en una reunión real)."""
    floor = float(np.percentile(rms, 20))
    loud = float(np.percentile(rms, 90))
    return max(ABS_SILENCE_RMS, min(floor * 1.8, loud * 0.25))


def find_cut(buffer: bytes, sample_rate: int = 16000, channels: int = 1) -> int | None:
    """Cuántos bytes del buffer transcribir ahora, o None para seguir juntando."""
    bytes_per_frame = sample_rate * channels * 2 * FRAME_MS // 1000
    rms = _frame_rms(buffer, sample_rate, channels)
    total_ms = len(rms) * FRAME_MS
    if total_ms < MIN_MS:
        return None

    threshold = silence_threshold(rms)
    speech = rms > threshold

    pause_frames = PAUSE_MS // FRAME_MS
    if (
        len(rms) >= pause_frames
        and not speech[-pause_frames:].any()
        and speech.sum() * FRAME_MS >= MIN_SPEECH_MS
    ):
        # Terminó de hablar: se corta en la mitad de la pausa, así el tramo
        # siguiente no arranca pegado a la última sílaba.
        return (len(rms) - pause_frames // 2) * bytes_per_frame

    if total_ms >= MAX_MS:
        start = max(0, len(rms) - SEARCH_MS // FRAME_MS)
        quietest = start + int(np.argmin(rms[start:]))
        return max(1, quietest) * bytes_per_frame
    return None
