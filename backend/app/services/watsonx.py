"""IBM watsonx.ai client wrapper.

Wraps the two model calls the rest of the backend needs, via langchain-ibm:

- an embeddings client (Granite embedding model), for the ingestion and
  retrieval pipeline (see the day 3 ingestion layer work in the dev plan)
- an instruct/chat client (a Granite or Mistral instruct model, per the dev
  plan — whichever is available on this project's WML instance), for
  grounded generation in each module's endpoint (telemetry, crisis, triage,
  rationing, query), with an automatic failover model if the primary
  instruct model errors

Both are built from the shared `Settings` in `app.config`, so there is one
place credentials and model ids are configured (`.env`, see `.env.example`
at the repo root). Callers should use `get_embedding_model()` and
`get_instruct_model()` rather than constructing `WatsonxEmbeddings` /
`ChatWatsonx` directly, so the whole backend shares one cached client per
model and one place to change model ids or auth.
"""

from functools import lru_cache

from langchain_core.runnables import Runnable
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
    """Return a cached instruct chat client, with an automatic failover model.

    Primary model id comes from `WATSONX_INSTRUCT_MODEL_ID` (defaults to a
    Mistral instruct model, see `.env.example`: this project's WML instance
    plan does not expose a Granite chat/instruct model, only Granite
    embeddings, so the dev plan's "Granite or Mistral" fallback wording
    applies here).

    If `WATSONX_INSTRUCT_MODEL_FALLBACK_ID` is set (it is, by default), the
    returned runnable wraps the primary model with LangChain's built-in
    `.with_fallbacks()`: a failure on the primary model — unavailable,
    rate-limited, or withdrawn from this project's model catalog — is
    retried once against the fallback model before the call is allowed to
    fail. Leave `WATSONX_INSTRUCT_MODEL_FALLBACK_ID` empty to disable this
    and get the bare primary `ChatWatsonx` client back.
    """
    _require_credentials()
    primary = _chat_watsonx(settings.WATSONX_INSTRUCT_MODEL_ID)
    if not settings.WATSONX_INSTRUCT_MODEL_FALLBACK_ID:
        return primary
    fallback = _chat_watsonx(settings.WATSONX_INSTRUCT_MODEL_FALLBACK_ID)
    return primary.with_fallbacks([fallback])
