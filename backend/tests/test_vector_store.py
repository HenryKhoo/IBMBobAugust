"""Unit tests for app.services.vector_store.upsert_chunks.

This is the boundary POST /ingest's `ingest_and_upsert()` calls once chunks
are ready (see app.services.ingestion), and the one place the backend would
actually hit Granite embeddings for real — previously untested. These tests
exercise `upsert_chunks`'s own pure-Python guards directly, mirroring how
`test_rationing.py` unit-tests `_survival_probability` directly rather than
only through the endpoint.
"""

import pytest

from app.services import vector_store


class _FakeZillizStore:
    """Records the texts/metadatas it was upserted with and returns fixed ids."""

    def __init__(self, ids: list[str]):
        self.ids = ids
        self.calls: list[dict] = []

    def add_texts(self, texts, metadatas):
        self.calls.append({"texts": list(texts), "metadatas": list(metadatas)})
        return self.ids


def test_upsert_chunks_raises_on_mismatched_lengths(monkeypatch):
    def _fail_if_called():
        raise AssertionError("get_vector_store must not be called before the length guard runs")

    monkeypatch.setattr(vector_store, "get_vector_store", _fail_if_called)

    with pytest.raises(ValueError):
        vector_store.upsert_chunks(["a", "b"], [{"doc_id": "x"}])


def test_upsert_chunks_empty_texts_returns_zero_without_calling_the_store(monkeypatch):
    def _fail_if_called():
        raise AssertionError("get_vector_store must not be called when there is nothing to embed")

    monkeypatch.setattr(vector_store, "get_vector_store", _fail_if_called)

    assert vector_store.upsert_chunks([], []) == 0


def test_upsert_chunks_happy_path_embeds_and_upserts_via_the_store(monkeypatch):
    fake_store = _FakeZillizStore(ids=["id-1", "id-2"])
    monkeypatch.setattr(vector_store, "get_vector_store", lambda: fake_store)

    texts = ["Step one. Step two.", "Nominal band is 30-60%."]
    metadatas = [
        {"doc_id": "proc-1", "doc_type": "procedure", "chunk_index": 0},
        {"doc_id": "spec-1", "doc_type": "sector_spec", "chunk_index": 0},
    ]

    count = vector_store.upsert_chunks(texts, metadatas)

    assert count == 2
    assert fake_store.calls[0]["texts"] == texts
    assert fake_store.calls[0]["metadatas"] == metadatas


class _FakeStoreNoIndexYet:
    """Mimics langchain-milvus's `similarity_search_with_relevance_scores` before any
    ingestion has ever happened: it raises `ValueError("No index params provided.
    Could not determine relevance function.")` instead of returning `[]`.

    Reproduced against a real local Milvus instance (see the debugging notes on
    `relevance_score_hits_or_empty`) — this is exactly what the deployed backend hit on
    every `/telemetry/interpret` and `/triage` call before anything had been ingested.
    """

    def similarity_search_with_relevance_scores(self, query, **kwargs):
        raise ValueError("No index params provided. Could not determine relevance function.")


class _FakeStoreOtherValueError:
    """A `ValueError` unrelated to the missing-index case should not be swallowed."""

    def similarity_search_with_relevance_scores(self, query, **kwargs):
        raise ValueError("some other problem entirely")


def test_relevance_score_hits_or_empty_returns_empty_when_index_not_created_yet():
    hits = vector_store.relevance_score_hits_or_empty(
        _FakeStoreNoIndexYet(), "query text", k=1, expr="doc_type == 'sector_spec'"
    )
    assert hits == []


def test_relevance_score_hits_or_empty_reraises_unrelated_value_errors():
    with pytest.raises(ValueError, match="some other problem"):
        vector_store.relevance_score_hits_or_empty(
            _FakeStoreOtherValueError(), "query text", k=1, expr="doc_type == 'sector_spec'"
        )


def test_escape_expr_string_literal_escapes_single_quotes():
    assert vector_store.escape_expr_string_literal("abc'def") == "abc\\'def"


def test_escape_expr_string_literal_escapes_backslashes_before_quotes():
    # backslash escaped first, so an attacker can't pre-seed a `\'` that
    # would be read back as an already-escaped (and thus unescaped) quote.
    assert vector_store.escape_expr_string_literal("a\\'b") == "a\\\\\\'b"


def test_escape_expr_string_literal_is_a_no_op_on_a_plain_value():
    assert vector_store.escape_expr_string_literal("session-abc-123") == "session-abc-123"


def test_relevance_score_hits_or_empty_passes_through_real_hits():
    fake_store = _FakeZillizStore(ids=[])  # unused here, just needs the right method
    fake_store.similarity_search_with_relevance_scores = lambda query, **kwargs: [
        ("doc", 0.9)
    ]
    hits = vector_store.relevance_score_hits_or_empty(
        fake_store, "query text", k=1, expr="doc_type == 'sector_spec'"
    )
    assert hits == [("doc", 0.9)]
