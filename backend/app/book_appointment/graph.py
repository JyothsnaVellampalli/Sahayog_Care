"""LangGraph booking-intake flow.

Nodes (in order):
  1. validate_input   - validate selected symptom IDs against the catalogue.
  2. deidentify       - remove direct identifiers from the free text. This node
                        runs BEFORE any external model call (PRD section 6/7).
  3. classify         - call the OpenRouter classifier on the selected symptoms
                        plus the de-identified text; categorise the condition.

The graph is intentionally small for Phase 1.2. Later phases extend it with the
emergency hand-off, specialty match, slot search and booking nodes.
"""

from __future__ import annotations

import contextvars
import logging
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.book_appointment.catalogue import label_for, valid_symptom_ids
from app.book_appointment.classifier import ClassifierError, classify, match_specialty
from app.book_appointment.db import doctors_with_slots, list_specialties
from app.book_appointment.deidentify import deidentify
from app.book_appointment.model_adapter import OpenRouterAdapter, get_adapter
from app.book_appointment.schemas import (
    Category,
    Classification,
    DoctorOut,
    IntakeRequest,
    IntakeResponse,
    SpecialtyMatch,
)
from app.book_appointment.tracing import init_tracing, run_config

logger = logging.getLogger("sahayog.book_appointment")

EMERGENCY_MESSAGE = (
    "An emergency condition. Will handle this condition in this application "
    "in later phases."
)
SEVERE_GUIDANCE = (
    "Your condition is severe, choose some slot as earliest possible."
)

# Export LangSmith env vars (if configured) before the graph is compiled so
# every run is traced. Safe no-op when tracing is disabled.
init_tracing()


class IntakeState(TypedDict, total=False):
    """Mutable state threaded through the graph.

    Only serializable, trace-friendly values live here. The model adapter is
    passed via the run config (configurable), not the state, so it does not
    pollute the LangSmith span inputs/outputs.
    """

    request: IntakeRequest
    # A readable summary of the selected symptoms (id + label + severity +
    # duration) so the trace shows "High fever", "Headache" rather than bare IDs.
    selected_symptoms: list[dict]
    deidentified_text: str
    removed_identifiers: dict[str, int]
    classification: Classification
    model: str | None
    note: str | None
    invalid_symptom_ids: list[str]
    # Phase 1.3 branch outputs.
    outcome: str  # "emergency" | "booking" | "unavailable"
    emergency_message: str | None
    severe_guidance: str | None
    specialty: dict | None
    doctors: list[dict]


# The model adapter is passed out-of-band via a context variable rather than
# through the graph state, so it is never serialized into the LangSmith trace.
# contextvars are isolated per execution context, so this is safe under
# concurrent requests.
_ADAPTER_CTX: contextvars.ContextVar[OpenRouterAdapter | None] = contextvars.ContextVar(
    "book_appointment_adapter", default=None
)


def _current_adapter() -> OpenRouterAdapter:
    """Resolve the adapter from the context var, defaulting to the real one."""
    return _ADAPTER_CTX.get() or get_adapter()


def _selected_summary(request: IntakeRequest) -> list[dict]:
    """Readable list of the patient's selected symptoms, with labels."""
    return [
        {
            "id": s.symptom_id,
            "label": label_for(s.symptom_id),
            "severity": s.severity.value if s.severity else "unknown",
            "duration_days": (
                s.duration_days if s.duration_days is not None else "unknown"
            ),
        }
        for s in request.symptoms
    ]


def _validate_input(state: IntakeState) -> dict[str, Any]:
    """Validate selected symptom IDs and surface a readable selection summary.

    When a logged-in ``patient_id`` is present, age and sex are taken from the
    patient's profile (Phase 1.4) rather than the form.
    """
    request = state["request"]

    # Pull age / sex from the patient record when logged in.
    if request.patient_id:
        try:
            from app.patient.service import get_patient_by_id

            record = get_patient_by_id(request.patient_id)
            if record:
                if record.get("age") is not None:
                    request.age = record["age"]
                if record.get("gender"):
                    request.sex = record["gender"]
        except Exception:
            # If the lookup fails, fall back to whatever the request carried.
            pass

    allowed = valid_symptom_ids()
    invalid = [s.symptom_id for s in request.symptoms if s.symptom_id not in allowed]
    # Keep only valid selections downstream.
    request.symptoms = [s for s in request.symptoms if s.symptom_id in allowed]
    return {
        "invalid_symptom_ids": invalid,
        "selected_symptoms": _selected_summary(request),
    }


def _deidentify(state: IntakeState) -> dict[str, Any]:
    """Scrub identifiers from the patient's free text before the model call."""
    request = state["request"]
    result = deidentify(request.free_text)
    return {
        "deidentified_text": result.text,
        "removed_identifiers": result.removed,
    }


def _classify(state: IntakeState) -> dict[str, Any]:
    """Run the classifier on selected symptoms + de-identified text."""
    request = state["request"]
    # Adapter comes from the context var (not state), so it is not traced.
    adapter = _current_adapter()
    try:
        classification = classify(
            request=request,
            deidentified_text=state.get("deidentified_text", ""),
            adapter=adapter,
        )
        return {
            "classification": classification,
            "model": adapter.classifier_model,
            "note": None,
        }
    except ClassifierError as exc:
        # Surface an UNAVAILABLE result rather than crashing the request; the
        # note explains why (e.g. no API key configured, or the call failed).
        return {
            "classification": Classification(
                status="UNAVAILABLE",
                category=None,
            ),
            "model": None,
            "note": str(exc),
            "outcome": "unavailable",
        }


