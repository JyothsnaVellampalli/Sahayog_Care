"""Chat tool tests: every tool is bound to one patient_id with no way for
the model to override it, and ownership filtering is preserved."""
from app.chat.tools import build_tools


def _tool(tools, name):
    return next(t for t in tools if t.name == name)


def test_tools_have_no_patient_id_parameter(monkeypatch):
    """The model can never supply a patient_id -- it isn't in any tool's
    schema, so there is no argument through which it could be overridden."""
    tools = build_tools("patient-1")
    for t in tools:
        assert "patient_id" not in t.args


def test_search_my_records_is_bound_to_the_given_patient(monkeypatch):
    captured = {}
    def fake_candidate_filters(patient_id):
        captured["patient_id"] = patient_id
        return {}, {}
    def fake_plan_query(query, doctors, appointments):
        return "plan"
    def fake_search_chunks(query, patient_id, plan):
        captured["search_patient_id"] = patient_id
        return [{"chunk_id": "c1", "text": "knee pain"}]
    import app.search.retrieval as retrieval
    import app.search.search as search
    monkeypatch.setattr(retrieval, "candidate_filters", fake_candidate_filters)
    monkeypatch.setattr(retrieval, "plan_query", fake_plan_query)
    monkeypatch.setattr(search, "search_chunks", fake_search_chunks)

    tools = build_tools("patient-1")
    result = _tool(tools, "search_my_records").invoke(
        {"name": "search_my_records", "args": {"query": "pain"}, "id": "call_1", "type": "tool_call"})
    assert captured["patient_id"] == "patient-1"
    assert captured["search_patient_id"] == "patient-1"
    assert result.artifact == [{"chunk_id": "c1", "text": "knee pain"}]


def test_list_my_appointments_is_bound_to_the_given_patient(monkeypatch):
    captured = {}
    def fake_list_appointments(patient_id):
        captured["patient_id"] = patient_id
        return [{"id": "a1", "type": "appointment", "status": "COMPLETED",
                "starts_at": "2026-01-01", "doctor_name": "Dr. X", "specialty": "Cardiology"}]
    import app.patient.service as patient_service
    monkeypatch.setattr(patient_service, "list_appointments", fake_list_appointments)

    tools = build_tools("patient-1")
    result = _tool(tools, "list_my_appointments").invoke({})
    assert captured["patient_id"] == "patient-1"
    assert result == [{"id": "a1", "type": "appointment", "status": "COMPLETED",
                       "starts_at": "2026-01-01", "doctor_name": "Dr. X", "specialty": "Cardiology"}]


def test_get_appointment_details_only_returns_this_patients_own_visit(monkeypatch):
    """appointment_detail() already filters by patient_id internally -- an id
    belonging to another patient returns None, which the tool turns into a
    clear 'not found' rather than ever returning someone else's data."""
    def fake_appointment_detail(patient_id, appointment_id):
        assert patient_id == "patient-1"
        return None  # as if this appointment belongs to a different patient
    import app.patient.service as patient_service
    monkeypatch.setattr(patient_service, "appointment_detail", fake_appointment_detail)

    tools = build_tools("patient-1")
    result = _tool(tools, "get_appointment_details").invoke({"appointment_id": "someone-elses-appt"})
    assert "error" in result
