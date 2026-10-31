"""Postgres-backed stock and completed, signed visits for the pharmacy portal."""
from datetime import datetime, timezone, timedelta
from functools import lru_cache

from fastapi import HTTPException
from app.config import settings
from app.consultation.finalization import signed_record


@lru_cache(maxsize=1)
def _admin():
    if not settings.supabase_configured:
        raise HTTPException(503, "Pharmacy database is not configured.")
    from supabase import create_client
    return create_client(settings.supabase_url, settings.supabase_service_key)


def identify(phone):
    rows = (_admin().table("pharmacists").select("id,full_name,phone")
            .eq("phone", phone.strip()).eq("is_active", True).limit(1).execute().data)
    if not rows:
        raise HTTPException(404, "No active pharmacist found for this phone number.")
    return {"profile": {**rows[0], "role": "pharmacist"}}


def require_pharmacist(pharmacist_id):
    rows = (_admin().table("pharmacists").select("id")
            .eq("id", str(pharmacist_id)).eq("is_active", True).limit(1).execute().data)
    if not rows:
        raise HTTPException(404, "Active pharmacist not found. Sign in again.")


def inventory(brand=None, specialty=None, composition=None, stock=None, offset=0, limit=50):
    query = _admin().table("pharmacy_brands").select(
        "brand_id,brand,manufacturer,variant,source_status,stock_quantity,locked_quantity,available_quantity,stock_is_demo,"
        "stock_updated_at,pharmacy_medicines!inner(id,generic_name,specialty,composition)", count="exact")
    if brand:
        query = query.eq("brand", brand)
    if specialty:
        query = query.eq("pharmacy_medicines.specialty", specialty)
    if composition:
        query = query.eq("pharmacy_medicines.composition", composition)
    if stock == "in_stock":
        query = query.gt("available_quantity", 0)
    elif stock == "out_of_stock":
        query = query.eq("available_quantity", 0)
    elif stock == "low_stock":
        query = query.gt("available_quantity", 0).lte("available_quantity", 10)
    elif stock == "unknown":
        query = query.is_("available_quantity", "null")
    result = query.order("brand").order("brand_id").range(offset, offset + limit - 1).execute()
    return {"items": result.data or [], "total": result.count or 0}


def facets():
    # Page through the DB so filter options cannot be silently truncated at its row limit.
    rows = []
    for offset in range(0, 100000, 500):
        batch = (_admin().table("pharmacy_brands").select(
            "brand,pharmacy_medicines!inner(specialty,composition)")
            .order("brand_id").range(offset, offset + 499).execute().data or [])
        rows.extend(batch)
        if len(batch) < 500:
            break
    return {"brands": sorted({r["brand"] for r in rows}),
            "specialties": sorted({r["pharmacy_medicines"]["specialty"] for r in rows}),
            "compositions": sorted({r["pharmacy_medicines"]["composition"] for r in rows})}


def update_stock(brand_id, quantity):
    rows = (_admin().table("pharmacy_brands").update({"stock_quantity": quantity,
            "stock_is_demo": False, "stock_updated_at": datetime.now(timezone.utc).isoformat()})
            .eq("brand_id", brand_id).execute().data)
    if not rows:
        raise HTTPException(404, "Brand not found.")
    return {"brand_id": brand_id, "stock_quantity": quantity}


def consultations(offset=0, limit=50):
    result = (_admin().table("appointments").select(
        "id,completed_at,patients(full_name),slots(doctors(full_name)),"
        "pharmacy_reservations(brand_id,medicine_id,quantity,status)", count="exact")
        .eq("status", "COMPLETED").not_.is_("finalised_record_key", "null")
        .order("completed_at", desc=True).order("id").range(offset, offset + limit - 1).execute())
    return {"items": [{**row, **reservation_status(row)} for row in result.data or []], "total": result.count or 0}


def consultation_detail(appointment_id):
    rows = (_admin().table("appointments").select("id,finalised_record_key,completed_at,patients(full_name),"
            "pharmacy_reservations(brand_id,medicine_id,quantity,status,resolved_at)")
            .eq("id", str(appointment_id)).eq("status", "COMPLETED")
            .not_.is_("finalised_record_key", "null").limit(1).execute().data)
    if not rows:
        raise HTTPException(404, "Signed consultation not found.")
    record = signed_record(rows[0])
    # Only the frozen summary/signature are needed here; never return transcript or object keys.
    return {"id": rows[0]["id"], "patient_name": (rows[0].get("patients") or {}).get("full_name"),
            **reservation_status(rows[0]),
            'prescription': record.get('prescription', []),
            **{key: record.get(key) for key in ("soap", "signature", "doctor_name", "signed_at")}}


def reservation_status(visit):
    reservations = visit.get('pharmacy_reservations') or []
    statuses = {row['status'] for row in reservations}
    status = 'LOCKED' if 'LOCKED' in statuses else next(iter(statuses), 'NONE')
    completed = visit.get('completed_at')
    unlock_at = datetime.fromisoformat(completed.replace('Z', '+00:00')) + timedelta(hours=24) if completed and status == 'LOCKED' else None
    return {'reservation_status': status, 'reservations': reservations,
            'release_available_at': unlock_at.isoformat() if unlock_at else None,
            'can_unlock': bool(unlock_at and datetime.now(timezone.utc) >= unlock_at)}


def resolve_reservation(appointment_id, pharmacist_id, action):
    return _admin().rpc('resolve_pharmacy_reservation', {
        'p_appointment_id': str(appointment_id), 'p_pharmacist_id': str(pharmacist_id),
        'p_action': action,
    }).execute().data