def _route_after_classify(state: IntakeState) -> str:
    """Conditional edge: emergency ends the flow; everything else books.

    An UNAVAILABLE classification (classifier could not run) also ends, since we
    cannot safely proceed to specialty matching without a triage result.
    """
    classification = state.get("classification")
    category = classification.category if classification else None
    if category == Category.emergency:
        return "emergency"
    if classification and classification.status != "OK":
        return END
    return "match_specialty"


def _emergency(state: IntakeState) -> dict[str, Any]:
    """Emergency path: record the case, log, and end.

    The case is persisted to ``emergency_intakes`` so front desk / staff can
    attend to it (and so it appears in the patient's list). Hand-off to a person
    comes in a later phase.
    """
    logger.warning(EMERGENCY_MESSAGE)

    request = state["request"]
    if request.patient_id:
        try:
            from app.patient.service import create_emergency_intake

            classification = state.get("classification")
            create_emergency_intake(
                patient_id=request.patient_id,
                symptoms=state.get("selected_symptoms", []),
                deidentified_text=state.get("deidentified_text", ""),
                scores=(classification.scores if classification else {}),
            )
        except Exception:
            # Recording failure must not break the patient's emergency guidance.
            pass

    return {"outcome": "emergency", "emergency_message": EMERGENCY_MESSAGE}


def _match_specialty(state: IntakeState) -> dict[str, Any]:
    """Pick the doctor specialty for a non-emergency case (Jev scores)."""
    request = state["request"]
    adapter = _current_adapter()
    specialties = list_specialties()
    if not specialties:
        return {
            "outcome": "unavailable",
            "note": "No specialties available in the database.",
            "specialty": None,
        }
    try:
        result = match_specialty(
            request=request,
            deidentified_text=state.get("deidentified_text", ""),
            specialties=specialties,
            adapter=adapter,
        )
    except ClassifierError as exc:
        return {"outcome": "unavailable", "note": str(exc), "specialty": None}

    matched = result.get("specialty")
    specialty_out = None
    if matched:
        specialty_out = {
            "id": matched.get("id"),
            "code": matched.get("code"),
            "name": matched.get("name"),
            "scores": result.get("scores", {}),
            "confidence": result.get("confidence"),
        }
    return {"specialty": specialty_out}


def _find_doctors(state: IntakeState) -> dict[str, Any]:
    """Find doctors in the matched specialty with their earliest open slots.

    Pure logic (no AI). For a Severe condition, attach the earliest-slot
    guidance message.
    """
    specialty = state.get("specialty")
    classification = state.get("classification")
    severe = bool(
        classification and classification.category == Category.severe
    )
    guidance = SEVERE_GUIDANCE if severe else None

    if not specialty or not specialty.get("id"):
        return {
            "outcome": "booking",
            "doctors": [],
            "severe_guidance": guidance,
            "note": "Could not determine a specialty to find doctors.",
        }

    doctors = doctors_with_slots(specialty["id"], limit_per_doctor=5)
    return {
        "outcome": "booking",
        "doctors": doctors,
        "severe_guidance": guidance,
    }


def build_graph():
    """Compile and return the intake graph.

    Flow: validate_input -> deidentify -> classify -> (conditional)
      - Emergency  -> emergency (log) -> END
      - UNAVAILABLE -> END
      - otherwise  -> match_specialty -> find_doctors -> END
    """
    graph = StateGraph(IntakeState)
    graph.add_node("validate_input", _validate_input)
    graph.add_node("deidentify", _deidentify)
    # TODO: Classify node should be able to match specality also(Can work with multi-lingual inputs)
    graph.add_node("classify", _classify)
    graph.add_node("emergency", _emergency)
    graph.add_node("match_specialty", _match_specialty)
    graph.add_node("find_doctors", _find_doctors)

    graph.add_edge(START, "validate_input")
    graph.add_edge("validate_input", "deidentify")
    graph.add_edge("deidentify", "classify")
    graph.add_conditional_edges(
        "classify",
        _route_after_classify,
        {
            "emergency": "emergency",
            "match_specialty": "match_specialty",
            END: END,
        },
    )
    graph.add_edge("emergency", END)
    graph.add_edge("match_specialty", "find_doctors")
    graph.add_edge("find_doctors", END)
    return graph.compile()


# Compile once at import; the graph is stateless and reusable.
_GRAPH = build_graph()


def run_intake(
    request: IntakeRequest,
    adapter: OpenRouterAdapter | None = None,
) -> IntakeResponse:
    """Run the full intake flow and return the API response model.

    The run is traced in LangSmith (when configured) with a clear run name and
    tags; each node (validate_input, deidentify, classify) appears as a span.
    The trace metadata includes the selected symptom labels for easy reading.
    """
    selected = _selected_summary(request)
    config = run_config()
    # Attach a readable selection summary to the run metadata (labels only).
    config["metadata"] = {
        **config.get("metadata", {}),
        "selected_symptoms": [s["label"] for s in selected],
        "selected_count": len(selected),
    }

    # Bind the adapter for this call via the context var (out-of-band from the
    # traced state), then run the graph.
    token = _ADAPTER_CTX.set(adapter)
    try:
        final: IntakeState = _GRAPH.invoke({"request": request}, config=config)
    finally:
        _ADAPTER_CTX.reset(token)

    specialty = final.get("specialty")
    return IntakeResponse(
        classification=final["classification"],
        symptoms=final.get("selected_symptoms", selected),
        deidentified_text=final.get("deidentified_text", ""),
        removed_identifiers=final.get("removed_identifiers", {}),
        model=final.get("model"),
        note=final.get("note"),
        outcome=final.get("outcome", "unavailable"),
        emergency_message=final.get("emergency_message"),
        severe_guidance=final.get("severe_guidance"),
        specialty=SpecialtyMatch(**specialty) if specialty else None,
        doctors=[DoctorOut(**d) for d in final.get("doctors", [])],
    )
