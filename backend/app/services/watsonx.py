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
  populated by re-running `backend/scripts/ingest_cosmos_corpus.py`
  with `GEMINI_API_KEY` set. Added after watsonx's Granite embedding quota
  started rejecting every retrieval call outright (`token_quota_reached`).
- an instruct/chat client, for grounded generation in `/ask` (and, before
  the C.O.S.M.O.S. revamp, each habitat module's endpoint). `WATSONX_INSTRUCT_MODEL_ID`
  is primary; `WATSONX_INSTRUCT_MODEL_FALLBACK_ID`, if set, is a second
  watsonx tier via LangChain's `.with_fallbacks()`. A prior version of this
  module argued generation never actually failed in production, so a
  Gemini tier here wasn't worth the wiring -- that held until 2026-08-26,
  when a live `/ask` call hit `token_quota_reached` on *both* watsonx
  tiers back to back (same account, so a different watsonx model id
  doesn't route around an account-level quota exhaustion the way it does
  a per-model outage). `get_instruct_model()` now appends a third,
  Gemini-backed tier -- `GEMINI_INSTRUCT_MODEL_ID` via `_gemini_chat()` --
  tried only if both watsonx tiers fail and `GEMINI_API_KEY` is set. This
  is safe as an actual `.with_fallbacks()` chain (unlike embeddings above):
  a single generation call's output is plain text, not a persisted vector,
  so there's no equivalent of the "different vector space" hazard that
  keeps embeddings a straight replacement instead of a fallback.

Built from the shared `Settings` in `app.config`, so there is one place
credentials and model ids are configured (`.env`, see `.env.example` at
the repo root). Callers should use `get_embedding_model()` and
`get_instruct_model()` rather than constructing `WatsonxEmbeddings` /
`GoogleGenerativeAIEmbeddings` / `ChatWatsonx` directly, so the whole
backend shares one cached client per model and one place to change model
ids or auth.
"""

import logging
import re
from functools import lru_cache

from langchain_core.embeddings import Embeddings
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langchain_ibm import ChatWatsonx, WatsonxEmbeddings

from app.config import settings

logger = logging.getLogger(__name__)

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


_GEMINI_MODEL_VERSION_RE = re.compile(r"^gemini-(\d+)\.")


def _require_gemini_3x_model(model_id: str) -> None:
    """Raise loudly if `model_id` isn't a Gemini 3.x model.

    `_gemini_chat()` hardcodes `thinking_config={"thinking_level":
    "minimal"}`, which only Gemini 3.x accepts -- see that function's
    docstring for the `thinking_budget` (2.5) vs `thinking_level` (3.x)
    history. `GEMINI_INSTRUCT_MODEL_ID` is a plain env var an operator can
    repoint at a 2.5-era model at any time; without this check, doing so
    would silently reproduce the exact bare `400 INVALID_ARGUMENT` this
    project already spent two rounds chasing down, and only surface at the
    first live call instead of here, at client-construction time.
    """
    match = _GEMINI_MODEL_VERSION_RE.match(model_id)
    if not match or int(match.group(1)) < 3:
        raise RuntimeError(
            f"GEMINI_INSTRUCT_MODEL_ID={model_id!r} is not a Gemini 3.x model, but "
            "_gemini_chat() hardcodes thinking_config={'thinking_level': 'minimal'}, "
            "which only Gemini 3.x accepts -- Gemini 2.5-era models reject it "
            "with a bare 400 INVALID_ARGUMENT and need thinking_budget=0 instead. "
            "Point GEMINI_INSTRUCT_MODEL_ID at a gemini-3.x model, or update "
            "_gemini_chat() for the new model generation's thinking-control API."
        )


def _gemini_chat() -> ChatGoogleGenerativeAI:
    """Build the Gemini chat client used as get_instruct_model()'s last fallback tier.

    Same temperature/max-output-length intent as `_INSTRUCT_PARAMS` (used
    for the watsonx tiers), expressed in langchain-google-genai's own kwarg
    names rather than watsonx's `params` dict shape.

    gemini-3.6-flash's extended-thinking mode is the same problem it always
    was: with thinking on, hidden reasoning tokens eat into
    `max_output_tokens` before the visible answer gets any, producing
    answers truncated mid-sentence, and the returned message `.content`
    comes back as a list of content blocks (a `text` part plus an opaque
    `signature`-carrying thought part) rather than the plain string every
    watsonx tier returns -- see `app.services.cosmos._message_text`,
    which every caller of `get_instruct_model().invoke(...)` must go
    through instead of `str(message.content)` for exactly this reason.

    How to turn thinking down is NOT the same across Gemini generations,
    though, and this bit us live on 2026-08-26: the first fix here was a
    top-level `thinking_budget=0` kwarg, which worked for Gemini 2.5 but
    made gemini-3.6-flash reject every request outright with a bare
    `400 INVALID_ARGUMENT` (no field name in the message -- confirmed by
    inspecting `ChatGoogleGenerativeAI._build_base_generation_config()`
    directly: `thinking_budget=0` serializes to
    `ThinkingConfig(thinking_budget=0)`, and Gemini 3.x's API rejects
    `thinkingConfig.thinkingBudget` as deprecated). Gemini 3.x replaced the
    token-budget knob with a coarser `thinking_level` enum instead
    (`minimal`/`low`/`medium`/`high`; requires langchain-google-genai
    >=4.2.6, confirmed installed). `thinking_config={"thinking_level":
    "minimal"}` serializes to `ThinkingConfig(thinking_level=MINIMAL)` --
    verified directly the same way -- with no `thinking_budget` field at
    all, so nothing deprecated ever reaches the request. `minimal` is the
    closest thing Gemini 3.x flash offers to the old "disable thinking
    outright" intent; there is no true zero/off level for this model
    generation. If Gemini ever adds one, or this project moves off
    gemini-3.6-flash to a 2.5-era model where `thinking_budget=0` is valid
    again, this is the one place to change -- and `_require_gemini_3x_model()`
    below is what stops `GEMINI_INSTRUCT_MODEL_ID` drifting onto a 2.5-era
    model without that change also happening: it fails loudly here, at
    client-construction time, instead of at the first live call.
    """
    _require_gemini_3x_model(settings.GEMINI_INSTRUCT_MODEL_ID)
    return ChatGoogleGenerativeAI(
        model=settings.GEMINI_INSTRUCT_MODEL_ID,
        google_api_key=settings.GEMINI_API_KEY,
        temperature=_INSTRUCT_PARAMS["temperature"],
        max_output_tokens=_INSTRUCT_PARAMS["max_tokens"],
        thinking_config={"thinking_level": "minimal"},
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


def _logged(model: Runnable, label: str) -> Runnable:
    """Wrap an instruct-model tier so ITS OWN failure gets logged as it happens.

    `get_instruct_model()` chains tiers with LangChain's `.with_fallbacks()`,
    which -- confirmed by reading `RunnableWithFallbacks.invoke()` directly --
    only ever re-raises the *first* tier's exception if every tier fails,
    silently discarding whatever every later tier actually failed with.
    Confirmed live 2026-08-26: watsonx primary and fallback both failed with
    a visible `token_quota_reached` (the watsonx SDK prints that itself,
    independent of langchain), then the new Gemini tier ALSO failed for some
    separate reason that never reached the logs or the user, because
    `.with_fallbacks()` re-raised the original watsonx error instead of
    Gemini's. Wrapping each tier here means every tier's own failure is
    logged the moment it happens, regardless of which one `.with_fallbacks()`
    ultimately chooses to re-raise -- so a "why did /ask 500?" investigation
    never again has to guess which tier actually caused it.
    """

    def _invoke_and_log(prompt):
        try:
            return model.invoke(prompt)
        except Exception as e:
            logger.warning("Instruct tier %r failed: %s: %s", label, type(e).__name__, e)
            raise

    return RunnableLambda(_invoke_and_log)


@lru_cache(maxsize=1)
def get_instruct_model() -> Runnable:
    """Return a cached instruct chat client, with up to two failover tiers.

    Primary model id comes from `WATSONX_INSTRUCT_MODEL_ID` (defaults to a
    Mistral instruct model — see `.env.example`: this project's WML
    instance plan does not expose a Granite chat/instruct model, only
    Granite embeddings, so the dev plan's "Granite or Mistral" fallback
    wording applies here). Up to two more tiers are chained onto it via
    LangChain's `.with_fallbacks()`, each tried only if every tier before
    it fails:

    1. `WATSONX_INSTRUCT_MODEL_FALLBACK_ID`, if set (it is, by default) — a
       second watsonx model. Useful for a per-model outage or a model
       withdrawn from the catalog, but see (2): this tier shares the same
       watsonx account/project as the primary, so it does *not* help when
       the failure is an account-level quota rejection rather than a
       per-model one.
    2. Gemini (`_gemini_chat`, `GEMINI_INSTRUCT_MODEL_ID`), if `GEMINI_API_KEY`
       is set — added 2026-08-26 after a live `/ask` call hit
       `token_quota_reached` on *both* watsonx tiers back to back, proving
       (1)'s limitation above wasn't theoretical. A different provider is
       what actually routes around an account-wide watsonx rejection. Safe
       to chain as a real fallback (unlike `get_embedding_model`'s
       Gemini/watsonx choice, which is a straight replacement): a single
       generation call's output is plain text consumed once, not a
       persisted vector, so there's no "different vector space" hazard to
       worry about here.

    Every tier is wrapped with `_logged()` before chaining (see its
    docstring), so if all tiers fail, whichever exception `.with_fallbacks()`
    re-raises is only ever the LAST thing that went wrong on the user-facing
    side -- the full story, one line per tier, is always in the logs first.

    Leave both `WATSONX_INSTRUCT_MODEL_FALLBACK_ID` and `GEMINI_API_KEY`
    unset to get the bare primary `ChatWatsonx` client back, unchanged from
    before either fallback tier existed -- not wrapped in `_logged()`, since
    there is no fallback to log a transition to.
    """
    _require_credentials()
    primary = _chat_watsonx(settings.WATSONX_INSTRUCT_MODEL_ID)
    tiers: list[tuple[str, Runnable]] = [("watsonx primary", primary)]
    if settings.WATSONX_INSTRUCT_MODEL_FALLBACK_ID:
        tiers.append(("watsonx fallback", _chat_watsonx(settings.WATSONX_INSTRUCT_MODEL_FALLBACK_ID)))
    if settings.GEMINI_API_KEY:
        tiers.append(("gemini fallback", _gemini_chat()))
    if len(tiers) == 1:
        return primary
    logged = [_logged(model, label) for label, model in tiers]
    return logged[0].with_fallbacks(logged[1:])
