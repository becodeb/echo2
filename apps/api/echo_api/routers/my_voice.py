"""Mi voz: la muestra con la que Echo reconoce a cada persona en las reuniones.

La graba la propia persona, con consentimiento explícito, y la puede borrar
cuando quiera. Se guarda como WAV 16 kHz mono de hasta 12 s, con su huella
(services/voiceprint.py), que se calcula acá, en el servidor de Echo.

"Mejorar el reconocimiento con mis reuniones" (§7.4) viene prendido al
grabar (decisión de Bauti, 1/10) y se puede apagar: al apagarlo, el perfil
vuelve a ser solo la muestra. Desde el 27/10 Echo no suma reuniones al perfil
(aprendía de lo que adivinaba); la opción queda para olvidar lo aprendido.

Desde el 27/10 grabarla es "medio obligatorio" (pedido de Bauti): la
invitación ya no se apaga para siempre, "Más tarde" la frena un día
(PROMPT_SNOOZE), y la campanita lo recuerda (services/voice_reminder.py).
"""
import asyncio
from datetime import UTC, datetime, timedelta

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import get_current_user
from ..models import Notification, User, UserVoiceSample
from ..services import voiceprint
from ..services.speaker_names import fingerprint_sample
from ..services.stt.base import pcm16_to_wav
from ..services.stt.windowing import silence_threshold
from ..services.voice_reminder import VOICE_REMINDER_KIND

router = APIRouter(prefix="/api/me/voice", tags=["voice"])

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MIN_SPEECH_MS = 3000
MAX_MS = 12000
# Calidad de la muestra (§7.5): voz por debajo de esto (dBFS) quedó baja;
# menos de esta diferencia entre voz y fondo (dB), con ruido.
LOW_LEVEL_DBFS = -38.0
MIN_SNR_DB = 15.0
# "Más tarde" en la invitación a grabarla: vuelve a aparecer pasado esto.
PROMPT_SNOOZE = timedelta(days=1)


class VoiceOut(BaseModel):
    has_sample: bool
    duration_ms: int | None = None
    recorded_at: datetime | None = None
    # Eligió "Más tarde" en la invitación a grabarla hace menos de un día.
    prompt_seen: bool = False
    learn_from_meetings: bool = True
    # Cuántas reuniones sumaron a su perfil.
    learned_count: int = 0
    # "baja" | "ruido": se guardó igual, pero conviene grabar de nuevo.
    # "corta": de antes del mínimo de 8 s; Echo no la usa hasta grabarla de nuevo.
    warning: str | None = None


def _out(sample: UserVoiceSample, seen: bool, warning: str | None = None) -> VoiceOut:
    if sample.duration_ms < voiceprint.MIN_SAMPLE_MS:
        warning = "corta"
    return VoiceOut(
        has_sample=True, duration_ms=sample.duration_ms, recorded_at=sample.updated_at, prompt_seen=seen,
        learn_from_meetings=sample.learn_from_meetings, learned_count=sample.learned_count, warning=warning,
    )


def _quality(pcm: bytes) -> str | None:
    """¿La muestra quedó muy baja o con mucho ruido de fondo?"""
    samples = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype=np.int16).astype(np.float32)
    frame = 1600
    count = len(samples) // frame
    if count < 5:
        return None
    rms = np.sqrt((samples[: count * frame].reshape(count, frame) ** 2).mean(axis=1)) + 1e-3
    loud = float(np.percentile(rms, 90))
    quiet = float(np.percentile(rms, 10))
    if 20 * np.log10(loud / 32768.0) < LOW_LEVEL_DBFS:
        return "baja"
    if 20 * np.log10(loud / quiet) < MIN_SNR_DB:
        return "ruido"
    return None


