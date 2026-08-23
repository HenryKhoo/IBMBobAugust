"""Zilliz Cloud (managed Milvus) vector store wrapper."""

import logging
from functools import lru_cache

from langchain_milvus import Zilliz

from app.config import settings
from app.services.watsonx import get_embedding_model

logger = logging.getLogger(__name__)

# Explicit so every process that builds a Zilliz client -- the FastAPI
# server (query-side) and backend/scripts/ingest_talkback_corpus.py
# (write-side) alike -- agrees on the metric type without either one having
# to guess. Without this, whichever process happens to *create* the
# collection (first `add_texts()` call) silently defaults to L2, and every
# other process that only ever queries it (like the running server) has no
# local record of that choice: langchain_milvus can't ask Zilliz what index
# a collection already has, so `_select_relevance_score_fn` falls back to
# assuming L2 too and logs "No index params provided. Could not determine
# relevance function. Use L2 distance as default." That fallback happened
# to land on the same metric here, so it wasn't silently *wrong* -- but L2
# distance mapped via `1 - l2/4` isn't well calibrated for confidence
# filtering unless the embeddings are unit-normalized, and it has no
# meaningful "unrelated" zero-point. COSINE does: a similarity near 0 means
# genuinely unrelated, so weak matches actually score low instead of
# clustering in a 0.6-0.85 band regardless of relevance.
#
# Changing this only affects a *new* collection -- Milvus doesn't let an
# existing index change metric type in place. If ZILLIZ_COLLECTION_NAME
# already has data ingested under the old L2 default, drop it first with
# backend/scripts/reset_zilliz_collection.py, then re-run
# backend/scripts/ingest_talkback_corpus.py so it's recreated with this
# metric type baked in.
_INDEX_PARAMS = {"metric_type": "COSINE", "index_type": "AUTOINDEX", "params": {}}


def missing_credentials() -> list[str]:
    return [
        name
        for name, value in (
            ("ZILLIZ_URI", settings.ZILLIZ_URI),
            ("ZILLIZ_TOKEN", settings.ZILLIZ_TOKEN),
        )
        if not value
    ]


def _require_credentials() -> None:
    missing = missing_credentials()
    if missing:
        raise RuntimeError(
            "Missing Zilliz Cloud credentials: "
            + ", ".join(missing)
            + ". Set them in a local .env at the repo root (see .env.example)."
        )


@lru_cache(maxsize=1)
def get_vector_store() -> Zilliz:
    _require_credentials()
    return Zilliz(
        embedding_function=get_embedding_model(),
        collection_name=settings.ZILLIZ_COLLECTION_NAME,
        connection_args={
            "uri": settings.ZILLIZ_URI,
            "token": settings.ZILLIZ_TOKEN,
        },
        index_params=_INDEX_PARAMS,
        auto_id=True,
    )


def upsert_chunks(texts: list[str], metadatas: list[dict]) -> int:
    if len(texts) != len(metadatas):
        raise ValueError("texts and metadatas must be the same length")
    if not texts:
        return 0
    ids = get_vector_store().add_texts(texts=texts, metadatas=metadatas)
    return len(ids)


def escape_expr_string_literal(value: str) -> str:
    """Escape a value for safe interpolation into a Milvus boolean `expr` string.

    Every `expr` filter in this codebase used to be a fixed literal (e.g.
    `"doc_type == 'science_reference'"`) — no request ever supplied the
    value going inside the quotes. `app.services.memory`'s session-scoped
    history recall is the first `expr` built from caller-controlled input
    (`session_id`, which `app.services.memory.get_or_create_session`
    deliberately accepts as an arbitrary string and treats an unrecognized
    one as valid). Without escaping, a `session_id` containing a `'` could
    break out of the string literal and rewrite the filter — e.g. drop the
    `doc_id == '...'` clause entirely and turn a session-scoped recall into
    a search across every session's history, exactly the cross-visitor
    leakage this filter exists to prevent. Backslash is escaped first so an
    already-escaped quote can't be re-interpreted.
    """
    return value.replace("\\", "\\\\").replace("'", "\\'")


def relevance_score_hits_or_empty(store, query: str, *, k: int, expr: str) -> list[tuple]:
    try:
        return store.similarity_search_with_relevance_scores(query, k=k, expr=expr)
    except ValueError as exc:
        if "index params" not in str(exc).lower():
            raise
        logger.warning(
            "similarity_search_with_relevance_scores found no index yet for "
            "expr=%r (nothing ingested for this doc_type?) — treating as no hits: %s",
            expr,
            exc,
        )
        return []
