"""Familias, sus integrantes, los motivos de reunión y la clasificación.

Clasificar una reunión es decir con qué familia fue, por qué motivo, con qué
gravedad y quién de la familia vino. Va todo junto en un solo PUT porque en la
práctica se completa de una sola sentada, al terminar la reunión.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..deps import OrgContext, can_edit_meeting, get_meeting_or_404, get_org_context
from ..models import (
    AUDIENCES,
    RELATIONSHIPS,
    SEVERITIES,
    Family,
    FamilyMember,
    FamilyProfessional,
    Meeting,
    MeetingAttendance,
    MeetingProfessionalAttendance,
    MeetingReason,
    Professional,
)
from ..services.audit import audit

router = APIRouter(tags=["families"])


# ── Salidas ──────────────────────────────────────────────────────


class FamilyMemberOut(BaseModel):
    id: uuid.UUID
    name: str
    relationship_type: str
    is_guardian: bool
    email: str | None
    phone: str | None

    class Config:
        from_attributes = True


class ProfessionalOut(BaseModel):
    id: uuid.UUID
    name: str
    role_label: str | None
    affiliation: str | None
    email: str | None
    phone: str | None
    is_active: bool

    class Config:
        from_attributes = True


class FamilyOut(BaseModel):
    id: uuid.UUID
    name: str
    reference: str | None
    notes: str | None
    drive_url: str | None = None
    members: list[FamilyMemberOut] = []
    professionals: list[ProfessionalOut] = []
    meetings: int = 0


class ReasonOut(BaseModel):
    id: uuid.UUID
    name: str
    is_active: bool
    position: int

    class Config:
        from_attributes = True


# ── Entradas ─────────────────────────────────────────────────────


class FamilyIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    reference: str | None = Field(default=None, max_length=80)
    notes: str | None = None
    # Carpeta de Drive de la familia. Echo solo guarda el enlace.
    drive_url: str | None = Field(default=None, max_length=600)


class ProfessionalIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    role_label: str | None = Field(default=None, max_length=120)
    affiliation: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=40)
    notes: str | None = None
    is_active: bool = True


class FamilyMemberIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    relationship_type: str = "tutor"
    is_guardian: bool = True
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=40)


class ReasonIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    is_active: bool = True
    position: int = 0


class ClassificationIn(BaseModel):
    family_id: uuid.UUID | None = None
    reason_id: uuid.UUID | None = None
    severity: str | None = None
    # Con quién fue: familia|profesionales|mixta|docentes|interna
    audience: str | None = None
    # Ids de los profesionales que asistieron.
    attended_professional_ids: list[uuid.UUID] | None = None
    # Ids de los integrantes que asistieron. Mandar la lista completa: lo que
    # no viene se marca como ausente.
    attended_member_ids: list[uuid.UUID] | None = None


class ClassificationOut(BaseModel):
    family_id: uuid.UUID | None
    family_name: str | None
    family_drive_url: str | None = None
    reason_id: uuid.UUID | None
    reason_name: str | None
    severity: str | None
    audience: str | None
    attendance: list[dict]
    all_guardians_present: bool | None
    professionals: list[dict] = []


# ── Familias ─────────────────────────────────────────────────────


async def _get_family(family_id: uuid.UUID, ctx: OrgContext, db: AsyncSession) -> Family:
    family = await db.get(Family, family_id)
    if not family or family.organization_id != ctx.org_id or family.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Familia no encontrada")
    return family


@router.get("/api/families", response_model=list[FamilyOut])
async def list_families(
    ctx: OrgContext = Depends(get_org_context), db: AsyncSession = Depends(get_db)
):
    families = (
        (
            await db.execute(
                select(Family)
                .where(Family.organization_id == ctx.org_id, Family.deleted_at.is_(None))
                .order_by(Family.name)
            )
        )
        .scalars()
        .all()
    )
    if not families:
        return []

    ids = [f.id for f in families]
    members = (
        (
            await db.execute(
                select(FamilyMember)
                .where(FamilyMember.family_id.in_(ids))
                .order_by(FamilyMember.name)
            )
        )
        .scalars()
        .all()
    )
    by_family: dict[uuid.UUID, list[FamilyMember]] = {}
    for member in members:
        by_family.setdefault(member.family_id, []).append(member)

    counts = dict(
        (
            await db.execute(
                select(Meeting.family_id, func.count())
                .where(Meeting.family_id.in_(ids), Meeting.deleted_at.is_(None))
                .group_by(Meeting.family_id)
            )
        ).all()
    )

    pros_by_family: dict[uuid.UUID, list[Professional]] = {}
    for family_id, professional in (
        await db.execute(
            select(FamilyProfessional.family_id, Professional)
            .join(Professional, Professional.id == FamilyProfessional.professional_id)
            .where(FamilyProfessional.family_id.in_(ids), Professional.deleted_at.is_(None))
            .order_by(Professional.name)
        )
    ).all():
        pros_by_family.setdefault(family_id, []).append(professional)

    return [
        FamilyOut(
            id=f.id,
            name=f.name,
            reference=f.reference,
            notes=f.notes,
            drive_url=f.drive_url,
            members=[FamilyMemberOut.model_validate(m) for m in by_family.get(f.id, [])],
            professionals=[
                ProfessionalOut.model_validate(pro) for pro in pros_by_family.get(f.id, [])
            ],
            meetings=counts.get(f.id, 0),
        )
        for f in families
    ]


@router.post("/api/families", response_model=FamilyOut, status_code=201)
async def create_family(
    data: FamilyIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    ctx.require_role("member")
    family = Family(
        organization_id=ctx.org_id,
        name=data.name.strip(),
        reference=(data.reference or "").strip() or None,
        notes=data.notes,
        drive_url=(data.drive_url or "").strip() or None,
    )
    db.add(family)
    await db.flush()
    await audit(db, ctx.org_id, ctx.user.id, "family.create", "family", str(family.id))
    await db.commit()
    return FamilyOut(
        id=family.id,
        name=family.name,
        reference=family.reference,
        notes=family.notes,
        drive_url=family.drive_url,
    )


@router.patch("/api/families/{family_id}", response_model=FamilyOut)
async def update_family(
    family_id: uuid.UUID,
    data: FamilyIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    ctx.require_role("member")
    family = await _get_family(family_id, ctx, db)
    family.name = data.name.strip()
    family.reference = (data.reference or "").strip() or None
    family.notes = data.notes
    family.drive_url = (data.drive_url or "").strip() or None
    await db.commit()
    members = (
        (await db.execute(select(FamilyMember).where(FamilyMember.family_id == family.id)))
        .scalars()
        .all()
    )
    return FamilyOut(
        id=family.id,
        name=family.name,
        reference=family.reference,
        notes=family.notes,
        drive_url=family.drive_url,
        members=[FamilyMemberOut.model_validate(m) for m in members],
    )


@router.delete("/api/families/{family_id}", status_code=204)
async def delete_family(
    family_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    from datetime import UTC, datetime

    ctx.require_role("admin")
    family = await _get_family(family_id, ctx, db)
    # Baja lógica: las reuniones ya hechas siguen apuntando acá y el histórico
    # de reportes no se puede quedar sin el nombre de la familia.
    family.deleted_at = datetime.now(UTC)
    await audit(db, ctx.org_id, ctx.user.id, "family.delete", "family", str(family.id))
    await db.commit()


@router.post("/api/families/{family_id}/members", response_model=FamilyMemberOut, status_code=201)
async def add_member(
    family_id: uuid.UUID,
    data: FamilyMemberIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    ctx.require_role("member")
    family = await _get_family(family_id, ctx, db)
    if data.relationship_type not in RELATIONSHIPS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Vínculo desconocido")
    member = FamilyMember(
        family_id=family.id,
        name=data.name.strip(),
        relationship_type=data.relationship_type,
        is_guardian=data.is_guardian,
        email=(data.email or "").strip() or None,
        phone=(data.phone or "").strip() or None,
    )
    db.add(member)
    await db.flush()
    await db.commit()
    return FamilyMemberOut.model_validate(member)


@router.patch("/api/families/members/{member_id}", response_model=FamilyMemberOut)
async def update_member(
    member_id: uuid.UUID,
    data: FamilyMemberIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    ctx.require_role("member")
    member = await db.get(FamilyMember, member_id)
    if not member:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Integrante no encontrado")
    await _get_family(member.family_id, ctx, db)  # valida que sea de esta organización
    if data.relationship_type not in RELATIONSHIPS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Vínculo desconocido")
    member.name = data.name.strip()
    member.relationship_type = data.relationship_type
    member.is_guardian = data.is_guardian
    member.email = (data.email or "").strip() or None
    member.phone = (data.phone or "").strip() or None
    await db.commit()
    return FamilyMemberOut.model_validate(member)


@router.delete("/api/families/members/{member_id}", status_code=204)
async def delete_member(
    member_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    ctx.require_role("member")
    member = await db.get(FamilyMember, member_id)
    if not member:
        return
    await _get_family(member.family_id, ctx, db)
    await db.delete(member)
    await db.commit()


# ── Profesionales ────────────────────────────────────────────────


async def _get_professional(
    professional_id: uuid.UUID, ctx: OrgContext, db: AsyncSession
) -> Professional:
    pro = await db.get(Professional, professional_id)
    if not pro or pro.organization_id != ctx.org_id or pro.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Profesional no encontrado")
    return pro


@router.get("/api/professionals", response_model=list[ProfessionalOut])
async def list_professionals(
    include_inactive: bool = False,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    query = select(Professional).where(
        Professional.organization_id == ctx.org_id, Professional.deleted_at.is_(None)
    )
    if not include_inactive:
        query = query.where(Professional.is_active.is_(True))
    rows = (await db.execute(query.order_by(Professional.name))).scalars().all()
    return [ProfessionalOut.model_validate(row) for row in rows]


@router.post("/api/professionals", response_model=ProfessionalOut, status_code=201)
async def create_professional(
    data: ProfessionalIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    ctx.require_role("member")
    pro = Professional(
        organization_id=ctx.org_id,
        name=data.name.strip(),
        role_label=(data.role_label or "").strip() or None,
        affiliation=(data.affiliation or "").strip() or None,
        email=(data.email or "").strip() or None,
        phone=(data.phone or "").strip() or None,
        notes=data.notes,
        is_active=data.is_active,
    )
    db.add(pro)
    await db.flush()
    await audit(db, ctx.org_id, ctx.user.id, "professional.create", "professional", str(pro.id))
    await db.commit()
    return ProfessionalOut.model_validate(pro)


@router.patch("/api/professionals/{professional_id}", response_model=ProfessionalOut)
async def update_professional(
    professional_id: uuid.UUID,
    data: ProfessionalIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    ctx.require_role("member")
    pro = await _get_professional(professional_id, ctx, db)
    pro.name = data.name.strip()
    pro.role_label = (data.role_label or "").strip() or None
    pro.affiliation = (data.affiliation or "").strip() or None
    pro.email = (data.email or "").strip() or None
    pro.phone = (data.phone or "").strip() or None
    pro.notes = data.notes
    pro.is_active = data.is_active
    await db.commit()
    return ProfessionalOut.model_validate(pro)


@router.delete("/api/professionals/{professional_id}", status_code=204)
async def delete_professional(
    professional_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    from datetime import UTC, datetime

    ctx.require_role("admin")
    pro = await _get_professional(professional_id, ctx, db)
    # Baja lógica: las reuniones donde estuvo tienen que seguir mostrando su
    # nombre.
    pro.deleted_at = datetime.now(UTC)
    await db.commit()


@router.put("/api/families/{family_id}/professionals/{professional_id}", status_code=204)
async def link_professional(
    family_id: uuid.UUID,
    professional_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    ctx.require_role("member")
    await _get_family(family_id, ctx, db)
    await _get_professional(professional_id, ctx, db)
    existing = (
        await db.execute(
            select(FamilyProfessional).where(
                FamilyProfessional.family_id == family_id,
                FamilyProfessional.professional_id == professional_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(FamilyProfessional(family_id=family_id, professional_id=professional_id))
        await db.commit()


@router.delete("/api/families/{family_id}/professionals/{professional_id}", status_code=204)
async def unlink_professional(
    family_id: uuid.UUID,
    professional_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    ctx.require_role("member")
    await _get_family(family_id, ctx, db)
    row = (
        await db.execute(
            select(FamilyProfessional).where(
                FamilyProfessional.family_id == family_id,
                FamilyProfessional.professional_id == professional_id,
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        await db.delete(row)
        await db.commit()


# ── Motivos ──────────────────────────────────────────────────────


@router.get("/api/org/meeting-reasons", response_model=list[ReasonOut])
async def list_reasons(
    include_inactive: bool = False,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    query = select(MeetingReason).where(MeetingReason.organization_id == ctx.org_id)
    if not include_inactive:
        query = query.where(MeetingReason.is_active.is_(True))
    rows = (
        (await db.execute(query.order_by(MeetingReason.position, MeetingReason.name)))
        .scalars()
        .all()
    )
    return [ReasonOut.model_validate(r) for r in rows]


@router.post("/api/org/meeting-reasons", response_model=ReasonOut, status_code=201)
async def create_reason(
    data: ReasonIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    ctx.require_role("admin")
    reason = MeetingReason(
        organization_id=ctx.org_id,
        name=data.name.strip(),
        is_active=data.is_active,
        position=data.position,
    )
    db.add(reason)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe un motivo con ese nombre") from None
    await db.refresh(reason)
    return ReasonOut.model_validate(reason)


@router.patch("/api/org/meeting-reasons/{reason_id}", response_model=ReasonOut)
async def update_reason(
    reason_id: uuid.UUID,
    data: ReasonIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    ctx.require_role("admin")
    reason = await db.get(MeetingReason, reason_id)
    if not reason or reason.organization_id != ctx.org_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Motivo no encontrado")
    reason.name = data.name.strip()
    reason.is_active = data.is_active
    reason.position = data.position
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe un motivo con ese nombre") from None
    return ReasonOut.model_validate(reason)


# ── Clasificación de una reunión ─────────────────────────────────


async def _classification_out(meeting: Meeting, db: AsyncSession) -> ClassificationOut:
    family_name = None
    family_drive_url = None
    attendance: list[dict] = []
    all_present: bool | None = None

    if meeting.family_id:
        family = await db.get(Family, meeting.family_id)
        family_name = family.name if family else None
        family_drive_url = family.drive_url if family else None

        members = (
            (
                await db.execute(
                    select(FamilyMember)
                    .where(FamilyMember.family_id == meeting.family_id)
                    .order_by(FamilyMember.name)
                )
            )
            .scalars()
            .all()
        )
        rows = {
            row.family_member_id: row.attended
            for row in (
                await db.execute(
                    select(MeetingAttendance).where(MeetingAttendance.meeting_id == meeting.id)
                )
            )
            .scalars()
            .all()
        }
        attendance = [
            {
                "member_id": str(m.id),
                "name": m.name,
                "relationship_type": m.relationship_type,
                "is_guardian": m.is_guardian,
                "attended": rows.get(m.id, False),
                "recorded": m.id in rows,
            }
            for m in members
        ]
        guardians = [m for m in members if m.is_guardian]
        # Sin ningún registro de asistencia la respuesta correcta es "no se
        # sabe", no "no vinieron": son cosas distintas en un reporte.
        if guardians and any(m.id in rows for m in guardians):
            all_present = all(rows.get(m.id, False) for m in guardians)

    reason_name = None
    if meeting.reason_id:
        reason = await db.get(MeetingReason, meeting.reason_id)
        reason_name = reason.name if reason else None

    # Profesionales: los de la familia, más cualquiera que se haya marcado
    # como presente aunque no esté vinculado (una interconsulta puntual).
    pro_rows = {
        row.professional_id: row.attended
        for row in (
            await db.execute(
                select(MeetingProfessionalAttendance).where(
                    MeetingProfessionalAttendance.meeting_id == meeting.id
                )
            )
        )
        .scalars()
        .all()
    }
    linked_ids: set[uuid.UUID] = set()
    if meeting.family_id:
        linked_ids = {
            row
            for row in (
                await db.execute(
                    select(FamilyProfessional.professional_id).where(
                        FamilyProfessional.family_id == meeting.family_id
                    )
                )
            )
            .scalars()
            .all()
        }
    wanted = linked_ids | set(pro_rows)
    professionals: list[dict] = []
    if wanted:
        for pro in (
            (
                await db.execute(
                    select(Professional)
                    .where(Professional.id.in_(wanted), Professional.deleted_at.is_(None))
                    .order_by(Professional.name)
                )
            )
            .scalars()
            .all()
        ):
            professionals.append(
                {
                    "professional_id": str(pro.id),
                    "name": pro.name,
                    "role_label": pro.role_label,
                    "attended": pro_rows.get(pro.id, False),
                    "linked": pro.id in linked_ids,
                }
            )

    return ClassificationOut(
        family_id=meeting.family_id,
        family_name=family_name,
        family_drive_url=family_drive_url,
        reason_id=meeting.reason_id,
        reason_name=reason_name,
        severity=meeting.severity,
        audience=meeting.audience,
        attendance=attendance,
        all_guardians_present=all_present,
        professionals=professionals,
    )


@router.get("/api/meetings/{meeting_id}/classification", response_model=ClassificationOut)
async def get_classification(
    meeting_id: uuid.UUID,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db)
    return await _classification_out(meeting, db)


@router.put("/api/meetings/{meeting_id}/classification", response_model=ClassificationOut)
async def set_classification(
    meeting_id: uuid.UUID,
    data: ClassificationIn,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    meeting = await get_meeting_or_404(meeting_id, ctx, db, minimum_role="editor")
    if not can_edit_meeting(ctx, meeting):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Sin permiso de edición")

    if data.severity is not None and data.severity != "" and data.severity not in SEVERITIES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Gravedad desconocida")
    if data.audience is not None and data.audience != "" and data.audience not in AUDIENCES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Tipo de reunión desconocido")

    if data.family_id is not None:
        await _get_family(data.family_id, ctx, db)
    if data.reason_id is not None:
        reason = await db.get(MeetingReason, data.reason_id)
        if not reason or reason.organization_id != ctx.org_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Motivo no encontrado")

    family_changed = data.family_id != meeting.family_id
    meeting.family_id = data.family_id
    meeting.reason_id = data.reason_id
    meeting.severity = data.severity or None
    meeting.audience = data.audience or None

    existing = {
        row.family_member_id: row
        for row in (
            await db.execute(
                select(MeetingAttendance).where(MeetingAttendance.meeting_id == meeting.id)
            )
        )
        .scalars()
        .all()
    }

    if family_changed:
        # La asistencia pertenece a la familia anterior; dejarla sería mezclar
        # integrantes de dos familias en la misma reunión.
        for row in existing.values():
            await db.delete(row)
        existing = {}

    if data.attended_member_ids is not None and meeting.family_id:
        members = (
            (
                await db.execute(
                    select(FamilyMember).where(FamilyMember.family_id == meeting.family_id)
                )
            )
            .scalars()
            .all()
        )
        attended = set(data.attended_member_ids)
        for member in members:
            row = existing.get(member.id)
            if row is None:
                db.add(
                    MeetingAttendance(
                        meeting_id=meeting.id,
                        family_member_id=member.id,
                        attended=member.id in attended,
                    )
                )
            else:
                row.attended = member.id in attended

    if data.attended_professional_ids is not None:
        current = {
            row.professional_id: row
            for row in (
                await db.execute(
                    select(MeetingProfessionalAttendance).where(
                        MeetingProfessionalAttendance.meeting_id == meeting.id
                    )
                )
            )
            .scalars()
            .all()
        }
        wanted = set(data.attended_professional_ids)
        for professional_id in wanted:
            pro = await db.get(Professional, professional_id)
            if not pro or pro.organization_id != ctx.org_id:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Profesional no encontrado")
            row = current.get(professional_id)
            if row is None:
                db.add(
                    MeetingProfessionalAttendance(
                        meeting_id=meeting.id, professional_id=professional_id, attended=True
                    )
                )
            else:
                row.attended = True
        # A diferencia de la familia, acá se borra en vez de marcar ausente:
        # un profesional que no vino simplemente no participó de esta reunión,
        # no es una ausencia que haya que contar.
        for professional_id, row in current.items():
            if professional_id not in wanted:
                await db.delete(row)

    await audit(db, ctx.org_id, ctx.user.id, "meeting.classify", "meeting", str(meeting.id))
    await db.commit()
    await db.refresh(meeting)
    return await _classification_out(meeting, db)