async def _to_pcm16(data: bytes) -> bytes:
    """Cualquier audio del navegador (webm, mp4/aac, wav) → PCM16 mono 16 kHz."""
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-loglevel", "error", "-protocol_whitelist", "pipe", "-i", "pipe:0", "-t", "30",
        "-ac", "1", "-ar", "16000", "-f", "s16le", "pipe:1",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await process.communicate(data)
    if process.returncode != 0 or not out:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No se pudo leer el audio. Probá grabar de nuevo.")
    return out


def _trim_to_speech(pcm: bytes) -> bytes:
    """Saca el silencio del principio y del final y deja hasta 12 s.

    Vacío si casi no hay voz o si lo que queda dura menos de 8 s
    (voiceprint.MIN_SAMPLE_MS): una muestra corta se parece a cualquiera."""
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
    if (last - first) * 100 < voiceprint.MIN_SAMPLE_MS:
        return b""
    return pcm[first * frame * 2 : last * frame * 2]


def _snoozed(user: User) -> bool:
    """Antes era "No volver a mostrar" para siempre; ahora dura un día, así
    que a quienes lo habían apagado se les vuelve a pedir."""
    return user.voice_prompt_seen_at is not None and user.voice_prompt_seen_at > datetime.now(UTC) - PROMPT_SNOOZE


@router.get("", response_model=VoiceOut)
async def my_voice(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    sample = (
        await db.execute(select(UserVoiceSample).where(UserVoiceSample.user_id == user.id))
    ).scalar_one_or_none()
    seen = _snoozed(user)
    if sample is None:
        return VoiceOut(has_sample=False, prompt_seen=seen)
    return _out(sample, seen)


@router.post("/prompt-seen", status_code=204)
async def voice_prompt_seen(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """"Más tarde" en la invitación a grabar la voz: no aparece por un día
    (PROMPT_SNOOZE). Sin esto, a quien no tiene muestra le aparece cada vez
    que entra."""
    user.voice_prompt_seen_at = datetime.now(UTC)
    await db.commit()


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
    recorded = await _to_pcm16(data)
    speech = _trim_to_speech(recorded)
    if not speech:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Casi no se escuchó tu voz o quedó corta. Grabá de nuevo leyendo el texto completo, cerca del micrófono.",
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
    fingerprint = await fingerprint_sample(speech)
    sample.sample_embedding = fingerprint
    sample.embedding = fingerprint
    sample.embedding_model = voiceprint.MODEL_NAME if fingerprint is not None else None
    sample.learned_count = 0
    sample.learn_from_meetings = True
    # Ya la grabó: el recordatorio de la campanita sobra, en todas sus sedes.
    if sample.duration_ms >= voiceprint.MIN_SAMPLE_MS:
        await db.execute(
            delete(Notification).where(Notification.user_id == user.id, Notification.kind == VOICE_REMINDER_KIND)
        )
    await db.commit()
    await db.refresh(sample)
    return _out(sample, _snoozed(user), _quality(recorded))


class LearnIn(BaseModel):
    learn_from_meetings: bool


@router.patch("", response_model=VoiceOut)
async def set_learning(data: LearnIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Prender o apagar "Mejorar el reconocimiento con mis reuniones". Al
    apagarlo se olvida lo aprendido: el perfil vuelve a ser solo la muestra."""
    sample = (
        await db.execute(select(UserVoiceSample).where(UserVoiceSample.user_id == user.id))
    ).scalar_one_or_none()
    if sample is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Todavía no grabaste tu voz")
    sample.learn_from_meetings = data.learn_from_meetings
    if not data.learn_from_meetings:
        sample.embedding = sample.sample_embedding
        sample.learned_count = 0
    await db.commit()
    await db.refresh(sample)
    return _out(sample, _snoozed(user))


@router.delete("", status_code=204)
async def delete_my_voice(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    sample = (
        await db.execute(select(UserVoiceSample).where(UserVoiceSample.user_id == user.id))
    ).scalar_one_or_none()
    if sample is not None:
        await db.delete(sample)
        await db.commit()
