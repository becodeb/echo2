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
import re

import numpy as np

# Etiquetas que consume el pipeline: "speaker_N" → "Speaker N".
MIC_SPEAKER = "speaker_1"
SYSTEM_SPEAKER = "speaker_2"

# Debajo de esto un canal se considera en silencio. PCM16 va de 0 a 32767;
# 300 deja pasar habla suave y corta el ruido de fondo de un micrófono abierto.
SILENCE_RMS = 300.0

# Un tramo es silencio si tiene menos habla que esto, contada en ventanas de
# 100 ms que superan SILENCE_RMS. Antes se promediaba el tramo entero: un "Sí,
# de acuerdo" de 1 s en un tramo de 4 s bajaba el promedio a menos de la
# mitad, y el tramo se tiraba sin llegar a transcribirse.
FRAME_MS = 100
MIN_VOICED_MS = 300

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
    "subtítulos en español",
    "subtitulos en español",
    "subtítulos hechos por",
    "suscríbete",
    "suscribete",
    "no olvides suscribirte",
    "dale like",
    "activa la campanita",
)

# Oraciones que, SOLAS, son lo que Whisper escribe sobre silencio o música
# (visto en producción y en el banco). Dentro de una frase más larga no se tocan.
HALLUCINATION_SENTENCES = {
    "amén", "amen", "música", "musica", "aplausos", "risas",
    "gracias por ver", "gracias por mirar",
    # En inglés aunque se pida castellano: los clásicos de Whisper sobre ruido.
    "you", "thank you", "thanks", "bye", "thank you very much",
}

