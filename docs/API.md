# API Contract — ChortleChat

Short-form endpoint reference for judges and contributors.

Base URL for local development: `http://localhost:8000`

Update this file, `backend/app/schemas.py`, and any frontend fetch calls
together whenever the contract changes.

## Endpoints

Six endpoints: `GET /health`, `POST /ingest`, `POST /query`, `POST /ask`,
`GET /conversation/history`, and `POST /speak`.

### GET /health

Reports whether the service is actually able to serve requests.

`status` is `"ok"` only when every watsonx/Zilliz credential `/ask` and
`/query` need is configured, and `"degraded"` otherwise — with HTTP `503`
and the specific unset settings named in `missing_config`.

**Response — healthy (HTTP 200)**
```json
{
  "status": "ok",
  "backend": "watsonx",
  "missing_config": []
}
```

**Response — misconfigured (HTTP 503)**
```json
{
  "status": "degraded",
  "backend": "watsonx",
  "missing_config": ["ZILLIZ_URI", "ZILLIZ_TOKEN"]
}
```

This checks configuration completeness, not live upstream reachability —
it does not round-trip to watsonx or Zilliz, so it stays cheap to poll.
Credentials that are present but *invalid* still report `"ok"` here and
fail at the endpoint.

### POST /ingest

Chunks, embeds with Granite, and upserts documents into Zilliz. Today the
only accepted `type` is `science_reference` (the NASA SMD Q&A corpus
ChortleChat is grounded in — see `backend/scripts/fetch_chortlechat_corpus.py`
and `backend/scripts/ingest_chortlechat_corpus.py` for the dev-time path that
already populates this).

**Request**
```json
{
  "documents": [
    { "id": "string", "type": "science_reference", "text": "string", "domain": "other" }
  ]
}
```

`domain` is optional per document, defaulting to `"other"` — see "Mission-based domains" below. Existing callers that predate `domain` keep working unchanged.

**Response**
```json
{
  "chunks_ingested": 0
}
```

### POST /query

Retrieval only, no generation — a transparency tool alongside `/ask` for
inspecting the actual source passages a question matches, not ChortleChat's
main interface. Searches the full ingested corpus with no `doc_type`
filter and returns the best-matching passages with source references. An
empty `results` list is a valid response (nothing in the corpus matches),
not an error — there's no generated claim here that would otherwise go
ungrounded.

**Request**
```json
{
  "question": "string",
  "top_k": 5,
  "domain": "tropical_cyclone_dynamics | saharan_dust | climate_reconstruction | environmental_hazards | other | null"
}
```

`top_k` is optional (default `5`, max `20`). `domain` is optional — see
"Mission-based domains" below; `null`/omitted searches the whole corpus,
exactly as this endpoint behaved before `domain` existed.

**Response**
```json
{
  "results": [
    { "text": "string", "source": "string", "relevance": 0.0 }
  ]
}
```

### POST /ask

