"""Chat con una reunión y chat global («Preguntale a Echo»).

Ambos responden EXCLUSIVAMENTE con contexto recuperado (RAG + memoria).
Si no hay evidencia: "No encontré eso" — nunca conocimiento general del modelo.
Toda respuesta incluye fuentes con timestamps.
"""
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..deps import OrgContext, get_meeting_or_404, get_org_context, rate_limit
from ..models import ActionItem, Decision, Meeting, MeetingSummary, Question, Risk
from ..services.ai_settings import resolve_embeddings, resolve_llm
from ..services.llm import LLMError, get_llm_provider
from ..services.memory_svc import query_memory_entities
from ..services.rag import retrieve_context
from ..services.transcript_util import format_ms

router = APIRouter(tags=["chat"])

FORMAT_RULES = """FORMATO DE LA RESPUESTA:
- Empezá por la respuesta directa, en UNA frase. Nada de preámbulos.
- Resaltá en **negrita** el dato que responde la pregunta (el número, el nombre,
  la fecha, la decisión). Solo eso: si está todo en negrita, no se destaca nada.
- Usá viñetas solo cuando enumerás tres cosas o más. Para una o dos, escribí prosa.
- NADA de líneas horizontales (---), ni encabezados tipo "## Respuesta", ni
  repetir la pregunta como título.
- Sin cierres de relleno ("espero que te sirva", "si querés te amplío").
- Cortito: 2 a 4 frases salvo que te pidan detalle."""

MEETING_CHAT_SYSTEM = """Sos Echo, el asistente de reuniones. Respondés preguntas sobre UNA
reunión usando los fragmentos de transcript provistos.

CÓMO RAZONAR:
1. Tu base es el transcript. No traigas conocimiento general del mundo.
2. Pero SÍ interpretá lo que se dijo. La gente habla en borrador: no repite la
   pregunta con las palabras que vos esperás. Si alguien dice "no sé para qué
   tiene dos micrófonos, con uno alcanza", la respuesta a "¿cuántos quiere?" es
   **uno** — no "no encontré eso". Sacá la conclusión y mostrá en qué se apoya.
3. Distinguí lo dicho de lo inferido: "dijo X" vs "de X se desprende Y".
4. Reservá "No encontré eso en esta reunión." para cuando los fragmentos
   realmente no tocan el tema. Si hablan del tema pero no cierran la respuesta,
   contá lo que sí se sabe y qué quedó sin definir — eso es útil; negarte no.
5. Citá el timestamp de cada afirmación, formato [MM:SS].
6. Si un hablante tiene nombre, usalo.
7. Respondé en el idioma de la pregunta.

""" + FORMAT_RULES

GLOBAL_CHAT_SYSTEM = """Sos Echo, la memoria de reuniones de la organización. Respondés usando
EXCLUSIVAMENTE los fragmentos de transcript, hechos de memoria y datos
estructurados provistos, que pueden venir de VARIAS reuniones.

CÓMO RAZONAR:
1. Tu base es el contexto provisto. No traigas conocimiento general del mundo.
2. Pero SÍ interpretá lo que se dijo: la gente no habla con las palabras exactas
   de la pregunta. Sacá la conclusión que el contexto sostiene y mostrá en qué
   se apoya, en vez de negarte porque no está textual.
3. Distinguí lo dicho de lo inferido: "dijo X" vs "de X se desprende Y".
4. Reservá "No encontré eso en las reuniones registradas." para cuando el
   contexto realmente no toca el tema. Si lo toca sin cerrarlo, contá lo que sí
   se sabe y qué quedó abierto.
5. Citá la reunión y el timestamp de lo que salga del transcript:
   («Título», DD/MM, [MM:SS]). Los bloques REUNIONES REGISTRADAS, DECISIONES
   VIGENTES, TAREAS ABIERTAS, PREGUNTAS ABIERTAS, RIESGOS y RESÚMENES son datos
   ya consolidados: citá la reunión de origen, pero NO inventes timestamps.
6. Si la información evolucionó entre reuniones, contá la evolución en orden
   cronológico citando cada una.
7. Respondé en el idioma de la pregunta.

""" + FORMAT_RULES


