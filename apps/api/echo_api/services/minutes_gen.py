"""Generación y verificación de actas.

Flujo: template (source of truth) + transcript + insights → LLM genera el acta
→ se publica enseguida → ActaVerifier contrasta cada afirmación contra el
transcript y anota el resultado. La regla crítica es NO INVENTAR: los campos
sin información llevan "No especificado durante la reunión".

El template default es PROVISIONAL y está marcado como tal: cuando el usuario
cargue su modelo real de acta (Ajustes → Formato de acta), ese pasa a mandar.
"""
import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime

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


def friendly_generation_error(exc: Exception) -> str:
    """Traduce una falla del generador a algo que la persona pueda accionar.

    Los LLMError traen el cuerpo crudo del proveedor (códigos HTTP, JSON de
    error, a veces la URL). Eso va al log y no a la pantalla.
    """
    text = str(exc).lower()
    if "api key" in text or "401" in text or "403" in text:
        return "La API key de IA no es válida o no tiene permisos. Revisala en Ajustes → IA."
    if "rate limit" in text or "429" in text:
        return "El proveedor de IA está limitando las solicitudes. Probá de nuevo en unos minutos."
    if "402" in text or "credit" in text or "quota" in text or "insufficient" in text:
        return "La cuenta del proveedor de IA se quedó sin crédito disponible."
    if "not found" in text or "404" in text or "does not exist" in text:
        return "El modelo configurado no existe para ese proveedor. Revisalo en Ajustes → IA."
    if "sin transcript" in text or "transcript" in text:
        return "La reunión no tiene transcript suficiente para armar un acta."
    if "error de red" in text or "timeout" in text or "connect" in text:
        return "No se pudo contactar al proveedor de IA. Probá de nuevo en un momento."
    return "No se pudo generar el acta. Revisá la configuración de IA en Ajustes → IA."


async def _set_generation_state(
    meeting_id: uuid.UUID, state: str, error: str | None = None
) -> None:
    async with SessionLocal() as db:
        minutes = (
            await db.execute(select(Minutes).where(Minutes.meeting_id == meeting_id))
        ).scalar_one_or_none()
        if not minutes:
            return
        minutes.generation_status = state
        minutes.generation_error = error
        await db.commit()


async def generate_minutes(meeting_id: uuid.UUID, provider: LLMProvider) -> None:
    """Genera el acta y deja registrado cómo terminó.

    Corre como BackgroundTask, o sea que nadie está esperando el resultado: si
    revienta y no lo anotamos, la falla no existe para nadie.
    """
    try:
        await _generate_minutes(meeting_id, provider)
    except Exception as exc:  # noqa: BLE001 - cualquier falla tiene que quedar registrada
        log.exception("falló la generación del acta de %s", meeting_id)
        await _set_generation_state(meeting_id, "failed", friendly_generation_error(exc))


async def _generate_minutes(meeting_id: uuid.UUID, provider: LLMProvider) -> None:
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

    # El pipeline no pasa por el endpoint de regenerar: sin esto la pantalla
    # dice "todavía no hay acta" mientras el acta se está escribiendo.
    await _mark_generating(meeting_id, org_id, template.id)

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

    # ── Guardar primero: el acta se ve apenas existe ─────────────
    # La verificación tarda (una consulta por afirmación) y no cambia el
    # texto, así que corre después, con el acta ya publicada en "verifying".
    version_id = await _store_version(meeting_id, org_id, template.id, markdown, provider)

    # ── Verificación contra el transcript ────────────────────────
    try:
        verification = await _verify_claims(provider, claims, lines)
    except Exception:  # noqa: BLE001 - el acta ya está; la verificación no la tira abajo
        log.exception("falló la verificación del acta de %s", meeting_id)
        verification = []

    async with SessionLocal() as db:
        row = await db.get(MinutesVersion, version_id)
        if row is not None:
            row.verification = verification
        minutes = (
            await db.execute(select(Minutes).where(Minutes.meeting_id == meeting_id))
        ).scalar_one_or_none()
        if minutes is not None and minutes.generation_status == "verifying":
            minutes.generation_status = "ok"
        await db.commit()


async def _mark_generating(meeting_id: uuid.UUID, org_id: uuid.UUID, template_id: uuid.UUID) -> None:
    """Deja la fila del acta en "generating" desde el primer momento."""
    async with SessionLocal() as db:
        minutes = (
            await db.execute(select(Minutes).where(Minutes.meeting_id == meeting_id))
        ).scalar_one_or_none()
        if minutes is None:
            minutes = Minutes(
                meeting_id=meeting_id,
                organization_id=org_id,
                template_id=template_id,
                status="draft",
                current_version=0,
            )
            db.add(minutes)
        minutes.generation_status = "generating"
        minutes.generation_error = None
        minutes.generation_started_at = datetime.now(UTC)
        await db.commit()


async def _store_version(
    meeting_id: uuid.UUID,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    markdown: str,
    provider: LLMProvider,
) -> uuid.UUID:
    """Publica el acta como versión nueva y deja el estado en "verifying"."""
    async with SessionLocal() as db:
        minutes = (
            await db.execute(select(Minutes).where(Minutes.meeting_id == meeting_id))
        ).scalar_one_or_none()
        if not minutes:
            minutes = Minutes(
                meeting_id=meeting_id,
                organization_id=org_id,
                template_id=template_id,
                status="draft",
                current_version=0,
                generation_status="generating",
                generation_started_at=datetime.now(UTC),
            )
            db.add(minutes)
            await db.flush()
        next_version = minutes.current_version + 1
        row = MinutesVersion(
            minutes_id=minutes.id,
            version=next_version,
            body_markdown=markdown,
            blocks=None,
            verification=None,
            note="Generada automáticamente",
            model_used=getattr(provider, "model", provider.name),
        )
        db.add(row)
        await db.flush()
        version_id = row.id
        minutes.current_version = next_version
        minutes.generation_status = "verifying"
        minutes.generation_error = None
        await db.commit()
        return version_id


async def _verify_claims(provider: LLMProvider, claims: list[dict], lines: list[dict]) -> list[dict]:
    """Verifica cada claim buscando primero por keyword y consultando al LLM.

    Las consultas van en paralelo (de a cuatro) y el resultado conserva el
    orden de las afirmaciones: treinta verificaciones en serie tardaban lo
    mismo que treinta actas.
    """
    limite = asyncio.Semaphore(4)

    async def verificar(claim: dict) -> dict | None:
        text = str(claim.get("text", "")).strip()
        if not text:
            return None
        # contexto: segmentos cercanos al timestamp + coincidencias léxicas
        context_lines = _claim_context(text, claim.get("approx_ms"), lines)
        if not context_lines:
            return {
                "claim": text,
                "status": "missing",
                "evidence_ms": None,
                "note": "sin coincidencias en el transcript",
            }
        context_text = transcript_to_text(context_lines)
        async with limite:
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
        return {
            "claim": text,
            "status": status,
            "evidence_ms": evidence_ms,
            "note": (result.get("note") if isinstance(result, dict) else None) or "",
        }

    # límite razonable de verificaciones por acta
    resultados = await asyncio.gather(*(verificar(claim) for claim in claims[:30]))
    return [item for item in resultados if item is not None]


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
