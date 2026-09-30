"""Métricas del banco de transcripción: qué tan fiel es un transcript a la referencia.

Un transcript es una lista de turnos (hablante, inicio_ms, texto). El hablante
puede ser None (un turno "Hablante" sin persona). La referencia usa letras o
nombres para las personas; el transcript usa sus propias etiquetas, así que
para medir hablantes se busca la correspondencia que más coincide (una
etiqueta del transcript = a lo sumo una persona de la referencia).
"""
from __future__ import annotations

import itertools
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher


@dataclass
class Turn:
    speaker: str | None
    start_ms: int
    text: str
    end_ms: int | None = None  # sin fin: hasta que empieza el turno siguiente


# ── Texto ────────────────────────────────────────────────────────


_NUMBERS = "cero uno dos tres cuatro cinco seis siete ocho nueve diez".split()


def normalize(text: str) -> str:
    """Minúsculas, sin puntuación, y "1, 2, 3" igual que "uno, dos, tres"."""
    text = (text or "").lower()
    text = re.sub(r"\b(10|[0-9])\b", lambda m: " " + _NUMBERS[int(m.group(1))] + " ", text)
    text = re.sub(r"[^\wáéíóúüñ ]", " ", text)
    return " ".join(text.split())


def words(text: str) -> list[str]:
    return normalize(text).split()


def phrases(turns: list[Turn]) -> list[tuple[str, int]]:
    """Frases (normalizadas) con el momento de su turno. Corta en . , ? ! y guiones."""
    out = []
    for turn in turns:
        for piece in re.split(r"[.,;:!?¡¿…]|\s-\s|^-\s", turn.text):
            norm = normalize(piece)
            if len(norm.split()) >= 1:
                out.append((norm, turn.start_ms))
    return out


# ── Alineación palabra por palabra (Levenshtein con recorrido) ───


def align(ref: list[str], hyp: list[str]) -> list[tuple[int | None, int | None]]:
    """Pares (índice ref, índice hyp); None del lado que falta (borrado / inserción)."""
    n, m = len(ref), len(hyp)
    dist = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dist[i][0] = i
    for j in range(m + 1):
        dist[0][j] = j
    for i in range(1, n + 1):
        row, prev = dist[i], dist[i - 1]
        for j in range(1, m + 1):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            row[j] = min(prev[j - 1] + cost, prev[j] + 1, row[j - 1] + 1)
    pairs = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and dist[i][j] == dist[i - 1][j - 1] + (0 if ref[i - 1] == hyp[j - 1] else 1):
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i > 0 and dist[i][j] == dist[i - 1][j] + 1:
            pairs.append((i - 1, None))
            i -= 1
        else:
            pairs.append((None, j - 1))
            j -= 1
    pairs.reverse()
    return pairs


def wer(ref_turns: list[Turn], hyp_turns: list[Turn]) -> dict:
    ref = [w for t in ref_turns for w in words(t.text)]
    hyp = [w for t in hyp_turns for w in words(t.text)]
    pairs = align(ref, hyp)
    subs = sum(1 for a, b in pairs if a is not None and b is not None and ref[a] != hyp[b])
    dels = sum(1 for a, b in pairs if b is None)
    ins = sum(1 for a, b in pairs if a is None)
    return {
        "wer": (subs + dels + ins) / max(len(ref), 1),
        "sub": subs,
        "del": dels,
        "ins": ins,
        "ref_words": len(ref),
        "hyp_words": len(hyp),
    }


# ── Duplicados ───────────────────────────────────────────────────


def _cluster_counts(items: list[str], threshold: float = 0.85) -> list[tuple[str, int]]:
    reps: list[list] = []
    for item in items:
        for rep in reps:
            if SequenceMatcher(None, item, rep[0], autojunk=False).ratio() >= threshold:
                rep[1] += 1
                break
        else:
            reps.append([item, 1])
    return [(rep, count) for rep, count in reps]


def duplicates(ref_turns: list[Turn] | None, hyp_turns: list[Turn]) -> dict:
    """Frases de más: cuántas veces aparece cada frase contra cuántas se dijo.

    Solo frases de 2+ palabras (un "sí" repetido no es duplicado). Sin
    referencia, cuenta las repeticiones del transcript contra sí mismo.
    """
    hyp = [p for p, _ in phrases(hyp_turns) if len(p.split()) >= 2]
    ref = [p for p, _ in phrases(ref_turns or []) if len(p.split()) >= 2]
    excess = 0
    detail = []
    for rep, count in _cluster_counts(hyp):
        said = sum(1 for p in ref if SequenceMatcher(None, p, rep, autojunk=False).ratio() >= 0.85)
        extra = count - said if ref_turns is not None else count - 1
        if extra > 0:
            excess += extra
            detail.append((rep, count, said))
    return {"excess_phrases": excess, "detail": sorted(detail, key=lambda d: -d[1])[:8]}


