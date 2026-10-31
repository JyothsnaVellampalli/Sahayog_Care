"""Consultation workflow endpoints, exposed under the doctor portal URLs."""

from __future__ import annotations

from uuid import UUID, uuid4
import asyncio
import base64
import logging
from time import monotonic

from fastapi import APIRouter, File, Form, UploadFile, HTTPException
from pydantic import BaseModel, Field
from postgrest.exceptions import APIError

from app.consultation import service, transcription, soap, finalization, prescriptions, jobs
from app import storage
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
    symptom_text: str | None = None
    specialty_id: str | None = None
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
        except (StorageError, OSError, service.ConsultationServiceUnavailable):
            raise HTTPException(status_code=503, detail="Could not load signed transcript.") from None
    try:
        return TranscriptResponse(segments=jobs.load_transcript(visit))
    except (StorageError, OSError, APIError, service.ConsultationServiceUnavailable):
        raise HTTPException(503, 'Could not load the saved transcript. Please retry.') from None


@router.post("/consultations/{consultation_id}/transcribe", status_code=202)
async def transcribe(
    consultation_id: UUID,
    file: UploadFile = File(...),
    recording_id: UUID = Form(...),
    session: int = Form(1, ge=1),
):
    """Persist audio and enqueue work before acknowledging the upload."""
    detail = await asyncio.to_thread(_editable, str(consultation_id))
    if not detail:
        raise HTTPException(status_code=404, detail="Consultation not found.")
    if not detail.get("consent_recorded"):
        raise HTTPException(status_code=409, detail="Record consent before sending audio to Sarvam.")
    audio = await file.read(settings.sarvam_max_audio_bytes + 1)
    if len(audio) > settings.sarvam_max_audio_bytes:
        raise HTTPException(status_code=413, detail="Recording exceeds the audio upload limit.")
    mime = (file.content_type or '').split(';')[0].lower().strip()
    if not audio or mime not in transcription._MIME_EXTENSIONS:
        raise HTTPException(422, 'Upload a non-empty supported audio recording.')
    try:
        job = await asyncio.to_thread(jobs.enqueue, str(consultation_id), 'TRANSCRIPTION', str(recording_id),
                                      {'audio_base64': base64.b64encode(audio).decode('ascii'), 'mime': mime, 'session': session})
        return {'job': public_job(job), 'recording_id': str(recording_id), 'state': 'Processing'}
    except (StorageError, OSError, APIError, service.ConsultationServiceUnavailable):
        raise HTTPException(503, 'Could not save the recording. Retry uploading it.') from None


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
    visit = _editable(consultation_id)
    segments = jobs.load_transcript(visit)
    segments.append({'speaker': request.speaker, 'text': request.text, 'session': request.session,
                     'ts': transcription._now_hhmm(), 'edited': False})
    _save_transcript_draft(visit, segments)
    return TranscriptResponse(segments=segments)


@router.post("/consultations/{consultation_id}/soap", status_code=202)
def generate_soap(consultation_id: str):
    visit = _editable(consultation_id)
    try:
        if not jobs.load_transcript(visit):
            raise HTTPException(422, 'Record audio or add a transcript note before generating SOAP.')
        return {'job': public_job(jobs.enqueue(visit['id'], 'SOAP', str(uuid4()), {'force': True}))}
    except APIError as exc:
        raise HTTPException(409 if exc.code == 'P0001' else 503, 'Could not start SOAP processing. Refresh and retry.') from None
    except (StorageError, OSError, service.ConsultationServiceUnavailable):
        raise HTTPException(503, 'Could not start SOAP processing. Your transcript is saved.') from None


def public_job(job):
    return {key: job.get(key) for key in ('id', 'kind', 'state', 'error', 'created_at', 'updated_at')}


@router.get('/consultations/{consultation_id}/processing')
def processing_status(consultation_id: UUID):
    _visit(str(consultation_id))
    try:
        return jobs.status(str(consultation_id))
    except (APIError, service.ConsultationServiceUnavailable):
        raise HTTPException(503, 'Processing status is temporarily unavailable. Please retry.') from None


@router.post('/consultations/{consultation_id}/processing/{job_id}/retry', status_code=202)
def retry_processing(consultation_id: UUID, job_id: UUID):
    _editable(str(consultation_id))
    try:
        job = jobs.client().rpc('retry_consultation_job', {'p_visit': str(consultation_id), 'p_job': str(job_id)}).execute().data
        return {'job': public_job(job)}
    except APIError as exc:
        raise HTTPException(409 if exc.code == 'P0001' else 503, 'Could not retry processing. Refresh the consultation.') from None


def _save_transcript_draft(visit, segments):
    try:
        key = f"transcript_edits/{visit['id']}/{uuid4()}.json"
        storage.put_json(key, {'segments': segments})
        jobs.client().rpc('save_consultation_draft', {'p_visit': visit['id'], 'p_kind': 'TRANSCRIPTION', 'p_key': key}).execute()
    except APIError as exc:
        raise HTTPException(409 if exc.code == 'P0001' else 503, 'Wait for processing to finish, then retry saving your transcript edits.') from None
    except (StorageError, OSError):
        raise HTTPException(503, 'Could not save transcript edits.') from None


