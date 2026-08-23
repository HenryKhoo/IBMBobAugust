"""Short-term, in-process conversational memory for POST /ask.

Talkback's `/ask` endpoint is otherwise stateless — each call is graded
independently on its own retrieval and its own generation (see
`app.services.talkback`). This module adds a thin session layer on top so a
natural follow-up ("what does it eat?" after "tell me about Snoopy the
rat") can be answered without the caller re-stating the whole question.

The grounding discipline in `app.services.talkback` is unchanged by this:
history here only ever helps the model interpret what a follow-up question
*means*. It never supplies a fact directly, and it never substitutes for
retrieval — every generated answer is still produced strictly from
whatever passage the *current* question retrieves. A wrong or stale memory
can make Talkback answer the wrong question; it can never make Talkback
state an ungrounded claim.

Storage is a plain in-process dict, not Zilliz or any external store. That
means memory doesn't survive a restart and doesn't work across multiple
server instances — an acceptable limitation for a single-process
deployment, but the first thing to replace (Redis, or Zilliz itself keyed
by session_id) if this ever needs to run horizontally. Sessions are never
explicitly deleted by a caller; `_MAX_SESSIONS` bounds memory growth by
evicting the least-recently-active session once the store is full, rather
than growing unbounded across a long-lived process.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from app.schemas import AskPersona, ConversationRole, ConversationTurn

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


def reset() -> None:
    """Clear every session. Test-only — production code never needs to wipe the store."""
    _sessions.clear()
