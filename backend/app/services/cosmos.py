"""Grounded generation for POST /ask — C.O.S.M.O.S.'s two-persona Q&A engine.

C.O.S.M.O.S. answers real space-science questions, grounded in the ingested
NASA SMD Q&A corpus (`doc_type == 'science_reference'`; see
`backend/scripts/fetch_cosmos_corpus.py` and
`backend/scripts/ingest_cosmos_corpus.py` for how it gets into Zilliz).
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

For the fixed set of "chip" questions the frontend suggests
(`backend/data/preset_qa.json`, drafted in `docs/preset-qa-draft.md`), a
matching question is answered straight from that curated cache — no
retrieval, no confidence gate, and no generation call for *either* persona
— so these known-good demo questions always answer instantly and
consistently, with zero dependency on a live vector store or instruct
model. Baseline and Banter each have their own pre-drafted, corpus-verified
text in the cache (`baseline_answer` / `banter_answer`); Banter's cached
copy still only ever restates what Baseline's cached copy says, drafted by
hand under the exact same "no new fact" rule `_BANTER_PROMPT` enforces at
generation time — it's just not generated live for these questions. Every
cached `banter_answer` opens with an actual short joke on the question's
topic (style inspired by the Kaggle "Short Jokes" dataset; see
`backend/data/preset_qa.json`'s `_readme`) — jokes are commentary, not a
claim, so they don't touch the "no new fact" rule either way. All 15 chip
questions currently have a genuine grounded answer (see
`preset_qa.json`'s `summary` block: `no_match: 0`), but a cache entry can
still carry `grounded: false` if a future chip question doesn't clear the
bar — it would route straight to the same honest fallback every other
unanswerable question gets — see `_PRESET_CACHE` and `_preset_response`.

Conversational memory (`app.services.memory`) sits on top of this in two
stages, tried in order:

1. Short-term session memory: prior turns still in the in-process sliding
   window for this session are rendered into the Baseline prompt as a
   "Conversation so far" block, so a follow-up question can be understood
   in context. This is the common case for an active conversation.
2. Long-term history retrieval: only when that window is empty for this
   `session_id` (an unrecognized/evicted id, or a fresh process after a
   restart) does C.O.S.M.O.S. fall back to searching Zilliz for this same
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

import json
from pathlib import Path

from app.schemas import (
    AskPersona,
    AskResponse,
    ConversationRole,
    ConversationTurn,
    Domain,
    HistorySource,
)
from app.services.memory import get_or_create_session, persist_grounded_exchange, recall_relevant_history
from app.services.vector_store import (
    escape_expr_string_literal,
    get_vector_store,
    relevance_score_hits_or_empty,
)
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

# Cache-first lookup for the frontend's suggested "chip" questions — see
# backend/data/preset_qa.json's own _readme and docs/preset-qa-draft.md for
# how each entry was drafted and verified against the corpus. This is a
# curated demo path, not a shortcut layered on top of live retrieval: a
# cache hit answers directly from a pre-verified answer and skips
# retrieval, the confidence-threshold gate, and the generation call
# entirely — for *both* personas — so all 15 known chip questions always
# answer instantly and consistently in a live demo, with zero dependency on
# a live vector store or instruct model. Baseline and Banter each read
# their own pre-drafted field (`baseline_answer` / `banter_answer`); any
# entry with `grounded: false` (no passage in the corpus actually
# answers it) is cached too, and routes to the exact same honest fallback
# `_fallback_response` gives any other unanswerable question — see
# `_preset_response`. `confidence` is always `None` on a cache hit — same
# meaning `AskResponse.confidence` already carries for "nothing was
# retrieved," which is literally true here since retrieval never ran.
# Keyed by the exact chip question text (stripped/lowercased for a
# forgiving match); every entry in the file is flagged `use_cache: true`.
_PRESET_QA_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "preset_qa.json"


def _load_preset_cache() -> dict[str, dict]:
    if not _PRESET_QA_PATH.exists():
        return {}
    with _PRESET_QA_PATH.open() as f:
        data = json.load(f)
    return {
        entry["question"].strip().lower(): entry
        for entry in data.get("entries", [])
        if entry.get("use_cache")
    }


_PRESET_CACHE = _load_preset_cache()


def _humor_label(humor: int) -> str:
    if humor < 34:
        return "mostly serious"
    if humor < 67:
        return "balanced"
    return "lean into it"


def _source_line(metadata: dict) -> str:
    return f"{metadata['doc_type']}:{metadata['doc_id']}#chunk{metadata['chunk_index']}"


def _retrieval_expr(domain: Domain | None) -> str:
    """Build the Milvus `expr` for the main-answer retrieval.

    `domain` is a closed `Domain` enum value, not free text a caller could
    inject through — Pydantic already rejects anything else at the
    `AskRequest`/`QueryRequest` boundary — so escaping here is
    defense-in-depth rather than a real injection risk, matching how
    every other filter value in this codebase gets escaped before joining
    an `expr`, regardless of how trusted its source looks today.
    """
    expr = "doc_type == 'science_reference'"
    if domain is not None:
        expr += f" and domain == '{escape_expr_string_literal(domain.value)}'"
    return expr


def _history_block(turns: list[ConversationTurn]) -> str:
    """Render prior turns as a "Conversation so far" block for the Baseline prompt.

    Empty string — not e.g. "Conversation so far:\\n(none)" — when there's
    no history yet, so the first question in a session sees byte-for-byte
    the same prompt C.O.S.M.O.S. always used before this feature existed. No
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


