import pytest

from app.services import memory


@pytest.fixture(autouse=True)
def _clear_sessions():
    """Every test gets an empty session store — this module is process-global state."""
    memory.reset()
    yield
    memory.reset()


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
