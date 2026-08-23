"""Retrieval-only search for POST /query.

Dev plan Aug 26, Task 1 ("Build the /query endpoint for the mission log
corpus"). Unlike the four grounded-generation endpoints (telemetry,
crisis, triage, rationing), /query never asks the instruct model to
generate anything — per the dev plan (Section 4: "Searches the embedded
mission log corpus in Zilliz. Returns matching passages with source
references") and the README ("search the mission log and procedure
library directly, and get an answer sourced back to the passage it came
from"), the retrieved passages themselves are the answer.

Two consequences follow from having no generation step:

- No `LookupError`-on-empty-retrieval. The other four services raise
  `LookupError` when nothing is retrieved (see e.g.
  `app.services.crisis.analyze_crisis`) specifically to stop the instruct
  model from generating an ungrounded guess — `app.main` maps that to a
  404. `run_query` has no generated claim to protect against, so a
  question that matches nothing in the corpus is simply an empty
  `results` list, not an error.
- `relevance` per result is retrieval strength alone (see `_relevance`),
  not a combined signal. `TelemetryInterpretResponse.confidence` and
  `TriageResponse.confidence` blend retrieval strength with a second,
  domain-specific signal (nominal-band conformity, an allergy check).
  /query has no such second signal to blend in.

Retrieval also spans the whole ingested corpus, with no `doc_type` filter
— unlike the other four services, which each narrow retrieval to one
document type via a Milvus `expr` (`sector_spec`, `procedure`, `crew_file`
plus a protocol, a rationing procedure). A free-form natural language
question over "the mission log corpus" isn't scoped to one document type
ahead of time the way a sector id or symptom report is.
"""

from __future__ import annotations

from app.schemas import Domain, QueryResponse, QueryResult
from app.services.vector_store import escape_expr_string_literal, get_vector_store


def _source_line(metadata: dict) -> str:
    return f"{metadata['doc_type']}:{metadata['doc_id']}#chunk{metadata['chunk_index']}"


def _relevance(relevance_score: float) -> float:
    """Clamp a raw retrieval relevance score into `[0, 1]`.

    Same clamp `app.services.telemetry._retrieval_strength` applies, and
    for the same reason: `similarity_search_with_relevance_scores`
    normalizes to `[0, 1]`, but its own base implementation warns rather
    than clamps when a score lands outside that range regardless. Rounded
    to two decimal places, matching every other rounded score in this API.
    """
    return round(max(0.0, min(1.0, relevance_score)), 2)


def run_query(question: str, top_k: int, domain: Domain | None = None) -> QueryResponse:
    """Search the full ingested mission document corpus for passages matching `question`.

    Returns up to `top_k` passages, most relevant first, each carrying its
    own source reference line and relevance score. An empty corpus, or a
    question that matches nothing, returns an empty `results` list rather
    than raising — see the module docstring for why that differs from the
    other four endpoints' LookupError-on-empty-retrieval behavior.

    `domain` restricts the search to that `Domain` tag via a Milvus `expr`
    — the one filter this endpoint applies at all, still with no
    `doc_type` clause (see the module docstring on why /query doesn't
    narrow by document type the way the other four endpoints do). `None`
    (the default) passes no `expr` whatsoever, so a caller that never
    knew `domain` existed gets the exact same unfiltered, whole-corpus
    search this endpoint always ran.
    """
    kwargs = {"k": top_k}
    if domain is not None:
        kwargs["expr"] = f"domain == '{escape_expr_string_literal(domain.value)}'"
    hits = get_vector_store().similarity_search_with_relevance_scores(question, **kwargs)
    return QueryResponse(
        results=[
            QueryResult(
                text=chunk.page_content,
                source=_source_line(chunk.metadata),
                relevance=_relevance(relevance_score),
            )
            for chunk, relevance_score in hits
        ]
    )
