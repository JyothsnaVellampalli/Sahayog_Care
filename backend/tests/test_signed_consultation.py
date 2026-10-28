from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import storage
from app.consultation import finalization, router, service, soap


@pytest.fixture
def visit(monkeypatch):
    monkeypatch.setattr(finalization.settings, "show_speech_transcripts", True)
    state = {"id": "visit", "doctor_id": "doctor", "status": "IN_PROGRESS",
             "consent_recorded": True}
    objects = {"signatures/doctor.png": b"signature",
               "soap/visit.json": {"subjective": ["Original"], "objective": [], "assessment": [], "plan": []},
               "transcripts/visit.json": {"segments": [{"text": "Original"}]}}
    monkeypatch.setattr(service, "get_consultation", lambda _: dict(state))
    monkeypatch.setattr(finalization.doctor_service, "get_doctor_by_id", lambda _: {
        "full_name": "Doctor", "signature_key": "signatures/doctor.png"})
    monkeypatch.setattr(storage, "get_bytes", lambda key, **_: objects.get(key))
    monkeypatch.setattr(storage, "get_json", lambda key, **_: deepcopy(objects.get(key)))
    monkeypatch.setattr(storage, "put_json", lambda key, value: objects.__setitem__(key, deepcopy(value)))

    class Update:
        def table(self, name):
            assert name == "appointments"
            return self
        def update(self, fields):
            self.fields = fields
            return self
        def eq(self, key, value):
            assert state[key] == value
            return self
        def execute(self):
            state.update(self.fields)
            return SimpleNamespace(data=[dict(state)])
    monkeypatch.setattr(service, "_admin", lambda: Update())
    return state, objects


def draft():
    return soap.SoapDraft(subjective=["Reviewed and edited"], objective=[], assessment=[], plan=[])


def test_close_freezes_edits_transcript_signature_and_retry(visit):
    state, objects = visit
    finalization.close("visit", "doctor", draft())
    assert state["status"] == "COMPLETED"
    key = state["finalised_record_key"]
    assert objects[key]["soap"] == draft().model_dump()
    objects["signatures/doctor.png"] = b"replacement signature"
    objects["transcripts/visit.json"] = {"segments": []}
    objects["soap/visit.json"] = {"subjective": ["later write"]}
    assert router.get_soap("visit")["soap"] == draft().model_dump()
    assert router.get_transcript("visit").segments == [{"text": "Original"}]
    assert router.get_soap("visit")["signature"].endswith("c2lnbmF0dXJl")
    finalization.close("visit", "doctor", draft())
    assert state["finalised_record_key"] == key


def test_failed_storage_does_not_close(visit, monkeypatch):
    def fail(*args):
        raise storage.StorageError("Unavailable")
    monkeypatch.setattr(storage, "put_json", fail)
    with pytest.raises(storage.StorageError):
        finalization.close("visit", "doctor", draft())
    assert visit[0]["status"] == "IN_PROGRESS"


def test_transcripts_excluded_from_snapshot_when_hidden(visit, monkeypatch):
    monkeypatch.setattr(finalization.settings, "show_speech_transcripts", False)
    state, objects = visit
    finalization.close("visit", "doctor", draft())
    record = objects[state["finalised_record_key"]]
    assert "segments" not in record
    assert record["soap"] == draft().model_dump()
    assert record["signature"]
    assert router.get_transcript("visit").segments == []


def test_signature_and_owner_required(visit):
    with pytest.raises(service.ConsultationError):
        finalization.close("visit", "other-doctor", draft())
    del visit[1]["signatures/doctor.png"]
    with pytest.raises(service.ConsultationError):
        finalization.close("visit", "doctor", draft())
    assert visit[0]["status"] == "IN_PROGRESS"


def test_closed_mutation_routes_reject(visit):
    import asyncio
    visit[0]["status"] = "COMPLETED"
    for action in (
        lambda: router.generate_soap("visit"),
        lambda: router.update_soap("visit", draft()),
        lambda: router.append_segment("visit", router.AppendSegmentRequest(text="New note")),
        lambda: router.edit_segment("visit", router.EditSegmentRequest(index=0, text="Changed")),
    ):
        with pytest.raises(HTTPException) as error:
            action()
        assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        asyncio.run(router.transcription_status("visit", "recording"))
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        asyncio.run(router.transcribe("visit", None, "recording", 1))
    assert error.value.status_code == 409


def test_get_soap_reads_without_generating(visit, monkeypatch):
    def unexpected(*args):
        raise AssertionError("Loading must not invoke the LLM")
    monkeypatch.setattr(soap, "generate_draft", unexpected)
    assert router.get_soap("visit")["soap"]["subjective"] == ["Original"]


def test_missing_signing_column_reports_migration(visit, monkeypatch):
    from postgrest.exceptions import APIError

    class BrokenUpdate:
        def table(self, *args): return self
        def update(self, *args): return self
        def eq(self, *args): return self
        def execute(self):
            raise APIError({"code": "PGRST204", "message": "Column missing"})

    monkeypatch.setattr(service, "_admin", lambda: BrokenUpdate())
    with pytest.raises(service.ConsultationServiceUnavailable, match="phase_2_2_signed_consultations.sql"):
        finalization.close("visit", "doctor", draft())
    assert visit[0]["status"] == "IN_PROGRESS"
