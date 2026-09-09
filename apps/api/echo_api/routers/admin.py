"""Panel de superadmin: ver todas las organizaciones y configurarles la IA.

Esto es transversal a la instalación, no a una organización, así que no usa
get_org_context ni el header X-Organization-Id: un superadmin no es miembro de
las organizaciones que administra.

El superadmin nunca lee una API key: la carga y la ve enmascarada, igual que
en Ajustes → IA. Lo que se guarda va cifrado con la misma clave de siempre.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import get_current_user
from ..models import (
    Meeting,
    OrgAISettings,
    Organization,
    OrganizationMember,
    User,
)
from ..security import decrypt_secret, encrypt_secret, mask_secret
from ..services.ai_settings import resolve_llm
from ..services.audit import audit

router = APIRouter(prefix="/api/admin", tags=["admin"])

LLM_PROVIDERS = ["openai", "anthropic", "gemini", "groq", "openrouter", "gmi", "ollama"]


async def get_superadmin(user: User = Depends(get_current_user)) -> User:
    if not user.is_superadmin:
        # 404 y no 403: para quien no es superadmin, este panel no existe.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No encontrado")
    return user


class AdminOrgOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    members: int
    meetings: int
    # Qué LLM va a usar esta organización ahora mismo, ya resolviendo el
    # fallback al default del servidor. Sin esto no se distingue "configurada"
    # de "viviendo del default", que es justo lo que se quiere ver acá.
    llm_provider: str | None
    llm_model: str | None
    llm_api_key_masked: str | None
    uses_own_key: bool


class AdminOrgAIIn(BaseModel):
    llm_provider: str | None = None
    llm_model: str | None = Field(default=None, max_length=120)
    # None = no tocar, "" = borrar la key y volver al default del servidor.
    llm_api_key: str | None = Field(default=None, max_length=500)
    llm_base_url: str | None = Field(default=None, max_length=300)


@router.get("/organizations", response_model=list[AdminOrgOut])
async def list_organizations(
    _: User = Depends(get_superadmin), db: AsyncSession = Depends(get_db)
):
    orgs = (
        (
            await db.execute(
                select(Organization)
                .where(Organization.deleted_at.is_(None))
                .order_by(Organization.created_at)
            )
        )
        .scalars()
        .all()
    )

    # Conteos en dos consultas agregadas y no una por organización.
    member_counts = dict(
        (
            await db.execute(
                select(OrganizationMember.organization_id, func.count())
                .group_by(OrganizationMember.organization_id)
            )
        ).all()
    )
    meeting_counts = dict(
        (
            await db.execute(
                select(Meeting.organization_id, func.count())
                .where(Meeting.deleted_at.is_(None))
                .group_by(Meeting.organization_id)
            )
        ).all()
    )
    settings_rows = {
        row.organization_id: row
        for row in (await db.execute(select(OrgAISettings))).scalars().all()
    }

    out: list[AdminOrgOut] = []
    for org in orgs:
        row = settings_rows.get(org.id)
        own_key = bool(row and row.llm_api_key_enc)
        resolved = await resolve_llm(db, org.id)
        out.append(
            AdminOrgOut(
                id=org.id,
                name=org.name,
                slug=org.slug,
                members=member_counts.get(org.id, 0),
                meetings=meeting_counts.get(org.id, 0),
                llm_provider=resolved.provider if resolved else None,
                llm_model=resolved.model if resolved else None,
                llm_api_key_masked=(
                    mask_secret(decrypt_secret(row.llm_api_key_enc) or "") if own_key else None
                ),
                uses_own_key=own_key,
            )
        )
    return out


@router.put("/organizations/{org_id}/ai", response_model=AdminOrgOut)
async def set_organization_ai(
    org_id: uuid.UUID,
    data: AdminOrgAIIn,
    admin: User = Depends(get_superadmin),
    db: AsyncSession = Depends(get_db),
):
    org = await db.get(Organization, org_id)
    if not org or org.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organización no encontrada")

    if data.llm_provider is not None and data.llm_provider not in LLM_PROVIDERS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Proveedor de IA desconocido")

    row = (
        await db.execute(select(OrgAISettings).where(OrgAISettings.organization_id == org_id))
    ).scalar_one_or_none()
    if row is None:
        row = OrgAISettings(organization_id=org_id)
        db.add(row)
        await db.flush()

    if data.llm_provider is not None:
        row.llm_provider = data.llm_provider or None
    if data.llm_model is not None:
        row.llm_model = data.llm_model or None
    if data.llm_base_url is not None:
        row.llm_base_url = data.llm_base_url or None
    if data.llm_api_key is not None:
        row.llm_api_key_enc = encrypt_secret(data.llm_api_key) if data.llm_api_key else None

    # Queda en el audit log de la organización afectada, con el nombre de quien
    # lo hizo: es una acción sobre datos de otro, tiene que ser rastreable.
    await audit(
        db,
        org_id,
        admin.id,
        "admin.org_ai_update",
        "organization",
        str(org_id),
        detail={"by": admin.email, "provider": row.llm_provider},
    )
    await db.commit()

    resolved = await resolve_llm(db, org_id)
    plain = decrypt_secret(row.llm_api_key_enc) if row.llm_api_key_enc else None
    members = (
        await db.execute(
            select(func.count()).select_from(OrganizationMember).where(
                OrganizationMember.organization_id == org_id
            )
        )
    ).scalar_one()
    meetings = (
        await db.execute(
            select(func.count()).select_from(Meeting).where(
                Meeting.organization_id == org_id, Meeting.deleted_at.is_(None)
            )
        )
    ).scalar_one()
    return AdminOrgOut(
        id=org.id,
        name=org.name,
        slug=org.slug,
        members=members,
        meetings=meetings,
        llm_provider=resolved.provider if resolved else None,
        llm_model=resolved.model if resolved else None,
        llm_api_key_masked=mask_secret(plain) if plain else None,
        uses_own_key=bool(row.llm_api_key_enc),
    )
