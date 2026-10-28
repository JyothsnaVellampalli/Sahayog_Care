"""Public schema and entry point for the translated, unsigned SOAP draft."""
from pydantic import BaseModel, ConfigDict, Field

from app import storage


class SoapError(RuntimeError):
    """A draft could not be generated or validated."""


class SoapDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    subjective: list[str] = Field(max_length=50)
    objective: list[str] = Field(max_length=50)
    assessment: list[str] = Field(max_length=50)
    plan: list[str] = Field(max_length=50)


def save_draft(consultation_id: str, draft: SoapDraft) -> str:
    """Persist the latest validated draft using the transcript storage backend."""
    return storage.put_json(
        f"soap/{consultation_id}.json", draft.model_dump(mode="json")
    )


def load_draft(consultation_id: str) -> SoapDraft | None:
    data = storage.get_json(f"soap/{consultation_id}.json", strict=True)
    if data is None:
        return None
    # Accept older files that also included consultation_id.
    return SoapDraft.model_validate({key: data[key] for key in SoapDraft.model_fields})


def generate_draft(segments: list[dict], adapter=None) -> SoapDraft:
    """Run translation and SOAP through the traced consultation graph."""
    from app.consultation.soap_graph import run_soap
    return run_soap(segments, adapter)
