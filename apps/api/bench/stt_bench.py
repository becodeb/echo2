"""Banco de transcripción: el mismo audio por varios modelos y pre-procesados.

    python bench/stt_bench.py --case bench/casos/2026-09-30 --audio "D:/.../reunion.mp3"

Necesita OPENAI_API_KEY en el entorno y ffmpeg (FFMPEG=ruta, o imageio-ffmpeg
instalado). Las respuestas de la API quedan en bench/.cache: volver a correr
con otra referencia o con otras métricas no gasta de nuevo (--fresh para
pedir todo otra vez; --repeat N para medir cuánto varía el modelo).

Variantes (modelo × pre-procesado), más dos que reproducen producción:
- prod_live: el transcript en vivo tal cual lo arma routers/live.py (cortes
  de services/stt/windowing.py, contexto de 300 caracteres como prompt,
  filtros de channels.py).
- prod_final: la pasada final de services/diarization.py sobre ese audio, con
  el en vivo simulado como respaldo (lo que termina en la base).

El audio real no va al repo: se pasa con --audio.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import metrics  # noqa: E402
from metrics import Turn  # noqa: E402

URL = "https://api.openai.com/v1/audio/transcriptions"
SR = 16000
CACHE = HERE / ".cache"

MODELS = ["whisper-1", "gpt-4o-transcribe", "gpt-4o-transcribe-diarize"]
PREPROCESS = ["raw", "norm", "vad", "vad+norm"]


# ── Audio ────────────────────────────────────────────────────────


def ffmpeg() -> str:
    if os.environ.get("FFMPEG"):
        return os.environ["FFMPEG"]
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def decode(path: str, filters: str | None = None) -> np.ndarray:
    """PCM16 mono 16 kHz, como el audio de trabajo de una reunión."""
    cmd = [ffmpeg(), "-hide_banner", "-loglevel", "error", "-i", path]
    if filters:
        cmd += ["-af", filters]
    cmd += ["-ac", "1", "-ar", str(SR), "-f", "s16le", "-"]
    return np.frombuffer(subprocess.run(cmd, check=True, capture_output=True).stdout, dtype=np.int16)


def channel_count(path: str) -> int:
    out = subprocess.run([ffmpeg(), "-hide_banner", "-i", path], capture_output=True, text=True).stderr
    return 2 if "stereo" in out else 1


def wav(pcm: np.ndarray) -> bytes:
    from echo_api.services.stt.base import pcm16_to_wav

    return pcm16_to_wav(pcm.astype(np.int16).tobytes(), SR)


def vad(pcm: np.ndarray, pad_ms: int = 300, min_gap_ms: int = 800) -> tuple[np.ndarray, list[tuple[int, int, int]]]:
    """Saca los silencios largos. Devuelve el audio y el mapa (nuevo_ms, original_ms, largo_ms)."""
    frame = SR // 100  # 10 ms
    count = len(pcm) // frame
    rms = np.sqrt((pcm[: count * frame].astype(np.float32).reshape(count, frame) ** 2).mean(1))
    db = 20 * np.log10(rms + 1)
    threshold = max(np.percentile(db, 20) + 8, 35)
    voiced = db > threshold
    pad = pad_ms // 10
    grown = voiced.copy()
    for shift in range(1, pad + 1):
        grown[shift:] |= voiced[:-shift]
        grown[:-shift] |= voiced[shift:]
    # Huecos cortos no se cortan: se pierde la prosodia.
    regions, start = [], None
    for index, on in enumerate(list(grown) + [False]):
        if on and start is None:
            start = index
        elif not on and start is not None:
            if regions and start - regions[-1][1] < min_gap_ms // 10:
                regions[-1] = (regions[-1][0], index)
            else:
                regions.append((start, index))
            start = None
    pieces, mapping, cursor = [], [], 0
    for a, b in regions:
        pieces.append(pcm[a * frame : b * frame])
        mapping.append((cursor, a * 10, (b - a) * 10))
        cursor += (b - a) * 10
    return (np.concatenate(pieces) if pieces else pcm[:0]), mapping


def unmap(ms: int, mapping: list[tuple[int, int, int]] | None) -> int:
    if not mapping:
        return ms
    for new, orig, length in mapping:
        if ms < new + length:
            return orig + max(0, ms - new)
    new, orig, length = mapping[-1]
    return orig + length


# ── API con caché ────────────────────────────────────────────────


def _key(form: dict, audio: bytes, run: int) -> str:
    h = hashlib.sha256(audio)
    h.update(json.dumps(form, sort_keys=True).encode())
    h.update(str(run).encode())
    return h.hexdigest()[:24]


async def transcribe(client: httpx.AsyncClient, sem: asyncio.Semaphore, form: dict, audio: bytes, run: int, fresh: bool) -> dict:
    CACHE.mkdir(exist_ok=True)
    path = CACHE / f"{_key(form, audio, run)}.json"
    if path.exists() and not fresh:
        return json.loads(path.read_text(encoding="utf-8"))
    async with sem:
        started = time.monotonic()
        response = await client.post(
            URL,
            headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
            data=form,
            files={"file": ("audio.wav", audio, "audio/wav")},
        )
    payload = {"status": response.status_code, "latency_ms": int((time.monotonic() - started) * 1000)}
    try:
        payload["body"] = response.json()
    except ValueError:
        payload["body"] = {"error": response.text[:500]}
    if response.status_code < 400:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def form_for(model: str, language: str | None, prompt: str | None) -> dict:
    if "diarize" in model:
        form = {"model": model, "response_format": "diarized_json", "chunking_strategy": "auto"}
        if language:
            form["language"] = language
        return form
    form = {"model": model, "response_format": "verbose_json" if model == "whisper-1" else "json"}
    if language:
        form["language"] = language
    if prompt:
        form["prompt"] = prompt
    return form


def to_turns(body: dict, mapping) -> list[Turn]:
    """Respuesta de la API → turnos. Los modelos de solo texto dan un turno sin persona por oración."""
    segments = body.get("segments") or []
    if segments:
        turns = []
        for seg in segments:
            text = (seg.get("text") or "").strip()
            if text:
                turns.append(Turn(seg.get("speaker"), unmap(int(float(seg.get("start") or 0) * 1000), mapping), text))
        return turns
    return [Turn(None, 0, (body.get("text") or "").strip())]


# ── Producción simulada ──────────────────────────────────────────


async def prod_live(client, sem, pcm: np.ndarray, language: str, vocabulary: list[str], model: str, run: int, fresh: bool, context: bool = True):
    """routers/live.py: cortes en pausas, contexto de lo último dicho, filtros.

    context=False: el mismo camino sin mandar lo último dicho como pista.
    """
    from echo_api.services.stt.channels import is_noise_transcript, is_prompt_echo, is_silent, strip_hallucinations
    from echo_api.services.stt.whisper_api import build_prompt
    from echo_api.services.stt.windowing import find_cut

    raw = pcm.astype(np.int16).tobytes()
    frame = SR * 2 // 10  # 100 ms, lo que manda el navegador
    buffer, chunks, offset = bytearray(), [], 0
    for index in range(0, len(raw), frame):
        buffer += raw[index : index + frame]
        cut = find_cut(bytes(buffer))
        if cut:
            chunks.append((bytes(buffer[:cut]), offset))
            offset += len(buffer[:cut]) // 32
            buffer = buffer[cut:]
    if buffer:
        chunks.append((bytes(buffer), offset))

    rows, recent = [], ""
    for chunk, start in chunks:  # en orden: cada tramo usa el texto del anterior
        if is_silent(chunk):
            continue
        form = form_for(model, language, build_prompt(vocabulary, recent if context else None))
        if "diarize" not in model and model != "whisper-1":
            form["response_format"] = "json"
        payload = await transcribe(client, sem, form, wav(np.frombuffer(chunk, dtype=np.int16)), run, fresh)
        body = payload.get("body") or {}
        texts = [s.get("text", "") for s in body.get("segments") or []] or [body.get("text") or ""]
        for text in texts:
            text = strip_hallucinations(" ".join(text.split()))
            if not text or is_prompt_echo(text, vocabulary) or is_noise_transcript(text, language):
                continue
            rows.append((start, start + len(chunk) // 32, text))
            recent = (recent + " " + text)[-300:]
    return rows, len(chunks)


async def prod_final(client, sem, pcm: np.ndarray, language: str, vocabulary: list[str], live_rows, run: int, fresh: bool):
    """services/diarization.py: separación de voces + texto final + mezcla (una sola parte)."""
    from echo_api.services import diarization as d

    audio = wav(pcm)
    diar = await transcribe(client, sem, form_for("gpt-4o-transcribe-diarize", None, None), audio, run, fresh)
    part, local = [], {}
    for seg in (diar.get("body") or {}).get("segments") or []:
        label = str(seg.get("speaker") or "").strip()
        if not label:
            continue
        local.setdefault(label, f"persona_{len(local) + 1}")
        part.append(d.DiarSegment(int(float(seg["start"]) * 1000), int(float(seg["end"]) * 1000), local[label], (seg.get("text") or "").strip()))

    text, note = None, ""
    for terms in [vocabulary, []] if vocabulary else [[]]:
        from echo_api.services.stt.whisper_api import build_prompt

        payload = await transcribe(client, sem, form_for("gpt-4o-transcribe", language, build_prompt(terms)), audio, run, fresh)
        candidate = d.strip_prompt_echo((payload.get("body") or {}).get("text") or "", vocabulary)
        if not candidate:
            continue
        score = d.agreement(candidate, part)
        note += f"acuerdo {score:.0%}; "
        if score >= d.MIN_AGREEMENT:
            text = candidate
            break
    end_ms = len(pcm) // 16
    if text and part:
        final, note = d.merge_text_with_voices(text, part, 0, end_ms), note + "texto final + voces"
    elif text:
        final, note = [(None, text, 0, end_ms)], note + "texto final sin voces"
    else:
        final, note = d.fallback_pieces(live_rows, part, 0, end_ms), note + "RESPALDO: en vivo"
    # Lo "dicho después del audio de trabajo" se agrega sin persona.
    final += [(None, t, s, e) for s, e, t in live_rows if s >= end_ms]
    return [Turn(label, start, text) for label, text, start, _ in final], note


# ── Corrida ──────────────────────────────────────────────────────


def fmt_pct(value) -> str:
    return "—" if value is None else f"{value * 100:.0f}%"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", required=True)
    parser.add_argument("--audio", required=True)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--only", help="variantes separadas por coma (p. ej. prod_final,gpt-4o-transcribe/raw)")
    parser.add_argument("--no-api", action="store_true", help="solo el transcript exportado de producción")
    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY") and (HERE / ".env").exists():
        for line in (HERE / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("OPENAI_API_KEY="):
                os.environ["OPENAI_API_KEY"] = line.split("=", 1)[1].strip()
    case = Path(args.case)
    meta = json.loads((case / "case.json").read_text(encoding="utf-8"))
    language, vocabulary = meta.get("language"), meta.get("vocabulary") or []
    ref_path = case / "reference.txt"
    reference = metrics.parse_transcript(ref_path.read_text(encoding="utf-8")) if ref_path.exists() else None
    if reference is not None and not reference:
        reference = None

    results: list[dict] = []

    def record(name: str, run: int, turns: list[Turn], extra: dict | None = None) -> None:
        row = {"variant": name, "run": run, **metrics.summary(reference, turns), **(extra or {})}
        row["transcript"] = [(t.speaker, t.start_ms, t.text) for t in turns]
        results.append(row)
        print(f"  {name} #{run}: {len(turns)} turnos", flush=True)

    exported = case / "prod_export.md"
    if exported.exists():
        record("prod_export (lo que salió)", 0, metrics.parse_transcript(exported.read_text(encoding="utf-8")))

    if not args.no_api:
        print(f"canales del audio: {channel_count(args.audio)}")
        variants = {
            "raw": (decode(args.audio), None),
            "norm": (decode(args.audio, "highpass=f=80,loudnorm=I=-20:TP=-2:LRA=11"), None),
        }
        variants["vad"] = vad(variants["raw"][0])
        variants["vad+norm"] = vad(variants["norm"][0])
        wanted = set(args.only.split(",")) if args.only else None
        sem = asyncio.Semaphore(4)
        async with httpx.AsyncClient(timeout=600) as client:
            for run in range(1, args.repeat + 1):
                jobs = []
                for model in MODELS:
                    for pre in PREPROCESS:
                        name = f"{model}/{pre}"
                        if wanted and name not in wanted:
                            continue
                        pcm, mapping = variants[pre]
                        # Idioma y diccionario fijos: así va a producción.
                        prompt = ", ".join(vocabulary) + "." if vocabulary else None
                        jobs.append((name, mapping, transcribe(client, sem, form_for(model, language, prompt), wav(pcm), run, args.fresh)))
                for name, mapping, job in jobs:
                    payload = await job
                    if payload["status"] >= 400:
                        print(f"  {name}: API {payload['status']}: {json.dumps(payload['body'])[:200]}")
                        results.append({"variant": name, "run": run, "error": payload["body"]})
                        continue
                    record(name, run, to_turns(payload["body"], mapping), {"latency_ms": payload["latency_ms"]})

                if not wanted or {"prod_live", "prod_final"} & wanted:
                    raw = variants["raw"][0]
                    live_rows, chunks = await prod_live(client, sem, raw, language, vocabulary, meta.get("live_model", "gpt-4o-transcribe"), run, args.fresh)
                    record("prod_live (simulado)", run, [Turn(None, s, t) for s, _, t in live_rows], {"chunks": chunks})
                    quiet, _ = await prod_live(client, sem, raw, language, vocabulary, meta.get("live_model", "gpt-4o-transcribe"), run, args.fresh, context=False)
                    record("prod_live sin contexto", run, [Turn(None, s, t) for s, _, t in quiet])
                    turns, note = await prod_final(client, sem, raw, language, vocabulary, live_rows, run, args.fresh)
                    record("prod_final (simulado)", run, turns, {"note": note})

    out = case / "results.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print_table(results, reference is not None)
    print(f"\nDetalle (transcripts de cada variante): {out}")


def print_table(results: list[dict], with_ref: bool) -> None:
    head = ["variante", "run", "WER", "ins", "frases de más", "\"uno dos tres probando\"", "personas", "persona ok (palabras)", "persona ok (turnos)", "turnos sin persona", "alucinaciones"]
    print("\n| " + " | ".join(head) + " |")
    print("|" + "---|" * len(head))
    for row in results:
        if "error" in row:
            print(f"| {row['variant']} | {row['run']} | error API | | | | | | | | |")
            continue
        hall = len(row["hallucinations"]) + len(row.get("invented", []))
        print(
            "| "
            + " | ".join(
                [
                    row["variant"],
                    str(row["run"]),
                    fmt_pct(row.get("wer")),
                    str(row.get("ins", "—")),
                    str(row["excess_phrases"]),
                    str(row["canary"]),
                    str(row["people"]),
                    fmt_pct(row.get("word_speaker_acc")),
                    fmt_pct(row.get("turn_speaker_acc")),
                    f"{row['orphan_turns']} ({row['orphan_words_pct'] * 100:.0f}% palabras)",
                    str(hall),
                ]
            )
            + " |"
        )


if __name__ == "__main__":
    asyncio.run(main())
