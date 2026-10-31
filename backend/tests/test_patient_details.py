"""Patient detail endpoints release only signed records and enforce ownership."""
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app.patient import router, service
from pydantic import ValidationError


def test_profile_updates_only_allowed_fields(monkeypatch):
    query = Query([{"id": "patient", "full_name": "New Name", "city": "Hyderabad"}])
    monkeypatch.setattr(router, "_verify_patient", lambda *a: {"id": "patient"})
    monkeypatch.setattr(service, "_require_admin", lambda: query)
    result = router.update_profile("patient", router.ProfileUpdate(full_name="  New Name  ", city="Hyderabad"))
    assert query.payload == {"full_name": "New Name", "city": "Hyderabad"}
    assert ("id", "patient") in query.filters
    assert result["city"] == "Hyderabad"


@pytest.mark.parametrize("payload", [
    {"full_name": " ", "city": "Pune"},
    {"full_name": "Name", "city": "Mumbai"},
    {"full_name": "Name", "city": "Pune", "role": "doctor"},
])
def test_profile_rejects_invalid_edits(payload):
    with pytest.raises(ValidationError):
        router.ProfileUpdate(**payload)


def test_profile_requires_authentication():
    with pytest.raises(HTTPException) as exc:
        router.patient_profile("patient", None)
    assert exc.value.status_code == 401


class Query:
    def __init__(self, rows):
        self.rows, self.filters = rows, []
    def table(self, *args): return self
    def select(self, *args): return self
    def update(self, payload):
        self.payload = payload
        return self
    def eq(self, *args):
        self.filters.append(args)
        return self
    def limit(self, *args): return self
    def execute(self): return SimpleNamespace(data=self.rows)


def test_detail_is_scoped_and_unsigned_notes_are_hidden(monkeypatch):
    query = Query([{"id": "visit", "status": "BOOKED", "finalised_record_key": "draft", "symptoms": [], "slots": {}}])
    monkeypatch.setattr(service, "_require_admin", lambda: query)
    result = service.appointment_detail("patient", "visit")
    assert result["soap"] is None
    assert "finalised_record_key" not in result
    assert ("patient_id", "patient") in query.filters
    assert ("id", "visit") in query.filters


def test_completed_detail_reads_signed_snapshot(monkeypatch):
    from app.consultation import finalization
    query = Query([{"id": "visit", "status": "COMPLETED", "finalised_record_key": "signed", "slots": {}}])
    monkeypatch.setattr(service, "_require_admin", lambda: query)
    monkeypatch.setattr(finalization, "signed_record", lambda _: {"soap": {"assessment": ["Reviewed"]}, "doctor_name": "Doctor", "signed_at": "today"})
    result = service.appointment_detail("patient", "visit")
    assert result["soap"]["assessment"] == ["Reviewed"]
    assert result["signed_by"] == "Doctor"


def test_detail_rejects_missing_token():
    with pytest.raises(HTTPException) as exc:
        router._verify_patient("patient", None)
    assert exc.value.status_code == 401


def test_detail_rejects_other_patient(monkeypatch):
    client = SimpleNamespace(auth=SimpleNamespace(get_user=lambda _: SimpleNamespace(user=SimpleNamespace(id="other"))))
    monkeypatch.setattr(service, "_require_admin", lambda: client)
    monkeypatch.setattr(service, "get_patient_by_id", lambda _: {"auth_user_id": "owner"})
    with pytest.raises(HTTPException) as exc:
        router._verify_patient("patient", "Bearer token")
    assert exc.value.status_code == 403


def test_edit_is_atomic_and_only_for_booked_visits(monkeypatch):
    query = Query([])
    monkeypatch.setattr(router, "_verify_patient", lambda *a: None)
    monkeypatch.setattr(service, "_require_admin", lambda: query)
    with pytest.raises(HTTPException) as exc:
        router.update_appointment_details("patient", "visit", router.AppointmentDetailsUpdate(symptoms=[], symptom_text=""))
    assert exc.value.status_code == 409
    assert ("patient_id", "patient") in query.filters
    assert ("id", "visit") in query.filters
    assert ("status", "BOOKED") in query.filters
