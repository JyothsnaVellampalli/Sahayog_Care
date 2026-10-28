"""Patient identity, profile and appointments (Phase 1.4).

Login is phone + password (dev stage, no OTP). Supabase Auth backs it using
email + password; the phone is the business identifier and ``auth_user_id``
links the ``patients`` profile row to the Supabase Auth user. ``role`` is stored
for future role-based authorization.

Flow:
  * login(phone, password): look up the profile by phone, sign in to Supabase
    with the stored email + password, return the session + profile.
  * register(phone, password, details): create the Supabase Auth user (email +
    password, email pre-confirmed) and the profile row, then sign in.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.config import settings


class PatientError(RuntimeError):
    """A recoverable patient-service error (bad credentials, duplicate, etc.)."""


class PatientServiceUnavailable(RuntimeError):
    """Raised when Supabase is not configured."""


@lru_cache(maxsize=1)
def _admin():
    """Service-role client (server-side admin ops: create user, DB writes)."""
    if not settings.supabase_configured:
        return None
    from supabase import create_client

    return create_client(settings.supabase_url, settings.supabase_service_key)


def _anon():
    """A fresh anon client for sign-in (each call gets its own session)."""
    if not (settings.supabase_url and settings.supabase_anon_key):
        return None
    from supabase import create_client

    return create_client(settings.supabase_url, settings.supabase_anon_key)


def _require_admin():
    client = _admin()
    if client is None:
        raise PatientServiceUnavailable("Supabase is not configured.")
    return client


_PROFILE_COLS = "id, phone, full_name, email, age, gender, city, role, auth_user_id"


def get_patient_by_phone(phone: str) -> dict | None:
    """Return the patient profile for a phone number, or None."""
    client = _admin()
    if client is None:
        return None
    res = (
        client.table("patients")
        .select(_PROFILE_COLS)
        .eq("phone", phone)
        .limit(1)
        .execute()
    )
    return (res.data or [None])[0]


def get_patient_by_id(patient_id: str) -> dict | None:
    """Return the patient profile for an id, or None."""
    client = _admin()
    if client is None:
        return None
    res = (
        client.table("patients")
        .select(_PROFILE_COLS)
        .eq("id", patient_id)
        .limit(1)
        .execute()
    )
    return (res.data or [None])[0]


def _public_profile(row: dict) -> dict:
    """Shape a profile row for the API (no secrets)."""
    return {
        "id": row["id"],
        "phone": row.get("phone"),
        "full_name": row.get("full_name"),
        "email": row.get("email"),
        "age": row.get("age"),
        "gender": row.get("gender"),
        "city": row.get("city"),
        "role": row.get("role", "patient"),
    }


def login(phone: str, password: str) -> dict:
    """Authenticate an existing patient by phone + password.

    Returns {"profile": {...}, "access_token": str, "refresh_token": str}.
    Raises PatientError if the phone is unknown or the password is wrong.
    """
    profile = get_patient_by_phone(phone)
    if not profile:
        raise PatientError("No account found for this phone number.")

    email = profile.get("email")
    if not email:
        raise PatientError("Account is missing an email; please contact support.")

    anon = _anon()
    if anon is None:
        raise PatientServiceUnavailable("Supabase is not configured.")
    try:
        session = anon.auth.sign_in_with_password(
            {"email": email, "password": password}
        )
    except Exception as exc:
        raise PatientError("Incorrect phone number or password.") from exc

    if not session or not session.session:
        raise PatientError("Incorrect phone number or password.")

    return {
        "profile": _public_profile(profile),
        "access_token": session.session.access_token,
        "refresh_token": session.session.refresh_token,
    }


def register(
    phone: str,
    password: str,
    full_name: str,
    age: int,
    gender: str,
    email: str,
    city: str | None,
) -> dict:
    """Create a new patient (Supabase Auth user + profile row), then sign in.

    Gender is mandatory. Raises PatientError if the phone or email is already
    registered.
    """
    admin = _require_admin()

    if get_patient_by_phone(phone):
        raise PatientError("This phone number is already registered.")

    # Create the Supabase Auth user (email + password, pre-confirmed since we
    # skip verification at this dev stage).
    try:
        created = admin.auth.admin.create_user(
            {
                "email": email,
                "password": password,
                "email_confirm": True,
                "phone": phone,
                "user_metadata": {"full_name": full_name, "role": "patient"},
            }
        )
    except Exception as exc:
        raise PatientError(f"Could not create the account: {exc}") from exc

    auth_user = created.user if created else None
    if not auth_user:
        raise PatientError("Could not create the account.")

    # Create the profile row linked to the Auth user.
    row = {
        "phone": phone,
        "full_name": full_name,
        "email": email,
        "age": age,
        "gender": gender,
        "city": city,
        "role": "patient",
        "auth_user_id": auth_user.id,
    }
    try:
        inserted = admin.table("patients").insert(row).execute()
    except Exception as exc:
        # Roll back the auth user so a failed profile insert is not orphaned.
        try:
            admin.auth.admin.delete_user(auth_user.id)
        except Exception:
            pass
        raise PatientError(f"Could not save the profile: {exc}") from exc

    profile = inserted.data[0]

    # Sign in to return a session.
    anon = _anon()
    session = anon.auth.sign_in_with_password({"email": email, "password": password})
    return {
        "profile": _public_profile(profile),
        "access_token": session.session.access_token,
        "refresh_token": session.session.refresh_token,
    }


def list_appointments(patient_id: str) -> list[dict]:
    """A patient's booked appointments plus open (not-met) emergency cases.

    Pending emergencies lead the list, then appointments, newest first in each
    group. Each is tagged with a
    ``type`` ("appointment" or "emergency"). Once staff attend to an emergency
    (is_met = true) and create an appointment, it drops out of the emergency
    source, so it is never shown twice.
    """
    client = _admin()
    if client is None:
        return []

    # Booked appointments (with doctor + slot details).
    appt_res = (
        client.table("appointments")
        .select(
            "id, status, reason, created_at, "
            "slots(starts_at, ends_at, doctors(full_name, specialties(name)))"
        )
        .eq("patient_id", patient_id)
        .order("created_at", desc=True)
        .execute()
    )
    out: list[dict] = []
    for a in appt_res.data or []:
        slot = a.get("slots") or {}
        doctor = (slot.get("doctors") or {}) if slot else {}
        specialty = (doctor.get("specialties") or {}) if doctor else {}
        out.append(
            {
                "type": "appointment",
                "id": a["id"],
                "status": a.get("status"),
                "reason": a.get("reason"),
                "created_at": a.get("created_at"),
                "starts_at": slot.get("starts_at"),
                "doctor_name": doctor.get("full_name"),
                "specialty": specialty.get("name"),
            }
        )

    # Open emergency cases (not yet attended by staff).
    for e in list_open_emergencies(patient_id):
        symptom_labels = [
            s.get("label", s.get("id", "")) for s in (e.get("symptoms") or [])
        ]
        out.append(
            {
                "type": "emergency",
                "id": e["id"],
                "status": "EMERGENCY_PENDING",
                "reason": ", ".join(symptom_labels) or "Emergency",
                "created_at": e.get("created_at"),
                "starts_at": None,
                "doctor_name": None,
                "specialty": (e.get("specialty") or {}).get("name"),
            }
        )

    # Pending emergencies always precede scheduled or historical appointments.
    out.sort(key=lambda r: (r["type"] == "emergency", r.get("created_at") or ""), reverse=True)
    return out


def create_appointment(patient_id, slot_id, reason, idempotency_key,
                       symptoms=None, severity=None, history=None):
    """Create the shared visit and reserve its slot atomically."""
    from app import appointments
    from app.book_appointment.deidentify import deidentify
    return appointments.book(_require_admin(), patient_id, slot_id, reason,
                             idempotency_key, symptoms, severity,
                             deidentify(history).text if history else None)


def appointment_detail(patient_id: str, appointment_id: str) -> dict | None:
    """Patient view of a visit; only signed clinical notes are released."""
    client = _require_admin()
    rows = client.table("appointments").select(
        "id, status, reason, symptoms, history, completed_at, finalised_record_key, "
        "slots(starts_at, doctors(full_name, specialties(name)))"
    ).eq("patient_id", patient_id).eq("id", appointment_id).limit(1).execute().data
    if not rows:
        return None
    row = rows[0]
    slot = row.get("slots") or {}
    doctor = slot.get("doctors") or {}
    result = {key: row.get(key) for key in ("id", "status", "reason", "symptoms", "history", "completed_at")}
    result.update(starts_at=slot.get("starts_at"), doctor_name=doctor.get("full_name"),
                  specialty=(doctor.get("specialties") or {}).get("name"), soap=None)
    if row.get("status") == "COMPLETED" and row.get("finalised_record_key"):
        from app.consultation.finalization import signed_record
        record = signed_record(row)
        result.update(soap=record.get("soap"), signed_at=record.get("signed_at"),
                      signed_by=record.get("doctor_name"))
    return result


# --- Emergency intakes (Phase 1.4 follow-up) ---------------------------------


def create_emergency_intake(
    patient_id: str | None,
    symptoms: list[dict],
    deidentified_text: str,
    scores: dict,
    specialty: dict | None = None,
) -> dict | None:
    """Record an emergency case. Returns the row, or None if DB is unavailable.

    Called when the triage classifies the patient as Emergency. Staff attend to
    these later (setting is_met = true and creating an appointment).
    """
    client = _admin()
    if client is None or not patient_id:
        return None
    row = {
        "patient_id": patient_id,
        "symptoms": symptoms,
        "deidentified_text": deidentified_text or "",
        "category": "Emergency",
        "scores": scores or {},
        "specialty": specialty,
    }
    res = client.table("emergency_intakes").insert(row).execute()
    return (res.data or [None])[0]


def list_open_emergencies(patient_id: str) -> list[dict]:
    """Return a patient's not-yet-attended emergency intakes (is_met = false)."""
    client = _admin()
    if client is None:
        return []
    res = (
        client.table("emergency_intakes")
        .select("id, symptoms, deidentified_text, category, is_met, created_at, specialty")
        .eq("patient_id", patient_id)
        .eq("is_met", False)
        .order("created_at", desc=True)
        .execute()
    )
    return res.data or []
