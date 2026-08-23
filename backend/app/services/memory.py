"""Conversational memory for POST /ask — short-term (in-process) and long-term (Zilliz).

ChortleChat's `/ask` endpoint is otherwise stateless — each call is graded
independently on its own retrieval and its own generation (see
`app.services.chortlechat`). This module adds two layers on top so a natural
follow-up ("what does it eat?" after "tell me about Snoopy the rat") can be
answered without the caller re-stating the whole question:

- Short-term session memory: a plain in-process dict, keyed by
  `session_id`, holding a sliding window of the most recent turns. Fast and
  exact, but doesn't survive a restart and doesn't work across multiple
  server instances — an acceptable limitation for a single-process
  deployment, and the common case, since most conversations are short
  enough to fit entirely inside the window.
- Long-term history: once an exchange is grounded, it's also written to
  Zilliz as a `conversation_turn` chunk tagged with `doc_id == session_id`
  (see `persist_grounded_exchange`) — the same store `science_reference`
  documents already live in, just a different `doc_type`. This is what
  makes a session's history outlive the in-process window: recoverable
  after a restart, after the session got evicted from `_sessions` under
  memory pressure, or once a conversation has run past `_MAX_TURNS` and the
  window has trimmed the earlier turns away. Recall is always scoped to one
  `session_id` via the `expr` filter (see `recall_relevant_history` and
  `list_full_history`) — never a cross-session search — so one visitor's
  questions can never surface as context in another visitor's conversation.
  Only grounded exchanges are persisted; a fallback "no grounded answer"
  turn carries no source and nothing worth recalling later, so it's kept in
  the short-term window only.

The grounding discipline in `app.services.chortlechat` is unchanged by either
layer: history only ever helps the model interpret what a follow-up
question *means*. It never supplies a fact directly, and it never
substitutes for retrieval — every generated answer is still produced
strictly from whatever `science_reference` passage the *current* question
retrieves. A wrong or stale memory can make ChortleChat answer the wrong
question; it can never make ChortleChat state an ungrounded claim.

Short-term storage is bounded two ways: `_MAX_TURNS` trims each session's
own window, and `_MAX_SESSIONS` bounds memory growth by evicting the
least-recently-active session once the store is full, rather than growing
unbounded across a long-lived process. Long-term storage has no such
ceiling here — it grows with the corpus, the same as ingested documents do.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field

from app.schemas import AskPersona, ConversationRole, ConversationTurn, HistorySource
from app.services.vector_store import (
    escape_expr_string_literal,
    relevance_score_hits_or_empty,
)

logger = logging.getLogger(__name__)

# The doc_type tag long-term conversation history is stored under in
# Zilliz — a sibling of "science_reference", not a `DocumentType` a caller
# can submit through POST /ingest. Keeping it out of that enum on purpose:
# conversation turns are only ever written by this module, never accepted
# as raw input, so there's no reason to let a client claim this doc_type.
_CONVERSATION_TURN_DOC_TYPE = "conversation_turn"

# How many past exchanges `recall_relevant_history` pulls back for context
# injection into the next prompt — small on purpose, this is a "does this
# question echo something we already covered" check, not a full transcript
# dump. Contrast with `_HISTORY_LIST_K` below.
_HISTORY_RECALL_K = 3

# How many past exchanges `list_full_history` (GET /conversation/history)
# fetches when reconstructing a session's complete transcript. Set high
# relative to any real conversation length in this demo so a filtered
# search (expr scopes it to one session_id already) effectively returns
# "everything for this session" rather than an arbitrary top-k slice.
_HISTORY_LIST_K = 50

# Turns kept per session, oldest first. Counts USER and ASSISTANT turns
# separately, so this is _MAX_TURNS // 2 question/answer exchanges of
# replayed context once a session is full — 8 turns is 4 exchanges, enough
# for a real back-and-forth without the prompt growing unbounded over a
# long conversation. Not tuned against real usage, just a sane starting
# ceiling.
_MAX_TURNS = 8

# Sessions kept across the whole process before the least-recently-active
# one is evicted to make room for a new one. Bounds memory growth on a
# long-lived server; also not tuned against real traffic.
_MAX_SESSIONS = 1000


@dataclass
class ConversationSession:
    """Live, mutable conversation state for one session_id.

    Deliberately not a Pydantic model the way `ConversationTurn` is — this
    is process-local mutable state that's never serialized over the wire
    as-is, only read from (`recent_turns`) to build a prompt, or written to
    (`add_turn`) once a generation call completes.
    """

    session_id: str
    turns: list[ConversationTurn] = field(default_factory=list)
    last_active: float = field(default_factory=time.time)
    # Total turns ever added to this session, uncapped by the `_MAX_TURNS`
    # trim below — unlike `len(turns)`, this never plateaus once the
    # window fills, so it's what `persist_grounded_exchange` uses as a
    # stable, ever-increasing `chunk_index` for this session's long-term
    # Zilliz records (see that function).
    turn_count: int = 0

    def add_turn(
        self,
        role: ConversationRole,
        content: str,
        *,
        persona: AskPersona | None = None,
        source: str | None = None,
    ) -> None:
        self.turns.append(
            ConversationTurn(role=role, content=content, persona=persona, source=source)
        )
        self.turn_count += 1
        # Trim from the front, not the back — a sliding window keeps the
        # *most recent* turns, which is what a follow-up question needs.
        if len(self.turns) > _MAX_TURNS:
            self.turns = self.turns[-_MAX_TURNS:]
        self.last_active = time.time()

    def recent_turns(self) -> list[ConversationTurn]:
        """The current sliding window, oldest first — ready to replay into a prompt."""
        return list(self.turns)


_sessions: dict[str, ConversationSession] = {}


def _evict_least_recently_active() -> None:
    if not _sessions:
        return
    oldest_id = min(_sessions, key=lambda sid: _sessions[sid].last_active)
    del _sessions[oldest_id]


def get_or_create_session(session_id: str | None) -> ConversationSession:
    """Look up an existing session, or start a new one.

    An unrecognized `session_id` — evicted, or simply never issued by this
    process (e.g. after a restart, since sessions are in-memory only) —
    starts a fresh session under that same id rather than raising, so a
    caller replaying a stale id degrades to "no memory yet" instead of an
    error. Passing `None` always creates a brand-new session with a
    server-generated id, matching `AskRequest.session_id`'s
    first-question-in-a-conversation case.
    """
    if session_id and session_id in _sessions:
        session = _sessions[session_id]
        session.last_active = time.time()
        return session

    new_id = session_id or str(uuid.uuid4())
    if len(_sessions) >= _MAX_SESSIONS:
        _evict_least_recently_active()
    session = ConversationSession(session_id=new_id)
    _sessions[new_id] = session
    return session


def _session_expr(session_id: str) -> str:
    """Milvus `expr` filter scoping a query to one session's conversation history.

    `session_id` is caller-controlled (see the module docstring on
    `get_or_create_session`), so it's escaped before interpolation —
    without that, a crafted `session_id` could break out of the string
    literal and turn a session-scoped recall into a cross-session one. See
    `app.services.vector_store.escape_expr_string_literal`.
    """
    escaped = escape_expr_string_literal(session_id)
    return f"doc_type == '{_CONVERSATION_TURN_DOC_TYPE}' and doc_id == '{escaped}'"


def persist_grounded_exchange(
    store,
    session_id: str,
    chunk_index: int,
    question: str,
    answer: str,
    persona: AskPersona,
    source: str,
) -> None:
    """Write one grounded question/answer exchange into Zilliz as long-term history.

    Only ever called for a grounded exchange (see `app.services.chortlechat`)
    — a fallback "no grounded answer" turn has no source and nothing worth
    recalling later, so it's never persisted here, only kept in the
    short-term window.

    Best-effort and never raises: a Zilliz write failure here must not
    break the `/ask` response the caller is already waiting on, since the
    short-term in-process turn was already recorded regardless. A failure
    is logged and swallowed — the cost is that this one exchange won't be
    recoverable after the session leaves the in-process window, not a
    failed request.

    `page_content` is a single "Question / Answer" block, so a similarity
    search naturally matches on either side. `question` and `answer` are
    additionally kept as separate metadata fields (rather than requiring a
    caller to re-parse `page_content`) for `list_full_history` to
    reconstruct a clean `ConversationTurn` pair from.
    """
    text = f"Question: {question}\nAnswer: {answer}"
    metadata = {
        "doc_type": _CONVERSATION_TURN_DOC_TYPE,
        "doc_id": session_id,
        "chunk_index": chunk_index,
        "question": question,
        "answer": answer,
        "persona": persona.value,
        "source": source,
    }
    try:
        store.add_texts(texts=[text], metadatas=[metadata])
    except Exception:
        logger.warning(
            "Failed to persist long-term conversation history for session_id=%r "
            "(chunk_index=%d) — the short-term in-process turn is unaffected.",
            session_id,
            chunk_index,
            exc_info=True,
        )


def recall_relevant_history(store, session_id: str, question: str, *, k: int = _HISTORY_RECALL_K):
    """Search Zilliz for this session's own past exchanges most relevant to `question`.

    Used by `app.services.chortlechat.ask_chortlechat` only when the in-process
    short-term window is empty for this `session_id` — i.e. session memory
    has nothing (an unrecognized id, an evicted session, or a fresh
    process after a restart), but grounded history for this same session
    may still be recoverable from long-term storage. Always scoped to one
    `session_id` via `_session_expr` — never a cross-session search.

    Returns the matched chunks themselves (not `(chunk, score)` pairs) in
    retrieval-relevance order — the caller only ever renders their
    `page_content`/`question`/`answer`, and has no use for the score, since
    this recall is never treated as a confidence signal on the *answer*
    the way passage retrieval is (see `HistorySource`'s docstring).
    """
    hits = relevance_score_hits_or_empty(
        store, question, k=k, expr=_session_expr(session_id)
    )
    return [chunk for chunk, _score in hits]


def list_full_history(store, session_id: str, *, k: int = _HISTORY_LIST_K) -> list[ConversationTurn]:
    """Reconstruct a session's full grounded history from Zilliz, oldest first.

    Used by `GET /conversation/history` once a session is no longer in the
    in-process store. Queries with a fixed, topic-neutral string rather
    than any real question — this isn't a relevance search, it's "give me
    everything filed under this session_id" — then re-sorts by
    `chunk_index` (assigned in persist order by `persist_grounded_exchange`)
    rather than trusting similarity-search order, so the reconstructed
    transcript reads chronologically, the way a real conversation did.

    Only grounded exchanges are ever persisted, so this can never recover
    a fallback "no grounded answer" turn — see `persist_grounded_exchange`.
    Each stored exchange becomes a USER turn followed by its ASSISTANT
    turn, matching the shape `ConversationSession.recent_turns()` already
    returns for the in-process case.
    """
    hits = relevance_score_hits_or_empty(
        store, "conversation history", k=k, expr=_session_expr(session_id)
    )
    chunks = sorted((chunk for chunk, _score in hits), key=lambda c: c.metadata["chunk_index"])

    turns: list[ConversationTurn] = []
    for chunk in chunks:
        meta = chunk.metadata
        turns.append(ConversationTurn(role=ConversationRole.USER, content=meta["question"]))
        turns.append(
            ConversationTurn(
                role=ConversationRole.ASSISTANT,
                content=meta["answer"],
                persona=AskPersona(meta["persona"]),
                source=meta["source"],
            )
        )
    return turns


def get_conversation_history(
    store_factory, session_id: str
) -> tuple[list[ConversationTurn], HistorySource]:
    """The full transcript `GET /conversation/history` should show for `session_id`.

    Prefers the live in-process session when one exists for this id — it's
    the freshest, most complete picture of an *active* conversation, even
    though it's capped to the last `_MAX_TURNS` turns by the sliding
    window. Falls back to `list_full_history`'s Zilliz reconstruction only
    once the in-process session is gone, which is also the only case where
    a transcript can run longer than `_MAX_TURNS` (long-term storage has no
    such cap) but can never include a fallback turn (see
    `persist_grounded_exchange`). An unrecognized `session_id` with no
    long-term history either returns an empty transcript with
    `HistorySource.NONE`, not an error — the same "unknown id degrades to
    nothing, not a failure" behavior `get_or_create_session` already has.

    `store_factory` — not a store instance — because the common case (a
    live in-process session) never needs Zilliz at all. Called (and its
    result actually used) only in the fallback branch, so a request for a
    still-active session never pays for a vector store round trip, and
    never requires Zilliz credentials to be configured just to serve
    something already sitting in memory. Pass `app.services.vector_store.
    get_vector_store` itself, the same lazily-constructed, cached factory
    every other call site uses.
    """
    session = _sessions.get(session_id)
    if session and session.turns:
        return session.recent_turns(), HistorySource.SESSION_MEMORY

    turns = list_full_history(store_factory(), session_id)
    if turns:
        return turns, HistorySource.HISTORY_RETRIEVAL
    return [], HistorySource.NONE


def reset() -> None:
    """Clear every session. Test-only — production code never needs to wipe the store."""
    _sessions.clear()
