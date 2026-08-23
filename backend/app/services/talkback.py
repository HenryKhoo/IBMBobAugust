"""Grounded generation for POST /ask — Talkback's two-persona Q&A engine.

Talkback answers real space-science questions, grounded in the ingested
NASA SMD Q&A corpus (`doc_type == 'science_reference'`; see
`backend/scripts/fetch_talkback_corpus.py` and
`backend/scripts/ingest_talkback_corpus.py` for how it gets into Zilliz).
Two voices are available — Baseline (direct, no commentary) and Banter (the
same fact, delivered with personality) — but only one of them ever touches
the actual claim: the grounded answer is generated exactly once, strictly
from the retrieved passage, always in Baseline's voice, before any persona
styling happens. Banter's step re-tells that already-generated,
already-grounded answer; it is never asked to answer the question itself
and is explicitly instructed to introduce no new fact, number, or claim.
This is what makes "honesty is not a dial" a property of the code, not
just a prompting convention — Banter has no path to inventing something
Baseline wouldn't have said first.

If nothing in the corpus scores as a confident match, both personas say so
plainly instead of guessing — same no-hallucination discipline the rest of
this API's retrieval-backed endpoints already follow.

Conversational memory (`app.services.memory`) sits on top of this in two
stages, tried in order:

1. Short-term session memory: prior turns still in the in-process sliding
   window for this session are rendered into the Baseline prompt as a
   "Conversation so far" block, so a follow-up question can be understood
   in context. This is the common case for an active conversation.
2. Long-term history retrieval: only when that window is empty for this
   `session_id` (an unrecognized/evicted id, or a fresh process after a
   restart) does Talkback fall back to searching Zilliz for this same
   session's own grounded exchanges from earlier — see
   `app.services.memory.recall_relevant_history`.

Either way this changes what a question is interpreted to *mean* only —
the grounding rules above are otherwise untouched: memory is never a
source of facts and never substitutes for the current question's own
retrieval. `AskResponse.history_source` reports which of the two stages
(if either) actually contributed, purely as transparency — see
`app.schemas.HistorySource`. See `_history_block`, `_recalled_history_block`,
and `app.services.memory`'s module docstring.
"""

from __future__ import annotations

from app.schemas import (
    AskPersona,
    AskResponse,
    ConversationRole,
    ConversationTurn,
    HistorySource,
)
from app.services.memory import get_or_create_session, persist_grounded_exchange, recall_relevant_history
from app.services.vector_store import get_vector_store, relevance_score_hits_or_empty
from app.services.watsonx import get_instruct_model

# Below this, a retrieval hit exists but is too weak to trust — same
# rationale as every other threshold in this codebase: a low score still
# returned *something*, but "something" isn't the same as "grounded enough
# to state as fact." This is on the COSINE-similarity scale vector_store.py
# now pins the collection to: raw cosine similarity in [-1, 1] gets mapped
# to confidence via `(cos + 1) / 2`, so confidence 0.5 means "orthogonal /
# no relation" and 1.0 means "identical." 0.68 corresponds to roughly
# cos >= 0.36, which for sentence-style embeddings is a reasonable line
# between "topically related" and "coincidentally overlapping vocabulary."
# Chosen as a well-reasoned starting point, not tuned against a validation
# set — retest with a mix of in-corpus and clearly-out-of-corpus questions
# after any corpus or embedding-model change, and adjust.
_CONFIDENCE_THRESHOLD = 0.68

_BASELINE_PROMPT = """You are Baseline, a factual research assistant answering real \
questions about space science and NASA missions. Answer strictly using the \
reference passage below. Do not add information the passage does not \
support, and do not speculate beyond it. If the passage only partly \
answers the question, say what it does support and stop there. Two to \
four sentences, plain and direct, no commentary or humor.
{history}
Reference passage:
{passage}

Question: {question}

Answer:"""

