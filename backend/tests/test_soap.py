"""SOAP boundary tests; no network or patient records."""
import json
from types import SimpleNamespace

import pytest

from app.consultation.soap import SoapError, generate_draft
from app.book_appointment.model_adapter import ModelCallError


class Adapter:
    def __init__(self, response):
        self.response = response
        self.payload = None

    def classify_json(self, prompt, payload):
        self.payload = payload
        if prompt.startswith("Translate"):
            turns = json.loads(payload)["turns"]
            return SimpleNamespace(content=json.dumps({"turns": [{"id": t["id"], "text": t["text"]} for t in turns]}))
        return SimpleNamespace(content=json.dumps(self.response))


def test_grounded_draft_removes_identifiers_and_preserves_negation():
    adapter = Adapter(dict(subjective=["No fever."], objective=[], assessment=[], plan=[]))
    draft = generate_draft([{"text": "My name is Rahul Sharma, phone 9876543210. No fever."}], adapter)
    assert draft.subjective == ["No fever."]
    assert draft.objective == []
    assert "Rahul" not in adapter.payload
    assert "9876543210" not in adapter.payload


@pytest.mark.parametrize("response", [
    dict(subjective=[], objective=[], assessment=["Invented diagnosis"], plan=[]),
    dict(subjective="No fever.", objective=[], assessment=[], plan=[]),
    dict(subjective=[], objective=[], assessment=[]),
    dict(subjective=[], objective=[], assessment=[], plan=[], signed=True),
])
def test_rejects_unsupported_or_invalid_output(response):
    with pytest.raises(SoapError):
        generate_draft([{"text": "No fever."}], Adapter(response))


def test_empty_transcript_does_not_call_model():
    adapter = Adapter({})
    with pytest.raises(SoapError):
        generate_draft([], adapter)
    assert adapter.payload is None


def test_upstream_error_does_not_expose_payload():
    class BrokenAdapter:
        def classify_json(self, *_args):
            raise ModelCallError("sensitive upstream payload")
    with pytest.raises(SoapError, match="model unavailable") as error:
        generate_draft([{"text": "No fever."}], BrokenAdapter())
    assert "sensitive" not in str(error.value)
