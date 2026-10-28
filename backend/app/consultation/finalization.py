"""Freeze reviewed clinical content and signature before completing a visit."""
import base64
import logging
from datetime import datetime, timezone
from uuid import uuid4
from postgrest.exceptions import APIError

from app import storage
from app.config import settings
from app.doctor import service as doctor_service
from app.consultation import service, soap

logger = logging.getLogger(__name__)


def signed_record(visit):
    key = visit.get("finalised_record_key")
    if not key:
        return None
    record = storage.get_json(key, strict=True)
    if not isinstance(record, dict):
        raise storage.StorageError("Signed record is unavailable.")
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
    object_id = visit.get("legacy_consultation_id") or visit["id"]
    if soap.load_draft(object_id) is None:
        raise service.ConsultationError("Generate and review a SOAP summary before signing.")
    completed_at = datetime.now(timezone.utc).isoformat()
    mime = "image/png" if signature_key.lower().endswith(".png") else "image/jpeg"
    record = {"soap": draft.model_dump(mode="json"),
              "signature": f"data:{mime};base64,{base64.b64encode(signature).decode('ascii')}",
              "signed_by": doctor_id, "doctor_name": doctor.get("full_name"),
              "signed_at": completed_at}
    if settings.show_speech_transcripts:
        transcript = storage.get_json(f"transcripts/{object_id}.json", strict=True)
        segments = transcript.get("segments", []) if isinstance(transcript, dict) else transcript or []
        record["segments"] = segments
    # Unique key: competing requests and later draft writes cannot overwrite it.
    key = f"signed_consultations/{visit['id']}/{uuid4()}.json"
    storage.put_json(key, record)
    try:
        result = service._admin().table("appointments").update({
            "status": "COMPLETED", "completed_at": completed_at, "finalised_record_key": key,
        }).eq("id", visit["id"]).eq("status", "IN_PROGRESS").execute()
    except APIError as exc:
        # Do not log provider details: constraint errors can include clinical rows.
        logger.warning("Signing database update failed (code=%s)", exc.code)
        if exc.code in ("PGRST204", "42703"):
            raise service.ConsultationServiceUnavailable(
                "Signing database columns are unavailable. Apply "
                "phase_2_2_signed_consultations.sql after the unified appointments "
                "migration and reload the PostgREST schema cache."
            ) from None
        raise service.ConsultationServiceUnavailable(
            "The signed snapshot was stored, but the appointment could not be closed. "
            "Reload the consultation and retry."
        ) from None
    if not result.data:
        raise service.ConsultationError("Consultation changed. Reload to see its saved status.")
    return {**visit, "status": "COMPLETED", "completed_at": completed_at, "finalised_record_key": key}
