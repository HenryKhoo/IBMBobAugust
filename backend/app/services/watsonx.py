"""IBM watsonx.ai (+ Gemini fallback/replacement) client wrapper.

Wraps the two model calls the rest of the backend needs, each independently
switchable to Gemini via `GEMINI_API_KEY`:

- an embeddings client, for the ingestion and retrieval pipeline (see the
  day 3 ingestion layer work in the dev plan). Granite (via langchain-ibm)
  by default; Gemini's `gemini-embedding-001` (via langchain-google-genai)
  instead once `GEMINI_API_KEY` is set — see `using_gemini_embeddings()`
  and `get_embedding_model()`. Unlike the instruct model below, this is a
  straight *replacement*, not a fallback chain: embeddings from different
  providers are different vector spaces, so a Gemini query vector compared
  against Granite-embedded document vectors (or vice versa) produces a
  meaningless similarity score without ever raising an error. Switching
  providers therefore always means querying a different Zilliz collection
  too (`ZILLIZ_COLLECTION_NAME_GEMINI`, not `ZILLIZ_COLLECTION_NAME` — see
  `app.services.vector_store.get_vector_store`), populated by re-running
  `backend/scripts/ingest_chortlechat_corpus.py` with `GEMINI_API_KEY` set.
  Added after watsonx's Granite embedding quota — a separate quota from
  the instruct model's — started rejecting every retrieval call outright
  (`token_quota_reached`), which is a fundamentally different failure than
  the instruct model being rate-limited: there's no "try Granite, fall
  back to Gemini" here, only "which single provider is authoritative for
  the currently-active collection."
- an instruct/chat client, for grounded generation in `/ask` (and, before
  the ChortleChat revamp, each habitat module's endpoint), with automatic
  failover across up to three tiers when a model errors or is
  rate-limited. When `GEMINI_API_KEY` is set, Gemini is the *primary* tier
  and both watsonx models become the failover chain instead — the
  watsonx/Granite trial tier's rate limit was being hit too often for
  watsonx to serve as the first attempt. With no Gemini key configured,
  watsonx stays primary exactly as before Gemini support existed.
  Whichever tier actually answers, it generates the exact same grounded
  prompt from the same retrieved passage (see `app.services.chortlechat`)
  — the no-hallucination discipline doesn't change based on which model
  tier answered. Unlike embeddings, a genuine fallback chain makes sense
  here because generation is stateless per call — nothing is stored in a
  shape tied to whichever model answered a previous question.

Built from the shared `Settings` in `app.config`, so there is one place
credentials and model ids are configured (`.env`, see `.env.example` at
the repo root). Callers should use `get_embedding_model()` and
`get_instruct_model()` rather than constructing `WatsonxEmbeddings` /
`GoogleGenerativeAIEmbeddings` / `ChatWatsonx` / `ChatGoogleGenerativeAI`
directly, so the whole backend shares one cached client per model and one
place to change model ids or auth.
"""

from functools import lru_cache

from langchain_core.embeddings import Embeddings
from langchain_core.runnables import Runnable
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_ibm import ChatWatsonx, WatsonxEmbeddings

from app.config import settings

_INSTRUCT_PARAMS = {"temperature": 0.2, "max_tokens": 512}


def using_gemini_embeddings() -> bool:
    """Whether embeddings currently come from Gemini rather than watsonx/Granite.

    Single source of truth shared by `get_embedding_model` (which client to
    build) and `app.services.vector_store.get_vector_store` (which Zilliz
    collection to point at) — the two must never disagree, since mixing a
    Gemini-embedded query against a Granite-embedded collection (or vice
    versa) fails silently rather than raising. See the module docstring.
    """
    return bool(settings.GEMINI_API_KEY)


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


def _gemini_embed() -> GoogleGenerativeAIEmbeddings:
    return GoogleGenerativeAIEmbeddings(
        model=settings.GEMINI_EMBEDDING_MODEL_ID,
        google_api_key=settings.GEMINI_API_KEY,
    )


@lru_cache(maxsize=1)
def get_embedding_model() -> Embeddings:
    """Return a cached embeddings client for document/query embedding.

    Gemini (`_gemini_embed`) when `GEMINI_API_KEY` is set, watsonx/Granite
    otherwise — a straight replacement, not a fallback chain; see the
    module docstring for why embeddings can't safely fail over the way the
    instruct model does. Watsonx credentials are only required on the
    watsonx branch: a Gemini-only deployment (no `WATSONX_API_KEY`/
    `WATSONX_PROJECT_ID`) is valid here, even though `get_instruct_model`
    still wants watsonx credentials for its own fallback tiers.
    """
    if using_gemini_embeddings():
        return _gemini_embed()
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
