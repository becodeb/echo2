"""Pipeline de finalización de reunión.

Al tocar "Finalizar" corre en background:
  1. consolidar hablantes (hints de diarización → Speaker rows)
  2. extracción estructurada final (temas, decisiones, tareas, etc.)
  3. resolución de fechas relativas (dentro del paso 2, al persistir)
  4. generación del acta: arranca acá y corre en paralelo con embeddings y
     resúmenes, porque es lo primero que se quiere ver al terminar
  5. embeddings del transcript (RAG)
  6. resúmenes (el ejecutivo aparte, para que salga en segundos)
  7. espera y verificación del acta
  8. notificaciones «tu acta está lista» (en _finish)
  9. actualización de la memoria organizacional, ya con la reunión lista
 10. sugerencia de reuniones relacionadas (dentro del paso 9)

Las reuniones internas (kind="interna": directivos, coordinadores) no tienen
acta ni alimentan la memoria organizacional: son de un grupo, y la memoria la
lee toda la sede. Tienen transcript, resumen, decisiones, tareas y chat.

NO hay paso de identificación de hablantes por voice profile. El modelo
`SpeakerProfile` existe en `models/meetings.py` con su columna de embedding y
su `consent_at`, pero NADIE lo lee ni lo escribe: es schema preparado, no una
etapa del pipeline. La identidad de un hablante hoy se resuelve sólo por los
hints del motor local y por el renombrado manual desde la UI.

Cada etapa reporta progreso vía live_bus y processing_state. Si el LLM no está
configurado, las etapas de IA se saltean y quedan marcadas como "skipped"
(la UI lo muestra; nada se simula).
"""
import asyncio
import json
import logging
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, text

from ..db import SessionLocal
from ..models import (
    ActionItem,
    Bookmark,
    Decision,
    Meeting,
    MeetingParticipant,
    MeetingSummary,
    MeetingTopic,
    Notification,
    Question,
    Risk,
    Speaker,
    TranscriptSegment,
)
from .access import users_who_can_see
from .ai_settings import resolve_embeddings, resolve_llm
from .dates import resolve_relative_date
from .insights_prompts import (
    FINAL_EXTRACT_SYSTEM,
    SECTION_SUMMARY_SYSTEM,
    SUMMARY_SYSTEM,
    build_executive_prompt,
    build_final_extract_prompt,
    build_section_summary_prompt,
    build_summary_prompt,
    language_name,
)
from .live_bus import live_bus
from .llm import LLMError, get_llm_provider
from .llm.base import reasoning
from .privacy import protect
from .diarization import diarize_meeting, name_speakers
from .memory_svc import update_memory_from_meeting
from .recording import finalize_recording
from .minutes_gen import generate_minutes
from .rag import embed_meeting_segments
from .task_owner import task_owner
from .insights_live import _is_duplicate
from .transcript_util import format_ms, is_grounded, load_transcript_lines, transcript_to_text

log = logging.getLogger("echo.pipeline")

SPEAKER_COLORS = ["#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#14b8a6"]

# Si el transcript supera este tamaño se procesa jerárquicamente. Era 24.000
# (una reunión de media hora): una de dos horas iba de a secciones, una detrás
# de la otra, y las tareas salían a los 3 minutos. Leer el transcript entero
# no tarda más (27/10: 6.000 o 22.000 tokens de entrada, el mismo tiempo).
SINGLE_PASS_CHAR_LIMIT = 300_000


async def _merge_state(meeting_id: uuid.UUID, patch: dict) -> None:
    # Se mezcla en la base y no leyendo y escribiendo: el acta y el resumen
    # avisan que están listos mientras las etapas siguen avanzando, y una
    # escritura pisaba a la otra.
    async with SessionLocal() as db:
        await db.execute(
            text(
                "update meetings set processing_state = "
                "coalesce(processing_state, '{}'::jsonb) || cast(:patch as jsonb) where id = :id"
            ),
            {"patch": json.dumps(patch), "id": meeting_id},
        )
        await db.commit()


