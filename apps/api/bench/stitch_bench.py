"""Banco de la unión de tramos (services/final_chunks.py) con grabaciones reales.

Para cada grabación:
- Referencia: la reunión entera en un solo pedido a ElevenLabs (las personas
  quedan con una sola numeración, sin cortes).
- Por tramos, como en producción: cortes en silencio cada 5 minutos (y cada 2,
  para forzar más uniones) unidos por la voz. Con `--viejo`, también el método
  anterior (tramos fijos con 40 s repetidos, unidos por las palabras).
- Se compara palabra por palabra con la referencia: cuántas personas salen,
  si alguna mezcla a dos personas de la referencia (lo peor) y qué parte de
  las palabras queda con la persona correcta.

Todo lo que se pide a ElevenLabs queda en `--work` para volver a correr sin
pagar de nuevo (por ejemplo, para calibrar los umbrales con `--grid`). El
audio y los textos son de reuniones reales: `--work` va en una carpeta
temporal y se borra al terminar.

Uso (desde apps/api, con ELEVENLABS_API_KEY):
    python bench/stitch_bench.py --work <carpeta> audio1.mp3 audio2.mp3 ...
    python bench/stitch_bench.py --work <carpeta> --grid audio1.mp3 ...
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import itertools
import json
import os
import subprocess
import sys
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from echo_api.services import final_chunks as fc  # noqa: E402
from echo_api.services import voiceprint  # noqa: E402
from echo_api.services.stt.base import SttWord, get_stt_provider  # noqa: E402

SIZES = (5 * 60_000, 2 * 60_000)
MATCH_MS = 700


def decode(audio: Path, target: Path) -> None:
    if not target.exists():
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(audio), "-ac", "1", "-ar", "16000", "-f", "s16le", str(target)],
            check=True,
        )


def to_mp3(pcm: bytes) -> bytes:
    return subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "s16le", "-ar", "16000", "-ac", "1", "-i", "pipe:0",
         "-codec:a", "libmp3lame", "-b:a", "64k", "-f", "mp3", "pipe:1"],
        input=pcm, capture_output=True, check=True,
    ).stdout


class Scribe:
    def __init__(self, cache: Path):
        self.engine = get_stt_provider("elevenlabs", os.environ["ELEVENLABS_API_KEY"])
        self.cache = cache
        self.cache.mkdir(parents=True, exist_ok=True)
        self.semaphore = asyncio.Semaphore(4)
        self.seconds = 0.0

    async def words(self, pcm: bytes, start_ms: int, end_ms: int, language: str | None) -> list[SttWord]:
        piece = pcm[start_ms * 32:end_ms * 32]
        key = hashlib.sha1(piece).hexdigest()[:16]
        path = self.cache / f"{start_ms}-{end_ms}-{key}.json"
        if path.exists():
            return [SttWord(**w) for w in json.loads(path.read_text(encoding="utf-8"))]
        async with self.semaphore:
            result = await self.engine.transcribe_file(to_mp3(piece), "tramo.mp3", language, [])
        self.seconds += (end_ms - start_ms) / 1000
        path.write_text(json.dumps([asdict(w) for w in result.words], ensure_ascii=False), encoding="utf-8")
        return result.words


def quiet_cuts(pcm: bytes, total_ms: int, size: int) -> list[int]:
    cuts: list[int] = []
    while True:
        start = cuts[-1] if cuts else 0
        if total_ms - start <= size + min(fc.TAIL_SLACK_MS, size // 5):
            return cuts
        target = start + size
        search = target - min(fc.CUT_SEARCH_MS, size // 10)
        cuts.append(fc.quiet_point(pcm[search * 32:target * 32], search))


async def chunks_for(scribe: Scribe, pcm: bytes, total_ms: int, size: int, mode: str, language: str | None,
                     voices_cache: Path) -> list[fc.Chunk]:
    if mode == "voice":
        plan = {"mode": "voice", "cuts": quiet_cuts(pcm, total_ms, size)}
    else:
        plan = {"mode": "overlap", "cuts": list(range(size, total_ms - size // 5, size))}
    spans = fc.spans(plan, total_ms)
    words = await asyncio.gather(*(scribe.words(pcm, s, e, language) for s, e in spans))
    chunks = []
    for index, ((start, end), chunk_words) in enumerate(zip(spans, words, strict=True)):
        voices = {}
        if mode == "voice":
            key = voices_cache / f"{start}-{end}.json"
            if key.exists():
                voices = json.loads(key.read_text(encoding="utf-8"))
            else:
                voices = fc.chunk_voices(pcm[start * 32:end * 32], chunk_words)
                key.write_text(json.dumps(voices), encoding="utf-8")
        chunks.append(fc.Chunk(
            index, start, end, "elevenlabs", language,
            [replace(w, start_ms=w.start_ms + start, end_ms=w.end_ms + start) for w in chunk_words], [], [], voices,
        ))
    return chunks


def align(reference: list[SttWord], stitched: list[SttWord]) -> list[tuple[str, str]]:
    """(persona de la referencia, persona por tramos) de cada palabra que está en las dos."""
    by_key: dict[str, list[SttWord]] = {}
    for word in reference:
        if word.speaker and fc._key(word.text):
            by_key.setdefault(fc._key(word.text), []).append(word)
    pairs = []
    for word in stitched:
        candidates = [w for w in by_key.get(fc._key(word.text), []) if abs(w.start_ms - word.start_ms) <= MATCH_MS]
        if word.speaker and candidates:
            twin = min(candidates, key=lambda w: abs(w.start_ms - word.start_ms))
            pairs.append((twin.speaker, word.speaker))
    return pairs


def score(pairs: list[tuple[str, str]]) -> dict:
    refs = sorted({r for r, _ in pairs})
    outs = sorted({o for _, o in pairs})
    counts = {(r, o): 0 for r in refs for o in outs}
    for pair in pairs:
        counts[pair] += 1
    total = len(pairs) or 1
    # Exactitud: cada persona de la referencia con una sola persona por tramos (uno a uno).
    best = 0
    if refs and outs:
        rows, cols = (refs, outs) if len(refs) <= len(outs) else (outs, refs)
        cost = [[-(counts[(r, c)] if rows is refs else counts[(c, r)]) for c in cols] for r in rows]
        assignment = voiceprint._hungarian(cost)
        best = -sum(cost[i][j] for i, j in enumerate(assignment))
    # Mezclas: una persona por tramos que tiene a dos de la referencia (cada una con ≥15 % y ≥20 palabras suyas).
    mixes = []
    for o in outs:
        own = sum(counts[(r, o)] for r in refs)
        big = [r for r in refs if counts[(r, o)] >= 20 and counts[(r, o)] >= 0.15 * own]
        if len(big) > 1:
            mixes.append((o, {r: counts[(r, o)] for r in big}))
    ref_people = [r for r in refs if sum(counts[(r, o)] for o in outs) >= 20]
    out_people = [o for o in outs if sum(counts[(r, o)] for r in refs) >= 20]
    return {
        "ref": len(ref_people), "personas": len(out_people), "personas_todas": len(outs),
        "exactitud": round(best / total, 3), "mezclas": mixes, "palabras": len(pairs),
    }


def label_identity(chunk: fc.Chunk, reference: list[SttWord]) -> dict[str, str]:
    """Persona de la referencia de cada etiqueta del tramo (si es clara)."""
    out = {}
    pairs = align(reference, chunk.words)
    for label in {o for _, o in pairs}:
        mine = [r for r, o in pairs if o == label]
        top = max(set(mine), key=mine.count)
        if mine.count(top) >= 0.85 * len(mine) and len(mine) >= 5:
            out[label] = top
    return out


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", nargs="+", type=Path)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--language", default="es")
    parser.add_argument("--grid", action="store_true", help="probar umbrales sobre lo ya guardado")
    parser.add_argument("--viejo", action="store_true", help="también el método viejo (40 s repetidos): cuesta más")
    args = parser.parse_args()
    scribe = Scribe(args.work / "scribe")
    cases = []
    for audio in args.audio:
        name = hashlib.sha1(audio.name.encode()).hexdigest()[:8]
        folder = args.work / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "voices").mkdir(exist_ok=True)
        pcm_file = folder / "audio.pcm"
        decode(audio, pcm_file)
        pcm = pcm_file.read_bytes()
        total_ms = len(pcm) // 32
        reference = await scribe.words(pcm, 0, total_ms, args.language)
        variants = {}
        for size in SIZES:
            if total_ms <= size * 1.2:
                continue
            variants[f"voz {size // 60000} min"] = await chunks_for(
                scribe, pcm, total_ms, size, "voice", args.language, folder / "voices")
        if args.viejo and total_ms > SIZES[0] * 1.2:
            variants["viejo 5 min"] = await chunks_for(
                scribe, pcm, total_ms, SIZES[0], "overlap", args.language, folder / "voices")
        cases.append((name, total_ms, reference, variants))
    print(f"ElevenLabs en esta corrida: {scribe.seconds / 60:.1f} min de audio")

    def run(params: dict | None = None) -> list[tuple[str, str, dict]]:
        saved = {k: getattr(fc, k) for k in (params or {})}
        for k, v in (params or {}).items():
            setattr(fc, k, v)
        try:
            out = []
            for name, _, reference, variants in cases:
                for variant, chunks in variants.items():
                    words, _ = fc.stitch_words(chunks, "voice" if variant.startswith("voz") else "overlap")
                    out.append((name, variant, score(align(reference, words))))
            return out
        finally:
            for k, v in saved.items():
                setattr(fc, k, v)

    # Calibración: coseno entre etiquetas de tramos distintos, misma persona o no.
    same, other = [], []
    for _, _, reference, variants in cases:
        for variant, chunks in variants.items():
            if not variant.startswith("voz"):
                continue
            labeled = []
            for chunk in chunks:
                ids = label_identity(chunk, reference)
                for label, data in chunk.voices.items():
                    if label in ids:
                        labeled.append((chunk.index, ids[label], np.asarray(data["vector"]), data["ms"]))
            for (ca, ra, va, ma), (cb, rb, vb, mb) in itertools.combinations(labeled, 2):
                if ca == cb:
                    continue
                (same if ra == rb else other).append((float(va @ vb), min(ma, mb)))

    def describe(values: list[tuple[float, int]], solid: bool) -> str:
        picked = sorted(v for v, ms in values if (ms >= fc.VOICE_SOLID_MS) == solid)
        if not picked:
            return "-"
        q = np.percentile(picked, [0, 5, 50, 95, 100])
        return f"n={len(picked)} min={q[0]:.2f} p5={q[1]:.2f} mediana={q[2]:.2f} p95={q[3]:.2f} max={q[4]:.2f}"

    print("misma persona  (≥4 s):", describe(same, True))
    print("otra persona   (≥4 s):", describe(other, True))
    print("misma persona  (<4 s):", describe(same, False))
    print("otra persona   (<4 s):", describe(other, False))

    for name, total_ms, *_ in cases:
        print(f"\n{name} ({total_ms / 60000:.0f} min)")
        for case, variant, result in run():
            if case == name:
                print(f"  {variant:12} {result}")

    if args.grid:
        best = None
        for link, margin, short, merge in itertools.product(
            (0.50, 0.55, 0.60, 0.65, 0.70), (0.03, 0.06, 0.10), (0.60, 0.65, 0.70, 0.75), (0.55, 0.60, 0.65, 0.70)
        ):
            results = [r for _, v, r in run({"LINK": link, "MARGIN": margin, "LINK_SHORT": short, "MERGE": merge})
                       if v.startswith("voz")]
            mixes = sum(len(r["mezclas"]) for r in results)
            extra = sum(max(0, r["personas"] - r["ref"]) for r in results)
            accuracy = sum(r["exactitud"] * r["palabras"] for r in results) / max(1, sum(r["palabras"] for r in results))
            key = (mixes, extra, -accuracy)
            if best is None or key < best[0]:
                best = (key, (link, margin, short, merge))
        print("\nmejores umbrales (mezclas, personas de más, -exactitud):", best)


if __name__ == "__main__":
    asyncio.run(main())
