"""IBM watsonx.ai (+ Gemini fallback) client wrapper.

Wraps the two model calls the rest of the backend needs:

- an embeddings client (Granite embedding model, via langchain-ibm), for
  the ingestion and retrieval pipeline (see the day 3 ingestion layer work
  in the dev plan). Watsonx/Granite-only, deliberately: the Zilliz
  collection is already indexed against Granite's vector space, so a
  second embedding provider would produce vectors that aren't comparable
  to the ones already stored — there's no safe fallback here, only a
  single source of truth.
- an instruct/chat client, for grounded generation in `/ask` (and, before
  the ChortleChat revamp, each habitat module's endpoint), with automatic
  failover across up to three tiers when a model errors or is
  rate-limited: the primary watsonx model, then an optional second
  watsonx model, then an optional Gemini model (via langchain-google-genai)
  as a fallback that's on a wholly separate quota from watsonx's. Added
  because the watsonx/Granite trial tier's rate limit was being hit
  regularly during the challenge; Gemini only ever runs after both watsonx
  attempts have already failed, and generates the exact same grounded
  prompt watsonx would have (see `app.services.chortlechat`) — the
  no-hallucination discipline doesn't change based on which model tier
  answered.

Built from the shared `Settings` in `app.config`, so there is one place
credentials and model ids are configured (`.env`, see `.env.example` at
the repo root). Callers should use `get_embedding_model()` and
`get_instruct_model()` rather than constructing `WatsonxEmbeddings` /
`ChatWatsonx` / `ChatGoogleGenerativeAI` directly, so the whole backend
shares one cached client per model and one place to change model ids or
auth.
"""

from functools import lru_cache

from langchain_core.runnables import Runnable
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ibm import ChatWatsonx, WatsonxEmbeddings

from app.config import settings

_INSTRUCT_PARAMS = {"temperature": 0.2, "max_tokens": 512}


def missing_credentials() -> list[str]:
    """Return the names of required watsonx.ai settings that are not set.

    Single source of truth for "is watsonx configured", shared by
    `_require_credentials` (which raises on the way into a model call) and
    `app.main.health` (which reports it without raising). Keeping one list
    means `/health` can never disagree with what an actual request would
    do — the drift that let `/health` report a healthy `mock` backend while
    every endpoint raised from here. Mirrors
    `app.services.vector_store.missing_credentials`.
    """
    return [
        name
        for name, value in (
            ("WATSONX_API_KEY", settings.WATSONX_API_KEY),
            ("WATSONX_PROJECT_ID", settings.WATSONX_PROJECT_ID),
        )
        if not value
    ]


def _require_credentials() -> None:
    """Raise a clear error if watsonx.ai credentials are not configured.

    Surfacing a specific, actionable message here is worth it: a bare
    langchain-ibm/ibm-watsonx-ai auth failure otherwise reads as a generic
    HTTP error deep in a retrieval call.
    """
    missing = missing_credentials()
    if missing:
        raise RuntimeError(
            "Missing watsonx.ai credentials: "
            + ", ".join(missing)
            + ". Set them in a local .env at the repo root (see .env.example)."
        )


def _chat_watsonx(model_id: str) -> ChatWatsonx:
    return ChatWatsonx(
        model_id=model_id,
        url=settings.WATSONX_URL,
        apikey=settings.WATSONX_API_KEY,
        project_id=settings.WATSONX_PROJECT_ID,
        params=_INSTRUCT_PARAMS,
    )


def _chat_gemini() -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=settings.GEMINI_INSTRUCT_MODEL_ID,
        google_api_key=settings.GEMINI_API_KEY,
        temperature=_INSTRUCT_PARAMS["temperature"],
        max_output_tokens=_INSTRUCT_PARAMS["max_tokens"],
    )


@lru_cache(maxsize=1)
def get_embedding_model() -> WatsonxEmbeddings:
    """Return a cached Granite embeddings client for document/query embedding."""
    _require_credentials()
    return WatsonxEmbeddings(
        model_id=settings.WATSONX_EMBEDDING_MODEL_ID,
        url=settings.WATSONX_URL,
        apikey=settings.WATSONX_API_KEY,
        project_id=settings.WATSONX_PROJECT_ID,
    )


@lru_cache(maxsize=1)
def get_instruct_model() -> Runnable:
    """Return a cached instruct chat client, with up to two failover tiers.

    Primary model id comes from `WATSONX_INSTRUCT_MODEL_ID` (defaults to a
    Mistral instruct model, see `.env.example`: this project's WML instance
    plan does not expose a Granite chat/instruct model, only Granite
    embeddings, so the dev plan's "Granite or Mistral" fallback wording
    applies here).

    The returned runnable wraps the primary model with LangChain's built-in
    `.with_fallbacks()`, trying each configured tier in order on failure —
    unavailable, rate-limited, or withdrawn from a model catalog all count:

    1. `WATSONX_INSTRUCT_MODEL_FALLBACK_ID` (set by default) — a second
       watsonx model, for when the primary model specifically is
       unavailable but the watsonx account/project itself still has quota.
    2. `GEMINI_API_KEY` (optional, unset by default) — a Gemini model on a
       wholly separate quota from watsonx's, tried only once both watsonx
       attempts above have failed. This is the tier that actually helps
       when watsonx's own rate limit is what's being hit, since tier 1 is
       still capped by that same account.

    Both tiers are independently optional: leave either/both unset to fall
    back to a shorter chain, down to the bare primary `ChatWatsonx` client
    if neither is configured — exactly this function's behavior before
    Gemini support existed.
    """
    _require_credentials()
    primary = _chat_watsonx(settings.WATSONX_INSTRUCT_MODEL_ID)

    fallbacks: list[Runnable] = []
    if settings.WATSONX_INSTRUCT_MODEL_FALLBACK_ID:
        fallbacks.append(_chat_watsonx(settings.WATSONX_INSTRUCT_MODEL_FALLBACK_ID))
    if settings.GEMINI_API_KEY:
        fallbacks.append(_chat_gemini())

    if not fallbacks:
        return primary
    return primary.with_fallbacks(fallbacks)
