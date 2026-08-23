from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.main import app
from app.services import talkback
from tests.conftest import _FakeDocument, _FakeInstructModel, _FakeMessage

FIXTURES = Path(__file__).parent / "fixtures"

client = TestClient(app)


class _FakeVectorStore:
    """Records the query/kwargs it was called with and returns fixed hits.

    `history_hits` is a separate fixed result set returned only when the
    call's `expr` targets `doc_type == 'conversation_turn'` — mirroring how
    a real Milvus `expr` filter actually scopes a query, so a test can
    configure the main-answer retrieval and the long-term history recall
    independently instead of one fake result leaking into both. Defaults
    to `[]`, so every existing test that never configures it keeps getting
    exactly the same "no history recalled" behavior as before this
    existed.
    """

    def __init__(
        self,
        hits: list[tuple[_FakeDocument, float]],
        history_hits: list[tuple[_FakeDocument, float]] | None = None,
    ):
        self.hits = hits
        self.history_hits = history_hits or []
        self.calls: list[dict] = []
        self.add_texts_calls: list[dict] = []

    def similarity_search_with_relevance_scores(self, query, **kwargs):
        self.calls.append({"query": query, **kwargs})
        if "conversation_turn" in kwargs.get("expr", ""):
            return self.history_hits
        return self.hits

    def add_texts(self, texts, metadatas):
        self.add_texts_calls.append({"texts": list(texts), "metadatas": list(metadatas)})
        return [f"id-{i}" for i in range(len(texts))]


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
    assert set(body.keys()) == {
        "answer",
        "persona",
        "grounded",
        "confidence",
        "source",
        "session_id",
        "history_source",
    }
    assert body["answer"] == STUBBED_ANSWER
    assert body["grounded"] is True
    assert body["session_id"]
    assert body["history_source"] == "none"


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


