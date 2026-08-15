from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import triage

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
    """Records the query/kwargs each call was made with and returns fixed hits.

    `run_triage` makes two different kinds of retrieval call against this
    store: `similarity_search` (crew file, no relevance score needed for an
    exact-match lookup) and `similarity_search_with_relevance_scores`
    (protocol, semantic match). `crew_hits` and `protocol_hits` are queued
    independently so a test can control each retrieval's outcome on its
    own — a crew-file miss with a protocol hit, or vice versa.
    """

    def __init__(
        self,
        crew_hits: list[_FakeDocument],
        protocol_hits: list[tuple[_FakeDocument, float]],
    ):
        self.crew_hits = crew_hits
        self.protocol_hits = protocol_hits
        self.calls: list[dict] = []

    def similarity_search(self, query, **kwargs):
        self.calls.append({"method": "similarity_search", "query": query, **kwargs})
        return self.crew_hits

    def similarity_search_with_relevance_scores(self, query, **kwargs):
        self.calls.append(
            {
                "method": "similarity_search_with_relevance_scores",
                "query": query,
                **kwargs,
            }
        )
        return self.protocol_hits


class _FakeInstructModel:
    """Records whether/how it was invoked and returns a fixed message."""

    def __init__(self, content: str):
        self.content = content
        self.invoked_with: list[str] = []

    def invoke(self, prompt):
        self.invoked_with.append(prompt)
        return _FakeMessage(self.content)


CREW_FILE_TEXT = (FIXTURES / "sample_crew_file.txt").read_text()
CREW_FILE_METADATA = {
    "doc_id": "kim",
    "doc_type": "crew_file",
    "chunk_index": 0,
    "doc_text": CREW_FILE_TEXT,
}

PROTOCOL_TEXT = (FIXTURES / "sample_triage_protocol.txt").read_text()
PROTOCOL_METADATA = {
    "doc_id": "stage-2-wound-infection",
    "doc_type": "procedure",
    "chunk_index": 0,
    # Real chunk metadata always carries the full source document (see
    # app.services.ingestion.Chunk) — in this fixture, page_content and
    # doc_text happen to be identical because the whole document fits in
    # one chunk.
    "doc_text": PROTOCOL_TEXT,
}

STUBBED_TRIAGE_LEAD = (
    "J. Alvarez is presenting with a Stage 2 wound infection and mild shock; treat "
    "as time-critical per the retrieved protocol."
)

# Computed by calling app.services.extraction.extract_procedure_steps directly
# against PROTOCOL_TEXT (see the fixture for why the "1.2 milliliters of
# antiseptic solution..." line is correctly skipped: it opens with a decimal
# number, not a step marker followed by whitespace).
EXPECTED_INSTRUCTIONS = [
    "Inject 2ml of Antibiotic X from Kit B.",
    "Irrigate and pack the wound; apply a pressure dressing.",
    "Elevate the affected limb and monitor for worsening confusion.",
    "Recheck heart rate and mental status every 15 minutes.",
    "Escalate to the ground-based flight surgeon if confusion persists past 30 minutes.",
    "Document the treatment in the crew member's medical file.",
    "Confirm vitals return to baseline before clearing the crew member for duty.",
    "Log the incident in the mission log for post-event review.",
]

REQUEST_PAYLOAD = {
    "crew_member_id": "kim",
    "symptom_report": (
        "Crew member has a deep laceration on the forearm, severe swelling, and is "
        "showing signs of confusion."
    ),
}


@pytest.fixture
def fake_crew_hit() -> _FakeDocument:
    return _FakeDocument(CREW_FILE_TEXT, dict(CREW_FILE_METADATA))


@pytest.fixture
def fake_protocol_hit() -> _FakeDocument:
    return _FakeDocument(PROTOCOL_TEXT, dict(PROTOCOL_METADATA))


