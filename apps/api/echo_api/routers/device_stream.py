"""Streaming de audio desde Echo Devices (ESP32).

El dispositivo se autentica con su device token, puede crear/iniciar una
reunión y transmite PCM16 16 kHz por WebSocket. El servidor transcribe con el
provider cloud de la organización, con los mismos filtros, respaldo e idioma
fijo que el vivo de la web. El audio también va al audio de trabajo de la
reunión, así al terminar tiene la misma pasada final (y se borra después,
services/recording.py). Si la organización usa Echo Bridge
en una PC de la sala, el dispositivo también puede apuntarse a ese bridge por
LAN (config del firmware) y entonces el audio no sale de la red local.
"""
import asyncio
import contextlib
import json
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, WebSocket, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..db import SessionLocal, get_db
from ..models import Device, Meeting, OrganizationMember
from ..routers.live import _record_live_usage, _store_segment
from ..security import hash_refresh_token
from ..services.ai_settings import get_vocabulary, resolve_stt, stt_fallbacks
from ..services.background import spawn
from ..services.insights_live import maybe_extract_live_insights
from ..services.live_bus import live_bus
from ..services.recording import PcmWriter
from ..services.stt import get_stt_provider
from ..services.stt.base import FallbackSttProvider
from ..services.stt.channels import (
    is_noise_transcript,
    is_prompt_echo,
    is_silent,
    is_unreliable,
    repeats_previous,
    strip_hallucinations,
)
from ..services.stt.windowing import find_cut

log = logging.getLogger("echo.device")

router = APIRouter(tags=["devices"])


