from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import CrisisEvent
from app.services import crisis
from tests.conftest import _FakeDocument, _FakeInstructModel, _FakeMessage

FIXTURES = Path(__file__).parent / "fixtures"

client = TestClient(app)


class _FakeVectorStore:
    """Records the query/kwargs it was called with and returns fixed hits.

    `hits` is either a flat list of `Document`-like hits (returned for
    every call, the original single-cause behavior) or a dict of
    `{sector: hits}` for tests exercising a compound feed where different
    sectors must retrieve different procedure chunks — matched against the
    `"{sector} sector event: ..."` query shape `crisis._build_retrieval_query`
    builds per sector group. A sector with no dict entry, or an empty list,
    returns no hits (see `test_analyze_crisis_raises_when_nothing_is_retrieved`
    and the multi-sector partial-match test below).

    No relevance score is recorded on hits — `similarity_search` is what
    `/crisis/analyze` calls, matching `crisis.py` (`/crisis/analyze` has no
    `confidence` field in `API.md`, unlike `/telemetry/interpret`).
    """

    def __init__(self, hits):
        self.hits = hits
        self.calls: list[dict] = []

    def similarity_search(self, query, **kwargs):
        self.calls.append({"query": query, **kwargs})
        if isinstance(self.hits, dict):
            for sector, sector_hits in self.hits.items():
                if query.startswith(f"{sector} sector event:"):
                    return sector_hits
            return []
        return self.hits


PROCEDURE_TEXT = (FIXTURES / "sample_emergency_procedure.txt").read_text()
PROCEDURE_METADATA = {
    "doc_id": "hull-breach-sector-4",
    "doc_type": "procedure",
    "chunk_index": 0,
    # Real chunk metadata always carries the full source document (see
    # app.services.ingestion.Chunk) — in this fixture, page_content and
    # doc_text happen to be identical because the whole document fits in
    # one chunk. test_steps_are_grounded_in_doc_text_not_page_content
    # below exercises the case where they differ.
    "doc_text": PROCEDURE_TEXT,
}
STUBBED_ROOT_CAUSE = (
    "A hull breach in Sector 4 caused rapid atmospheric loss, triggering the "
    "compartment isolation sequence."
)
# Computed by calling app.services.extraction.extract_procedure_steps directly
# against PROCEDURE_TEXT — see extraction.py for why the "1.5 liters of
# coolant..." line is correctly skipped (no whitespace after "1.").
EXPECTED_STEPS = [
    "Sound the compartment alarm and confirm all crew have evacuated Sector 4.",
    "Seal the primary bulkhead door between Sector 4 and Sector 3.",
    "Vent the compromised compartment to vacuum to stop the outflow.",
    "Confirm hull pressure has stabilized at zero before proceeding.",
    "Retrieve the emergency patch kit from the Sector 3 locker.",
    "Apply the patch to the breach point identified by the hull sensor grid.",
    "Repressurize the compartment slowly and monitor for leaks.",
    "Confirm structural integrity readings return to nominal.",
    "Log the incident in the mission log for post-event review.",
    "Notify mission control once the sector is cleared for re-entry.",
]

EVENTS_PAYLOAD = [
    {
        "timestamp": "T+00:14",
        "sector": "sector-4",
        "description": "Rapid pressure drop detected in Sector 4.",
    },
    {
        "timestamp": "T+00:15",
        "sector": "sector-4",
        "description": "Hull sensor grid flags a breach near frame 12.",
    },
]

# A second, distinct procedure document used by the compound-scenario tests
# below, standing in for a concurrent ECLSS/life-support failure alongside
# the hull breach above.
SECOND_PROCEDURE_TEXT = (
    "1. Don emergency oxygen mask.\n"
    "2. Switch to backup CO2 scrubber canisters.\n"
    "3. Report cabin CO2 ppm to mission control.\n"
)
SECOND_PROCEDURE_METADATA = {
    "doc_id": "eclss-failure-01",
    "doc_type": "procedure",
    "chunk_index": 0,
    "doc_text": SECOND_PROCEDURE_TEXT,
}
SECOND_EXPECTED_STEPS = [
    "Don emergency oxygen mask.",
    "Switch to backup CO2 scrubber canisters.",
    "Report cabin CO2 ppm to mission control.",
]

COMPOUND_EVENTS = [
    CrisisEvent(
        timestamp="T+00:14",
        sector="sector-4",
        description="Hull sensor grid flags a breach near frame 12.",
    ),
    CrisisEvent(
        timestamp="T+00:16",
        sector="eclss",
        description="Cabin CO2 climbing past nominal band.",
    ),
]


@pytest.fixture
def fake_hit() -> _FakeDocument:
    return _FakeDocument(PROCEDURE_TEXT, dict(PROCEDURE_METADATA))


def _events() -> list[CrisisEvent]:
    return [CrisisEvent(**event) for event in EVENTS_PAYLOAD]