async def _set_stage(meeting_id: uuid.UUID, stage: str, progress: int, extra: dict | None = None) -> None:
    await _merge_state(meeting_id, {"stage": stage, "progress": progress, **(extra or {})})
    await live_bus.publish(
        str(meeting_id), {"type": "processing", "stage": stage, "progress": progress}
    )


async def announce_ready(meeting_id: uuid.UUID, what: str) -> None:
    """El acta ("minutes") o el resumen ejecutivo ("summary") ya se pueden leer.

    La pantalla de "Finalizar" pasa a la reunión con esto, sin esperar la
    verificación ni lo demás: el 27/10 el acta de una reunión de 4 minutos
    estaba a los 13 s y se veía a los 22.
    """
    await _merge_state(meeting_id, {f"{what}_ready": True})
    await live_bus.publish(str(meeting_id), {"type": "ready", "what": what})


async def run_finalize_pipeline(meeting_id_str: str) -> None:
    meeting_id = uuid.UUID(meeting_id_str)
    try:
        await _run(meeting_id)
    except Exception as exc:
        log.exception("pipeline fallo meeting=%s", meeting_id)
        async with SessionLocal() as db:
            meeting = await db.get(Meeting, meeting_id)
            if meeting:
                meeting.status = "failed"
                meeting.processing_state = {
                    **(meeting.processing_state or {}),
                    "stage": "failed",
                    "error": str(exc)[:500],
                }
                await db.commit()
        await live_bus.publish(meeting_id_str, {"type": "status", "status": "failed"})
    finally:
        # El audio de trabajo se cierra siempre: se borra, o si la reunión se
        # grababa, va al Drive de quien grabó (services/recording.py).
        try:
            await finalize_recording(meeting_id)
        except Exception:  # noqa: BLE001 - la limpieza tiene su propio respaldo
            log.exception("no se pudo cerrar el audio de %s", meeting_id)


