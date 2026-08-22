"""Pydantic schemas for the Talkback API.

Talkback answers real space-science questions, grounded in the ingested
NASA SMD Q&A corpus — see `app.services.talkback` for the engine and
`backend/scripts/fetch_talkback_corpus.py` /
`backend/scripts/ingest_talkback_corpus.py` for how that corpus gets in.

This is a deliberately small surface: `GET /health`, `POST /ingest`,
`POST /query` (raw passage search, for transparency), and `POST /ask`
(the actual product). Earlier iterations of this repo carried five
habitat-crisis-console endpoints (telemetry, crisis, triage, rationing)
built around a fictional deep-space-habitat scenario; those schemas were
removed in the revamp to a single-objective product rather than kept
around unused — see the project's `revamp/talkback` branch history for
that decision.
"""

from enum import Enum

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Response body for GET /health.

    `status` is `"ok"` only when every upstream credential Talkback needs
    to actually serve a request is configured, and `"degraded"` otherwise
    — derived from the same credential checks a real `/ask` or `/query`
    call would run (`missing_credentials()` in both service modules is the
    shared source of truth), so this can never disagree with what a real
    request would do. `missing_config` names the specific unset settings
    behind a `"degraded"` status. This checks configuration completeness,
    not live upstream reachability, so it stays cheap enough to poll.
    """

    status: str
    backend: str
    missing_config: list[str] = Field(default_factory=list)


class DocumentType(str, Enum):
    """Kinds of documents accepted by POST /ingest.

    A single member today (`science_reference`, the NASA SMD Q&A corpus
    Talkback is grounded in) — kept as an enum rather than inlined as a
    literal string so a second corpus can be added later without changing
    the request/response shape.
    """

    SCIENCE_REFERENCE = "science_reference"


class MissionDocument(BaseModel):
    """A single raw document submitted for ingestion."""

    id: str
    type: DocumentType
    text: str = Field(min_length=1)


class IngestRequest(BaseModel):
    """Request body for POST /ingest."""

    documents: list[MissionDocument]


class IngestResponse(BaseModel):
    """Response body for POST /ingest."""

    chunks_ingested: int


class QueryRequest(BaseModel):
    """Request body for POST /query.

    `top_k` caps how many passages `app.services.query.run_query` returns.
    Bounded (`ge=1, le=20`) since this endpoint has no downstream
    generation step to keep a runaway value in check the way `/ask`'s
    single-chunk retrieval implicitly does.
    """

    question: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


class QueryResult(BaseModel):
    """One retrieved passage in a POST /query response.

    `relevance` is the raw retrieval relevance score for this passage
    alone, clamped to `[0, 1]`. /query does no generation and blends in no
    second signal, so retrieval strength is the whole story here.
    """

    text: str
    source: str
    relevance: float


class QueryResponse(BaseModel):
    """Response body for POST /query.

    Exposed alongside /ask as a transparency tool — "see the actual source
    passages Talkback's answers are grounded in" — not as Talkback's main
    interface. `results` is ordered most-relevant-first. An empty list is a
    valid response (nothing in the corpus matches), not an error: unlike
    /ask, there's no generated claim here that would otherwise go
    ungrounded.
    """

    results: list[QueryResult]


class AskPersona(str, Enum):
    """Which voice answers a Talkback question.

    Persona changes only how a true thing is said, never whether it's
    said, or what it claims — see `app.services.talkback` for how that's
    enforced structurally, not just by prompting convention.
    """

    BASELINE = "baseline"
    BANTER = "banter"


class AskRequest(BaseModel):
    """Request body for POST /ask.

    `humor` only affects `AskPersona.BANTER` — Baseline ignores it
    entirely, since Baseline has no humor dial to turn. Bounded `[0, 100]`
    to match the frontend's slider range.
    """

    question: str = Field(min_length=1)
    persona: AskPersona = AskPersona.BASELINE
    humor: int = Field(default=50, ge=0, le=100)


class AskResponse(BaseModel):
    """Response body for POST /ask.

    `grounded` is `False` whenever `answer` is the honest no-match
    fallback rather than a generated, source-backed answer — the frontend
    uses this (not string-matching `answer`'s text) to decide whether to
    show a citation/confidence badge or the muted "no grounded answer"
    treatment. `confidence` is retrieval strength on the matched passage,
    `None` only when nothing was retrieved at all (an empty/uningested
    corpus) rather than a low-but-real score. `source` is `None` whenever
    `grounded` is `False`, and a real `doc_type:doc_id#chunkN` citation
    otherwise, same format the rest of this API's retrieval-backed
    responses use.

    Never a 404: an unmatched question is a valid, honest response (see
    `app.services.talkback.ask_talkback`), not a failure to protect
    against generating an ungrounded guess — the protection already
    happened, that *is* what the fallback response is.
    """

    answer: str
    persona: AskPersona
    grounded: bool
    confidence: float | None = None
    source: str | None = None
