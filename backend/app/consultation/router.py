"""Consultation workflow endpoints, exposed under the doctor portal URLs."""

from __future__ import annotations

from uuid import UUID
import logging
from time import monotonic

from fastapi import APIRouter, File, Form, UploadFile, HTTPException
from pydantic import BaseModel, Field

from app.consultation import service, transcription, soap, finalization
from app.consultation.soap import SoapDraft
from app.consultation.sarvam import SarvamError
from app.config import settings
from app.storage import StorageError

router = APIRouter(prefix="/api/doctors", tags=["consultation"])
logger = logging.getLogger(__name__)


class ErrorResponse(BaseModel):
    error: str

# --- Consultations -----------------------------------------------------------


class ConsultationListItem(BaseModel):
    type: str = "appointment"
    id: str
    status: str | None = None
    severity: str | None = None
    symptoms: list = Field(default_factory=list)
    starts_at: str | None = None
    patient_name: str | None = None
    patient_age: int | None = None
    patient_gender: str | None = None


class ConsultationListResponse(BaseModel):
    count: int
    consultations: list[ConsultationListItem]


@router.get("/{doctor_id}/consultations", response_model=ConsultationListResponse)
def consultations(
    doctor_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
    status: str | None = None,
) -> ConsultationListResponse:
    """A doctor's consultations. Filter by slot date range and/or status.

    The frontend passes today's range by default (the Doctor Portal home).
    """
    items = service.list_consultations(doctor_id, date_from, date_to, status)
    return ConsultationListResponse(
        count=len(items), consultations=[ConsultationListItem(**c) for c in items]
    )


class ConsultationDetail(BaseModel):
    id: str
    status: str | None = None
    severity: str | None = None
    symptoms: list = Field(default_factory=list)
    history: str | None = None
    allergies: str | None = None
    vitals: str | None = None
    consent_recorded: bool = False
    transcript_key: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    starts_at: str | None = None
    doctor_id: str | None = None
    patient_id: str | None = None
    patient_name: str | None = None
    patient_age: int | None = None
    patient_gender: str | None = None


