"""search_chunks tests: patient_id is always enforced, query bodies are
built correctly per retrieval type, and RRF merge ordering."""
from app.search import search
from app.search.retrieval import RetrievalPlan


def hit(chunk_id, score, **source):
    return {"_id": chunk_id, "_score": score, "_source": {"chunk_type": "symptom", **source}}


def test_keyword_search_always_includes_patient_id_filter(monkeypatch):
    captured = {}
    class FakeClient:
        def search(self, index, body):
            captured["body"] = body
            return {"hits": {"hits": [hit("c1", 1.0, text="knee pain")]}}
    monkeypatch.setattr(search, "get_client", lambda: FakeClient())
    monkeypatch.setattr(search, "index_name", lambda: "idx")
    plan = RetrievalPlan(retrieval_type="keyword")
    results = search.search_chunks("knee pain", "patient-1", plan)
    assert {"term": {"patient_id": "patient-1"}} in captured["body"]["query"]["bool"]["filter"]
    assert results[0]["chunk_id"] == "c1"


def test_plan_cannot_search_without_a_patient_id_filter_even_if_empty(monkeypatch):
    """Defensive: even a maliciously/accidentally empty patient_id must still
    produce a term filter, never an unfiltered query across all patients."""
    captured = {}
    class FakeClient:
        def search(self, index, body):
            captured["body"] = body
            return {"hits": {"hits": []}}
    monkeypatch.setattr(search, "get_client", lambda: FakeClient())
    monkeypatch.setattr(search, "index_name", lambda: "idx")
    search.search_chunks("query", "", RetrievalPlan(retrieval_type="keyword"))
    assert {"term": {"patient_id": ""}} in captured["body"]["query"]["bool"]["filter"]


def test_doctor_and_appointment_filters_are_added_on_top_of_patient(monkeypatch):
    captured = {}
    class FakeClient:
        def search(self, index, body):
            captured["body"] = body
            return {"hits": {"hits": []}}
    monkeypatch.setattr(search, "get_client", lambda: FakeClient())
    monkeypatch.setattr(search, "index_name", lambda: "idx")
    plan = RetrievalPlan(retrieval_type="keyword", doctor_id="doc-1", appointment_id="appt-1")
    search.search_chunks("query", "patient-1", plan)
    filters = captured["body"]["query"]["bool"]["filter"]
    assert {"term": {"patient_id": "patient-1"}} in filters
    assert {"term": {"doctor_id": "doc-1"}} in filters
    assert {"term": {"appointment_id": "appt-1"}} in filters


def test_semantic_search_embeds_query_and_uses_knn(monkeypatch):
    captured = {}
    class FakeClient:
        def search(self, index, body):
            captured["body"] = body
            return {"hits": {"hits": []}}
    monkeypatch.setattr(search, "get_client", lambda: FakeClient())
    monkeypatch.setattr(search, "index_name", lambda: "idx")
    monkeypatch.setattr(search.embeddings, "embed_text", lambda text: [0.1, 0.2, 0.3])
    search.search_chunks("query", "patient-1", RetrievalPlan(retrieval_type="semantic"))
    knn = captured["body"]["query"]["bool"]["must"][0]["knn"]["embedding"]
    assert knn["vector"] == [0.1, 0.2, 0.3]


def test_hybrid_merges_both_searches_via_rrf(monkeypatch):
    calls = []
    class FakeClient:
        def search(self, index, body):
            calls.append(body)
            if len(calls) == 1:  # keyword call
                return {"hits": {"hits": [hit("c1", 5.0), hit("c2", 3.0)]}}
            return {"hits": {"hits": [hit("c2", 0.9), hit("c3", 0.8)]}}  # semantic call
    monkeypatch.setattr(search, "get_client", lambda: FakeClient())
    monkeypatch.setattr(search, "index_name", lambda: "idx")
    monkeypatch.setattr(search.embeddings, "embed_text", lambda text: [0.1])
    results = search.search_chunks("query", "patient-1", RetrievalPlan(retrieval_type="hybrid"))
    # c2 appears in both lists (rank 1 keyword, rank 0 semantic) -> highest combined RRF score.
    assert results[0]["chunk_id"] == "c2"
    assert {r["chunk_id"] for r in results} == {"c1", "c2", "c3"}


def test_reciprocal_rank_fusion_orders_by_combined_rank():
    list_a = [hit("c1", 1.0), hit("c2", 0.9)]
    list_b = [hit("c2", 1.0), hit("c3", 0.9)]
    merged = search._reciprocal_rank_fusion(list_a, list_b)
    assert [h["_id"] for h in merged] == ["c2", "c1", "c3"]
