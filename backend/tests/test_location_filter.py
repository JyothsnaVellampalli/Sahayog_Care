"""Location matching never broadens a patient's search to other cities."""
from app.book_appointment import db, graph
from app.book_appointment.schemas import IntakeRequest
from app.patient import service


def doctors():
    return [dict(id=str(i), doctor_code=str(i), full_name=f"Doctor {i}", years_experience=10,
                 hospitals={"city": city, "name": "Clinic"})
            for i, city in enumerate(["Pune", "Hyderabad", " PUNE  ", None])]


def test_city_filters_before_slot_lookup(monkeypatch):
    monkeypatch.setattr(db, "doctors_by_specialty", lambda _: doctors())
    requested = []
    def slots(ids, **kwargs):
        requested.extend(ids)
        return {i: [] for i in ids}
    monkeypatch.setattr(db, "open_slots_for_doctors", slots)
    result = db.doctors_with_slots("specialty", city=" pune ")
    assert {d["id"] for d in result} == {"0", "2"}
    assert set(requested) == {"0", "2"}


def test_unmatched_city_does_not_return_other_locations(monkeypatch):
    monkeypatch.setattr(db, "doctors_by_specialty", lambda _: doctors())
    monkeypatch.setattr(db, "open_slots_for_doctors", lambda *a, **k: (_ for _ in ()).throw(AssertionError("No slot query expected")))
    assert db.doctors_with_slots("specialty", city="Mumbai") == []


def test_profile_city_is_used(monkeypatch):
    monkeypatch.setattr(service, "get_patient_by_id", lambda _: {"city": "Hyderabad"})
    calls = []
    monkeypatch.setattr(graph, "doctors_with_slots", lambda *a, **kw: calls.append(kw) or [])
    graph._find_doctors({"request": IntakeRequest(patient_id="patient"), "specialty": {"id": "specialty"}})
    assert calls == [{"limit_per_doctor": 5, "city": "Hyderabad"}]


def test_missing_profile_city_stops_local_search(monkeypatch):
    monkeypatch.setattr(service, "get_patient_by_id", lambda _: {"city": "  "})
    monkeypatch.setattr(graph, "doctors_with_slots", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("No search expected")))
    result = graph._find_doctors({"request": IntakeRequest(patient_id="patient"), "specialty": {"id": "specialty"}})
    assert result["doctors"] == []
    assert "city" in result["note"]


def test_profile_lookup_failure_does_not_broaden_search(monkeypatch):
    monkeypatch.setattr(service, "get_patient_by_id", lambda _: (_ for _ in ()).throw(RuntimeError("offline")))
    result = graph._find_doctors({"request": IntakeRequest(patient_id="patient"), "specialty": {"id": "specialty"}})
    assert result["doctors"] == []
    assert "try again" in result["note"]
