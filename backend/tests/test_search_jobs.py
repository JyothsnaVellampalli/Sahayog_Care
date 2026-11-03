"""Search ingestion job tests: enqueue no-op, chunk dispatch, indexer bulk upsert."""
from types import SimpleNamespace

import pytest

from app.config import settings
from app.search import indexer, jobs as search_jobs


def test_enqueue_is_a_noop_when_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "opensearch_endpoint", None)
    calls = []
    monkeypatch.setattr(search_jobs, "client", lambda: calls.append("called") or None)
    search_jobs.enqueue("APPOINTMENT", "a1")
    assert calls == []  # the database client was never even touched


def test_enqueue_calls_rpc_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "opensearch_endpoint", "https://example.com")
    monkeypatch.setattr(settings, "opensearch_aws_access_key_id", "k")
    monkeypatch.setattr(settings, "opensearch_aws_secret_access_key", "s")
    monkeypatch.setattr(settings, "openrouter_api_key", "k")
    monkeypatch.setattr(settings, "openrouter_embeddings_model", "m")

    class Query:
        def __getattr__(self, name): return lambda *a, **kw: self
        def execute(self): return SimpleNamespace(data=[{"id": "job1"}])
    monkeypatch.setattr(search_jobs, "client", lambda: Query())
    search_jobs.enqueue("APPOINTMENT", "a1")  # must not raise


def test_enqueue_never_raises_on_database_error(monkeypatch):
    monkeypatch.setattr(settings, "opensearch_endpoint", "https://example.com")
    monkeypatch.setattr(settings, "opensearch_aws_access_key_id", "k")
    monkeypatch.setattr(settings, "opensearch_aws_secret_access_key", "s")
    monkeypatch.setattr(settings, "openrouter_api_key", "k")
    monkeypatch.setattr(settings, "openrouter_embeddings_model", "m")

    def broken():
        raise RuntimeError("db is down")
    monkeypatch.setattr(search_jobs, "client", broken)
    search_jobs.enqueue("APPOINTMENT", "a1")  # fire-and-forget: must not raise


def test_build_chunks_dispatches_appointment_kind(monkeypatch):
    monkeypatch.setattr(search_jobs, "_fetch_appointment",
                        lambda _id: {"id": "a1", "symptom_text": "Knee pain", "symptoms": []})
    chunks = search_jobs._build_chunks({"kind": "APPOINTMENT", "source_id": "a1"})
    assert len(chunks) == 1 and chunks[0].chunk_type == "symptom"


def test_build_chunks_missing_appointment_returns_empty(monkeypatch):
    monkeypatch.setattr(search_jobs, "_fetch_appointment", lambda _id: None)
    assert search_jobs._build_chunks({"kind": "APPOINTMENT", "source_id": "missing"}) == []


def test_index_chunks_embeds_and_bulk_upserts(monkeypatch):
    from app.search.chunking import Chunk
    chunk = Chunk(chunk_id="a1:symptom", patient_id="p1", doctor_id="d1",
                 appointment_id="a1", chunk_type="symptom", section=None, text="Knee pain")
    monkeypatch.setattr(indexer.embeddings, "embed_text", lambda text: [0.1, 0.2])
    monkeypatch.setattr(indexer, "get_client", lambda: "fake-client")

    captured = {}
    def fake_bulk(client, actions, raise_on_error=False):
        captured["actions"] = actions
        return len(actions), []
    monkeypatch.setattr("opensearchpy.helpers.bulk", fake_bulk)

    count = indexer.index_chunks([chunk])
    assert count == 1
    assert captured["actions"][0]["_id"] == "a1:symptom"
    assert captured["actions"][0]["_source"]["embedding"] == [0.1, 0.2]


def test_index_chunks_empty_list_is_a_noop(monkeypatch):
    monkeypatch.setattr(indexer, "get_client", lambda: (_ for _ in ()).throw(AssertionError("should not be called")))
    assert indexer.index_chunks([]) == 0


def test_index_chunks_raises_on_bulk_errors(monkeypatch):
    from app.search.chunking import Chunk
    chunk = Chunk(chunk_id="a1:symptom", patient_id="p1", doctor_id=None,
                 appointment_id="a1", chunk_type="symptom", section=None, text="Knee pain")
    monkeypatch.setattr(indexer.embeddings, "embed_text", lambda text: [0.1])
    monkeypatch.setattr(indexer, "get_client", lambda: "fake-client")
    monkeypatch.setattr("opensearchpy.helpers.bulk", lambda client, actions, raise_on_error=False: (0, ["boom"]))
    with pytest.raises(RuntimeError):
        indexer.index_chunks([chunk])
