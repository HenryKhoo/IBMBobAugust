from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import query
from tests.conftest import _FakeDocument

FIXTURES = Path(__file__).parent / "fixtures"

client = TestClient(app)


class _FakeVectorStore:
    """Records the query/kwargs it was called with and returns fixed hits.

    `hits` is a list of `(document, relevance_score)` tuples, matching what
    `similarity_search_with_relevance_scores` returns — the same call
    `app.services.telemetry` makes, but `/query` has no `expr` filter and
    no instruct model in the loop, so there's no fake instruct model here.
    """

    def __init__(self, hits: list[tuple[_FakeDocument, float]]):
        self.hits = hits
        self.calls: list[dict] = []

    def similarity_search_with_relevance_scores(self, query_text, **kwargs):
        self.calls.append({"query": query_text, **kwargs})
        return self.hits


INCIDENT_TEXT = (FIXTURES / "sample_incident_record.txt").read_text()
INCIDENT_METADATA = {
    "doc_id": "sector-4-breach-incident",
    "doc_type": "incident_record",
    "chunk_index": 0,
}
SECTOR_SPEC_TEXT = (FIXTURES / "sample_sector_spec.txt").read_text()
SECTOR_SPEC_METADATA = {
    "doc_id": "sector-2-spec",
    "doc_type": "sector_spec",
    "chunk_index": 1,
}


@pytest.fixture
def fake_hits() -> list[tuple[_FakeDocument, float]]:
    return [
        (_FakeDocument(INCIDENT_TEXT, dict(INCIDENT_METADATA)), 0.91),
        (_FakeDocument(SECTOR_SPEC_TEXT, dict(SECTOR_SPEC_METADATA)), 0.42),
    ]


def test_run_query_returns_passages_ordered_by_relevance(monkeypatch, fake_hits):
    fake_store = _FakeVectorStore(fake_hits)
    monkeypatch.setattr(query, "get_vector_store", lambda: fake_store)

    response = query.run_query("What caused the Sector 4 breach?", top_k=5)

    assert [result.text for result in response.results] == [INCIDENT_TEXT, SECTOR_SPEC_TEXT]
    assert response.results[0].source == "incident_record:sector-4-breach-incident#chunk0"
    assert response.results[0].relevance == 0.91
    assert response.results[1].source == "sector_spec:sector-2-spec#chunk1"
    assert response.results[1].relevance == 0.42

    # no doc_type filter — unlike telemetry/crisis/triage/rationing, /query
    # searches the whole corpus.
    assert "expr" not in fake_store.calls[0]
    assert fake_store.calls[0]["query"] == "What caused the Sector 4 breach?"
    assert fake_store.calls[0]["k"] == 5


def test_run_query_clamps_relevance_into_unit_range(monkeypatch):
    fake_store = _FakeVectorStore(
        [(_FakeDocument(INCIDENT_TEXT, dict(INCIDENT_METADATA)), 1.4)]
    )
    monkeypatch.setattr(query, "get_vector_store", lambda: fake_store)

    response = query.run_query("breach", top_k=1)

    assert response.results[0].relevance == 1.0


def test_run_query_returns_empty_results_rather_than_raising(monkeypatch):
    fake_store = _FakeVectorStore([])
    monkeypatch.setattr(query, "get_vector_store", lambda: fake_store)

    # unlike telemetry/crisis/triage/rationing, an empty retrieval is not
    # an error here — there's no generated claim to protect from being
    # ungrounded.
    response = query.run_query("something not in the corpus", top_k=5)

    assert response.results == []


def test_endpoint_happy_path_matches_api_contract_shape(monkeypatch, fake_hits):
    fake_store = _FakeVectorStore(fake_hits)
    monkeypatch.setattr(query, "get_vector_store", lambda: fake_store)

    response = client.post(
        "/query", json={"question": "What caused the Sector 4 breach?", "top_k": 2}
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"results"}
    assert len(body["results"]) == 2
    assert set(body["results"][0].keys()) == {"text", "source", "relevance"}
    assert body["results"][0]["source"] == "incident_record:sector-4-breach-incident#chunk0"


def test_endpoint_defaults_top_k_to_five(monkeypatch, fake_hits):
    fake_store = _FakeVectorStore(fake_hits)
    monkeypatch.setattr(query, "get_vector_store", lambda: fake_store)

    response = client.post("/query", json={"question": "What caused the breach?"})

    assert response.status_code == 200
    assert fake_store.calls[0]["k"] == 5


def test_endpoint_returns_200_with_empty_results_when_nothing_matches(monkeypatch):
    fake_store = _FakeVectorStore([])
    monkeypatch.setattr(query, "get_vector_store", lambda: fake_store)

    response = client.post("/query", json={"question": "anything"})

    assert response.status_code == 200
    assert response.json() == {"results": []}


@pytest.mark.parametrize(
    "payload",
    [
        {},  # missing question
        {"question": ""},  # empty question
        {"question": "valid", "top_k": 0},  # top_k below minimum
        {"question": "valid", "top_k": 21},  # top_k above maximum
    ],
)
def test_endpoint_rejects_invalid_requests(payload):
    response = client.post("/query", json=payload)
    assert response.status_code == 422
