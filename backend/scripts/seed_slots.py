"""Seed synthetic appointment slots for development (Phase 1.3).

The schema seeds specialties, hospitals and doctors but no slots, so the
booking flow has nothing to offer. This script generates OPEN slots for every
active doctor across the next few days during clinic hours.

All slots are synthetic development data (PRD section 10). Idempotent: it skips
(doctor, starts_at) pairs that already exist via the unique constraint.

Run from the repo root or backend/ with the backend venv:
    python backend/scripts/seed_slots.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]

# Clinic schedule for the synthetic data.
DAYS_AHEAD = 7          # generate slots for the next 7 days
START_HOUR = 9          # 09:00
END_HOUR = 17           # last slot ends by 17:00
SLOT_MINUTES = 45
SKIP_WEEKDAYS = {6}     # 6 = Sunday (Mon=0 .. Sun=6)
# Use IST (UTC+5:30) wall-clock for clinic hours, stored as timestamptz.
IST = timezone(timedelta(hours=5, minutes=30))


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(BACKEND_DIR / ".env")


def _day_slots(day: datetime) -> list[tuple[datetime, datetime]]:
    """Return (start, end) pairs for one clinic day."""
    slots = []
    cursor = day.replace(hour=START_HOUR, minute=0, second=0, microsecond=0)
    end_of_day = day.replace(hour=END_HOUR, minute=0, second=0, microsecond=0)
    step = timedelta(minutes=SLOT_MINUTES)
    while cursor + step <= end_of_day:
        slots.append((cursor, cursor + step))
        cursor += step
    return slots


def main() -> int:
    _load_env()
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
    if not url or not key:
        print("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set.", file=sys.stderr)
        return 1

    from supabase import create_client

    client = create_client(url, key)

    doctors = (
        client.table("doctors").select("id").eq("is_active", True).execute().data
    )
    if not doctors:
        print("No active doctors found; nothing to seed.", file=sys.stderr)
        return 1

    # Build the clinic days (starting tomorrow in IST).
    now_ist = datetime.now(IST)
    days = []
    d = now_ist + timedelta(days=1)
    while len(days) < DAYS_AHEAD:
        if d.weekday() not in SKIP_WEEKDAYS:
            days.append(d)
        d += timedelta(days=1)

    rows = []
    for doc in doctors:
        for day in days:
            for start, end in _day_slots(day):
                rows.append(
                    {
                        "doctor_id": doc["id"],
                        "starts_at": start.astimezone(timezone.utc).isoformat(),
                        "ends_at": end.astimezone(timezone.utc).isoformat(),
                        "status": "OPEN",
                    }
                )

    # Upsert in batches; conflict on the (doctor_id, starts_at) unique constraint.
    inserted = 0
    batch = 500
    for i in range(0, len(rows), batch):
        chunk = rows[i : i + batch]
        client.table("slots").upsert(
            chunk, on_conflict="doctor_id,starts_at", ignore_duplicates=True
        ).execute()
        inserted += len(chunk)

    print(f"Seeded up to {inserted} synthetic OPEN slots for {len(doctors)} doctors.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