class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[dict] = Field(default_factory=list, max_length=12)


class SourceOut(BaseModel):
    meeting_id: str
    meeting_title: str
    segment_id: str
    start_ms: int
    end_ms: int
    text: str
    speaker: str | None = None


class ChatOut(BaseModel):
    answer: str
    sources: list[SourceOut]


def _context_block(chunks: list[dict], include_meeting: bool) -> str:
    lines = []
    for chunk in chunks:
        stamp = f"[{format_ms(chunk['start_ms'])}]"
        speaker = f"{chunk['speaker']}: " if chunk.get("speaker") else ""
        if include_meeting:
            date = (chunk.get("meeting_date") or "")[:10]
            lines.append(f"(Reunión «{chunk['meeting_title']}» {date}) {stamp} {speaker}{chunk['text']}")
        else:
            lines.append(f"{stamp} {speaker}{chunk['text']}")
    return "\n".join(lines)


async def _structured_block(
    db: AsyncSession, org_id: uuid.UUID, meeting_id: uuid.UUID | None
) -> str:
    """Decisiones, tareas y reuniones como contexto estructurado.

    El transcript no alcanza: "¿qué decisiones siguen sin ejecutarse?" o
    "¿cuántas reuniones tuvimos?" se responden con las tablas `decisions`,
    `action_items` y `meetings`, no con los segmentos hablados.
    """
    meetings_q = select(Meeting).where(
        Meeting.organization_id == org_id, Meeting.deleted_at.is_(None)
    )
    if meeting_id:
        meetings_q = meetings_q.where(Meeting.id == meeting_id)
    meetings = (await db.execute(meetings_q.order_by(Meeting.started_at.asc()))).scalars().all()
    titles = {meeting.id: meeting.title for meeting in meetings}
    if not meetings:
        return ""

    decisions_q = select(Decision).where(
        Decision.organization_id == org_id, Decision.status == "active"
    )
    tasks_q = select(ActionItem).where(
        ActionItem.organization_id == org_id, ActionItem.status.in_(("pending", "in_progress"))
    )
    if meeting_id:
        decisions_q = decisions_q.where(Decision.meeting_id == meeting_id)
        tasks_q = tasks_q.where(ActionItem.meeting_id == meeting_id)
    questions_q = select(Question).where(Question.organization_id == org_id)
    risks_q = select(Risk).where(Risk.organization_id == org_id)
    summaries_q = select(MeetingSummary).where(
        MeetingSummary.organization_id == org_id, MeetingSummary.kind == "executive"
    )
    if meeting_id:
        questions_q = questions_q.where(Question.meeting_id == meeting_id)
        risks_q = risks_q.where(Risk.meeting_id == meeting_id)
        summaries_q = summaries_q.where(MeetingSummary.meeting_id == meeting_id)
    decisions = (await db.execute(decisions_q.limit(50))).scalars().all()
    tasks = (await db.execute(tasks_q.limit(50))).scalars().all()
    questions = (await db.execute(questions_q.limit(30))).scalars().all()
    risks = (await db.execute(risks_q.limit(30))).scalars().all()
    summaries = (await db.execute(summaries_q.limit(20))).scalars().all()

    parts: list[str] = []
    if not meeting_id:
        listing = "\n".join(
            f"- «{meeting.title}»"
            + (f" ({meeting.started_at.date().isoformat()})" if meeting.started_at else "")
            + f" — estado: {meeting.status}"
            for meeting in meetings
        )
        parts.append(f"REUNIONES REGISTRADAS ({len(meetings)} en total):\n{listing}")
    if decisions:
        listing = "\n".join(
            f"- {decision.text} (reunión «{titles.get(decision.meeting_id, '?')}»)"
            for decision in decisions
        )
        parts.append(f"DECISIONES VIGENTES ({len(decisions)}):\n{listing}")
    if tasks:
        listing = "\n".join(
            f"- {task.text}"
            + (f" — responsable: {task.assignee_name}" if task.assignee_name else "")
            + (f" — vence: {task.due_text}" if task.due_text else "")
            + f" — estado: {task.status}"
            for task in tasks
        )
        parts.append(f"TAREAS ABIERTAS ({len(tasks)}):\n{listing}")
    if questions:
        listing = "\n".join(
            f"- {item.text} (reunión «{titles.get(item.meeting_id, '?')}»)" for item in questions
        )
        parts.append(f"PREGUNTAS ABIERTAS ({len(questions)}):\n{listing}")
    if risks:
        listing = "\n".join(
            f"- {item.text} (reunión «{titles.get(item.meeting_id, '?')}»)" for item in risks
        )
        parts.append(f"RIESGOS DETECTADOS ({len(risks)}):\n{listing}")
    if summaries:
        listing = "\n".join(
            f"- «{titles.get(item.meeting_id, '?')}»: "
            + json.dumps(item.content, ensure_ascii=False)[:800]
            for item in summaries
        )
        parts.append(f"RESÚMENES EJECUTIVOS ({len(summaries)}):\n{listing}")
    return ("\n\n" + "\n\n".join(parts)) if parts else ""