async def _run(meeting_id: uuid.UUID) -> None:
    skipped: list[str] = []
    # Cuánto tarda cada paso, en segundos desde "Finalizar": queda en
    # processing_state["timings"] para medir (capacitación 26/10: "tarda mucho").
    started = time.monotonic()
    timings: dict[str, float] = {}

    def mark(step: str) -> None:
        timings[step] = round(time.monotonic() - started, 1)

    # 1. Quién habló: con el audio completo si se puede; si no, lo de siempre.
    await _set_stage(meeting_id, "speakers", 5)
    diarized = False
    try:
        diarized = await diarize_meeting(meeting_id)
    except Exception as exc:  # noqa: BLE001 - sin separación la reunión sigue igual
        log.warning("separación de hablantes falló meeting=%s: %s", meeting_id, exc)
        skipped.append("speakers:separacion_fallida")
    if not diarized:
        await consolidate_speakers(meeting_id)
    mark("transcripcion")

    async with SessionLocal() as db:
        meeting = await db.get(Meeting, meeting_id)
        if not meeting:
            return
        org_id = meeting.organization_id
        created_by = meeting.created_by
        internal = meeting.kind == "interna"
        # Las internas solo arman acta si se pidió al crearlas (meta.minutes).
        wants_minutes = not internal or bool((meeting.meta or {}).get("minutes"))
        # Resumen, tareas y acta van en el idioma de actas de la sede, aunque
        # se haya hablado en otro (reuniones en inglés, un traductor).
        from .ai_settings import get_org_ai_settings

        ai_settings = await get_org_ai_settings(db, org_id)
        language = language_name(ai_settings.minutes_language if ai_settings else None)
        reference_date = (meeting.started_at or meeting.created_at).date()
        llm_config = await resolve_llm(db, org_id)
        embeddings_config = await resolve_embeddings(db, org_id)
        lines = await load_transcript_lines(db, meeting_id)
        bookmarks = (
            (
                await db.execute(
                    select(Bookmark).where(Bookmark.meeting_id == meeting_id).order_by(Bookmark.at_ms)
                )
            )
            .scalars()
            .all()
        )
        bookmarks_text = "\n".join(
            f"[{format_ms(b.at_ms)}] {b.kind.upper()}: {b.note or '(sin nota)'}" for b in bookmarks
        )

    if not lines:
        # reunión sin transcript: completar directamente
        await _finish(meeting_id, skipped + ["sin_transcript"])
        return

    provider = None
    if llm_config:
        provider = get_llm_provider(
            llm_config.provider, llm_config.api_key, llm_config.model, llm_config.base_url
        )
        # Todo lo que sigue (insights, acta, resumen, memoria) usa este
        # provider: con él, ningún nombre le llega a la IA.
        async with SessionLocal() as db:
            provider = await protect(db, org_id, provider, meeting_id, created_by)
        # Nombres para las personas que la voz no reconoció, deducidos de la
        # conversación. Va antes de todo lo demás para que el acta y el
        # resumen ya digan quién dijo qué.
        if diarized:
            try:
                if await name_speakers(meeting_id, provider):
                    async with SessionLocal() as db:
                        lines = await load_transcript_lines(db, meeting_id)
            except Exception as exc:  # noqa: BLE001 - sin nombres queda "Persona 1"
                log.warning("nombres de hablantes fallaron meeting=%s: %s", meeting_id, exc)
        mark("nombres")

    # 2–6 en paralelo. Antes el acta esperaba a la extracción de tareas y
    # decisiones, y eran dos llamadas largas a la IA una detrás de la otra con
    # la familia esperando. El acta sale del transcript; lo estructurado que ya
    # haya (lo detectado en vivo) le sirve de pista.
    minutes_task: asyncio.Task | None = None
    if not wants_minutes:
        # Interna sin acta: lo que se quiere es el resumen y poder preguntarle.
        if provider:
            await _set_stage(meeting_id, "summary", 20)
    elif provider:
        await _set_stage(meeting_id, "minutes", 20)

        async def _minutes() -> None:
            await generate_minutes(meeting_id, provider)
            mark("acta")

        minutes_task = asyncio.create_task(_minutes())
    else:
        skipped.append("minutes:llm_no_configurado")

    async def _embeddings() -> None:
        if not embeddings_config:
            skipped.append("embeddings:no_configurado")
            return
        try:
            await embed_meeting_segments(meeting_id, embeddings_config)
        except Exception as exc:
            log.warning("embeddings fallo: %s", exc)
            skipped.append(f"embeddings:{exc}")
        mark("embeddings")

    embeddings_task = asyncio.create_task(_embeddings())

    # Resúmenes, a la par del acta y de las tareas. Antes esperaban a la
    # extracción para "no contradecirla", y en la reunión de dos horas del
    # 27/10 el resumen ejecutivo salió a los 4 minutos.
    summary_task: asyncio.Task | None = None
    if provider:

        async def _summaries() -> None:
            try:
                await _generate_summaries(provider, meeting_id, org_id, language, lines)
            except Exception as exc:  # noqa: BLE001 - sin resumen, el acta y las tareas siguen
                log.warning("resumen fallo: %s", exc)
                skipped.append(f"summary:{exc}")
            mark("resumen")

        summary_task = asyncio.create_task(_summaries())

    # Extracción estructurada final (+ resolución de fechas al persistir)
    insights: dict = {}
    if provider:
        try:
            insights = await _extract_final(provider, lines, bookmarks_text, language)
            # Solo tareas con la frase que las respalda (transcript_util.is_grounded).
            insights["tasks"] = [item for item in insights.get("tasks") or [] if is_grounded(item, lines)]
            await _persist_insights(meeting_id, insights, reference_date)
        except LLMError as exc:
            log.warning("extraccion final fallo: %s", exc)
            skipped.append(f"insights:{exc}")
        mark("tareas")
    else:
        skipped.append("insights:llm_no_configurado")

    if summary_task is not None:
        if not summary_task.done():
            await _set_stage(meeting_id, "summary", 60)
        await summary_task

    await embeddings_task
    # Esperar el acta si todavía no terminó (generación + verificación)
    if minutes_task is not None:
        if not minutes_task.done():
            await _set_stage(meeting_id, "minutes", 75)
        try:
            await minutes_task
        except Exception as exc:  # noqa: BLE001 - generate_minutes ya dejó registrada la falla
            log.warning("acta fallo: %s", exc)
            skipped.append(f"minutes:{exc}")

    mark("total")
    log.info("pipeline %s: %s", meeting_id, timings)
    await _finish(meeting_id, skipped, timings)

    # 8. Memoria organizacional (+ sugerencia de reuniones relacionadas). Las
    #    internas no: la memoria la ve toda la sede y la reunión es de un grupo.
    #    Va después de avisar que está lista: nadie la espera, y tenía la
    #    reunión "procesando" medio minuto más con el acta ya hecha (27/10).
    if provider and not internal:
        try:
            await update_memory_from_meeting(meeting_id, insights, embeddings_config)
        except Exception as exc:  # noqa: BLE001 - la reunión ya está lista
            log.warning("memoria fallo: %s", exc)


