"""Generación y verificación de actas.

Flujo: template (source of truth) + transcript + insights → LLM genera el acta
→ se publica enseguida → se sacan del acta las afirmaciones verificables y
ActaVerifier contrasta cada una contra el transcript y anota el resultado.
Lo único que espera quien terminó la reunión es la redacción: va sin razonar
y sin pedir las afirmaciones junto al acta (27/10: de ~16 s a ~8 s). La regla
crítica es NO INVENTAR: los campos sin información llevan "No especificado
durante la reunión".

El template default es PROVISIONAL y está marcado como tal: cuando el usuario
cargue su modelo real de acta (Ajustes → Formato de acta), ese pasa a mandar.
"""
import asyncio
import json
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select

from ..db import SessionLocal
from ..models import (
    ActionItem,
    Decision,
    Family,
    FamilyMember,
    Meeting,
    MeetingReason,
    MeetingParticipant,
    MeetingTopic,
    Minutes,
    MinutesTemplate,
    MinutesVersion,
    Organization,
    Question,
)
from . import acta_entrevista
from .insights_prompts import language_name
from .llm import LLMError, LLMProvider
from .llm.base import reasoning, streaming
from .transcript_util import format_ms, load_transcript_lines, transcript_to_text

log = logging.getLogger("echo.minutes")

# ── El acta mientras se escribe ──────────────────────────────────
# El borrador de cada acta que se está escribiendo, en memoria (una sola API
# corre el pipeline y atiende la pantalla). La pantalla lo pide mientras el
# acta está "generating" y lo muestra como si se tipeara (28/10: "ver el acta
# mientras se escribe").
_drafts: dict[uuid.UUID, str] = {}


def draft_for(meeting_id: uuid.UUID) -> str | None:
    return _drafts.get(meeting_id)


def partial_json_strings(text: str) -> dict[str, str]:
    """Los textos de un JSON que todavía está llegando: clave → valor (el último, a medias).

    Solo strings, en cualquier nivel ({"fields": {"desarrollo": "..."}} da
    "desarrollo"). Un escape cortado al final se descarta hasta que llega entero.
    """
    out: dict[str, str] = {}
    key: str | None = None
    index, size = 0, len(text)
    while index < size:
        if text[index] != '"':
            index += 1
            continue
        end = index + 1
        while end < size and text[end] != '"':
            end += 2 if text[end] == "\\" else 1
        raw = text[index + 1:min(end, size)]
        complete = end < size
        if not complete:
            # Un escape o un \uXXXX a medias al final: se espera.
            cut = raw.rfind("\\")
            if cut != -1 and (cut == len(raw) - 1 or (raw[cut + 1] == "u" and len(raw) - cut < 6)):
                raw = raw[:cut]
        try:
            value = json.loads(f'"{raw}"')
        except json.JSONDecodeError:
            value = raw
        rest = text[end + 1:].lstrip() if complete else ""
        if complete and rest.startswith(":"):
            key = value
        elif key is not None:
            out[key] = value
            key = None
        index = end + 1
    return out


def _drafter(meeting_id: uuid.UUID, render: Callable[[dict[str, str]], str]) -> Callable[[str], None]:
    """El aviso que recibe el texto de la IA a medida que llega y arma el borrador."""
    announced = False

    def on_text(raw: str) -> None:
        nonlocal announced
        markdown = render(partial_json_strings(raw))
        if not markdown.strip():
            return
        _drafts[meeting_id] = markdown
        if not announced:
            # Con la primera línea, la pantalla de "Finalizar" ya pasa al acta.
            announced = True
            from .background import spawn
            from .pipeline import announce_ready  # pipeline importa este módulo

            spawn(announce_ready(meeting_id, "minutes"), name=f"acta-escribiendo:{meeting_id}")

    return on_text

DEFAULT_TEMPLATE_NAME = "Acta estándar (provisional)"

# Hasta dónde se le pasa el transcript al acta: ~100.000 tokens, una reunión
# de varias horas.
TRANSCRIPT_CHAR_LIMIT = 400_000

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
5. Escribí el acta en {language}."""


CLAIMS_SYSTEM = """Recibís un acta de reunión y el transcript del que salió. Listá
las afirmaciones verificables del acta (hechos, acuerdos, compromisos, fechas,
cifras), una frase cada una, con el timestamp aproximado del transcript donde
se dijo. Como mucho 20, las más importantes primero.

