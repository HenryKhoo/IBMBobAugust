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
"""

from __future__ import annotations

from app.schemas import AskPersona, AskResponse
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


def _retrieval_strength(relevance_score: float) -> float:
    """Normalize a retrieval relevance score to a [0, 1] confidence signal.

    Same clamp-and-round `app.services.query._relevance` applies, for the
    same reason: `similarity_search_with_relevance_scores` normalizes to
    `[0, 1]` but its own base implementation only warns, never clamps,
    when a score lands outside that range regardless.
    """
    return round(max(0.0, min(1.0, relevance_score)), 2)


def _fallback_response(persona: AskPersona, confidence: float | None) -> AskResponse:
    return AskResponse(
        answer=_FALLBACK_BASELINE if persona == AskPersona.BASELINE else _FALLBACK_BANTER,
        persona=persona,
        grounded=False,
        confidence=confidence,
        source=None,
    )


def ask_talkback(question: str, persona: AskPersona, humor: int) -> AskResponse:
    """Answer a space-science question, grounded in the ingested corpus.

    Retrieves the single best-matching `science_reference` chunk. With
    nothing ingested yet, or a match below `_CONFIDENCE_THRESHOLD`, both
    personas return an honest no-match response rather than let the model
    guess — see the module docstring. Above threshold, the grounded answer
    is generated exactly once, always in Baseline's voice; Banter re-styles
    that finished, already-true answer rather than generating its own, so
    the humor dial can never change what is actually claimed.
    """
    hits = relevance_score_hits_or_empty(
        get_vector_store(), question, k=1, expr="doc_type == 'science_reference'"
    )
    if not hits:
        return _fallback_response(persona, confidence=None)

    chunk, relevance_score = hits[0]
    confidence = _retrieval_strength(relevance_score)
    if confidence < _CONFIDENCE_THRESHOLD:
        return _fallback_response(persona, confidence=confidence)

    baseline_prompt = _BASELINE_PROMPT.format(passage=chunk.page_content, question=question)
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

    return AskResponse(
        answer=final_answer,
        persona=persona,
        grounded=True,
        confidence=confidence,
        source=_source_line(chunk.metadata),
    )
