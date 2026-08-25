"""IBM watsonx.ai (+ Gemini embeddings) client wrapper.

Wraps the two model calls the rest of the backend needs:

- an embeddings client, for the ingestion and retrieval pipeline (see the
  day 3 ingestion layer work in the dev plan). Granite (via langchain-ibm)
  by default; Gemini's `gemini-embedding-001` (via langchain-google-genai)
  instead once `GEMINI_API_KEY` is set — see `using_gemini_embeddings()`
  and `get_embedding_model()`. This is a straight *replacement*, not a
  fallback chain: embeddings from different providers are different
  vector spaces, so a Gemini query vector compared against Granite-embedded
  document vectors (or vice versa) produces a meaningless similarity score
  without ever raising an error. Switching providers therefore always means
  querying a different Zilliz collection too (`ZILLIZ_COLLECTION_NAME_GEMINI`,
  not `ZILLIZ_COLLECTION_NAME` — see `app.services.vector_store.get_vector_store`),
  populated by re-running `backend/scripts/ingest_chortlechat_corpus.py`
  with `GEMINI_API_KEY` set. Added after watsonx's Granite embedding quota
  started rejecting every retrieval call outright (`token_quota_reached`).
- an instruct/chat client, for grounded generation in `/ask` (and, before
  the ChortleChat revamp, each habitat module's endpoint). Watsonx only —
  a Gemini fallback/primary tier here was tried and then deliberately
  removed: the actual failure this project hit was always on the
  embedding side (see above), never generation, so adding Gemini to this
  path was solving a problem generation didn't have while adding a second
  provider's worth of wiring to reason about. `WATSONX_INSTRUCT_MODEL_ID`
  is primary; `WATSONX_INSTRUCT_MODEL_FALLBACK_ID`, if set, is a single
  failover tier via LangChain's `.with_fallbacks()`.

Built from the shared `Settings` in `app.config`, so there is one place
credentials and model ids are configured (`.env`, see `.env.example` at
the repo root). Callers should use `get_embedding_model()` and
`get_instruct_model()` rather than constructing `WatsonxEmbeddings` /
`GoogleGenerativeAIEmbeddings` / `ChatWatsonx` directly, so the whole
backend shares one cached client per model and one place to change model
ids or auth.
"""

from functools import lru_cache

from langchain_core.embeddings import Embeddings
from langchain_core.runnables import Runnable
from langchain_google_genai import GoogleGenerativeAIEmbeddings
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
    """Return a cached watsonx instruct chat client, with one optional failover tier.

    Primary model id comes from `WATSONX_INSTRUCT_MODEL_ID` (defaults to a
    Mistral instruct model — see `.env.example`: this project's WML
    instance plan does not expose a Granite chat/instruct model, only
    Granite embeddings, so the dev plan's "Granite or Mistral" fallback
    wording applies here). If `WATSONX_INSTRUCT_MODEL_FALLBACK_ID` is set
    (it is, by default), the returned runnable wraps the primary model with
    LangChain's built-in `.with_fallbacks()`: a failure on the primary —
    unavailable, rate-limited, or withdrawn from the model catalog — is
    retried once against the fallback model before the call is allowed to
    fail. Leave `WATSONX_INSTRUCT_MODEL_FALLBACK_ID` empty to disable this
    and get the bare primary `ChatWatsonx` client back.

    Watsonx only, deliberately — no Gemini tier here. Generation was never
    actually the thing failing in production (see `app.services.watsonx`'s
    module docstring); that was always the embedding call, which
    `get_embedding_model` below handles independently.
    """
    _require_credentials()
    primary = _chat_watsonx(settings.WATSONX_INSTRUCT_MODEL_ID)
    if not settings.WATSONX_INSTRUCT_MODEL_FALLBACK_ID:
        return primary
    fallback = _chat_watsonx(settings.WATSONX_INSTRUCT_MODEL_FALLBACK_ID)
    return primary.with_fallbacks([fallback])
