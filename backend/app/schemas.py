"""Base Pydantic schemas shared across the API.

Endpoint-specific request/response models for the four module endpoints
(telemetry, crisis, triage, rationing) and the optional query endpoint are
added alongside their respective endpoints per the day-by-day build plan.
This module also holds the POST /ingest schemas, since ingestion is shared
infrastructure feeding every module's retrieval step rather than a single
module's endpoint.
"""

from enum import Enum

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Response body for GET /health."""

    status: str
    backend: str


class DocumentType(str, Enum):
    """Kinds of mission documents accepted by POST /ingest."""

    PROCEDURE = "procedure"
    SECTOR_SPEC = "sector_spec"
    CREW_FILE = "crew_file"
    INCIDENT_RECORD = "incident_record"


class MissionDocument(BaseModel):
    """A single raw mission document submitted for ingestion."""

    id: str
    type: DocumentType
    text: str = Field(min_length=1)


class IngestRequest(BaseModel):
    """Request body for POST /ingest."""

    documents: list[MissionDocument]


class IngestResponse(BaseModel):
    """Response body for POST /ingest."""

    chunks_ingested: int


class TelemetryInterpretRequest(BaseModel):
    """Request body for POST /telemetry/interpret.

    `metrics` is a flat map of raw metric name to reading, e.g.
    `{"eff": 85, "o2pp": 158, "humidity": 34}` for the oxygen sector — see
    the per-sector `state` shapes in `mission-console.html`'s Module 02.
    """

    sector_id: str = Field(min_length=1)
    metrics: dict[str, float] = Field(min_length=1)


class TelemetryInterpretResponse(BaseModel):
    """Response body for POST /telemetry/interpret.

    `confidence` is derived from retrieval strength and distance from the
    nominal band the readings are checked against (see
    `app.services.telemetry._combine_confidence`), never a random or
    fabricated placeholder number. It stays optional (`float | None`)
    rather than a required `float`: a future retrieval implementation that
    can't produce a relevance score should be able to omit it honestly
    instead of forcing a number, the same reasoning that left it `None`
    before confidence scoring existed at all.
    """

    summary: str
    confidence: float | None = None
    source: str
