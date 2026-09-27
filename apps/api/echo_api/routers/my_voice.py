"""Mi voz: la muestra con la que Echo reconoce a cada persona en las reuniones.

La graba la propia persona, con consentimiento explícito, y la puede borrar
cuando quiera. Se guarda como WAV 16 kHz mono de hasta 10 s (lo que acepta el
modelo que separa hablantes; services/diarization.py).
"""
import asyncio
from datetime import UTC, datetime

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import get_current_user
from ..models import User, UserVoiceSample
from ..services.stt.base import pcm16_to_wav
from ..services.stt.windowing import silence_threshold

router = APIRouter(prefix="/api/me/voice", tags=["voice"])

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MIN_SPEECH_MS = 3000
MAX_MS = 10000


class VoiceOut(BaseModel):
    has_sample: bool
    duration_ms: int | None = None
    recorded_at: datetime | None = None


async def _to_pcm16(data: bytes) -> bytes:
    """Cualquier audio del navegador (webm, mp4/aac, wav) → PCM16 mono 16 kHz."""
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-t", "30",
        "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await process.communicate(data)
    if process.returncode != 0 or not out:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No se pudo leer el audio. Probá grabar de nuevo.")
    return out


def _trim_to_speech(pcm: bytes) -> bytes:
    """Saca el silencio del principio y del final y deja hasta 10 s."""
    samples = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype=np.int16).astype(np.float32)
    frame = 1600  # 100 ms
    count = len(samples) // frame
    if count == 0:
        return b""
    rms = np.sqrt((samples[: count * frame].reshape(count, frame) ** 2).mean(axis=1))
    threshold = silence_threshold(rms)
    voiced = np.nonzero(rms > threshold)[0]
    if len(voiced) * 100 < MIN_SPEECH_MS:
        return b""
    first, last = int(voiced[0]), int(voiced[-1]) + 1
    last = min(last, first + MAX_MS // 100)
    return pcm[first * frame * 2 : last * frame * 2]


@router.get("", response_model=VoiceOut)
async def my_voice(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    sample = (
        await db.execute(select(UserVoiceSample).where(UserVoiceSample.user_id == user.id))
    ).scalar_one_or_none()
    if sample is None:
        return VoiceOut(has_sample=False)
    return VoiceOut(has_sample=True, duration_ms=sample.duration_ms, recorded_at=sample.updated_at)


@router.post("", response_model=VoiceOut)
async def save_my_voice(
    audio: UploadFile = File(...),
    consent: bool = Form(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not consent:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Hace falta tu consentimiento para guardar la muestra")
    data = await audio.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "La grabación es demasiado larga")
    speech = _trim_to_speech(await _to_pcm16(data))
    if not speech:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Casi no se escuchó tu voz. Grabá de nuevo hablando cerca del micrófono unos segundos.",
        )
    sample = (
        await db.execute(select(UserVoiceSample).where(UserVoiceSample.user_id == user.id))
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if sample is None:
        sample = UserVoiceSample(user_id=user.id, audio_wav=b"", duration_ms=0, consent_at=now)
        db.add(sample)
    sample.audio_wav = pcm16_to_wav(speech, 16000)
    sample.duration_ms = len(speech) // 32
    sample.consent_at = now
    await db.commit()
    await db.refresh(sample)
    return VoiceOut(has_sample=True, duration_ms=sample.duration_ms, recorded_at=sample.updated_at)


@router.delete("", status_code=204)
async def delete_my_voice(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    sample = (
        await db.execute(select(UserVoiceSample).where(UserVoiceSample.user_id == user.id))
    ).scalar_one_or_none()
    if sample is not None:
        await db.delete(sample)
        await db.commit()
