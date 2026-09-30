"""Banco de transcripción: el mismo audio por varios modelos y pre-procesados.

    python bench/stt_bench.py --case bench/casos/2026-09-30 --audio "C:/.../reunion.mp3"

Keys en bench/.env (fuera de git): GROQ_API_KEY y ELEVENLABS_API_KEY (las de
PRUEBA). Necesita ffmpeg (FFMPEG=ruta, o imageio-ffmpeg instalado). Las
respuestas quedan en bench/.cache: volver a correr con otra referencia o con
otras métricas no gasta de nuevo (--fresh para pedir todo otra vez; --repeat N
para medir cuánto varía el modelo).

Variantes:
- groq/raw: Groq whisper-large-v3-turbo con el audio entero (es, temperature 0).
- scribe/raw: ElevenLabs Scribe v2 con el audio entero, con personas.
- prod_live: el en vivo de routers/live.py (cortes de services/stt/windowing.py,
  Groq sin pista de contexto, filtros de channels.py).
- prod_final: la pasada final de services/diarization.py con personas
  (Scribe → turnos desde las palabras).
- prod_final sin personas: la misma pasada con Groq (plan Base sin crédito,
  reuniones con menores).
- Con --openai (gasta en OpenAI; Bauti pidió no usarlo): los modelos de
  OpenAI × pre-procesados (raw, norm, vad, vad+norm).

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
GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
SCRIBE_URL = "https://api.elevenlabs.io/v1/speech-to-text"
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


def _key(form: dict, audio: bytes, run: int, url: str = URL) -> str:
    h = hashlib.sha256(audio)
    h.update(json.dumps(form, sort_keys=True).encode())
    h.update(str(run).encode())
    if url != URL:  # las claves de OpenAI quedan como estaban: su caché sigue sirviendo
        h.update(url.encode())
    return h.hexdigest()[:24]


def _auth(url: str) -> dict:
    if url == SCRIBE_URL:
        return {"xi-api-key": os.environ["ELEVENLABS_API_KEY"]}
    if url == GROQ_URL:
        return {"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"}
    return {"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"}


async def transcribe(
    client: httpx.AsyncClient, sem: asyncio.Semaphore, form: dict, audio: bytes, run: int, fresh: bool,
    url: str = URL, filename: str = "audio.wav",
) -> dict:
    CACHE.mkdir(exist_ok=True)
    path = CACHE / f"{_key(form, audio, run, url)}.json"
    if path.exists() and not fresh:
        return json.loads(path.read_text(encoding="utf-8"))
    async with sem:
        started = time.monotonic()
        from echo_api.services.stt.base import post_with_rate_limit

        response = await post_with_rate_limit(
            client,
            url,
            headers=_auth(url),
            data=form,
            files={"file": (filename, audio, "audio/mpeg" if filename.endswith(".mp3") else "audio/wav")},
        )
    payload = {"status": response.status_code, "latency_ms": int((time.monotonic() - started) * 1000)}
    try:
        payload["body"] = response.json()
    except ValueError:
        payload["body"] = {"error": response.text[:500]}
    if response.status_code < 400:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def mp3(pcm: np.ndarray) -> bytes:
    """Lo que producción le manda a Scribe (services/diarization.py): mp3 64 kbps."""
    cmd = [ffmpeg(), "-hide_banner", "-loglevel", "error", "-f", "s16le", "-ar", str(SR), "-ac", "1", "-i", "-",
           "-codec:a", "libmp3lame", "-b:a", "64k", "-f", "mp3", "-"]
    return subprocess.run(cmd, input=pcm.astype(np.int16).tobytes(), check=True, capture_output=True).stdout


def groq_form(language: str | None, vocabulary: list[str]) -> dict:
    from echo_api.services.stt.whisper_api import build_prompt

    form = {"model": "whisper-large-v3-turbo", "response_format": "verbose_json", "temperature": "0.0"}
    if language:
        form["language"] = language
    prompt = build_prompt(vocabulary)
    if prompt:
        form["prompt"] = prompt
    return form


def scribe_form(language: str | None, vocabulary: list[str]) -> dict:
    from echo_api.services.stt.elevenlabs import ElevenLabsProvider

    return ElevenLabsProvider("x").form(language, vocabulary)


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
                turns.append(Turn(seg.get("speaker"), unmap(int(float(seg.get("start") or 0) * 1000), mapping), text, unmap(int(float(seg.get("end") or 0) * 1000), mapping) or None))
        return turns
    return [Turn(None, 0, (body.get("text") or "").strip())]


# ── Producción simulada ──────────────────────────────────────────


async def prod_live(client, sem, pcm: np.ndarray, language: str, vocabulary: list[str], run: int, fresh: bool):
    """routers/live.py: cortes en pausas, Groq sin pista, filtros."""
    from echo_api.services.stt.channels import (
        is_noise_transcript,
        is_prompt_echo,
        is_silent,
        is_unreliable,
        repeats_previous,
        strip_hallucinations,
    )
    from echo_api.services.stt.whisper_api import WhisperApiProvider
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

    parser = WhisperApiProvider("groq", "", "", "whisper-large-v3-turbo")
    rows, previous = [], ""
    for chunk, start in chunks:
        if is_silent(chunk):
            continue
        audio = wav(np.frombuffer(chunk, dtype=np.int16))
        payload = await transcribe(client, sem, groq_form(language, vocabulary), audio, run, fresh, GROQ_URL)
        if payload["status"] >= 400:
            print(f"  prod_live: Groq {payload['status']}: {json.dumps(payload['body'])[:200]}")
            continue
        for seg in parser._parse(payload["body"], start, len(chunk) // 32).segments:
            text = strip_hallucinations(seg.text)
            if (
                not text
                or is_unreliable(seg)
                or is_prompt_echo(text, vocabulary)
                or is_noise_transcript(text, language)
                or repeats_previous(text, previous)
            ):
                continue
            rows.append((seg.start_ms, seg.end_ms, text))
            previous = text
    return rows, len(chunks)


def final_turns(body: dict, language: str) -> list[Turn]:
    """services/diarization.py con personas: Scribe → turnos desde las palabras."""
    from echo_api.services.diarization import rows_from_scribe
    from echo_api.services.stt.elevenlabs import parse

    rows, _ = rows_from_scribe(parse(body), language, [], 0)
    return [Turn(label, start, text, end) for label, text, start, end in rows]


def final_turns_without_people(body: dict, language: str) -> list[Turn]:
    """services/diarization.py sin personas: Groq sobre el audio entero, con filtros."""
    from echo_api.services.diarization import _clean_rows
    from echo_api.services.stt.whisper_api import WhisperApiProvider

    segments = WhisperApiProvider("groq", "", "", "whisper-large-v3-turbo")._parse(body, 0).segments
    return [Turn(None, start, text, end) for _, text, start, end in _clean_rows(segments, language)]


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
    parser.add_argument("--openai", action="store_true", help="también los modelos de OpenAI (gasta en OpenAI)")
    parser.add_argument("--out", default="results.json", help="archivo de resultados dentro del caso")
    args = parser.parse_args()

    if (HERE / ".env").exists():
        for line in (HERE / ".env").read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() and not os.environ.get(key.strip()):
                os.environ[key.strip()] = value.strip()
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
        row["transcript"] = [(t.speaker, t.start_ms, t.text, t.end_ms) for t in turns]
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
                def want(name: str) -> bool:
                    return not wanted or name in wanted

                raw = variants["raw"][0]
                if args.openai:
                    jobs = []
                    for model in MODELS:
                        for pre in PREPROCESS:
                            name = f"{model}/{pre}"
                            if not want(name):
                                continue
                            pcm, mapping = variants[pre]
                            # Idioma y diccionario fijos: así va a producción.
                            prompt = ", ".join(vocabulary) + "." if vocabulary else None
                            form = form_for(model, language, prompt)
                            jobs.append((name, mapping, transcribe(client, sem, form, wav(pcm), run, args.fresh)))
                    for name, mapping, job in jobs:
                        payload = await job
                        if payload["status"] >= 400:
                            print(f"  {name}: API {payload['status']}: {json.dumps(payload['body'])[:200]}")
                            results.append({"variant": name, "run": run, "error": payload["body"]})
                            continue
                        record(name, run, to_turns(payload["body"], mapping), {"latency_ms": payload["latency_ms"]})

                if want("groq/raw") or want("prod_final sin personas"):
                    form = groq_form(language, vocabulary)
                    payload = await transcribe(client, sem, form, wav(raw), run, args.fresh, GROQ_URL)
                    if payload["status"] >= 400:
                        print(f"  groq: API {payload['status']}: {json.dumps(payload['body'])[:200]}")
                    else:
                        if want("groq/raw"):
                            record("groq/raw", run, to_turns(payload["body"], None), {"latency_ms": payload["latency_ms"]})
                        if want("prod_final sin personas"):
                            record("prod_final sin personas", run, final_turns_without_people(payload["body"], language))

                if want("scribe/raw") or want("prod_final"):
                    form = scribe_form(language, vocabulary)
                    payload = await transcribe(client, sem, form, mp3(raw), run, args.fresh, SCRIBE_URL, "reunion.mp3")
                    if payload["status"] >= 400:
                        print(f"  scribe: API {payload['status']}: {json.dumps(payload['body'])[:200]}")
                    else:
                        if want("scribe/raw"):
                            words = [w for w in payload["body"].get("words") or [] if w.get("type") == "word"]
                            turns = [
                                Turn(w.get("speaker_id"), int(w["start"] * 1000), w["text"], int(w["end"] * 1000))
                                for w in words
                            ]
                            record("scribe/raw", run, turns, {"latency_ms": payload["latency_ms"]})
                        if want("prod_final"):
                            record("prod_final", run, final_turns(payload["body"], language))

                if want("prod_live"):
                    live_rows, chunks = await prod_live(client, sem, raw, language, vocabulary, run, args.fresh)
                    record("prod_live", run, [Turn(None, s, t, e) for s, e, t in live_rows], {"chunks": chunks})

    out = case / args.out
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print_table(results, reference is not None)
    print(f"\nDetalle (transcripts de cada variante): {out}")


def print_table(results: list[dict], with_ref: bool) -> None:
    head = ["variante", "run", "WER", "ins", "frases de más", "\"uno dos tres probando\"", "personas", "persona ok (palabras)", "persona ok (turnos)", "persona ok (tiempo)", "turnos sin persona", "alucinaciones"]
    print("\n| " + " | ".join(head) + " |")
    print("|" + "---|" * len(head))
    for row in results:
        if "error" in row:
            print(f"| {row['variant']} | {row['run']} | error API | | | | | | | | | |")
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
                    fmt_pct(row.get("time_speaker_acc")),
                    f"{row['orphan_turns']} ({row['orphan_words_pct'] * 100:.0f}% palabras)",
                    str(hall),
                ]
            )
            + " |"
        )


if __name__ == "__main__":
    asyncio.run(main())
