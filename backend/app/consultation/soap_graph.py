"""Translation -> SOAP graph; clinical payloads stay outside traced state.

Checkpointing (Phase 5): only data already sent to the consultation LLM
(de-identified turns, their English translation, and the SOAP draft) is ever
placed into graph ``State``, so the optional Postgres checkpointer never
stores anything more sensitive than what already left the process for every
SOAP job. Raw, pre-de-identification transcript segments stay in the
per-invocation ``Payload`` contextvar as before; they are durably stored
separately (``transcripts/<id>.json``) and are re-supplied fresh by the
caller on every attempt, so they never need to be checkpointed.
"""
import contextvars
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.book_appointment.deidentify import deidentify
from app.book_appointment.model_adapter import get_adapter, ModelCallError, ModelNotConfiguredError
from app.book_appointment.tracing import init_tracing, run_config
from app.config import settings
from app.consultation.soap import SoapDraft, SoapError

logger = logging.getLogger(__name__)


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
    flagged_count: int
    medicine_count: int
    # Checkpointed so a resumed run (same thread_id) can skip completed LLM
    # calls. See module docstring for the PHI boundary this respects.
    turns: list[dict]
    english: list[dict]
    draft: dict


@dataclass
class Payload:
    segments: list[dict]
    adapter: object
    turns: list[dict] = field(default_factory=list)
    english: list[dict] = field(default_factory=list)
    draft: SoapDraft | None = None
    medicines: list[dict] = field(default_factory=list)
    on_prescription: object = None
    # Appointment ID only, for log lines. Never anything clinical.
    consultation_id: str | None = None


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
    if state.get("turns"):
        # Resuming from a checkpoint: the de-identified turns already exist.
        p.turns = state["turns"]
        return {"stage": "deidentified"}
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
    return {"stage": "deidentified", "turns": p.turns}


def _call(prompt_name, payload, stage):
    prompt = Path(__file__).with_name(prompt_name).read_text(encoding="utf-8")
    try:
        return _PAYLOAD.get().adapter.classify_json(prompt, json.dumps(payload, ensure_ascii=False)).content
    except (ModelCallError, ModelNotConfiguredError) as exc:
        # Log only the underlying exception's type (e.g. APITimeoutError,
        # RateLimitError) -- never its message, which can echo provider
        # request/response bodies. This is enough to tell a slow model apart
        # from a bad key or a rate limit without risking sensitive content.
        logger.warning("soap: %s model call failed (%s)", stage, type(exc.__cause__ or exc).__name__)
        # Suppress provider exception chains in what reaches the client.
        raise SoapError(f"{stage} model unavailable. Check the server model configuration and try again.") from None


def _translate(state):
    p = _PAYLOAD.get()
    if state.get("english"):
        # Resuming from a checkpoint: skip paying for translation again.
        logger.info("soap visit=%s: translating to English - resumed from checkpoint, skipping LLM call",
                    p.consultation_id)
        p.english = state["english"]
        return {"stage": "translated"}
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
    return {"stage": "translated", "translated_count": len(p.english), "english": p.english}


def _soap(state):
    p = _PAYLOAD.get()
    if state.get("draft"):
        # Resuming from a checkpoint: skip paying for SOAP extraction again.
        logger.info("soap visit=%s: generating SOAP - resumed from checkpoint, skipping LLM call",
                    p.consultation_id)
        p.draft = SoapDraft.model_validate(state["draft"])
        return {"stage": "soap_generated"}
    content = _call("soap_prompt.txt", {"turns": p.english}, "SOAP")
    try:
        p.draft = SoapDraft.model_validate_json(content)
    except ValidationError:
        raise SoapError("The model returned an invalid SOAP draft. Please try again.") from None
    return {"stage": "soap_generated", "draft": p.draft.model_dump(mode="json")}


def _tokenize(text):
    return re.findall(r"[a-z0-9]+", text.lower())


# Clinical-voice scaffolding the prompt explicitly asks the model to add
# (e.g. "Patient reports...") plus common stopwords. Excluded from the
# grounding check so rephrasing into clinical language isn't mistaken for
# fabrication -- the check should only flag substantive invented content.
_GROUNDING_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "and", "or", "of", "to", "in",
    "on", "for", "with", "at", "by", "it", "that", "this", "patient", "patients",
    "reports", "report", "reported", "reporting", "denies", "denied", "denying",
    "states", "stated", "stating", "complains", "complained", "complaining",
    "notes", "noted", "mentions", "mentioned",
}


def _grounding_ratio(excerpt, source_words):
    """Fraction of the excerpt's substantive words that appear somewhere in
    the English transcript (bag-of-words, not phrase order) -- see
    ``_check`` docstring for why this replaced an exact-substring match.
    Returns (ratio, unmatched_words); ratio is 1.0 for an excerpt with no
    substantive words left after stripping scaffolding/stopwords.
    """
    words = [w for w in _tokenize(excerpt) if (len(w) > 2 or w.isdigit()) and w not in _GROUNDING_STOPWORDS]
    if not words:
        return 1.0, []
    unmatched = [w for w in words if w not in source_words]
    return (len(words) - len(unmatched)) / len(words), unmatched


