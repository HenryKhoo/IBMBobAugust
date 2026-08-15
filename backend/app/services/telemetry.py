"""Grounded generation for POST /telemetry/interpret.

Takes a sector's raw metric readings from Module 02, retrieves the sector
documentation chunk that best matches those readings, and asks the Granite
instruct model for a short plain-language operational summary grounded in
that chunk. Nothing here fabricates a reading or a fact: if retrieval
finds no matching sector documentation, this module refuses to generate a
summary rather than let the model guess (see `interpret_telemetry`).

Confidence scoring (dev plan Aug 19, Task 2) combines two real signals,
never a random or filler number:

- Retrieval strength — how well the retrieved chunk matched the query, via
  `similarity_search_with_relevance_scores` (see `_retrieval_strength`).
- Distance from the nominal band — how far the request's readings fall
  from the thresholds `app.services.extraction.extract_sector_thresholds`
  parses out of the retrieved chunk's own text (see `_band_conformity`).

If a reading can't be matched to a threshold (see `app.services.
metric_aliases`), the band signal is simply absent for that response —
confidence falls back to retrieval strength alone rather than guessing a
neutral filler value (see `_combine_confidence`).
"""

from __future__ import annotations

import re

from app.schemas import TelemetryInterpretResponse
from app.services.extraction import SectorThreshold, extract_sector_thresholds
from app.services.metric_aliases import METRIC_ALIASES
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

_CONFIDENCE_WEIGHT_RETRIEVAL = 0.5
_CONFIDENCE_WEIGHT_BAND = 0.5


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


def _retrieval_strength(relevance_score: float) -> float:
    """Normalize a retrieval relevance score to a [0, 1] confidence signal.

    `relevance_score` comes from `similarity_search_with_relevance_scores`,
    which langchain-milvus already normalizes to `[0, 1]` regardless of
    whether the live Zilliz collection's index uses L2, IP, or COSINE —
    see `Milvus._select_relevance_score_fn`. That normalization falls back
    to an L2 mapping (with a logged warning) if it can't determine the
    collection's actual metric type, so this hasn't been verified against
    the live collection specifically — only against how this codebase
    would create one. Clamped defensively either way, since the library's
    own base implementation warns rather than clamps when a score lands
    outside `[0, 1]`.
    """
    return max(0.0, min(1.0, relevance_score))


def _normalize_metric_name(name: str) -> str:
    """Normalize a metric name for alias/threshold matching.

    Lowercases and collapses everything that isn't a letter or digit into
    a single space, so "Cabin pressure (kPa)" and "cabin pressure" compare
    equal without requiring wording/punctuation to match exactly.
    """
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def _metric_conformity(value: float, threshold: SectorThreshold) -> float | None:
    """How well one reading conforms to its nominal band, in [0, 1].

    `1.0` inside `[low, high]`. Outside the band, conformity decays with
    the reading's distance past the nearer edge, relative to the band's
    own width — a reading one full band-width outside the band scores
    `0.0`. Returns `None` (rather than a guess) if the band has zero or
    negative width, since "distance relative to band width" is undefined
    there.
    """
    band_width = threshold.high - threshold.low
    if band_width <= 0:
        return None
    if threshold.low <= value <= threshold.high:
        return 1.0
    excess = threshold.low - value if value < threshold.low else value - threshold.high
    return max(0.0, 1 - excess / band_width)


def _band_conformity(chunk_text: str, metrics: dict[str, float]) -> float | None:
    """Average nominal-band conformity across the readings that could be matched.

    Parses thresholds from the retrieved chunk's own text (no separate
    lookup), then matches each request metric to a threshold via
    `app.services.metric_aliases.METRIC_ALIASES`. A metric with no alias
    entry, or whose aliased name doesn't appear among the chunk's parsed
    thresholds, contributes no signal — it is skipped, not scored as
    non-conforming. Returns `None` if nothing could be matched at all, so
    the caller can fall back to retrieval strength alone instead of
    combining with a meaningless average of zero terms.
    """
    thresholds = extract_sector_thresholds(chunk_text)
    if not thresholds:
        return None

    thresholds_by_name = {
        _normalize_metric_name(threshold.metric): threshold for threshold in thresholds
    }

    conformities: list[float] = []
    for metric_key, value in metrics.items():
        canonical_name = METRIC_ALIASES.get(metric_key.lower())
        if canonical_name is None:
            continue
        threshold = thresholds_by_name.get(_normalize_metric_name(canonical_name))
        if threshold is None:
            continue
        conformity = _metric_conformity(value, threshold)
        if conformity is not None:
            conformities.append(conformity)

    if not conformities:
        return None
    return sum(conformities) / len(conformities)


def _combine_confidence(retrieval_strength: float, band_conformity: float | None) -> float:
    """Combine the two confidence signals into one score in [0, 1].

    Weighted evenly across both signals when a band signal exists. When it
    doesn't (see `_band_conformity`), confidence is retrieval strength
    alone — the weight isn't redistributed to a fabricated neutral value
    for the missing signal, per the dev plan's "never a random number"
    rule. Rounded to two decimal places for the API response.
    """
    if band_conformity is None:
        combined = retrieval_strength
    else:
        combined = (
            _CONFIDENCE_WEIGHT_RETRIEVAL * retrieval_strength
            + _CONFIDENCE_WEIGHT_BAND * band_conformity
        )
    return round(max(0.0, min(1.0, combined)), 2)


def interpret_telemetry(
    sector_id: str, metrics: dict[str, float]
) -> TelemetryInterpretResponse:
    """Retrieve the matching sector documentation and generate a grounded summary.

    Raises `LookupError` if no `sector_spec` documentation is found for
    this sector's readings — callers (see `app.main`) should map that to a
    404 rather than fall back to an ungrounded summary. `confidence` in the
    response is derived from real retrieval and nominal-band signals; see
    the module docstring.
    """
    query = _build_retrieval_query(sector_id, metrics)
    hits = get_vector_store().similarity_search_with_relevance_scores(
        query, k=1, expr="doc_type == 'sector_spec'"
    )
    if not hits:
        raise LookupError(
            f"No sector documentation found for sector '{sector_id}'. "
            "Ingest sector specs via POST /ingest first."
        )

    chunk, relevance_score = hits[0]
    prompt = _build_prompt(chunk.page_content, sector_id, metrics)
    message = get_instruct_model().invoke(prompt)
    summary = str(message.content).strip()

    confidence = _combine_confidence(
        _retrieval_strength(relevance_score),
        _band_conformity(chunk.page_content, metrics),
    )

    return TelemetryInterpretResponse(
        summary=summary,
        confidence=confidence,
        source=_source_line(chunk.metadata),
    )
