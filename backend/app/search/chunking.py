"""Pure chunk-building functions (Phase 6.1) -- no I/O, easy to unit test.

Only ever operates on text that is already de-identified by the time it
reaches these functions (appointments.symptom_text, emergency_intakes.
deidentified_text, the signed SOAP record, extracted report text) -- see
app/search/jobs.py for where that data is fetched from.
"""
from __future__ import annotations

from dataclasses import dataclass

SOAP_SECTIONS = ("subjective", "objective", "assessment", "plan")


@dataclass
class Chunk:
    chunk_id: str
    patient_id: str | None
    doctor_id: str | None
    appointment_id: str | None
    chunk_type: str  # "symptom" | "soap" | "report"
    section: str | None
    text: str


def _symptom_text(symptoms, fallback_text) -> str:
    text = (fallback_text or "").strip()
    if text:
        return text
    labels = [str(s.get("label") or s) if isinstance(s, dict) else str(s) for s in (symptoms or [])]
    return ", ".join(label for label in labels if label)


def chunks_for_appointment(visit: dict) -> list[Chunk]:
    """One "symptom" chunk from a booked appointment's intake fields."""
    text = _symptom_text(visit.get("symptoms"), visit.get("symptom_text"))
    if not text:
        return []
    return [Chunk(
        chunk_id=f"{visit['id']}:symptom", patient_id=visit.get("patient_id"),
        doctor_id=visit.get("doctor_id"), appointment_id=visit["id"],
        chunk_type="symptom", section=None, text=text,
    )]


def chunks_for_emergency_intake(intake: dict) -> list[Chunk]:
    """One "symptom" chunk from a pending (not yet assigned) emergency intake."""
    text = _symptom_text(intake.get("symptoms"), intake.get("deidentified_text"))
    if not text:
        return []
    return [Chunk(
        chunk_id=f"intake:{intake['id']}:symptom", patient_id=intake.get("patient_id"),
        doctor_id=None, appointment_id=None, chunk_type="symptom", section=None, text=text,
    )]


def chunks_for_signed_consultation(visit: dict, signed_record: dict) -> list[Chunk]:
    """One chunk per non-empty SOAP section, from the final signed record."""
    soap = signed_record.get("soap") or {}
    chunks = []
    for section in SOAP_SECTIONS:
        lines = [str(line).strip() for line in (soap.get(section) or []) if str(line).strip()]
        if not lines:
            continue
        chunks.append(Chunk(
            chunk_id=f"{visit['id']}:soap:{section}", patient_id=visit.get("patient_id"),
            doctor_id=visit.get("doctor_id"), appointment_id=visit["id"],
            chunk_type="soap", section=section, text="\n".join(lines),
        ))
    return chunks


def chunks_for_report(report_row: dict, visit: dict, text: str | None) -> list[Chunk]:
    """One "report" chunk from extracted PDF text (see reports_text.py)."""
    text = (text or "").strip()
    if not text:
        return []
    return [Chunk(
        chunk_id=f"report:{report_row['id']}", patient_id=visit.get("patient_id"),
        doctor_id=visit.get("doctor_id"), appointment_id=visit.get("id"),
        chunk_type="report", section=None, text=text,
    )]