# Signos que se sacan antes de comparar: puntuación y los guiones de diálogo
# de subtítulos ("- Hola. - Hola.").
_EDGE = ".!¡¿?,;:…-–—\"' "


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
    """Tramo sin habla: no tiene sentido gastar una llamada de STT."""
    samples = np.frombuffer(pcm16[: len(pcm16) // 2 * 2], dtype=np.int16).astype(np.float32)
    frame = max(1, sample_rate * FRAME_MS // 1000)
    count = len(samples) // frame
    if count == 0:
        return rms(pcm16, sample_rate=sample_rate) < SILENCE_RMS
    frames = samples[: count * frame].reshape(count, frame)
    voiced = np.sqrt((frames * frames).mean(axis=1)) >= SILENCE_RMS
    return int(voiced.sum()) * FRAME_MS < min(MIN_VOICED_MS, count * FRAME_MS)


def is_hallucination(text: str) -> bool:
    """Texto que Whisper inventa sobre silencio, no algo que alguien dijo."""
    normalized = " ".join(text.strip().lower().strip(_EDGE).split())
    if not normalized:
        return True
    if normalized in HALLUCINATION_SENTENCES:
        return True
    return any(marker in normalized for marker in HALLUCINATION_MARKERS)


def _clean_sentence(sentence: str) -> str:
    """Sin el guion de diálogo de subtítulos adelante ("- Hola." → "Hola.")."""
    return re.sub(r"^[-–—]+\s*", "", sentence.strip()).strip()


# Una frase repetida seguida más de esto es un bucle del modelo, no habla: en
# el banco "¿Cómo estás?" salió 100 veces; alguien que prueba el micrófono
# repite "uno dos tres probando" 5.
MAX_REPEATS = 5
_MAX_LOOP_WORDS = 8


def collapse_loops(text: str) -> str:
    """Deja una sola vez una frase que el modelo repitió en bucle."""
    tokens = (text or "").split()
    if len(tokens) < MAX_REPEATS + 1:
        return (text or "").strip()
    norm = [token.lower().strip(_EDGE) for token in tokens]
    out: list[str] = []
    index = 0
    while index < len(tokens):
        collapsed = False
        for size in range(1, _MAX_LOOP_WORDS + 1):
            unit = norm[index:index + size]
            if len(unit) < size or not any(unit):
                break
            repeats = 1
            while norm[index + repeats * size:index + (repeats + 1) * size] == unit:
                repeats += 1
            if repeats > MAX_REPEATS:
                out.extend(tokens[index:index + size])
                index += repeats * size
                collapsed = True
                break
        if not collapsed:
            out.append(tokens[index])
            index += 1
    return " ".join(out)


def strip_hallucinations(text: str) -> str:
    """El texto sin las oraciones inventadas ni los bucles.

    Los modelos de solo texto devuelven UN texto por tramo de 4-12 s: si al
    final le pegan "Subtítulos realizados por la comunidad de Amara.org",
    descartarlo entero se llevaba también lo que alguien dijo de verdad.
    """
    sentences = re.split(r"(?<=[.!?…])\s+", collapse_loops(text))
    kept = [_clean_sentence(sentence) for sentence in sentences if sentence and not is_hallucination(sentence)]
    return " ".join(sentence for sentence in kept if sentence).strip()


# Umbrales de Whisper (los mismos que usa su propio decodificador): mucha
# probabilidad de silencio con poca confianza es un tramo sin habla que el
# modelo "completó".
NO_SPEECH_PROB = 0.6
LOW_LOGPROB = -1.0
# Muy por debajo de esto el texto es ruido aunque el modelo crea que hubo habla.
VERY_LOW_LOGPROB = -1.5


def is_unreliable(segment) -> bool:
    """Una frase que el propio modelo marca como probablemente inventada.

    Solo con las señales de verbose_json (Groq, whisper-1); sin ellas, nunca.
    """
    no_speech = getattr(segment, "no_speech_prob", None)
    logprob = getattr(segment, "avg_logprob", None)
    if logprob is None:
        return False
    if no_speech is not None and no_speech >= NO_SPEECH_PROB and logprob < LOW_LOGPROB:
        return True
    return logprob < VERY_LOW_LOGPROB


def is_prompt_echo(text: str, vocabulary: list[str] | None) -> bool:
    """El modelo "leyó" el diccionario en vez de transcribir.

    Con el diccionario de la sede como prompt, sobre un tramo casi mudo el
    modelo a veces devuelve una palabra del diccionario sola (en una prueba
    real, "Gibson" en el último segundo de silencio). Unas pocas palabras que
    son todas del diccionario no es habla.
    """
    if not vocabulary:
        return False
    words = [w for w in "".join(c.lower() if c.isalnum() else " " for c in text).split() if w]
    if not words or len(words) > 4:
        return False
    known = {w for term in vocabulary for w in "".join(c.lower() if c.isalnum() else " " for c in term).split()}
    return all(word in known for word in words)


def _words(text: str) -> list[str]:
    return "".join(c.lower() if c.isalnum() else " " for c in text or "").split()


# Menos palabras que esto pueden repetirse de verdad ("Sí, dale." dos veces).
MIN_REPEAT_WORDS = 3


def repeats_previous(text: str, previous: str | None) -> bool:
    """El tramo es el anterior otra vez, palabra por palabra.

    Sobre un tramo casi mudo el modelo a veces devuelve lo último que oyó en
    vez de lo que hay (reunión eb3ce903, 02:10). Una frase corta repetida
    puede ser real, así que solo cuenta desde MIN_REPEAT_WORDS palabras.
    """
    words = _words(text)
    return len(words) >= MIN_REPEAT_WORDS and words == _words(previous or "")


# Lo que los modelos devuelven sobre ruido en vez de habla: descripciones de
# sonidos en inglés (vistas en producción: "click", "crackling", "reverberations").
_SOUND_WORDS = {
    "click", "clicks", "crackling", "reverberations", "reverberation", "static", "noise",
    "music", "applause", "laughter", "silence", "beep", "beeping", "breathing", "hum", "buzzing",
}
_LATIN_LANGUAGES = {"es", "en", "pt", "it", "fr", "de"}


def is_noise_transcript(text: str, language: str | None) -> bool:
    """Texto que no puede ser lo que se dijo en una reunión en ese idioma.

    En una reunión en castellano, un tramo escrito en otro alfabeto (árabe,
    chino, hebreo, cirílico, cingalés...) es el modelo adivinando sobre ruido,
    no alguien que habló. Lo mismo una sola palabra que describe un sonido.
    """
    stripped = text.strip().strip(".,;:!?¡¿。、…").strip()
    if not stripped:
        return True
    if stripped.lower() in _SOUND_WORDS:
        return True
    if (language or "es") not in _LATIN_LANGUAGES:
        return False
    letters = [char for char in stripped if char.isalpha()]
    if not letters:
        return True
    latin = sum(1 for char in letters if ord(char) < 0x250)
    return latin / len(letters) < 0.5
