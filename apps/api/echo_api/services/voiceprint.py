"""Huella de voz: poner el nombre de quien habló a partir de "Mi voz".

Después de que la pasada final separa a las personas (ElevenLabs Scribe), se
saca la huella (embedding) de cada persona de la reunión con hasta 30 s de
sus turnos limpios, y se compara con las huellas de "Mi voz" de los
candidatos: miembros de la organización que grabaron su voz. Una persona
queda nombrada solo si la coincidencia supera un umbral Y le saca margen a
la segunda mejor opción; si no, queda como sugerencia para confirmar con un
toque. Un nombre equivocado es peor que "Persona 1".

El modelo (WeSpeaker ResNet34, ONNX, vía sherpa-onnx) corre en la CPU del
servidor de Echo: ni la muestra ni el audio salen a terceros. Si el modelo
no está (desarrollo sin descargarlo), todo esto se saltea sin error.

Calibrado con bench/voiceprint_bench.py (docs/plan-correcciones.md §7.2).
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger("echo.voiceprint")

MODEL_NAME = "wespeaker_resnet34"
MODEL_FILE = "wespeaker_en_voxceleb_resnet34.onnx"
DIM = 256
SAMPLE_RATE = 16000
# Turnos que sirven para la huella: al menos esto, sin pisarse con otra persona.
MIN_TURN_MS = 1000
# Cuánto audio de cada persona: más no mejora y cuesta CPU (servidor de 2 vCPU).
MAX_PERSON_MS = 30000
# Menos que esto de una persona y la huella no es confiable: no se nombra.
MIN_PERSON_MS = 3000
# Coseno entre la huella de "Mi voz" y la de la persona en la reunión. En el
# banco (1/10): misma persona 0,81-0,97 (también entre reuniones de días
# distintos); dos personas distintas en la misma sala 0,67-0,73, porque la
# sala y el micrófono pesan.
#
# Se lleva a "qué tan seguro" (0-100 %): 0 % donde llegan dos personas
# distintas, 100 % bien adentro de la misma persona. Decisión de Bauti (6/10):
# con 80 % o más se pone el nombre; entre 50 y 80 %, "¿Es X?"; menos, nada. Con
# 0,65 de piso, cualquiera con Mi voz grabada aparecía como "¿Es…?" en todas
# las reuniones.
CERTAIN_FROM = 0.70  # 0 %
CERTAIN_AT = 0.85  # 100 %
ACCEPT_CERTAINTY = 0.80
SUGGEST_CERTAINTY = 0.50


def certainty(score: float) -> float:
    """Coseno → qué tan seguro (0 a 1)."""
    return round(float(min(1.0, max(0.0, (score - CERTAIN_FROM) / (CERTAIN_AT - CERTAIN_FROM)))), 4)


ACCEPT = round(CERTAIN_FROM + ACCEPT_CERTAINTY * (CERTAIN_AT - CERTAIN_FROM), 4)  # 0,82
SUGGEST = round(CERTAIN_FROM + SUGGEST_CERTAINTY * (CERTAIN_AT - CERTAIN_FROM), 4)  # 0,775
# Además del umbral, la persona tiene que ganarle por esto a la segunda opción
# (dos voces parecidas no se nombran solas).
MARGIN = 0.08

_lock = threading.Lock()
_extractor = None
_missing = False


def model_path() -> Path:
    default = Path(__file__).resolve().parents[2] / "models" / MODEL_FILE
    return Path(os.environ.get("VOICEPRINT_MODEL") or default)


def available() -> bool:
    return _get_extractor() is not None


def _get_extractor():
    global _extractor, _missing
    if _extractor is not None or _missing:
        return _extractor
    with _lock:
        if _extractor is not None or _missing:
            return _extractor
        path = model_path()
        try:
            import sherpa_onnx

            if not path.exists():
                raise FileNotFoundError(path)
            config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(path), num_threads=1, provider="cpu")
            _extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
        except Exception as exc:  # noqa: BLE001 - sin modelo no hay nombres por voz, nada más
            log.warning("huella de voz no disponible (%s): %s", path, exc)
            _missing = True
    return _extractor


def embed(samples: np.ndarray) -> np.ndarray | None:
    """Huella normalizada de audio PCM16 (int16) o float32 en [-1, 1], 16 kHz mono."""
    extractor = _get_extractor()
    if extractor is None or samples is None or len(samples) < SAMPLE_RATE // 2:
        return None
    wave = samples.astype(np.float32) / 32768.0 if samples.dtype == np.int16 else samples.astype(np.float32)
    with _lock:  # el extractor no es seguro entre hilos
        stream = extractor.create_stream()
        stream.accept_waveform(sample_rate=SAMPLE_RATE, waveform=wave)
        stream.input_finished()
        if not extractor.is_ready(stream):
            return None
        vector = np.array(extractor.compute(stream), dtype=np.float32)
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 0 else None


def clean_turns(turns: list[tuple[str | None, int, int]]) -> list[tuple[str, int, int]]:
    """Turnos de al menos 1 s que no se pisan con los de otra persona."""
    out = []
    for index, (who, start, end) in enumerate(turns):
        if who is None or end - start < MIN_TURN_MS:
            continue
        overlaps = any(
            other != who and s < end and start < e
            for j, (other, s, e) in enumerate(turns)
            if j != index
        )
        if not overlaps:
            out.append((who, start, end))
    return out


def embed_spans(pcm: np.ndarray, spans: list[tuple[int, int]], limit_ms: int = MAX_PERSON_MS) -> np.ndarray | None:
    """Huella de una persona: sus tramos (ms) en fila, hasta `limit_ms`."""
    pieces, taken = [], 0
    for start, end in spans:
        if taken >= limit_ms:
            break
        end = min(end, start + limit_ms - taken)
        piece = pcm[start * SAMPLE_RATE // 1000:end * SAMPLE_RATE // 1000]
        if len(piece):
            pieces.append(piece)
            taken += end - start
    if taken < MIN_PERSON_MS or not pieces:
        return None
    return embed(np.concatenate(pieces))


def people_prints(pcm: np.ndarray, turns: list[tuple[str | None, int, int]]) -> dict[str, np.ndarray]:
    """La huella de cada persona de la reunión (las que tienen audio suficiente)."""
    clean = clean_turns(turns)
    prints = {}
    for who in dict.fromkeys(w for w, _, _ in clean):
        vector = embed_spans(pcm, [(s, e) for w, s, e in clean if w == who])
        if vector is not None:
            prints[who] = vector
    return prints


def _hungarian(cost: list[list[float]]) -> list[int]:
    """Asignación de costo mínimo, filas ≤ columnas. Devuelve la columna de cada fila."""
    n, m = len(cost), len(cost[0])
    inf = float("inf")
    u, v, p, way = [0.0] * (n + 1), [0.0] * (m + 1), [0] * (m + 1), [0] * (m + 1)
    for i in range(1, n + 1):
        p[0], j0 = i, 0
        minv, used = [inf] * (m + 1), [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], inf, 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    result = [-1] * n
    for j in range(1, m + 1):
        if p[j]:
            result[p[j] - 1] = j - 1
    return result


@dataclass
class Match:
    person: str  # la persona de la reunión ("speaker_1")
    candidate: int  # índice del candidato
    score: float
    accepted: bool  # True: se nombra; False: queda como sugerencia


def assign(scores: np.ndarray, accept: float = ACCEPT, margin: float = MARGIN, suggest: float = SUGGEST,
           people: list[str] | None = None) -> list[Match]:
    """Uno a uno (nadie se nombra dos veces), con umbral y margen.

    `scores[i][j]`: coseno entre la persona i de la reunión y el candidato j.
    El margen se mide contra la segunda mejor opción de la persona y contra la
    otra persona que más se parece al mismo candidato.
    """
    scores = np.asarray(scores, dtype=np.float32)
    if scores.size == 0:
        return []
    people = people or [str(i) for i in range(scores.shape[0])]
    transposed = scores.shape[0] > scores.shape[1]
    matrix = scores.T if transposed else scores
    columns = _hungarian((-matrix).tolist())
    pairs = [(col, row) for row, col in enumerate(columns)] if transposed else list(enumerate(columns))
    out = []
    for i, j in pairs:
        if i < 0 or j < 0:
            continue
        score = float(scores[i, j])
        if score < suggest:
            continue
        rival_candidate = max((float(x) for k, x in enumerate(scores[i]) if k != j), default=-1.0)
        rival_person = max((float(x) for k, x in enumerate(scores[:, j]) if k != i), default=-1.0)
        accepted = score >= accept and score - max(rival_candidate, rival_person) >= margin
        out.append(Match(people[i], j, round(score, 3), accepted))
    return out


def to_list(vector: np.ndarray | None) -> list[float] | None:
    return None if vector is None else [float(x) for x in vector]