def _message_text(message) -> str:
    """Extract plain answer text from a chat model's response message.

    `message.content` is a plain `str` for every watsonx tier this project
    uses, but not every provider guarantees that -- Gemini's fallback tier
    (`get_instruct_model`'s third tier, added 2026-08-26) can return a
    `list` of content blocks instead: a `text` part plus, when its
    extended-thinking mode is on, a `thought`-carrying part with an opaque
    `signature` blob for cross-turn continuity. Naively `str()`-ing that
    list dumps the whole structure -- signature included -- straight into
    the user-facing answer, which is exactly what happened live before this
    existed (see `app.services.watsonx._gemini_chat`'s docstring, which
    also disables thinking outright so this case should be rare going
    forward). This concatenates only genuine `text` parts, in order,
    regardless of which shape the active provider/tier returned, so a
    future provider swap or an un-set `thinking_budget` degrades to
    garbled-but-present text instead of a wall of base64.
    """
    content = message.content
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "".join(parts).strip()
    return str(content).strip()


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


def _preset_response(
    store,
    preset: dict,
    persona: AskPersona,
    session,
    question: str,
    history_source: HistorySource,
) -> AskResponse:
    """Answer a known chip question straight from the curated demo cache.

    No retrieval, no confidence gate, no generation call — for either
    persona — see `_PRESET_CACHE` for why. `preset["grounded"]` is `False`
    for a chip question the corpus genuinely doesn't answer; that
    case is routed to the same honest, hardcoded fallback text
    `_fallback_response` gives any other unanswerable question, still
    without touching retrieval. Otherwise, Baseline and Banter each read
    their own pre-drafted, corpus-verified field — `baseline_answer` /
    `banter_answer` — rather than one being generated from the other live;
    both were hand-drafted under the same "Banter never adds a new fact"
    rule `_BANTER_PROMPT` enforces at generation time.
    """
    if not preset.get("grounded", True):
        response = _fallback_response(
            persona, confidence=None, session_id=session.session_id, history_source=history_source
        )
        session.add_turn(ConversationRole.ASSISTANT, response.answer, persona=persona)
        return response

    final_answer = (
        preset["baseline_answer"] if persona == AskPersona.BASELINE else preset["banter_answer"]
    )
    source = ", ".join(preset.get("source") or []) or None

    session.add_turn(ConversationRole.ASSISTANT, final_answer, persona=persona, source=source)
    persist_grounded_exchange(
        store, session.session_id, session.turn_count, question, final_answer, persona, source
    )

    return AskResponse(
        answer=final_answer,
        persona=persona,
        grounded=True,
        confidence=None,
        source=source,
        session_id=session.session_id,
        history_source=history_source,
    )


