"""FastAPI application entrypoint for The North Star backend."""

import logging

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.schemas import (
    CrisisAnalyzeRequest,
    CrisisAnalyzeResponse,
    HealthResponse,
    IngestRequest,
    IngestResponse,
    QueryRequest,
    QueryResponse,
    RationingSimulateRequest,
    RationingSimulateResponse,
    TelemetryInterpretRequest,
    TelemetryInterpretResponse,
    TriageRequest,
    TriageResponse,
)
from app.services.crisis import analyze_crisis
from app.services.ingestion import ingest_and_upsert
from app.services.query import run_query
from app.services.rationing import simulate_rationing
from app.services.telemetry import interpret_telemetry
from app.services.triage import run_triage
from app.services.vector_store import missing_credentials as zilliz_missing_credentials
from app.services.watsonx import missing_credentials as watsonx_missing_credentials

logger = logging.getLogger(__name__)

# The single provider that actually serves requests. Reported by /health
# instead of `settings.BACKEND_MODE`, which named a `mock` provider that was
# documented but never implemented — see `health` and `app.schemas
# .HealthResponse` for why echoing it back was the deployment bug.
_ACTIVE_BACKEND = "watsonx"


class _UnhandledExceptionToJSON(BaseHTTPMiddleware):
    """Turn any otherwise-uncaught exception into a normal JSON 500 response.

    This exists to fix a specific bug reported from production: the browser
    logged "/telemetry/interpret ... blocked by CORS policy: No
    'Access-Control-Allow-Origin' header is present", even though
    `CORSMiddleware` below is configured to allow all origins. The actual
    cause has nothing to do with the CORS config itself — an *uncaught*
    exception (e.g. the watsonx.ai/Zilliz SDK error this masked, see
    `app.services.vector_store.relevance_score_hits_or_empty`) is handled by
    Starlette's `ServerErrorMiddleware`, which always sits *outside* every
    middleware added via `add_middleware` (Starlette special-cases handlers
    registered for the bare `Exception` type, or status 500, routing them to
    `ServerErrorMiddleware` specifically — a `@app.exception_handler(Exception)`
    handler does NOT fix this, it still runs outside `CORSMiddleware`).
    `ServerErrorMiddleware`'s fallback response bypasses `CORSMiddleware`
    entirely, so it carries no `Access-Control-Allow-Origin` header — which
    is indistinguishable, from the browser's point of view, from an actual
    CORS misconfiguration.

    The fix: catch the exception ourselves, in a middleware added *before*
    `CORSMiddleware` (Starlette's `add_middleware` makes each new call the
    outermost layer, so registering this one first puts it *inside*
    `CORSMiddleware` — verified locally: an unguarded 500 from this position
    comes back with no CORS header, the same one from here comes back with
    the header present). Returning a normal `Response` here means it flows
    back up through `CORSMiddleware` like any other response, picking up the
    same CORS headers a success or a clean 404 would.
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
# on Railway); allow it to call this API from any origin during
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

    Fixes a deployment bug found while testing the Railway deployment
    end to end: this endpoint used to return `{"status": "ok", "backend":
    settings.BACKEND_MODE}` unconditionally. `BACKEND_MODE` defaults to
    `"mock"` (see `app.config`), and `.env.example`/`RAILWAY.md` both
    documented `mock` as a way to run "without IBM watsonx/Zilliz" — but
    no mock provider was ever built. Nothing anywhere branched on
    `BACKEND_MODE`; this line was its only reader. So a service deployed
    without credentials answered `/health` with `{"status": "ok",
    "backend": "mock"}` — a perfectly healthy-looking response — while
    every one of the five module endpoints raised `RuntimeError` from
    `watsonx._require_credentials`/`vector_store._require_credentials` and
    returned a 500. Reproduced locally: `/health` 200 `ok`/`mock`,
    all five module endpoints 500, same process.

    That combination is worse than a plain outage, because the frontend
    degrades silently by design: every `fetch` in `mission-console.html`
    catches its failure, logs to the console, and leaves the
    hand-authored fallback text on screen (see `fetchSectorSummary`,
    `fetchCrisisAnalysis`, `fetchTriageAnalysis`). A console with a dead
    AI backend looks, to anyone but its developer, exactly like a working
    one — and `/health`, the one thing you would check to tell the
    difference, agreed that it was fine.

    So status is now derived from the same credential checks a real
    request runs (`missing_credentials()` in both service modules is the
    shared source of truth), and a service that cannot serve says so with
    a 503 rather than a 200.

    This reports *configuration completeness*, not live upstream
    reachability: it deliberately does not round-trip to watsonx or
    Zilliz, so it stays cheap enough to poll and cannot fail on a
    transient upstream blip. Credentials that are present but wrong (an
    expired API key, a deleted collection) still report `"ok"` here and
    fail at the endpoint — this closes the "misconfigured deployment
    looks healthy" gap, not the "valid config, broken upstream" one.
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
    """Chunk, embed with Granite, and upsert mission documents into Zilliz."""
    chunks_ingested = ingest_and_upsert(request.documents)
    return IngestResponse(chunks_ingested=chunks_ingested)


@app.post("/telemetry/interpret", response_model=TelemetryInterpretResponse)
def telemetry_interpret(
    request: TelemetryInterpretRequest,
) -> TelemetryInterpretResponse:
    """Retrieve the matching sector documentation and return a grounded summary.

    404s if no sector documentation has been ingested for this sector's
    readings yet, rather than returning an ungrounded summary.
    """
    try:
        return interpret_telemetry(request.sector_id, request.metrics)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/crisis/analyze", response_model=CrisisAnalyzeResponse)
def crisis_analyze(request: CrisisAnalyzeRequest) -> CrisisAnalyzeResponse:
    """Retrieve the matching emergency procedure(s) and return a grounded root cause.

    The event feed can span more than one concurrent failure point (see
    `app.services.crisis.analyze_crisis`); each distinct `sector` present
    in `request.events` gets its own retrieval attempt. 404s only if none
    of them matched any procedure documentation, rather than returning an
    ungrounded root cause — a feed where only some sectors matched still
    returns a 200 grounded in whichever ones did.
    """
    try:
        return analyze_crisis(request.events)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/triage", response_model=TriageResponse)
def triage(request: TriageRequest) -> TriageResponse:
    """Retrieve the crew member's file and a matching protocol, and return a grounded lead.

    404s if no crew file is found for `crew_member_id`, or if no protocol
    documentation matches the symptom report, rather than returning an
    ungrounded triage lead.
    """
    try:
        return run_triage(request.crew_member_id, request.symptom_report)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/rationing/simulate", response_model=RationingSimulateResponse)
def rationing_simulate(request: RationingSimulateRequest) -> RationingSimulateResponse:
    """Retrieve the matching rationing procedure and return a grounded simulation.

    404s if no rationing/supply procedure documentation matches this
    scenario, rather than returning an ungrounded narrative.
    """
    try:
        return simulate_rationing(
            request.stock_level, request.ration_amount, request.days_until_resupply
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest) -> QueryResponse:
    """Search the embedded mission log corpus and return matching passages.

    Retrieval only, no generation step — so unlike every other endpoint
    above, there is no LookupError/404 case here. A question that matches
    nothing in the corpus is a valid, empty result set rather than an
    error; see `app.services.query` for why.
    """
    return run_query(request.question, request.top_k)
