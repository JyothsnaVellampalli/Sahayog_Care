"""Book-an-appointment module (Phase 1.2).

Responsible for the appointment booking intake flow: the patient selects
symptoms and adds free text, the free text is de-identified, and a classifier
categorises the condition as Emergency, Severe or Normal.

Public entry point: `run_intake` in `app.book_appointment.graph`.
"""

from app.book_appointment.graph import run_intake

__all__ = ["run_intake"]
