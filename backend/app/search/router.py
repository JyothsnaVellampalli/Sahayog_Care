"""Patient-facing retrieval endpoint (Phase 6.2)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.patient.router import _verify_patient
from app.search import retrieval, search
from app.search.client import SearchServiceUnavailable

router = APIRouter(prefix="/api/patients", tags=["search"])
logger = logging.getLogger(__name__)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)


class SearchHit(BaseModel):
    chunk_id: str
    chunk_type: str | None = None
    section: str | None = None
    appointment_id: str | None = None
    text: str | None = None
    score: float


class SearchResponse(BaseModel):
    retrieval_type: str
    results: list[SearchHit]


@router.post("/{patient_id}/search", response_model=SearchResponse)
def search_records(patient_id: str, request: SearchRequest, authorization: str | None = Header(default=None)):
    _verify_patient(patient_id, authorization)
    if not settings.opensearch_configured:
        raise HTTPException(503, "Search is not available right now.")
    logger.info("search: query received patient=%s length=%d", patient_id, len(request.query))
    doctors, appointments = retrieval.candidate_filters(patient_id)
    plan = retrieval.plan_query(request.query, doctors, appointments)
    logger.info("search: patient=%s plan type=%s filtered=%s", patient_id, plan.retrieval_type,
                bool(plan.doctor_id or plan.appointment_id))
    try:
        results = search.search_chunks(request.query, patient_id, plan)
    except SearchServiceUnavailable:
        raise HTTPException(503, "Search is not available right now.") from None
    except Exception as exc:
        logger.warning("search: query failed for patient=%s (%s)", patient_id, type(exc).__name__)
        raise HTTPException(503, "Search could not complete. Please retry.") from None
    logger.info("search: patient=%s returned %d result(s)", patient_id, len(results))
    return SearchResponse(retrieval_type=plan.retrieval_type, results=results)
