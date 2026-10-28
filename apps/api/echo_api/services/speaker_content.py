"""Dos voces parecidas: quién es quién en cada tramo, por lo que dice cada una.

La unión de tramos por la voz (services/final_chunks.py) separa bien a voces
distintas, pero dos parecidas se confunden: el 27/10, la voz de una docente
cambió hacia el final de la reunión y se parecía más a la de la mamá, y 10
minutos de lo que dijo quedaron como dichos por la mamá. Por el contenido no
hay duda ("sepan que también estamos trabajando" es de la docente).

Solo corre si quedaron dos personas con la voz parecida (`similar_voices`): en
una reunión con voces claras no suma ni un segundo. Se le muestra a la IA qué
dice cada una en un tramo donde hablaron las dos (ahí ElevenLabs ya las separó
y no hay duda de que son dos) y, por cada otro tramo, qué dice cada una de las
dos; la IA decide por el rol y el tema. Pasa por la IA seudonimizada (privacy):
ningún nombre sale de Echo. Si la IA no está segura, queda lo que dijo la voz.
"""
from __future__ import annotations

import logging

from .final_chunks import Chunk
from .llm import LLMError, LLMProvider
from .llm.base import reasoning
from .stt.elevenlabs import group_words

log = logging.getLogger("echo.speaker_content")

# Cuánto de cada persona en cada tramo se le muestra a la IA.
QUOTE_CHARS = 600
REFERENCE_CHARS = 1500
# Pares a revisar como mucho por reunión (cada uno es una consulta).
MAX_PAIRS = 2
# Probado el 28/10 con las reuniones reales del 26/10: la de la docente y la
# mamá pasó de 74 % a 100 % de lo dicho con la persona correcta, ninguna
# empeoró, y la que tenía voces claras no lo corrió. Suma 3-5 s solo ahí.
ENABLED = True

SYSTEM = """Sos un asistente que ayuda a separar quién habló en la transcripción de una reunión de un colegio.
Dos personas de la reunión tienen la voz parecida y el sistema puede haberlas confundido entre tramos.
Te muestro qué dice cada una en un tramo donde hablaron las dos (ahí están bien separadas) y, para otros
tramos, fragmentos que el sistema le atribuyó a una o a la otra.

Para cada fragmento decidí si lo dice la persona A o la persona B, por el CONTENIDO: el rol (docente,
directivo, familia, profesional), si habla del colegio o de la casa, en primera persona de qué, a quién se
dirige, cómo sigue lo que venía diciendo. Si con el contenido no se puede saber, respondé "duda".
No adivines: un "duda" es mejor que equivocarse."""


def _quotes(chunk: Chunk, label: str, limit: int) -> str:
    turns = [segment.text for segment in group_words(chunk.words) if segment.speaker == label and segment.text]
    # Los turnos más largos dicen más del rol que los "sí", "claro".
    picked, size = [], 0
    for text in sorted(turns, key=len, reverse=True):
        if size >= limit:
            break
        picked.append(text[: limit - size])
        size += len(picked[-1])
    return " … ".join(picked)


async def check(
    chunks: list[Chunk],
    mappings: list[dict[str, str]],
    pairs: list[tuple[str, str, float]],
    provider: LLMProvider,
) -> list[dict[str, str]]:
    """Las mismas asignaciones, corregidas donde el contenido dice otra cosa que la voz."""
    if not ENABLED:
        return mappings
    mappings = [dict(mapping) for mapping in mappings]
    for a, b, score in pairs[:MAX_PAIRS]:
        both = [
            position for position, mapping in enumerate(mappings)
            if a in mapping.values() and b in mapping.values()
        ]
        if not both:
            continue

        def label_of(position: int, person: str) -> str | None:
            return next((label for label, p in mappings[position].items() if p == person), None)

        def speech(position: int) -> int:
            chunk = chunks[position]
            mine = {label_of(position, a), label_of(position, b)}
            return sum(w.end_ms - w.start_ms for w in chunk.words if w.speaker in mine)

        reference = max(both, key=speech)
        reference_a = _quotes(chunks[reference], label_of(reference, a), REFERENCE_CHARS)
        reference_b = _quotes(chunks[reference], label_of(reference, b), REFERENCE_CHARS)
        if not reference_a or not reference_b:
            continue
        items: dict[str, tuple[int, str]] = {}
        lines = []
        for position, mapping in enumerate(mappings):
            if position == reference:
                continue
            for label, person in mapping.items():
                if person not in (a, b):
                    continue
                quote = _quotes(chunks[position], label, QUOTE_CHARS)
                if not quote:
                    continue
                key = f"t{position}_{label}"
                items[key] = (position, label)
                lines.append(f'- "{key}" (tramo {position + 1}): {quote}')
        if not items:
            continue
        prompt = (
            f"PERSONA A (tramo {reference + 1}): {reference_a}\n\n"
            f"PERSONA B (tramo {reference + 1}): {reference_b}\n\n"
            "FRAGMENTOS:\n" + "\n".join(lines) + "\n\n"
            'Devolvé JSON: {"<clave>": "A" | "B" | "duda", ...} con todas las claves.'
        )
        try:
            with reasoning("none"):
                answer = await provider.chat_json(SYSTEM, [{"role": "user", "content": prompt}], max_tokens=1500)
        except LLMError as exc:
            log.warning("revisión por contenido falló: %s", exc)
            continue
        if not isinstance(answer, dict):
            continue
        decided: dict[int, dict[str, str]] = {}
        for key, (position, label) in items.items():
            verdict = str(answer.get(key) or "").strip().upper()
            if verdict in ("A", "B"):
                decided.setdefault(position, {})[label] = a if verdict == "A" else b
        changed = 0
        for position, choices in decided.items():
            proposal = {**mappings[position], **choices}
            # Dos personas que ElevenLabs separó en el mismo tramo nunca quedan como una.
            mine = [p for label, p in proposal.items() if p in (a, b)]
            if len(mine) != len(set(mine)):
                continue
            changed += sum(1 for label, person in choices.items() if mappings[position][label] != person)
            mappings[position] = proposal
        log.info("revisión por contenido (%s/%s, voz %.2f): %d de %d fragmentos cambiados",
                 a, b, score, changed, len(items))
    return mappings
