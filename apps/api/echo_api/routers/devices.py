"""Echo Device (ESP32): pairing por código temporal, estado y sesiones.

Onboarding:
  1. El dispositivo arranca sin token → POST /api/devices/pair/init
     (recibe {code, poll_token}; muestra el código en pantalla).
  2. El usuario entra a Ajustes → Dispositivos → Vincular y escribe el código.
  3. El dispositivo hace polling con poll_token; cuando el usuario reclamó el
     código recibe su device_token definitivo (se guarda en NVS del ESP32).
"""
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import OrgContext, get_org_context, rate_limit
from ..models import Device, DevicePairCode, Meeting
from ..security import hash_refresh_token
from ..services.audit import audit

router = APIRouter(prefix="/api/devices", tags=["devices"])

PAIR_CODE_TTL_MINUTES = 10


# ── Endpoints del DISPOSITIVO (sin auth de usuario) ──────────────


class PairInitIn(BaseModel):
    kind: str = Field(default="esp32", max_length=40)
    info: dict | None = None


@router.post("/pair/init")
async def pair_init(data: PairInitIn, db: AsyncSession = Depends(get_db)):
    rate_limit("device_pair_init", 20, 60)
    code = "".join(secrets.choice("0123456789") for _ in range(6))
    pair = DevicePairCode(
        code=code,
        device_kind=data.kind,
        device_info=data.info,
        expires_at=datetime.now(UTC) + timedelta(minutes=PAIR_CODE_TTL_MINUTES),
        poll_token=secrets.token_urlsafe(32),
    )
    db.add(pair)
    await db.commit()
    return {"code": code, "poll_token": pair.poll_token, "expires_in_seconds": PAIR_CODE_TTL_MINUTES * 60}


class PairPollIn(BaseModel):
    poll_token: str


@router.post("/pair/poll")
async def pair_poll(data: PairPollIn, db: AsyncSession = Depends(get_db)):
    pair = (
        await db.execute(select(DevicePairCode).where(DevicePairCode.poll_token == data.poll_token))
    ).scalar_one_or_none()
    if not pair or pair.expires_at < datetime.now(UTC):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Código expirado; reiniciá el pairing")
    if not pair.claimed_device_id:
        return {"status": "pending"}
    device = await db.get(Device, pair.claimed_device_id)
    if not device:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dispositivo no encontrado")
    # el token en claro está guardado temporalmente en device_info hasta este poll
    token = (pair.device_info or {}).get("_issued_token")
    if not token:
        return {"status": "pending"}
    pair.device_info = {k: v for k, v in (pair.device_info or {}).items() if k != "_issued_token"}
    await db.commit()
    return {"status": "paired", "device_token": token, "device_id": str(device.id), "name": device.name}


class HeartbeatIn(BaseModel):
    firmware_version: str | None = None
    state: dict | None = None


async def _device_from_token(
    db: AsyncSession, authorization: str | None
) -> Device:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Falta token de dispositivo")
    token = authorization.removeprefix("Bearer ").strip()
    device = (
        await db.execute(
            select(Device).where(
                Device.token_hash == hash_refresh_token(token), Device.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if not device:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Dispositivo no vinculado")
    return device


@router.post("/heartbeat")
async def device_heartbeat(
    data: HeartbeatIn,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    device = await _device_from_token(db, authorization)
    device.last_seen_at = datetime.now(UTC)
    if data.firmware_version:
        device.firmware_version = data.firmware_version
    if data.state is not None:
        device.last_state = data.state
    await db.commit()
    # meeting activa de la organización, para que el dispositivo pueda unirse
    active = (
        await db.execute(
            select(Meeting)
            .where(
                Meeting.organization_id == device.organization_id,
                Meeting.status.in_(["live", "paused"]),
                Meeting.deleted_at.is_(None),
            )
            .order_by(Meeting.started_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return {
        "ok": True,
        "available_version": device.available_version,
        "active_meeting": {"id": str(active.id), "title": active.title, "status": active.status}
        if active
        else None,
    }


# ── Endpoints del USUARIO ────────────────────────────────────────


class ClaimIn(BaseModel):
    code: str = Field(min_length=4, max_length=12)
    name: str = Field(default="Echo Device", max_length=200)


@router.post("/claim", status_code=201)
async def claim_device(
    data: ClaimIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    ctx.require_role("member")
    pair = (
        await db.execute(select(DevicePairCode).where(DevicePairCode.code == data.code.strip()))
    ).scalar_one_or_none()
    if not pair or pair.expires_at < datetime.now(UTC) or pair.claimed_device_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Código inválido o expirado")

    token = secrets.token_urlsafe(40)
    device = Device(
        organization_id=ctx.org_id,
        name=data.name.strip(),
        kind=pair.device_kind,
        token_hash=hash_refresh_token(token),
    )
    db.add(device)
    await db.flush()
    pair.claimed_device_id = device.id
    pair.device_info = {**(pair.device_info or {}), "_issued_token": token}
    await audit(db, ctx.org_id, ctx.user.id, "device.claim", "device", str(device.id))
    await db.commit()
    return {"id": str(device.id), "name": device.name}


@router.get("")
async def list_devices(ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)):
    rows = (
        (
            await db.execute(
                select(Device)
                .where(Device.organization_id == ctx.org_id, Device.deleted_at.is_(None))
                .order_by(Device.created_at)
            )
        )
        .scalars()
        .all()
    )
    now = datetime.now(UTC)
    return [
        {
            "id": str(d.id),
            "name": d.name,
            "kind": d.kind,
            "firmware_version": d.firmware_version,
            "available_version": d.available_version,
            "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
            "online": bool(d.last_seen_at and (now - d.last_seen_at).total_seconds() < 60),
            "state": d.last_state,
        }
        for d in rows
    ]


class DeviceRenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


@router.patch("/{device_id}")
async def rename_device(
    device_id: uuid.UUID,
    data: DeviceRenameIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    ctx.require_role("member")
    device = (
        await db.execute(
            select(Device).where(Device.id == device_id, Device.organization_id == ctx.org_id)
        )
    ).scalar_one_or_none()
    if not device:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dispositivo no encontrado")
    device.name = data.name.strip()
    await db.commit()
    return {"id": str(device.id), "name": device.name}


@router.delete("/{device_id}", status_code=204)
async def unlink_device(
    device_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    ctx.require_role("admin")
    device = (
        await db.execute(
            select(Device).where(Device.id == device_id, Device.organization_id == ctx.org_id)
        )
    ).scalar_one_or_none()
    if not device:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dispositivo no encontrado")
    device.deleted_at = datetime.now(UTC)
    await audit(db, ctx.org_id, ctx.user.id, "device.unlink", "device", str(device.id))
    await db.commit()
