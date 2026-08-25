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
  rate-limited. When `GEMINI_API_KEY` is set, Gemini (via
  langchain-google-genai) is the *primary* tier and both watsonx models
  become the failover chain instead — the watsonx/Granite trial tier's
  rate limit was being hit too often for watsonx to serve as the first
  attempt. With no Gemini key configured, watsonx stays primary exactly as
  before Gemini support existed. Whichever tier actually answers, it
  generates the exact same grounded prompt from the same retrieved passage
  (see `app.services.chortlechat`) — the no-hallucination discipline
  doesn't change based on which model tier answered.

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

    Watsonx model ids come from `WATSONX_INSTRUCT_MODEL_ID` (primary,
    defaults to a Mistral instruct model — see `.env.example`: this
    project's WML instance plan does not expose a Granite chat/instruct
    model, only Granite embeddings, so the dev plan's "Granite or Mistral"
    fallback wording applies here) and `WATSONX_INSTRUCT_MODEL_FALLBACK_ID`
    (a second watsonx model, set by default).

    Which client is actually *primary* depends on `GEMINI_API_KEY`:

    - **Unset** (default): unchanged from before Gemini support existed.
      The watsonx primary model is primary; the watsonx fallback model (if
      set) is the one and only failover tier.
    - **Set**: Gemini is primary instead, since watsonx's own rate limit
      was being hit too often to trust it as the first attempt. Both
      watsonx models become the failover chain, tried in the same relative
      order they were tried in before Gemini existed (watsonx primary,
      then watsonx fallback) — so a Gemini outage degrades all the way
      back to the original watsonx-only behavior rather than failing hard.

    Either way this uses LangChain's built-in `.with_fallbacks()`, trying
    each tier in order on failure — unavailable, rate-limited, or
    withdrawn from a model catalog all count as a failure that advances to
    the next tier.
    """
    _require_credentials()
    watsonx_primary = _chat_watsonx(settings.WATSONX_INSTRUCT_MODEL_ID)
    watsonx_fallback = (
        _chat_watsonx(settings.WATSONX_INSTRUCT_MODEL_FALLBACK_ID)
        if settings.WATSONX_INSTRUCT_MODEL_FALLBACK_ID
        else None
    )

    if settings.GEMINI_API_KEY:
        fallbacks = [watsonx_primary] + ([watsonx_fallback] if watsonx_fallback else [])
        return _chat_gemini().with_fallbacks(fallbacks)

    if not watsonx_fallback:
        return watsonx_primary
    return watsonx_primary.with_fallbacks([watsonx_fallback])