@router.get("/consultations/{consultation_id}", response_model=ConsultationDetail)
def consultation_detail(consultation_id: str):
    detail = service.get_consultation(consultation_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Consultation not found.")
    return ConsultationDetail(**detail)


class StartConsultationRequest(BaseModel):
    consent: bool = False


@router.post("/consultations/{consultation_id}/start")
def start_consultation(consultation_id: str, request: StartConsultationRequest):
    try:
        return service.start_consultation(consultation_id, request.consent)
    except (service.ConsultationError, service.ConsultationServiceUnavailable) as exc:
        return ErrorResponse(error=str(exc))


# --- Transcript --------------------------------------------------------------


class TranscriptResponse(BaseModel):
    segments: list = Field(default_factory=list)
    text: str | None = None
    ok: bool = True
    note: str | None = None


@router.get("/consultations/{consultation_id}/transcript", response_model=TranscriptResponse)
def get_transcript(consultation_id: str) -> TranscriptResponse:
    visit = _visit(consultation_id)
    if visit.get("finalised_record_key"):
        try:
            record = finalization.signed_record(visit)
            return TranscriptResponse(segments=record.get("segments", []) if settings.show_speech_transcripts else [])
        except (StorageError, OSError):
            raise HTTPException(status_code=503, detail="Could not load signed transcript.") from None
    return TranscriptResponse(segments=transcription.load_transcript(_storage_id(consultation_id)))


@router.post("/consultations/{consultation_id}/transcribe")
async def transcribe(
    consultation_id: UUID,
    file: UploadFile = File(...),
    recording_id: UUID = Form(...),
    session: int = Form(1, ge=1),
):
    """Upload to Sarvam; poll separately for speaker-labeled text."""
    detail = _editable(str(consultation_id))
    if not detail:
        raise HTTPException(status_code=404, detail="Consultation not found.")
    if not detail.get("consent_recorded"):
        raise HTTPException(status_code=409, detail="Record consent before sending audio to Sarvam.")
    audio = await file.read(settings.sarvam_max_audio_bytes + 1)
    if len(audio) > settings.sarvam_max_audio_bytes:
        raise HTTPException(status_code=413, detail="Recording exceeds the audio upload limit.")
    try:
        return await transcription.submit_recording(
            _storage_id(str(consultation_id)), str(recording_id), audio,
            file.content_type or "application/octet-stream", session,
        )
    except SarvamError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None


@router.get("/consultations/{consultation_id}/transcription-jobs/{recording_id}")
async def transcription_status(consultation_id: UUID, recording_id: UUID):
    _editable(str(consultation_id))
    try:
        return await transcription.poll_recording(_storage_id(str(consultation_id)), str(recording_id))
    except SarvamError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None


class AppendSegmentRequest(BaseModel):
    speaker: str | None = None
    text: str = Field(..., min_length=1)
    session: int = 1


@router.post("/consultations/{consultation_id}/transcript/segment", response_model=TranscriptResponse)
def append_segment(consultation_id: str, request: AppendSegmentRequest) -> TranscriptResponse:
    """Manually append a transcript segment (typed by the doctor)."""
    _editable(consultation_id)
    segments = transcription.append_segment(
        _storage_id(consultation_id), request.speaker, request.text, session=request.session
    )
    return TranscriptResponse(segments=segments)


@router.post("/consultations/{consultation_id}/soap", response_model=soap.SoapDraft)
def generate_soap(consultation_id: str) -> soap.SoapDraft:
    _editable(consultation_id)
    try:
        object_id = _storage_id(consultation_id)
        draft = soap.generate_draft(transcription.load_transcript(object_id))
        _editable(consultation_id)  # It may have closed while the model ran.
        logger.info("SOAP generation completed; saving draft JSON")
        save_started = monotonic()
        soap.save_draft(object_id, draft)
        logger.info("SOAP draft JSON saved in %.2fs", monotonic() - save_started)
        return draft
    except soap.SoapError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (StorageError, OSError):
        logger.warning("SOAP draft JSON could not be saved")
        raise HTTPException(status_code=503, detail="Could not save the SOAP draft. Please try again.") from None


class EditSegmentRequest(BaseModel):
    index: int = Field(..., ge=0)
    text: str = Field(..., min_length=1)


@router.put("/consultations/{consultation_id}/transcript/segment", response_model=TranscriptResponse)
def edit_segment(consultation_id: str, request: EditSegmentRequest) -> TranscriptResponse:
    """Edit a transcript segment's text (marks it edited)."""
    _editable(consultation_id)
    segments = transcription.edit_segment(
        _storage_id(consultation_id), request.index, request.text
    )
    return TranscriptResponse(segments=segments)


def _storage_id(consultation_id: str) -> str:
    try:
        return service.storage_id(consultation_id)
    except service.ConsultationError:
        raise HTTPException(status_code=404, detail="Consultation not found.") from None


def _visit(consultation_id):
    visit = service.get_consultation(consultation_id)
    if not visit:
        raise HTTPException(status_code=404, detail="Consultation not found.")
    return visit


def _editable(consultation_id):
    visit = _visit(consultation_id)
    if visit.get("status") in ("COMPLETED", "CANCELLED", "NO_SHOW"):
        raise HTTPException(status_code=409, detail="This consultation is closed and cannot be edited.")
    return visit


@router.get("/consultations/{consultation_id}/soap")
def get_soap(consultation_id: str):
    visit = _visit(consultation_id)
    try:
        if visit.get("finalised_record_key"):
            record = finalization.signed_record(visit)
            return {key: value for key, value in record.items() if key != "segments"}
        draft = soap.load_draft(_storage_id(consultation_id))
        return {"soap": draft.model_dump() if draft else None, "signature": None}
    except (StorageError, OSError, ValueError, KeyError):
        raise HTTPException(status_code=503, detail="Could not load the saved SOAP summary.") from None


@router.put("/consultations/{consultation_id}/soap", response_model=soap.SoapDraft)
def update_soap(consultation_id: str, draft: soap.SoapDraft):
    _editable(consultation_id)
    try:
        soap.save_draft(_storage_id(consultation_id), draft)
        return draft
    except (StorageError, OSError):
        raise HTTPException(status_code=503, detail="Could not save the SOAP edits.") from None


class SignConsultationRequest(BaseModel):
    doctor_id: UUID
    soap: SoapDraft


@router.post("/consultations/{consultation_id}/sign", response_model=ConsultationDetail)
def sign_consultation(consultation_id: str, request: SignConsultationRequest):
    try:
        return finalization.close(consultation_id, str(request.doctor_id), request.soap)
    except service.ConsultationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except service.ConsultationServiceUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None
    except (StorageError, OSError):
        raise HTTPException(status_code=503, detail="Could not save the signed consultation. Please retry.") from None


class EmergencyAssignmentRequest(BaseModel):
    patient_id: UUID
    slot_id: UUID
    idempotency_key: UUID


@router.post("/{doctor_id}/emergency-intakes/{intake_id}/assign")
def assign_emergency(doctor_id: UUID, intake_id: UUID, request: EmergencyAssignmentRequest):
    """Explicit manual hand-off; never called by the intake/triage graph."""
    from app import appointments
    admin = service._admin()
    if admin is None:
        raise HTTPException(status_code=503, detail="Booking service unavailable.")
    slot = admin.table("slots").select("id").eq("id", str(request.slot_id)).eq(
        "doctor_id", str(doctor_id)).execute().data
    if not slot:
        raise HTTPException(status_code=409, detail="Select a slot belonging to this doctor.")
    try:
        return appointments.book(admin, str(request.patient_id), str(request.slot_id),
                                 "Emergency", str(request.idempotency_key),
                                 emergency_intake_id=str(intake_id))
    except Exception:
        raise HTTPException(status_code=409, detail="Could not assign this emergency. Refresh and retry.") from None