def _check(state):
    """Flag (but no longer block on) excerpts that look unsupported.

    Paraphrasing into clinical-note voice means an excerpt's words will
    legitimately diverge from the transcript's wording (synonyms, tense,
    person), so a word-overlap threshold strict enough to catch real
    fabrication also produces false positives on good paraphrases -- and
    discarding two already-paid-for LLM calls over a false positive is worse
    than letting the doctor's existing mandatory review catch it. This now
    logs a warning (visit, section, ratio, unmatched words) instead of
    raising, so a human can look twice at anything flagged while regenerate
    always completes. A hard reject is kept for genuinely empty excerpts,
    which indicate a real formatting bug, not a grounding question.
    """
    p = _PAYLOAD.get()
    source_words = set(_tokenize(" ".join(t["text"] for t in p.english)))
    draft = p.draft.model_dump()
    flagged = 0
    for section, excerpts in draft.items():
        for excerpt in excerpts:
            if not excerpt.strip():
                raise SoapError("The draft contained an empty entry. Please try again.")
            ratio, unmatched = _grounding_ratio(excerpt, source_words)
            if ratio < 0.5:
                flagged += 1
                logger.warning(
                    "soap visit=%s: %s entry only %.0f%% grounded (unmatched: %s): %r",
                    p.consultation_id, section, ratio * 100, ", ".join(unmatched[:8]), excerpt,
                )
    return {"stage": "completed", "excerpt_count": sum(len(v) for v in draft.values()), "flagged_count": flagged}
    

def _prescription(state):
    from app.consultation.prescriptions import suggest
    p = _PAYLOAD.get()
    suggestions = suggest(p.draft, p.medicines)
    if p.on_prescription:
        p.on_prescription(suggestions)
    return {'stage': 'prescription_review_ready', 'medicine_count': len(suggestions)}


_STAGE_LABELS = {
    "validate_input": "validating transcript",
    "deidentify": "de-identifying",
    "translate_to_english": "translating to English",
    "generate_soap": "generating SOAP",
    "validate_soap": "validating SOAP against source",
    "medicine_prescription": "suggesting medicines",
}


def _traced(name, fn):
    """Wrap a node so every stage logs a clear starting/done/failed line.

    This is what shows up in the terminal/deployment logs as consultation
    progress: "soap visit=<id>: <stage> - starting" / "- done" / "- failed:
    <reason>". Never logs transcript/model content, only the stage name,
    the appointment id, and (on failure) the user-facing error message.
    """
    label = _STAGE_LABELS.get(name, name)

    def wrapped(state):
        consultation_id = _PAYLOAD.get().consultation_id
        logger.info("soap visit=%s: %s - starting", consultation_id, label)
        try:
            result = fn(state)
        except Exception as exc:
            logger.warning("soap visit=%s: %s - failed: %s", consultation_id, label, exc)
            raise
        logger.info("soap visit=%s: %s - done", consultation_id, label)
        return result
    return wrapped


def _build_checkpointer():
    """A pooled Postgres checkpointer, or None when unconfigured/unreachable.

    A pool (not a single shared connection) because up to two SOAP jobs for
    different appointments can run concurrently in this process (main.py
    starts two worker tasks), and a psycopg connection is not safe to share
    across concurrent callers.
    """
    if not settings.consultation_checkpointing_configured:
        return None
    pool = None
    try:
        from psycopg_pool import ConnectionPool
        from langgraph.checkpoint.postgres import PostgresSaver
        pool = ConnectionPool(
            conninfo=settings.consultation_checkpoint_db_url, max_size=5, open=True, timeout=10,
            kwargs={"autocommit": True, "prepare_threshold": 0},
        )
        saver = PostgresSaver(pool)
        saver.setup()
        return saver
    except Exception:
        logger.warning("Consultation checkpointer unavailable; SOAP graph will run without resumable checkpoints.")
        if pool is not None:
            # Otherwise the pool keeps retrying the unreachable DB forever
            # in a background thread with nothing left to use it.
            pool.close()
        return None


def build_graph():
    graph = StateGraph(State)
    previous = START
    for name, node in [("validate_input", _validate), ("deidentify", _deidentify),
                       ("translate_to_english", _translate), ("generate_soap", _soap),
                       ("validate_soap", _check), ("medicine_prescription", _prescription)]:
        graph.add_node(name, _traced(name, node))
        graph.add_edge(previous, name)
        previous = name
    graph.add_edge(previous, END)
    return graph.compile(checkpointer=_build_checkpointer())


init_tracing()
_GRAPH = build_graph()


def run_soap(segments, adapter=None, medicines=None, on_prescription=None, thread_id=None, consultation_id=None):
    p = Payload(segments, adapter or get_adapter(), medicines=medicines or [], on_prescription=on_prescription,
                consultation_id=consultation_id)
    token = _PAYLOAD.set(p)
    config = run_config(thread_id)
    config.update(run_name="doctor_consultation_soap", tags=["doctor", "translation", "soap"], run_id=uuid4())
    config["metadata"] = {**config["metadata"], "workflow": "doctor_consultation_soap"}
    if _GRAPH.checkpointer:
        # LangGraph requires a thread_id/checkpoint_ns/checkpoint_id in
        # `configurable` whenever the compiled graph has *any* checkpointer
        # bound, even for a call that doesn't care about resuming. Without a
        # real thread_id, use a disposable one -- this run still completes
        # normally, it just isn't resumable (same as before checkpointing
        # existed for ad hoc, non-resumable callers like the unit tests).
        config["configurable"] = {**config.get("configurable", {}), "thread_id": thread_id or str(uuid4())}
    logger.info("soap visit=%s: starting (segments=%d)", consultation_id, len(segments))
    try:
        _GRAPH.invoke({"stage": "started"}, config=config)
        logger.info("soap visit=%s: finished", consultation_id)
        return p.draft
    finally:
        _PAYLOAD.reset(token)
