"""Extiende la pista de la demo de Testra (34 s) al largo de la demo de Echo.

    python3 scripts/music.py   → public/music.mp3 (44 s)

La pista va a 120 BPM con el primer golpe a los 0,283 s (medido). Se repiten
cinco compases (12,283 → 22,283 s): los dos cortes caen en un golpe y en el
mismo lugar del compás, así la grilla del video no se corre. Crossfade de
equal-power de 40 ms en el empalme para que no haga clic.
"""
import subprocess
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "public" / "music-testra.mp3"
TARGET = ROOT / "public" / "music.mp3"
SR = 48000
REPEAT_FROM, REPEAT_TO = 12.283, 22.283  # golpes 24 y 44: cinco compases
FADE = 0.04

tmp = ROOT / "out" / "music-src.wav"
tmp.parent.mkdir(exist_ok=True)
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(SOURCE), "-ar", str(SR), "-ac", "2", str(tmp)], check=True)
with wave.open(str(tmp)) as w:
    audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).reshape(-1, 2).astype(np.float32)

cut_a = int(REPEAT_TO * SR)  # hasta acá la primera pasada...
cut_b = int(REPEAT_FROM * SR)  # ...y sigue desde acá (se repiten los cinco compases)
n = int(FADE * SR)
t = np.linspace(0, np.pi / 2, n)[:, None]
joint = audio[cut_a - n // 2 : cut_a + n - n // 2] * np.cos(t) + audio[cut_b - n // 2 : cut_b + n - n // 2] * np.sin(t)
out = np.concatenate([audio[: cut_a - n // 2], joint, audio[cut_b + n - n // 2 :]])

wav = ROOT / "out" / "music-long.wav"
with wave.open(str(wav), "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(np.clip(out, -32768, 32767).astype(np.int16).tobytes())
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-c:a", "libmp3lame", "-b:a", "256k", str(TARGET)], check=True)
print(f"{TARGET.name}: {len(out) / SR:.2f} s")
