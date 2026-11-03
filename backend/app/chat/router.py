"""Patient chatbot endpoints (Phase 6.3)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.chat import agent
from app.config import settings
from app.patient.router import _verify_patient

router = APIRouter(prefix="/api/patients", tags=["chat"])
logger = logging.getLogger(__name__)


def _chat_configured() -> bool:
    return settings.opensearch_configured and settings.consultation_checkpointing_configured


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)


class ChatReference(BaseModel):
    chunk_id: str
    chunk_type: str | None = None
    section: str | None = None
    appointment_id: str | None = None
    text: str | None = None


class ChatResponse(BaseModel):
    reply: str
    references: list[ChatReference]


class ChatHistoryTurn(BaseModel):
    role: str
    content: str


class ChatHistoryResponse(BaseModel):
    history: list[ChatHistoryTurn]


@router.post("/{patient_id}/chat", response_model=ChatResponse)
def ask_question(patient_id: str, request: ChatRequest, authorization: str | None = Header(default=None)):
    _verify_patient(patient_id, authorization)
    if not _chat_configured():
        raise HTTPException(503, "Ask your query is not available right now.")
    logger.info("chat: message received patient=%s length=%d", patient_id, len(request.message))
    try:
        result = agent.ask(patient_id, request.message)
    except Exception as exc:
        logger.warning("chat: reply failed for patient=%s (%s)", patient_id, type(exc).__name__)
        raise HTTPException(503, "Could not get a reply. Please retry.") from None
    logger.info("chat: reply returned patient=%s references=%d", patient_id, len(result.references))
    return ChatResponse(reply=result.reply, references=[ChatReference(**r) for r in result.references])


@router.get("/{patient_id}/chat", response_model=ChatHistoryResponse)
def chat_history(patient_id: str, authorization: str | None = Header(default=None)):
    _verify_patient(patient_id, authorization)
    if not settings.consultation_checkpointing_configured:
        return ChatHistoryResponse(history=[])
    try:
        history = agent.get_history(patient_id)
    except Exception as exc:
        logger.warning("chat: history unavailable for patient=%s (%s)", patient_id, type(exc).__name__)
        raise HTTPException(503, "Chat history is not available right now.") from None
    return ChatHistoryResponse(history=[ChatHistoryTurn(**turn) for turn in history])