class EditSegmentRequest(BaseModel):
    index: int = Field(..., ge=0)
    text: str = Field(..., min_length=1)


@router.put("/consultations/{consultation_id}/transcript/segment", response_model=TranscriptResponse)
def edit_segment(consultation_id: str, request: EditSegmentRequest) -> TranscriptResponse:
    """Edit a transcript segment's text (marks it edited)."""
    visit = _editable(consultation_id)
    segments = jobs.load_transcript(visit)
    if request.index >= len(segments):
        raise HTTPException(409, 'Transcript changed. Reload before editing.')
    segments[request.index].update(text=request.text, edited=True)
    _save_transcript_draft(visit, segments)
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
        draft = soap.load_for_visit(visit)
        return {"soap": draft.model_dump() if draft else None, "signature": None}
    except (StorageError, OSError, ValueError, KeyError, service.ConsultationServiceUnavailable):
        raise HTTPException(status_code=503, detail="Could not load the saved SOAP summary.") from None


@router.put("/consultations/{consultation_id}/soap", response_model=soap.SoapDraft)
def update_soap(consultation_id: str, draft: soap.SoapDraft):
    visit = _editable(consultation_id)
    try:
        key = f'soap_results/{consultation_id}/edited-{uuid4()}.json'
        storage.put_json(key, {'soap': draft.model_dump(), 'suggestions': []})
        jobs.client().rpc('save_consultation_draft', {'p_visit': visit['id'], 'p_kind': 'SOAP', 'p_key': key}).execute()
        return draft
    except APIError as exc:
        raise HTTPException(409 if exc.code == 'P0001' else 503, 'Wait for processing to finish before saving SOAP edits.') from None
    except (StorageError, OSError):
        raise HTTPException(status_code=503, detail="Could not save the SOAP edits.") from None


class SignConsultationRequest(BaseModel):
    doctor_id: UUID
    soap: SoapDraft


def _prescription_owner(consultation_id, doctor_id, editable=False):
    visit = _editable(consultation_id) if editable else _visit(consultation_id)
    if visit.get('doctor_id') != str(doctor_id):
        raise HTTPException(403, 'Consultation does not belong to this doctor.')
    if editable and visit.get('status') != 'IN_PROGRESS':
        raise HTTPException(409, 'Start the consultation before prescribing medicines.')
    return visit


@router.get('/{doctor_id}/medicines')
def medicine_catalogue(doctor_id: UUID):
    try:
        return prescriptions.catalogue(str(doctor_id))
    except service.ConsultationError as exc:
        raise HTTPException(404, str(exc)) from None
    except (APIError, service.ConsultationServiceUnavailable):
        raise HTTPException(503, 'Medicine catalogue unavailable. Please retry.') from None


@router.get('/consultations/{consultation_id}/prescription')
def get_prescription(consultation_id: str, doctor_id: UUID):
    visit = _prescription_owner(consultation_id, doctor_id)
    try:
        if visit.get('finalised_record_key'):
            record = finalization.signed_record(visit)
            return {'items': record.get('prescription', []), 'reviewed': True, 'suggestions': [],
                    'soap_revision': prescriptions.revision(record['soap'])}
        object_id = _storage_id(consultation_id)
        return prescriptions.load(object_id, soap.load_for_visit(visit), visit=visit)
    except (StorageError, OSError, ValueError, KeyError, service.ConsultationServiceUnavailable):
        raise HTTPException(503, 'Could not load the prescription. Please retry.') from None


@router.put('/consultations/{consultation_id}/prescription')
def save_prescription(consultation_id: str, doctor_id: UUID, request: prescriptions.PrescriptionDraft):
    _prescription_owner(consultation_id, doctor_id, editable=True)
    try:
        catalogue = prescriptions.catalogue(str(doctor_id))
        _prescription_owner(consultation_id, doctor_id, editable=True)
        saved = prescriptions.save(_storage_id(consultation_id), str(doctor_id), request, catalogue['items'])
        return {**saved, 'reviewed': True}
    except service.ConsultationError as exc:
        raise HTTPException(409, str(exc)) from None
    except (StorageError, OSError, APIError, service.ConsultationServiceUnavailable):
        raise HTTPException(503, 'Could not save the prescription. Please retry.') from None


@router.put('/consultations/{consultation_id}/prescription/workspace')
def save_prescription_workspace(consultation_id: str, doctor_id: UUID, request: prescriptions.PrescriptionWorkspace):
    _prescription_owner(consultation_id, doctor_id, editable=True)
    try:
        return prescriptions.save_workspace(consultation_id, request)
    except service.ConsultationError as exc:
        raise HTTPException(409, str(exc)) from None
    except (StorageError, OSError, APIError, service.ConsultationServiceUnavailable):
        raise HTTPException(503, 'Could not autosave the prescription. Your browser draft is retained.') from None


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
