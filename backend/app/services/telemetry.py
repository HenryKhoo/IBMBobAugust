"""Grounded generation for POST /telemetry/interpret.

Takes a sector's raw metric readings from Module 02, retrieves the sector
documentation chunk that best matches those readings, and asks the Granite
instruct model for a short plain-language operational summary grounded in
that chunk. Nothing here fabricates a reading or a fact: if retrieval
finds no matching sector documentation, this module refuses to generate a
summary rather than let the model guess (see `interpret_telemetry`).

Confidence scoring is a separate follow-up (dev plan Aug 19, Task 2) and is
not computed here — see `app.schemas.TelemetryInterpretResponse`.
"""

from __future__ import annotations

from app.schemas import TelemetryInterpretResponse
from app.services.vector_store import get_vector_store
from app.services.watsonx import get_instruct_model

_PROMPT_TEMPLATE = """You are the telemetry translator for The North Star, a deep space \
habitat's mission console. You turn raw sector sensor readings into a short, \
plain-language operational summary for the crew.

Base your summary strictly on the sector documentation and readings below. \
Do not invent facts, thresholds, or recommendations that are not supported \
by this documentation. If a reading falls outside the nominal band the \
documentation describes, say so plainly and state the recommended action \
the documentation gives, if any. Keep the summary to two or three sentences.

Sector documentation:
{chunk_text}

Sector: {sector_id}
Raw readings: {readings}

Plain-language summary:"""


def _build_retrieval_query(sector_id: str, metrics: dict[str, float]) -> str:
    """Build the text used to semantically match sector documentation.

    Sector spec chunks carry no `sector_id` in their metadata (see
    `app.services.ingestion.Chunk.metadata`) — they're free text tagged
    only with `doc_id`/`doc_type`/`chunk_index`. So "the right sector
    chunk" is found by similarity between this query text and the embedded
    documentation, not by an exact metadata match.
    """
    readings = ", ".join(f"{name}={value}" for name, value in metrics.items())
    return f"{sector_id} sector telemetry: {readings}"


def _build_prompt(chunk_text: str, sector_id: str, metrics: dict[str, float]) -> str:
    readings = ", ".join(f"{name}={value}" for name, value in metrics.items())
    return _PROMPT_TEMPLATE.format(
        chunk_text=chunk_text, sector_id=sector_id, readings=readings
    )


def _source_line(metadata: dict) -> str:
    return f"{metadata['doc_type']}:{metadata['doc_id']}#chunk{metadata['chunk_index']}"


def interpret_telemetry(
    sector_id: str, metrics: dict[str, float]
) -> TelemetryInterpretResponse:
    """Retrieve the matching sector documentation and generate a grounded summary.

    Raises `LookupError` if no `sector_spec` documentation is found for
    this sector's readings — callers (see `app.main`) should map that to a
    404 rather than fall back to an ungrounded summary. `confidence` in the
    response is always `None`; see the module docstring.
    """
    query = _build_retrieval_query(sector_id, metrics)
    hits = get_vector_store().similarity_search(
        query, k=1, expr="doc_type == 'sector_spec'"
    )
    if not hits:
        raise LookupError(
            f"No sector documentation found for sector '{sector_id}'. "
            "Ingest sector specs via POST /ingest first."
        )

    chunk = hits[0]
    prompt = _build_prompt(chunk.page_content, sector_id, metrics)
    message = get_instruct_model().invoke(prompt)
    summary = str(message.content).strip()

    return TelemetryInterpretResponse(
        summary=summary,
        confidence=None,
        source=_source_line(chunk.metadata),
    )
