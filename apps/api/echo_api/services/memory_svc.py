"""Memoria organizacional: entidades y relaciones entre reuniones.

Después de cada reunión se actualiza un grafo liviano:
  MemoryEntity (project|person|topic) ← MemoryRelation → hechos con evidencia.

El chat global usa este grafo ADEMÁS del RAG por embeddings, para responder
"¿qué pasó con la fecha de DOE?" citando ambas reuniones.
"""
import logging
import re
import unicodedata
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from ..db import SessionLocal
from ..models import (
    ActionItem,
    Decision,
    Meeting,
    MeetingLink,
    MemoryEntity,
    MemoryRelation,
)
from .ai_settings import EmbeddingsConfig
from .embeddings import embed_texts

log = logging.getLogger("echo.memory")


def normalize_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text.strip().lower())


async def _get_or_create_entity(
    db, org_id: uuid.UUID, kind: str, name: str, embeddings_config: EmbeddingsConfig | None
) -> MemoryEntity | None:
    name = name.strip()
    if not name or len(name) > 290:
        return None
    normalized = normalize_name(name)
    if not normalized:
        return None
    entity = (
        await db.execute(
            select(MemoryEntity).where(
                MemoryEntity.organization_id == org_id,
                MemoryEntity.kind == kind,
                MemoryEntity.normalized_name == normalized,
            )
        )
    ).scalar_one_or_none()
    if entity:
        return entity
    entity = MemoryEntity(
        organization_id=org_id, kind=kind, name=name, normalized_name=normalized
    )
    if embeddings_config:
        try:
            vectors = await embed_texts(embeddings_config, [f"{kind}: {name}"])
            entity.embedding = vectors[0]
        except Exception:
            pass
    db.add(entity)
    await db.flush()
    return entity


async def update_memory_from_meeting(
    meeting_id: uuid.UUID, insights: dict, embeddings_config: EmbeddingsConfig | None
) -> None:
    async with SessionLocal() as db:
        meeting = await db.get(Meeting, meeting_id)
        if not meeting:
            return
        org_id = meeting.organization_id
        happened_at = meeting.started_at or meeting.created_at
        mentions = insights.get("mentions") or {}

        # entidades mencionadas
        entity_cache: dict[tuple[str, str], MemoryEntity] = {}

        async def entity(kind: str, name: str) -> MemoryEntity | None:
            key = (kind, normalize_name(name))
            if key in entity_cache:
                return entity_cache[key]
            row = await _get_or_create_entity(db, org_id, kind, name, embeddings_config)
            if row:
                entity_cache[key] = row
            return row

        for project_name in mentions.get("projects") or []:
            project_entity = await entity("project", str(project_name))
            if project_entity:
                db.add(
                    MemoryRelation(
                        organization_id=org_id,
                        entity_id=project_entity.id,
                        meeting_id=meeting_id,
                        relation="mentioned",
                        happened_at=happened_at,
                    )
                )

        for person_name in mentions.get("people") or []:
            person_entity = await entity("person", str(person_name))
            if person_entity:
                db.add(
                    MemoryRelation(
                        organization_id=org_id,
                        entity_id=person_entity.id,
                        meeting_id=meeting_id,
                        relation="mentioned",
                        happened_at=happened_at,
                    )
                )

        # decisiones → relación "decided" ligada a proyecto si el texto lo menciona
        decisions = (
            (await db.execute(select(Decision).where(Decision.meeting_id == meeting_id)))
            .scalars()
            .all()
        )
        project_entities = [e for (k, _), e in entity_cache.items() if k == "project"]
        for decision in decisions:
            targets = [e for e in project_entities if e.normalized_name in normalize_name(decision.text)]
            if not targets:
                # entidad "topic" derivada de la primera palabra clave de la decisión
                targets = [t for t in [await entity("topic", _topic_from_text(decision.text))] if t]
            for target in targets:
                db.add(
                    MemoryRelation(
                        organization_id=org_id,
                        entity_id=target.id,
                        meeting_id=meeting_id,
                        relation="decided",
                        ref_type="decision",
                        ref_id=decision.id,
                        fact=decision.text,
                        happened_at=happened_at,
                        evidence_start_ms=decision.evidence_start_ms,
                        evidence_end_ms=decision.evidence_end_ms,
                    )
                )

        # tareas → relación "assigned" a la persona responsable
        tasks = (
            (await db.execute(select(ActionItem).where(ActionItem.meeting_id == meeting_id)))
            .scalars()
            .all()
        )
        for task in tasks:
            if task.assignee_name:
                person_entity = await entity("person", task.assignee_name)
                if person_entity:
                    db.add(
                        MemoryRelation(
                            organization_id=org_id,
                            entity_id=person_entity.id,
                            meeting_id=meeting_id,
                            relation="assigned",
                            ref_type="action_item",
                            ref_id=task.id,
                            fact=task.text,
                            happened_at=happened_at,
                            evidence_start_ms=task.evidence_start_ms,
                            evidence_end_ms=task.evidence_end_ms,
                        )
                    )

        await db.commit()

        # ── Sugerir reuniones relacionadas ───────────────────────
        await _suggest_related_meetings(db, org_id, meeting_id, project_entities)


