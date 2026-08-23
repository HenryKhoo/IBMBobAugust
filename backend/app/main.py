"""FastAPI application entrypoint for Talkback."""

import logging

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.config import settings
from app.schemas import (
    AskRequest,
    AskResponse,
    ConversationHistoryResponse,
    HealthResponse,
    IngestRequest,
    IngestResponse,
    QueryRequest,
    QueryResponse,
)
from app.services import memory
from app.services.ingestion import ingest_and_upsert
from app.services.query import run_query
from app.services.talkback import ask_talkback
from app.services.vector_store import get_vector_store
from app.services.vector_store import missing_credentials as zilliz_missing_credentials
from app.services.watsonx import missing_credentials as watsonx_missing_credentials

logger = logging.getLogger(__name__)

# The single provider that actually serves requests. Reported by /health
# rather than a config value, so it can never drift from what a real
# request would do — see `health`.
_ACTIVE_BACKEND = "watsonx"


class _UnhandledExceptionToJSON(BaseHTTPMiddleware):
    """Turn any otherwise-uncaught exception into a normal JSON 500 response.

    Without this, an *uncaught* exception is handled by Starlette's
    `ServerErrorMiddleware`, which always sits *outside* every middleware
    added via `add_middleware` — including `CORSMiddleware` below. Its
    fallback response carries no `Access-Control-Allow-Origin` header,
    which the browser can't distinguish from an actual CORS
    misconfiguration (this is exactly how a real 500 on an earlier version
    of this API was misreported as a CORS failure — see
    `backend/tests/test_smoke.py`'s regression test).

    The fix: catch the exception ourselves, in a middleware added *before*
    `CORSMiddleware` (each `add_middleware` call becomes the outermost
    layer, so registering this one first puts it *inside* `CORSMiddleware`).
    Returning a normal `Response` here means it flows back up through
    `CORSMiddleware` like any other response, picking up the same CORS
    headers a success or a clean 404 would.
    """

    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except Exception:
            logger.exception(
                "Unhandled exception on %s %s", request.method, request.url.path
            )
            return JSONResponse(status_code=500, content={"detail": "Internal server error"})


app = FastAPI(title=settings.APP_NAME)

# Order matters: this must be added *before* CORSMiddleware so that it ends
# up inside it (see _UnhandledExceptionToJSON's docstring) — its error
# responses need to pass back through CORSMiddleware to get CORS headers.
app.add_middleware(_UnhandledExceptionToJSON)

# The frontend is a single static HTML file served separately (locally or
# once deployed); allow it to call this API from any origin during
# development. Tighten this once a deployed frontend origin is known.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
def health(response: Response) -> HealthResponse:
    """Report whether this service is actually able to serve requests.

    `status` is derived from the same credential checks a real `/ask` or
    `/query` call would run (`missing_credentials()` in both service
    modules is the shared source of truth) — so this can never disagree
    with what a real request would do. A service missing any required
    watsonx/Zilliz setting reports `"degraded"` with a 503 and names the
    specific missing settings in `missing_config`, rather than reporting
    healthy while every real request would fail.

    This reports *configuration completeness*, not live upstream
    reachability — it deliberately does not round-trip to watsonx or
    Zilliz, so it stays cheap enough to poll. Credentials that are present
    but wrong (an expired API key, a deleted collection) still report
    `"ok"` here and fail at the endpoint.
    """
    missing = watsonx_missing_credentials() + zilliz_missing_credentials()
    if missing:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(
            status="degraded", backend=_ACTIVE_BACKEND, missing_config=missing
        )
    return HealthResponse(status="ok", backend=_ACTIVE_BACKEND)


@app.post("/ingest", response_model=IngestResponse)
def ingest(request: IngestRequest) -> IngestResponse:
    """Chunk, embed with Granite, and upsert documents into Zilliz.

    See `backend/scripts/fetch_talkback_corpus.py` and
    `backend/scripts/ingest_talkback_corpus.py` for the dev-time path that
    populates the corpus this endpoint also accepts documents through
    directly.
    """
    chunks_ingested = ingest_and_upsert(request.documents)
    return IngestResponse(chunks_ingested=chunks_ingested)


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest) -> QueryResponse:
    """Search the embedded corpus directly and return matching passages.

    A transparency tool alongside /ask — "see the actual source passages,"
    not Talkback's main interface. Retrieval only, no generation step: a
    question that matches nothing in the corpus is a valid, empty result
    set rather than an error.
    """
    return run_query(request.question, request.top_k, request.domain)


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest) -> AskResponse:
    """Answer a space-science question, grounded in the ingested corpus.

    Never 404s: an unmatched question is a valid, honest "no grounded
    answer" response (see `app.services.talkback.ask_talkback`), not an
    error to raise — the no-hallucination protection this API's other
    endpoints get from a 404 is already built into that fallback response
    itself here.

    `request.session_id` opts into conversational memory across calls to
    this endpoint — see `AskRequest.session_id` and `app.services.memory`.
    """
    return ask_talkback(
        request.question, request.persona, request.humor, request.session_id, request.domain
    )


@app.get("/conversation/history", response_model=ConversationHistoryResponse)
def conversation_history(session_id: str) -> ConversationHistoryResponse:
    """Return the transcript for one conversation, for the Conversation History panel.

    Prefers the live in-process session for `session_id` if one exists,
    falling back to Zilliz-persisted long-term history (grounded exchanges
    only) once that's gone — see `app.services.memory.get_conversation_history`
    for exactly how those two sources are chosen between.

    Never 404s: an unrecognized `session_id` — mistyped, expired, or simply
    never issued — returns an empty `turns` list with `source: "none"`
    rather than an error, the same "unknown id degrades to nothing"
    behavior `POST /ask` already has for a stale `session_id`.
    """
    turns, source = memory.get_conversation_history(get_vector_store, session_id)
    return ConversationHistoryResponse(session_id=session_id, turns=turns, source=source)