async def _ask(
    db: AsyncSession,
    ctx: OrgContext,
    question: str,
    history: list[dict],
    meeting_id: uuid.UUID | None,
) -> ChatOut:
    llm_config = await resolve_llm(db, ctx.org_id)
    if llm_config is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "No hay un modelo de IA configurado. Configuralo en Ajustes → IA.",
        )
    embeddings_config = await resolve_embeddings(db, ctx.org_id)
    chunks = await retrieve_context(
        db, ctx.org_id, question, embeddings_config, meeting_id=meeting_id, limit=12
    )

    memory_block = ""
    if meeting_id is None:
        entities = await query_memory_entities(db, ctx.org_id, question)
        if entities:
            memory_block = "\n\nHECHOS DE MEMORIA (con reunión de origen):\n" + json.dumps(
                entities, ensure_ascii=False, indent=1
            )

    structured_block = await _structured_block(db, ctx.org_id, meeting_id)

    if not chunks and not memory_block and not structured_block:
        no_info = (
            "No encontré eso en esta reunión."
            if meeting_id
            else "No encontré eso en las reuniones registradas."
        )
        return ChatOut(answer=no_info, sources=[])

    system = MEETING_CHAT_SYSTEM if meeting_id else GLOBAL_CHAT_SYSTEM
    context = _context_block(chunks, include_meeting=meeting_id is None)

    messages = [
        {"role": m.get("role", "user"), "content": str(m.get("content", ""))[:2000]}
        for m in history
        if m.get("role") in ("user", "assistant")
    ]
    messages.append(
        {
            "role": "user",
            "content": (
                f"FRAGMENTOS DEL TRANSCRIPT:\n{context}"
                f"{memory_block}{structured_block}\n\nPREGUNTA: {question}"
            ),
        }
    )

    provider = get_llm_provider(
        llm_config.provider, llm_config.api_key, llm_config.model, llm_config.base_url
    )
    try:
        answer = await provider.chat(system, messages, temperature=llm_config.temperature)
    except LLMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"El modelo falló: {exc}")

    return ChatOut(
        answer=answer.strip(),
        sources=[
            SourceOut(
                meeting_id=chunk["meeting_id"],
                meeting_title=chunk["meeting_title"],
                segment_id=chunk["segment_id"],
                start_ms=chunk["start_ms"],
                end_ms=chunk["end_ms"],
                text=chunk["text"][:300],
                speaker=chunk.get("speaker"),
            )
            for chunk in chunks[:8]
        ],
    )


@router.post("/api/meetings/{meeting_id}/chat", response_model=ChatOut)
async def meeting_chat(
    meeting_id: uuid.UUID,
    data: ChatIn,
    request: Request,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    rate_limit(f"chat:{ctx.user.id}", settings.rate_limit_chat_per_minute)
    meeting = await get_meeting_or_404(meeting_id, ctx, db)
    return await _ask(db, ctx, data.question, data.history, meeting.id)


@router.post("/api/ask", response_model=ChatOut)
async def global_chat(
    data: ChatIn,
    request: Request,
    ctx: OrgContext = Depends(get_org_context),
    db: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    rate_limit(f"chat:{ctx.user.id}", settings.rate_limit_chat_per_minute)
    return await _ask(db, ctx, data.question, data.history, None)
