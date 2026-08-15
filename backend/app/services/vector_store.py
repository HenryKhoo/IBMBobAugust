"""Zilliz Cloud (managed Milvus) vector store wrapper.

Wraps the vector store the ingestion and retrieval pipeline needs, via
langchain-milvus's `Zilliz` vectorstore class, backed by the Granite
embedding client from `app.services.watsonx.get_embedding_model()`. This
mirrors `watsonx.py`'s pattern: one cached client, built from the shared
`Settings`, that the rest of the backend imports rather than constructing
`Zilliz` directly.

`upsert_chunks()` is the entry point `ingestion.py`'s `ingest_and_upsert()`
calls once chunks are ready. The four retrieval endpoints (telemetry,
crisis, triage, query) call `get_vector_store().similarity_search()` (or
`similarity_search_with_relevance_scores_or_empty()`, see below) directly.
"""

import logging
from functools import lru_cache

from langchain_milvus import Zilliz

from app.config import settings
from app.services.watsonx import get_embedding_model

logger = logging.getLogger(__name__)


def missing_credentials() -> list[str]:
    """Return the names of required Zilliz Cloud settings that are not set.

    Same single-source-of-truth rationale as
    `app.services.watsonx.missing_credentials`: `_require_credentials`
    raises on it, `app.main.health` reports it, and neither can drift from
    what a real retrieval call would actually do.
    """
    return [
        name
        for name, value in (
            ("ZILLIZ_URI", settings.ZILLIZ_URI),
            ("ZILLIZ_TOKEN", settings.ZILLIZ_TOKEN),
        )
        if not value
    ]


def _require_credentials() -> None:
    """Raise a clear error if Zilliz Cloud credentials are not configured.

    Same rationale as `watsonx._require_credentials`: a bare pymilvus/gRPC
    connection failure otherwise reads as a generic error deep in an
    ingestion or retrieval call.
    """
    missing = missing_credentials()
    if missing:
        raise RuntimeError(
            "Missing Zilliz Cloud credentials: "
            + ", ".join(missing)
            + ". Set them in a local .env at the repo root (see .env.example)."
        )


@lru_cache(maxsize=1)
def get_vector_store() -> Zilliz:
    """Return a cached Zilliz vector store client, embedding via Granite.

    `auto_id=True` lets Zilliz assign each chunk's primary key, since
    chunks are identified by their `doc_id`/`chunk_index` metadata (see
    `ingestion.Chunk.metadata`) rather than a caller-supplied id.
    """
    _require_credentials()
    return Zilliz(
        embedding_function=get_embedding_model(),
        collection_name=settings.ZILLIZ_COLLECTION_NAME,
        connection_args={
            "uri": settings.ZILLIZ_URI,
            "token": settings.ZILLIZ_TOKEN,
        },
        auto_id=True,
    )


def upsert_chunks(texts: list[str], metadatas: list[dict]) -> int:
    """Embed and upsert chunk texts into Zilliz, returning the count stored.

    `texts` and `metadatas` must be the same length and in the same
    order — each metadata dict carries the source attribution (doc id, doc
    type, chunk index) a retrieval hit needs to cite back to. Embedding
    happens inside `Zilliz.add_texts()`, via the Granite embedding client
    this store was built with.
    """
    if len(texts) != len(metadatas):
        raise ValueError("texts and metadatas must be the same length")
    if not texts:
        return 0
    ids = get_vector_store().add_texts(texts=texts, metadatas=metadatas)
    return len(ids)


def relevance_score_hits_or_empty(store, query: str, *, k: int, expr: str) -> list[tuple]:
    """Call `store.similarity_search_with_relevance_scores`, treating "no index yet" as no hits.

    langchain-milvus's `_select_relevance_score_fn` needs the collection's
    index params to pick a score-normalization function, and those are only
    set once the collection has been created by a prior `add_texts()` call
    (see `upsert_chunks`). Before that first ingest, the collection has no
    index yet, and this raises a plain `ValueError` ("No index params
    provided. Could not determine relevance function.") — unlike the plain
    `similarity_search()` used elsewhere in this codebase, which just
    returns `[]` in the same situation. Reproduced directly against a local
    Milvus instance (empty collection, no prior `add_texts()` call) while
    debugging the deployed backend's `/telemetry/interpret` and `/triage`
    endpoints, both of which call `similarity_search_with_relevance_scores`:
    every call was crashing with this unhandled `ValueError` rather than
    the intended "no hits" -> 404 path (see `app.main`'s `LookupError`
    handling). And because the exception was unhandled, it also skipped
    past `CORSMiddleware` — Starlette's `ServerErrorMiddleware` sits
    outside user middleware, so an uncaught exception's fallback 500
    response goes out with no CORS headers at all, which is what the
    browser was reporting as a CORS failure rather than a 500.

    `store` is passed in (rather than this function calling
    `get_vector_store()` itself) so callers keep using their own
    module-level `get_vector_store()` — what the existing unit tests
    monkeypatch — as the single source of the vector store instance.
    """
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
