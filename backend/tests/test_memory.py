import pytest

from app.schemas import AskPersona, HistorySource
from app.services import memory


@pytest.fixture(autouse=True)
def _clear_sessions():
    """Every test gets an empty session store — this module is process-global state."""
    memory.reset()
    yield
    memory.reset()


class _FakeDocument:
    def __init__(self, page_content: str, metadata: dict):
        self.page_content = page_content
        self.metadata = metadata


class _FakeStore:
    """Records add_texts calls; returns configured hits, filtered like a real
    Milvus `expr` would scope a query — only when `expr` targets this exact
    `doc_id`, so a test can prove recall/listing is actually session-scoped
    rather than trusting the fake to hand back whatever it was given.
    """

    def __init__(self, hits: list[tuple] | None = None):
        self.hits = hits or []
        self.add_texts_calls: list[dict] = []
        self.search_calls: list[dict] = []

    def add_texts(self, texts, metadatas):
        self.add_texts_calls.append({"texts": list(texts), "metadatas": list(metadatas)})
        return [f"id-{i}" for i in range(len(texts))]

    def similarity_search_with_relevance_scores(self, query, **kwargs):
        self.search_calls.append({"query": query, **kwargs})
        expr = kwargs.get("expr", "")
        return [
            (chunk, score)
            for chunk, score in self.hits
            if f"doc_id == '{chunk.metadata['doc_id']}'" in expr
        ]


def test_get_or_create_session_with_none_always_creates_a_new_session():
    first = memory.get_or_create_session(None)
    second = memory.get_or_create_session(None)

    assert first.session_id != second.session_id
    assert first.turns == []


def test_get_or_create_session_returns_the_same_session_for_a_known_id():
    created = memory.get_or_create_session(None)
    created.add_turn(memory.ConversationRole.USER, "What is Veggie?")

    fetched = memory.get_or_create_session(created.session_id)

    assert fetched is created
    assert len(fetched.recent_turns()) == 1


def test_get_or_create_session_with_an_unknown_id_starts_fresh_under_that_id():
    session = memory.get_or_create_session("some-id-never-issued")

    assert session.session_id == "some-id-never-issued"
    assert session.recent_turns() == []


def test_add_turn_trims_to_the_sliding_window_keeping_the_most_recent():
    session = memory.get_or_create_session(None)
    for i in range(memory._MAX_TURNS + 4):
        session.add_turn(memory.ConversationRole.USER, f"turn {i}")

    turns = session.recent_turns()
    assert len(turns) == memory._MAX_TURNS
    # oldest turns were dropped; the tail (most recent) survives, in order.
    assert turns[0].content == f"turn {4}"
    assert turns[-1].content == f"turn {memory._MAX_TURNS + 3}"


def test_add_turn_records_persona_and_source_on_assistant_turns_only():
    session = memory.get_or_create_session(None)
    session.add_turn(memory.ConversationRole.USER, "What is Veggie?")
    session.add_turn(
        memory.ConversationRole.ASSISTANT,
        "A plant growth chamber.",
        persona=memory.AskPersona.BASELINE,
        source="science_reference:nasa-smd-veggie-001#chunk0",
    )

    user_turn, assistant_turn = session.recent_turns()
    assert user_turn.persona is None
    assert user_turn.source is None
    assert assistant_turn.persona == memory.AskPersona.BASELINE
    assert assistant_turn.source == "science_reference:nasa-smd-veggie-001#chunk0"


def test_evicts_least_recently_active_session_once_store_is_full(monkeypatch):
    monkeypatch.setattr(memory, "_MAX_SESSIONS", 2)

    first = memory.get_or_create_session("session-a")
    second = memory.get_or_create_session("session-b")
    # touch "session-b" more recently than "session-a" so eviction picks "session-a".
    second.last_active = first.last_active + 1

    memory.get_or_create_session("session-c")

    assert "session-a" not in memory._sessions
    assert "session-b" in memory._sessions
    assert "session-c" in memory._sessions


# --- Phase 3: persist_grounded_exchange --------------------------------------


