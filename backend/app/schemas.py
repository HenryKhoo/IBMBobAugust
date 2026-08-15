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
