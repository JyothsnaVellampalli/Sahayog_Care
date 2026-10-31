"""Regression coverage for the shared patient/doctor visit record."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app import appointments
from app.consultation import service as doctor
from app.patient import service as patient


class Query:
    def __init__(self, db, table):
        self.db, self.table = db, table
        self.filters, self.changes = [], None

    def select(self, columns):
        self.db.selects.append((self.table, columns))
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def update(self, changes):
        self.changes = changes
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, *args):
        return self

    def gte(self, key, value):
        self.db.bounds.append(("gte", key, value))
        return self

    def lte(self, key, value):
        self.db.bounds.append(("lte", key, value))
        return self

    def execute(self):
        def matches(row):
            for key, value in self.filters:
                current = row
                for part in key.split("."):
                    current = current.get(part) if isinstance(current, dict) else None
                if current != value:
                    return False
            return True
        rows = [row for row in self.db.rows[self.table] if matches(row)]
        if self.changes:
            self.db.writes.append(self.table)
            for row in rows:
                row.update(self.changes)
        return SimpleNamespace(data=deepcopy(rows))


@pytest.fixture
def database(monkeypatch):
    class Database:
        def table(self, name):
            assert name != "consultations", "No duplicated consultation records"
            return Query(self, name)

    db = Database()
    db.selects, db.writes, db.bounds = [], [], []
    db.rows = {
        "appointments": [{
            "id": "visit", "patient_id": "patient", "status": "BOOKED",
            "reason": "General Medicine - Severe", "severity": "Severe",
            "symptoms": [{"id": "S001", "label": "Headache", "duration_days": 2}],
            "symptom_text": "Symptoms since yesterday", "created_at": "2026-10-28",
            "patients": {"full_name": "Test Patient", "age": 42, "gender": "female"},
            "slots": {"doctor_id": "doctor", "starts_at": "2026-10-29T10:00:00Z",
                      "doctors": {"full_name": "Test Doctor", "specialties": {"name": "General Medicine"}}},
        }],
        "emergency_intakes": [{
            "id": "emergency", "patient_id": "patient", "is_met": False,
            "created_at": "2026-10-20", "symptoms": [{"label": "Chest pain"}],
            "patients": {"full_name": "Test Patient", "age": 42, "gender": "female"},
        }],
    }
    monkeypatch.setattr(doctor, "_admin", lambda: db)
    monkeypatch.setattr(patient, "_admin", lambda: db)
    return db


def test_both_portals_use_same_id_and_pending_emergencies_first(database):
    patient_rows = patient.list_appointments("patient")
    doctor_rows = doctor.list_consultations("doctor")
    assert [r["id"] for r in patient_rows] == ["emergency", "visit"]
    assert [r["id"] for r in doctor_rows] == ["emergency", "visit"]
    assert doctor_rows[1]["status"] == "SCHEDULED"
    assert doctor_rows[1]["symptoms"] == ["Headache"]
    assert doctor_rows[1]["patient_age"] == 42
    assert doctor.get_consultation("visit")["symptom_text"] == "Symptoms since yesterday"
    assert database.writes == []


def test_start_updates_patient_visible_status_and_preserves_start_time(database):
    doctor.start_consultation("visit", True)
    started_at = database.rows["appointments"][0]["started_at"]
    doctor.start_consultation("visit", True)
    assert database.rows["appointments"][0]["started_at"] == started_at
    assert patient.list_appointments("patient")[1]["status"] == "IN_PROGRESS"
    assert database.writes == ["appointments"]


@pytest.mark.parametrize("status", ["CANCELLED", "COMPLETED", "NO_SHOW"])
def test_terminal_visits_cannot_restart(database, status):
    database.rows["appointments"][0]["status"] = status
    with pytest.raises(doctor.ConsultationError):
        doctor.start_consultation("visit", True)
    assert database.writes == []


def test_scope_filters_and_handled_emergency_disappears(database):
    database.rows["emergency_intakes"][0]["is_met"] = True
    assert doctor.list_consultations("other-doctor") == []
    assert patient.list_appointments("other-patient") == []
    assert len(doctor.list_consultations("doctor", "from", "to", "SCHEDULED")) == 1
    assert database.bounds == [("gte", "slots.starts_at", "from"), ("lte", "slots.starts_at", "to")]


def test_storage_uses_shared_id_and_missing_links_return_none(database):
    assert doctor.storage_id("visit") == "visit"
    assert doctor.get_consultation("old-visit") is None


def test_consent_and_existing_visit_required(database):
    with pytest.raises(doctor.ConsultationError):
        doctor.start_consultation("visit", False)
    with pytest.raises(doctor.ConsultationError):
        doctor.start_consultation("missing", True)
    assert database.writes == []


def test_booking_uses_single_transaction_with_full_context():
    calls = []
    class Database:
        def rpc(self, name, params):
            calls.append((name, params))
            return SimpleNamespace(execute=lambda: SimpleNamespace(data={"id": "visit"}))
    assert appointments.book(Database(), "patient", "slot", "reason", "retry-key",
                             [{"label": "Headache"}], "Severe", "History") == {"id": "visit"}
    assert calls[0][0] == "book_appointment"
    assert calls[0][1]["p_symptoms"] == [{"label": "Headache"}]
    assert calls[0][1]["p_symptom_text"] == "History"
    assert calls[0][1]["p_idempotency_key"] == "retry-key"


def test_manual_assignment_passes_intake_to_transaction():
    calls = []
    class Database:
        def rpc(self, name, params):
            calls.append(params)
            return SimpleNamespace(execute=lambda: SimpleNamespace(data={"id": "visit"}))
    appointments.book(Database(), "patient", "slot", "Emergency", "retry-key",
                      emergency_intake_id="intake")
    assert calls[0]["p_emergency_intake_id"] == "intake"
    assert calls[0]["p_patient_id"] == "patient"
    assert calls[0]["p_slot_id"] == "slot"