def test_run_triage_returns_grounded_lead_and_instructions(
    monkeypatch, fake_crew_hit, fake_protocol_hit
):
    fake_store = _FakeVectorStore(
        crew_hits=[fake_crew_hit], protocol_hits=[(fake_protocol_hit, 0.87)]
    )
    fake_model = _FakeInstructModel(STUBBED_TRIAGE_LEAD)
    monkeypatch.setattr(triage, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(triage, "get_instruct_model", lambda: fake_model)

    response = triage.run_triage(
        REQUEST_PAYLOAD["crew_member_id"], REQUEST_PAYLOAD["symptom_report"]
    )

    assert response.triage_lead == STUBBED_TRIAGE_LEAD
    assert response.instructions == EXPECTED_INSTRUCTIONS
    assert response.allergy_check is None
    assert response.confidence == 0.87

    # crew file was looked up by exact doc_id match, not semantic search.
    crew_call = fake_store.calls[0]
    assert crew_call["method"] == "similarity_search"
    assert crew_call["expr"] == "doc_type == 'crew_file' && doc_id == 'kim'"

    # protocol was matched semantically against the symptom report.
    protocol_call = fake_store.calls[1]
    assert protocol_call["method"] == "similarity_search_with_relevance_scores"
    assert protocol_call["expr"] == "doc_type == 'procedure'"

    # the prompt handed to the instruct model is grounded in both the
    # protocol chunk's text and the crew file's text.
    assert PROTOCOL_TEXT in fake_model.invoked_with[0]
    assert CREW_FILE_TEXT in fake_model.invoked_with[0]


def test_instructions_are_grounded_in_doc_text_not_page_content(
    monkeypatch, fake_crew_hit
):
    """Regression coverage mirroring day-20's crisis fix: a narrow retrieval
    excerpt (page_content) must not be what instructions are extracted
    from — doc_text (the full source document) must be, applied here from
    the start rather than as a follow-up fix.
    """
    narrow_excerpt = (
        "1. Inject 2ml of Antibiotic X from Kit B.\n2. Irrigate and pack the wound; "
        "apply a pressure dressing."
    )
    assert narrow_excerpt != PROTOCOL_TEXT  # sanity: genuinely a different string
    protocol_hit = _FakeDocument(
        narrow_excerpt, {**PROTOCOL_METADATA, "doc_text": PROTOCOL_TEXT}
    )
    fake_store = _FakeVectorStore(
        crew_hits=[fake_crew_hit], protocol_hits=[(protocol_hit, 0.5)]
    )
    fake_model = _FakeInstructModel(STUBBED_TRIAGE_LEAD)
    monkeypatch.setattr(triage, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(triage, "get_instruct_model", lambda: fake_model)

    response = triage.run_triage(
        REQUEST_PAYLOAD["crew_member_id"], REQUEST_PAYLOAD["symptom_report"]
    )

    # all 8 instructions, including the ones that live outside the narrow
    # excerpt the retrieval hit's page_content actually contains.
    assert response.instructions == EXPECTED_INSTRUCTIONS
    # triage_lead grounding still comes from the excerpt, not doc_text.
    assert narrow_excerpt in fake_model.invoked_with[0]
    assert "Escalate to the ground-based flight surgeon" not in fake_model.invoked_with[0]


def test_run_triage_raises_when_no_crew_file_is_found(monkeypatch, fake_protocol_hit):
    fake_store = _FakeVectorStore(crew_hits=[], protocol_hits=[(fake_protocol_hit, 0.87)])
    fake_model = _FakeInstructModel(STUBBED_TRIAGE_LEAD)
    monkeypatch.setattr(triage, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(triage, "get_instruct_model", lambda: fake_model)

    with pytest.raises(LookupError):
        triage.run_triage(
            REQUEST_PAYLOAD["crew_member_id"], REQUEST_PAYLOAD["symptom_report"]
        )

    # no crew file was found, so the protocol search and the model must
    # never run — fail fast on the cheap exact-match lookup first.
    assert len(fake_store.calls) == 1
    assert fake_model.invoked_with == []


def test_run_triage_raises_when_no_protocol_is_found(monkeypatch, fake_crew_hit):
    fake_store = _FakeVectorStore(crew_hits=[fake_crew_hit], protocol_hits=[])
    fake_model = _FakeInstructModel(STUBBED_TRIAGE_LEAD)
    monkeypatch.setattr(triage, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(triage, "get_instruct_model", lambda: fake_model)

    with pytest.raises(LookupError):
        triage.run_triage(
            REQUEST_PAYLOAD["crew_member_id"], REQUEST_PAYLOAD["symptom_report"]
        )

    # no grounding protocol was found, so the model must never be asked to
    # generate an ungrounded guess.
    assert fake_model.invoked_with == []


def test_endpoint_returns_404_when_no_crew_file_is_found(monkeypatch, fake_protocol_hit):
    fake_store = _FakeVectorStore(crew_hits=[], protocol_hits=[(fake_protocol_hit, 0.87)])
    fake_model = _FakeInstructModel(STUBBED_TRIAGE_LEAD)
    monkeypatch.setattr(triage, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(triage, "get_instruct_model", lambda: fake_model)

    response = client.post("/triage", json=REQUEST_PAYLOAD)

    assert response.status_code == 404
    assert fake_model.invoked_with == []


def test_endpoint_returns_404_when_no_protocol_is_found(monkeypatch, fake_crew_hit):
    fake_store = _FakeVectorStore(crew_hits=[fake_crew_hit], protocol_hits=[])
    fake_model = _FakeInstructModel(STUBBED_TRIAGE_LEAD)
    monkeypatch.setattr(triage, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(triage, "get_instruct_model", lambda: fake_model)

    response = client.post("/triage", json=REQUEST_PAYLOAD)

    assert response.status_code == 404
    assert fake_model.invoked_with == []


def test_endpoint_happy_path_matches_api_contract_shape(
    monkeypatch, fake_crew_hit, fake_protocol_hit
):
    fake_store = _FakeVectorStore(
        crew_hits=[fake_crew_hit], protocol_hits=[(fake_protocol_hit, 0.87)]
    )
    fake_model = _FakeInstructModel(STUBBED_TRIAGE_LEAD)
    monkeypatch.setattr(triage, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(triage, "get_instruct_model", lambda: fake_model)

    response = client.post("/triage", json=REQUEST_PAYLOAD)

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "triage_lead",
        "instructions",
        "allergy_check",
        "confidence",
    }
    assert body["triage_lead"] == STUBBED_TRIAGE_LEAD
    assert body["instructions"] == EXPECTED_INSTRUCTIONS
    assert body["allergy_check"] is None
    assert body["confidence"] == 0.87


@pytest.mark.parametrize(
    "payload",
    [
        {},  # missing both fields
        {"symptom_report": "Dizziness and chest tightness."},  # missing crew_member_id
        {"crew_member_id": "kim"},  # missing symptom_report
        {"crew_member_id": "", "symptom_report": "Dizziness."},  # empty crew_member_id
        {"crew_member_id": "kim", "symptom_report": ""},  # empty symptom_report
        # expr-injection guard: a crew_member_id with a quote must be
        # rejected by the pattern constraint, not reach the vector store.
        {"crew_member_id": "kim' || doc_type == 'crew_file", "symptom_report": "Dizziness."},
        {"crew_member_id": "Kim", "symptom_report": "Dizziness."},  # uppercase not allowed
    ],
)
def test_endpoint_rejects_invalid_requests(payload):
    response = client.post("/triage", json=payload)
    assert response.status_code == 422