_BANTER_PROMPT = """You are Banter, the same research assistant as Baseline but with \
personality turned on. Below is a factual answer Baseline already gave, \
already fully grounded in a reference passage. You are not answering the \
question yourself — you are re-telling Baseline's exact answer in your \
own voice. Every fact, number, and claim in your version must match \
Baseline's answer. You may add wit, an aside, or a joke, but you may \
never add a new fact, number, or claim that is not already present in \
Baseline's answer below.

Humor level: {humor}/100 ({humor_label}). At low levels stay close to \
Baseline's own phrasing with only a light touch of personality. At high \
levels, feel free to lead with a joke or aside before landing the fact.

Baseline's answer: {baseline_answer}

Banter's version:"""

_FALLBACK_BASELINE = "No grounded answer for that."
_FALLBACK_BANTER = (
    "I've got nothing solid on that one. Nothing in the corpus backs it up, "
    "so I'm not going to make something up just to sound clever."
)


def _humor_label(humor: int) -> str:
    if humor < 34:
        return "mostly serious"
    if humor < 67:
        return "balanced"
    return "lean into it"


def _source_line(metadata: dict) -> str:
    return f"{metadata['doc_type']}:{metadata['doc_id']}#chunk{metadata['chunk_index']}"


def _history_block(turns: list[ConversationTurn]) -> str:
    """Render prior turns as a "Conversation so far" block for the Baseline prompt.

    Empty string — not e.g. "Conversation so far:\\n(none)" — when there's
    no history yet, so the first question in a session sees byte-for-byte
    the same prompt Talkback always used before this feature existed. No
    regression for the common single-question case.

    This is included so the model can resolve a follow-up's pronouns and
    implicit subject ("what does it eat?") against what was already asked
    and answered. It is never a source of facts for the *current* answer —
    that's still generated strictly from `passage` in `_BASELINE_PROMPT`,
    exactly as before this existed.
    """
    if not turns:
        return ""
    lines = [
        f"{'Question' if turn.role == ConversationRole.USER else 'Answer'}: {turn.content}"
        for turn in turns
    ]
    return "\nConversation so far:\n" + "\n".join(lines) + "\n"


def _recalled_history_block(chunks: list) -> str:
    """Render Zilliz-recovered past exchanges as a "Conversation so far" block.

    Same shape and same empty-string-when-nothing convention as
    `_history_block`, so the Baseline prompt looks identical to the model
    regardless of whether history came from the live session window or was
    recovered from long-term storage. Each chunk's `page_content` is
    already a "Question: ...\\nAnswer: ..." block (see
    `app.services.memory.persist_grounded_exchange`), so this just joins
    them — no reparsing needed.
    """
    if not chunks:
        return ""
    body = "\n".join(chunk.page_content for chunk in chunks)
    return "\nConversation so far:\n" + body + "\n"


def _retrieval_strength(relevance_score: float) -> float:
    """Normalize a retrieval relevance score to a [0, 1] confidence signal.

    Same clamp-and-round `app.services.query._relevance` applies, for the
    same reason: `similarity_search_with_relevance_scores` normalizes to
    `[0, 1]` but its own base implementation only warns, never clamps,
    when a score lands outside that range regardless.
    """
    return round(max(0.0, min(1.0, relevance_score)), 2)


def _fallback_response(
    persona: AskPersona,
    confidence: float | None,
    session_id: str,
    history_source: HistorySource,
) -> AskResponse:
    return AskResponse(
        answer=_FALLBACK_BASELINE if persona == AskPersona.BASELINE else _FALLBACK_BANTER,
        persona=persona,
        grounded=False,
        confidence=confidence,
        source=None,
        session_id=session_id,
        history_source=history_source,
    )


