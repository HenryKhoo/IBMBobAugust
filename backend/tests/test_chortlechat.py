from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.main import app
from app.schemas import Domain
from app.services import chortlechat
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


class _DomainAwareFakeVectorStore(_FakeVectorStore):
    """Like `_FakeVectorStore`, but distinguishes a domain-scoped call from
    the domain-less retry `ask_chortlechat` makes when a domain search comes
    back empty — needed only by the domain-fallback tests below; every
    other test's `_FakeVectorStore` has no reason to care which expr it
    got, so this stays local rather than replacing the shared fake.
    """

    def __init__(self, hits, domain_hits, history_hits=None):
        super().__init__(hits, history_hits)
        self.domain_hits = domain_hits

    def similarity_search_with_relevance_scores(self, query, **kwargs):
        self.calls.append({"query": query, **kwargs})
        expr = kwargs.get("expr", "")
        if "conversation_turn" in expr:
            return self.history_hits
        if "domain ==" in expr:
            return self.domain_hits
        return self.hits


def test_ask_baseline_returns_grounded_answer_and_source(monkeypatch, fake_hit):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(chortlechat, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(chortlechat, "get_instruct_model", lambda: fake_model)

    response = chortlechat.ask_chortlechat("What is Veggie?", chortlechat.AskPersona.BASELINE, humor=50)

    assert response.answer == STUBBED_ANSWER
    assert response.persona == chortlechat.AskPersona.BASELINE
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
    monkeypatch.setattr(chortlechat, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(chortlechat, "get_instruct_model", lambda: fake_model)

    chortlechat.ask_chortlechat("What is Veggie?", chortlechat.AskPersona.BANTER, humor=80)

    # two generation calls: the baseline fact, then the banter restyle.
    assert len(fake_model.invoked_with) == 2
    baseline_prompt, banter_prompt = fake_model.invoked_with
    assert REFERENCE_TEXT in baseline_prompt
    assert STUBBED_ANSWER in banter_prompt
    assert "80/100" in banter_prompt


def test_ask_falls_back_honestly_when_nothing_is_retrieved(monkeypatch):
    fake_store = _FakeVectorStore([])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(chortlechat, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(chortlechat, "get_instruct_model", lambda: fake_model)

    response = chortlechat.ask_chortlechat("anything", chortlechat.AskPersona.BASELINE, humor=50)

    assert response.grounded is False
    assert response.confidence is None
    assert response.source is None
    assert response.answer == "No grounded answer for that."
    # never asked the model to guess.
    assert fake_model.invoked_with == []


def test_ask_falls_back_honestly_when_the_embedding_provider_rejects_the_call(monkeypatch):
    """End-to-end regression test for the live `token_quota_reached` 500:
    watsonx's embedding call raising mid-retrieval must reach the caller as
    the same honest "no grounded answer" response an ordinary unmatched
    question gets, not an unhandled 500. Deliberately does not mock
    `relevance_score_hits_or_empty` — the real one (imported by
    `chortlechat`) has to be the thing that catches this, exercising the
    fix at the same layer `ask_chortlechat` actually calls through.
    """

    class _RejectingVectorStore:
        def similarity_search_with_relevance_scores(self, query, **kwargs):
            raise RuntimeError(
                'Failure during generate. Status code: 403, body: {"errors":'
                '[{"code":"token_quota_reached","message":"Request of 1 token(s) '
                'from quota was rejected"}]}'
            )

    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(chortlechat, "get_vector_store", lambda: _RejectingVectorStore())
    monkeypatch.setattr(chortlechat, "get_instruct_model", lambda: fake_model)

    response = chortlechat.ask_chortlechat("What is Veggie?", chortlechat.AskPersona.BASELINE, humor=50)

    assert response.grounded is False
    assert response.answer == "No grounded answer for that."
    # never asked the model to guess, and never let the exception escape.
    assert fake_model.invoked_with == []


def test_ask_falls_back_below_confidence_threshold_with_persona_specific_wording(
    monkeypatch,
):
    weak_hit = (_FakeDocument(REFERENCE_TEXT, dict(REFERENCE_METADATA)), 0.1)
    fake_store = _FakeVectorStore([weak_hit])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(chortlechat, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(chortlechat, "get_instruct_model", lambda: fake_model)

    baseline_response = chortlechat.ask_chortlechat(
        "anything", chortlechat.AskPersona.BASELINE, humor=50
    )
    banter_response = chortlechat.ask_chortlechat("anything", chortlechat.AskPersona.BANTER, humor=50)

    assert baseline_response.grounded is False
    assert baseline_response.confidence == 0.1
    assert banter_response.grounded is False
    assert banter_response.answer != baseline_response.answer
    assert fake_model.invoked_with == []


# --- Domain scoping -----------------------------------------------------


def test_ask_scopes_retrieval_to_the_requested_domain(monkeypatch, fake_hit):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(chortlechat, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(chortlechat, "get_instruct_model", lambda: fake_model)

    chortlechat.ask_chortlechat(
        "What is Veggie?",
        chortlechat.AskPersona.BASELINE,
        humor=50,
        domain=Domain.TROPICAL_CYCLONE_DYNAMICS,
    )

    assert fake_store.calls[0]["expr"] == (
        "doc_type == 'science_reference' and domain == 'tropical_cyclone_dynamics'"
    )
    # exactly one retrieval call — a real hit came back, so there's nothing
    # for the empty-domain fallback to do.
    assert len(fake_store.calls) == 1


def test_ask_falls_back_to_the_whole_corpus_when_a_domain_has_nothing_indexed(monkeypatch):
    # The requested domain's own search comes back with literally nothing,
    # but the whole corpus (no domain clause) does have a real match —
    # simulating an empty/misconfigured domain rather than a genuinely
    # unanswerable question.
    strong_hit = (_FakeDocument(REFERENCE_TEXT, dict(REFERENCE_METADATA)), RELEVANCE_SCORE)
    fake_store = _DomainAwareFakeVectorStore(hits=[strong_hit], domain_hits=[])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(chortlechat, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(chortlechat, "get_instruct_model", lambda: fake_model)

    response = chortlechat.ask_chortlechat(
        "What is Veggie?",
        chortlechat.AskPersona.BASELINE,
        humor=50,
        domain=Domain.SAHARAN_DUST,
    )

    assert response.grounded is True
    assert response.answer == STUBBED_ANSWER
    # two retrieval calls: the domain-scoped one that came back empty, then
    # the domain-less retry that actually found something.
    assert len(fake_store.calls) == 2
    assert "domain ==" in fake_store.calls[0]["expr"]
    assert "domain ==" not in fake_store.calls[1]["expr"]


def test_ask_does_not_fall_back_when_a_domain_search_finds_only_a_weak_match(monkeypatch):
    # A domain-scoped search that finds *something*, just below the
    # confidence threshold, must be treated as a real "no grounded answer
    # in this domain" — not retried against the whole corpus, even though a
    # stronger match exists elsewhere. The empty-domain fallback exists for
    # "nothing indexed here at all," not for "weak match in this domain."
    weak_hit = (_FakeDocument(REFERENCE_TEXT, dict(REFERENCE_METADATA)), 0.1)
    strong_hit_elsewhere = (_FakeDocument(REFERENCE_TEXT, dict(REFERENCE_METADATA)), 0.95)
    fake_store = _DomainAwareFakeVectorStore(hits=[strong_hit_elsewhere], domain_hits=[weak_hit])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(chortlechat, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(chortlechat, "get_instruct_model", lambda: fake_model)

    response = chortlechat.ask_chortlechat(
        "anything",
        chortlechat.AskPersona.BASELINE,
        humor=50,
        domain=Domain.CLIMATE_RECONSTRUCTION,
    )

    assert response.grounded is False
    assert response.confidence == 0.1
    assert len(fake_store.calls) == 1
    assert fake_model.invoked_with == []


def test_ask_without_a_domain_makes_exactly_one_retrieval_call(monkeypatch, fake_hit):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(chortlechat, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(chortlechat, "get_instruct_model", lambda: fake_model)

    chortlechat.ask_chortlechat("What is Veggie?", chortlechat.AskPersona.BASELINE, humor=50)

    assert fake_store.calls[0]["expr"] == "doc_type == 'science_reference'"
    assert len(fake_store.calls) == 1


def test_endpoint_accepts_a_domain_and_rejects_an_unknown_one(monkeypatch, fake_hit):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(chortlechat, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(chortlechat, "get_instruct_model", lambda: fake_model)

    ok = client.post(
        "/ask", json={"question": "What is Veggie?", "domain": "environmental_hazards"}
    )
    assert ok.status_code == 200
    assert fake_store.calls[0]["expr"] == (
        "doc_type == 'science_reference' and domain == 'environmental_hazards'"
    )

    bad = client.post("/ask", json={"question": "valid", "domain": "not_a_real_domain"})
    assert bad.status_code == 422


def test_endpoint_happy_path_matches_api_contract_shape(monkeypatch, fake_hit):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(chortlechat, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(chortlechat, "get_instruct_model", lambda: fake_model)

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
    monkeypatch.setattr(chortlechat, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(chortlechat, "get_instruct_model", lambda: fake_model)

    response = client.post("/ask", json={"question": "anything"})

    assert response.status_code == 200
    assert response.json()["grounded"] is False


def test_endpoint_defaults_persona_to_baseline_and_humor_to_fifty(monkeypatch, fake_hit):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(chortlechat, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(chortlechat, "get_instruct_model", lambda: fake_model)

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
    monkeypatch.setattr(chortlechat, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(chortlechat, "get_instruct_model", lambda: fake_model)

    first = chortlechat.ask_chortlechat("What is Veggie?", chortlechat.AskPersona.BASELINE, humor=50)
    second = chortlechat.ask_chortlechat("What is Veggie?", chortlechat.AskPersona.BASELINE, humor=50)

    assert first.session_id != second.session_id
    # no history block on either call — each is the first question of its
    # own session, so the prompt is byte-for-byte the no-history shape.
    assert "Conversation so far" not in fake_model.invoked_with[0]
    assert "Conversation so far" not in fake_model.invoked_with[1]


def test_ask_with_session_id_replays_prior_turns_into_the_next_prompt(monkeypatch, fake_hit):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(chortlechat, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(chortlechat, "get_instruct_model", lambda: fake_model)

    first = chortlechat.ask_chortlechat("What is Veggie?", chortlechat.AskPersona.BASELINE, humor=50)
    second = chortlechat.ask_chortlechat(
        "What does it grow?",
        chortlechat.AskPersona.BASELINE,
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
    monkeypatch.setattr(chortlechat, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(chortlechat, "get_instruct_model", lambda: fake_model)

    first = chortlechat.ask_chortlechat("anything", chortlechat.AskPersona.BASELINE, humor=50)
    from app.services import memory

    session = memory.get_or_create_session(first.session_id)
    roles = [turn.role for turn in session.recent_turns()]
    assert roles == [memory.ConversationRole.USER, memory.ConversationRole.ASSISTANT]
    assert session.recent_turns()[-1].content == "No grounded answer for that."


# --- Phase 3: long-term persistence -----------------------------------------


def test_ask_persists_a_grounded_exchange_to_zilliz_as_conversation_turn(monkeypatch, fake_hit):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(chortlechat, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(chortlechat, "get_instruct_model", lambda: fake_model)

    response = chortlechat.ask_chortlechat("What is Veggie?", chortlechat.AskPersona.BASELINE, humor=50)

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
    monkeypatch.setattr(chortlechat, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(chortlechat, "get_instruct_model", lambda: fake_model)

    chortlechat.ask_chortlechat("anything", chortlechat.AskPersona.BASELINE, humor=50)

    assert fake_store.add_texts_calls == []


def test_ask_survives_a_zilliz_write_failure_during_persistence(monkeypatch, fake_hit):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)

    def _raise(*args, **kwargs):
        raise RuntimeError("Zilliz is unreachable")

    fake_store.add_texts = _raise
    monkeypatch.setattr(chortlechat, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(chortlechat, "get_instruct_model", lambda: fake_model)

    response = chortlechat.ask_chortlechat("What is Veggie?", chortlechat.AskPersona.BASELINE, humor=50)

    # the /ask response is unaffected by the persistence failure — it's
    # logged and swallowed, not raised.
    assert response.grounded is True
    assert response.answer == STUBBED_ANSWER


# --- Phase 4: retrieval-augmented recall + history_source --------------------


def test_ask_reports_history_source_none_on_a_fresh_first_question(monkeypatch, fake_hit):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(chortlechat, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(chortlechat, "get_instruct_model", lambda: fake_model)

    response = chortlechat.ask_chortlechat("What is Veggie?", chortlechat.AskPersona.BASELINE, humor=50)

    assert response.history_source == chortlechat.HistorySource.NONE
    # a fresh session has nothing recoverable — no history-recall round
    # trip should even be attempted.
    assert not any("conversation_turn" in call.get("expr", "") for call in fake_store.calls)


def test_ask_reports_history_source_session_memory_for_an_in_window_followup(
    monkeypatch, fake_hit
):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(chortlechat, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(chortlechat, "get_instruct_model", lambda: fake_model)

    first = chortlechat.ask_chortlechat("What is Veggie?", chortlechat.AskPersona.BASELINE, humor=50)
    second = chortlechat.ask_chortlechat(
        "What does it grow?", chortlechat.AskPersona.BASELINE, humor=50, session_id=first.session_id
    )

    assert second.history_source == chortlechat.HistorySource.SESSION_MEMORY


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
    monkeypatch.setattr(chortlechat, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(chortlechat, "get_instruct_model", lambda: fake_model)

    response = chortlechat.ask_chortlechat(
        "What does it grow?",
        chortlechat.AskPersona.BASELINE,
        humor=50,
        session_id="resumed-session",
    )

    assert response.history_source == chortlechat.HistorySource.HISTORY_RETRIEVAL
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
    monkeypatch.setattr(chortlechat, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(chortlechat, "get_instruct_model", lambda: fake_model)

    malicious_id = "abc' or doc_type == 'science_reference"
    chortlechat.ask_chortlechat("anything", chortlechat.AskPersona.BASELINE, humor=50, session_id=malicious_id)

    history_call = next(c for c in fake_store.calls if "conversation_turn" in c.get("expr", ""))
    assert "doc_id == 'abc\\' or doc_type == \\'science_reference'" in history_call["expr"]


# --- GET /conversation/history ------------------------------------------------


def test_conversation_history_endpoint_returns_the_live_session(monkeypatch, fake_hit):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(chortlechat, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(chortlechat, "get_instruct_model", lambda: fake_model)

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


# --- Preset chip-question cache (backend/data/preset_qa.json) ----------------

CACHED_QUESTION = "What ocean heat conditions favor tropical cyclone intensification?"
CACHED_ANSWER_SNIPPET = "barrier layer thickness"
UNCACHED_NO_MATCH_QUESTION = "What atmospheric conditions influence tropical cyclone formation?"


def test_ask_serves_a_cached_baseline_answer_without_touching_retrieval(monkeypatch, fake_hit):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(chortlechat, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(chortlechat, "get_instruct_model", lambda: fake_model)

    response = chortlechat.ask_chortlechat(CACHED_QUESTION, chortlechat.AskPersona.BASELINE, humor=50)

    assert response.grounded is True
    assert CACHED_ANSWER_SNIPPET in response.answer
    assert response.answer != STUBBED_ANSWER
    assert response.source == "science_reference:nasa-smd-50#chunk0"
    # confidence is None: nothing was retrieved, on purpose — this is a
    # demo cache hit, not a scored live match.
    assert response.confidence is None
    # no Baseline generation call, and no retrieval call either — a cache
    # hit answers straight from the curated cache, live vector store and
    # instruct-model quota issues notwithstanding.
    assert fake_model.invoked_with == []
    assert fake_store.calls == []


def test_ask_serves_a_cached_answer_even_when_the_vector_store_would_fail(monkeypatch):
    """The whole point of bypassing retrieval for a cache hit: a live
    vector-store/embedding outage must not be able to take down these known
    demo questions."""

    class _RejectingVectorStore:
        def similarity_search_with_relevance_scores(self, query, **kwargs):
            raise RuntimeError("vector store is unreachable")

        def add_texts(self, texts, metadatas):
            raise RuntimeError("vector store is unreachable")

    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(chortlechat, "get_vector_store", lambda: _RejectingVectorStore())
    monkeypatch.setattr(chortlechat, "get_instruct_model", lambda: fake_model)

    response = chortlechat.ask_chortlechat(CACHED_QUESTION, chortlechat.AskPersona.BASELINE, humor=50)

    assert response.grounded is True
    assert CACHED_ANSWER_SNIPPET in response.answer


def test_ask_banter_still_makes_a_live_call_to_restyle_a_cached_baseline_answer(
    monkeypatch, fake_hit
):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(chortlechat, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(chortlechat, "get_instruct_model", lambda: fake_model)

    chortlechat.ask_chortlechat(CACHED_QUESTION, chortlechat.AskPersona.BANTER, humor=80)

    # exactly one generation call — the banter restyle — no baseline call
    # and no retrieval call.
    assert len(fake_model.invoked_with) == 1
    banter_prompt = fake_model.invoked_with[0]
    assert CACHED_ANSWER_SNIPPET in banter_prompt
    assert "80/100" in banter_prompt
    assert fake_store.calls == []


def test_ask_ignores_the_cache_for_the_documented_no_match_question(monkeypatch, fake_hit):
    fake_store = _FakeVectorStore([fake_hit])
    fake_model = _FakeInstructModel(STUBBED_ANSWER)
    monkeypatch.setattr(chortlechat, "get_vector_store", lambda: fake_store)
    monkeypatch.setattr(chortlechat, "get_instruct_model", lambda: fake_model)

    response = chortlechat.ask_chortlechat(
        UNCACHED_NO_MATCH_QUESTION, chortlechat.AskPersona.BASELINE, humor=50
    )

    # this entry's use_cache is false, per preset_qa.json — falls through to
    # normal live generation exactly as an uncached question would.
    assert response.answer == STUBBED_ANSWER
    assert len(fake_model.invoked_with) == 1
