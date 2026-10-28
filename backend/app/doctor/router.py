"""FastAPI routes for doctor login, registration and signature (Phase 2.1)."""

from __future__ import annotations

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel, Field

from app.doctor import service

router = APIRouter(prefix="/api/doctors", tags=["doctor"])


class DoctorProfile(BaseModel):
    id: str
    doctor_code: str | None = None
    full_name: str | None = None
    phone: str | None = None
    email: str | None = None
    role: str = "doctor"
    has_signature: bool = False


class DoctorAuthResponse(BaseModel):
    """Phone-only sign-in result: just the doctor profile (no session token)."""

    profile: DoctorProfile


class ErrorResponse(BaseModel):
    error: str


class LookupRequest(BaseModel):
    phone: str = Field(..., min_length=5, max_length=20)


class LookupResponse(BaseModel):
    exists: bool


class IdentifyRequest(BaseModel):
    phone: str = Field(..., min_length=5, max_length=20)


@router.post("/lookup", response_model=LookupResponse)
def lookup(request: LookupRequest) -> LookupResponse:
    return LookupResponse(exists=service.get_doctor_by_phone(request.phone) is not None)


@router.post("/identify")
def identify(request: IdentifyRequest):
    """Identify a doctor by phone number (dev-stage: no password, no OTP)."""
    try:
        return DoctorAuthResponse(**service.identify(request.phone))
    except (service.DoctorError, service.DoctorServiceUnavailable) as exc:
        return ErrorResponse(error=str(exc))


class SignatureStatus(BaseModel):
    has_signature: bool


@router.get("/{doctor_id}/signature", response_model=SignatureStatus)
def signature_status(doctor_id: str) -> SignatureStatus:
    return SignatureStatus(has_signature=service.has_signature(doctor_id))


@router.post("/{doctor_id}/signature")
async def upload_signature(doctor_id: str, file: UploadFile = File(...)):
    data = await file.read()
    try:
        result = service.save_signature(
            doctor_id, data, file.content_type or "application/octet-stream"
        )
    except (service.DoctorError, service.DoctorServiceUnavailable) as exc:
        return ErrorResponse(error=str(exc))
    return SignatureStatus(has_signature=result["has_signature"])


