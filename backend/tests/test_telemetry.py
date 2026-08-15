from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import telemetry
from app.services.extraction import SectorThreshold

FIXTURES = Path(__file__).parent / "fixtures"

client = TestClient(app)


class _FakeDocument:
    """Stand-in for a langchain `Document` hit from retrieval."""

    def __init__(self, page_content: str, metadata: dict):
        self.page_content = page_content
        self.metadata = metadata


class _FakeMessage:
    """Stand-in for the `AIMessage` a `ChatWatsonx` runnable's `invoke` returns."""

    def __init__(self, content: str):
        self.content = content


class _FakeVectorStore:
    """Records the query/kwargs it was called with and returns fixed hits.

    `hits` is a list of `(document, relevance_score)` tuples, matching what
    `similarity_search_with_relevance_scores` returns.
    """

    def __init__(self, hits: list[tuple[_FakeDocument, float]]):
        self.hits = hits
        self.calls: list[dict] = []

    def similarity_search_with_relevance_scores(self, query, **kwargs):
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
# Fixed for test math: RELEVANCE_SCORE alone (no band match) rounds to 0.8;
# combined with a fully-conforming band match (1.0) it rounds to 0.9.
RELEVANCE_SCORE = 0.8


@pytest.fixture
def fake_hit() -> tuple[_FakeDocument, float]:
    return (_FakeDocument(SECTOR_SPEC_TEXT, dict(SECTOR_SPEC_METADATA)), RELEVANCE_SCORE)


def test_interpret_telemetry_returns_grounded_summary_and_source(monkeypatch, fake_hit):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_SUMMARY)
    monkeypatch.setattr(telemetry, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(telemetry, "get_instruct_model", lambda: fake_model)

    # "humidity" is the only metric with an alias entry (see
    # app.services.metric_aliases), and 34 falls inside the fixture's
    # 30-60% band, so this exercises the combined retrieval+band path.
    response = telemetry.interpret_telemetry(
        "oxygen", {"eff": 85, "o2pp": 158, "humidity": 34}
    )

    assert response.summary == STUBBED_SUMMARY
    assert response.confidence == 0.9  # round(0.5*0.8 + 0.5*1.0, 2)
    assert response.source == "sector_spec:sector-2-spec#chunk0"

    # retrieval was filtered to sector_spec chunks, and the prompt handed to
    # the instruct model is grounded in the retrieved chunk's text.
    assert fake_store.calls[0]["expr"] == "doc_type == 'sector_spec'"
    assert SECTOR_SPEC_TEXT in fake_model.invoked_with[0]


def test_interpret_telemetry_falls_back_to_retrieval_strength_when_no_metric_matches(
    monkeypatch, fake_hit
):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_SUMMARY)
    monkeypatch.setattr(telemetry, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(telemetry, "get_instruct_model", lambda: fake_model)

    # Neither "eff" nor "o2pp" has an alias entry, so no band signal exists
    # at all — confidence should be retrieval strength alone, not a
    # fabricated filler for the missing band signal.
    response = telemetry.interpret_telemetry("oxygen", {"eff": 85, "o2pp": 158})

    assert response.confidence == RELEVANCE_SCORE


def test_interpret_telemetry_confidence_drops_for_out_of_band_reading(
    monkeypatch, fake_hit
):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_SUMMARY)
    monkeypatch.setattr(telemetry, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(telemetry, "get_instruct_model", lambda: fake_model)

    # Humidity's band is 30-60%; 90% is a full band-width (30) past the
    # high edge, so conformity bottoms out at 0.0.
    response = telemetry.interpret_telemetry("oxygen", {"humidity": 90})

    assert response.confidence == 0.4  # round(0.5*0.8 + 0.5*0.0, 2)


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
    assert body["confidence"] == RELEVANCE_SCORE
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


# --- Confidence-scoring helpers, tested directly ---------------------------


@pytest.mark.parametrize(
    "score, expected",
    [
        (0.0, 0.0),
        (1.0, 1.0),
        (0.42, 0.42),
        (-0.1, 0.0),  # clamps below 0 (L2 mapping can dip negative)
        (1.2, 1.0),  # clamps above 1 (defensive; base class only warns)
    ],
)
def test_retrieval_strength_clamps_to_unit_range(score, expected):
    assert telemetry._retrieval_strength(score) == expected


def test_metric_conformity_full_inside_band():
    threshold = SectorThreshold(metric="humidity", low=30.0, high=60.0, unit="%")
    assert telemetry._metric_conformity(45, threshold) == 1.0
    # boundaries are inclusive
    assert telemetry._metric_conformity(30, threshold) == 1.0
    assert telemetry._metric_conformity(60, threshold) == 1.0


def test_metric_conformity_decays_outside_band():
    threshold = SectorThreshold(metric="humidity", low=30.0, high=60.0, unit="%")
    # 15 past the high edge, band width 30 -> half conformity.
    assert telemetry._metric_conformity(75, threshold) == 0.5
    # a full band-width past the edge or further bottoms out at 0.0.
    assert telemetry._metric_conformity(90, threshold) == 0.0
    assert telemetry._metric_conformity(1000, threshold) == 0.0


def test_metric_conformity_none_for_zero_width_band():
    threshold = SectorThreshold(metric="fixed", low=10.0, high=10.0, unit="")
    assert telemetry._metric_conformity(10, threshold) is None


def test_band_conformity_none_when_chunk_has_no_thresholds():
    assert telemetry._band_conformity("no numbers here", {"humidity": 34}) is None


def test_band_conformity_none_when_no_metric_matches():
    # "eff"/"o2pp" have no alias entry in app.services.metric_aliases.
    result = telemetry._band_conformity(SECTOR_SPEC_TEXT, {"eff": 85, "o2pp": 158})
    assert result is None


def test_band_conformity_averages_matched_metrics():
    # Only "humidity" has an alias; a single matched, fully-conforming
    # metric averages to exactly its own conformity.
    result = telemetry._band_conformity(SECTOR_SPEC_TEXT, {"humidity": 45})
    assert result == 1.0


@pytest.mark.parametrize(
    "retrieval_strength, band_conformity, expected",
    [
        (0.8, 1.0, 0.9),
        (0.8, 0.0, 0.4),
        (0.8, None, 0.8),
        (1.0, None, 1.0),
        (0.333, 0.667, 0.5),
    ],
)
def test_combine_confidence(retrieval_strength, band_conformity, expected):
    assert telemetry._combine_confidence(retrieval_strength, band_conformity) == expected