def test_persist_grounded_exchange_writes_a_conversation_turn_chunk():
    store = _FakeStore()

    memory.persist_grounded_exchange(
        store, "session-a", 2, "What is Veggie?", "A plant growth chamber.",
        AskPersona.BASELINE, "science_reference:doc-1#chunk0",
    )

    assert len(store.add_texts_calls) == 1
    call = store.add_texts_calls[0]
    assert call["texts"] == ["Question: What is Veggie?\nAnswer: A plant growth chamber."]
    assert call["metadatas"][0] == {
        "doc_type": "conversation_turn",
        "doc_id": "session-a",
        "chunk_index": 2,
        "question": "What is Veggie?",
        "answer": "A plant growth chamber.",
        "persona": "baseline",
        "source": "science_reference:doc-1#chunk0",
    }


def test_persist_grounded_exchange_swallows_a_write_failure():
    store = _FakeStore()
    store.add_texts = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("unreachable"))

    # must not raise — persistence is best-effort.
    memory.persist_grounded_exchange(
        store, "session-a", 1, "q", "a", AskPersona.BASELINE, "source:doc#chunk0"
    )


# --- Phase 4: recall_relevant_history, list_full_history, get_conversation_history --


def _conversation_turn_chunk(doc_id: str, chunk_index: int, question: str, answer: str) -> _FakeDocument:
    return _FakeDocument(
        f"Question: {question}\nAnswer: {answer}",
        {
            "doc_type": "conversation_turn",
            "doc_id": doc_id,
            "chunk_index": chunk_index,
            "question": question,
            "answer": answer,
            "persona": "baseline",
            "source": "science_reference:doc-1#chunk0",
        },
    )


def test_recall_relevant_history_is_scoped_to_the_given_session_id():
    mine = _conversation_turn_chunk("session-a", 1, "What is Veggie?", "A growth chamber.")
    someone_elses = _conversation_turn_chunk("session-b", 1, "What is Veggie?", "A growth chamber.")
    store = _FakeStore(hits=[(mine, 0.9), (someone_elses, 0.9)])

    results = memory.recall_relevant_history(store, "session-a", "What is Veggie?")

    assert results == [mine]


def test_recall_relevant_history_returns_empty_for_an_unrecognized_session():
    store = _FakeStore(hits=[])

    assert memory.recall_relevant_history(store, "never-seen", "anything") == []


def test_list_full_history_reconstructs_question_answer_pairs_in_chunk_order():
    second = _conversation_turn_chunk("session-a", 2, "What does it grow?", "Leafy greens.")
    first = _conversation_turn_chunk("session-a", 1, "What is Veggie?", "A growth chamber.")
    # hits arrive out of order — list_full_history must re-sort by chunk_index.
    store = _FakeStore(hits=[(second, 0.5), (first, 0.9)])

    turns = memory.list_full_history(store, "session-a")

    assert [t.content for t in turns] == [
        "What is Veggie?", "A growth chamber.", "What does it grow?", "Leafy greens.",
    ]
    assert [t.role for t in turns] == [
        memory.ConversationRole.USER, memory.ConversationRole.ASSISTANT,
        memory.ConversationRole.USER, memory.ConversationRole.ASSISTANT,
    ]
    assert turns[1].persona == AskPersona.BASELINE
    assert turns[1].source == "science_reference:doc-1#chunk0"


def test_get_conversation_history_prefers_the_live_session_when_present():
    session = memory.get_or_create_session("session-a")
    session.add_turn(memory.ConversationRole.USER, "What is Veggie?")

    def _fail_if_called():
        raise AssertionError("must not reach Zilliz when the live session already has turns")

    turns, source = memory.get_conversation_history(_fail_if_called, "session-a")

    assert source == HistorySource.SESSION_MEMORY
    assert len(turns) == 1


def test_get_conversation_history_falls_back_to_zilliz_when_session_is_gone():
    chunk = _conversation_turn_chunk("session-a", 1, "What is Veggie?", "A growth chamber.")
    store = _FakeStore(hits=[(chunk, 0.9)])

    turns, source = memory.get_conversation_history(lambda: store, "session-a")

    assert source == HistorySource.HISTORY_RETRIEVAL
    assert len(turns) == 2


def test_get_conversation_history_returns_none_for_a_totally_unknown_session():
    store = _FakeStore(hits=[])

    turns, source = memory.get_conversation_history(lambda: store, "never-seen")

    assert turns == []
    assert source == HistorySource.NONE
