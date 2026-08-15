"""Base Pydantic schemas shared across the API.

Endpoint-specific request/response models (telemetry, crisis, triage,
rationing, ingest, query) are added alongside their respective endpoints
per the day-by-day build plan. This module starts with the schemas the
health check needs.
"""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Response body for GET /health."""

    status: str
    backend: str
