"""Pure chunk-building tests; no network, no database."""
from app.search import chunking


def test_appointment_chunk_prefers_symptom_text_over_labels():
    visit = {"id": "a1", "patient_id": "p1", "doctor_id": "d1",
             "symptom_text": "Knee pain for 10 days.", "symptoms": ["Knee pain"]}
    chunks = chunking.chunks_for_appointment(visit)
    assert len(chunks) == 1
    assert chunks[0].chunk_id == "a1:symptom"
    assert chunks[0].chunk_type == "symptom"
    assert chunks[0].text == "Knee pain for 10 days."
    assert chunks[0].patient_id == "p1" and chunks[0].doctor_id == "d1" and chunks[0].appointment_id == "a1"


def test_appointment_chunk_falls_back_to_symptom_labels():
    visit = {"id": "a1", "patient_id": "p1", "symptom_text": "", "symptoms": [{"label": "Fever"}, "Cough"]}
    chunks = chunking.chunks_for_appointment(visit)
    assert chunks[0].text == "Fever, Cough"


def test_appointment_with_no_text_produces_no_chunks():
    assert chunking.chunks_for_appointment({"id": "a1", "symptom_text": "", "symptoms": []}) == []


def test_emergency_intake_chunk_has_no_appointment_id():
    intake = {"id": "i1", "patient_id": "p1", "deidentified_text": "Chest pain, cannot breathe."}
    chunks = chunking.chunks_for_emergency_intake(intake)
    assert len(chunks) == 1
    assert chunks[0].chunk_id == "intake:i1:symptom"
    assert chunks[0].appointment_id is None and chunks[0].doctor_id is None


def test_signed_consultation_one_chunk_per_nonempty_section():
    visit = {"id": "a1", "patient_id": "p1", "doctor_id": "d1"}
    record = {"soap": {"subjective": ["Knee pain for 10 days."], "objective": [],
                       "assessment": ["Possible overuse."], "plan": []}}
    chunks = chunking.chunks_for_signed_consultation(visit, record)
    assert [c.section for c in chunks] == ["subjective", "assessment"]
    assert chunks[0].chunk_id == "a1:soap:subjective"
    assert all(c.chunk_type == "soap" and c.appointment_id == "a1" for c in chunks)


def test_signed_consultation_all_empty_sections_produces_no_chunks():
    visit = {"id": "a1"}
    record = {"soap": {"subjective": [], "objective": [], "assessment": [], "plan": []}}
    assert chunking.chunks_for_signed_consultation(visit, record) == []


def test_report_chunk_uses_visit_metadata_not_report_row():
    report_row = {"id": "r1", "appointment_id": "a1"}
    visit = {"id": "a1", "patient_id": "p1", "doctor_id": "d1"}
    chunks = chunking.chunks_for_report(report_row, visit, "Blood test: Hemoglobin 13.5 g/dL")
    assert len(chunks) == 1
    assert chunks[0].chunk_id == "report:r1"
    assert chunks[0].patient_id == "p1" and chunks[0].doctor_id == "d1" and chunks[0].appointment_id == "a1"


def test_report_chunk_with_no_text_produces_no_chunks():
    assert chunking.chunks_for_report({"id": "r1"}, {"id": "a1"}, None) == []
    assert chunking.chunks_for_report({"id": "r1"}, {"id": "a1"}, "   ") == []