def test_ask_without_session_id_starts_a_fresh_session_each_time(monkeypatch, fake_hit):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(talkback, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(talkback, "get_instruct_model", lambda: fake_model)

    first = talkback.ask_talkback("What is Veggie?", talkback.AskPersona.BASELINE, humor=50)
    second = talkback.ask_talkback("What is Veggie?", talkback.AskPersona.BASELINE, humor=50)

    assert first.session_id != second.session_id
    # no history block on either call — each is the first question of its
    # own session, so the prompt is byte-for-byte the no-history shape.
    assert "Conversation so far" not in fake_model.invoked_with[0]
    assert "Conversation so far" not in fake_model.invoked_with[1]


def test_ask_with_session_id_replays_prior_turns_into_the_next_prompt(monkeypatch, fake_hit):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(talkback, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(talkback, "get_instruct_model", lambda: fake_model)

    first = talkback.ask_talkback("What is Veggie?", talkback.AskPersona.BASELINE, humor=50)
    second = talkback.ask_talkback(
        "What does it grow?",
        talkback.AskPersona.BASELINE,
        humor=50,
        session_id=first.session_id,
    )

    assert second.session_id == first.session_id
    second_prompt = fake_model.invoked_with[-1]
    assert "Conversation so far" in second_prompt
    assert "What is Veggie?" in second_prompt
    assert STUBBED_ANSWER in second_prompt


def test_ask_records_fallback_turns_in_session_history_too(monkeypatch):
    fake_store = _FakeVectorStore([])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(talkback, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(talkback, "get_instruct_model", lambda: fake_model)

    first = talkback.ask_talkback("anything", talkback.AskPersona.BASELINE, humor=50)
    from app.services import memory

    session = memory.get_or_create_session(first.session_id)
    roles = [turn.role for turn in session.recent_turns()]
    assert roles == [memory.ConversationRole.USER, memory.ConversationRole.ASSISTANT]
    assert session.recent_turns()[-1].content == "No grounded answer for that."


# --- Phase 3: long-term persistence -----------------------------------------


def test_ask_persists_a_grounded_exchange_to_zilliz_as_conversation_turn(monkeypatch, fake_hit):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(talkback, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(talkback, "get_instruct_model", lambda: fake_model)

    response = talkback.ask_talkback("What is Veggie?", talkback.AskPersona.BASELINE, humor=50)

    assert len(fake_store.add_texts_calls) == 1
    call = fake_store.add_texts_calls[0]
    assert call["texts"] == ["Question: What is Veggie?\nAnswer: " + STUBBED_ANSWER]
    metadata = call["metadatas"][0]
    assert metadata["doc_type"] == "conversation_turn"
    assert metadata["doc_id"] == response.session_id
    assert metadata["question"] == "What is Veggie?"
    assert metadata["answer"] == STUBBED_ANSWER
    assert metadata["persona"] == "baseline"
    assert metadata["source"] == response.source


def test_ask_does_not_persist_a_fallback_turn(monkeypatch):
    fake_store = _FakeVectorStore([])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(talkback, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(talkback, "get_instruct_model", lambda: fake_model)

    talkback.ask_talkback("anything", talkback.AskPersona.BASELINE, humor=50)

    assert fake_store.add_texts_calls == []


def test_ask_survives_a_zilliz_write_failure_during_persistence(monkeypatch, fake_hit):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)

    def _raise(*args, **kwargs):
        raise RuntimeError("Zilliz is unreachable")

    fake_store.add_texts = _raise
    monkeypatch.setattr(talkback, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(talkback, "get_instruct_model", lambda: fake_model)

    response = talkback.ask_talkback("What is Veggie?", talkback.AskPersona.BASELINE, humor=50)

    # the /ask response is unaffected by the persistence failure — it's
    # logged and swallowed, not raised.
    assert response.grounded is True
    assert response.answer == STUBBED_ANSWER


# --- Phase 4: retrieval-augmented recall + history_source --------------------


def test_ask_reports_history_source_none_on_a_fresh_first_question(monkeypatch, fake_hit):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(talkback, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(talkback, "get_instruct_model", lambda: fake_model)

    response = talkback.ask_talkback("What is Veggie?", talkback.AskPersona.BASELINE, humor=50)

    assert response.history_source == talkback.HistorySource.NONE
    # a fresh session has nothing recoverable — no history-recall round
    # trip should even be attempted.
    assert not any("conversation_turn" in call.get("expr", "") for call in fake_store.calls)


def test_ask_reports_history_source_session_memory_for_an_in_window_followup(
    monkeypatch, fake_hit
):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(talkback, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(talkback, "get_instruct_model", lambda: fake_model)

    first = talkback.ask_talkback("What is Veggie?", talkback.AskPersona.BASELINE, humor=50)
    second = talkback.ask_talkback(
        "What does it grow?", talkback.AskPersona.BASELINE, humor=50, session_id=first.session_id
    )

    assert second.history_source == talkback.HistorySource.SESSION_MEMORY


def test_ask_recovers_history_from_zilliz_when_the_session_window_is_empty(monkeypatch, fake_hit):
    """Simulates a resumed session after a restart/eviction: the caller sends back
    a session_id the in-process store has never seen, but Zilliz still has that
    session's earlier grounded exchange.
    """
    history_hit = (
        _FakeDocument(
            "Question: What is Veggie?\nAnswer: A plant growth chamber on the ISS.",
            {
                "doc_type": "conversation_turn",
                "doc_id": "resumed-session",
                "chunk_index": 1,
                "question": "What is Veggie?",
                "answer": "A plant growth chamber on the ISS.",
                "persona": "baseline",
                "source": "science_reference:nasa-smd-veggie-001#chunk0",
            },
        ),
        0.7,
    )
    fake_store = _FakeVectorStore([fake_hit], history_hits=[history_hit])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(talkback, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(talkback, "get_instruct_model", lambda: fake_model)

    response = talkback.ask_talkback(
        "What does it grow?",
        talkback.AskPersona.BASELINE,
        humor=50,
        session_id="resumed-session",
    )

    assert response.history_source == talkback.HistorySource.HISTORY_RETRIEVAL
    prompt = fake_model.invoked_with[0]
    assert "Conversation so far" in prompt
    assert "What is Veggie?" in prompt
    assert "A plant growth chamber on the ISS." in prompt
    # recall was scoped to this exact session_id.
    history_call = next(c for c in fake_store.calls if "conversation_turn" in c.get("expr", ""))
    assert "doc_id == 'resumed-session'" in history_call["expr"]


def test_ask_history_recall_is_scoped_to_the_caller_s_own_session_id_even_with_quotes(
    monkeypatch, fake_hit
):
    """A session_id containing a single quote must not be able to break out of the
    Milvus expr filter and widen a session-scoped recall into a cross-session one.
    """
    fake_store = _FakeVectorStore([fake_hit], history_hits=[])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(talkback, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(talkback, "get_instruct_model", lambda: fake_model)

    malicious_id = "abc' or doc_type == 'science_reference"
    talkback.ask_talkback("anything", talkback.AskPersona.BASELINE, humor=50, session_id=malicious_id)

    history_call = next(c for c in fake_store.calls if "conversation_turn" in c.get("expr", ""))
    assert "doc_id == 'abc\\' or doc_type == \\'science_reference'" in history_call["expr"]


# --- GET /conversation/history ------------------------------------------------


def test_conversation_history_endpoint_returns_the_live_session(monkeypatch, fake_hit):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(talkback, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(talkback, "get_instruct_model", lambda: fake_model)

    ask_response = client.post("/ask", json={"question": "What is Veggie?"}).json()

    def _fail_if_called():
        raise AssertionError("must not reach Zilliz when the live session already has turns")

    monkeypatch.setattr(main, "get_vector_store", _fail_if_called)

    response = client.get(
        "/conversation/history", params={"session_id": ask_response["session_id"]}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == ask_response["session_id"]
    assert body["source"] == "session_memory"
    assert [t["role"] for t in body["turns"]] == ["user", "assistant"]
    assert body["turns"][0]["content"] == "What is Veggie?"
    assert body["turns"][1]["content"] == STUBBED_ANSWER


def test_conversation_history_endpoint_recovers_from_long_term_storage(monkeypatch):
    chunk = _FakeDocument(
        "Question: What is Veggie?\nAnswer: A plant growth chamber.",
        {
            "doc_type": "conversation_turn",
            "doc_id": "resumed-session-endpoint-test",
            "chunk_index": 1,
            "question": "What is Veggie?",
            "answer": "A plant growth chamber.",
            "persona": "baseline",
            "source": "science_reference:nasa-smd-veggie-001#chunk0",
        },
    )
    fake_store = _FakeVectorStore([], history_hits=[(chunk, 0.9)])
    monkeypatch.setattr(main, "get_vector_store", lambda: fake_store)

    response = client.get(
        "/conversation/history", params={"session_id": "resumed-session-endpoint-test"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "history_retrieval"
    assert [t["content"] for t in body["turns"]] == [
        "What is Veggie?", "A plant growth chamber.",
    ]


def test_conversation_history_endpoint_never_404s_on_an_unknown_session(monkeypatch):
    fake_store = _FakeVectorStore([], history_hits=[])
    monkeypatch.setattr(main, "get_vector_store", lambda: fake_store)

    response = client.get("/conversation/history", params={"session_id": "never-seen"})

    assert response.status_code == 200
    body = response.json()
    assert body == {"session_id": "never-seen", "turns": [], "source": "none"}


def test_conversation_history_endpoint_requires_session_id():
    response = client.get("/conversation/history")
    assert response.status_code == 422
