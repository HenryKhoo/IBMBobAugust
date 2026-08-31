"""FastAPI application entrypoint for C.O.S.M.O.S."""

import logging

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.config import settings
from app.schemas import (
    AdminAppendPresetRequest,
    AdminAppendPresetResponse,
    AdminGenerateBaselineRequest,
    AdminGenerateBaselineResponse,
    AdminGenerateBanterRequest,
    AdminGenerateBanterResponse,
    AskRequest,
    AskResponse,
    ConversationHistoryResponse,
    HealthResponse,
    IngestRequest,
    IngestResponse,
    QueryRequest,
    QueryResponse,
    SpeakRequest,
    SpeakResponse,
)
from app.services import audio_cache, memory, speechify
from app.services.ingestion import ingest_and_upsert
from app.services.query import run_query
from app.services.cosmos import ask_cosmos, generate_baseline_draft, generate_banter_draft
from app.services.preset_admin import DuplicateQuestionError, append_preset_entry
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

    See `backend/scripts/fetch_cosmos_corpus.py` and
    `backend/scripts/ingest_cosmos_corpus.py` for the dev-time path that
    populates the corpus this endpoint also accepts documents through
    directly.
    """
    chunks_ingested = ingest_and_upsert(request.documents)
    return IngestResponse(chunks_ingested=chunks_ingested)


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest) -> QueryResponse:
    """Search the embedded corpus directly and return matching passages.

    A transparency tool alongside /ask — "see the actual source passages,"
    not C.O.S.M.O.S.'s main interface. Retrieval only, no generation step: a
    question that matches nothing in the corpus is a valid, empty result
    set rather than an error.
    """
    return run_query(request.question, request.top_k, request.domain)


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest) -> AskResponse:
    """Answer a space-science question, grounded in the ingested corpus.

    Never 404s: an unmatched question is a valid, honest "no grounded
    answer" response (see `app.services.cosmos.ask_cosmos`), not an
    error to raise — the no-hallucination protection this API's other
    endpoints get from a 404 is already built into that fallback response
    itself here.

    `request.session_id` opts into conversational memory across calls to
    this endpoint — see `AskRequest.session_id` and `app.services.memory`.
    """
    return ask_cosmos(
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


@app.post("/speak", response_model=SpeakResponse)
def speak(request: SpeakRequest) -> SpeakResponse:
    """Voice a companion answer via Speechify, when configured.

    Returns 503 (not 500) when `SPEECHIFY_API_KEY` or the requested
    persona/gender's voice ID is unset, and 502 when Speechify itself
    rejected or failed the request — two distinct causes the frontend can
    tell apart, though it falls back to the browser's own `SpeechSynthesis`
    API either way (see `frontend/app.html`'s `speakCompanionAnswer`). The
    companion should never go silent just because Speechify is
    unconfigured or its free tier is exhausted for the month.

    Deliberately not folded into `GET /health`'s `missing_config`: voice is
    a presentation enhancement layered on top of C.O.S.M.O.S.'s actual
    product (grounded answers) — an environment missing `SPEECHIFY_API_KEY`
    is still a fully healthy Q&A service, just one voiced by the browser
    instead of Speechify.
    """
    missing = speechify.missing_credentials(request.persona.value, request.gender)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Speechify not configured: missing {', '.join(missing)}",
        )
    try:
        result = speechify.synthesize_speech(request.text, request.gender, request.persona.value)
    except speechify.SpeechifySynthesisError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    audio_url = audio_cache.store(result.audio_data, result.audio_format)
    return SpeakResponse(audio_url=audio_url, audio_format=result.audio_format, speech_marks=result.speech_marks)


@app.get("/speak/audio/{filename}")
def speak_audio(filename: str) -> FileResponse:
    """Serve a clip cached by a prior `POST /speak` call.

    A real HTTP resource, not embedded base64/blob data -- see
    `SpeakResponse.audio_url`'s docstring and `app.services.audio_cache`
    for why. `FileResponse` (not a bare byte `Response`) so Range requests
    work, which some browsers' media engines expect even without seeking.
    """
    try:
        path = audio_cache.resolve(filename)
    except (ValueError, FileNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audio clip not found or expired")
    return FileResponse(path, media_type=f"audio/{path.suffix.lstrip('.')}")


def _require_admin_token(x_admin_token: str | None = Header(default=None)) -> None:
    """Gate every /admin/* route behind `ADMIN_TOKEN`, when one is configured.

    Mirrors this codebase's other optional-credential settings: an unset
    `ADMIN_TOKEN` leaves these routes open, matching local/dev use where
    `frontend/admin.html` is reached only by knowing its `?admin=true` URL.
    Any environment that sets `ADMIN_TOKEN` requires every caller to echo
    it back via the `X-Admin-Token` header — the `?admin=true` gate on the
    page itself is client-side only and not real access control on its own.
    """
    if settings.ADMIN_TOKEN and x_admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid admin token")


@app.post(
    "/admin/preset-qa/generate-baseline",
    response_model=AdminGenerateBaselineResponse,
    dependencies=[Depends(_require_admin_token)],
)
def admin_generate_baseline(request: AdminGenerateBaselineRequest) -> AdminGenerateBaselineResponse:
    """Draft a Baseline answer for a new preset-cache entry — admin tool only.

    Runs the same retrieval + `_BASELINE_PROMPT` + `get_instruct_model()`
    path `POST /ask` uses live, including its Granite -> watsonx-fallback ->
    Gemini-fallback failover chain — see
    `app.services.cosmos.generate_baseline_draft`.
    """
    return AdminGenerateBaselineResponse(**generate_baseline_draft(request.question, request.domain))


@app.post(
    "/admin/preset-qa/generate-banter",
    response_model=AdminGenerateBanterResponse,
    dependencies=[Depends(_require_admin_token)],
)
def admin_generate_banter(request: AdminGenerateBanterRequest) -> AdminGenerateBanterResponse:
    """Draft a Banter restyle of an admin-supplied Baseline answer.

    Same `_BANTER_PROMPT` "restate, never add a new fact" contract
    `POST /ask` enforces live, including the same failover chain — see
    `app.services.cosmos.generate_banter_draft`.
    """
    banter_answer = generate_banter_draft(request.baseline_answer, request.humor)
    return AdminGenerateBanterResponse(banter_answer=banter_answer)


@app.post(
    "/admin/preset-qa",
    response_model=AdminAppendPresetResponse,
    dependencies=[Depends(_require_admin_token)],
)
def admin_append_preset(request: AdminAppendPresetRequest) -> AdminAppendPresetResponse:
    """Append one curated Q&A entry to `backend/data/preset_qa.json` — admin tool only.

    Writes straight to disk and reloads the live preset cache, so the new
    question is answerable by `POST /ask` immediately, with no restart.
    409s if `question` already exists in the file — see
    `app.services.preset_admin.append_preset_entry`.
    """
    try:
        entry = append_preset_entry(
            request.question, request.domains, request.baseline_answer, request.banter_answer
        )
    except DuplicateQuestionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return AdminAppendPresetResponse(id=entry["id"], question=entry["question"])
