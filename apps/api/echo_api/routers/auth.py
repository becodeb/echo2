"""Registro, login, refresh, logout, organizaciones e invitaciones."""
import re
import secrets
import unicodedata
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..deps import get_current_user, rate_limit
from ..models import (
    Organization,
    OrganizationInvite,
    OrganizationMember,
    RefreshToken,
    User,
)
from ..security import (
    create_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)
from ..services.audit import audit

router = APIRouter(prefix="/api/auth", tags=["auth"])

REFRESH_COOKIE = "echo_refresh"

AVATAR_COLORS = ["#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#14b8a6"]


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    name: str = Field(min_length=1, max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    avatar_color: str
    job_title: str | None
    locale: str
    is_superadmin: bool

    class Config:
        from_attributes = True


class OrgOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    role: str


class SessionOut(BaseModel):
    access_token: str
    user: UserOut
    organizations: list[OrgOut]


def _slugify(name: str) -> str:
    base = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-") or "org"
    return f"{base[:60]}-{secrets.token_hex(3)}"


async def _user_orgs(db: AsyncSession, user_id: uuid.UUID) -> list[OrgOut]:
    rows = (
        await db.execute(
            select(Organization, OrganizationMember.role)
            .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
            .where(OrganizationMember.user_id == user_id, Organization.deleted_at.is_(None))
            .order_by(Organization.created_at)
        )
    ).all()
    return [OrgOut(id=o.id, name=o.name, slug=o.slug, role=r) for o, r in rows]


def _set_refresh_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=s.refresh_token_days * 86400,
        httponly=True,
        secure=s.is_production,
        samesite="lax",
        path="/api/auth",
    )


async def _issue_refresh(db: AsyncSession, user: User, request: Request) -> str:
    s = get_settings()
    token = new_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_refresh_token(token),
            expires_at=datetime.now(UTC) + timedelta(days=s.refresh_token_days),
            user_agent=(request.headers.get("user-agent") or "")[:400],
        )
    )
    return token


async def _session_payload(db: AsyncSession, user: User) -> SessionOut:
    return SessionOut(
        access_token=create_access_token(str(user.id)),
        user=UserOut.model_validate(user),
        organizations=await _user_orgs(db, user.id),
    )


@router.post("/register", response_model=SessionOut, status_code=201)
async def register(
    data: RegisterIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)
):
    s = get_settings()
    rate_limit(f"register:{request.client.host if request.client else 'x'}", s.rate_limit_auth_per_minute)

    existing = (
        await db.execute(select(User).where(User.email == data.email.lower()))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe una cuenta con ese email")

    user = User(
        email=data.email.lower(),
        password_hash=hash_password(data.password),
        name=data.name.strip(),
        avatar_color=secrets.choice(AVATAR_COLORS),
    )
    db.add(user)
    await db.flush()

    refresh = await _issue_refresh(db, user, request)
    await audit(db, None, user.id, "user.register", "user", str(user.id))
    await db.commit()

    _set_refresh_cookie(response, refresh)
    return await _session_payload(db, user)


@router.post("/login", response_model=SessionOut)
async def login(
    data: LoginIn, request: Request, response: Response, db: AsyncSession = Depends(get_db)
):
    s = get_settings()
    rate_limit(f"login:{request.client.host if request.client else 'x'}", s.rate_limit_auth_per_minute)

    user = (
        await db.execute(select(User).where(User.email == data.email.lower()))
    ).scalar_one_or_none()
    if user and not user.password_hash:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Esta cuenta entra con Google. Usá el botón “Continuar con Google”.",
        )
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email o contraseña incorrectos")
    if not user.is_active or user.deleted_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Cuenta deshabilitada")

    refresh = await _issue_refresh(db, user, request)
    await db.commit()

    _set_refresh_cookie(response, refresh)
    return await _session_payload(db, user)


@router.post("/refresh", response_model=SessionOut)
async def refresh_session(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    # CSRF: cookie SameSite=Lax + este header custom obligatorio
    if request.headers.get("x-echo-client") != "web":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cliente no reconocido")

    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sin sesión")

    stored = (
        await db.execute(select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw)))
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if not stored or stored.revoked_at is not None or stored.expires_at < now:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión expirada")

    user = await db.get(User, stored.user_id)
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuario inválido")

    # Rotación: revocar el token usado y emitir uno nuevo
    stored.revoked_at = now
    new_raw = await _issue_refresh(db, user, request)
    await db.commit()

    _set_refresh_cookie(response, new_raw)
    return await _session_payload(db, user)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        stored = (
            await db.execute(
                select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw))
            )
        ).scalar_one_or_none()
        if stored:
            stored.revoked_at = datetime.now(UTC)
            await db.commit()
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")


@router.get("/me", response_model=SessionOut)
async def me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    return await _session_payload(db, user)


# ── Organizaciones ───────────────────────────────────────────────


class CreateOrgIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


@router.post("/organizations", response_model=OrgOut, status_code=201)
async def create_organization(
    data: CreateOrgIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    org = Organization(name=data.name.strip(), slug=_slugify(data.name))
    db.add(org)
    await db.flush()
    db.add(OrganizationMember(organization_id=org.id, user_id=user.id, role="owner"))
    await audit(db, org.id, user.id, "org.create", "organization", str(org.id))
    await db.commit()
    return OrgOut(id=org.id, name=org.name, slug=org.slug, role="owner")


class AcceptInviteIn(BaseModel):
    token: str


@router.post("/invites/accept", response_model=OrgOut)
async def accept_invite(
    data: AcceptInviteIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    invite = (
        await db.execute(select(OrganizationInvite).where(OrganizationInvite.token == data.token))
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if not invite or invite.accepted_at is not None or invite.expires_at < now:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invitación inválida o expirada")
    if invite.email.lower() != user.email.lower():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "La invitación es para otro email")

    existing = (
        await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == invite.organization_id,
                OrganizationMember.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if not existing:
        db.add(
            OrganizationMember(
                organization_id=invite.organization_id, user_id=user.id, role=invite.role
            )
        )
    invite.accepted_at = now
    org = await db.get(Organization, invite.organization_id)
    await audit(db, org.id, user.id, "org.invite_accepted", "organization", str(org.id))
    await db.commit()
    return OrgOut(id=org.id, name=org.name, slug=org.slug, role=invite.role)
