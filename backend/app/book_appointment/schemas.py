"""Pydantic schemas for the booking intake flow.

PRD section 9: validate every external input with Pydantic at the boundary, and
never trust a model's output shape without validation. These models are used at
both the API boundary and the graph boundary.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Severity(str, Enum):
    mild = "mild"
    moderate = "moderate"
    severe = "severe"


class Category(str, Enum):
    emergency = "Emergency"
    severe = "Severe"
    normal = "Normal"
    needs_more_info = "Need more information"


class SymptomDetail(BaseModel):
    """One symptom the patient selected, with the UI-captured detail."""

    symptom_id: str = Field(..., description="Catalogue id, e.g. S019")
    severity: Severity | None = None
    duration_days: int | None = Field(
        default=None, ge=0, le=3650, description="Duration in days, if provided"
    )


class IntakeRequest(BaseModel):
    """What the patient submits from the Book-an-appointment form.

    From Phase 1.4, age and sex are taken from the logged-in patient's profile
    (via ``patient_id``) rather than being asked on the form. The ``age``/``sex``
    fields remain so the flow still works for anonymous/legacy callers, but the
    patient record takes precedence when ``patient_id`` is present.
    """

    symptoms: list[SymptomDetail] = Field(default_factory=list)
    free_text: str | None = Field(
        default=None, max_length=4000, description="Optional free-text detail"
    )
    patient_id: str | None = Field(default=None, description="Logged-in patient id")
    age: int | None = Field(default=None, ge=0, le=120)
    sex: Literal["female", "male", "other", "unknown"] | None = None
    pregnant: bool | None = None

    @field_validator("free_text")
    @classmethod
    def _strip_text(cls, v: str | None) -> str | None:
        return v.strip() if isinstance(v, str) else v


class Classification(BaseModel):
    """Result of the Jev decisions classifier.

    Jev is a decision model, not a chat model: it returns a chosen category plus
    a probability (weightage) for each category, and no natural-language
    reasoning. We pick ``category`` as the highest-weighted option.

    Attributes:
        status: "OK" when the classifier ran, "UNAVAILABLE" when it could not
            (e.g. no API key). There is no patient follow-up at this stage.
        category: the winning category (highest weightage), or None if
            unavailable.
        scores: category -> weightage (probability 0..1). The basis for the
            decision; the UI/doctor can see the full distribution.
        confidence: how concentrated the distribution is (0..1), if provided.
    """

    status: Literal["OK", "UNAVAILABLE"]
    category: Category | None = None
    scores: dict[str, float] = Field(default_factory=dict)
    confidence: float | None = None


class SpecialtyMatch(BaseModel):
    """The specialty chosen by the Jev specialty decision (Phase 1.3)."""

    id: str | None = None
    code: str | None = None
    name: str | None = None
    scores: dict[str, float] = Field(default_factory=dict)
    confidence: float | None = None


class SlotOut(BaseModel):
    """One open appointment slot offered to the patient."""

    id: str
    starts_at: str
    ends_at: str


class DoctorOut(BaseModel):
    """A doctor in the matched specialty, with their earliest open slots."""

    id: str
    doctor_code: str
    full_name: str
    years_experience: int | None = None
    languages: list[str] = Field(default_factory=list)
    facility_name: str | None = None
    city: str | None = None
    slots: list[SlotOut] = Field(default_factory=list)


class IntakeResponse(BaseModel):
    """What the intake endpoint returns to the frontend.

    Phase 1.3 adds the triage outcome branch:
      - ``outcome`` is "emergency", "booking", or "unavailable".
      - For an emergency, ``emergency_message`` is set and no doctors are listed.
      - For a non-emergency, ``specialty`` + ``doctors`` (with slots) are set so
        the patient can choose a doctor and slot. ``severe_guidance`` is set when
        the condition is Severe.
    """

    classification: Classification
    symptoms: list[dict] = Field(default_factory=list)
    deidentified_text: str = ""
    removed_identifiers: dict[str, int] = Field(default_factory=dict)
    model: str | None = None
    note: str | None = None

    # Phase 1.3 outputs.
    outcome: Literal["emergency", "booking", "unavailable"] = "unavailable"
    emergency_message: str | None = None
    severe_guidance: str | None = None
    specialty: SpecialtyMatch | None = None
    doctors: list[DoctorOut] = Field(default_factory=list)