def test_analyze_crisis_returns_grounded_root_cause_and_steps(monkeypatch, fake_hit):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_ROOT_CAUSE)
    monkeypatch.setattr(crisis, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(crisis, "get_instruct_model", lambda: fake_model)

    response = crisis.analyze_crisis(_events())

    assert response.root_cause == STUBBED_ROOT_CAUSE
    assert response.steps == EXPECTED_STEPS
    assert response.step_counts == [len(EXPECTED_STEPS)]
    assert response.sources == ["procedure:hull-breach-sector-4#chunk0"]
    assert response.contributing_causes == [
        "sector-4: procedure:hull-breach-sector-4#chunk0"
    ]

    # retrieval was filtered to procedure chunks, and the prompt handed to
    # the instruct model is grounded in the retrieved chunk's text.
    assert fake_store.calls[0]["expr"] == "doc_type == 'procedure'"
    assert PROCEDURE_TEXT in fake_model.invoked_with[0]


def test_steps_reconstruct_across_chunk_boundaries(monkeypatch):
    """Regression test for Task 2's first problem: a long procedure document
    can span more than one embedded chunk, so the single chunk retrieval
    returns can be missing steps that live in a different chunk.

    Simulates a real narrow retrieval hit: `page_content` is just a short
    excerpt (as similarity search would actually return for one chunk of a
    multi-chunk document), containing only steps 1-3, while `doc_text`
    metadata carries the full document. `steps` must reflect the full
    document, not the excerpt.
    """
    narrow_excerpt = (
        "1. Sound the compartment alarm and confirm all crew have evacuated "
        "Sector 4.\n2. Seal the primary bulkhead door between Sector 4 and "
        "Sector 3.\n3. Vent the compromised compartment to vacuum to stop "
        "the outflow."
    )
    assert narrow_excerpt != PROCEDURE_TEXT  # sanity: genuinely a different string
    hit = _FakeDocument(
        narrow_excerpt,
        {**PROCEDURE_METADATA, "doc_text": PROCEDURE_TEXT},
    )
    fake_store = _FakeVectorStore([hit])
    fake_model = _FakeInstructModel(STUBBED_ROOT_CAUSE)
    monkeypatch.setattr(crisis, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(crisis, "get_instruct_model", lambda: fake_model)

    response = crisis.analyze_crisis(_events())

    # all 10 steps, including the ones (4 onward) that live outside the
    # narrow excerpt the retrieval hit's page_content actually contains.
    assert response.steps == EXPECTED_STEPS
    # root_cause grounding still comes from the excerpt, not doc_text.
    assert narrow_excerpt in fake_model.invoked_with[0]
    assert "Retrieve the emergency patch kit" not in fake_model.invoked_with[0]


def test_steps_survive_chunk_text_collapsing_newlines(monkeypatch):
    """Regression test for Task 2's second problem: app.services.ingestion
    .chunk_text collapses every whitespace run, including newlines, before
    packing a document into chunks — so a real retrieved chunk's
    page_content has no line breaks left at all, and
    extract_procedure_steps (which is line-anchored) finds nothing in it.
    Verified against the real chunk_text; see crisis.py's module docstring.

    page_content here mimics what a real embedded chunk actually looks
    like: the whole document, whitespace-collapsed to one line. steps must
    still come back correct because extraction reads doc_text instead.
    """
    collapsed_page_content = " ".join(PROCEDURE_TEXT.split())
    assert "\n" not in collapsed_page_content
    hit = _FakeDocument(
        collapsed_page_content,
        {**PROCEDURE_METADATA, "doc_text": PROCEDURE_TEXT},
    )
    fake_store = _FakeVectorStore([hit])
    fake_model = _FakeInstructModel(STUBBED_ROOT_CAUSE)
    monkeypatch.setattr(crisis, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(crisis, "get_instruct_model", lambda: fake_model)

    response = crisis.analyze_crisis(_events())

    assert response.steps == EXPECTED_STEPS


def test_analyze_crisis_raises_when_nothing_is_retrieved(monkeypatch):
    fake_store = _FakeVectorStore([])
    fake_model = _FakeInstructModel(STUBBED_ROOT_CAUSE)
    monkeypatch.setattr(crisis, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(crisis, "get_instruct_model", lambda: fake_model)

    with pytest.raises(LookupError):
        crisis.analyze_crisis(_events())

    # no grounding chunk was found, so the model must never be asked to
    # generate an ungrounded guess.
    assert fake_model.invoked_with == []


def test_endpoint_returns_404_when_nothing_is_retrieved(monkeypatch):
    fake_store = _FakeVectorStore([])
    fake_model = _FakeInstructModel(STUBBED_ROOT_CAUSE)
    monkeypatch.setattr(crisis, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(crisis, "get_instruct_model", lambda: fake_model)

    response = client.post("/crisis/analyze", json={"events": EVENTS_PAYLOAD})

    assert response.status_code == 404
    assert fake_model.invoked_with == []


def test_endpoint_happy_path_matches_api_contract_shape(monkeypatch, fake_hit):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_ROOT_CAUSE)
    monkeypatch.setattr(crisis, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(crisis, "get_instruct_model", lambda: fake_model)

    response = client.post("/crisis/analyze", json={"events": EVENTS_PAYLOAD})

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "root_cause",
        "steps",
        "step_counts",
        "sources",
        "contributing_causes",
    }
    assert body["root_cause"] == STUBBED_ROOT_CAUSE
    assert body["steps"] == EXPECTED_STEPS
    assert body["step_counts"] == [len(EXPECTED_STEPS)]
    assert body["sources"] == ["procedure:hull-breach-sector-4#chunk0"]
    assert body["contributing_causes"] == [
        "sector-4: procedure:hull-breach-sector-4#chunk0"
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {},  # missing events
        {"events": []},  # empty events list
        {"events": [{"timestamp": "T+00:14", "sector": "sector-4"}]},  # missing description
        {"events": [{"timestamp": "T+00:14", "description": "Pressure drop."}]},  # missing sector
        {"events": [{"sector": "sector-4", "description": "Pressure drop."}]},  # missing timestamp
        {"events": [{"timestamp": "", "sector": "sector-4", "description": "Pressure drop."}]},  # empty timestamp
        {"events": [{"timestamp": "T+00:14", "sector": "sector-4", "description": ""}]},  # empty description
    ],
)
def test_endpoint_rejects_invalid_requests(payload):
    response = client.post("/crisis/analyze", json=payload)
    assert response.status_code == 422


# --- Compound scenario: more than one concurrent failure point -----------


def test_analyze_crisis_synthesizes_across_multiple_matched_sectors(monkeypatch):
    """A feed spanning two distinct sectors (e.g. Module 01's hull breach
    and ECLSS failure injected together) should retrieve and ground on
    both matching procedure documents, not just whichever one a single
    blended query happened to favor.
    """
    hull_hit = _FakeDocument(PROCEDURE_TEXT, dict(PROCEDURE_METADATA))
    eclss_hit = _FakeDocument(SECOND_PROCEDURE_TEXT, dict(SECOND_PROCEDURE_METADATA))
    fake_store = _FakeVectorStore({"sector-4": [hull_hit], "eclss": [eclss_hit]})
    fake_model = _FakeInstructModel(STUBBED_ROOT_CAUSE)
    monkeypatch.setattr(crisis, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(crisis, "get_instruct_model", lambda: fake_model)

    response = crisis.analyze_crisis(COMPOUND_EVENTS)

    assert response.steps == EXPECTED_STEPS + SECOND_EXPECTED_STEPS
    assert response.step_counts == [len(EXPECTED_STEPS), len(SECOND_EXPECTED_STEPS)]
    assert response.sources == [
        "procedure:hull-breach-sector-4#chunk0",
        "procedure:eclss-failure-01#chunk0",
    ]
    assert response.contributing_causes == [
        "sector-4: procedure:hull-breach-sector-4#chunk0",
        "eclss: procedure:eclss-failure-01#chunk0",
    ]
    # both matched excerpts were handed to the model in the same synthesis call
    assert PROCEDURE_TEXT in fake_model.invoked_with[0]
    assert SECOND_PROCEDURE_TEXT in fake_model.invoked_with[0]
    assert len(fake_model.invoked_with) == 1


def test_analyze_crisis_grounds_partially_when_only_some_sectors_match(monkeypatch):
    """One sector in a compound feed matching nothing shouldn't 404 the
    whole request — the response should still be grounded in whichever
    sector(s) did match, per the module docstring's partial-match rule.
    """
    hull_hit = _FakeDocument(PROCEDURE_TEXT, dict(PROCEDURE_METADATA))
    fake_store = _FakeVectorStore({"sector-4": [hull_hit]})  # "eclss" matches nothing
    fake_model = _FakeInstructModel(STUBBED_ROOT_CAUSE)
    monkeypatch.setattr(crisis, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(crisis, "get_instruct_model", lambda: fake_model)

    response = crisis.analyze_crisis(COMPOUND_EVENTS)

    assert response.steps == EXPECTED_STEPS
    assert response.step_counts == [len(EXPECTED_STEPS)]
    assert response.sources == ["procedure:hull-breach-sector-4#chunk0"]


def test_analyze_crisis_caps_sector_grouping_at_max(monkeypatch):
    """More distinct sectors than `crisis._MAX_SECTORS` in one feed should
    only trigger that many retrieval calls, bounding prompt size/cost —
    see the module docstring's "Compound scenarios" section.
    """
    fake_store = _FakeVectorStore([])  # nothing matches; we only inspect calls made
    fake_model = _FakeInstructModel(STUBBED_ROOT_CAUSE)
    monkeypatch.setattr(crisis, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(crisis, "get_instruct_model", lambda: fake_model)

    events = [
        CrisisEvent(
            timestamp=f"T+00:{i:02d}",
            sector=f"sector-{i}",
            description=f"Anomaly detected in sector {i}.",
        )
        for i in range(crisis._MAX_SECTORS + 2)
    ]

    with pytest.raises(LookupError):
        crisis.analyze_crisis(events)

    queried_sectors = {
        call["query"].split(" sector event:")[0] for call in fake_store.calls
    }
    assert len(queried_sectors) == crisis._MAX_SECTORS
