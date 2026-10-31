"""Phone-only development identity, matching the existing doctor portal."""
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from postgrest.exceptions import APIError
from app import storage
from app.pharmacy import service
from app.consultation.service import ConsultationServiceUnavailable

router = APIRouter(prefix="/api/pharmacy", tags=["pharmacy"])


def run(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except APIError as exc:
        if exc.code == 'P0001':
            raise HTTPException(409, exc.message) from None
        if exc.code == '23514':
            raise HTTPException(409, 'Stock cannot be reduced below the reserved quantity. Refresh the stock list.') from None
        raise HTTPException(503, "Pharmacy database unavailable. Check the Phase 4.1 and 4.3 migrations.") from None
    except storage.StorageError as exc:
        raise HTTPException(503, "Signed consultation storage is unavailable. Please retry.") from exc
    except ConsultationServiceUnavailable:
        raise HTTPException(503, 'Prescription database is unavailable. Please retry.') from None


def pharmacist(pharmacist_id: UUID):
    run(service.require_pharmacist, pharmacist_id)


class IdentifyRequest(BaseModel):
    phone: str = Field(min_length=5, max_length=20)


class StockUpdate(BaseModel):
    quantity: int = Field(strict=True, ge=0, le=2147483647)


@router.post("/identify")
def identify(body: IdentifyRequest):
    return run(service.identify, body.phone)


@router.get("/{pharmacist_id}/stock", dependencies=[Depends(pharmacist)])
def stock(brand: str | None = Query(None, max_length=200),
          specialty: Literal['cardiology', 'orthopedics', 'dermatology', 'gastroenterology'] | None = None,
          composition: str | None = Query(None, max_length=500),
          stock: Literal['in_stock', 'out_of_stock', 'low_stock', 'unknown'] | None = None,
          offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    return run(service.inventory, brand, specialty, composition, stock, offset, limit)


@router.get("/{pharmacist_id}/filters", dependencies=[Depends(pharmacist)])
def filters():
    return run(service.facets)


@router.patch("/{pharmacist_id}/stock/{brand_id}", dependencies=[Depends(pharmacist)])
def update_stock(brand_id: str, body: StockUpdate):
    return run(service.update_stock, brand_id, body.quantity)


@router.get("/{pharmacist_id}/consultations", dependencies=[Depends(pharmacist)])
def consultations(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    return run(service.consultations, offset, limit)


@router.get("/{pharmacist_id}/consultations/{appointment_id}", dependencies=[Depends(pharmacist)])
def consultation(appointment_id: UUID):
    return run(service.consultation_detail, appointment_id)


class ReservationAction(BaseModel):
    action: Literal['release', 'dispense']


@router.post('/{pharmacist_id}/consultations/{appointment_id}/reservation', dependencies=[Depends(pharmacist)])
def resolve_reservation(pharmacist_id: UUID, appointment_id: UUID, body: ReservationAction):
    return run(service.resolve_reservation, appointment_id, pharmacist_id, body.action)
