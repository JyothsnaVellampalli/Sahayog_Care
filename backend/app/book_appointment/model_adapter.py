"""Single model adapter (PRD section 7: all model calls go through one adapter,
vendor swappable without rewriting workflows).

Two surfaces are supported, both via OpenRouter with the same API key:

* ``decisions`` — the Jev "System One" decisions endpoint
  (``/api/alpha/decisions``). Jev returns a *typed decision with probabilities*
  (weightage per option), not text. This is what the symptom triage classifier
  uses. See https://openrouter.ai/docs/guides/community/jev.
* ``classify_json`` — a normal chat model via the OpenAI-compatible endpoint,
  kept for later phases that need generated text.

Every call has a timeout (PRD section 7).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import settings


class ModelNotConfiguredError(RuntimeError):
    """Raised when the required API key / endpoint is not configured."""


class ModelCallError(RuntimeError):
    """Raised when the model call fails or returns no usable content."""


@dataclass
class ModelResponse:
    content: str
    model: str


@dataclass
class DecisionResponse:
    """A parsed Jev decisions response (one question's typed answer).

    Attributes:
        choice: the winning option label (e.g. "Emergency").
        probabilities: option -> probability (0..1); this is the "weightage".
        confidence: how concentrated the distribution is (0..1).
        model: the model id that served the request.
        raw: the full decoded response body, for debugging.
    """

    choice: str | None
    probabilities: dict[str, float]
    confidence: float | None
    model: str
    raw: dict[str, Any]


class OpenRouterAdapter:
    """Swappable wrapper over OpenRouter's decisions and chat endpoints."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        classifier_model: str | None = None,
        classifier_url: str | None = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else settings.openrouter_api_key
        self._model = model or settings.openrouter_model
        self._base_url = base_url or settings.openrouter_base_url
        self._timeout = (
            timeout if timeout is not None else settings.openrouter_timeout_seconds
        )
        self._classifier_model = (
            classifier_model or settings.symptom_classifier_model
        )
        self._classifier_url = classifier_url or settings.open_router_classifier_url

    @property
    def model(self) -> str:
        return self._model

    @property
    def classifier_model(self) -> str:
        return self._classifier_model

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    # --- Jev decisions surface ------------------------------------------------

    def decisions(
        self,
        state: str | dict[str, Any],
        questions: dict[str, Any],
    ) -> dict[str, Any]:
        """Call the Jev decisions endpoint and return the raw decoded JSON.

        Args:
            state: the application state (situation) to decide on.
            questions: a mapping of question name -> typed question spec.

        Returns:
            The decoded response body (one typed answer per question + usage).

        Raises:
            ModelNotConfiguredError: if the API key is missing.
            ModelCallError: if the HTTP call fails or returns a non-OK status.
        """
        if not self._api_key:
            raise ModelNotConfiguredError(
                "OPENROUTER_API_KEY is not set. Add it to backend/.env to run "
                "the Jev classifier."
            )

        import httpx

        payload = {
            "model": self._classifier_model,
            "state": state,
            "questions": questions,
        }
        try:
            response = httpx.post(
                self._classifier_url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "X-Title": "Sahayog Care",
                },
                json=payload,
                timeout=self._timeout,
            )
        except Exception as exc:
            raise ModelCallError(f"Decisions call failed: {exc}") from exc

        if response.status_code >= 400:
            # Surface the upstream message without echoing the whole body.
            detail = response.text[:300]
            raise ModelCallError(
                f"Decisions call returned {response.status_code}: {detail}"
            )

        try:
            return response.json()
        except Exception as exc:
            raise ModelCallError("Decisions response was not valid JSON.") from exc

    def choice_decision(
        self,
        state: str | dict[str, Any],
        question_name: str,
        instructions: str,
        criteria: dict[str, str],
    ) -> DecisionResponse:
        """Ask a single Choice question and return the parsed decision.

        A Choice question picks exactly one option from ``criteria`` (option ->
        description) and returns a probability for each option. We read the
        winning ``choice`` and the ``probabilities`` (the weightage).
        """
        questions = {
            question_name: {
                "type": "choice",
                "instructions": instructions,
                "criteria": criteria,
            }
        }
        body = self.decisions(state, questions)
        # Typed answers are nested under "answers" keyed by question name.
        answers = body.get("answers") or {}
        answer = answers.get(question_name) or body.get(question_name) or {}
        probs = answer.get("probabilities") or {}
        # Coerce probabilities to floats defensively.
        probabilities = {
            str(k): float(v) for k, v in probs.items() if _is_number(v)
        }
        return DecisionResponse(
            choice=answer.get("choice"),
            probabilities=probabilities,
            confidence=(
                float(answer["confidence"])
                if _is_number(answer.get("confidence"))
                else None
            ),
            model=str(body.get("model") or self._classifier_model),
            raw=body,
        )

    # --- Chat surface (kept for later phases) --------------------------------

    def classify_json(self, system_prompt: str, user_payload: str) -> ModelResponse:
        """Send a system + user message to a chat model and return JSON content."""
        if not self._api_key:
            raise ModelNotConfiguredError(
                "OPENROUTER_API_KEY is not set. Add it to backend/.env."
            )

        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - dependency guaranteed
            raise ModelCallError("The 'openai' package is not installed.") from exc

        client = OpenAI(
            api_key=self._api_key,
            base_url=self._base_url,
            timeout=self._timeout,
        )

        try:
            completion = client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_payload},
                ],
                temperature=0,
                response_format={"type": "json_object"},
                extra_headers={
                    "HTTP-Referer": "https://sahayog.care",
                    "X-Title": "Sahayog Care",
                },
            )
        except Exception as exc:
            raise ModelCallError(f"Model call failed: {exc}") from exc

        if not completion.choices or not completion.choices[0].message.content:
            raise ModelCallError("Model returned no content.")

        return ModelResponse(
            content=completion.choices[0].message.content,
            model=self._model,
        )


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def get_adapter() -> OpenRouterAdapter:
    """Factory so callers do not construct the vendor client directly."""
    return OpenRouterAdapter()
