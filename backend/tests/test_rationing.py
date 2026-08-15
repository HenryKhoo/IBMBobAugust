from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import rationing
from tests.conftest import _FakeDocument, _FakeInstructModel, _FakeMessage

FIXTURES = Path(__file__).parent / "fixtures"

client = TestClient(app)


class _FakeVectorStore:
    """Records the query/kwargs it was called with and returns fixed hits.

    `hits` is a list of `Document`-like objects, matching what
    `similarity_search` returns (no relevance score — `/rationing/simulate`
    has no `confidence` field in `API.md`, same as `/crisis/analyze`).
    """

    def __init__(self, hits: list[_FakeDocument]):
        self.hits = hits
        self.calls: list[dict] = []

    def similarity_search(self, query, **kwargs):
        self.calls.append({"query": query, **kwargs})
        return self.hits


PROTOCOL_TEXT = (FIXTURES / "sample_rationing_protocol.txt").read_text()
PROTOCOL_METADATA = {
    "doc_id": "food-rationing-shortfall",
    "doc_type": "procedure",
    "chunk_index": 0,
}
STUBBED_NARRATIVE = (
    "Hold the ration at the modeled level and suspend high-exertion tasks; "
    "the current plan leaves a projected surplus at resupply."
)


@pytest.fixture
def fake_hit() -> _FakeDocument:
    return _FakeDocument(PROTOCOL_TEXT, dict(PROTOCOL_METADATA))