def ask_talkback(
    question: str, persona: AskPersona, humor: int, session_id: str | None = None
) -> AskResponse:
    """Answer a space-science question, grounded in the ingested corpus.

    Retrieves the single best-matching `science_reference` chunk. With
    nothing ingested yet, or a match below `_CONFIDENCE_THRESHOLD`, both
    personas return an honest no-match response rather than let the model
    guess — see the module docstring. Above threshold, the grounded answer
    is generated exactly once, always in Baseline's voice; Banter re-styles
    that finished, already-true answer rather than generating its own, so
    the humor dial can never change what is actually claimed.

    `session_id` opts into conversational memory (`app.services.memory`):
    prior context for this question is resolved in two stages — the
    in-process session window first, then (only if that's empty for this
    `session_id`) a Zilliz search scoped to this same session's own
    long-term history — and rendered into the Baseline prompt before this
    question's turn is recorded. This question's turn plus whatever answer
    gets returned are recorded in the short-term window afterward,
    regardless of whether that answer was grounded or a fallback; a
    grounded answer is additionally persisted to long-term storage (see
    `app.services.memory.persist_grounded_exchange`). `None` starts a
    brand-new session. Either way the returned `AskResponse.session_id` is
    what a caller sends back on the next turn to keep continuity, and
    `AskResponse.history_source` reports which stage (if either) actually
    contributed context for this question.
    """
    store = get_vector_store()
    session = get_or_create_session(session_id)
    in_window = session.recent_turns()

    if in_window:
        history = _history_block(in_window)
        history_source = HistorySource.SESSION_MEMORY
    elif session_id is not None:
        # `session_id is not None` — a caller only ever passes an id it
        # already got back from a prior response, so a fresh `None` call
        # (see `test_ask_without_session_id_starts_a_fresh_session_each_time`)
        # skips this Zilliz round-trip entirely: `get_or_create_session`
        # guarantees a brand-new, never-issued id in that case, so nothing
        # could possibly be recoverable for it.
        recalled_chunks = recall_relevant_history(store, session_id, question)
        history = _recalled_history_block(recalled_chunks)
        history_source = (
            HistorySource.HISTORY_RETRIEVAL if recalled_chunks else HistorySource.NONE
        )
    else:
        history = ""
        history_source = HistorySource.NONE

    session.add_turn(ConversationRole.USER, question)

    hits = relevance_score_hits_or_empty(
        store, question, k=1, expr="doc_type == 'science_reference'"
    )
    if not hits:
        response = _fallback_response(
            persona, confidence=None, session_id=session.session_id, history_source=history_source
        )
        session.add_turn(ConversationRole.ASSISTANT, response.answer, persona=persona)
        return response

    chunk, relevance_score = hits[0]
    confidence = _retrieval_strength(relevance_score)
    if confidence < _CONFIDENCE_THRESHOLD:
        response = _fallback_response(
            persona, confidence=confidence, session_id=session.session_id, history_source=history_source
        )
        session.add_turn(ConversationRole.ASSISTANT, response.answer, persona=persona)
        return response

    baseline_prompt = _BASELINE_PROMPT.format(
        history=history, passage=chunk.page_content, question=question
    )
    baseline_message = get_instruct_model().invoke(baseline_prompt)
    baseline_answer = str(baseline_message.content).strip()

    if persona == AskPersona.BASELINE:
        final_answer = baseline_answer
    else:
        banter_prompt = _BANTER_PROMPT.format(
            humor=humor, humor_label=_humor_label(humor), baseline_answer=baseline_answer
        )
        banter_message = get_instruct_model().invoke(banter_prompt)
        final_answer = str(banter_message.content).strip()

    source = _source_line(chunk.metadata)
    session.add_turn(ConversationRole.ASSISTANT, final_answer, persona=persona, source=source)
    persist_grounded_exchange(
        store, session.session_id, session.turn_count, question, final_answer, persona, source
    )

    return AskResponse(
        answer=final_answer,
        persona=persona,
        grounded=True,
        confidence=confidence,
        source=source,
        session_id=session.session_id,
        history_source=history_source,
    )
