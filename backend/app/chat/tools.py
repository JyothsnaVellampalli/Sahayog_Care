"""Patient-scoped agent tools (Phase 6.3).

Every tool here is built fresh per request by build_tools(patient_id),
closing over the already-verified patient_id -- the model is never given a
patient_id parameter to set, so there is no code path by which the agent
can be asked to fetch another patient's data. This is the same hard
server-side boundary Phase 6.2's retrieval endpoint already enforces,
extended to these two new structured-data lookups.
"""
from __future__ import annotations

import logging

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def build_tools(patient_id: str):
    """Return this patient's three tools, each with patient_id baked in."""

    @tool(response_format="content_and_artifact")
    def search_my_records(query: str):
        """Search this patient's own symptom notes, SOAP summaries and
        report text for anything relevant to the query. Use this for any
        question about what was discussed, found, or recorded during a
        visit. Returns a list of matching excerpts with their source
        (symptom/soap/report), section, and the appointment they came
        from -- cite these in the answer, never invent what they say."""
        from app.search import retrieval, search
        doctors, appointments = retrieval.candidate_filters(patient_id)
        plan = retrieval.plan_query(query, doctors, appointments)
        results = search.search_chunks(query, patient_id, plan)
        # content_and_artifact: the model sees the string content; agent.ask()
        # reads the artifact (the real, unstringified chunk list) back out of
        # the ToolMessage to build non-hallucinated citations for the reply.
        return str(results), results

    @tool
    def list_my_appointments() -> list[dict]:
        """List this patient's appointments (past and upcoming) with their
        date, doctor, specialty and status. Use this to find an
        appointment's exact id/date before asking for its details, or to
        answer "when was my last visit"-style questions."""
        from app.patient.service import list_appointments
        return [
            {"id": v.get("id"), "type": v.get("type"), "status": v.get("status"),
             "starts_at": v.get("starts_at"), "doctor_name": v.get("doctor_name"),
             "specialty": v.get("specialty")}
            for v in list_appointments(patient_id)
        ]

    @tool
    def get_appointment_details(appointment_id: str) -> dict:
        """Get the exact signed SOAP summary, prescription and status for
        one specific appointment by its id (from list_my_appointments).
        Only ever returns data if the appointment belongs to this patient."""
        from app.patient.service import appointment_detail
        return appointment_detail(patient_id, appointment_id) or {
            "error": "No appointment found with that id for this patient."
        }

    return [search_my_records, list_my_appointments, get_appointment_details]
