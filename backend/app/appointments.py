"""Shared appointment persistence; 'consultation' is the doctor-facing name."""
import logging

logger = logging.getLogger(__name__)


def symptom_labels(symptoms):
    return [str(s.get("label") or s.get("id") or "") if isinstance(s, dict) else str(s)
            for s in (symptoms or [])]


def book(client, patient_id, slot_id, reason, idempotency_key,
         symptoms=None, severity=None, symptom_text=None, emergency_intake_id=None, specialty_id=None,
         linked_appointment_id=None):
    """Reserve the slot and insert the visit in one database transaction."""
    result = client.rpc("book_appointment", {
        "p_patient_id": patient_id, "p_slot_id": slot_id,
        "p_reason": reason, "p_idempotency_key": idempotency_key,
        "p_symptoms": symptoms or [], "p_severity": severity,
        "p_specialty_id": specialty_id, "p_symptom_text": symptom_text, "p_emergency_intake_id": emergency_intake_id,
        **({"p_linked_appointment_id": linked_appointment_id} if linked_appointment_id else {}),
    }).execute()
    logger.info("booking: slot=%s reserved appointment_id=%s status=%s",
                slot_id, (result.data or {}).get("id"), (result.data or {}).get("status"))
    if result.data and result.data.get("id"):
        from app.search import jobs as search_jobs
        search_jobs.enqueue("APPOINTMENT", result.data["id"])
    return result.data


def open_emergencies(client, patient_id=None):
    query = client.table("emergency_intakes").select(
        "id, patient_id, symptoms, deidentified_text, created_at, patients(full_name, age, gender)"
    ).eq("is_met", False)
    if patient_id:
        query = query.eq("patient_id", patient_id)
    return query.order("created_at", desc=True).execute().data or []


def doctor_view(row):
    patient = row.get("patients") or {}
    slot = row.get("slots") or {}
    return {
        **{k: row.get(k) for k in (
            "id", "severity", "symptom_text", "specialty_id", "transcript_key",
            "started_at", "patient_id", "completed_at", "linked_appointment_id",
            "finalised_record_key", "soap_draft_key")},
        "type": "appointment",
        "status": "SCHEDULED" if row.get("status") == "BOOKED" else row.get("status"),
        "symptoms": symptom_labels(row.get("symptoms")),
        "consent_recorded": row.get("consent_recorded", False),
        "starts_at": slot.get("starts_at"), "doctor_id": slot.get("doctor_id"),
        "patient_name": patient.get("full_name"), "patient_age": patient.get("age"),
        "patient_gender": patient.get("gender"),
    }


def emergency_view(row):
    return {**doctor_view(row), "type": "emergency", "status": "EMERGENCY_PENDING",
            "severity": "Emergency", "symptom_text": row.get("deidentified_text")}
