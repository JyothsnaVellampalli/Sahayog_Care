"""Chat router tests: auth is enforced, unconfigured degrades safely, and a
failure never leaks the raw exception."""
import pytest
from fastapi import HTTPException

from app.chat import router
from app.config import settings


def test_unauthenticated_chat_is_rejected(monkeypatch):
    def deny(*a):
        raise HTTPException(401, "Please sign in again.")
    monkeypatch.setattr(router, "_verify_patient", deny)
    with pytest.raises(HTTPException) as error:
        router.ask_question("patient-1", router.ChatRequest(message="hi"), None)
    assert error.value.status_code == 401


def test_unconfigured_chat_returns_503(monkeypatch):
    monkeypatch.setattr(router, "_verify_patient", lambda *a: {"id": "patient-1"})
    monkeypatch.setattr(settings, "opensearch_endpoint", None)
    with pytest.raises(HTTPException) as error:
        router.ask_question("patient-1", router.ChatRequest(message="hi"), "Bearer t")
    assert error.value.status_code == 503


def test_chat_failure_does_not_leak_the_raw_exception(monkeypatch):
    monkeypatch.setattr(router, "_verify_patient", lambda *a: {"id": "patient-1"})
    monkeypatch.setattr(router, "_chat_configured", lambda: True)
    def broken(patient_id, message):
        raise RuntimeError("sensitive internal detail")
    monkeypatch.setattr(router.agent, "ask", broken)
    with pytest.raises(HTTPException) as error:
        router.ask_question("patient-1", router.ChatRequest(message="hi"), "Bearer t")
    assert error.value.status_code == 503
    assert "sensitive" not in error.value.detail


def test_successful_chat_returns_reply_and_references(monkeypatch):
    monkeypatch.setattr(router, "_verify_patient", lambda *a: {"id": "patient-1"})
    monkeypatch.setattr(router, "_chat_configured", lambda: True)
    monkeypatch.setattr(router.agent, "ask", lambda patient_id, message: router.agent.AgentResult(
        reply="You're doing fine.", references=[{"chunk_id": "c1", "text": "knee pain"}]))
    result = router.ask_question("patient-1", router.ChatRequest(message="how am I doing"), "Bearer t")
    assert result.reply == "You're doing fine."
    assert result.references[0].chunk_id == "c1"


def test_history_unconfigured_returns_empty_list_not_an_error(monkeypatch):
    monkeypatch.setattr(router, "_verify_patient", lambda *a: {"id": "patient-1"})
    monkeypatch.setattr(settings, "consultation_checkpoint_db_url", None)
    result = router.chat_history("patient-1", "Bearer t")
    assert result.history == []