async def _finish(meeting_id: uuid.UUID, skipped: list[str], timings: dict | None = None) -> None:
    async with SessionLocal() as db:
        meeting = await db.get(Meeting, meeting_id)
        if not meeting:
            return
        meeting.status = "completed"
        meeting.processing_state = {
            "stage": "done",
            "progress": 100,
            "skipped": skipped,
            "finished_at": datetime.now(UTC).isoformat(),
            **({"timings": timings} if timings else {}),
        }
        # Avisar que está lista solo a quienes la pueden ver: el aviso lleva el
        # título, y el título ya dice de qué familia o tema fue.
        for user_id in await users_who_can_see(db, meeting):
            db.add(
                Notification(
                    user_id=user_id,
                    organization_id=meeting.organization_id,
                    kind="minutes_ready",
                    title=f"La reunión «{meeting.title}» está lista",
                    body=(
                        "Resumen, decisiones y chat disponibles."
                        if meeting.kind == "interna"
                        else "Resumen, decisiones, tareas y acta disponibles."
                    ),
                    link=f"/meetings/{meeting.id}",
                )
            )
        await db.commit()
    await live_bus.publish(str(meeting_id), {"type": "status", "status": "completed"})


# ── Hablantes ────────────────────────────────────────────────────


async def consolidate_speakers(meeting_id: uuid.UUID) -> None:
    """Agrupa speaker_hints en filas Speaker y las asigna a los segmentos."""
    async with SessionLocal() as db:
        meeting = await db.get(Meeting, meeting_id)
        if not meeting:
            return
        hints = (
            await db.execute(
                select(TranscriptSegment.speaker_hint, func.min(TranscriptSegment.seq))
                .where(TranscriptSegment.meeting_id == meeting_id)
                .group_by(TranscriptSegment.speaker_hint)
                .order_by(func.min(TranscriptSegment.seq))
            )
        ).all()
        if not hints:
            return

        existing = {
            s.label: s
            for s in (
                (await db.execute(select(Speaker).where(Speaker.meeting_id == meeting_id)))
                .scalars()
                .all()
            )
        }

        index = len(existing)
        hint_to_speaker: dict[str | None, Speaker] = {}
        for hint, _first_seq in hints:
            label = f"Speaker {index + 1}" if hint is None or hint not in existing else hint
            if hint is not None and hint.startswith("speaker_"):
                # hints normalizados del bridge: speaker_1, speaker_2...
                label = "Speaker " + hint.removeprefix("speaker_")
            speaker = existing.get(label)
            if not speaker:
                speaker = Speaker(
                    meeting_id=meeting_id,
                    label=label,
                    color=SPEAKER_COLORS[index % len(SPEAKER_COLORS)],
                )
                db.add(speaker)
                await db.flush()
                existing[label] = speaker
                index += 1
            hint_to_speaker[hint] = speaker

        for hint, speaker in hint_to_speaker.items():
            condition = (
                TranscriptSegment.speaker_hint.is_(None)
                if hint is None
                else TranscriptSegment.speaker_hint == hint
            )
            from sqlalchemy import update

            await db.execute(
                update(TranscriptSegment)
                .where(TranscriptSegment.meeting_id == meeting_id, condition)
                .values(speaker_id=speaker.id)
            )
        await db.commit()


