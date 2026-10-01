"""Provider STT de ElevenLabs Scribe (batch): texto, tiempos y quién habló juntos.

Es el motor de la pasada final "con personas" (services/diarization.py). En el
banco del 30/9 (bench/casos/2026-09-30) fue el texto más completo y el único
que separó a las tres personas de la reunión del 27/9 sin un error.

Lo que se le pide (verificado contra la doc de la API, 30/9/2026):
- `language_code` en ISO-639-3 (`spa`): fijo, sin detectar idioma.
- `diarize=true` y `timestamps_granularity=word`: cada palabra trae inicio,
  fin y `speaker_id`. Texto y personas salen del MISMO resultado, así no hay
  que alinear dos transcripciones distintas.
- `tag_audio_events=false`: sin "(risas)" ni "(ruido)" en el acta.
- `keyterms`: el diccionario de la sede (+20% del costo; máx. 1000 términos
  de menos de 50 caracteres y 5 palabras).
- `entity_detection`: nombres, contactos y documentos que se dijeron, para
  sumarlos a la seudonimización antes de mandar nada al LLM.

`enable_logging=false` (retención cero) es solo para Enterprise: no se manda.

Nunca mandar acá audio de reuniones donde hablan menores de 18: la política de
privacidad de ElevenLabs lo prohíbe (docs/plan-transcripcion-y-planes.md, §4).
"""
import logging
import re
import time

import httpx

from .base import (
    SttEntity,
    SttResult,
    SttSegment,
    SttWord,
    TranscriptionProvider,
    post_with_rate_limit,
)

log = logging.getLogger("echo.stt")

URL = "https://api.elevenlabs.io/v1/speech-to-text"

# Echo guarda el idioma en ISO-639-1; Scribe se probó con ISO-639-3.
_ISO3 = {"es": "spa", "en": "eng", "pt": "por", "it": "ita", "fr": "fra", "de": "deu"}

MAX_KEYTERMS = 1000
MAX_KEYTERM_CHARS = 49
MAX_KEYTERM_WORDS = 5

# Categorías de entidades que interesan para la privacidad: datos personales
# (nombres, contactos, documentos) y de salud (diagnósticos de un alumno).
ENTITY_CATEGORIES = ["pii", "phi"]

# Un turno largo se parte en una pausa de esto después de un punto.
TURN_PAUSE_MS = 1500
TURN_MAX_CHARS = 400

_SENTENCE_END = (".", "?", "!", "…")


def language_code(language: str | None) -> str | None:
    if not language or language == "auto":
        return None
    return _ISO3.get(language, language)


def keyterms(vocabulary: list[str] | None) -> list[str]:
    """Los términos del diccionario que la API acepta (los demás darían 422)."""
    out: list[str] = []
    for term in vocabulary or []:
        term = " ".join(term.split())
        if not term or len(term) > MAX_KEYTERM_CHARS or len(term.split()) > MAX_KEYTERM_WORDS:
            continue
        if term not in out:
            out.append(term)
        if len(out) >= MAX_KEYTERMS:
            break
    return out


def _fill_speakers(words: list[SttWord]) -> None:
    """Una palabra sin persona hereda la de la palabra más cercana en el tiempo.

    Con separación de voces no queda ningún turno sin persona: un turno
    "Hablante" suelto en el acta es peor que una palabra mal atribuida.
    """
    known = [index for index, word in enumerate(words) if word.speaker]
    if not known or len(known) == len(words):
        return
    cursor = 0
    for index, word in enumerate(words):
        if word.speaker:
            continue
        while cursor + 1 < len(known) and known[cursor + 1] < index:
            cursor += 1
        candidates = [known[cursor]]
        if cursor + 1 < len(known):
            candidates.append(known[cursor + 1])

        def distance(other: int) -> int:
            neighbor = words[other]
            return max(neighbor.start_ms - word.end_ms, word.start_ms - neighbor.end_ms, 0)

        word.speaker = words[min(candidates, key=distance)].speaker


def group_words(words: list[SttWord]) -> list[SttSegment]:
    """Turnos a partir de las palabras: uno nuevo cuando cambia la persona, o
    después de un punto seguido de una pausa larga (o si el turno ya es largo)."""
    segments: list[SttSegment] = []
    current: list[SttWord] = []

    def close() -> None:
        if current:
            text = " ".join(word.text for word in current)
            segments.append(SttSegment(text, current[0].start_ms, current[-1].end_ms, speaker=current[0].speaker))
            current.clear()

    for word in words:
        if current:
            last = current[-1]
            ended = last.text.endswith(_SENTENCE_END)
            long_enough = sum(len(w.text) + 1 for w in current) >= TURN_MAX_CHARS
            if (
                word.speaker != last.speaker
                or (ended and word.start_ms - last.end_ms >= TURN_PAUSE_MS)
                or (ended and long_enough)
            ):
                close()
        current.append(word)
    close()
    return segments


