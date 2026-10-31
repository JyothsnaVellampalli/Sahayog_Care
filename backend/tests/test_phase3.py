"""Phase 3 catalogue, intake routing and booking contract regressions."""
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.book_appointment import catalogue, db, router
from app.book_appointment.graph import run_intake
from app.book_appointment.schemas import IntakeRequest, SymptomDetail
from test_intake_graph import StubJev, _patch_db


def test_catalogue_has_four_specialties_and_full_severity_range():
    symptoms = catalogue.load_symptoms()
    assert len(symptoms) == 132
    for specialty in catalogue.SPECIALTY_CODES:
        assert {s['severity'] for s in symptoms if s['specialty'] == specialty} == {
            'mild', 'moderate', 'severe', 'emergency'}
    response = router.list_symptoms()
    assert response.symptoms[0].severity == 'emergency'
    assert response.symptoms[0].specialty == 'cardiology'


@pytest.mark.parametrize('symptom_id,category,outcome', [
    ('S001', 'Emergency', 'emergency'), ('S003', 'Severe', 'booking'),
    ('S006', 'Normal', 'booking'), ('S007', 'Normal', 'booking'),
    ('S033', 'Emergency', 'emergency'), ('S070', 'Emergency', 'emergency'),
    ('S115', 'Emergency', 'emergency'),
])
def test_catalogue_cannot_be_downgraded(monkeypatch, symptom_id, category, outcome):
    _patch_db(monkeypatch)
    result = run_intake(IntakeRequest(symptoms=[SymptomDetail(symptom_id=symptom_id, severity='mild')]),
                        adapter=StubJev('Normal', {'Normal': 1}))
    assert result.classification.category.value == category
    assert result.outcome == outcome
    assert result.symptoms[0]['severity'] == catalogue.symptom_index()[symptom_id]['severity']
    if outcome == 'emergency':
        assert result.doctors == []


def test_text_only_and_out_of_scope_do_not_force_specialty(monkeypatch):
    _patch_db(monkeypatch)
    result = run_intake(IntakeRequest(free_text='symptoms outside supported specialties'),
                        adapter=StubJev('Normal', {'Normal': 1}, 'Outside supported specialties'))
    assert result.specialty is None
    assert result.doctors == []


def test_insufficient_information_never_offers_slots(monkeypatch):
    _patch_db(monkeypatch)
    result = run_intake(IntakeRequest(free_text='unwell'),
                        adapter=StubJev('Need more information', {'Need more information': 1}))
    assert result.outcome == 'unavailable'
    assert result.doctors == []


@pytest.mark.parametrize('payload', [IntakeRequest(free_text='  '),
    IntakeRequest(symptoms=[SymptomDetail(symptom_id='old-invalid')])])
def test_api_rejects_empty_or_unknown_symptoms(payload):
    with pytest.raises(HTTPException) as error:
        router.appointment_intake(payload)
    assert error.value.status_code == 422


def test_specialties_are_filtered_without_deleting_doctors(monkeypatch):
    rows = [{'code': code} for code in ['CARD', 'ORTH', 'DERM', 'GAST', 'GMED', 'NEUR']]
    class Query:
        def table(self, *args): return self
        def select(self, *args): return self
        def order(self, *args): return self
        def execute(self): return SimpleNamespace(data=rows)
    monkeypatch.setattr(db, '_client', Query)
    assert {s['code'] for s in db.list_specialties()} == set(catalogue.SPECIALTY_CODES.values())


def test_booking_carries_specialty_and_canonical_metadata(monkeypatch):
    saved = []
    monkeypatch.setattr(router.patient_service, 'create_appointment',
                        lambda **kw: saved.append(kw) or {'id': 'visit', 'status': 'BOOKED'})
    specialty_id = uuid4()
    router.book_appointment_slot(router.BookSlotRequest(
        slot_id=uuid4(), patient_id=uuid4(), idempotency_key=uuid4(), specialty_id=specialty_id,
        symptoms=[{'id': 'S003', 'label': 'forged', 'severity': 'mild'}],
        symptom_text='Chest tightness', severity='Normal'))
    assert saved[0]['specialty_id'] == str(specialty_id)
    assert saved[0]['symptom_text'] == 'Chest tightness'
    assert saved[0]['severity'] == 'Severe'
    assert saved[0]['symptoms'][0]['label'] == catalogue.symptom_index()['S003']['label']


def test_booking_cannot_bypass_selected_emergency():
    with pytest.raises(HTTPException):
        router.book_appointment_slot(router.BookSlotRequest(
            slot_id=uuid4(), patient_id=uuid4(), idempotency_key=uuid4(),
            symptoms=[{'id': 'S001'}], severity='Normal'))
