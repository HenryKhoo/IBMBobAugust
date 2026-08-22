from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import talkback
from tests.conftest import _FakeDocument, _FakeInstructModel, _FakeMessage

FIXTURES = Path(__file__).parent / "fixtures"

client = TestClient(app)


class _FakeVectorStore:
    """Records the query/kwargs it was called with and returns fixed hits."""

    def __init__(self, hits: list[tuple[_FakeDocument, float]]):
        self.hits = hits
        self.calls: list[dict] = []

    def similarity_search_with_relevance_scores(self, query, **kwargs):
        self.calls.append({"query": query, **kwargs})
        return self.hits


REFERENCE_TEXT = (
    "Source: Veggie\n\nThe Vegetable Production System (Veggie) is a "
    "deployable plant growth chamber used to study and grow crops in the "
    "unique environment of space.\n\n"
    "Q: What is Veggie?\nA: A plant growth chamber on the ISS."
)
REFERENCE_METADATA = {
    "doc_id": "nasa-smd-veggie-001",
    "doc_type": "science_reference",
    "chunk_index": 0,
}
STUBBED_ANSWER = "Veggie is a deployable plant growth chamber used on the ISS to study crops."
RELEVANCE_SCORE = 0.82


@pytest.fixture
def fake_hit() -> tuple[_FakeDocument, float]:
    return (_FakeDocument(REFERENCE_TEXT, dict(REFERENCE_METADATA)), RELEVANCE_SCORE)


def test_ask_baseline_returns_grounded_answer_and_source(monkeypatch, fake_hit):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(talkback, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(talkback, "get_instruct_model", lambda: fake_model)

    response = talkback.ask_talkback("What is Veggie?", talkback.AskPersona.BASELINE, humor=50)

    assert response.answer == STUBBED_ANSWER
    assert response.persona == talkback.AskPersona.BASELINE
    assert response.grounded is True
    assert response.confidence == RELEVANCE_SCORE
    assert response.source == "science_reference:nasa-smd-veggie-001#chunk0"
    # exactly one generation call for Baseline — no second, unnecessary pass.
    assert len(fake_model.invoked_with) == 1
    assert REFERENCE_TEXT in fake_model.invoked_with[0]


def test_ask_banter_restyles_the_baseline_answer_without_regenerating_the_fact(
    monkeypatch, fake_hit
):
    """The property that actually enforces "honesty is not a dial": Banter's
    prompt must contain Baseline's exact finished answer, proving Banter is
    re-telling a fact that was already generated and grounded, never
    answering the question itself from scratch.
    """
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(talkback, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(talkback, "get_instruct_model", lambda: fake_model)

    talkback.ask_talkback("What is Veggie?", talkback.AskPersona.BANTER, humor=80)

    # two generation calls: the baseline fact, then the banter restyle.
    assert len(fake_model.invoked_with) == 2
    baseline_prompt, banter_prompt = fake_model.invoked_with
    assert REFERENCE_TEXT in baseline_prompt
    assert STUBBED_ANSWER in banter_prompt
    assert "80/100" in banter_prompt


def test_ask_falls_back_honestly_when_nothing_is_retrieved(monkeypatch):
    fake_store = _FakeVectorStore([])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(talkback, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(talkback, "get_instruct_model", lambda: fake_model)

    response = talkback.ask_talkback("anything", talkback.AskPersona.BASELINE, humor=50)

    assert response.grounded is False
    assert response.confidence is None
    assert response.source is None
    assert response.answer == "No grounded answer for that."
    # never asked the model to guess.
    assert fake_model.invoked_with == []


def test_ask_falls_back_below_confidence_threshold_with_persona_specific_wording(
    monkeypatch,
):
    weak_hit = (_FakeDocument(REFERENCE_TEXT, dict(REFERENCE_METADATA)), 0.1)
    fake_store = _FakeVectorStore([weak_hit])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(talkback, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(talkback, "get_instruct_model", lambda: fake_model)

    baseline_response = talkback.ask_talkback(
        "anything", talkback.AskPersona.BASELINE, humor=50
    )
    banter_response = talkback.ask_talkback("anything", talkback.AskPersona.BANTER, humor=50)

    assert baseline_response.grounded is False
    assert baseline_response.confidence == 0.1
    assert banter_response.grounded is False
    assert banter_response.answer != baseline_response.answer
    assert fake_model.invoked_with == []


def test_endpoint_happy_path_matches_api_contract_shape(monkeypatch, fake_hit):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(talkback, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(talkback, "get_instruct_model", lambda: fake_model)

    response = client.post("/ask", json={"question": "What is Veggie?", "persona": "baseline"})

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"answer", "persona", "grounded", "confidence", "source"}
    assert body["answer"] == STUBBED_ANSWER
    assert body["grounded"] is True


def test_endpoint_never_404s_on_no_match(monkeypatch):
    fake_store = _FakeVectorStore([])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(talkback, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(talkback, "get_instruct_model", lambda: fake_model)

    response = client.post("/ask", json={"question": "anything"})

    assert response.status_code == 200
    assert response.json()["grounded"] is False


def test_endpoint_defaults_persona_to_baseline_and_humor_to_fifty(monkeypatch, fake_hit):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(talkback, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(talkback, "get_instruct_model", lambda: fake_model)

    response = client.post("/ask", json={"question": "What is Veggie?"})

    assert response.status_code == 200
    assert response.json()["persona"] == "baseline"


@pytest.mark.parametrize(
    "payload",
    [
        {},  # missing question
        {"question": ""},  # empty question
        {"question": "valid", "persona": "sarcastic"},  # invalid persona
        {"question": "valid", "humor": 101},  # humor above maximum
        {"question": "valid", "humor": -1},  # humor below minimum
    ],
)
def test_endpoint_rejects_invalid_requests(payload):
    response = client.post("/ask", json=payload)
    assert response.status_code == 422
