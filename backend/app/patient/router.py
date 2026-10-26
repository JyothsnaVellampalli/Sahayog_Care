"""FastAPI routes for patient login, registration and appointments (Phase 1.4).

Login is phone + password (dev stage, no OTP). Supabase Auth issues the session
token; the profile row carries name/age/gender/city/role.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.patient import service

router = APIRouter(prefix="/api/patients", tags=["patient"])


class Profile(BaseModel):
    id: str
    phone: str | None = None
    full_name: str | None = None
    email: str | None = None
    age: int | None = None
    gender: str | None = None
    city: str | None = None
    role: str = "patient"


class AuthResponse(BaseModel):
    profile: Profile
    access_token: str
    refresh_token: str | None = None


class LookupRequest(BaseModel):
    phone: str = Field(..., min_length=5, max_length=20)


class LookupResponse(BaseModel):
    exists: bool


class LoginRequest(BaseModel):
    phone: str = Field(..., min_length=5, max_length=20)
    password: str = Field(..., min_length=6, max_length=100)


class RegisterRequest(BaseModel):
    phone: str = Field(..., min_length=5, max_length=20)
    password: str = Field(..., min_length=6, max_length=100)
    full_name: str = Field(..., min_length=1, max_length=120)
    age: int = Field(..., ge=0, le=120)
    gender: Literal["female", "male", "other"]  # mandatory
    email: str = Field(..., min_length=3, max_length=200)
    city: Literal["Pune", "Hyderabad"] | None = None


class ErrorResponse(BaseModel):
    error: str


@router.post("/lookup", response_model=LookupResponse)
def lookup(request: LookupRequest) -> LookupResponse:
    """Check whether a phone number is already registered."""
    return LookupResponse(exists=service.get_patient_by_phone(request.phone) is not None)


@router.post("/login")
def login(request: LoginRequest):
    """Log in an existing patient by phone + password."""
    try:
        result = service.login(request.phone, request.password)
    except service.PatientError as exc:
        return ErrorResponse(error=str(exc))
    except service.PatientServiceUnavailable as exc:
        return ErrorResponse(error=str(exc))
    return AuthResponse(**result)


@router.post("/register")
def register(request: RegisterRequest):
    """Register a new patient and return a session."""
    try:
        result = service.register(
            phone=request.phone,
            password=request.password,
            full_name=request.full_name,
            age=request.age,
            gender=request.gender,
            email=request.email,
            city=request.city,
        )
    except service.PatientError as exc:
        return ErrorResponse(error=str(exc))
    except service.PatientServiceUnavailable as exc:
        return ErrorResponse(error=str(exc))
    return AuthResponse(**result)


class AppointmentOut(BaseModel):
    type: str = "appointment"  # "appointment" or "emergency"
    id: str
    status: str | None = None
    reason: str | None = None
    starts_at: str | None = None
    created_at: str | None = None
    doctor_name: str | None = None
    specialty: str | None = None


class AppointmentsResponse(BaseModel):
    count: int
    appointments: list[AppointmentOut]


@router.get("/{patient_id}/appointments", response_model=AppointmentsResponse)
def appointments(patient_id: str) -> AppointmentsResponse:
    """List a patient's appointments (most recent first)."""
    items = service.list_appointments(patient_id)
    return AppointmentsResponse(
        count=len(items), appointments=[AppointmentOut(**a) for a in items]
    )
