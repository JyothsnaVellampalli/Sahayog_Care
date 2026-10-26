"""Regression tests for the booking intake graph (Phase 1.2 + 1.3).

These use a stub adapter and monkeypatched DB lookups so no network/API key or
live database is needed.
"""

import app.book_appointment.graph as graph_mod
from app.book_appointment.graph import run_intake
from app.book_appointment.model_adapter import DecisionResponse, OpenRouterAdapter
from app.book_appointment.schemas import IntakeRequest, Severity, SymptomDetail

# Shared fake data for the specialty / doctor lookups.
_FAKE_SPECIALTIES = [
    {"id": "sp-card", "code": "CARD", "name": "Cardiology", "description": "Heart"},
    {"id": "sp-gmed", "code": "GMED", "name": "General Medicine", "description": "General"},
]
_FAKE_DOCTORS = [
    {
        "id": "doc-1",
        "doctor_code": "CARD-01",
        "full_name": "Dr. Test",
        "years_experience": 10,
        "languages": ["English"],
        "facility_name": "Clinic A",
        "city": "Pune",
        "slots": [
            {"id": "slot-1", "starts_at": "2026-10-27T03:30:00+00:00", "ends_at": "2026-10-27T04:15:00+00:00"},
        ],
    }
]


class StubJev(OpenRouterAdapter):
    """Canned Jev decisions. Answers triage and specialty questions separately."""

    def __init__(self, triage, triage_scores, specialty="Cardiology"):
        self._triage = triage
        self._triage_scores = triage_scores
        self._specialty = specialty
        self._classifier_model = "typesafe/jev-stub"

    @property
    def classifier_model(self) -> str:
        return self._classifier_model

    def choice_decision(self, state, question_name, instructions, criteria):
        self.last_state = state
        if question_name == "doctor_specialty":
            scores = {name: 0.0 for name in criteria}
            scores[self._specialty] = 1.0
            return DecisionResponse(
                choice=self._specialty, probabilities=scores, confidence=1.0,
                model=self._classifier_model, raw={},
            )
        # triage_category
        return DecisionResponse(
            choice=self._triage, probabilities=self._triage_scores, confidence=0.9,
            model=self._classifier_model, raw={},
        )


def _patch_db(monkeypatch):
    monkeypatch.setattr(graph_mod, "list_specialties", lambda: _FAKE_SPECIALTIES)
    monkeypatch.setattr(
        graph_mod, "doctors_with_slots", lambda specialty_id, limit_per_doctor=5: _FAKE_DOCTORS
    )


# --- Phase 1.2: triage classification -----------------------------------------

def test_highest_weightage_becomes_category(monkeypatch):
    _patch_db(monkeypatch)
    stub = StubJev("Emergency", {"Emergency": 0.82, "Severe": 0.12, "Normal": 0.04})
    req = IntakeRequest(
        symptoms=[SymptomDetail(symptom_id="S019", severity=Severity.severe)],
        free_text="chest pain",
        age=60,
    )
    resp = run_intake(req, adapter=stub)
    assert resp.classification.category.value == "Emergency"
    assert resp.classification.status == "OK"


def test_pii_is_removed_before_model_call(monkeypatch):
    _patch_db(monkeypatch)
    stub = StubJev("Normal", {"Normal": 0.9})
    req = IntakeRequest(free_text="I am Rahul Sharma, phone 9876543210, mild cough")
    run_intake(req, adapter=stub)
    assert "Rahul" not in stub.last_state
    assert "9876543210" not in stub.last_state


def test_no_api_key_degrades_gracefully():
    adapter = OpenRouterAdapter(api_key="")
    req = IntakeRequest(
        symptoms=[SymptomDetail(symptom_id="S027")], free_text="mild cough"
    )
    resp = run_intake(req, adapter=adapter)
    assert resp.classification.status == "UNAVAILABLE"
    assert resp.outcome in ("unavailable", "emergency")  # cannot proceed to booking


# --- Phase 1.3: emergency branch ----------------------------------------------

def test_emergency_ends_without_booking(monkeypatch):
    _patch_db(monkeypatch)
    stub = StubJev("Emergency", {"Emergency": 1.0, "Severe": 0.0, "Normal": 0.0})
    req = IntakeRequest(symptoms=[SymptomDetail(symptom_id="S019")], free_text="chest pain")
    resp = run_intake(req, adapter=stub)
    assert resp.outcome == "emergency"
    assert resp.emergency_message
    assert resp.doctors == []
    assert resp.specialty is None


# --- Phase 1.3: non-emergency booking branch ----------------------------------

def test_normal_lists_specialty_and_doctors(monkeypatch):
    _patch_db(monkeypatch)
    stub = StubJev("Normal", {"Emergency": 0.0, "Severe": 0.1, "Normal": 0.9}, specialty="Cardiology")
    req = IntakeRequest(symptoms=[SymptomDetail(symptom_id="S079")], free_text="palpitations")
    resp = run_intake(req, adapter=stub)
    assert resp.outcome == "booking"
    assert resp.specialty is not None
    assert resp.specialty.name == "Cardiology"
    assert len(resp.doctors) == 1
    assert resp.doctors[0].slots[0].id == "slot-1"
    assert resp.severe_guidance is None  # Normal, not Severe


def test_severe_adds_earliest_slot_guidance(monkeypatch):
    _patch_db(monkeypatch)
    stub = StubJev("Severe", {"Emergency": 0.0, "Severe": 0.8, "Normal": 0.2})
    req = IntakeRequest(symptoms=[SymptomDetail(symptom_id="S045")], free_text="high fever")
    resp = run_intake(req, adapter=stub)
    assert resp.outcome == "booking"
    assert resp.severe_guidance is not None
    assert "earliest" in resp.severe_guidance.lower()
    assert len(resp.doctors) == 1
