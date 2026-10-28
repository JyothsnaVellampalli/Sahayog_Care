"""Sarvam-only transcription jobs and editable transcript storage.

Speaker IDs are scoped to a recording, never inferred doctor/patient roles.
Audio is transferred to Sarvam but is not persisted by this application.
"""
from datetime import datetime, timezone
from threading import RLock

import httpx
from pydantic import BaseModel, Field, ValidationError

from app import storage
from app.config import settings
from app.consultation.sarvam import SarvamClient, SarvamError

_TRANSCRIPT_LOCK = RLock()
_MIME_EXTENSIONS = {
    "audio/webm": "webm", "video/webm": "webm", "audio/ogg": "ogg",
    "audio/mp4": "m4a", "video/mp4": "mp4", "audio/wav": "wav",
    "audio/x-wav": "wav", "audio/mpeg": "mp3",
}


def _transcript_key(consultation_id: str) -> str:
    return f"transcripts/{consultation_id}.json"


def load_transcript(consultation_id: str) -> list[dict]:
    data = storage.get_json(_transcript_key(consultation_id))
    if isinstance(data, dict):
        return data.get("segments", [])
    return data if isinstance(data, list) else []


def save_transcript(consultation_id: str, segments: list[dict]) -> str:
    return storage.put_json(_transcript_key(consultation_id), {
        "consultation_id": consultation_id, "segments": segments,
    })


def _now_hhmm() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%H:%M")


def append_segment(consultation_id: str, speaker: str | None, text: str, session: int = 1) -> list[dict]:
    with _TRANSCRIPT_LOCK:
        segments = load_transcript(consultation_id)
        segments.append({"speaker": speaker, "text": text, "ts": _now_hhmm(),
                         "edited": False, "session": session})
        save_transcript(consultation_id, segments)
        return segments


def edit_segment(consultation_id: str, index: int, text: str) -> list[dict]:
    with _TRANSCRIPT_LOCK:
        segments = load_transcript(consultation_id)
        if 0 <= index < len(segments):
            segments[index].update(text=text, edited=True)
        save_transcript(consultation_id, segments)
        return segments


class SpeakerEntry(BaseModel):
    transcript: str
    speaker_id: str | int | None = None
    start_time_seconds: float = Field(ge=0, allow_inf_nan=False)
    end_time_seconds: float = Field(ge=0, allow_inf_nan=False)


def normalize_result(result: dict, recording_id: str, session: int) -> list[dict]:
    """Preserve scripts and timestamps; assign neutral labels by first appearance."""
    if "transcript" not in result and "diarized_transcript" not in result:
        raise SarvamError("Sarvam returned an invalid transcript response.")
    diarized = result.get("diarized_transcript") or {}
    entries = diarized.get("entries") if isinstance(diarized, dict) else None
    if not entries:
        if str(result.get("transcript") or "").strip():
            raise SarvamError("Sarvam returned text without speaker turns. Please retry with diarization enabled.")
        return []
    try:
        turns = sorted([SpeakerEntry.model_validate(e) for e in entries], key=lambda e: e.start_time_seconds)
    except (ValidationError, TypeError):
        raise SarvamError("Sarvam returned invalid speaker turns.") from None
    speakers: dict[str, str] = {}
    segments = []
    for turn in turns:
        if turn.end_time_seconds < turn.start_time_seconds:
            raise SarvamError("Sarvam returned invalid turn timestamps.")
        if not turn.transcript.strip():
            continue
        identifier = str(turn.speaker_id) if turn.speaker_id is not None else ""
        if identifier:
            speakers.setdefault(identifier, f"Person {len(speakers) + 1}")
        segments.append({
            "speaker": speakers.get(identifier, "Unidentified speaker"),
            "provider_speaker_id": identifier or None,
            "recording_id": recording_id, "session": session,
            "start_seconds": turn.start_time_seconds, "end_seconds": turn.end_time_seconds,
            "text": turn.transcript.strip(), "ts": _now_hhmm(), "edited": False,
            "language_code": result.get("language_code"), "source": "sarvam",
        })
    return segments


def _job_key(consultation_id: str, recording_id: str) -> str:
    return f"transcription_jobs/{consultation_id}/{recording_id}.json"


async def submit_recording(consultation_id: str, recording_id: str, audio: bytes,
                           mime_type: str, session: int) -> dict:
    mime = mime_type.split(";")[0].lower().strip()
    if mime not in _MIME_EXTENSIONS:
        raise SarvamError("Unsupported recording format. Use WebM, Ogg, MP4, WAV or MP3.")
    if not audio or len(audio) > settings.sarvam_max_audio_bytes:
        raise SarvamError("Recording is empty or exceeds the configured audio upload limit.")
    key = _job_key(consultation_id, recording_id)
    job = storage.get_json(key)
    async with httpx.AsyncClient(timeout=settings.sarvam_timeout_seconds) as http:
        client = SarvamClient(http)
        if not job:
            job = {"job_id": await client.create(), "session": session, "uploaded": False}
            storage.put_json(key, job)
        if job.get("completed"):
            return {"recording_id": recording_id, "state": "Completed"}
        if not job["uploaded"]:
            await client.upload(job["job_id"], audio, f"recording.{_MIME_EXTENSIONS[mime]}", mime)
            job["uploaded"] = True
            storage.put_json(key, job)
        status = await client.status(job["job_id"])
        if status.get("job_state") == "Accepted":
            await client.start(job["job_id"])
    return {"recording_id": recording_id, "state": "Processing"}


async def poll_recording(consultation_id: str, recording_id: str) -> dict:
    key = _job_key(consultation_id, recording_id)
    job = storage.get_json(key)
    if not job:
        raise SarvamError("Recording job not found. Retry uploading the recording.")
    if job.get("completed"):
        return {"state": "Completed", "segments": load_transcript(consultation_id), "note": job.get("note")}
    if not job.get("uploaded"):
        raise SarvamError("Audio upload was interrupted. Retry uploading the recording.")
    async with httpx.AsyncClient(timeout=settings.sarvam_timeout_seconds) as http:
        client = SarvamClient(http)
        status = await client.status(job["job_id"])
        state = status.get("job_state")
        if state == "Failed":
            return {"state": "Failed", "note": "Sarvam could not process the recording. Make a new recording."}
        if state == "Accepted":
            await client.start(job["job_id"])
        if state in ("Accepted", "Pending", "Running"):
            return {"state": "Processing"}
        if state != "Completed":
            raise SarvamError("Sarvam returned an unexpected job status. Please retry checking.")
        result = await client.result(job["job_id"], status)
    turns = normalize_result(result, recording_id, job["session"])
    with _TRANSCRIPT_LOCK:
        segments = load_transcript(consultation_id)
        if not any(s.get("recording_id") == recording_id for s in segments):
            segments.extend(turns)
            save_transcript(consultation_id, segments)
        note = None if turns else "No speech was detected in this recording."
        job.update(completed=True, note=note)
        storage.put_json(key, job)
    return {"state": "Completed", "segments": segments, "note": note}
