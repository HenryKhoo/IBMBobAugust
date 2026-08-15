from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import triage
from tests.conftest import _FakeDocument, _FakeInstructModel, _FakeMessage

FIXTURES = Path(__file__).parent / "fixtures"

client = TestClient(app)


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

# A treatment protocol whose text names two of sample_crew_file.txt's
# recorded allergens (penicillin, shellfish), used to exercise the
# allergy-check's conflict-detected path — sample_triage_protocol.txt's
# "Antibiotic X" deliberately names no real drug, so it only ever exercises
# the no-conflict path.
CONFLICT_PROTOCOL_TEXT = (FIXTURES / "sample_triage_protocol_conflict.txt").read_text()
CONFLICT_PROTOCOL_METADATA = {
    "doc_id": "severe-allergic-reaction",
    "doc_type": "procedure",
    "chunk_index": 0,
    "doc_text": CONFLICT_PROTOCOL_TEXT,
}

# A crew file whose allergy line is a none-token ("None known"), used to
# exercise the allergy-check's "no known allergies" path.
NO_ALLERGY_CREW_FILE_TEXT = (FIXTURES / "sample_crew_file_no_allergies.txt").read_text()
NO_ALLERGY_CREW_FILE_METADATA = {
    "doc_id": "suarez",
    "doc_type": "crew_file",
    "chunk_index": 0,
    "doc_text": NO_ALLERGY_CREW_FILE_TEXT,
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

# Computed by calling app.services.extraction.extract_allergies directly
# against CREW_FILE_TEXT ("Allergies: penicillin, shellfish and latex").
EXPECTED_ALLERGIES = ["penicillin", "shellfish", "latex"]

# Computed by calling app.services.triage._check_allergies directly against
# EXPECTED_ALLERGIES and PROTOCOL_TEXT — no allergen appears in the "Antibiotic
# X" protocol text, so this is the no-conflict message.
EXPECTED_NO_CONFLICT_ALLERGY_CHECK = (
    "No conflict detected between recorded allergies "
    "(penicillin, shellfish, latex) and this treatment protocol."
)

# Computed the same way against CONFLICT_PROTOCOL_TEXT, which names both
# "penicillin" and "shellfish-derived" (a word-boundary match on "shellfish").
EXPECTED_CONFLICT_ALLERGY_CHECK = (
    "CONFLICT: crew member has a recorded allergy to penicillin, shellfish, "
    "which appears in the recommended treatment. Confirm before administering."
)

EXPECTED_NO_KNOWN_ALLERGY_CHECK = "No known allergies on file for this crew member."

# app.services.triage._source_line's format: "{doc_type}:{doc_id}#chunk{chunk_index}",
# joined for both retrieved documents with "; " (see _combined_source).
EXPECTED_SOURCE = "crew_file:kim#chunk0; procedure:stage-2-wound-infection#chunk0"

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
    assert response.allergy_check == EXPECTED_NO_CONFLICT_ALLERGY_CHECK
    assert response.confidence == 0.87
    assert response.source == EXPECTED_SOURCE

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


def test_allergy_check_is_grounded_in_doc_text_not_page_content(
    monkeypatch, fake_crew_hit
):
    """Same regression shape as the instructions test above, for allergy_check:
    a narrow retrieval excerpt must not be what the cross check runs
    against — doc_text (the full source document) must be.
    """
    narrow_excerpt = "1. Administer epinephrine auto-injector into the outer thigh."
    assert "penicillin" not in narrow_excerpt
    protocol_hit = _FakeDocument(
        narrow_excerpt, {**CONFLICT_PROTOCOL_METADATA, "doc_text": CONFLICT_PROTOCOL_TEXT}
    )
    fake_store = _FakeVectorStore(
        crew_hits=[fake_crew_hit], protocol_hits=[(protocol_hit, 0.6)]
    )
    fake_model = _FakeInstructModel(STUBBED_TRIAGE_LEAD)
    monkeypatch.setattr(triage, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(triage, "get_instruct_model", lambda: fake_model)

    response = triage.run_triage(
        REQUEST_PAYLOAD["crew_member_id"], REQUEST_PAYLOAD["symptom_report"]
    )

    # the conflict lives in doc_text (the full protocol), not the narrow
    # page_content excerpt actually returned by retrieval.
    assert response.allergy_check == EXPECTED_CONFLICT_ALLERGY_CHECK


def test_allergy_check_flags_conflict_when_protocol_names_a_recorded_allergen(
    monkeypatch, fake_crew_hit
):
    protocol_hit = _FakeDocument(
        CONFLICT_PROTOCOL_TEXT, dict(CONFLICT_PROTOCOL_METADATA)
    )
    fake_store = _FakeVectorStore(
        crew_hits=[fake_crew_hit], protocol_hits=[(protocol_hit, 0.72)]
    )
    fake_model = _FakeInstructModel(STUBBED_TRIAGE_LEAD)
    monkeypatch.setattr(triage, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(triage, "get_instruct_model", lambda: fake_model)

    response = triage.run_triage(
        REQUEST_PAYLOAD["crew_member_id"], REQUEST_PAYLOAD["symptom_report"]
    )

    assert response.allergy_check == EXPECTED_CONFLICT_ALLERGY_CHECK
    assert response.allergy_check.startswith("CONFLICT:")
    assert response.source == "crew_file:kim#chunk0; procedure:severe-allergic-reaction#chunk0"


def test_allergy_check_reports_no_known_allergies_when_crew_file_has_none(
    monkeypatch, fake_protocol_hit
):
    crew_hit = _FakeDocument(NO_ALLERGY_CREW_FILE_TEXT, dict(NO_ALLERGY_CREW_FILE_METADATA))
    fake_store = _FakeVectorStore(
        crew_hits=[crew_hit], protocol_hits=[(fake_protocol_hit, 0.87)]
    )
    fake_model = _FakeInstructModel(STUBBED_TRIAGE_LEAD)
    monkeypatch.setattr(triage, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(triage, "get_instruct_model", lambda: fake_model)

    response = triage.run_triage("suarez", "Mild headache after EVA prep.")

    assert response.allergy_check == EXPECTED_NO_KNOWN_ALLERGY_CHECK
    assert response.source == "crew_file:suarez#chunk0; procedure:stage-2-wound-infection#chunk0"


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


class _FakeVectorStoreNoIndexYetForProtocol:
    """Mimics langchain-milvus before any `/ingest` call has ever created the
    'procedure' collection's index: `similarity_search_with_relevance_scores`
    raises `ValueError` instead of returning `[]`, the same way
    `app.services.vector_store.relevance_score_hits_or_empty` was written to
    handle (see its docstring for how this was reproduced against a real
    production-like backend). The crew file lookup still uses plain
    `similarity_search`, unaffected by this bug, so it returns normally.
    """

    def __init__(self, crew_hits: list):
        self.crew_hits = crew_hits

    def similarity_search(self, query, **kwargs):
        return self.crew_hits

    def similarity_search_with_relevance_scores(self, query, **kwargs):
        raise ValueError("No index params provided. Could not determine relevance function.")


def test_endpoint_returns_404_not_500_when_protocol_index_not_created_yet(
    monkeypatch, fake_crew_hit
):
    # Regression test: before anything had ever been ingested, a crew file
    # hit followed by a protocol lookup crashed with an unhandled
    # ValueError, which the browser reported as a CORS failure rather than
    # the intended 404 (see app.main's unhandled_exception_handler and
    # app.services.vector_store.relevance_score_hits_or_empty).
    fake_store = _FakeVectorStoreNoIndexYetForProtocol(crew_hits=[fake_crew_hit])
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
        "source",
    }
    assert body["triage_lead"] == STUBBED_TRIAGE_LEAD
    assert body["instructions"] == EXPECTED_INSTRUCTIONS
    assert body["allergy_check"] == EXPECTED_NO_CONFLICT_ALLERGY_CHECK
    assert body["confidence"] == 0.87
    assert body["source"] == EXPECTED_SOURCE


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
