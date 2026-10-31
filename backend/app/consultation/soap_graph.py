"""Translation -> SOAP graph; clinical payloads stay outside traced state."""
import contextvars
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.book_appointment.deidentify import deidentify
from app.book_appointment.model_adapter import get_adapter, ModelCallError, ModelNotConfiguredError
from app.book_appointment.tracing import init_tracing, run_config
from app.consultation.soap import SoapDraft, SoapError


class Turn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: int
    text: str = Field(min_length=1, max_length=60000)


class Translation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    turns: list[Turn]


class State(TypedDict, total=False):
    stage: str
    turn_count: int
    translated_count: int
    excerpt_count: int
    medicine_count: int


@dataclass
class Payload:
    segments: list[dict]
    adapter: object
    turns: list[dict] = field(default_factory=list)
    english: list[dict] = field(default_factory=list)
    draft: SoapDraft | None = None
    medicines: list[dict] = field(default_factory=list)
    on_prescription: object = None


# Isolated per invocation, like the booking adapter context. Neither transcripts
# nor model payloads are serialized into LangGraph/LangSmith state or config.
_PAYLOAD = contextvars.ContextVar("doctor_soap_payload")


def _validate(state):
    p = _PAYLOAD.get()
    text = "\n".join(str(s.get("text") or "").strip() for s in p.segments).strip()
    if not text:
        raise SoapError("Add a transcript before generating SOAP.")
    if len(text) > 60000:
        raise SoapError("Transcript is too long to generate a draft in one request.")
    return {"stage": "validated", "turn_count": sum(bool(str(s.get("text") or "").strip()) for s in p.segments)}


def _deidentify(state):
    p = _PAYLOAD.get()
    # Canonicalize labels; never trust stored speaker names as identifiers/roles.
    speakers = {}
    recordings = {}
    for s in p.segments:
        text = str(s.get("text") or "").strip()
        if not text:
            continue
        recording = str(s.get("recording_id") or s.get("session") or "legacy")
        recordings.setdefault(recording, len(recordings) + 1)
        speaker = s.get("speaker")
        key = (recording, str(speaker))
        if speaker:
            speakers.setdefault(key, f"Person {sum(k[0] == recording for k in speakers) + 1}")
        p.turns.append({"id": len(p.turns), "recording": recordings[recording],
                        "speaker": speakers.get(key, "Unidentified speaker"),
                        "text": deidentify(text).text})
    return {"stage": "deidentified"}


def _call(prompt_name, payload, stage):
    prompt = Path(__file__).with_name(prompt_name).read_text(encoding="utf-8")
    try:
        return _PAYLOAD.get().adapter.classify_json(prompt, json.dumps(payload, ensure_ascii=False)).content
    except (ModelCallError, ModelNotConfiguredError):
        # Suppress provider exception chains, which can contain sensitive bodies.
        raise SoapError(f"{stage} model unavailable. Check the server model configuration and try again.") from None


def _translate(state):
    p = _PAYLOAD.get()
    content = _call("translation_prompt.txt", {"turns": p.turns}, "Translation")
    try:
        translated = Translation.model_validate_json(content).turns
    except ValidationError:
        raise SoapError("The model returned an invalid English translation. Please try again.") from None
    if [t.id for t in translated] != [t["id"] for t in p.turns] or any(not t.text.strip() for t in translated):
        raise SoapError("Translation omitted or reordered conversation turns. Please try again.")
    if sum(len(t.text) for t in translated) > 120000:
        raise SoapError("English translation exceeds the draft size limit.")
    p.english = [{**original, "text": deidentify(t.text).text} for original, t in zip(p.turns, translated)]
    return {"stage": "translated", "translated_count": len(p.english)}


def _soap(state):
    p = _PAYLOAD.get()
    content = _call("soap_prompt.txt", {"turns": p.english}, "SOAP")
    try:
        p.draft = SoapDraft.model_validate_json(content)
    except ValidationError:
        raise SoapError("The model returned an invalid SOAP draft. Please try again.") from None
    return {"stage": "soap_generated"}


def _check(state):
    p = _PAYLOAD.get()
    sources = [" ".join(t["text"].split()) for t in p.english]
    for excerpts in p.draft.model_dump().values():
        for excerpt in excerpts:
            if not excerpt.strip() or not any(" ".join(excerpt.split()) in source for source in sources):
                raise SoapError("The draft contained text not supported by the English transcript. Please try again.")
    return {"stage": "completed", "excerpt_count": sum(len(v) for v in p.draft.model_dump().values())}
    

def _prescription(state):
    from app.consultation.prescriptions import suggest
    p = _PAYLOAD.get()
    suggestions = suggest(p.draft, p.medicines)
    if p.on_prescription:
        p.on_prescription(suggestions)
    return {'stage': 'prescription_review_ready', 'medicine_count': len(suggestions)}


def build_graph():
    graph = StateGraph(State)
    previous = START
    for name, node in [("validate_input", _validate), ("deidentify", _deidentify),
                       ("translate_to_english", _translate), ("generate_soap", _soap),
                       ("validate_soap", _check), ("medicine_prescription", _prescription)]:
        graph.add_node(name, node)
        graph.add_edge(previous, name)
        previous = name
    graph.add_edge(previous, END)
    return graph.compile()


init_tracing()
_GRAPH = build_graph()


def run_soap(segments, adapter=None, medicines=None, on_prescription=None):
    p = Payload(segments, adapter or get_adapter(), medicines=medicines or [], on_prescription=on_prescription)
    token = _PAYLOAD.set(p)
    config = run_config()
    config.update(run_name="doctor_consultation_soap", tags=["doctor", "translation", "soap"], run_id=uuid4())
    config["metadata"] = {**config["metadata"], "workflow": "doctor_consultation_soap"}
    try:
        _GRAPH.invoke({"stage": "started"}, config=config)
        return p.draft
    finally:
        _PAYLOAD.reset(token)