async def _suggest_related_meetings(db, org_id, meeting_id, project_entities) -> None:
    """Si otra reunión tocó los mismos proyectos, sugerir el vínculo."""
    for project_entity in project_entities:
        rows = (
            (
                await db.execute(
                    select(MemoryRelation.meeting_id)
                    .where(
                        MemoryRelation.organization_id == org_id,
                        MemoryRelation.entity_id == project_entity.id,
                        MemoryRelation.meeting_id.isnot(None),
                        MemoryRelation.meeting_id != meeting_id,
                    )
                    .distinct()
                    .limit(3)
                )
            )
            .scalars()
            .all()
        )
        for other_id in rows:
            existing = (
                await db.execute(
                    select(MeetingLink).where(
                        MeetingLink.meeting_id == meeting_id,
                        MeetingLink.related_meeting_id == other_id,
                    )
                )
            ).scalar_one_or_none()
            if not existing:
                db.add(
                    MeetingLink(
                        meeting_id=meeting_id,
                        related_meeting_id=other_id,
                        kind="related",
                        confirmed=False,
                        suggested_reason=f"Ambas reuniones mencionan «{project_entity.name}»",
                    )
                )
    await db.commit()


def _topic_from_text(text: str) -> str:
    words = [w for w in re.findall(r"[A-Za-zÁÉÍÓÚáéíóúñÑ0-9]+", text) if len(w) > 3]
    return " ".join(words[:4]) or text[:40]


async def query_memory_entities(
    db, org_id: uuid.UUID, question: str, limit: int = 6
) -> list[dict]:
    """Busca entidades relevantes por coincidencia de nombre en la pregunta."""
    normalized_question = normalize_name(question)
    rows = (
        (
            await db.execute(
                select(MemoryEntity).where(
                    MemoryEntity.organization_id == org_id, MemoryEntity.deleted_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    matched = [e for e in rows if e.normalized_name and e.normalized_name in normalized_question]
    results = []
    for entity in matched[:limit]:
        relations = (
            (
                await db.execute(
                    select(MemoryRelation, Meeting)
                    .outerjoin(Meeting, Meeting.id == MemoryRelation.meeting_id)
                    .where(MemoryRelation.entity_id == entity.id)
                    .order_by(MemoryRelation.happened_at.asc().nullslast())
                    .limit(30)
                )
            )
        ).all()
        facts = []
        for relation, meeting in relations:
            facts.append(
                {
                    "relation": relation.relation,
                    "fact": relation.fact,
                    "meeting_id": str(relation.meeting_id) if relation.meeting_id else None,
                    "meeting_title": meeting.title if meeting else None,
                    "date": relation.happened_at.strftime("%d/%m/%Y") if relation.happened_at else None,
                    "evidence_start_ms": relation.evidence_start_ms,
                }
            )
        results.append(
            {"kind": entity.kind, "name": entity.name, "summary": entity.summary, "facts": facts}
        )
    return results
