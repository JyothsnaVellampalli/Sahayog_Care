"""Application configuration.

All configuration is read from environment variables. No secrets are hard-coded
(PRD section 9: "Read configuration from environment variables. Commit
`.env.example` only.").
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve the backend .env by absolute path so it loads no matter which
# directory the server is launched from (app/config.py -> backend/.env).
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_ENV_FILE = _BACKEND_DIR / ".env"


class Settings(BaseSettings):
    """Runtime settings, loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App metadata
    app_name: str = "Sahayog Care"
    environment: str = "development"
    # App-wide validation switch; never expose other settings through the API.
    show_speech_transcripts: bool = False

    # CORS: origins allowed to call the API (the React dev server by default).
    frontend_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # Supabase (free tier) — kept out of code per PRD section 9.
    supabase_url: str | None = None
    supabase_anon_key: str | None = None
    supabase_service_key: str | None = None

    # OpenRouter (swappable vendor behind one adapter — PRD section 7).
    openrouter_api_key: str | None = None
    openrouter_model: str = "google/gemini-3.8-flash"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_timeout_seconds: float = 30.0

    # Jev decisions model — the symptom triage classifier. Unlike a chat model,
    # Jev returns a typed decision with per-category probabilities (weightage),
    # not text. Uses the same OPENROUTER_API_KEY.
    symptom_classifier_model: str = "typesafe/jev-1.13"
    open_router_classifier_url: str = "https://openrouter.ai/api/alpha/decisions"

    # Object storage (Phase 2.1): signatures + transcripts. S3 when configured,
    # otherwise a local folder under the backend (dev fallback).
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_region: str = "ap-south-1"
    s3_bucket: str | None = None
    s3_prefix: str = ""
    local_storage_dir: str = "storage"

    # Sarvam is the only speech recognition and speaker separation provider.
    sarvam_api_key: str | None = None
    sarvam_stt_model: str = "saaras:v4"
    sarvam_timeout_seconds: float = 60.0
    sarvam_max_audio_bytes: int = 100 * 1024 * 1024

    @property
    def s3_configured(self) -> bool:
        return bool(
            self.aws_access_key_id and self.aws_secret_access_key and self.s3_bucket
        )

    # LangSmith tracing (observability/audit — PRD section 7).
    langsmith_tracing: bool = False
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_api_key: str | None = None
    langsmith_agent_id: str = "sahayog-care"
    langsmith_agent_environment: str = "local"
    # Optional explicit project name; if unset, derived as
    # "{agent_id}-{environment}" (e.g. sahayog-care-local).
    langsmith_project: str | None = None

    @property
    def langsmith_project_name(self) -> str:
        return (
            self.langsmith_project
            or f"{self.langsmith_agent_id}-{self.langsmith_agent_environment}"
        )

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_key)

    @property
    def openrouter_configured(self) -> bool:
        return bool(self.openrouter_api_key)

    @property
    def classifier_configured(self) -> bool:
        """The Jev classifier needs the OpenRouter key and the decisions URL."""
        return bool(self.openrouter_api_key and self.open_router_classifier_url)

    @property
    def langsmith_configured(self) -> bool:
        """Tracing is active only when enabled and an API key is present."""
        return bool(self.langsmith_tracing and self.langsmith_api_key)


settings = Settings()
