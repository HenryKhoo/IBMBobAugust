"""Pydantic schemas for the C.O.S.M.O.S. API.

C.O.S.M.O.S. answers real space-science questions, grounded in the ingested
NASA SMD Q&A corpus — see `app.services.cosmos` for the engine and
`backend/scripts/fetch_cosmos_corpus.py` /
`backend/scripts/ingest_cosmos_corpus.py` for how that corpus gets in.

This is a deliberately small surface: `GET /health`, `POST /ingest`,
`POST /query` (raw passage search, for transparency), and `POST /ask`
(the actual product). Earlier iterations of this repo carried five
habitat-crisis-console endpoints (telemetry, crisis, triage, rationing)
built around a fictional deep-space-habitat scenario; those schemas were
removed in the revamp to a single-objective product rather than kept
around unused — see the project's `revamp/cosmos` branch history for
that decision.
"""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Response body for GET /health.

    `status` is `"ok"` only when every upstream credential C.O.S.M.O.S. needs
    to actually serve a request is configured, and `"degraded"` otherwise
    — derived from the same credential checks a real `/ask` or `/query`
    call would run (`missing_credentials()` in both service modules is the
    shared source of truth), so this can never disagree with what a real
    request would do. `missing_config` names the specific unset settings
    behind a `"degraded"` status. This checks configuration completeness,
    not live upstream reachability, so it stays cheap enough to poll.
    """

    status: str
    backend: str
    missing_config: list[str] = Field(default_factory=list)


class DocumentType(str, Enum):
    """Kinds of documents accepted by POST /ingest.

    A single member today (`science_reference`, the NASA SMD Q&A corpus
    C.O.S.M.O.S. is grounded in) — kept as an enum rather than inlined as a
    literal string so a second corpus can be added later without changing
    the request/response shape.
    """

    SCIENCE_REFERENCE = "science_reference"


class Domain(str, Enum):
    """Which subject-matter slice of the science_reference corpus a document
    or a question belongs to.

    This is a lightweight topical tag on top of the single existing corpus
    — not a second corpus, and not a return of the pre-revamp habitat
    mission-console module set (telemetry/crisis/triage/rationing) that
    was deliberately removed; see this module's own docstring. A user
    picks one of these before asking a question so the suggested chips and
    (optionally) retrieval itself are scoped to what they're actually
    interested in, instead of one undifferentiated question box.

    `OTHER` is a real, permanent bucket, not a placeholder for
    "unclassified" — every corpus document gets tagged into one of these
    five at ingestion time (see `backend/scripts/tag_corpus_domains.py`),
    and a document whose topic doesn't fit the four specific buckets
    belongs in `OTHER` on purpose, the same way a "no filter" question
    still needs a real, matchable domain if one is ever assigned to it.
    """

    TROPICAL_CYCLONE_DYNAMICS = "tropical_cyclone_dynamics"
    SAHARAN_DUST = "saharan_dust"
    CLIMATE_RECONSTRUCTION = "climate_reconstruction"
    ENVIRONMENTAL_HAZARDS = "environmental_hazards"
    OTHER = "other"


class MissionDocument(BaseModel):
    """A single raw document submitted for ingestion.

    `domain` defaults to `Domain.OTHER` so an existing /ingest caller that
    predates this field keeps working unchanged rather than being rejected
    for a now-required value it never knew to send.
    """

    id: str
    type: DocumentType
    text: str = Field(min_length=1)
    domain: Domain = Domain.OTHER


class IngestRequest(BaseModel):
    """Request body for POST /ingest."""

    documents: list[MissionDocument]


class IngestResponse(BaseModel):
    """Response body for POST /ingest."""

    chunks_ingested: int


class QueryRequest(BaseModel):
    """Request body for POST /query.

    `top_k` caps how many passages `app.services.query.run_query` returns.
    Bounded (`ge=1, le=20`) since this endpoint has no downstream
    generation step to keep a runaway value in check the way `/ask`'s
    single-chunk retrieval implicitly does.

    `domain` restricts retrieval to one `Domain` tag. `None` (the default)
    searches the whole corpus, exactly as this endpoint behaved before
    `domain` existed — see `app.services.query.run_query`.
    """

    question: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    domain: Domain | None = None


class QueryResult(BaseModel):
    """One retrieved passage in a POST /query response.

    `relevance` is the raw retrieval relevance score for this passage
    alone, clamped to `[0, 1]`. /query does no generation and blends in no
    second signal, so retrieval strength is the whole story here.
    """

    text: str
    source: str
    relevance: float


class QueryResponse(BaseModel):
    """Response body for POST /query.

    Exposed alongside /ask as a transparency tool — "see the actual source
    passages C.O.S.M.O.S.'s answers are grounded in" — not as C.O.S.M.O.S.'s main
    interface. `results` is ordered most-relevant-first. An empty list is a
    valid response (nothing in the corpus matches), not an error: unlike
    /ask, there's no generated claim here that would otherwise go
    ungrounded.
    """

    results: list[QueryResult]


class AskPersona(str, Enum):
    """Which voice answers a C.O.S.M.O.S. question.

    Persona changes only how a true thing is said, never whether it's
    said, or what it claims — see `app.services.cosmos` for how that's
    enforced structurally, not just by prompting convention.
    """

    BASELINE = "baseline"
    BANTER = "banter"


class ConversationRole(str, Enum):
    """Who said a given turn in a C.O.S.M.O.S. conversation.

    Only ever set by the server — `POST /ask` accepts a `session_id`, never
    a `role`, on the way in. Kept as a schema type rather than an inlined
    raw string so the wire shape and the in-process store
    (`app.services.memory`) can't drift into disagreeing about what values
    are valid.
    """

    USER = "user"
    ASSISTANT = "assistant"


class ConversationTurn(BaseModel):
    """One turn of a C.O.S.M.O.S. conversation, held in short-term session memory.

    `persona` and `source` are only ever set on an `ASSISTANT` turn — `None`
    on every `USER` turn, since a question has no persona or citation of its
    own, and `None` on an `ASSISTANT` turn that fell back to the honest
    no-match response, since there's no source to cite there either. This
    is the same information `AskResponse` already returns for a single
    answer, plus which side of the conversation said it. `app.services.memory`
    is what actually holds a list of these per session; this is a schema
    even though no endpoint returns a list of turns directly yet, so the
    shape has one definition shared by both.
    """

    role: ConversationRole
    content: str = Field(min_length=1)
    persona: AskPersona | None = None
    source: str | None = None


class HistorySource(str, Enum):
    """How a C.O.S.M.O.S. answer's conversational context was resolved.

    Orthogonal to `AskResponse.grounded`/`confidence`, which describe the
    *answer* — this describes the *question's* interpretation instead. The
    answer itself is always generated strictly from a freshly retrieved
    `science_reference` passage (see `app.services.cosmos`'s module
    docstring); history is never a source of facts, only of context for
    resolving a follow-up's pronouns and implicit subject.

    - `NONE`: no prior turns available — either the first question of a
      session, or an unrecognized `session_id` with nothing recoverable.
    - `SESSION_MEMORY`: resolved against the live, in-process sliding
      window (`app.services.memory.ConversationSession`) — the common
      case for an active, ongoing conversation.
    - `HISTORY_RETRIEVAL`: the in-process window was empty (an
      unrecognized or evicted `session_id`, or a fresh process after a
      restart) but grounded exchanges from earlier in that same session
      were recovered from Zilliz's long-term store instead. Recall is
      scoped to the caller's own `session_id` — never a cross-session
      search — so one visitor's questions never surface as context in
      another visitor's conversation.
    """

    NONE = "none"
    SESSION_MEMORY = "session_memory"
    HISTORY_RETRIEVAL = "history_retrieval"


class ConversationHistoryResponse(BaseModel):
    """Response body for GET /conversation/history.

    `turns` is ordered oldest-first, same as `ConversationTurn` everywhere
    else in this API. `source` reports where this transcript came from —
    see `HistorySource` — so a caller (the frontend's Conversation History
    panel) can tell "this is the live conversation" apart from "this is a
    resumed transcript recovered from long-term storage," and render an
    honest empty state when `source` is `NONE` rather than assuming a typo
    in the `session_id`.

    Only ever reflects grounded exchanges once a session's in-process
    memory is gone (see `app.services.memory.persist_grounded_exchange`) —
    a fallback "no grounded answer" turn is never written to long-term
    storage, so it will not reappear here after the live session expires,
    even though it *is* visible while the session is still in memory.
    """

    session_id: str
    turns: list[ConversationTurn]
    source: HistorySource


class AskRequest(BaseModel):
    """Request body for POST /ask.

    `humor` only affects `AskPersona.BANTER` — Baseline ignores it
    entirely, since Baseline has no humor dial to turn. Bounded `[0, 100]`
    to match the frontend's slider range.

    `session_id` is how a caller opts into conversational memory
    (`app.services.memory`): omit it on the first question, then send back
    whatever `AskResponse.session_id` returned on every follow-up. This
    lets a later question like "what does it eat?" resolve "it" against
    what was actually asked and answered before, without the caller
    re-stating the whole question. An unrecognized or expired `session_id`
    silently starts a fresh session under that id rather than erroring —
    see `app.services.memory.get_or_create_session`. Memory only ever
    changes what a follow-up question is understood to *mean*; it never
    supplies a fact — every answer is still generated strictly from
    whatever the current question retrieves, exactly as before this field
    existed.

    `domain` restricts retrieval to one `Domain` tag — see
    `app.services.cosmos.ask_cosmos` for the fallback that kicks in if
    that domain has nothing indexed at all. `None` (the default) searches
    the whole corpus, exactly as `/ask` behaved before `domain` existed.
    """

    question: str = Field(min_length=1)
    persona: AskPersona = AskPersona.BASELINE
    humor: int = Field(default=50, ge=0, le=100)
    session_id: str | None = None
    domain: Domain | None = None


class AskResponse(BaseModel):
    """Response body for POST /ask.

    `grounded` is `False` whenever `answer` is the honest no-match
    fallback rather than a generated, source-backed answer — the frontend
    uses this (not string-matching `answer`'s text) to decide whether to
    show a citation/confidence badge or the muted "no grounded answer"
    treatment. `confidence` is retrieval strength on the matched passage,
    `None` only when nothing was retrieved at all (an empty/uningested
    corpus) rather than a low-but-real score. `source` is `None` whenever
    `grounded` is `False`, and a real `doc_type:doc_id#chunkN` citation
    otherwise, same format the rest of this API's retrieval-backed
    responses use.

    `session_id` is always populated — server-generated (`uuid4`) when the
    request didn't send one, echoed back unchanged otherwise — telling the
    caller what to send on the next turn to keep continuity. A caller can
    never set an arbitrary conversation's identity from scratch this way;
    they can only ever hand back an id this API already issued.

    Never a 404: an unmatched question is a valid, honest response (see
    `app.services.cosmos.ask_cosmos`), not a failure to protect
    against generating an ungrounded guess — the protection already
    happened, that *is* what the fallback response is.

    `history_source` is always populated and reports how (if at all) prior
    turns shaped the interpretation of this question — see `HistorySource`.
    It is informational, not a trust signal: it never changes what
    `confidence` or `grounded` mean, since the answer itself is always
    generated fresh from a retrieved passage regardless of where the
    surrounding conversational context came from.
    """

    answer: str
    persona: AskPersona
    grounded: bool
    confidence: float | None = None
    source: str | None = None
    session_id: str
    history_source: HistorySource = HistorySource.NONE


class AdminGenerateBaselineRequest(BaseModel):
    """Request body for POST /admin/preset-qa/generate-baseline.

    Internal admin-tool endpoint (see `frontend/admin.html`), not part of
    C.O.S.M.O.S.'s public product surface — drafts a Baseline answer for a
    new curated preset-cache entry using the same retrieval path `POST
    /ask` uses live. `domain` is optional the same way it is on `AskRequest`.
    """

    question: str = Field(min_length=1)
    domain: Domain | None = None


class AdminGenerateBaselineResponse(BaseModel):
    """Response body for POST /admin/preset-qa/generate-baseline.

    `baseline_answer` is always populated — see
    `app.services.cosmos.generate_baseline_draft`. `source_type` is the
    load-bearing field: `"corpus"` means `baseline_answer` is grounded in a
    real retrieved passage (`source`/`grounded` describe that passage, the
    same as a live `/ask` answer would); `"general_knowledge"` means
    retrieval found nothing confident enough, so the model answered from
    its own general knowledge instead — `source` is then `None` and
    `grounded` is `False`. The admin page must not silently treat a
    `general_knowledge` draft the same as a `corpus` one — see
    `frontend/admin.html`'s acknowledgment checkbox.
    """

    grounded: bool
    source_type: Literal["corpus", "general_knowledge"]
    baseline_answer: str
    source: str | None = None
    confidence: float | None = None


class AdminGenerateBanterRequest(BaseModel):
    """Request body for POST /admin/preset-qa/generate-banter.

    `baseline_answer` is the (possibly hand-edited) text from the
    generate-baseline step — Banter is drafted as a restyle of it, never
    generated independently, matching the "Banter never adds a new fact"
    rule `POST /ask` enforces live. `humor` mirrors `AskRequest.humor`.
    """

    baseline_answer: str = Field(min_length=1)
    humor: int = Field(default=50, ge=0, le=100)


class AdminGenerateBanterResponse(BaseModel):
    """Response body for POST /admin/preset-qa/generate-banter."""

    banter_answer: str


class AdminAppendPresetRequest(BaseModel):
    """Request body for POST /admin/preset-qa.

    Appends one curated entry to `backend/data/preset_qa.json` in the same
    shape `app.services.cosmos._load_preset_cache` already expects, so it's
    answerable by `POST /ask` immediately — see
    `app.services.preset_admin.append_preset_entry`.

    `source_type` should echo whatever `AdminGenerateBaselineResponse.source_type`
    returned for this entry's Baseline answer (`"manual"` if the admin never
    called generate-baseline, e.g. because they typed both answers by hand).
    It controls the saved entry's `caveat`/`match_quality` fields, not
    whether the entry gets saved at all — the admin page is expected to
    gate the Save action itself for a `"general_knowledge"` draft (its
    acknowledgment checkbox), same as it always could for a manually typed
    answer the admin simply got wrong.
    """

    question: str = Field(min_length=1)
    domains: list[Domain] = Field(min_length=1)
    baseline_answer: str = Field(min_length=1)
    banter_answer: str = Field(min_length=1)
    source_type: Literal["corpus", "general_knowledge", "manual"] = "manual"


class AdminAppendPresetResponse(BaseModel):
    """Response body for POST /admin/preset-qa."""

    id: str
    question: str


class SpeakRequest(BaseModel):
    """Request body for POST /speak.

    `gender` pairs with the frontend's existing `state.companionGender`
    toggle (avatar + voice) — a misnomer now that "cat" is a third option
    alongside male/female, kept as-is rather than renamed to avoid
    rippling the field name through the frontend and `app.services.speechify`
    for a cosmetic fix. `persona` reuses
    `AskPersona` rather than a separate vocabulary — it's the *second* axis
    voice selection is keyed on (see `app.services.speechify`), since
    Banter now gets its own voice, not just its own text.
    """

    text: str = Field(min_length=1, max_length=2000)
    gender: Literal["male", "female", "cat"] = "female"
    persona: AskPersona = AskPersona.BASELINE


class SpeechMarkChunk(BaseModel):
    """One word-level timing entry from Speechify's speech marks.

    Drives the companion's mouth puppet off real word boundaries
    (`audio.currentTime` between `start_time`/`end_time`, in milliseconds)
    instead of the blind 150ms flap timer used for the Web Speech
    fallback — see `frontend/app.html`'s companion lip-sync section.
    """

    start_time: int
    end_time: int
    start: int
    end: int
    value: str


class SpeakResponse(BaseModel):
    """Response body for POST /speak.

    `audio_url` points at `GET /speak/audio/{filename}` on this same
    backend, not embedded base64/blob data — the deployed frontend's CSP
    (`media-src 'self' https: *`) rejects both `data:` and `blob:` URIs,
    so the frontend has to point `<audio>` at a real HTTP resource instead
    (see `app.services.audio_cache`). It's a path relative to the
    backend's own origin; a caller on a different origin (the frontend) is
    responsible for prefixing it with the backend's base URL. `speech_marks`
    is empty when Speechify's response didn't include usable timing data;
    the frontend degrades to its flap-timer lip sync in that case rather
    than failing to speak at all.
    """

    audio_url: str
    audio_format: str
    speech_marks: list[SpeechMarkChunk] = Field(default_factory=list)
