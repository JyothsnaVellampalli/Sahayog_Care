"""FastAPI routes for patient login, registration and appointments (Phase 1.4).

Login is phone + password (dev stage, no OTP). Supabase Auth issues the session
token; the profile row carries name/age/gender/city/role.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Header, HTTPException
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


def _verify_patient(patient_id: str, authorization: str | None):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Please sign in again.")
    try:
        user = service._require_admin().auth.get_user(authorization[7:]).user
    except Exception:
        raise HTTPException(401, "Please sign in again.") from None
    profile = service.get_patient_by_id(patient_id)
    if not user or not profile or profile.get("auth_user_id") != user.id:
        raise HTTPException(403, "This patient profile is not available.")


@router.get("/{patient_id}/appointments/{appointment_id}")
def appointment_detail(patient_id: str, appointment_id: str, authorization: str | None = Header(default=None)):
    _verify_patient(patient_id, authorization)
    from app.storage import StorageError
    try:
        result = service.appointment_detail(patient_id, appointment_id)
    except (service.PatientServiceUnavailable, StorageError):
        raise HTTPException(503, "Appointment details are temporarily unavailable. Please retry.") from None
    if result is None:
        raise HTTPException(404, "Appointment not found.")
    return result


from app.book_appointment.schemas import SymptomDetail


class AppointmentDetailsUpdate(BaseModel):
    symptoms: list[SymptomDetail] = Field(max_length=200)
    history: str = Field(default="", max_length=4000)


@router.put("/{patient_id}/appointments/{appointment_id}")
def update_appointment_details(patient_id: str, appointment_id: str, request: AppointmentDetailsUpdate,
                               authorization: str | None = Header(default=None)):
    _verify_patient(patient_id, authorization)
    from app.book_appointment.catalogue import valid_symptom_ids, label_for
    from app.book_appointment.deidentify import deidentify
    allowed = valid_symptom_ids()
    if any(s.symptom_id not in allowed for s in request.symptoms):
        raise HTTPException(422, "Select symptoms from the catalogue.")
    symptoms = [{"id": s.symptom_id, "label": label_for(s.symptom_id),
                 "severity": s.severity.value if s.severity else "unknown",
                 "duration_days": s.duration_days} for s in request.symptoms]
    rows = service._require_admin().table("appointments").update({
        "symptoms": symptoms, "history": deidentify(request.history).text,
    }).eq("patient_id", patient_id).eq("id", appointment_id).eq("status", "BOOKED").execute().data
    if not rows:
        raise HTTPException(409, "Only a scheduled appointment can be edited. Reload to see its latest status.")
    return {"ok": True}