def test_simulate_rationing_returns_grounded_narrative_survival_and_source(
    monkeypatch, fake_hit
):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_NARRATIVE)
    monkeypatch.setattr(rationing, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(rationing, "get_instruct_model", lambda: fake_model)

    # Surplus scenario: 1,650,000 kcal on hand, 2,000 kcal/person/day ration,
    # 45 days to resupply. daily_burn = 2000*4 = 8000; buffer =
    # 1,650,000 - 8000*45 = 1,290,000 (non-negative) -> base tier (2000+) = 99.
    response = rationing.simulate_rationing(1_650_000, 2000, 45)

    assert response.narrative == STUBBED_NARRATIVE
    assert response.survival_probability == 99.0
    assert response.source == "procedure:food-rationing-shortfall#chunk0"

    # retrieval was filtered to procedure chunks, and the prompt handed to
    # the instruct model is grounded in the retrieved chunk's text.
    assert fake_store.calls[0]["expr"] == "doc_type == 'procedure'"
    assert PROTOCOL_TEXT in fake_model.invoked_with[0]


def test_simulate_rationing_shortfall_scenario(monkeypatch, fake_hit):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_NARRATIVE)
    monkeypatch.setattr(rationing, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(rationing, "get_instruct_model", lambda: fake_model)

    # Mirrors mission-console.html's default crop-failure scenario:
    # 320,000 kcal on hand, standard 2,500 kcal/person/day ration, 45 days
    # to resupply. daily_burn = 2500*4 = 10000; buffer =
    # 320,000 - 10000*45 = -130,000 -> base (2000+) = 99, shortfall_days =
    # ceil(130000/10000) = 13, survival = max(5, min(60, 99 - 13*4)) = 47.
    response = rationing.simulate_rationing(320_000, 2500, 45)

    assert response.survival_probability == 47.0


def test_simulate_rationing_raises_when_nothing_is_retrieved(monkeypatch):
    fake_store = _FakeVectorStore([])
    fake_model = _FakeInstructModel(STUBBED_NARRATIVE)
    monkeypatch.setattr(rationing, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(rationing, "get_instruct_model", lambda: fake_model)

    with pytest.raises(LookupError):
        rationing.simulate_rationing(1_650_000, 2000, 45)

    # no grounding chunk was found, so the model must never be asked to
    # generate an ungrounded guess.
    assert fake_model.invoked_with == []


def test_endpoint_returns_404_when_nothing_is_retrieved(monkeypatch):
    fake_store = _FakeVectorStore([])
    fake_model = _FakeInstructModel(STUBBED_NARRATIVE)
    monkeypatch.setattr(rationing, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(rationing, "get_instruct_model", lambda: fake_model)

    response = client.post(
        "/rationing/simulate",
        json={"stock_level": 1_650_000, "ration_amount": 2000, "days_until_resupply": 45},
    )

    assert response.status_code == 404
    assert fake_model.invoked_with == []


def test_endpoint_happy_path_matches_api_contract_shape(monkeypatch, fake_hit):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_NARRATIVE)
    monkeypatch.setattr(rationing, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(rationing, "get_instruct_model", lambda: fake_model)

    response = client.post(
        "/rationing/simulate",
        json={"stock_level": 1_650_000, "ration_amount": 2000, "days_until_resupply": 45},
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"narrative", "survival_probability", "source"}
    assert body["narrative"] == STUBBED_NARRATIVE
    assert body["survival_probability"] == 99.0
    assert body["source"] == "procedure:food-rationing-shortfall#chunk0"


@pytest.mark.parametrize(
    "payload",
    [
        {"ration_amount": 2000, "days_until_resupply": 45},  # missing stock_level
        {"stock_level": 1_650_000, "days_until_resupply": 45},  # missing ration_amount
        {"stock_level": 1_650_000, "ration_amount": 2000},  # missing days_until_resupply
        {"stock_level": -1, "ration_amount": 2000, "days_until_resupply": 45},  # negative stock
        {"stock_level": 1_650_000, "ration_amount": 0, "days_until_resupply": 45},  # zero ration
        {"stock_level": 1_650_000, "ration_amount": -100, "days_until_resupply": 45},  # negative ration
        {"stock_level": 1_650_000, "ration_amount": 2000, "days_until_resupply": 0},  # zero days
        {"stock_level": 1_650_000, "ration_amount": 2000, "days_until_resupply": -1},  # negative days
        {"stock_level": "a lot", "ration_amount": 2000, "days_until_resupply": 45},  # non-numeric stock
    ],
)
def test_endpoint_rejects_invalid_requests(payload):
    response = client.post("/rationing/simulate", json=payload)
    assert response.status_code == 422


# --- Survival-probability helper, tested directly ---------------------------


@pytest.mark.parametrize(
    "ration_amount, buffer, daily_burn, expected",
    [
        # Non-negative buffer returns the ration tier's base unchanged,
        # regardless of daily_burn, at every tier boundary.
        (2000, 1.0, 8000, 99.0),
        (1999, 1.0, 7996, 95.0),
        (1800, 1.0, 7200, 95.0),
        (1799, 1.0, 7196, 85.0),
        (1500, 1.0, 6000, 85.0),
        (1499, 1.0, 5996, 65.0),
        (1200, 1.0, 4800, 65.0),
        (1199, 1.0, 4796, 40.0),
        (0.01, 1.0, 0.04, 40.0),
        (2000, 0, 8000, 99.0),  # exactly zero buffer counts as non-negative
    ],
)
def test_survival_probability_non_negative_buffer_returns_base_tier(
    ration_amount, buffer, daily_burn, expected
):
    assert rationing._survival_probability(ration_amount, buffer, daily_burn) == expected


def test_survival_probability_shortfall_scales_penalty_by_days_early():
    # base 99 (ration >= 2000); shortfall_days = ceil(130000/10000) = 13;
    # 99 - 13*4 = 47, within [5, 60].
    assert rationing._survival_probability(2500, -130_000, 10_000) == 47.0


def test_survival_probability_shortfall_clamps_to_floor():
    # base 40 (ration < 1200); a very early, large stock-out drives
    # base - shortfall_days*4 far below 5, which must clamp to 5.
    assert rationing._survival_probability(1000, -3_999_000, 4_000) == 5.0


def test_survival_probability_shortfall_clamps_to_ceiling():
    # base 99, but even a 1-day-early shortfall (99 - 4 = 95) must clamp to
    # the 60 ceiling — running out at all caps the score even if barely.
    assert rationing._survival_probability(2500, -9_900, 10_000) == 60.0


def test_survival_probability_zero_daily_burn_treated_as_one_day_shortfall():
    # daily_burn <= 0 can't derive a shortfall-days count from division, so
    # it's treated as a 1-day shortfall rather than raising or dividing by
    # zero (mirrors the frontend's `dailyBurn > 0 ? ... : 1` guard).
    assert rationing._survival_probability(1000, -1.0, 0) == 36.0  # 40 - 1*4
