"""Chat con una reunión y chat global («Preguntale a Echo»).

Ambos responden EXCLUSIVAMENTE con contexto recuperado (RAG + memoria).
Si no hay evidencia: "No encontré eso" — nunca conocimiento general del modelo.
Toda respuesta incluye fuentes con timestamps.
"""
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db import get_db
from ..deps import OrgContext, get_meeting_or_404, get_org_context, rate_limit
from ..services.ai_settings import resolve_embeddings, resolve_llm
from ..services.llm import LLMError, get_llm_provider
from ..services.memory_svc import query_memory_entities
from ..services.rag import retrieve_context
from ..services.transcript_util import format_ms

router = APIRouter(tags=["chat"])

MEETING_CHAT_SYSTEM = """Sos Echo, el asistente de reuniones. Respondés preguntas sobre UNA
reunión usando EXCLUSIVAMENTE los fragmentos de transcript provistos.

REGLAS ESTRICTAS:
1. Solo podés afirmar lo que esté en los fragmentos. NADA de conocimiento general.
2. Si la respuesta no está en los fragmentos, respondé exactamente:
   "No encontré eso en esta reunión."
3. Citá SIEMPRE los timestamps de donde sale cada afirmación, formato [MM:SS].
4. Si un hablante tiene nombre, usalo.
5. Respondé en el idioma de la pregunta, conciso y directo."""

GLOBAL_CHAT_SYSTEM = """Sos Echo, la memoria de reuniones de la organización. Respondés usando
EXCLUSIVAMENTE los fragmentos de transcript y hechos de memoria provistos,
que pueden venir de VARIAS reuniones.

REGLAS ESTRICTAS:
1. Solo podés afirmar lo que esté en el contexto provisto.
2. Si no hay evidencia, respondé exactamente: "No encontré eso en las reuniones registradas."
3. Citá SIEMPRE la reunión y el timestamp de cada afirmación:
   («Título de la reunión», DD/MM, [MM:SS]).
4. Si la información evolucionó entre reuniones, contá la evolución en orden
   cronológico citando cada reunión.
5. Respondé en el idioma de la pregunta."""


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

    if not chunks and not memory_block:
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
            "content": f"FRAGMENTOS DEL TRANSCRIPT:\n{context}{memory_block}\n\nPREGUNTA: {question}",
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
