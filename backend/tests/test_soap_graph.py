import copy
import json
from types import SimpleNamespace

import pytest

from app.consultation.soap import generate_draft, SoapError
from app.consultation import soap_graph


class Adapter:
    def __init__(self, translations):
        self.translations = translations
        self.calls = []

    def classify_json(self, prompt, payload):
        self.calls.append(json.loads(payload))
        result = {"turns": self.translations} if len(self.calls) == 1 else {
            "subjective": ["No fever for two days."], "objective": [], "assessment": [], "plan": []}
        return SimpleNamespace(content=json.dumps(result))


def test_translation_precedes_soap_preserves_turns_and_original():
    segments = [{"text": "दो दिन से बुखार नहीं है।", "speaker": "Person 2", "recording_id": "a"},
                {"text": "దగ్గు ఉందా?", "speaker": "Person 1", "recording_id": "a"}]
    original = copy.deepcopy(segments)
    adapter = Adapter([{"id": 0, "text": "No fever for two days."}, {"id": 1, "text": "Do you have a cough?"}])
    result = generate_draft(segments, adapter)
    assert result.subjective == ["No fever for two days."]
    assert adapter.calls[1]["turns"][1]["text"] == "Do you have a cough?"
    assert adapter.calls[1]["turns"][0]["speaker"] != adapter.calls[1]["turns"][1]["speaker"]
    assert segments == original
    with pytest.raises(LookupError):
        soap_graph._PAYLOAD.get()


@pytest.mark.parametrize("turns", [[], [{"id": 1, "text": "No fever."}],
                                      [{"id": 0, "text": "  "}]])
def test_bad_translation_stops_before_soap(turns):
    adapter = Adapter(turns)
    with pytest.raises(SoapError):
        generate_draft([{"text": "बुखार नहीं है"}], adapter)
    assert len(adapter.calls) == 1


def test_traced_state_contains_only_progress():
    adapter = Adapter([{"id": 0, "text": "No fever for two days."}])
    payload = soap_graph.Payload([{"text": "बुखार नहीं है"}], adapter)
    token = soap_graph._PAYLOAD.set(payload)
    try:
        updates = list(soap_graph._GRAPH.stream({"stage": "started"}, stream_mode="updates"))
    finally:
        soap_graph._PAYLOAD.reset(token)
    assert [next(iter(u)) for u in updates] == ["validate_input", "deidentify", "translate_to_english", "generate_soap", "validate_soap", "medicine_prescription"]
    for update in updates:
        for value in update.values():
            assert set(value) <= {"stage", "turn_count", "translated_count", "excerpt_count", "medicine_count"}