Respondé JSON: {"claims": [{"text": "afirmación", "approx_ms": <int o null>}]}"""


VERIFIER_SYSTEM = """Sos el verificador de actas de Echo. Recibís una afirmación de un
acta y fragmentos del transcript. Determiná si el transcript RESPALDA la
afirmación.

Respondé JSON: {"status": "verified"|"weak"|"missing", "evidence_ms": <int o null>, "note": "breve"}
- verified: el transcript la respalda claramente.
- weak: hay algo relacionado pero no es concluyente.
- missing: no hay evidencia en el transcript."""


# Reuniones entre las dos sedes (Nordelta y Puertos): el acta sale con el
# modelo genérico de Echo, sin el formulario de ninguna sede.
INTERSEDE_TEMPLATE_NAME = "Intersede (sin formato de sede)"


async def template_for(db, meeting: Meeting) -> MinutesTemplate:
    """El modelo de acta de esta reunión: el de la sede, o el genérico si es intersede."""
    if not (meeting.meta or {}).get("intersede"):
        return await get_active_template(db, meeting.organization_id)
    template = (
        await db.execute(
            select(MinutesTemplate).where(
                MinutesTemplate.organization_id == meeting.organization_id,
                MinutesTemplate.name == INTERSEDE_TEMPLATE_NAME,
            )
        )
    ).scalars().first()
    if template is None:
        template = MinutesTemplate(
            organization_id=meeting.organization_id,
            name=INTERSEDE_TEMPLATE_NAME,
            body_markdown=DEFAULT_TEMPLATE,
            is_default=False,
            is_provisional=False,
        )
        db.add(template)
        await db.commit()
        await db.refresh(template)
    return template


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


# Lo que quien pide el acta quiere que esté o que no esté (opcional, al
# generar o regenerar). Nunca habilita a inventar: va debajo de las reglas.
MAX_INSTRUCTIONS = 1000


def instructions_block(instructions: str | None) -> str:
    text = " ".join((instructions or "").split())[:MAX_INSTRUCTIONS]
    if not text:
        return ""
    return (
        "\n\nINDICACIONES DE QUIEN PIDE EL ACTA (qué incluir y qué dejar afuera; respetalas, "
        "pero sin inventar nada que no se haya dicho en la reunión):\n" + text
    )


async def generate_minutes(meeting_id: uuid.UUID, provider: LLMProvider, instructions: str | None = None) -> None:
    """Genera el acta y deja registrado cómo terminó.

    Corre como BackgroundTask, o sea que nadie está esperando el resultado: si
    revienta y no lo anotamos, la falla no existe para nadie.
    """
    try:
        await _generate_minutes(meeting_id, provider, instructions)
    except Exception as exc:  # noqa: BLE001 - cualquier falla tiene que quedar registrada
        log.exception("falló la generación del acta de %s", meeting_id)
        await _set_generation_state(meeting_id, "failed", friendly_generation_error(exc))
        return
    finally:
        _drafts.pop(meeting_id, None)
    # Al Drive de la sede apenas está, sin esperar a que la aprueben.
    from .drive import upload_minutes

    try:
        await upload_minutes(meeting_id)
    except Exception:  # noqa: BLE001 - Drive nunca tira abajo el acta
        log.exception("drive: no se pudo subir el acta de %s", meeting_id)


async def _generate_minutes(meeting_id: uuid.UUID, provider: LLMProvider, instructions: str | None = None) -> None:
    async with SessionLocal() as db:
        meeting = await db.get(Meeting, meeting_id)
        if not meeting:
            return
        org_id = meeting.organization_id
        template = await template_for(db, meeting)
        org = await db.get(Organization, org_id)
        letterhead = (org.letterhead if org else None) or {}
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
            (
                await db.execute(
                    select(ActionItem).where(ActionItem.meeting_id == meeting_id, ActionItem.status != "dismissed")
                )
            )
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
        # El acta sale en el idioma de actas de la sede aunque se haya
        # hablado en otro ("varios idiomas": inglés, un traductor).
        language = language_name(ai_settings.minutes_language if ai_settings else None)

        # Lo que se cargó a mano en la clasificación vale más que lo que el
        # modelo pueda deducir del audio: va como pista explícita.
        reason_name = None
        if meeting.reason_id:
            reason = await db.get(MeetingReason, meeting.reason_id)
            reason_name = reason.name if reason else None
        family_hint = None
        # De qué hijo(s) es la reunión: lo eligió quien la creó; si la familia
        # tiene un solo estudiante, es ese. Van al acta con iniciales y curso.
        students: list[FamilyMember] = []
        # Todos los hijos de la familia: el borrador los oculta a todos (el
        # acta final, al elegido o al que nombró la IA).
        all_kids: list[FamilyMember] = []
        if meeting.family_id:
            family = await db.get(Family, meeting.family_id)
            if family is not None:
                members = (
                    (await db.execute(select(FamilyMember).where(FamilyMember.family_id == family.id)))
                    .scalars()
                    .all()
                )
                chosen = {str(student_id) for student_id in meeting.student_ids or []}
                kids = [m for m in members if m.relationship_type == "estudiante"]
                all_kids = kids
                students = [m for m in kids if str(m.id) in chosen] or (kids if len(kids) == 1 else [])
                family_hint = {
                    "familia": family.name,
                    "integrantes": [
                        {"nombre": m.name, "vinculo": m.relationship_type, **({"curso": m.curso} if m.curso else {})}
                        for m in members
                    ],
                }
                if students:
                    family_hint["alumno_de_la_reunion"] = [
                        {"iniciales": acta_entrevista.initials(m.name), **({"curso": m.curso} if m.curso else {})}
                        for m in students
                    ]

    # El pipeline no pasa por el endpoint de regenerar: sin esto la pantalla
    # dice "todavía no hay acta" mientras el acta se está escribiendo.
    await _mark_generating(meeting_id, org_id, template.id)

    transcript_text = transcript_to_text(lines)
    # Antes se cortaba en 28.000 caracteres (~35 minutos) y el acta de una
    # reunión de dos horas salía solo con el principio. Leer más no tarda: lo
    # que tarda es lo que se escribe (medido: 6.000 o 22.000 tokens de entrada,
    # el mismo tiempo).
    if len(transcript_text) > TRANSCRIPT_CHAR_LIMIT:
        transcript_text = (
            transcript_text[:TRANSCRIPT_CHAR_LIMIT]
            + "\n[transcript truncado para el prompt; los datos estructurados cubren el resto]"
        )

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
                # Quién se comprometió en la reunión, no a quién se le repartió.
                "responsable": t.suggested_assignee or t.assignee_name,
                "fecha": t.due_text,
                "fecha_resuelta": t.due_date.isoformat() if t.due_date else None,
                "evidencia_ms": t.evidence_start_ms,
            }
            for t in tasks
        ],
        "pendientes": [q.text for q in questions if not q.resolved],
    }
    if students:
        # Cargado por quien creó la reunión: el acta nombra al alumno solo así.
        structured["alumno"] = [
            {"iniciales": acta_entrevista.initials(m.name), **({"curso": m.curso} if m.curso else {})}
            for m in students
        ]

    if acta_entrevista.is_interview_template(template.body_markdown):
        fecha = acta_entrevista.meeting_date(meeting.started_at or meeting.created_at)
        hora = acta_entrevista.meeting_time(meeting.started_at or meeting.created_at)
        # El membrete puede fijar el formulario por nivel; si no, el del modelo de acta.
        nivel = acta_entrevista.configured_level(letterhead, meeting.level)
        level_cfg = acta_entrevista.level_settings(letterhead, nivel)
        formato = level_cfg["format"] or acta_entrevista.template_format(template.body_markdown)
        # "De manera presencial / remota" del párrafo de la planilla: remota si se
        # grabó el audio de una llamada (Meet, Zoom, Teams).
        modalidad = ("remota" if (meeting.meta or {}).get("remote") else "presencial") if level_cfg["school"] else ""
        hints = {**structured, "motivo_cargado": reason_name, "familia_cargada": family_hint}
        hidden = [(m.name, acta_entrevista.initials(m.name)) for m in students]
        draft_hidden = [(m.name, acta_entrevista.initials(m.name)) for m in all_kids]

        def render_draft(values: dict[str, str]) -> str:
            # Lo mismo que el acta final con lo que llegó hasta ahora.
            partial = acta_entrevista.normalize_fields(
                {**values, "fecha": fecha.isoformat(), "formato": formato, "hora": hora, "nivel": nivel, "modalidad": modalidad},
                fecha,
                hora,
            )
            if not (partial["desarrollo"] or partial["con"] or partial["reunen"]):
                return ""
            if students:
                partial["alumno"] = ", ".join(acta_entrevista.initials(m.name) for m in students)
                cursos = [m.curso for m in students if m.curso]
                if cursos:
                    partial["curso"] = ", ".join(dict.fromkeys(cursos))
            if reason_name and not partial["motivo"]:
                partial["motivo"] = reason_name
            for key in ("alumno", "desarrollo", "con", "reunen", "motivo"):
                partial[key] = acta_entrevista.hide_student_names(partial[key], draft_hidden)
            return acta_entrevista.render_markdown(partial, letterhead)

        with reasoning("none"), streaming(_drafter(meeting_id, render_draft)):
            result = await provider.chat_json(
                acta_entrevista.GENERATOR_SYSTEM.format(language=language),
                [
                    {
                        "role": "user",
                        "content": f"""{acta_entrevista.fields_spec(formato, nivel, level_cfg["school"])}

