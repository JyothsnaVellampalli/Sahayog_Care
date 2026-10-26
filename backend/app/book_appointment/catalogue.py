"""Loads the symptom catalogue and the category buckets from the JSON data files.

The JSON files are the single source of truth for symptoms; they are not stored
in the database. Keeping them in JSON (not Python) lets a clinician/engineer
update the symptom list or the category mapping without touching code (Phase 1.2
goal: "Make sure the list of symptoms ... are added in a different json file and
prompt uses the list from json file").

Symptoms are English-only. Later the JSON may be hosted in S3 for security; when
that happens, only the loader functions below need to change (fetch from S3
instead of reading the local file) — callers stay the same.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
SYMPTOMS_FILE = DATA_DIR / "symptoms.json"
CATEGORIES_FILE = DATA_DIR / "symptom_categories.json"


@lru_cache(maxsize=1)
def load_symptoms() -> list[dict]:
    """Return the cleaned symptom catalogue: [{id, code, label, weight}, ...]."""
    payload = json.loads(SYMPTOMS_FILE.read_text(encoding="utf-8"))
    return payload["symptoms"]


@lru_cache(maxsize=1)
def load_categories() -> dict:
    """Return the category->symptom mapping used by the classifier prompt."""
    return json.loads(CATEGORIES_FILE.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def symptom_index() -> dict[str, dict]:
    """Map symptom id -> symptom record for fast lookup/validation."""
    return {s["id"]: s for s in load_symptoms()}


def valid_symptom_ids() -> set[str]:
    return set(symptom_index().keys())


def label_for(symptom_id: str) -> str:
    """Return the human-readable label for a symptom id (or the id if unknown)."""
    record = symptom_index().get(symptom_id)
    return record["label"] if record else symptom_id
