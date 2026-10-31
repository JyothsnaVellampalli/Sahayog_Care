"""Shared appointment consultation lifecycle."""
from datetime import datetime, timezone
from app import appointments
from app.book_appointment.db import _client as _admin


class ConsultationError(RuntimeError):
    pass


class ConsultationServiceUnavailable(RuntimeError):
    pass


# --- Consultations -----------------------------------------------------------

def list_consultations(doctor_id, date_from=None, date_to=None, status=None):
    """Read shared visits; pending unassigned emergencies lead the queue."""
    admin = _admin()
    if admin is None:
        return []
    q = admin.table("appointments").select(
        "*, patients(full_name, age, gender), slots!inner(doctor_id, starts_at, ends_at)"
    ).eq("slots.doctor_id", doctor_id)
    if status:
        q = q.eq("status", "BOOKED" if status == "SCHEDULED" else status)
    if date_from:
        q = q.gte("slots.starts_at", date_from)
    if date_to:
        q = q.lte("slots.starts_at", date_to)
    visits = [appointments.doctor_view(row) for row in (q.execute().data or [])]
    visits.sort(key=lambda row: row.get("starts_at") or "")
    return [appointments.emergency_view(e) for e in appointments.open_emergencies(admin)] + visits


def get_consultation(consultation_id):
    admin = _admin()
    if admin is None:
        return None
    columns = "*, patients(full_name, age, gender), slots(doctor_id, starts_at, ends_at)"
    rows = admin.table("appointments").select(columns).eq("id", consultation_id).limit(1).execute().data
    return appointments.doctor_view(rows[0]) if rows else None


def storage_id(consultation_id):
    """Use the shared appointment ID for transcripts, SOAP and recording jobs."""
    visit = get_consultation(consultation_id)
    if not visit:
        raise ConsultationError("Consultation not found.")
    return visit["id"]


def start_consultation(consultation_id, consent):
    admin = _admin()
    if admin is None:
        raise ConsultationServiceUnavailable("Supabase is not configured.")
    if not consent:
        raise ConsultationError("Patient consent is required before recording.")
    visit = get_consultation(consultation_id)
    if not visit:
        raise ConsultationError("Consultation not found.")
    if visit["status"] == "IN_PROGRESS":
        return {"status": "IN_PROGRESS"}
    if visit["status"] != "SCHEDULED":
        raise ConsultationError("Only a scheduled appointment can be started.")
    result = admin.table("appointments").update({
        "status": "IN_PROGRESS", "consent_recorded": True,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", visit["id"]).eq("status", "BOOKED").execute()
    if not result.data:
        raise ConsultationError("Appointment changed. Refresh and try again.")
    return {"status": "IN_PROGRESS"}
