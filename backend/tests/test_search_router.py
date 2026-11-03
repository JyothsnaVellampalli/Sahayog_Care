"""Search router tests: auth is enforced, and a plan/search failure degrades
to a safe HTTP error rather than a raw exception."""
import pytest
from fastapi import HTTPException

from app.config import settings
from app.search import router


def test_unauthenticated_request_is_rejected(monkeypatch):
    def deny(*a):
        raise HTTPException(401, "Please sign in again.")
    monkeypatch.setattr(router, "_verify_patient", deny)
    with pytest.raises(HTTPException) as error:
        router.search_records("patient-1", router.SearchRequest(query="pain"), None)
    assert error.value.status_code == 401


def test_unconfigured_search_returns_503(monkeypatch):
    monkeypatch.setattr(router, "_verify_patient", lambda *a: {"id": "patient-1"})
    monkeypatch.setattr(settings, "opensearch_endpoint", None)
    with pytest.raises(HTTPException) as error:
        router.search_records("patient-1", router.SearchRequest(query="pain"), "Bearer t")
    assert error.value.status_code == 503


def test_search_failure_does_not_leak_the_raw_exception(monkeypatch):
    monkeypatch.setattr(router, "_verify_patient", lambda *a: {"id": "patient-1"})
    monkeypatch.setattr(settings, "opensearch_endpoint", "https://example.com")
    monkeypatch.setattr(settings, "opensearch_aws_access_key_id", "k")
    monkeypatch.setattr(settings, "opensearch_aws_secret_access_key", "s")
    monkeypatch.setattr(settings, "openrouter_api_key", "k")
    monkeypatch.setattr(settings, "openrouter_embeddings_model", "m")
    monkeypatch.setattr(router.retrieval, "candidate_filters", lambda patient_id: ({}, {}))
    monkeypatch.setattr(router.retrieval, "plan_query", lambda *a: router.retrieval.RetrievalPlan())

    def broken(*a, **kw):
        raise RuntimeError("sensitive internal detail")
    monkeypatch.setattr(router.search, "search_chunks", broken)
    with pytest.raises(HTTPException) as error:
        router.search_records("patient-1", router.SearchRequest(query="pain"), "Bearer t")
    assert error.value.status_code == 503
    assert "sensitive" not in error.value.detail


def test_successful_search_returns_results_and_chosen_type(monkeypatch):
    monkeypatch.setattr(router, "_verify_patient", lambda *a: {"id": "patient-1"})
    monkeypatch.setattr(settings, "opensearch_endpoint", "https://example.com")
    monkeypatch.setattr(settings, "opensearch_aws_access_key_id", "k")
    monkeypatch.setattr(settings, "opensearch_aws_secret_access_key", "s")
    monkeypatch.setattr(settings, "openrouter_api_key", "k")
    monkeypatch.setattr(settings, "openrouter_embeddings_model", "m")
    monkeypatch.setattr(router.retrieval, "candidate_filters", lambda patient_id: ({}, {}))
    monkeypatch.setattr(router.retrieval, "plan_query",
                        lambda *a: router.retrieval.RetrievalPlan(retrieval_type="semantic"))
    monkeypatch.setattr(router.search, "search_chunks",
                        lambda *a, **kw: [{"chunk_id": "c1", "chunk_type": "soap", "section": "plan",
                                          "appointment_id": "a1", "text": "Rest and ice.", "score": 1.0}])
    result = router.search_records("patient-1", router.SearchRequest(query="what should I do"), "Bearer t")
    assert result.retrieval_type == "semantic"
    assert result.results[0].chunk_id == "c1"
