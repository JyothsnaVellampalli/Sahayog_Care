"""FastAPI routes for the Book-an-appointment flow (Phase 1.2).

Endpoints:
  GET  /api/symptoms            - catalogue for the symptom multi-select.
  POST /api/appointments/intake - run the intake graph and return the category.

The symptom catalogue is managed as a local JSON file (symptoms_2.json) and is the
single source of truth. It is English-only and is not stored in the database.
(Later this JSON may be served from S3; the loader just needs to return the same
shape, so only app.book_appointment.catalogue would change.)
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.book_appointment.catalogue import load_symptoms, symptom_index
from app.book_appointment.graph import run_intake
from app.book_appointment.schemas import IntakeRequest, IntakeResponse
from app.patient import service as patient_service

router = APIRouter(prefix="/api", tags=["book_appointment"])


class SymptomOut(BaseModel):
    id: str
    code: str
    label: str
    weight: int
    specialty: str
    severity: str


class SymptomListResponse(BaseModel):
    count: int
    symptoms: list[SymptomOut]


@router.get("/symptoms", response_model=SymptomListResponse)
def list_symptoms() -> SymptomListResponse:
    """Return the symptom catalogue for the patient form's multi-select."""
    symptoms = [SymptomOut(**s) for s in load_symptoms()]
    return SymptomListResponse(count=len(symptoms), symptoms=symptoms)


@router.post("/appointments/intake", response_model=IntakeResponse)
def appointment_intake(request: IntakeRequest) -> IntakeResponse:
    """Run the booking intake flow: de-identify, then categorise the condition.

    Input is validated by Pydantic at the boundary (PRD section 9). The response
    carries the classification (Emergency / Severe / Normal), and for a
    non-emergency, the matched specialty with doctors and their open slots.
    """
    if not request.symptoms and not request.free_text:
        raise HTTPException(422, "Select a symptom or describe what you are experiencing.")
    if any(s.symptom_id not in symptom_index() for s in request.symptoms):
        raise HTTPException(422, "Refresh the symptom catalogue and select valid symptoms.")
    return run_intake(request)


class BookSlotRequest(BaseModel):
    slot_id: UUID
    patient_id: UUID
    idempotency_key: UUID
    reason: str | None = Field(default=None, max_length=500)
    symptoms: list[dict] = Field(default_factory=list, max_length=100)
    severity: Literal["Normal", "Severe", "Need more information"] | None = None
    symptom_text: str | None = Field(default=None, max_length=4000)
    specialty_id: UUID | None = None


class BookSlotResponse(BaseModel):
    ok: bool
    slot_id: str
    status: str | None = None
    appointment_id: str | None = None
    reason: str | None = None


@router.post("/appointments/book", response_model=BookSlotResponse)
def book_appointment_slot(request: BookSlotRequest) -> BookSlotResponse:
    canonical = []
    for selected in request.symptoms:
        symptom = symptom_index().get(selected.get("id"))
        if not symptom:
            raise HTTPException(422, "Refresh the symptom catalogue and select valid symptoms.")
        if symptom["severity"] == "emergency":
            raise HTTPException(422, "Emergency symptoms require the emergency intake flow.")
        canonical.append({**symptom, "duration_days": selected.get("duration_days")})
    severity = "Severe" if any(s["severity"] == "severe" for s in canonical) else request.severity
    try:
        appt = patient_service.create_appointment(
            patient_id=str(request.patient_id), slot_id=str(request.slot_id),
            reason=request.reason, idempotency_key=str(request.idempotency_key),
            symptoms=canonical, severity=severity, symptom_text=request.symptom_text,
            specialty_id=str(request.specialty_id) if request.specialty_id else None,
        )
    except patient_service.PatientServiceUnavailable:
        raise HTTPException(status_code=503, detail="Booking service unavailable.") from None
    except Exception:
        raise HTTPException(status_code=409, detail="Could not book this slot. Refresh availability and retry.") from None
    return BookSlotResponse(ok=True, slot_id=str(request.slot_id),
                            status=appt["status"], appointment_id=appt["id"])
