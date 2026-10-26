"""Sahayog Care — FastAPI application entry point (Phase 1.1).

This is the backend skeleton: a stateless API container (PRD section 7) that
currently exposes health/metadata endpoints and allows the React frontend to
call it via CORS. Workflows (find-my-doctor, my-records, consultation-note) are
added in later phases.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.book_appointment.router import router as book_appointment_router
from app.config import settings
from app.patient.router import router as patient_router

app = FastAPI(
    title=f"{settings.app_name} API",
    version="0.1.0",
    description="Backend API for the Sahayog Care patient and doctor platform.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.frontend_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(book_appointment_router)
app.include_router(patient_router)


class HealthResponse(BaseModel):
    """Response shape for the health check endpoint."""

    status: str
    service: str
    environment: str


class RootResponse(BaseModel):
    """Response shape for the root endpoint."""

    service: str
    version: str
    message: str


@app.get("/", response_model=RootResponse, tags=["meta"])
def root() -> RootResponse:
    """Root endpoint with basic service metadata."""
    return RootResponse(
        service=settings.app_name,
        version=app.version,
        message="Sahayog Care API is running.",
    )


@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health() -> HealthResponse:
    """Liveness/health check used by the frontend and infra."""
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        environment=settings.environment,
    )