# ── Extracción final (single-pass o jerárquica) ──────────────────


async def _extract_final(provider, lines: list[dict], bookmarks_text: str, language: str = "castellano") -> dict:
    full_text = transcript_to_text(lines)
    if len(full_text) <= SINGLE_PASS_CHAR_LIMIT:
        result = await provider.chat_json(
            FINAL_EXTRACT_SYSTEM.format(language=language),
            [{"role": "user", "content": build_final_extract_prompt(full_text, bookmarks_text)}],
            temperature=0.1,
            max_tokens=8000,
        )
        return result if isinstance(result, dict) else {}

    # Jerárquico: dividir en secciones, extraer por sección y fusionar
    sections = _split_sections(lines, SINGLE_PASS_CHAR_LIMIT)
    merged: dict = {
        "topics": [], "decisions": [], "tasks": [], "questions": [], "risks": [],
        "mentions": {"people": [], "projects": [], "dates": [], "numbers": [], "links": []},
        "timeline": [], "next_steps": [],
    }
    async def extract(section_lines: list[dict]) -> dict | None:
        try:
            return await provider.chat_json(
                FINAL_EXTRACT_SYSTEM.format(language=language),
                [{"role": "user", "content": build_final_extract_prompt(transcript_to_text(section_lines), bookmarks_text)}],
                temperature=0.1,
                max_tokens=8000,
            )
        except LLMError:
            return None

    # Las secciones a la vez: en orden, una tras otra, sumaban minutos.
    for partial in await asyncio.gather(*(extract(section) for section in sections)):
        if not isinstance(partial, dict):
            continue
        for key in ("topics", "decisions", "tasks", "questions", "risks", "timeline", "next_steps"):
            merged[key].extend(partial.get(key) or [])
        mentions = partial.get("mentions") or {}
        for key in merged["mentions"]:
            merged["mentions"][key].extend(mentions.get(key) or [])

    # dedupe básico por texto
    for key in ("decisions", "tasks", "questions", "risks"):
        seen: set[str] = set()
        unique = []
        for item in merged[key]:
            text = str(item.get("text", "")).strip().lower()
            if text and text not in seen:
                seen.add(text)
                unique.append(item)
        merged[key] = unique
    return merged


def _split_sections(lines: list[dict], char_limit: int) -> list[list[dict]]:
    sections: list[list[dict]] = []
    current: list[dict] = []
    size = 0
    for line in lines:
        line_size = len(line["text"]) + 30
        if size + line_size > char_limit and current:
            sections.append(current)
            current, size = [], 0
        current.append(line)
        size += line_size
    if current:
        sections.append(current)
    return sections


