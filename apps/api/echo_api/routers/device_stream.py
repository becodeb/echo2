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
from ..models import Device, Meeting, Organization, OrganizationMember, User
from ..routers.live import _record_live_usage, _store_segment
from ..security import hash_refresh_token
from ..services import plans
from ..services.ai_settings import get_vocabulary, resolve_stt
from ..services.background import spawn
from ..services.insights_live import maybe_extract_live_insights
from ..services.live_bus import live_bus
from ..services.recording import PcmWriter, pcm_path
from ..services.stt import get_stt_provider
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
    # El dispositivo puede marcar una reunión con menores, nunca desmarcarla:
    # eso es del ajuste del dispositivo (Ajustes → Dispositivos).
    minors: bool = False


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
        meta={"visibility": "org", "device_id": str(device.id), "minors": bool(device.minors or data.minors)},
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
        # Un dispositivo de un aula con menores marca la reunión a la que se
        # suma (y no se desmarca): si no, la pasada final mandaría el audio de
        # los chicos a separar voces y a comparar con huellas de voz.
        if device.minors and not plans.minors_present(meeting):
            meeting.meta = {**(meeting.meta or {}), "minors": True}
            await db.commit()
        stt_config = await resolve_stt(db, device.organization_id)
        vocabulary = await get_vocabulary(db, device.organization_id)
        org = await db.get(Organization, meeting.organization_id)
        creator = await db.get(User, meeting.created_by) if meeting.created_by else None
        # El plan Gratis corta a la hora, como el vivo de la web.
        free_limit = not (
            plans.is_paid(org, creator) if creator else org is not None and org.plan in plans.PAID_ORG_PLANS
        )

    await websocket.accept()
    if stt_config is None:
        await websocket.send_text(
            json.dumps({"type": "error", "code": "stt_not_configured",
                        "message": "Sin motor STT cloud configurado"})
        )
        await websocket.close()
        return

    # Sin respaldo en otro proveedor: un tramo que Groq no transcribe queda en
    # el audio de trabajo y sale en la pasada final.
    provider = get_stt_provider(stt_config.provider, stt_config.api_key, stt_config.model)
    # Idioma fijo, como en la web: con "auto" Whisper adivina por tramo.
    language = meeting.language if meeting.language and meeting.language != "auto" else "es"
    previous_text = ""
    writer = PcmWriter(meeting.id)
    sample_rate = 16000
    audio_buffer = bytearray()
    stream_offset_ms = 0
    channel = str(meeting.id)
    segments_since_insights = 0
    # Horas de audio del mes de quien administra la sede (§2.2).
    audio_guard = plans.AudioGuard(meeting.id, meeting.organization_id, meeting.created_by)
    existing = pcm_path(meeting.id)
    audio_ms = existing.stat().st_size // 32 if existing.exists() else 0

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
        if is_silent(chunk, sample_rate) or not await audio_guard.allowed(offset):
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
                audio_ms += int(len(message["bytes"]) / 2 / sample_rate * 1000)
                if free_limit and audio_ms >= plans.FREE_MEETING_SECONDS * 1000:
                    await websocket.send_text(json.dumps({
                        "type": "limit", "code": "meeting_length",
                        "message": "En el plan Gratis las reuniones duran hasta una hora.",
                    }))
                    break
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
