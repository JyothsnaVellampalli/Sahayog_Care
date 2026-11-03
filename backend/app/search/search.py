"""Query the OpenSearch chunk index (Phase 6.2).

patient_id is always a hard filter, applied here in Python before any
query is built -- the retrieval plan (see retrieval.py) can only add
doctor_id/appointment_id on top of it, never replace or remove it. See
search_chunks()'s docstring for the full boundary.
"""
from __future__ import annotations

import logging

from app.search import embeddings
from app.search.client import get_client, index_name
from app.search.retrieval import RetrievalPlan

logger = logging.getLogger(__name__)

RRF_K = 60


def _base_filter(patient_id: str, plan: RetrievalPlan) -> list[dict]:
    filters = [{"term": {"patient_id": patient_id}}]
    if plan.doctor_id:
        filters.append({"term": {"doctor_id": plan.doctor_id}})
    if plan.appointment_id:
        filters.append({"term": {"appointment_id": plan.appointment_id}})
    return filters


def _hit_to_result(hit) -> dict:
    source = hit["_source"]
    return {
        "chunk_id": hit["_id"], "chunk_type": source.get("chunk_type"),
        "section": source.get("section"), "appointment_id": source.get("appointment_id"),
        "text": source.get("text"), "score": hit["_score"],
    }


def _keyword_search(client, index, query_text, filters, k):
    body = {
        "size": k,
        "query": {"bool": {"must": [{"match": {"text": query_text}}], "filter": filters}},
        "_source": ["chunk_type", "section", "appointment_id", "text"],
    }
    return client.search(index=index, body=body)["hits"]["hits"]


def _semantic_search(client, index, query_text, filters, k):
    vector = embeddings.embed_text(query_text)
    body = {
        "size": k,
        "query": {"bool": {"must": [{"knn": {"embedding": {"vector": vector, "k": k}}}], "filter": filters}},
        "_source": ["chunk_type", "section", "appointment_id", "text"],
    }
    return client.search(index=index, body=body)["hits"]["hits"]


def _reciprocal_rank_fusion(*ranked_lists, k=RRF_K):
    """Merge ranked hit lists by rank (not raw score, which isn't comparable
    between a keyword match score and a knn similarity score)."""
    scores: dict[str, float] = {}
    hits_by_id: dict[str, dict] = {}
    for hits in ranked_lists:
        for rank, hit in enumerate(hits):
            scores[hit["_id"]] = scores.get(hit["_id"], 0.0) + 1.0 / (k + rank + 1)
            hits_by_id.setdefault(hit["_id"], hit)
    ordered = sorted(scores, key=scores.get, reverse=True)
    merged = []
    for chunk_id in ordered:
        hit = dict(hits_by_id[chunk_id])
        hit["_score"] = scores[chunk_id]
        merged.append(hit)
    return merged


def search_chunks(query_text: str, patient_id: str, plan: RetrievalPlan, k: int = 8) -> list[dict]:
    """Search this patient's own chunks (never any other patient's).

    plan.doctor_id/plan.appointment_id may narrow the result further, but
    patient_id is applied unconditionally regardless of what's in plan --
    there is no code path here that can search outside the given patient_id.
    """
    client = get_client()
    index = index_name()
    filters = _base_filter(patient_id, plan)

    if plan.retrieval_type == "keyword":
        hits = _keyword_search(client, index, query_text, filters, k)
    elif plan.retrieval_type == "semantic":
        hits = _semantic_search(client, index, query_text, filters, k)
    else:
        keyword_hits = _keyword_search(client, index, query_text, filters, k)
        semantic_hits = _semantic_search(client, index, query_text, filters, k)
        hits = _reciprocal_rank_fusion(keyword_hits, semantic_hits)[:k]

    return [_hit_to_result(hit) for hit in hits]