async def _persist_insights(meeting_id: uuid.UUID, insights: dict, reference_date) -> None:
    async with SessionLocal() as db:
        meeting = await db.get(Meeting, meeting_id)
        if not meeting:
            return
        org_id = meeting.organization_id

        # La pasada final reemplaza lo extraído en vivo (consolidado > incremental)
        for model in (MeetingTopic, Decision, Question, Risk):
            await db.execute(delete(model).where(model.meeting_id == meeting_id))
        # Las tareas en vivo pueden tener estado cambiado (o estar repartidas)
        # a mano: solo borrar las "ai" intactas. Repartir o confirmar una la
        # pasa a "manual"; las descartadas quedan para no volver a sugerirlas.
        await db.execute(
            delete(ActionItem).where(
                ActionItem.meeting_id == meeting_id,
                ActionItem.source == "ai",
                ActionItem.status.in_(("pending", "suggested")),
            )
        )

        for item in insights.get("topics", []) or []:
            title = str(item.get("title", "")).strip()
            if not title:
                continue
            db.add(
                MeetingTopic(
                    meeting_id=meeting_id, organization_id=org_id, title=title,
                    summary=item.get("summary"),
                    start_ms=_ms(item.get("start_ms")), end_ms=_ms(item.get("end_ms")),
                )
            )
        for item in insights.get("decisions", []) or []:
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            db.add(
                Decision(
                    meeting_id=meeting_id, organization_id=org_id, text=text,
                    context=item.get("context"),
                    evidence_start_ms=_ms(item.get("evidence_start_ms")),
                    evidence_end_ms=_ms(item.get("evidence_end_ms")),
                )
            )
        participants = (
            (
                await db.execute(
                    select(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting_id)
                )
            )
            .scalars()
            .all()
        )
        participant_users = {p.name.lower(): p.user_id for p in participants if p.user_id}
        owner_id, owner_name = await task_owner(db, meeting)
        # Las que quedaron (tocadas a mano: estado, texto o a quién se le
        # repartió) no se vuelven a crear.
        kept = list(
            (await db.execute(select(ActionItem.text).where(ActionItem.meeting_id == meeting_id))).scalars().all()
        )
        suggested = 0
        for item in insights.get("tasks", []) or []:
            text = str(item.get("text", "")).strip()
            if not text or _is_duplicate(text, kept):
                continue
            suggested += 1
            assignee = (str(item.get("assignee") or "").strip() or None)
            due_text = item.get("due")
            db.add(
                ActionItem(
                    meeting_id=meeting_id, organization_id=org_id, text=text,
                    # A quien grabó, que la reparte; sin quien grabó (Echo
                    # Device), a quien se nombró si es de la sede.
                    assignee_name=owner_name if owner_id else assignee,
                    assignee_user_id=owner_id or participant_users.get((assignee or "").lower()),
                    suggested_assignee=assignee[:200] if assignee else None,
                    due_text=due_text,
                    due_date=resolve_relative_date(due_text, reference_date),
                    evidence_start_ms=_ms(item.get("evidence_start_ms")),
                    evidence_end_ms=_ms(item.get("evidence_end_ms")),
                    # La IA se equivoca: una persona la confirma antes de que cuente.
                    status="suggested",
                )
            )
        if suggested and owner_id:
            db.add(
                Notification(
                    user_id=owner_id,
                    organization_id=org_id,
                    kind="tasks_suggested",
                    title=f"Echo sugirió {suggested} {'tarea' if suggested == 1 else 'tareas'} en «{meeting.title}»",
                    body="Confirmá las que correspondan; hasta entonces no se asignan ni aparecen en Mi trabajo.",
                    link=f"/meetings/{meeting_id}?tab=tasks",
                )
            )
        for item in insights.get("questions", []) or []:
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            db.add(
                Question(
                    meeting_id=meeting_id, organization_id=org_id, text=text,
                    evidence_start_ms=_ms(item.get("evidence_start_ms")),
                    evidence_end_ms=_ms(item.get("evidence_end_ms")),
                )
            )
        for item in insights.get("risks", []) or []:
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            db.add(
                Risk(
                    meeting_id=meeting_id, organization_id=org_id, text=text,
                    evidence_start_ms=_ms(item.get("evidence_start_ms")),
                    evidence_end_ms=_ms(item.get("evidence_end_ms")),
                )
            )

        meeting.meta = {
            **(meeting.meta or {}),
            "mentions": insights.get("mentions") or {},
            "timeline": insights.get("timeline") or [],
            "next_steps": insights.get("next_steps") or [],
        }
        await db.commit()


