"""Endpoint tests for POST /ingest.

`test_ingestion.py` already unit-tests the pure chunking functions
(`chunk_text`, `chunk_document`, `chunk_documents`) `app.services.ingestion`
is built on. This file covers what was previously untested: the endpoint
itself, and `ingest_and_upsert()`'s wiring from chunked documents into
`vector_store.upsert_chunks` — the one path that would hit Granite
embeddings for real. Mocking boundary: `app.services.ingestion.upsert_chunks`
(the name `ingestion.py` imports and calls), the same "fast, no real
watsonx" pattern the other four endpoint test files use one level down at
`get_vector_store`/`get_instruct_model`.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import ingestion

client = TestClient(app)


class _FakeUpsert:
    """Records the texts/metadatas it was called with and returns a fixed count."""

    def __init__(self, count: int | None = None):
        self.count = count
        self.calls: list[dict] = []

    def __call__(self, texts, metadatas):
        self.calls.append({"texts": list(texts), "metadatas": list(metadatas)})
        return self.count if self.count is not None else len(texts)


TWO_DOCUMENTS_PAYLOAD = {
    "documents": [
        {
            "id": "nasa-smd-veggie-001",
            "type": "science_reference",
            "text": "Veggie is a deployable plant growth chamber used on the ISS.",
        },
        {
            "id": "nasa-smd-dart-001",
            "type": "science_reference",
            "text": "DART tested kinetic impact as a planetary defense technique.",
        },
    ]
}


def test_ingest_endpoint_returns_total_chunk_count_and_upserts_every_document(monkeypatch):
    fake_upsert = _FakeUpsert()
    monkeypatch.setattr(ingestion, "upsert_chunks", fake_upsert)

    response = client.post("/ingest", json=TWO_DOCUMENTS_PAYLOAD)

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"chunks_ingested"}
    # both documents here are short enough to stay in a single chunk each.
    assert body["chunks_ingested"] == 2

    assert len(fake_upsert.calls) == 1
    call = fake_upsert.calls[0]
    assert len(call["texts"]) == 2
    assert len(call["metadatas"]) == 2
    assert [m["doc_id"] for m in call["metadatas"]] == [
        "nasa-smd-veggie-001",
        "nasa-smd-dart-001",
    ]
    assert [m["doc_type"] for m in call["metadatas"]] == [
        "science_reference",
        "science_reference",
    ]


def test_ingest_endpoint_empty_documents_returns_zero_without_calling_upsert(monkeypatch):
    fake_upsert = _FakeUpsert()
    monkeypatch.setattr(ingestion, "upsert_chunks", fake_upsert)

    response = client.post("/ingest", json={"documents": []})

    assert response.status_code == 200
    assert response.json() == {"chunks_ingested": 0}
    # nothing to embed, so the embedding/upsert boundary must never be hit.
    assert fake_upsert.calls == []


@pytest.mark.parametrize(
    "payload",
    [
        {},  # missing documents
        {"documents": [{"type": "science_reference", "text": "Some text."}]},  # missing id
        {"documents": [{"id": "doc-1", "text": "Some text."}]},  # missing type
        {"documents": [{"id": "doc-1", "type": "science_reference"}]},  # missing text
        {"documents": [{"id": "doc-1", "type": "science_reference", "text": ""}]},  # empty text
        {"documents": [{"id": "doc-1", "type": "not_a_real_type", "text": "Some text."}]},  # invalid type
    ],
)
def test_ingest_endpoint_rejects_invalid_requests(monkeypatch, payload):
    fake_upsert = _FakeUpsert()
    monkeypatch.setattr(ingestion, "upsert_chunks", fake_upsert)

    response = client.post("/ingest", json=payload)

    assert response.status_code == 422
    assert fake_upsert.calls == []
