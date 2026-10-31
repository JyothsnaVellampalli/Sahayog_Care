"""Freeze reviewed clinical content and signature before completing a visit."""
import base64
import logging
from datetime import datetime, timezone
from uuid import uuid4
from postgrest.exceptions import APIError

from app import storage
from app.config import settings
from app.doctor import service as doctor_service
from app.consultation import service, soap, prescriptions, jobs, prescription_store

logger = logging.getLogger(__name__)


def signed_record(visit):
    key = visit.get("finalised_record_key")
    if not key:
        return None
    record = storage.get_json(key, strict=True)
    if not isinstance(record, dict):
        raise storage.StorageError("Signed record is unavailable.")
    record['prescription'] = prescription_store.load(visit['id']).get('items', [])
    return record


def close(consultation_id, doctor_id, draft: soap.SoapDraft):
    visit = service.get_consultation(consultation_id)
    if not visit or visit["doctor_id"] != doctor_id:
        raise service.ConsultationError("Consultation does not belong to this doctor.")
    if visit["status"] == "COMPLETED":
        return visit  # Safe retry after a lost response; never replace a signature.
    if visit["status"] != "IN_PROGRESS" or not visit.get("consent_recorded"):
        raise service.ConsultationError("Start the consultation with consent before signing.")
    doctor = doctor_service.get_doctor_by_id(doctor_id)
    signature_key = (doctor or {}).get("signature_key")
    if not signature_key:
        raise service.ConsultationError("Upload your signature before signing.")
    signature = storage.get_bytes(signature_key, strict=True)
    if not signature:
        raise service.ConsultationError("The uploaded signature is unavailable.")
    object_id = visit["id"]
    if soap.load_for_visit(visit) is None:
        raise service.ConsultationError("Generate and review a SOAP summary before signing.")
    prescription = prescriptions.for_signing(object_id, doctor_id, draft)
    completed_at = datetime.now(timezone.utc).isoformat()
    mime = "image/png" if signature_key.lower().endswith(".png") else "image/jpeg"
    record = {"soap": draft.model_dump(mode="json"),
              "signature": f"data:{mime};base64,{base64.b64encode(signature).decode('ascii')}",
              "signed_by": doctor_id, "doctor_name": doctor.get("full_name"),
              "signed_at": completed_at}
    if settings.show_speech_transcripts:
        segments = jobs.load_transcript(visit)
        record["segments"] = segments
    # Unique key: competing requests and later draft writes cannot overwrite it.
    key = f"signed_consultations/{visit['id']}/{uuid4()}.json"
    storage.put_json(key, record)
    try:
        result = service._admin().rpc('finalize_consultation_with_stock', {
            'p_appointment_id': visit['id'], 'p_doctor_id': doctor_id,
            'p_record_key': key, 'p_prescription': prescription,
        }).execute()
    except APIError as exc:
        # Do not log provider details: constraint errors can include clinical rows.
        logger.warning("Signing database update failed (code=%s)", exc.code)
        if exc.code == 'P0001':
            raise service.ConsultationError(exc.message) from None
        if exc.code in ("PGRST204", "PGRST202", "42703", "42883"):
            raise service.ConsultationServiceUnavailable(
                "Signing database functions are unavailable. Apply "
                "phase_4_3.sql after the Phase 4.1 "
                "migration and reload the PostgREST schema cache."
            ) from None
        raise service.ConsultationServiceUnavailable(
            "The signed snapshot was stored, but the appointment could not be closed. "
            "Reload the consultation and retry."
        ) from None
    if not result.data:
        raise service.ConsultationError("Consultation changed. Reload to see its saved status.")
    saved = result.data
    return {**visit, 'status': saved['status'], 'completed_at': saved['completed_at'],
            'finalised_record_key': saved['finalised_record_key']}
