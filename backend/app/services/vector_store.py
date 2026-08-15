"""Zilliz Cloud (managed Milvus) vector store wrapper.

Wraps the vector store the ingestion and retrieval pipeline needs, via
langchain-milvus's `Zilliz` vectorstore class, backed by the Granite
embedding client from `app.services.watsonx.get_embedding_model()`. This
mirrors `watsonx.py`'s pattern: one cached client, built from the shared
`Settings`, that the rest of the backend imports rather than constructing
`Zilliz` directly.

`upsert_chunks()` is the entry point `ingestion.py`'s `ingest_and_upsert()`
calls once chunks are ready. The four retrieval endpoints (telemetry,
crisis, triage, query) will call `get_vector_store().similarity_search()`
directly once they're built.
"""

from functools import lru_cache

from langchain_milvus import Zilliz

from app.config import settings
from app.services.watsonx import get_embedding_model


def _require_credentials() -> None:
    """Raise a clear error if Zilliz Cloud credentials are not configured.

    Same rationale as `watsonx._require_credentials`: a bare pymilvus/gRPC
    connection failure otherwise reads as a generic error deep in an
    ingestion or retrieval call.
    """
    missing = [
        name
        for name, value in (
            ("ZILLIZ_URI", settings.ZILLIZ_URI),
            ("ZILLIZ_TOKEN", settings.ZILLIZ_TOKEN),
        )
        if not value
    ]
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
