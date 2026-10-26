"""Builds the ``state`` and the Choice ``question`` for the Jev classifier.

Jev is a decision model: it does not read a chat-style system/user prompt. It
takes a ``state`` (the situation to decide on) and typed ``questions``. We put
everything the model needs into ``state``:

* the clinician-reviewed instructions from References/Categorise_symptom.txt,
* the category reference buckets (from symptom_categories.json),
* the allowed symptom list (from symptoms.json),
* the patient's input: selected symptoms (with severity/duration) and the
  de-identified free text, plus age / sex / pregnancy / duration.

The question is a single Choice over the four categories; Jev returns a
probability (weightage) for each, and we pick the highest.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.book_appointment.catalogue import (
    label_for,
    load_categories,
    load_symptoms,
)
from app.book_appointment.schemas import Category, IntakeRequest

# References/Categorise_symptom.txt lives at the repo root, two levels above app/.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_REFERENCE_FILE = _REPO_ROOT / "References" / "Categorise_symptom.txt"

# The Choice question name and the criteria (category -> short description) that
# Jev scores. Descriptions are kept brief; the detailed rules live in `state`.
CLASSIFIER_QUESTION_NAME = "triage_category"
CLASSIFIER_INSTRUCTIONS = (
    "Using the triage rules and the patient's symptoms and text in the state, "
    "choose the single category that best describes how urgent the patient's "
    "condition is."
)
CATEGORY_CRITERIA: dict[str, str] = {
    Category.emergency.value: (
        "A red-flag symptom is present that needs urgent, same-time human care."
    ),
    Category.severe.value: (
        "Serious but not an immediate emergency; should be seen soon."
    ),
    Category.normal.value: (
        "Routine; no red flags and no serious escalation."
    ),
    Category.needs_more_info.value: (
        "Not enough information in the symptoms or text to decide."
    ),
}


@lru_cache(maxsize=1)
def _reference_instructions() -> str:
    """The clinician-reviewed triage rules used as decision guidance."""
    if _REFERENCE_FILE.exists():
        return _REFERENCE_FILE.read_text(encoding="utf-8").strip()
    return (
        "Classify the patient's condition as Emergency, Severe, or Normal based "
        "on the symptoms and text. Emergency beats Severe beats Normal."
    )


def _format_symptom_list() -> str:
    """Render the allowed symptom list (id, label, weight) for the state."""
    return "\n".join(
        f'{s["id"]}\t{s["label"]}\t(weight {s["weight"]})' for s in load_symptoms()
    )


def _format_category_buckets() -> str:
    """Render the category->symptom buckets from the JSON file."""
    categories = load_categories().get("categories", {})
    blocks: list[str] = []
    for name, spec in categories.items():
        parts = [f"{name}:"]
        if spec.get("description"):
            parts.append(f"  {spec['description']}")
        for item in spec.get("catalogue", []):
            parts.append(f"  - {item['id']} ({item['code']}): {item.get('note', '')}")
        for phrase in spec.get("text_only", []):
            parts.append(f"  - (from text) {phrase}")
        blocks.append("\n".join(parts))
    return "\n\n".join(blocks)


def _format_patient_input(request: IntakeRequest, deidentified_text: str) -> str:
    """Render the patient's selected symptoms + de-identified text as JSON.

    The free text passed here MUST already be de-identified.
    """
    selected = [
        {
            "id": item.symptom_id,
            "severity": item.severity.value if item.severity else "unknown",
            "duration_days": (
                item.duration_days if item.duration_days is not None else "unknown"
            ),
        }
        for item in request.symptoms
    ]
    durations = [
        s.duration_days for s in request.symptoms if s.duration_days is not None
    ]
    duration_days = max(durations) if durations else "unknown"

    patient = {
        "SELECTED": [s["id"] for s in selected],
        "SELECTED_DETAIL": selected,
        "TEXT": deidentified_text or "",
        "AGE": request.age if request.age is not None else "unknown",
        "SEX": request.sex or "unknown",
        "PREGNANT": "unknown" if request.pregnant is None else bool(request.pregnant),
        "DURATION_DAYS": duration_days,
    }
    return json.dumps(patient, ensure_ascii=False)


def build_state(request: IntakeRequest, deidentified_text: str) -> str:
    """Assemble the full ``state`` string sent to the Jev classifier.

    Combines the triage rules, the category buckets, the allowed symptom list,
    and the patient's (de-identified) input into one document.
    """
    return (
        "TRIAGE RULES:\n"
        f"{_reference_instructions()}\n\n"
        "CATEGORY REFERENCE (higher symptom weight = more severe):\n"
        f"{_format_category_buckets()}\n\n"
        "SYMPTOM_LIST (id, label, weight):\n"
        f"{_format_symptom_list()}\n\n"
        "PATIENT_INPUT (JSON; TEXT is already de-identified):\n"
        f"{_format_patient_input(request, deidentified_text)}\n"
    )


# --- Specialty matching (Phase 1.3) ------------------------------------------

SPECIALTY_QUESTION_NAME = "doctor_specialty"
SPECIALTY_INSTRUCTIONS = (
    "Based on the patient's symptoms and text in the state, choose the single "
    "medical specialty whose doctor is the best first point of care. If no "
    "specialty clearly fits, prefer General Medicine."
)


def _format_symptom_labels(request: IntakeRequest) -> str:
    """Readable 'label (severity, N days)' lines for the selected symptoms."""
    lines = []
    for s in request.symptoms:
        sev = s.severity.value if s.severity else "unknown severity"
        dur = f"{s.duration_days} days" if s.duration_days is not None else "unknown duration"
        lines.append(f"- {label_for(s.symptom_id)} ({sev}, {dur})")
    return "\n".join(lines) if lines else "- (none selected)"


def build_specialty_state(
    request: IntakeRequest, deidentified_text: str, specialties: list[dict]
) -> str:
    """Assemble the ``state`` for the specialty-matching Jev decision.

    Includes the patient's symptoms (with labels) and the available specialties
    with their descriptions, so the model scores against the real options.
    """
    specialty_lines = "\n".join(
        f"- {s['name']}: {s.get('description', '')}" for s in specialties
    )
    return (
        "TASK: choose the medical specialty best suited to see this patient "
        "first.\n\n"
        "PATIENT SYMPTOMS:\n"
        f"{_format_symptom_labels(request)}\n\n"
        "PATIENT TEXT (de-identified):\n"
        f"{deidentified_text or '(none)'}\n\n"
        "AGE: "
        f"{request.age if request.age is not None else 'unknown'}\n\n"
        "AVAILABLE SPECIALTIES:\n"
        f"{specialty_lines}\n"
    )


def specialty_criteria(specialties: list[dict]) -> dict[str, str]:
    """Build the Choice criteria (specialty name -> description) from the DB."""
    return {s["name"]: (s.get("description") or s["name"]) for s in specialties}
