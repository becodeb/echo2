"""Generación y verificación de actas.

Flujo: template (source of truth) + transcript + insights → LLM genera el acta
→ ActaVerifier contrasta cada afirmación contra el transcript y anota el
resultado. La regla crítica es NO INVENTAR: los campos sin información llevan
"No especificado durante la reunión".

El template default es PROVISIONAL y está marcado como tal: cuando el usuario
cargue su modelo real de acta (Ajustes → Formato de acta), ese pasa a mandar.
"""
import json
import logging
import uuid

from sqlalchemy import select

from ..db import SessionLocal
from ..models import (
    ActionItem,
    Decision,
    Meeting,
    MeetingParticipant,
    MeetingTopic,
    Minutes,
    MinutesTemplate,
    MinutesVersion,
    Question,
)
from .llm import LLMError, LLMProvider
from .transcript_util import format_ms, load_transcript_lines, transcript_to_text

log = logging.getLogger("echo.minutes")

DEFAULT_TEMPLATE_NAME = "Acta estándar (provisional)"

DEFAULT_TEMPLATE = """# ACTA DE REUNIÓN

> Plantilla provisional de Echo. Reemplazala en Ajustes → Formato de acta
> con el modelo real de tu organización.

## Datos de la reunión
- **Título:** {{titulo}}
- **Fecha:** {{fecha}}
- **Duración:** {{duracion}}
- **Participantes:** {{participantes}}

## Orden del día / Temas tratados
{{temas}}

## Desarrollo
{{desarrollo}}

## Decisiones adoptadas
{{decisiones}}

## Compromisos y tareas
| Tarea | Responsable | Fecha límite |
|-------|-------------|--------------|
{{tareas}}

## Temas pendientes
{{pendientes}}

## Próxima reunión
{{proxima_reunion}}

---
_Acta generada por Echo el {{fecha_generacion}}._
"""

GENERATOR_SYSTEM = """Sos el generador de actas de Echo. Tu trabajo es completar el MODELO
de acta de la organización usando EXCLUSIVAMENTE la información del transcript
y los datos estructurados provistos.

REGLAS CRÍTICAS:
1. NO INVENTES INFORMACIÓN. Nunca. Bajo ninguna circunstancia.
2. Si un campo del modelo no tiene información en el transcript, escribí
   exactamente: "No especificado durante la reunión".
3. Respetá la estructura, títulos, orden y estilo del modelo AL PIE DE LA LETRA.
4. Todo lo que afirmes debe poder rastrearse al transcript.
5. Junto al acta, devolvé la lista de afirmaciones verificables (claims) con el
   timestamp aproximado de donde salen.
6. Escribí el acta en {language}."""


VERIFIER_SYSTEM = """Sos el verificador de actas de Echo. Recibís una afirmación de un
acta y fragmentos del transcript. Determiná si el transcript RESPALDA la
afirmación.

Respondé JSON: {"status": "verified"|"weak"|"missing", "evidence_ms": <int o null>, "note": "breve"}
- verified: el transcript la respalda claramente.
- weak: hay algo relacionado pero no es concluyente.
- missing: no hay evidencia en el transcript."""