def ask_cosmos(
    question: str,
    persona: AskPersona,
    humor: int,
    session_id: str | None = None,
    domain: Domain | None = None,
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

    `domain` restricts the main-answer retrieval to that `Domain` tag —
    conversational-history recall (above) is unaffected, since it's scoped
    by `session_id`, not subject matter. If the domain-scoped search comes
    back with literally nothing, or with a hit below
    `_CONFIDENCE_THRESHOLD` (an empty/misconfigured domain, or a stale
    domain filter pointing retrieval at the wrong slice of the corpus),
    retrieval retries once against the whole corpus rather than surfacing
    a false "no grounded answer" that would really just mean "nothing
    good tagged for this domain" — see `_retrieval_expr`. `None` searches
    the whole corpus directly, exactly as this function behaved before
    `domain` existed.
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

    preset = _PRESET_CACHE.get(question.strip().lower())
    if preset is not None:
        return _preset_response(store, preset, persona, session, question, history_source)

    hits = relevance_score_hits_or_empty(store, question, k=1, expr=_retrieval_expr(domain))
    if domain is not None:
        if not hits:
            hits = relevance_score_hits_or_empty(store, question, k=1, expr=_retrieval_expr(None))
        elif _retrieval_strength(hits[0][1]) < _CONFIDENCE_THRESHOLD:
            hits = relevance_score_hits_or_empty(store, question, k=1, expr=_retrieval_expr(None))
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
    baseline_answer = _message_text(baseline_message)

    if persona == AskPersona.BASELINE:
        final_answer = baseline_answer
    else:
        banter_prompt = _BANTER_PROMPT.format(
            humor=humor, humor_label=_humor_label(humor), baseline_answer=baseline_answer
        )
        banter_message = get_instruct_model().invoke(banter_prompt)
        final_answer = _message_text(banter_message)

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


def generate_baseline_draft(question: str, domain: Domain | None = None) -> dict:
    """Draft a Baseline answer for a new preset-cache entry — admin tool only.

    Runs the exact same retrieval + `_BASELINE_PROMPT` + `get_instruct_model()`
    path `ask_cosmos` uses for a live question (single best-matching
    `science_reference` chunk, same `_CONFIDENCE_THRESHOLD` gate, same
    domain-scoped-then-whole-corpus retry), so a drafted preset entry is
    grounded exactly as strictly as a live answer would be — including
    `get_instruct_model()`'s Granite -> watsonx-fallback -> Gemini-fallback
    chain. Carries no session/conversational-memory state, since a preset
    entry being drafted has no conversation. Returns `grounded: False` (with
    no `baseline_answer`/`source`) rather than raising when nothing clears
    the confidence bar, so the admin page can show that honestly and fall
    back to a hand-written answer instead.
    """
    store = get_vector_store()
    hits = relevance_score_hits_or_empty(store, question, k=1, expr=_retrieval_expr(domain))
    if domain is not None and (not hits or _retrieval_strength(hits[0][1]) < _CONFIDENCE_THRESHOLD):
        hits = relevance_score_hits_or_empty(store, question, k=1, expr=_retrieval_expr(None))
    if not hits:
        return {"grounded": False, "baseline_answer": None, "source": None, "confidence": None}

    chunk, relevance_score = hits[0]
    confidence = _retrieval_strength(relevance_score)
    if confidence < _CONFIDENCE_THRESHOLD:
        return {"grounded": False, "baseline_answer": None, "source": None, "confidence": confidence}

    baseline_prompt = _BASELINE_PROMPT.format(history="", passage=chunk.page_content, question=question)
    baseline_answer = _message_text(get_instruct_model().invoke(baseline_prompt))
    return {
        "grounded": True,
        "baseline_answer": baseline_answer,
        "source": _source_line(chunk.metadata),
        "confidence": confidence,
    }


def generate_banter_draft(baseline_answer: str, humor: int = 50) -> str:
    """Draft a Banter restyle of a (possibly hand-edited) Baseline answer.

    Admin tool only — same `_BANTER_PROMPT` and "restate, never add a new
    fact" contract `ask_cosmos` enforces live, including
    `get_instruct_model()`'s failover chain. The caller supplies
    `baseline_answer` directly (rather than this generating it from a fresh
    retrieval), matching how `preset_qa.json`'s existing `banter_answer`
    entries were hand-drafted as a restyle of their own `baseline_answer`.
    """
    banter_prompt = _BANTER_PROMPT.format(
        humor=humor, humor_label=_humor_label(humor), baseline_answer=baseline_answer
    )
    return _message_text(get_instruct_model().invoke(banter_prompt))


def reload_preset_cache() -> None:
    """Re-read `preset_qa.json` from disk into `_PRESET_CACHE`.

    Called by `app.services.preset_admin.append_preset_entry` after it
    writes a new entry to the file, so that entry is answerable by
    `POST /ask` immediately — no process restart needed.
    """
    global _PRESET_CACHE
    _PRESET_CACHE = _load_preset_cache()