async def _device_by_token(db, token: str) -> Device | None:
    return (
        await db.execute(
            select(Device).where(
                Device.token_hash == hash_refresh_token(token), Device.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()


class DeviceMeetingIn(BaseModel):
    title: str | None = Field(default=None, max_length=300)


@router.post("/api/devices/meetings", status_code=201)
async def device_create_meeting(
    data: DeviceMeetingIn,
    db=Depends(get_db),
    authorization: str | None = Header(default=None),
):
    """El botón físico del dispositivo puede arrancar una reunión."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Falta token")
    device = await _device_by_token(db, authorization.removeprefix("Bearer ").strip())
    if not device:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Dispositivo no vinculado")

    # Toda reunión tiene quien la creó (y a quien se le anota el consumo): la
    # de un dispositivo es de quien administra la sede. Antes iba vacío y la
    # base lo rechazaba, así que el botón del dispositivo no creaba nada.
    owner = (
        await db.execute(
            select(OrganizationMember.user_id)
            .where(OrganizationMember.organization_id == device.organization_id)
            .order_by((OrganizationMember.role == "owner").desc(), OrganizationMember.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    if owner is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "La sede no tiene miembros")
    meeting = Meeting(
        organization_id=device.organization_id,
        created_by=owner,
        title=data.title or f"Reunión — {device.name}",
        status="live",
        audio_source="device",
        started_at=datetime.now(UTC),
        meta={"visibility": "org", "device_id": str(device.id)},
    )
    db.add(meeting)
    await db.commit()
    await db.refresh(meeting)
    return {"id": str(meeting.id), "title": meeting.title, "status": meeting.status}


@router.post("/api/devices/meetings/{meeting_id}/finish")
async def device_finish_meeting(
    meeting_id: uuid.UUID,
    db=Depends(get_db),
    authorization: str | None = Header(default=None),
):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Falta token")
    device = await _device_by_token(db, authorization.removeprefix("Bearer ").strip())
    if not device:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Dispositivo no vinculado")
    meeting = (
        await db.execute(
            select(Meeting).where(
                Meeting.id == meeting_id, Meeting.organization_id == device.organization_id
            )
        )
    ).scalar_one_or_none()
    if not meeting or meeting.status not in ("live", "paused"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Reunión no activa")
    meeting.status = "processing"
    meeting.ended_at = datetime.now(UTC)
    if meeting.started_at:
        meeting.duration_seconds = int((meeting.ended_at - meeting.started_at).total_seconds())
    meeting.processing_state = {"stage": "queued", "progress": 0}
    await db.commit()
    from ..services.pipeline import run_finalize_pipeline

    spawn(run_finalize_pipeline(str(meeting.id)), name=f"finalize:{meeting.id}")
    await live_bus.publish(str(meeting.id), {"type": "status", "status": "processing"})
    return {"status": "processing"}


@router.websocket("/api/devices/stream")
async def device_stream(websocket: WebSocket):
    token = websocket.query_params.get("token", "")
    meeting_id_raw = websocket.query_params.get("meeting_id", "")
    async with SessionLocal() as db:
        device = await _device_by_token(db, token)
        if not device:
            await websocket.close(code=4401, reason="Dispositivo no vinculado")
            return
        try:
            meeting_id = uuid.UUID(meeting_id_raw)
        except ValueError:
            await websocket.close(code=4400, reason="meeting_id inválido")
            return
        meeting = (
            await db.execute(
                select(Meeting).where(
                    Meeting.id == meeting_id,
                    Meeting.organization_id == device.organization_id,
                    Meeting.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if not meeting or meeting.status not in ("live", "paused"):
            await websocket.close(code=4404, reason="Reunión no activa")
            return
        stt_config = await resolve_stt(db, device.organization_id)
        vocabulary = await get_vocabulary(db, device.organization_id)

    await websocket.accept()
    if stt_config is None:
        await websocket.send_text(
            json.dumps({"type": "error", "code": "stt_not_configured",
                        "message": "Sin motor STT cloud configurado"})
        )
        await websocket.close()
        return

    chain = [get_stt_provider(c.provider, c.api_key, c.model) for c in [stt_config, *stt_fallbacks(stt_config)]]
    provider = chain[0] if len(chain) == 1 else FallbackSttProvider(chain)
    # Idioma fijo, como en la web: con "auto" Whisper adivina por tramo.
    language = meeting.language if meeting.language and meeting.language != "auto" else "es"
    previous_text = ""
    writer = PcmWriter(meeting.id)
    sample_rate = 16000
    audio_buffer = bytearray()
    stream_offset_ms = 0
    channel = str(meeting.id)
    segments_since_insights = 0

    async def flush(upto: int | None = None):
        nonlocal audio_buffer, stream_offset_ms, segments_since_insights, previous_text
        if not audio_buffer:
            return
        cut = len(audio_buffer) if upto is None else upto
        chunk = bytes(audio_buffer[:cut])
        audio_buffer = audio_buffer[cut:]
        duration_ms = int(len(chunk) / 2 / sample_rate * 1000)
        offset = stream_offset_ms
        stream_offset_ms += duration_ms
        if is_silent(chunk, sample_rate):
            del chunk
            return
        try:
            result = await provider.transcribe_chunk(chunk, sample_rate, language, vocabulary, offset_ms=offset)
        except Exception as exc:
            log.warning("device stt error: %s", exc)
            return
        finally:
            del chunk
        await _record_live_usage(meeting, meeting.created_by, provider, duration_ms / 1000)
        for seg in result.segments:
            # Los mismos filtros que el vivo de la web.
            text = strip_hallucinations(seg.text)
            if (
                not text
                or is_unreliable(seg)
                or is_prompt_echo(text, vocabulary)
                or is_noise_transcript(text, language)
                or repeats_previous(text, previous_text)
            ):
                continue
            previous_text = text
            event = await _store_segment(meeting, text, seg.start_ms, seg.end_ms, seg.confidence, "device")
            await live_bus.publish(channel, event)
            segments_since_insights += 1
        if segments_since_insights >= 8:
            segments_since_insights = 0
            spawn(maybe_extract_live_insights(channel), name=f"insights:{channel}")

    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                audio_buffer.extend(message["bytes"])
                writer.write(message["bytes"], 1)
                # Cortes en las pausas, como el WebSocket de la web: el corte
                # fijo cada 6 s partía palabras al medio y el modelo las perdía.
                cut = find_cut(bytes(audio_buffer), sample_rate)
                if cut:
                    await flush(upto=cut)
            elif message.get("text"):
                with contextlib.suppress(json.JSONDecodeError):
                    data = json.loads(message["text"])
                    if data.get("type") == "flush":
                        await flush()
    except Exception as exc:
        log.info("device ws cerrado: %s", exc)
    finally:
        with contextlib.suppress(Exception):
            await flush()
        writer.close()
