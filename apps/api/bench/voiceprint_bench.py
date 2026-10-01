"""Banco de huellas de voz (docs/plan-correcciones.md §7.2): ¿alcanza la huella
para poner el nombre correcto, y con qué umbral y margen?

Para cada reunión del banco con personas marcadas, simula "Mi voz" con los
primeros ~9 s de cada persona (como la muestra que se graba) y arma la huella
de "la persona en la reunión" con hasta 30 s del resto de sus turnos limpios
(como services/voiceprint.py). Después compara todas contra todas, también
entre reuniones (Bautista está en las tres): misma persona vs. otra persona.

Uso (en apps/api, con ffmpeg en el PATH y el modelo en models/; si los audios
están en otra carpeta que la del case.json, BENCH_AUDIO_DIR):
    python bench/voiceprint_bench.py
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from echo_api.services import voiceprint  # noqa: E402

CASES = Path(__file__).parent / "casos"
ENROLL_MS = 9000
# Quién es quién entre reuniones (las letras son por reunión).
SAME_PERSON = {
    ("2026-09-27", "A"): "Bautista",
    # Probable (no confirmado escuchando): "uno, tres, probando" y 0,90 contra
    # el Bautista del 1/10.
    ("2026-09-30", "A"): "Bautista",
    ("2026-10-01", "A"): "Bautista",
    ("2026-10-01", "B"): "Laura",
    ("2026-09-27", "B"): "Vanina",
    ("2026-09-27", "C"): "Choto",
}


def _audio(path: str) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-i", path, "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.int16)


def _turns(case_dir: Path) -> list[tuple[str, int, int]]:
    case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
    if case.get("turns"):
        return [tuple(t) for t in case["turns"]]
    reference = case_dir / "reference.txt"
    if not reference.exists():
        reference = case_dir / "reference.draft.txt"
    turns = []
    for line in reference.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\[(\d+):(\d+)-(\d+):(\d+)\] ([A-Z]):", line)
        if match:
            a, b, c, d, who = match.groups()
            turns.append((who, (int(a) * 60 + int(b)) * 1000, (int(c) * 60 + int(d)) * 1000 + 999))
    return turns


def main() -> None:
    enrolled: dict[str, np.ndarray] = {}
    meeting: dict[str, np.ndarray] = {}
    for case_dir in sorted(CASES.iterdir()):
        case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
        audio = Path(case["audio"])
        if not audio.exists() and os.environ.get("BENCH_AUDIO_DIR"):
            audio = Path(os.environ["BENCH_AUDIO_DIR"]) / audio.name
        if not audio.exists():
            continue
        pcm = _audio(str(audio))
        turns = _turns(case_dir)
        clean = voiceprint.clean_turns(turns)
        for who in sorted({t[0] for t in clean}):
            mine = [(s, e) for w, s, e in clean if w == who]
            enroll, rest, taken = [], [], 0
            for start, end in mine:
                (enroll if taken < ENROLL_MS else rest).append((start, end))
                taken += end - start
            key = f"{case_dir.name}/{who}"
            if enroll and rest:
                enrolled[key] = voiceprint.embed_spans(pcm, enroll)
                meeting[key] = voiceprint.embed_spans(pcm, rest)
            print(f"{key}: {sum(e - s for s, e in mine) / 1000:.1f} s limpios")

    def person(key: str) -> str:
        day, who = key.split("/")
        return SAME_PERSON.get((day, who), key)

    same, other = [], []
    print("\nmuestra → reunión (coseno)")
    for a, ea in enrolled.items():
        row = []
        for b, eb in meeting.items():
            score = float(np.dot(ea, eb))
            (same if person(a) == person(b) else other).append(score)
            row.append(f"{b}={score:.2f}")
        print(f"  {a}: " + "  ".join(row))
    print(f"\nmisma persona: min {min(same):.2f} · prom {np.mean(same):.2f}")
    print(f"otra persona:  max {max(other):.2f} · prom {np.mean(other):.2f}")
    print(f"umbrales: nombra desde {voiceprint.ACCEPT} con margen {voiceprint.MARGIN}; sugiere desde {voiceprint.SUGGEST}")


if __name__ == "__main__":
    main()
