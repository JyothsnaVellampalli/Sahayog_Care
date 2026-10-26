"""FastAPI routes for the Book-an-appointment flow (Phase 1.2).

Endpoints:
  GET  /api/symptoms            - catalogue for the symptom multi-select.
  POST /api/appointments/intake - run the intake graph and return the category.

The symptom catalogue is managed as a local JSON file (symptoms.json) and is the
single source of truth. It is English-only and is not stored in the database.
(Later this JSON may be served from S3; the loader just needs to return the same
shape, so only app.book_appointment.catalogue would change.)
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

import uuid

from app.book_appointment.catalogue import load_symptoms
from app.book_appointment.db import DatabaseNotConfiguredError, book_slot
from app.book_appointment.graph import run_intake
from app.book_appointment.schemas import IntakeRequest, IntakeResponse
from app.patient import service as patient_service

router = APIRouter(prefix="/api", tags=["book_appointment"])

# TODO: Move this types to schema file.
class SymptomOut(BaseModel):
    id: str
    code: str
    label: str
    weight: int


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
    return run_intake(request)


class BookSlotRequest(BaseModel):
    slot_id: str
    patient_id: str | None = None
    # Human-readable summary for "My appointments" (e.g. "Cardiology - Severe").
    reason: str | None = None


class BookSlotResponse(BaseModel):
    ok: bool
    slot_id: str
    status: str | None = None
    appointment_id: str | None = None
    reason: str | None = None  # error reason when ok is False


@router.post("/appointments/book", response_model=BookSlotResponse)
def book_appointment_slot(request: BookSlotRequest) -> BookSlotResponse:
    """Reserve a chosen slot and record the appointment (Phase 1.3 + 1.4).

    Transitions the slot OPEN -> BOOKED with a guard so it cannot be
    double-booked, then (when a patient is provided) creates an appointment row
    so the booking shows up in "My appointments".
    """
    try:
        result = book_slot(request.slot_id)
    except DatabaseNotConfiguredError as exc:
        return BookSlotResponse(ok=False, slot_id=request.slot_id, reason=str(exc))

    if not result["ok"]:
        slot = result.get("slot") or {}
        return BookSlotResponse(
            ok=False,
            slot_id=request.slot_id,
            status=slot.get("status"),
            reason=result.get("reason"),
        )

    appointment_id = None
    if request.patient_id:
        try:
            appt = patient_service.create_appointment(
                patient_id=request.patient_id,
                slot_id=request.slot_id,
                reason=request.reason,
                idempotency_key=str(uuid.uuid4()),
            )
            appointment_id = appt.get("id")
        except Exception as exc:
            # The slot is reserved, but recording the appointment failed. Surface
            # it rather than hiding it, so the patient does not think the booking
            # fully succeeded when it will not show in "My appointments".
            return BookSlotResponse(
                ok=False,
                slot_id=request.slot_id,
                status="BOOKED",
                reason=f"Slot reserved but could not record the appointment: {exc}",
            )

    return BookSlotResponse(
        ok=True,
        slot_id=request.slot_id,
        status="BOOKED",
        appointment_id=appointment_id,
    )
