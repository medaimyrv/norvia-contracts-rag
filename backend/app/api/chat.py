"""Chat por SSE: POST con fetch + ReadableStream en el frontend [R9, D9, F7]."""

import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from opentelemetry import trace
from sqlalchemy.orm import Session, sessionmaker

from app.adapters.db.retriever import PgVectorRetriever
from app.adapters.providers import Providers
from app.api.deps import get_chat_service, get_providers, get_sessions
from app.domain.models import ChatRequest
from app.services.chat import (
    Answer,
    ChatEvent,
    ChatService,
    Clarification,
    Failure,
    Retrieval,
    Token,
)

router = APIRouter(prefix="/api", tags=["chat"])
log = logging.getLogger(__name__)


def sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def to_sse(event: ChatEvent) -> list[str]:
    match event:
        case Clarification(suggestions):
            return [sse("clarification", {"suggestions": suggestions})]
        case Retrieval() as r:
            data = {
                "k": len(r.chunks),
                "top_score": round(r.top_score, 4),
                "carrier_filter": r.carrier_filter,
                "chunks": [
                    {"chunk_id": str(c.chunk_id), "score": round(c.score, 4)} for c in r.chunks
                ],
            }
            return [sse("retrieval", data)]
        case Token(text):
            return [sse("token", {"text": text})]
        case Answer(final):
            citations = {
                "citations": [c.model_dump(mode="json") for c in final.citations],
                "confidence": final.confidence.value,
                "evidence": final.evidence,
            }
            return [sse("citations", citations), sse("done", {"answer": final.answer})]
        case Failure(code, message):
            return [sse("error", {"code": code, "message": message})]
    return []


async def event_stream(
    request: Request, service: ChatService, chat: ChatRequest
) -> AsyncIterator[str]:
    events = service.stream(chat)
    try:
        async for event in events:
            # Cliente desconectado [F7]: se deja de consumir y se cierra el stream del LLM
            if await request.is_disconnected():
                log.info("sse client disconnected")
                trace.get_current_span().set_attribute("sse.client_disconnected", True)
                break
            for chunk in to_sse(event):
                yield chunk
    finally:
        await events.aclose()


@router.post("/chat")
async def chat(
    request: Request,
    body: ChatRequest,
    service: Annotated[ChatService, Depends(get_chat_service)],
) -> StreamingResponse:
    return StreamingResponse(
        event_stream(request, service, body),
        media_type="text/event-stream",
        # Sin caché ni buffering en proxies: los tokens deben llegar según se generan
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/config")
def config(
    providers: Annotated[Providers, Depends(get_providers)],
    sessions: Annotated[sessionmaker[Session], Depends(get_sessions)],
) -> dict[str, object]:
    """Lo que la web necesita saber: modo demo [D15] y transportistas disponibles [D16]."""
    return {
        "demo_mode": providers.is_fake,
        "llm_model": providers.llm.model,
        "carriers": PgVectorRetriever(sessions).known_carriers(),
    }
