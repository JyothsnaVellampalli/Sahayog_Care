"""Jev decisions classifiers for the booking flow.

Two decisions use the same Jev "Choice" pattern (a typed decision with a
probability/weightage per option, no reasoning text):

1. ``classify`` — triage category (Emergency / Severe / Normal / Need more info).
2. ``match_specialty`` — which doctor specialty should see the patient first.

Both pick the option with the highest weightage.
"""

from __future__ import annotations

from app.book_appointment.model_adapter import (
    ModelCallError,
    ModelNotConfiguredError,
    OpenRouterAdapter,
    get_adapter,
)
from app.book_appointment.prompt import (
    CATEGORY_CRITERIA,
    CLASSIFIER_INSTRUCTIONS,
    CLASSIFIER_QUESTION_NAME,
    SPECIALTY_INSTRUCTIONS,
    SPECIALTY_QUESTION_NAME,
    build_specialty_state,
    build_state,
    specialty_criteria,
)
from app.book_appointment.schemas import Category, Classification, IntakeRequest


class ClassifierError(RuntimeError):
    """Raised when a classification cannot be completed."""


def _to_category(label: str | None) -> Category | None:
    """Map a Jev option label back to the Category enum, tolerating casing."""
    if not label:
        return None
    for category in Category:
        if category.value.lower() == label.strip().lower():
            return category
    return None


def _top_label(choice: str | None, scores: dict[str, float]) -> str | None:
    """Return the highest-weighted option, falling back to Jev's own choice."""
    if scores:
        return max(scores, key=scores.get)
    return choice


def classify(
    request: IntakeRequest,
    deidentified_text: str,
    adapter: OpenRouterAdapter | None = None,
) -> Classification:
    """Classify the patient's triage category with the Jev decisions model.

    Args:
        request: the (already validated) intake request.
        deidentified_text: the patient's free text with identifiers removed.
        adapter: optional adapter override (used by tests).

    Returns:
        A Classification with the chosen category and per-category scores.

    Raises:
        ClassifierError: if the decision call cannot be completed.
    """
    adapter = adapter or get_adapter()
    state = build_state(request, deidentified_text)

    try:
        decision = adapter.choice_decision(
            state=state,
            question_name=CLASSIFIER_QUESTION_NAME,
            instructions=CLASSIFIER_INSTRUCTIONS,
            criteria=CATEGORY_CRITERIA,
        )
    except ModelNotConfiguredError as exc:
        raise ClassifierError(str(exc)) from exc
    except ModelCallError as exc:
        raise ClassifierError(str(exc)) from exc

    category = _to_category(_top_label(decision.choice, decision.probabilities))
    if category is None:
        raise ClassifierError(
            "Jev returned no recognisable category "
            f"(choice={decision.choice!r}, scores={decision.probabilities!r})."
        )

    return Classification(
        status="OK",
        category=category,
        scores=decision.probabilities,
        confidence=decision.confidence,
    )


def match_specialty(
    request: IntakeRequest,
    deidentified_text: str,
    specialties: list[dict],
    adapter: OpenRouterAdapter | None = None,
) -> dict:
    """Pick the best doctor specialty for the patient (Jev scores per specialty).

    Args:
        request: the intake request.
        deidentified_text: the de-identified free text.
        specialties: specialties from the DB ([{id, code, name, description}]).
        adapter: optional adapter override.

    Returns:
        {"specialty": <matched specialty dict or None>, "scores": {name: p},
         "confidence": float | None}.

    Raises:
        ClassifierError: if the decision call cannot be completed.
    """
    if not specialties:
        raise ClassifierError("No specialties available to match against.")

    adapter = adapter or get_adapter()
    state = build_specialty_state(request, deidentified_text, specialties)
    criteria = specialty_criteria(specialties)

    try:
        decision = adapter.choice_decision(
            state=state,
            question_name=SPECIALTY_QUESTION_NAME,
            instructions=SPECIALTY_INSTRUCTIONS,
            criteria=criteria,
        )
    except ModelNotConfiguredError as exc:
        raise ClassifierError(str(exc)) from exc
    except ModelCallError as exc:
        raise ClassifierError(str(exc)) from exc

    top_name = _top_label(decision.choice, decision.probabilities)
    matched = next(
        (s for s in specialties if s["name"].lower() == (top_name or "").lower()),
        None,
    )
    return {
        "specialty": matched,
        "scores": decision.probabilities,
        "confidence": decision.confidence,
    }
