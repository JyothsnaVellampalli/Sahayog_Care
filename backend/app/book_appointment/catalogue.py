"""Validated Phase 3 catalogue: the single source of symptom metadata."""
import json
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
SYMPTOMS_FILE = DATA_DIR / "symptoms_2.json"
SPECIALTY_CODES = {"cardiology": "CARD", "orthopedics": "ORTH",
                   "dermatology": "DERM", "gastroenterology": "GAST"}
CATEGORY_BY_SEVERITY = {"mild": "Normal", "moderate": "Normal",
                        "severe": "Severe", "emergency": "Emergency"}

@lru_cache(maxsize=1)
def load_symptoms() -> list[dict]:
    symptoms = json.loads(SYMPTOMS_FILE.read_text(encoding="utf-8"))["symptoms"]
    ids, codes = set(), set()
    for s in symptoms:
        if (not s.get("id") or s["id"] in ids or not s.get("code") or s["code"] in codes
            or not s.get("label") or s.get("specialty") not in SPECIALTY_CODES
            or s.get("severity") not in CATEGORY_BY_SEVERITY
            or type(s.get("weight")) is not int or not 1 <= s["weight"] <= 5):
            raise ValueError("Invalid or duplicate Phase 3 symptom record")
        ids.add(s["id"])
        codes.add(s["code"])
    if {s["specialty"] for s in symptoms} != set(SPECIALTY_CODES):
        raise ValueError("Catalogue must cover all four MVP specialties")
    return symptoms

@lru_cache(maxsize=1)
def symptom_index() -> dict[str, dict]:
    return {s["id"]: s for s in load_symptoms()}

def valid_symptom_ids() -> set[str]:
    return set(symptom_index())

def label_for(symptom_id: str) -> str:
    return symptom_index().get(symptom_id, {}).get("label", symptom_id)

def load_categories() -> dict:
    """Derived compatibility view; never reads the legacy category file."""
    categories = {name: {"catalogue": []} for name in ("Emergency", "Severe", "Normal")}
    for s in load_symptoms():
        categories[CATEGORY_BY_SEVERITY[s["severity"]]]["catalogue"].append(s)
    return {"categories": categories}
