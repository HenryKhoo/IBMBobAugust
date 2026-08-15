from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import telemetry

FIXTURES = Path(__file__).parent / "fixtures"

client = TestClient(app)


class _FakeDocument:
    """Stand-in for a langchain `Document` hit from `similarity_search`."""

    def __init__(self, page_content: str, metadata: dict):
        self.page_content = page_content
        self.metadata = metadata


class _FakeMessage:
    """Stand-in for the `AIMessage` a `ChatWatsonx` runnable's `invoke` returns."""

    def __init__(self, content: str):
        self.content = content


class _FakeVectorStore:
    """Records the query/kwargs it was called with and returns fixed hits."""

    def __init__(self, hits: list[_FakeDocument]):
        self.hits = hits
        self.calls: list[dict] = []

    def similarity_search(self, query, **kwargs):
        self.calls.append({"query": query, **kwargs})
        return self.hits


class _FakeInstructModel:
    """Records whether/how it was invoked and returns a fixed message."""

    def __init__(self, content: str):
        self.content = content
        self.invoked_with: list[str] = []

    def invoke(self, prompt):
        self.invoked_with.append(prompt)
        return _FakeMessage(self.content)


SECTOR_SPEC_TEXT = (FIXTURES / "sample_sector_spec.txt").read_text()
SECTOR_SPEC_METADATA = {
    "doc_id": "sector-2-spec",
    "doc_type": "sector_spec",
    "chunk_index": 0,
}
STUBBED_SUMMARY = (
    "O2 saturation and cabin pressure are within the nominal band; "
    "no action required."
)


@pytest.fixture
def fake_hit() -> _FakeDocument:
    return _FakeDocument(SECTOR_SPEC_TEXT, dict(SECTOR_SPEC_METADATA))


def test_interpret_telemetry_returns_grounded_summary_and_source(monkeypatch, fake_hit):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_SUMMARY)
    monkeypatch.setattr(telemetry, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(telemetry, "get_instruct_model", lambda: fake_model)

    response = telemetry.interpret_telemetry(
        "oxygen", {"eff": 85, "o2pp": 158, "humidity": 34}
    )

    assert response.summary == STUBBED_SUMMARY
    assert response.confidence is None
    assert response.source == "sector_spec:sector-2-spec#chunk0"

    # retrieval was filtered to sector_spec chunks, and the prompt handed to
    # the instruct model is grounded in the retrieved chunk's text.
    assert fake_store.calls[0]["expr"] == "doc_type == 'sector_spec'"
    assert SECTOR_SPEC_TEXT in fake_model.invoked_with[0]


def test_interpret_telemetry_raises_when_nothing_is_retrieved(monkeypatch):
    fake_store = _FakeVectorStore([])
    fake_model = _FakeInstructModel(STUBBED_SUMMARY)
    monkeypatch.setattr(telemetry, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(telemetry, "get_instruct_model", lambda: fake_model)

    with pytest.raises(LookupError):
        telemetry.interpret_telemetry("oxygen", {"eff": 85})

    # no grounding chunk was found, so the model must never be asked to
    # generate an ungrounded guess.
    assert fake_model.invoked_with == []


def test_endpoint_returns_404_when_nothing_is_retrieved(monkeypatch):
    fake_store = _FakeVectorStore([])
    fake_model = _FakeInstructModel(STUBBED_SUMMARY)
    monkeypatch.setattr(telemetry, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(telemetry, "get_instruct_model", lambda: fake_model)

    response = client.post(
        "/telemetry/interpret",
        json={"sector_id": "oxygen", "metrics": {"eff": 85}},
    )

    assert response.status_code == 404
    assert fake_model.invoked_with == []


def test_endpoint_happy_path_matches_api_contract_shape(monkeypatch, fake_hit):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_SUMMARY)
    monkeypatch.setattr(telemetry, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(telemetry, "get_instruct_model", lambda: fake_model)

    response = client.post(
        "/telemetry/interpret",
        json={"sector_id": "oxygen", "metrics": {"eff": 85, "o2pp": 158}},
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"summary", "confidence", "source"}
    assert body["summary"] == STUBBED_SUMMARY
    assert body["confidence"] is None
    assert body["source"] == "sector_spec:sector-2-spec#chunk0"


@pytest.mark.parametrize(
    "payload",
    [
        {"metrics": {"eff": 85}},  # missing sector_id
        {"sector_id": "oxygen"},  # missing metrics
        {"sector_id": "oxygen", "metrics": {}},  # empty metrics
        {"sector_id": "oxygen", "metrics": {"eff": "high"}},  # non-numeric reading
        {"sector_id": "", "metrics": {"eff": 85}},  # empty sector_id
    ],
)
def test_endpoint_rejects_invalid_requests(payload):
    response = client.post("/telemetry/interpret", json=payload)
    assert response.status_code == 422
