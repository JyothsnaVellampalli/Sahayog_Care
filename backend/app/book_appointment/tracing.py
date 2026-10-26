"""LangSmith tracing setup for the booking flow (PRD section 7: observability
and audit; every run has a trace id).

LangGraph/LangChain emit traces automatically when the ``LANGSMITH_*`` (and the
legacy ``LANGCHAIN_*``) environment variables are set. Our settings are loaded
from ``.env`` via pydantic-settings, which does not always export them to
``os.environ`` where the SDK looks — so this module copies the resolved values
into ``os.environ`` once, at import time.

Traces show each graph node (validate_input, deidentify, classify) as a span.
We attach safe metadata (category, scores, removed-identifier *types*) via the
run config — never raw free text or identifier values (PRD section 9).
"""

from __future__ import annotations

import os

from app.config import settings

# LangSmith project for this app. Derived from the agent id + environment
# (e.g. "sahayog-care-local") so traces land in the project you watch, or an
# explicit LANGSMITH_PROJECT override.
PROJECT_NAME = settings.langsmith_project_name

_INITIALISED = False


def init_tracing() -> bool:
    """Export LangSmith env vars so LangGraph auto-traces. Idempotent.

    Returns True if tracing is configured and enabled, else False.
    """
    global _INITIALISED
    if _INITIALISED:
        return settings.langsmith_configured

    if settings.langsmith_configured:
        # Set both the new and legacy variable names the SDK understands.
        # Tracing flags/keys use setdefault (respect anything already exported),
        # but the project and endpoint are set authoritatively so traces always
        # land in the project this app expects.
        os.environ.setdefault("LANGSMITH_TRACING", "true")
        os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
        os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
        os.environ["LANGCHAIN_ENDPOINT"] = settings.langsmith_endpoint
        os.environ.setdefault("LANGSMITH_API_KEY", settings.langsmith_api_key or "")
        os.environ.setdefault("LANGCHAIN_API_KEY", settings.langsmith_api_key or "")
        os.environ["LANGSMITH_PROJECT"] = PROJECT_NAME
        os.environ["LANGCHAIN_PROJECT"] = PROJECT_NAME

    _INITIALISED = True
    return settings.langsmith_configured


def run_config(thread_id: str | None = None) -> dict:
    """Build a LangGraph run config that gives the trace a clear name + tags.

    The run name and tags make the trace easy to identify in LangSmith for
    debugging and audit. No patient data is placed here.
    """
    metadata = {
        "agent_id": settings.langsmith_agent_id,
        "environment": settings.langsmith_agent_environment,
        "workflow": "book_appointment",
    }
    if thread_id:
        metadata["thread_id"] = thread_id
    return {
        "run_name": "book_appointment_intake",
        "tags": ["book_appointment", "triage", settings.langsmith_agent_environment],
        "metadata": metadata,
    }