def parse(payload: dict, offset_ms: int = 0) -> SttResult:
    """Respuesta de Scribe → palabras con persona, turnos y entidades.

    Las personas se renombran en orden de aparición (speaker_1, speaker_2...):
    Scribe numera desde speaker_0 y el resto de Echo cuenta desde 1.
    """
    words: list[SttWord] = []
    names: dict[str, str] = {}
    for item in payload.get("words") or []:
        if item.get("type", "word") != "word":
            continue  # espacios y eventos de audio
        text = (item.get("text") or "").strip()
        if not text:
            continue
        start = item.get("start")
        end = item.get("end")
        start_ms = offset_ms + int(float(start or 0) * 1000)
        end_ms = offset_ms + int(float(end if end is not None else start or 0) * 1000)
        raw = item.get("speaker_id")
        speaker = None
        if raw:
            speaker = names.setdefault(str(raw), f"speaker_{len(names) + 1}")
        logprob = item.get("logprob")
        words.append(SttWord(text, start_ms, max(end_ms, start_ms), speaker, float(logprob) if logprob is not None else None))
    _fill_speakers(words)

    entities = [
        SttEntity(text=" ".join(str(entity.get("text") or "").split()), entity_type=str(entity.get("entity_type") or ""))
        for entity in payload.get("entities") or []
        if str(entity.get("text") or "").strip()
    ]
    segments = group_words(words)
    if not segments and (payload.get("text") or "").strip():
        segments = [SttSegment(" ".join(payload["text"].split()), offset_ms, offset_ms)]
    return SttResult(segments=segments, language=payload.get("language_code"), words=words, entities=entities)


class ElevenLabsProvider(TranscriptionProvider):
    name = "elevenlabs"
    supports_streaming = False

    def __init__(self, api_key: str, model: str = "scribe_v2", diarize: bool = True, detect_entities: bool = True):
        self.api_key = api_key
        self.model = model
        self.diarize = diarize
        self.detect_entities = detect_entities

    def form(self, language: str | None, vocabulary: list[str] | None, num_speakers: int | None = None) -> dict:
        form: dict = {
            "model_id": self.model,
            "timestamps_granularity": "word",
            "tag_audio_events": "false",
            "diarize": "true" if self.diarize else "false",
        }
        code = language_code(language)
        if code:
            form["language_code"] = code
        if self.diarize and num_speakers:
            form["num_speakers"] = str(num_speakers)
        terms = keyterms(vocabulary)
        if terms:
            form["keyterms"] = terms
        if self.detect_entities:
            form["entity_detection"] = ENTITY_CATEGORIES
        return form

    async def _request(self, data: bytes, filename: str, form: dict) -> dict:
        started = time.monotonic()
        async with httpx.AsyncClient(timeout=900) as client:
            response = await post_with_rate_limit(
                client,
                URL,
                headers={"xi-api-key": self.api_key},
                data=form,
                files={"file": (filename, data, _content_type(filename))},
            )
        latency_ms = int((time.monotonic() - started) * 1000)
        log.info("stt elevenlabs model=%s latency_ms=%d status=%d", self.model, latency_ms, response.status_code)
        if response.status_code >= 400:
            log.warning("stt elevenlabs rechazó el pedido: %s", response.text[:300])
        response.raise_for_status()
        return response.json()

    async def transcribe_file(
        self,
        data: bytes,
        filename: str,
        language: str | None,
        vocabulary: list[str] | None = None,
        num_speakers: int | None = None,
    ) -> SttResult:
        payload = await self._request(data, filename, self.form(language, vocabulary, num_speakers))
        return parse(payload)

    async def transcribe_chunk(
        self,
        pcm16: bytes,
        sample_rate: int,
        language: str | None,
        vocabulary: list[str] | None = None,
        offset_ms: int = 0,
        context: str | None = None,
    ) -> SttResult:
        """Cerrado a propósito: ElevenLabs solo recibe la reunión entera en la
        pasada final, y nunca la de una reunión con menores. Un tramo en vivo no
        sabe si hablan menores, así que no se manda (docs/plan-correcciones.md §1.8)."""
        raise RuntimeError("ElevenLabs no transcribe en vivo: solo la pasada final")


def _content_type(filename: str) -> str:
    extension = re.sub(r"^.*\.", "", filename.lower())
    return {"mp3": "audio/mpeg", "m4a": "audio/mp4", "ogg": "audio/ogg", "webm": "audio/webm"}.get(extension, "audio/wav")