The main Q&A endpoint. Retrieves the single best-matching
`science_reference` passage and, above a confidence threshold, generates a
grounded answer exactly once (always in Baseline's voice); Banter re-tells
that already-generated, already-grounded answer in its own tone rather
than answering the question itself. Below threshold, or with nothing
ingested yet, both personas return an honest no-match response instead of
guessing. Never 404s — an unmatched question is a valid response, not a
failure.

**Request**
```json
{
  "question": "string",
  "persona": "baseline | banter",
  "humor": 50,
  "session_id": "string | null",
  "domain": "tropical_cyclone_dynamics | saharan_dust | climate_reconstruction | environmental_hazards | other | null"
}
```

`persona` defaults to `baseline`; `humor` (0–100) is only used by Banter.
`session_id` is optional — omit it on the first question of a
conversation, then send back whatever the previous response's
`session_id` was on every follow-up. See "Conversational memory" below.
`domain` is optional — see "Mission-based domains" below; `null`/omitted
searches the whole corpus, exactly as this endpoint behaved before
`domain` existed.

**Response**
```json
{
  "answer": "string",
  "persona": "baseline | banter",
  "grounded": true,
  "confidence": 0.0,
  "source": "string | null",
  "session_id": "string",
  "history_source": "none | session_memory | history_retrieval"
}
```

`session_id` is always populated — server-generated when the request
didn't send one, echoed back unchanged otherwise. `confidence` and
`source` are `null` whenever `grounded` is `false`. `history_source`
reports how (if at all) prior turns shaped the interpretation of this
question — see "Conversational memory" below; it is informational only
and never changes what `confidence`/`grounded` mean, since the answer
itself is always generated fresh from a retrieved passage regardless of
where the surrounding context came from.

### GET /conversation/history

Returns the transcript for one conversation, for a Conversation History
browse panel. Never 404s: an unrecognized `session_id` — mistyped,
expired, or simply never issued — returns an empty `turns` list with
`source: "none"` rather than an error.

**Request** — query parameter

```
GET /conversation/history?session_id=string
```

**Response**
```json
{
  "session_id": "string",
  "turns": [
    { "role": "user | assistant", "content": "string", "persona": "baseline | banter | null", "source": "string | null" }
  ],
  "source": "none | session_memory | history_retrieval"
}
```

`turns` is ordered oldest-first. `persona`/`source` are only ever set on
an `assistant` turn. See "Conversational memory" below for what `source`
means and its limitations.

### POST /speak

Voices a companion answer via Speechify's TTS API, when configured — an
additive, optional feature layered on top of the actual product, not a
required credential like watsonx/Zilliz. Holds `SPEECHIFY_API_KEY`
server-side; the frontend never talks to Speechify directly.

**Request**
```json
{
  "text": "string",
  "gender": "male | female | cat",
  "persona": "baseline | banter"
}
```

`gender` pairs with the companion's existing avatar/voice toggle.
`persona` picks a *different voice*, not just different text — Banter has
its own voice pair from Baseline's, so the two personas actually sound
different (see "Companion voice" below).

**Response — HTTP 200**
```json
{
  "audio_url": "/speak/audio/<id>.mp3",
  "audio_format": "mp3",
  "speech_marks": [
    { "start_time": 0, "end_time": 200, "start": 0, "end": 4, "value": "string" }
  ]
}
```

`audio_url` is a path on this same backend (`GET /speak/audio/{filename}`)
serving the generated clip, cached on disk for a short time — a real HTTP
resource rather than embedded base64/blob data, since a `data:`/`blob:`
URL is rejected by the deployed frontend's CSP (`media-src 'self' https:
*`). Prefix it with the backend's base URL before assigning it to an
`<audio>` element on a different origin. `speech_marks` is word-level
timing (milliseconds) used to drive the companion's mouth puppet off real
word boundaries instead of a fixed timer; it's an empty list when
Speechify's response didn't include usable timing data.

**Response — not configured (HTTP 503)** or **Speechify failed (HTTP 502)**
```json
{ "detail": "string" }
```

503 means `SPEECHIFY_API_KEY` or the requested persona/gender's voice ID
is unset; 502 means the request reached Speechify and Speechify itself
rejected or failed it (bad key, exhausted quota, etc). The frontend treats
both the same way — fall back to the browser's own `SpeechSynthesis` API —
but the distinction matters for diagnosing a deployment. Deliberately not
folded into `GET /health`'s `missing_config`: see that section above.

## Conversational memory

`/ask` is stateful across calls that share a `session_id`, in two layers:

- **Short-term session memory** — an in-process sliding window of the most
  recent turns for that `session_id`, replayed into the next prompt as
  context so a follow-up ("what does it eat?") can be understood without
  restating the whole question. Fast and exact, but doesn't survive a
  server restart and is capped to the last few turns.
- **Long-term history** — once an exchange is grounded, it's additionally
  persisted to Zilliz, tagged with that same `session_id`. This is what
  lets a conversation's context survive a restart, an evicted in-process
  session, or a window that's trimmed the earlier turns away: if the
  short-term window is empty for a `session_id` a caller sends, `/ask`
  falls back to searching this session's own long-term history instead. A
  fallback "no grounded answer" turn is never persisted here — only
  grounded exchanges are recallable later.

Recall is always scoped to the caller's own `session_id` — never a
cross-session search — so one visitor's questions can never surface as
context in another visitor's conversation. Either way, memory only ever
shapes what a question is *interpreted to mean*; it is never a source of
facts and never substitutes for the current question's own retrieval — see
the grounding discipline under "Conventions" below, which is otherwise
completely unaffected by any of this.

## Mission-based domains

A lightweight topical tag on the single existing `science_reference`
corpus — not a second corpus, and not a return of the pre-revamp habitat
mission-console module set (telemetry/crisis/triage/rationing) that was
deliberately removed from this API; see `app/schemas.py`'s module
docstring. The five `Domain` values are `tropical_cyclone_dynamics`,
`saharan_dust`, `climate_reconstruction`, `environmental_hazards`, and
`other`. `other` is a real, permanent bucket for topics that don't fit
the four specific ones, not a placeholder for "unclassified" — every
ingested document gets tagged into one of the five (see
`backend/scripts/tag_corpus_domains.py`).

A user picks a domain in the console before asking a question so the
suggested chips — and, if a domain is set, retrieval itself — are scoped
to what they're actually interested in. `domain` on `/ask`/`/query`
restricts the main-answer or passage search to documents tagged with that
value; conversational-history recall on `/ask` is unaffected, since it's
scoped by `session_id`, not subject matter.

If a domain-scoped search on `/ask` comes back with literally nothing —
an empty or misconfigured domain, not just a weak match — it retries once
against the whole corpus rather than surfacing a false "no grounded
answer" that would really just mean "nothing tagged for this domain." A
domain search that does find something, even below the confidence
threshold, is a real "no grounded answer in this domain" and is not
retried.

## Companion voice

`POST /speak` voices a companion answer with Speechify when
`SPEECHIFY_API_KEY` and the requested persona/gender's voice ID are
configured; otherwise (including a `.env` that never sets
`SPEECHIFY_API_KEY` at all) the frontend falls back to the browser's own
`SpeechSynthesis` API, exactly how this companion behaved before Speechify
integration existed. This is deliberate degrade-safe behavior, not an
error state — the companion should never go silent just because a
month's free-tier character quota (50,000/month) is exhausted or the
credential was never set up.

Voice selection is keyed on **both** `gender` (male/female/cat) and
`persona`, via five separate `SPEECHIFY_VOICE_ID_*` settings. For male and
female, Banter gets its own voice, distinct from Baseline's, so the two
personas actually sound different and not just read different (jokier)
text. That Banter voice is chosen to be a stock catalog voice with a
laid-back, energetic delivery, not a licensed celebrity voice: Speechify's
celebrity voices (e.g. its Snoop Dogg voice) are a feature of its consumer
reading app only, absent from every tier of the developer API this backend
calls, and cloning a real person's voice without consent is a rights
problem independent of which product does the cloning.

Cat is the exception: one voice (`SPEECHIFY_VOICE_ID_CAT`), not a pair.
Persona is instead expressed by dynamically pitch/rate-shifting that same
voice at call time via SSML — Banter gets `<prosody pitch="+10%"
rate="+12%">` wrapped around the answer text for a bright, quick "humour
voice"; Baseline gets the same voice with plain, unwrapped text (Speechify's
own default medium/medium prosody) for a flat, deadpan delivery. This
avoids sourcing and auditioning a second "playful" cat voice from the
catalog sight unseen — see `app.services.speechify._cat_banter_input`.
Speechify's `<prosody>` tag only accepts keyword (`x-slow`..`x-fast`) or
percentage values, not the multiplier/semitone syntax some other TTS APIs
use.

## Conventions

Every generated answer is grounded in a retrieved document, never a
hand-written guess. Confidence values are derived from real signals (retrieval
strength), not random numbers. Every endpoint that generates a claim
carries a source reference line back to the document it came from.
`POST /query` is the one exception to "generates a claim": it returns
retrieved passages verbatim rather than generating anything, so its
`relevance` field is a retrieval strength score, not a generation
confidence score.