# ── Resúmenes ────────────────────────────────────────────────────


async def _generate_summaries(
    provider, meeting_id: uuid.UUID, org_id: uuid.UUID, language: str, lines: list[dict]
) -> None:
    """Resumen ejecutivo por un lado y detallado + "qué dijo cada uno" por otro, a la vez.

    El ejecutivo son unas pocas frases: pedido solo y sin razonar aparece en
    segundos, sin esperar al detallado, que es largo de escribir.
    """
    full_text = transcript_to_text(lines)

    if len(full_text) > SINGLE_PASS_CHAR_LIMIT:
        # jerárquico: resumen por sección → resumen global sobre los resúmenes
        sections = _split_sections(lines, SINGLE_PASS_CHAR_LIMIT)

        async def summarize(section_lines: list[dict]) -> str | None:
            try:
                partial = await provider.chat_json(
                    SECTION_SUMMARY_SYSTEM,
                    [{"role": "user", "content": build_section_summary_prompt(transcript_to_text(section_lines))}],
                )
            except LLMError:
                return None
            if isinstance(partial, dict) and partial.get("summary"):
                return f"[Sección desde {format_ms(section_lines[0]['start_ms'])}] {partial['summary']}"
            return None

        with reasoning("none"):
            section_summaries = [s for s in await asyncio.gather(*(summarize(x) for x in sections)) if s]
        source_text = "\n\n".join(section_summaries) or full_text[:SINGLE_PASS_CHAR_LIMIT]
    else:
        source_text = full_text

    model_name = getattr(provider, "model", provider.name)
    system = SUMMARY_SYSTEM.format(language=language)

    async def executive() -> None:
        with reasoning("none"):
            result = await provider.chat_json(
                system, [{"role": "user", "content": build_executive_prompt(source_text)}], max_tokens=1500
            )
        points = result.get("executive") if isinstance(result, dict) else None
        await _store_summaries(meeting_id, org_id, model_name, {"executive": {"points": points} if points else None})
        if points:
            await announce_ready(meeting_id, "summary")

    async def detailed() -> None:
        with reasoning("none"):
            result = await provider.chat_json(
                system, [{"role": "user", "content": build_summary_prompt(source_text)}], max_tokens=6000
            )
        if not isinstance(result, dict):
            return
        # "Qué dijo cada uno": lo pidió Karina para las reuniones de equipo (26/10).
        people = [
            {"name": str(entry.get("persona") or "").strip()[:200], "points": [str(p) for p in entry.get("puntos") or []][:8]}
            for entry in result.get("by_person") or []
            if isinstance(entry, dict) and entry.get("persona") and entry.get("puntos")
        ]
        await _store_summaries(
            meeting_id,
            org_id,
            model_name,
            {
                "detailed": {"markdown": result["detailed"]} if result.get("detailed") else None,
                "by_person": {"people": people} if people else None,
            },
        )

    failures = [r for r in await asyncio.gather(executive(), detailed(), return_exceptions=True) if r is not None]
    if failures:
        raise failures[0]


async def _store_summaries(
    meeting_id: uuid.UUID, org_id: uuid.UUID, model_name: str, contents: dict[str, dict | None]
) -> None:
    """Reemplaza los resúmenes de esos tipos; uno en None queda borrado."""
    async with SessionLocal() as db:
        await db.execute(
            delete(MeetingSummary).where(
                MeetingSummary.meeting_id == meeting_id, MeetingSummary.kind.in_(list(contents))
            )
        )
        for kind, content in contents.items():
            if content:
                db.add(
                    MeetingSummary(
                        meeting_id=meeting_id, organization_id=org_id, kind=kind,
                        content=content, model_used=model_name,
                    )
                )
        await db.commit()


def _ms(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
