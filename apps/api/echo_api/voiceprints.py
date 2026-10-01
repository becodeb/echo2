"""Calcula la huella de las muestras de "Mi voz" que no la tienen (o que la
tienen con otro modelo). Se corre una vez después de desplegar §7.2:

    python -m echo_api.voiceprints            # calcula las que faltan
    python -m echo_api.voiceprints --comparar # y muestra el coseno entre muestras

`--comparar` sirve para calibrar con voces reales sin sacarlas del servidor:
dos muestras de la misma persona tienen que dar bastante más que las de dos
personas distintas (services/voiceprint.py, ACCEPT y MARGIN).
"""
import asyncio
import sys
import wave
from io import BytesIO

import numpy as np
from sqlalchemy import select

from .db import SessionLocal
from .models import User, UserVoiceSample
from .services import voiceprint


def _pcm(wav: bytes) -> bytes:
    with wave.open(BytesIO(wav)) as reader:
        return reader.readframes(reader.getnframes())


async def main(compare: bool) -> None:
    if not voiceprint.available():
        print(f"No está el modelo de huella ({voiceprint.model_path()}): nada que hacer.")
        return
    async with SessionLocal() as db:
        samples = (await db.execute(select(UserVoiceSample, User.name).join(User))).all()
        done = 0
        for sample, _ in samples:
            if sample.embedding_model == voiceprint.MODEL_NAME and sample.sample_embedding is not None:
                continue
            pcm = np.frombuffer(_pcm(sample.audio_wav), dtype=np.int16)
            vector = voiceprint.to_list(await asyncio.to_thread(voiceprint.embed, pcm))
            sample.sample_embedding = vector
            sample.embedding = vector
            sample.embedding_model = voiceprint.MODEL_NAME if vector is not None else None
            sample.learned_count = 0
            done += 1
        await db.commit()
        print(f"{done} huellas calculadas de {len(samples)} muestras.")
        if compare:
            ready = [(name, np.asarray(s.sample_embedding)) for s, name in samples if s.sample_embedding is not None]
            for i, (a, va) in enumerate(ready):
                for b, vb in ready[i + 1:]:
                    print(f"{a} ↔ {b}: {float(np.dot(va, vb)):.2f}")


if __name__ == "__main__":
    asyncio.run(main("--comparar" in sys.argv))