DATOS DE LA REUNIÓN (lo "cargado" lo ingresó una persona: tiene prioridad):
{json.dumps(hints, ensure_ascii=False, indent=1)}

TRANSCRIPT (con timestamps [MM:SS] y hablantes):

{transcript_text}{instructions_block(instructions)}

Devolvé JSON:
{{
  "fields": {{"alumno": "", "curso": "", "solicitada_por": "", "motivo": "", "reunen": "", "con": "", "desarrollo": ""}}
}}""",
                    }
                ],
                temperature=0.1,
                max_tokens=8000,
            )
        if not isinstance(result, dict) or not isinstance(result.get("fields"), dict):
            raise LLMError("El generador de actas no devolvió contenido")
        fields = acta_entrevista.normalize_fields(
            {**result["fields"], "fecha": fecha.isoformat(), "formato": formato, "hora": hora, "nivel": nivel, "modalidad": modalidad},
            fecha,
            hora,
        )
        if reason_name and not fields["motivo"]:
            fields["motivo"] = reason_name
        # Si la IA nombró al alumno con su marcador, sabemos exactamente quién
        # es: va como figura en la nómina ("MUNAFO, Allegra") y con su curso.
        pseudonymizer = getattr(provider, "pseudonymizer", None)
        student = pseudonymizer.person_for_token_text(fields["alumno"]) if pseudonymizer else None
        if students:
            # Lo cargado gana: el alumno elegido al crear la reunión, con su curso.
            fields["alumno"] = ", ".join(acta_entrevista.initials(m.name) for m in students)
            cursos = [m.curso for m in students if m.curso]
            if cursos:
                fields["curso"] = ", ".join(dict.fromkeys(cursos))
        elif student is not None:
            full = student.formal or student.display
            fields["alumno"] = acta_entrevista.initials(full)
            hidden.append((full, fields["alumno"]))
            # El curso de la nómina ("1F EP") gana sobre cómo se dijo en voz
            # alta ("primero F"): es el formato del registro del colegio.
            if student.extra.get("curso"):
                fields["curso"] = str(student.extra["curso"])
        # El acta nombra al alumno solo con sus iniciales, también en el desarrollo.
        for key in ("desarrollo", "con", "reunen", "motivo"):
            fields[key] = acta_entrevista.hide_student_names(fields[key], hidden)
        await _publish_and_verify(
            meeting_id, org_id, template.id, acta_entrevista.render_markdown(fields, letterhead),
            acta_entrevista.to_blocks(fields), result, lines, provider, instructions,
        )
        return

    prompt = f"""MODELO DE ACTA (respetalo al pie de la letra):

