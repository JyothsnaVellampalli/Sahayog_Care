"""Regression tests for the booking intake graph (Phase 1.2 + 1.3).

These use a stub adapter and monkeypatched DB lookups so no network/API key or
live database is needed.
"""

import app.book_appointment.graph as graph_mod
from app.book_appointment.graph import run_intake
from app.book_appointment.model_adapter import DecisionResponse, ModelCallError, OpenRouterAdapter
import pytest
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

    def classify_json(self, system_prompt, user_payload):
        raise AssertionError("Intake must never call a chat/translation model")

    def decisions(self, state, questions):
        self.calls = getattr(self, "calls", 0) + 1
        self.questions = questions
        self.last_state = state
        return {"answers": {
            "triage_category": {"choice": self._triage, "probabilities": self._triage_scores, "confidence": 0.9},
            "doctor_specialty": {"choice": self._specialty, "probabilities": {self._specialty: 1.0}},
        }}

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
    assert resp.specialty.name == "Cardiology"
    assert stub.calls == 1
    assert set(stub.questions) == {"triage_category", "doctor_specialty"}


# --- Phase 1.3: non-emergency booking branch ----------------------------------

def test_normal_lists_specialty_and_doctors(monkeypatch):
    _patch_db(monkeypatch)
    stub = StubJev("Normal", {"Emergency": 0.0, "Severe": 0.1, "Normal": 0.9}, specialty="Cardiology")
    req = IntakeRequest(symptoms=[SymptomDetail(symptom_id="S006")], free_text="palpitations")
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


@pytest.mark.parametrize("text", [
    "mujhe bukhar hai, cough nahi hai",
    "naaku jwaram undi, cough ledu",
    "\u092e\u0941\u091d\u0947 \u092c\u0941\u0916\u093e\u0930 \u0939\u0948",
    "mild cough",
])
def test_original_language_reaches_single_decision(monkeypatch, text):
    _patch_db(monkeypatch)
    stub = StubJev("Severe", {"Severe": 1})
    result = run_intake(IntakeRequest(free_text=text), adapter=stub)
    assert text in stub.last_state
    assert result.deidentified_text == text
    assert stub.calls == 1
    assert set(stub.questions) == {"triage_category", "doctor_specialty"}


def test_decision_failure_has_no_translation_fallback(monkeypatch):
    _patch_db(monkeypatch)
    stub = StubJev("Normal", {"Normal": 1})
    def fail(*args):
        raise ModelCallError("offline")
    monkeypatch.setattr(stub, "decisions", fail)
    result = run_intake(IntakeRequest(free_text="bukhar"), adapter=stub)
    assert result.outcome == "unavailable"


def test_symptom_only_intake_uses_one_decision(monkeypatch):
    _patch_db(monkeypatch)
    stub = StubJev("Normal", {"Normal": 1})
    result = run_intake(IntakeRequest(symptoms=[SymptomDetail(symptom_id="S027")]), adapter=stub)
    assert result.outcome == "booking"
    assert stub.calls == 1


def test_emergency_specialty_persisted_and_failure_visible(monkeypatch):
    from app.patient import service
    _patch_db(monkeypatch)
    monkeypatch.setattr(service, "get_patient_by_id", lambda _: {})
    saved = []
    monkeypatch.setattr(service, "create_emergency_intake", lambda **kw: saved.append(kw) or {"id": "emergency"})
    stub = StubJev("Emergency", {"Emergency": 1})
    request = IntakeRequest(patient_id="patient", free_text="chest pain")
    result = run_intake(request, adapter=stub)
    assert saved[0]["specialty"]["name"] == "Cardiology"
    assert result.outcome == "emergency"
    monkeypatch.setattr(service, "create_emergency_intake", lambda **kw: None)
    result = run_intake(request, adapter=stub)
    assert result.outcome == "emergency"
    assert "could not be saved" in result.note


def test_missing_specialty_preserves_emergency(monkeypatch):
    _patch_db(monkeypatch)
    stub = StubJev("Emergency", {"Emergency": 1})
    monkeypatch.setattr(stub, "decisions", lambda *args: {"answers": {
        "triage_category": {"probabilities": {"Emergency": 1}}}})
    result = run_intake(IntakeRequest(free_text="chest pain"), adapter=stub)
    assert result.outcome == "emergency"
    assert result.specialty is None
    assert result.note
