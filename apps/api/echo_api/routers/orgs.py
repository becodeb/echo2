"""Gestión de la organización: miembros, invitaciones, diccionario."""
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import OrgContext, get_org_context
from ..models import (
    ROLES,
    OrganizationInvite,
    OrganizationMember,
    OrgDictionaryEntry,
    User,
)
from ..services.audit import audit

router = APIRouter(prefix="/api/org", tags=["org"])


class MemberOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    email: str
    avatar_color: str
    job_title: str | None
    role: str


@router.get("/members", response_model=list[MemberOut])
async def list_members(ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(OrganizationMember, User)
            .join(User, User.id == OrganizationMember.user_id)
            .where(OrganizationMember.organization_id == ctx.org_id)
            .order_by(User.name)
        )
    ).all()
    return [
        MemberOut(
            id=m.id,
            user_id=u.id,
            name=u.name,
            email=u.email,
            avatar_color=u.avatar_color,
            job_title=u.job_title,
            role=m.role,
        )
        for m, u in rows
    ]


class InviteIn(BaseModel):
    email: EmailStr
    role: str = Field(default="member")


class InviteOut(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    token: str
    expires_at: datetime


@router.post("/invites", response_model=InviteOut, status_code=201)
async def create_invite(
    data: InviteIn, ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)
):
    ctx.require_role("admin")
    if data.role not in ROLES or data.role == "owner":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Rol inválido")

    invite = OrganizationInvite(
        organization_id=ctx.org_id,
        email=data.email.lower(),
        role=data.role,
        token=secrets.token_urlsafe(32),
        invited_by=ctx.user.id,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    db.add(invite)
    await audit(db, ctx.org_id, ctx.user.id, "org.invite_created", "invite", data.email)
    await db.commit()
    await db.refresh(invite)
    return InviteOut(
        id=invite.id, email=invite.email, role=invite.role, token=invite.token,
        expires_at=invite.expires_at,
    )


@router.get("/invites", response_model=list[InviteOut])
async def list_invites(ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)):
    ctx.require_role("admin")
    rows = (
        (
            await db.execute(
                select(OrganizationInvite).where(
                    OrganizationInvite.organization_id == ctx.org_id,
                    OrganizationInvite.accepted_at.is_(None),
                    OrganizationInvite.expires_at > datetime.now(UTC),
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        InviteOut(id=i.id, email=i.email, role=i.role, token=i.token, expires_at=i.expires_at)
        for i in rows
    ]


class RoleIn(BaseModel):
    role: str


@router.patch("/members/{member_id}", response_model=MemberOut)
async def change_role(
    member_id: uuid.UUID,
    data: RoleIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    ctx.require_role("admin")
    if data.role not in ROLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Rol inválido")
    member = (
        await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.id == member_id,
                OrganizationMember.organization_id == ctx.org_id,
            )
        )
    ).scalar_one_or_none()
    if not member:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Miembro no encontrado")
    if member.role == "owner":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No se puede cambiar el rol del owner")
    if data.role == "owner":
        ctx.require_role("owner")
    member.role = data.role
    await audit(db, ctx.org_id, ctx.user.id, "org.role_changed", "member", str(member_id))
    await db.commit()
    user = await db.get(User, member.user_id)
    return MemberOut(
        id=member.id, user_id=user.id, name=user.name, email=user.email,
        avatar_color=user.avatar_color, job_title=user.job_title, role=member.role,
    )


@router.delete("/members/{member_id}", status_code=204)
async def remove_member(
    member_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    ctx.require_role("admin")
    member = (
        await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.id == member_id,
                OrganizationMember.organization_id == ctx.org_id,
            )
        )
    ).scalar_one_or_none()
    if not member:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Miembro no encontrado")
    if member.role == "owner":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No se puede eliminar al owner")
    await db.delete(member)
    await audit(db, ctx.org_id, ctx.user.id, "org.member_removed", "member", str(member_id))
    await db.commit()


# ── Diccionario personalizado ────────────────────────────────────


class DictEntryIn(BaseModel):
    term: str = Field(min_length=1, max_length=120)
    kind: str = Field(default="term")
    note: str | None = Field(default=None, max_length=300)


class DictEntryOut(DictEntryIn):
    id: uuid.UUID

    class Config:
        from_attributes = True


@router.get("/dictionary", response_model=list[DictEntryOut])
async def list_dictionary(
    ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)
):
    rows = (
        (
            await db.execute(
                select(OrgDictionaryEntry)
                .where(OrgDictionaryEntry.organization_id == ctx.org_id)
                .order_by(OrgDictionaryEntry.term)
            )
        )
        .scalars()
        .all()
    )
    return rows


@router.post("/dictionary", response_model=DictEntryOut, status_code=201)
async def add_dictionary_entry(
    data: DictEntryIn, ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)
):
    ctx.require_role("member")
    entry = OrgDictionaryEntry(
        organization_id=ctx.org_id, term=data.term.strip(), kind=data.kind, note=data.note
    )
    db.add(entry)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "El término ya existe")
    await db.refresh(entry)
    return entry


@router.delete("/dictionary/{entry_id}", status_code=204)
async def delete_dictionary_entry(
    entry_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    ctx.require_role("member")
    await db.execute(
        delete(OrgDictionaryEntry).where(
            OrgDictionaryEntry.id == entry_id,
            OrgDictionaryEntry.organization_id == ctx.org_id,
        )
    )
    await db.commit()