{template.body_markdown}

DATOS ESTRUCTURADOS DE LA REUNIÓN:
{json.dumps(structured, ensure_ascii=False, indent=1)}

TRANSCRIPT (con timestamps [MM:SS] y hablantes):

{transcript_text}{instructions_block(instructions)}

Devolvé JSON:
{{
  "markdown": "el acta completa en markdown siguiendo el modelo"
}}"""

    draft_hidden = [(m.name, acta_entrevista.initials(m.name)) for m in all_kids]

    def render_draft(values: dict[str, str]) -> str:
        return acta_entrevista.hide_student_names(values.get("markdown", ""), draft_hidden)

    with reasoning("none"), streaming(_drafter(meeting_id, render_draft)):
        result = await provider.chat_json(
            GENERATOR_SYSTEM.format(language=language),
            [{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=8000,
        )
    if not isinstance(result, dict) or not result.get("markdown"):
        raise LLMError("El generador de actas no devolvió contenido")

    # El acta nombra al alumno solo con sus iniciales.
    markdown = acta_entrevista.hide_student_names(
        str(result["markdown"]), [(m.name, acta_entrevista.initials(m.name)) for m in students]
    )
    await _publish_and_verify(
        meeting_id, org_id, template.id, markdown, None, result, lines, provider, instructions
    )


async def _publish_and_verify(
    meeting_id: uuid.UUID,
    org_id: uuid.UUID,
    template_id: uuid.UUID,
    markdown: str,
    blocks: dict | None,
    result: dict,
    lines: list[dict],
    provider: LLMProvider,
    instructions: str | None = None,
) -> None:
    # ── Guardar primero: el acta se ve apenas existe ─────────────
    # La verificación tarda (sacar las afirmaciones y una consulta por cada
    # una) y no cambia el texto, así que corre después, con el acta ya
    # publicada en "verifying".
    version_id = await _store_version(meeting_id, org_id, template_id, markdown, provider, blocks, instructions)
    from .pipeline import announce_ready  # pipeline importa este módulo

    await announce_ready(meeting_id, "minutes")

    # ── Verificación contra el transcript ────────────────────────
    try:
        claims = [c for c in (result.get("claims") or []) if isinstance(c, dict) and c.get("text")]
        if not claims:
            claims = await _extract_claims(provider, markdown, lines)
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
    blocks: dict | None = None,
    instructions: str | None = None,
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
            blocks=blocks,
            verification=None,
            note=(
                f"Generada con indicaciones: {' '.join(instructions.split())}"[:300]
                if instructions and instructions.strip()
                else "Generada automáticamente"
            ),
            model_used=getattr(provider, "model", provider.name),
        )
        db.add(row)
        await db.flush()
        version_id = row.id
        minutes.current_version = next_version
        minutes.generation_status = "verifying"
        minutes.generation_error = None
        # El número no sale solo: lo pone quien hace el acta (Bauti, 6/10),
        # porque hay actas que se hacen fuera de Echo y el contador no las ve.
        await db.commit()
        return version_id


async def _extract_claims(provider: LLMProvider, markdown: str, lines: list[dict]) -> list[dict]:
    """Las afirmaciones verificables del acta ya publicada, con dónde se dijeron."""
    transcript_text = transcript_to_text(lines)[:TRANSCRIPT_CHAR_LIMIT]
    content = f"ACTA:\n{markdown}\n\nTRANSCRIPT (con timestamps [MM:SS]):\n{transcript_text}"
    with reasoning("none"):
        result = await provider.chat_json(
            CLAIMS_SYSTEM,
            [{"role": "user", "content": content}],
            temperature=0.0,
            max_tokens=3000,
        )
    claims = result.get("claims") if isinstance(result, dict) else None
    return [c for c in claims or [] if isinstance(c, dict) and c.get("text")]


async def _verify_claims(provider: LLMProvider, claims: list[dict], lines: list[dict]) -> list[dict]:
    """Verifica cada claim buscando primero por keyword y consultando al LLM.

    Las consultas van en paralelo (de a diez) y el resultado conserva el
    orden de las afirmaciones: treinta verificaciones en serie tardaban lo
    mismo que treinta actas, y de a cuatro la reunión seguía "procesando"
    medio minuto después de tener el acta (27/10).
    """
    limite = asyncio.Semaphore(10)

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
