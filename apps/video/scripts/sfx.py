"""Efectos de sonido de la demo, sintetizados (deterministas, sin bancos externos).

    python3 scripts/sfx.py   → public/sfx/*.wav (44,1 kHz, 16 bit, mono)

- click: un click de mouse (presiona y suelta, 55 ms entre los dos).
- key1..key4: teclas de un teclado de notebook, cada una con su timbre.
- tick: la confirmación de una afirmación verificada.
- whoosh: aire muy suave para las transformaciones de la superficie.
"""
import wave
from pathlib import Path

import numpy as np

SR = 44100
OUT = Path(__file__).resolve().parent.parent / "public" / "sfx"
rng = np.random.default_rng(7)


def t(seconds):
    return np.arange(int(SR * seconds)) / SR


def resonance(freq, decay, length, phase=0.0):
    x = t(length)
    return np.sin(2 * np.pi * freq * x + phase) * np.exp(-x / decay)


def transient(length, decay):
    x = t(length)
    noise = rng.standard_normal(len(x))
    noise = np.diff(noise, prepend=0)  # agudo: saca el grave del ruido
    return noise * np.exp(-x / decay)


def normalize(signal, peak_db):
    peak = np.max(np.abs(signal)) or 1
    return signal / peak * 10 ** (peak_db / 20)


def fade_out(signal, ms=6):
    n = int(SR * ms / 1000)
    signal[-n:] *= np.linspace(1, 0, n)
    return signal


def save(name, signal):
    OUT.mkdir(parents=True, exist_ok=True)
    data = (np.clip(signal, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(OUT / f"{name}.wav"), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SR)
        out.writeframes(data.tobytes())


def click_part(gain, body):
    length = 0.03
    part = transient(length, 0.0012) * 0.8
    part += resonance(body, 0.004, length) * 0.9
    part += resonance(170, 0.006, length) * 0.5
    return part * gain


# Click de mouse: presiona (más fuerte) y suelta.
click = np.zeros(int(SR * 0.12))
press = click_part(1.0, 2350)
release = click_part(0.55, 2600)
click[: len(press)] += press
start = int(SR * 0.055)
click[start : start + len(release)] += release
save("click", fade_out(normalize(click, -3)))

# Teclas: un golpe corto, cada una con un cuerpo distinto.
for index, body in enumerate([1750, 1980, 2240, 2450], start=1):
    key = transient(0.05, 0.0009) * 0.7 + resonance(body, 0.0028, 0.05) * 0.8 + resonance(140, 0.004, 0.05) * 0.35
    save(f"key{index}", fade_out(normalize(key, -4)))

# Tick: dos parciales limpios, ataque de 2 ms.
x = t(0.18)
tick = (np.sin(2 * np.pi * 1760 * x) + 0.45 * np.sin(2 * np.pi * 2640 * x)) * np.exp(-x / 0.045)
tick *= np.minimum(1, x / 0.002)
save("tick", fade_out(normalize(tick, -6)))

# Whoosh: ruido rosado con un filtro que se abre y se cierra.
length = 0.42
x = t(length)
white = rng.standard_normal(len(x))
spectrum = np.fft.rfft(white)
freqs = np.fft.rfftfreq(len(white), 1 / SR)
pink = np.fft.irfft(spectrum / np.sqrt(np.maximum(freqs, 20)), len(white))
cutoff = 300 + 2600 * np.sin(np.pi * x / length) ** 2
filtered = np.zeros_like(pink)
state = 0.0
for i, sample in enumerate(pink):
    alpha = 1 - np.exp(-2 * np.pi * cutoff[i] / SR)
    state += alpha * (sample - state)
    filtered[i] = state
whoosh = filtered * np.sin(np.pi * x / length) ** 2
save("whoosh", fade_out(normalize(whoosh, -10), 20))
print("ok", sorted(p.name for p in OUT.iterdir()))