def canary(turns: list[Turn], phrase: str = "uno dos tres probando") -> int:
    """Veces que aparece una frase conocida (en esta reunión, "uno dos tres probando")."""
    text = normalize(" ".join(t.text for t in turns))
    return text.count(phrase)


# ── Alucinaciones típicas ────────────────────────────────────────

_HALLUCINATION_PATTERNS = [
    r"\bam[eé]n\b",
    r"subt[ií]tul",
    r"amara",
    r"gracias por ver",
    r"suscr[ií]b",
    r"^\s*-\s",
]


def flagged_hallucinations(turns: list[Turn]) -> list[str]:
    """Turnos con fórmulas típicas de alucinación (subtítulos, "Amén", guiones sueltos)."""
    return [t.text.strip() for t in turns if any(re.search(p, t.text.strip().lower()) for p in _HALLUCINATION_PATTERNS)]


def invented(ref_turns: list[Turn], hyp_turns: list[Turn]) -> list[str]:
    """Frases del transcript que no se parecen a nada de lo dicho ("Tá brón orm")."""
    ref = [p for p, _ in phrases(ref_turns)]
    out = []
    for phrase, _ in phrases(hyp_turns):
        best = max((SequenceMatcher(None, phrase, p, autojunk=False).ratio() for p in ref), default=0)
        if best < 0.6:
            out.append(phrase)
    return out


# ── Hablantes ────────────────────────────────────────────────────


def _word_speakers(turns: list[Turn]) -> list[str | None]:
    return [t.speaker for t in turns for _ in words(t.text)]


def speakers(ref_turns: list[Turn], hyp_turns: list[Turn]) -> dict:
    """Atribución: % de palabras y de turnos de la referencia con la persona correcta."""
    ref_w = [w for t in ref_turns for w in words(t.text)]
    hyp_w = [w for t in hyp_turns for w in words(t.text)]
    ref_spk = _word_speakers(ref_turns)
    hyp_spk = _word_speakers(hyp_turns)
    ref_turn_of = [index for index, t in enumerate(ref_turns) for _ in words(t.text)]
    pairs = [(a, b) for a, b in align(ref_w, hyp_w) if a is not None and b is not None]

    confusion: dict[tuple[str, str | None], int] = Counter((ref_spk[a], hyp_spk[b]) for a, b in pairs)
    ref_labels = sorted({s for s in ref_spk if s})
    hyp_labels = sorted({s for s in hyp_spk if s})
    best_map: dict[str, str] = {}
    best_score = -1
    # Correspondencia óptima por fuerza bruta (pocas personas).
    if len(hyp_labels) <= 9:
        size = min(len(ref_labels), len(hyp_labels))
        for chosen in itertools.permutations(hyp_labels, size):
            for refs in itertools.combinations(ref_labels, size) if len(ref_labels) > size else [ref_labels]:
                mapping = dict(zip(chosen, refs))
                score = sum(confusion.get((r, h), 0) for h, r in mapping.items())
                if score > best_score:
                    best_score, best_map = score, mapping
    else:  # voraz
        for (r, h), _ in Counter(confusion).most_common():
            if h and h not in best_map and r not in best_map.values():
                best_map[h] = r
        best_score = sum(confusion.get((r, h), 0) for h, r in best_map.items())

    word_acc = best_score / max(len(pairs), 1)

    # Turnos: la persona mayoritaria (mapeada) entre las palabras alineadas del turno.
    votes: dict[int, Counter] = defaultdict(Counter)
    for a, b in pairs:
        votes[ref_turn_of[a]][best_map.get(hyp_spk[b])] += 1
    ok = sum(
        1
        for index, turn in enumerate(ref_turns)
        if votes[index] and votes[index].most_common(1)[0][0] == turn.speaker
    )
    return {
        "word_speaker_acc": word_acc,
        "turn_speaker_acc": ok / max(len(ref_turns), 1),
        "mapping": best_map,
    }