async def get_active_template(db, org_id: uuid.UUID) -> MinutesTemplate:
    template = (
        await db.execute(
            select(MinutesTemplate)
            .where(MinutesTemplate.organization_id == org_id, MinutesTemplate.is_default.is_(True))
            .order_by(MinutesTemplate.created_at.desc())
        )
    ).scalars().first()
    if template:
        return template
    template = MinutesTemplate(
        organization_id=org_id,
        name=DEFAULT_TEMPLATE_NAME,
        body_markdown=DEFAULT_TEMPLATE,
        is_default=True,
        is_provisional=True,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return template


async def generate_minutes(meeting_id: uuid.UUID, provider: LLMProvider) -> None:
    async with SessionLocal() as db:
        meeting = await db.get(Meeting, meeting_id)
        if not meeting:
            return
        org_id = meeting.organization_id
        template = await get_active_template(db, org_id)
        lines = await load_transcript_lines(db, meeting_id)
        participants = (
            (
                await db.execute(
                    select(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting_id)
                )
            )
            .scalars()
            .all()
        )
        decisions = (
            (await db.execute(select(Decision).where(Decision.meeting_id == meeting_id)))
            .scalars()
            .all()
        )
        tasks = (
            (await db.execute(select(ActionItem).where(ActionItem.meeting_id == meeting_id)))
            .scalars()
            .all()
        )
        questions = (
            (await db.execute(select(Question).where(Question.meeting_id == meeting_id)))
            .scalars()
            .all()
        )
        topics = (
            (await db.execute(select(MeetingTopic).where(MeetingTopic.meeting_id == meeting_id)))
            .scalars()
            .all()
        )
        from .ai_settings import get_org_ai_settings

        ai_settings = await get_org_ai_settings(db, org_id)
        language = ai_settings.minutes_language if ai_settings else meeting.language

    transcript_text = transcript_to_text(lines)
    if len(transcript_text) > 28000:
        transcript_text = transcript_text[:28000] + "\n[transcript truncado para el prompt; los datos estructurados cubren el resto]"

    duration_min = meeting.duration_seconds // 60
    structured = {
        "titulo": meeting.title,
        "fecha": (meeting.started_at or meeting.created_at).strftime("%d/%m/%Y"),
        "duracion": f"{duration_min} minutos",
        "participantes": [p.name for p in participants] or "No especificado durante la reunión",
        "temas": [{"titulo": t.title, "resumen": t.summary} for t in topics],
        "decisiones": [
            {"texto": d.text, "contexto": d.context, "evidencia_ms": d.evidence_start_ms}
            for d in decisions
        ],
        "tareas": [
            {
                "texto": t.text,
                "responsable": t.assignee_name,
                "fecha": t.due_text,
                "fecha_resuelta": t.due_date.isoformat() if t.due_date else None,
                "evidencia_ms": t.evidence_start_ms,
            }
            for t in tasks
        ],
        "pendientes": [q.text for q in questions if not q.resolved],
    }

    prompt = f"""MODELO DE ACTA (respetalo al pie de la letra):

{template.body_markdown}

DATOS ESTRUCTURADOS DE LA REUNIÓN:
{json.dumps(structured, ensure_ascii=False, indent=1)}

TRANSCRIPT (con timestamps [MM:SS] y hablantes):

{transcript_text}

Devolvé JSON:
{{
  "markdown": "el acta completa en markdown siguiendo el modelo",
  "claims": [{{"text": "afirmación verificable del acta", "approx_ms": <int|null>}}]
}}"""

    result = await provider.chat_json(
        GENERATOR_SYSTEM.format(language=language),
        [{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=8000,
    )
    if not isinstance(result, dict) or not result.get("markdown"):
        raise LLMError("El generador de actas no devolvió contenido")

    markdown = str(result["markdown"])
    claims = [c for c in (result.get("claims") or []) if isinstance(c, dict) and c.get("text")]

    # ── Verificación contra el transcript ────────────────────────
    verification = await _verify_claims(provider, claims, lines)

    async with SessionLocal() as db:
        minutes = (
            await db.execute(select(Minutes).where(Minutes.meeting_id == meeting_id))
        ).scalar_one_or_none()
        if not minutes:
            minutes = Minutes(
                meeting_id=meeting_id,
                organization_id=org_id,
                template_id=template.id,
                status="draft",
                current_version=0,
            )
            db.add(minutes)
            await db.flush()
        next_version = minutes.current_version + 1
        db.add(
            MinutesVersion(
                minutes_id=minutes.id,
                version=next_version,
                body_markdown=markdown,
                blocks=None,
                verification=verification,
                note="Generada automáticamente",
                model_used=getattr(provider, "model", provider.name),
            )
        )
        minutes.current_version = next_version
        await db.commit()


async def _verify_claims(provider: LLMProvider, claims: list[dict], lines: list[dict]) -> list[dict]:
    """Verifica cada claim buscando primero por keyword y consultando al LLM."""
    verification: list[dict] = []
    for claim in claims[:30]:  # límite razonable de verificaciones por acta
        text = str(claim.get("text", "")).strip()
        if not text:
            continue
        # contexto: segmentos cercanos al timestamp + coincidencias léxicas
        context_lines = _claim_context(text, claim.get("approx_ms"), lines)
        if not context_lines:
            verification.append({"claim": text, "status": "missing", "evidence_ms": None, "note": "sin coincidencias en el transcript"})
            continue
        context_text = transcript_to_text(context_lines)
        try:
            result = await provider.chat_json(
                VERIFIER_SYSTEM,
                [
                    {
                        "role": "user",
                        "content": f"Afirmación: {text}\n\nFragmentos del transcript:\n{context_text}",
                    }
                ],
                temperature=0.0,
                max_tokens=400,
            )
        except LLMError:
            result = {}
        status = result.get("status") if isinstance(result, dict) else None
        if status not in ("verified", "weak", "missing"):
            status = "weak"
        evidence_ms = result.get("evidence_ms") if isinstance(result, dict) else None
        if evidence_ms is None and context_lines:
            evidence_ms = context_lines[0]["start_ms"]
        verification.append(
            {
                "claim": text,
                "status": status,
                "evidence_ms": evidence_ms,
                "note": (result.get("note") if isinstance(result, dict) else None) or "",
            }
        )
    return verification


def _claim_context(claim_text: str, approx_ms, lines: list[dict], window: int = 6) -> list[dict]:
    """Fragmentos candidatos: alrededor del timestamp + top coincidencias léxicas."""
    selected: dict[int, dict] = {}
    if approx_ms is not None:
        try:
            approx = int(approx_ms)
            nearest = sorted(lines, key=lambda line: abs(line["start_ms"] - approx))[:window]
            for line in nearest:
                selected[line["seq"]] = line
        except (TypeError, ValueError):
            pass

    words = {w.lower().strip(".,;:¿?¡!\"'()") for w in claim_text.split() if len(w) > 4}
    if words:
        scored = []
        for line in lines:
            line_words = set(line["text"].lower().split())
            overlap = sum(1 for word in words if any(word in lw for lw in line_words))
            if overlap:
                scored.append((overlap, line))
        scored.sort(key=lambda pair: -pair[0])
        for _score, line in scored[:window]:
            selected[line["seq"]] = line

    return [selected[seq] for seq in sorted(selected)]
