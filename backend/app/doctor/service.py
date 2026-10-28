"""Doctor identity, digital signature, and consultations (Phase 2.1).

Doctors are identified by phone number alone (dev-stage: no password, no OTP,
no Supabase Auth user). Each doctor is pre-seeded with a unique phone number, so
"signing in" is simply a lookup by phone. A digital signature must still be on
file before a doctor can open a consultation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache

from app.config import settings
from app import storage


class DoctorError(RuntimeError):
    """Recoverable doctor-service error (bad credentials, duplicate, etc.)."""


class DoctorServiceUnavailable(RuntimeError):
    """Raised when Supabase is not configured."""


@lru_cache(maxsize=1)
def _admin():
    if not settings.supabase_configured:
        return None
    from supabase import create_client

    return create_client(settings.supabase_url, settings.supabase_service_key)


_PROFILE_COLS = (
    "id, doctor_code, full_name, phone, email, specialty_id, "
    "signature_key, auth_user_id"
)


def get_doctor_by_phone(phone: str) -> dict | None:
    client = _admin()
    if client is None:
        return None
    res = (
        client.table("doctors").select(_PROFILE_COLS).eq("phone", phone).limit(1).execute()
    )
    return (res.data or [None])[0]


def get_doctor_by_id(doctor_id: str) -> dict | None:
    client = _admin()
    if client is None:
        return None
    res = (
        client.table("doctors").select(_PROFILE_COLS).eq("id", doctor_id).limit(1).execute()
    )
    return (res.data or [None])[0]


def _public_profile(row: dict) -> dict:
    return {
        "id": row["id"],
        "doctor_code": row.get("doctor_code"),
        "full_name": row.get("full_name"),
        "phone": row.get("phone"),
        "email": row.get("email"),
        "role": "doctor",
        "has_signature": bool(row.get("signature_key")),
    }


def identify(phone: str) -> dict:
    """Identify a doctor by phone number only (dev-stage: no password/no OTP).

    Doctors are pre-seeded with a unique phone number. Signing in is just a
    lookup by phone; there is no Supabase Auth user and no session token. The
    returned profile carries the doctor id the UI uses for subsequent calls.
    """
    if _admin() is None:
        raise DoctorServiceUnavailable("Supabase is not configured.")
    profile = get_doctor_by_phone(phone)
    if not profile:
        raise DoctorError("No doctor found for this phone number.")
    return {"profile": _public_profile(profile)}


# --- Digital signature -------------------------------------------------------

_MAX_SIGNATURE_BYTES = 500 * 1024  # 500 KB per the design


def save_signature(doctor_id: str, data: bytes, content_type: str) -> dict:
    """Store a doctor's signature image and record the key on the doctor row."""
    admin = _admin()
    if admin is None:
        raise DoctorServiceUnavailable("Supabase is not configured.")
    if len(data) > _MAX_SIGNATURE_BYTES:
        raise DoctorError("Signature image must be under 500 KB.")
    if content_type not in ("image/png", "image/jpeg"):
        raise DoctorError("Signature must be a PNG or JPG image.")

    ext = "png" if content_type == "image/png" else "jpg"
    key = f"signatures/{doctor_id}.{ext}"
    storage.put_bytes(key, data, content_type=content_type)
    admin.table("doctors").update(
        {
            "signature_key": key,
            "signature_uploaded_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", doctor_id).execute()
    return {"has_signature": True, "signature_key": key}


def has_signature(doctor_id: str) -> bool:
    doc = get_doctor_by_id(doctor_id)
    return bool(doc and doc.get("signature_key"))