def _timeline(turns: list[Turn], step: int = 100) -> dict[int, str | None]:
    """Quién habla cada `step` ms según los turnos (sin fin: hasta el siguiente)."""
    out: dict[int, str | None] = {}
    ordered = sorted(turns, key=lambda t: t.start_ms)
    for index, turn in enumerate(ordered):
        end = turn.end_ms or (ordered[index + 1].start_ms if index + 1 < len(ordered) else turn.start_ms + 3000)
        for t in range(turn.start_ms - turn.start_ms % step, end, step):
            if t >= turn.start_ms:
                out.setdefault(t, turn.speaker)
    return out


def speaker_time(ref_turns: list[Turn], hyp_turns: list[Turn]) -> dict:
    """Parte del tiempo hablado (según la referencia) en que el transcript tiene a la persona correcta.

    Parecido a la tasa de error de diarización: cada 100 ms de la referencia se
    compara con quién dice el transcript que hablaba, con la mejor
    correspondencia entre etiquetas. Sin persona en el transcript = error.
    """
    ref = {t: s for t, s in _timeline(ref_turns).items() if s}
    hyp = _timeline([t for t in hyp_turns if t.speaker])
    confusion = Counter((s, hyp.get(t)) for t, s in ref.items())
    ref_labels = sorted({s for s in ref.values()})
    hyp_labels = sorted({s for s in hyp.values() if s})
    best, best_map = -1, {}
    size = min(len(ref_labels), len(hyp_labels))
    for chosen in itertools.permutations(hyp_labels, size):
        for refs in itertools.permutations(ref_labels, size):
            mapping = dict(zip(chosen, refs))
            score = sum(confusion.get((r, h), 0) for h, r in mapping.items())
            if score > best:
                best, best_map = score, mapping
    per_person = {}
    for label in ref_labels:
        total = sum(1 for s in ref.values() if s == label)
        ok = sum(1 for t, s in ref.items() if s == label and best_map.get(hyp.get(t)) == label)
        per_person[label] = round(ok / total, 2)
    return {"time_speaker_acc": max(best, 0) / max(len(ref), 1), "per_person": per_person, "time_mapping": best_map}


def summary(ref_turns: list[Turn] | None, hyp_turns: list[Turn]) -> dict:
    """Todas las métricas de un transcript. Sin referencia, solo las que no la necesitan."""
    labels = {t.speaker for t in hyp_turns if t.speaker}
    total_words = sum(len(words(t.text)) for t in hyp_turns) or 1
    orphan = [t for t in hyp_turns if not t.speaker]
    out = {
        "turns": len(hyp_turns),
        "people": len(labels),
        "orphan_turns": len(orphan),
        "orphan_words_pct": sum(len(words(t.text)) for t in orphan) / total_words,
        "canary": canary(hyp_turns),
        "hallucinations": flagged_hallucinations(hyp_turns),
    }
    out.update(duplicates(ref_turns, hyp_turns))
    if ref_turns:
        out.update(wer(ref_turns, hyp_turns))
        out["invented"] = invented(ref_turns, hyp_turns)
        if labels:
            out.update(speakers(ref_turns, hyp_turns))
            out.update(speaker_time(ref_turns, hyp_turns))
    return out


# ── Lectura de transcripts ───────────────────────────────────────

_LINE = re.compile(r"^\**\[(\d+):(\d+)(?::(\d+))?(?:\s*-\s*(\d+):(\d+))?\]\s*([^:]+?)\s*:\**\s*(.*)$")


def parse_transcript(text: str) -> list[Turn]:
    """Lee "[mm:ss] Persona: texto" (la referencia y el Markdown exportado de Echo).

    "Hablante" (así exporta Echo un turno sin persona) queda como None.
    """
    turns = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE.match(line)
        if not match:
            if turns:
                turns[-1].text += " " + line
            continue
        a, b, c, ea, eb, who, body = match.groups()
        seconds = int(a) * 3600 + int(b) * 60 + int(c) if c else int(a) * 60 + int(b)
        # "[mm:ss-mm:ss]": el fin es inclusivo al segundo.
        end = (int(ea) * 60 + int(eb) + 1) * 1000 if ea else None
        who = who.strip().strip("*").strip()
        speaker = None if who.lower() in {"hablante", "?", ""} else who
        turns.append(Turn(speaker, seconds * 1000, body.strip().strip("*").strip(), end))
    return turns
