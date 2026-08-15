"""Grounded generation for POST /rationing/simulate.

Takes Module 04's rationing inputs — stock on hand, the per-person daily
ration, and the days until resupply — retrieves the supply/rationing
procedure chunk that best matches that scenario, and asks the instruct
model for a short narrative grounded in that chunk plus the computed
rationing state. Nothing here fabricates a fact: if retrieval finds no
matching procedure documentation, this module refuses to generate a
narrative rather than let the model guess (see `simulate_rationing`), the
same no-hallucination discipline `app.services.telemetry`/`crisis`/`triage`
follow.

`survival_probability` is the one part of this endpoint that isn't
retrieval-grounded at all — dev plan Aug 22 Task 1 asks for it to be
"compute[d]...from stock, ration, and days," and `API.md` gives this
endpoint no `confidence` field the way telemetry/triage have. It's pure
arithmetic (see `_survival_probability`), a direct port of
`mission-console.html`'s existing `computeSurvivalProbability` JS function,
not a model output and not a retrieval-strength score.

`API.md`'s request (`stock_level`, `ration_amount`, `days_until_resupply`)
has no `crew_size` field, but the frontend's formula this is ported from
needs one to turn a per-person ration into a daily burn against total
stock. `CREW_SIZE` below hardcodes the same assumption the frontend
currently hardcodes (`crewSize = 4` in `mission-console.html`) — see this
module's and the day-22 plan's notes on that being a judgment call, not
something the API contract itself carries.
"""

from __future__ import annotations

import math

from app.schemas import RationingSimulateResponse
from app.services.vector_store import get_vector_store
from app.services.watsonx import get_instruct_model

# Matches mission-console.html's hardcoded `var crewSize = 4;`. Not part of
# the API contract (see module docstring) — kept as a single named constant
# so it's easy to find and update if the frontend's crew size ever changes.
CREW_SIZE = 4

_PROMPT_TEMPLATE = """You are the rationing simulator for The North Star, a deep space \
habitat's mission console. You turn a supply-shortfall scenario into a short, \
plain-language rationing narrative and recommendation for the crew.

Base your narrative strictly on the rationing/supply procedure documentation and the \
computed rationing state below. Do not invent facts, thresholds, or recommendations \
that are not supported by this documentation or the arithmetic given. State plainly \
whether the stock is projected to run out before resupply, and hold to the modeled \
survival probability given below rather than restating or re-deriving your own number. \
Keep the narrative to two or three sentences.

Rationing/supply procedure documentation:
{chunk_text}

Stock on hand: {stock_level} kcal
Ration: {ration_amount} kcal per person per day (crew of {crew_size})
Days until resupply: {days_until_resupply}
Projected buffer at resupply: {buffer} kcal
Modeled survival probability: {survival_probability}

Rationing narrative:"""


def _build_retrieval_query(
    stock_level: float, ration_amount: float, days_until_resupply: int
) -> str:
    """Build the text used to semantically match rationing/supply documentation.

    Like `telemetry`/`crisis`'s retrieval queries, procedure chunks carry no
    scenario-specific metadata (see `app.services.ingestion.Chunk.metadata`)
    — they're free text tagged only with `doc_id`/`doc_type`/`chunk_index`.
    So "the matching rationing procedure" is found by similarity between
    this query text and the embedded documentation, not by an exact
    metadata match.
    """
    return (
        f"Supply rationing scenario: {stock_level} kcal on hand, "
        f"{ration_amount} kcal per person per day ration, "
        f"{days_until_resupply} days until resupply."
    )


def _build_prompt(
    chunk_text: str,
    stock_level: float,
    ration_amount: float,
    days_until_resupply: int,
    buffer: float,
    survival_probability: float,
) -> str:
    return _PROMPT_TEMPLATE.format(
        chunk_text=chunk_text,
        stock_level=stock_level,
        ration_amount=ration_amount,
        crew_size=CREW_SIZE,
        days_until_resupply=days_until_resupply,
        buffer=buffer,
        survival_probability=survival_probability,
    )


def _source_line(metadata: dict) -> str:
    return f"{metadata['doc_type']}:{metadata['doc_id']}#chunk{metadata['chunk_index']}"


def _survival_probability(ration_amount: float, buffer: float, daily_burn: float) -> float:
    """Compute a survival probability from the ration level and projected buffer.

    A direct port of `mission-console.html`'s `computeSurvivalProbability`,
    kept on that function's original 0-100 scale rather than the `[0, 1]`
    scale `confidence` uses elsewhere in this API (see
    `RationingSimulateResponse`'s docstring for why).

    Base probability comes from the per-person ration tier alone: 99 at
    2000+ kcal/day, 95 at 1800+, 85 at 1500+, 65 at 1200+, 40 below that —
    the same breakpoints the frontend's slider range (1200-2500) was tuned
    against. If the projected buffer at resupply is non-negative (stock
    lasts the full window), that base is returned unchanged. If stock runs
    out before resupply, the base is overridden by a penalty that scales
    with how many days early the stock-out hits (`shortfall_days * 4`),
    clamped to `[5, 60]` — a ration that's merely tight but doesn't run out
    still returns its full base probability; only running out early caps
    it, and less catastrophically the closer the shortfall is to zero.
    """
    if ration_amount >= 2000:
        base = 99.0
    elif ration_amount >= 1800:
        base = 95.0
    elif ration_amount >= 1500:
        base = 85.0
    elif ration_amount >= 1200:
        base = 65.0
    else:
        base = 40.0

    if buffer >= 0:
        return base

    shortfall_days = math.ceil(abs(buffer) / daily_burn) if daily_burn > 0 else 1
    return float(max(5, min(60, base - shortfall_days * 4)))


def simulate_rationing(
    stock_level: float, ration_amount: float, days_until_resupply: int
) -> RationingSimulateResponse:
    """Retrieve the matching rationing procedure and generate a grounded narrative.

    Raises `LookupError` if no `procedure` documentation is found for this
    scenario — callers (see `app.main`) should map that to a 404 rather
    than fall back to an ungrounded narrative. `survival_probability` is
    computed deterministically from the three request values (see
    `_survival_probability`); it does not depend on retrieval at all, but
    stays inside this function so the response is only ever built once
    grounding has succeeded, matching how every other module in this
    codebase never generates a response without a grounding chunk.
    """
    query = _build_retrieval_query(stock_level, ration_amount, days_until_resupply)
    hits = get_vector_store().similarity_search(query, k=1, expr="doc_type == 'procedure'")
    if not hits:
        raise LookupError(
            "No rationing or supply procedure documentation found matching this "
            "scenario. Ingest procedure documents via POST /ingest first."
        )

    chunk = hits[0]
    daily_burn = ration_amount * CREW_SIZE
    buffer = stock_level - daily_burn * days_until_resupply
    survival_probability = _survival_probability(ration_amount, buffer, daily_burn)

    prompt = _build_prompt(
        chunk.page_content,
        stock_level,
        ration_amount,
        days_until_resupply,
        buffer,
        survival_probability,
    )
    message = get_instruct_model().invoke(prompt)
    narrative = str(message.content).strip()

    return RationingSimulateResponse(
        narrative=narrative,
        survival_probability=survival_probability,
        source=_source_line(chunk.metadata),
    )
