"""Database access for the booking flow (Phase 1.3).

Thin, typed helpers over the Supabase client for the read queries the booking
graph needs: specialties, doctors by specialty, and open slots. These are plain
data lookups — no AI (PRD: the slot engine is deterministic).

All functions degrade gracefully: if Supabase is not configured they return
empty lists rather than raising, so the graph can still run and report that no
options are available.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.config import settings


class DatabaseNotConfiguredError(RuntimeError):
    """Raised when a write/booking op is attempted without Supabase config."""


@lru_cache(maxsize=1)
def _client():
    """Return a cached Supabase client, or None if not configured."""
    if not settings.supabase_configured:
        return None
    from supabase import create_client

    return create_client(settings.supabase_url, settings.supabase_service_key)


def list_specialties() -> list[dict]:
    """All specialties: [{id, code, name, description}, ...]."""
    client = _client()
    if client is None:
        return []
    res = (
        client.table("specialties")
        .select("id, code, name, description")
        .order("name")
        .execute()
    )
    return res.data or []


def doctors_by_specialty(specialty_id: str) -> list[dict]:
    """Active doctors in a specialty, with their facility name."""
    client = _client()
    if client is None:
        return []
    res = (
        client.table("doctors")
        .select(
            "id, doctor_code, full_name, years_experience, languages, "
            "specialty_id, facility_id, hospitals(name, city)"
        )
        .eq("specialty_id", specialty_id)
        .eq("is_active", True)
        .order("years_experience", desc=True)
        .execute()
    )
    return res.data or []


def open_slots_for_doctors(
    doctor_ids: list[str], limit_per_doctor: int = 5
) -> dict[str, list[dict]]:
    """Earliest OPEN slots per doctor.

    Returns {doctor_id: [{id, starts_at, ends_at}, ...]} ordered by start time.
    Pure logic, no AI (PRD: the slot suggestion engine is deterministic).
    """
    client = _client()
    if client is None or not doctor_ids:
        return {}

    # Fetch upcoming OPEN slots for all requested doctors in one query, then
    # group and trim per doctor in Python (keeps it to a single round-trip).
    res = (
        client.table("slots")
        .select("id, doctor_id, starts_at, ends_at")
        .in_("doctor_id", doctor_ids)
        .eq("status", "OPEN")
        .order("starts_at")
        .execute()
    )
    grouped: dict[str, list[dict]] = {d: [] for d in doctor_ids}
    for row in res.data or []:
        bucket = grouped.setdefault(row["doctor_id"], [])
        if len(bucket) < limit_per_doctor:
            bucket.append(
                {
                    "id": row["id"],
                    "starts_at": row["starts_at"],
                    "ends_at": row["ends_at"],
                }
            )
    return grouped


def get_slot(slot_id: str) -> dict | None:
    """Fetch a single slot by id, or None."""
    client = _client()
    if client is None:
        return None
    res = (
        client.table("slots")
        .select("id, doctor_id, starts_at, ends_at, status")
        .eq("id", slot_id)
        .limit(1)
        .execute()
    )
    return (res.data or [None])[0]


def book_slot(slot_id: str) -> dict:
    """Reserve an OPEN slot by transitioning it to BOOKED.

    The update is guarded on ``status = 'OPEN'`` so a slot cannot be
    double-booked: if two requests race, only the first flips OPEN -> BOOKED and
    the second updates zero rows.

    Returns {"ok": bool, "slot": <slot or None>, "reason": str | None}.
    """
    client = _client()
    if client is None:
        raise DatabaseNotConfiguredError(
            "Supabase is not configured; cannot book a slot."
        )

    existing = get_slot(slot_id)
    if existing is None:
        return {"ok": False, "slot": None, "reason": "Slot not found."}
    if existing["status"] != "OPEN":
        return {"ok": False, "slot": existing, "reason": "Slot is no longer available."}

    res = (
        client.table("slots")
        .update({"status": "BOOKED"})
        .eq("id", slot_id)
        .eq("status", "OPEN")  # guard: only book if still open
        .execute()
    )
    if not res.data:
        # Someone else booked it between the read and the update.
        return {"ok": False, "slot": get_slot(slot_id), "reason": "Slot was just taken."}
    return {"ok": True, "slot": res.data[0], "reason": None}


def doctors_with_slots(
    specialty_id: str, limit_per_doctor: int = 5
) -> list[dict]:
    """Doctors in a specialty, each with their earliest OPEN slots attached.

    Doctors with no open slots are still returned (with an empty slot list) so
    the UI can show availability transparently.
    """
    doctors = doctors_by_specialty(specialty_id)
    if not doctors:
        return []
    slot_map = open_slots_for_doctors(
        [d["id"] for d in doctors], limit_per_doctor=limit_per_doctor
    )
    result = []
    for d in doctors:
        facility = d.get("hospitals") or {}
        result.append(
            {
                "id": d["id"],
                "doctor_code": d["doctor_code"],
                "full_name": d["full_name"],
                "years_experience": d.get("years_experience"),
                "languages": d.get("languages") or [],
                "facility_name": facility.get("name"),
                "city": facility.get("city"),
                "slots": slot_map.get(d["id"], []),
            }
        )
    # Surface doctors who actually have availability first.
    result.sort(key=lambda r: (len(r["slots"]) == 0, -(r["years_experience"] or 0)))
    return result
