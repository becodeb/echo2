"""Unión de tramos por la voz, simulada sobre reuniones ya separadas (sin pagar ElevenLabs).

Las reuniones transcriptas enteras de una vez (antes del 27/10, o una de
referencia) ya tienen a cada persona con una sola etiqueta. Con su audio:
- se corta en tramos como en producción (en silencio, cada 5 o 2 minutos),
- en cada tramo las personas se renumeran al azar (lo que hace ElevenLabs),
- se saca la huella de cada una y se unen con `final_chunks.link_voices`,
- y se compara con la etiqueta real de cada turno.

No reemplaza una pasada real por tramos (ahí ElevenLabs además puede separar
distinto dentro de un tramo), pero prueba la unión, que es lo que fallaba, con
cualquier cantidad de cortes y sin costo: solo CPU.

`simulate(pcm, turns)` es puro; el script de producción le pasa los turnos de
la base y el audio guardado.
"""
from __future__ import annotations

import itertools
import random

import numpy as np

from echo_api.services import final_chunks as fc
from echo_api.services import voiceprint
from echo_api.services.stt.base import SttWord


def cuts_for(pcm: bytes, total_ms: int, size: int) -> list[int]:
    cuts: list[int] = []
    while True:
        start = cuts[-1] if cuts else 0
        if total_ms - start <= size + min(fc.TAIL_SLACK_MS, size // 5):
            return cuts
        target = start + size
        search = target - min(fc.CUT_SEARCH_MS, size // 10)
        cuts.append(fc.quiet_point(pcm[search * 32:target * 32], search))


def build_chunks(pcm: bytes, turns: list[tuple[str, int, int]], size: int, seed: int, cache: dict) -> tuple[list[fc.Chunk], list[dict[str, str]]]:
    """Tramos con las personas renumeradas al azar; y, por tramo, etiqueta → persona real."""
    total_ms = len(pcm) // 32
    cuts = cuts_for(pcm, total_ms, size)
    spans = fc.spans({"mode": "voice", "cuts": cuts}, total_ms)
    rng = random.Random(seed)
    chunks, truth = [], []
    for index, (start, end) in enumerate(spans):
        mine = [(who, s, min(e, end)) for who, s, e in turns if start <= s < end]
        people = list(dict.fromkeys(who for who, _, _ in mine))
        labels = [f"speaker_{n}" for n in range(len(people))]
        rng.shuffle(labels)
        relabel = dict(zip(people, labels, strict=True))
        words = [SttWord("x", s, e, relabel[who]) for who, s, e in mine]
        key = (start, end, tuple((who, s, e) for who, s, e in mine))
        if key not in cache:
            relative = [SttWord("x", s - start, e - start, who) for who, s, e in mine]
            by_person = fc.chunk_voices(pcm[start * 32:end * 32], relative)
            cache[key] = by_person
        voices = {relabel[who]: data for who, data in cache[key].items()}
        chunks.append(fc.Chunk(index, start, end, "elevenlabs", "es", words, [], [], voices))
        truth.append({label: who for who, label in relabel.items()})
    return chunks, truth


def evaluate(chunks: list[fc.Chunk], truth: list[dict[str, str]]) -> dict:
    mappings, _ = fc.link_voices(chunks)
    time: dict[tuple[str, str], int] = {}
    for chunk, mapping, real in zip(chunks, mappings, truth, strict=True):
        for word in chunk.words:
            key = (real[word.speaker], mapping[word.speaker])
            time[key] = time.get(key, 0) + (word.end_ms - word.start_ms)
    refs = sorted({r for r, _ in time})
    outs = sorted({o for _, o in time})
    total = sum(time.values()) or 1
    rows, cols = (refs, outs) if len(refs) <= len(outs) else (outs, refs)
    cost = [[-time.get((r, c) if rows is refs else (c, r), 0) for c in cols] for r in rows]
    best = -sum(cost[i][j] for i, j in enumerate(voiceprint._hungarian(cost))) if rows else 0
    mixes = 0
    for o in outs:
        own = sum(time.get((r, o), 0) for r in refs)
        if sum(1 for r in refs if time.get((r, o), 0) >= max(3000, 0.1 * own)) > 1:
            mixes += 1
    real_people = [r for r in refs if sum(time.get((r, o), 0) for o in outs) >= 5000]
    # Personas de más: cuántas etiquetas finales con al menos 5 s, de más sobre las reales.
    found = [o for o in outs if sum(time.get((r, o), 0) for r in refs) >= 5000]
    return {
        "reales": len(real_people), "personas": len(found), "todas": len(outs),
        "exactitud": round(best / total, 4), "mezclas": mixes,
    }


def similarity_stats(cases: list[tuple[list[fc.Chunk], list[dict[str, str]]]]) -> dict[str, list[float]]:
    same, other = [], []
    for chunks, truth in cases:
        labeled = [
            (chunk.index, real[label], np.asarray(data["vector"]), data["ms"])
            for chunk, real in zip(chunks, truth, strict=True)
            for label, data in chunk.voices.items()
        ]
        for (ca, ra, va, ma), (cb, rb, vb, mb) in itertools.combinations(labeled, 2):
            if ca != cb:
                (same if ra == rb else other).append((float(va @ vb), min(ma, mb)))
    out = {}
    for name, values in (("misma", same), ("otra", other)):
        for solid in (True, False):
            picked = sorted(v for v, ms in values if (ms >= fc.VOICE_SOLID_MS) == solid)
            if picked:
                q = np.percentile(picked, [0, 1, 5, 50, 95, 99, 100])
                out[f"{name} {'>=4s' if solid else '<4s'}"] = [len(picked)] + [round(float(x), 3) for x in q]
    return out


GRID = {
    "LINK": (0.50, 0.55, 0.60, 0.65, 0.70, 0.75),
    "MARGIN": (0.0, 0.03, 0.06, 0.10),
    "LINK_SHORT": (0.60, 0.65, 0.70, 0.75, 0.80),
    "MERGE": (0.50, 0.55, 0.60, 0.65, 0.70, 0.75),
}


def grid(cases: list[tuple[str, list[fc.Chunk], list[dict[str, str]]]]) -> list[tuple]:
    """Umbrales ordenados por (mezclas, personas de más o de menos, -exactitud)."""
    saved = {k: getattr(fc, k) for k in GRID}
    results = []
    try:
        for values in itertools.product(*GRID.values()):
            params = dict(zip(GRID, values, strict=True))
            for k, v in params.items():
                setattr(fc, k, v)
            scores = [evaluate(chunks, truth) for _, chunks, truth in cases]
            mixes = sum(s["mezclas"] for s in scores)
            wrong_count = sum(abs(s["personas"] - s["reales"]) for s in scores)
            accuracy = min(s["exactitud"] for s in scores)
            mean = sum(s["exactitud"] for s in scores) / len(scores)
            results.append(((mixes, wrong_count, -accuracy, -mean), params))
    finally:
        for k, v in saved.items():
            setattr(fc, k, v)
    results.sort(key=lambda item: item[0])
    return results
