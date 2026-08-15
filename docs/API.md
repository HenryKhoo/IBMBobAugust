# API Contract — The North Star

Short-form endpoint reference for judges and contributors. The longer,
detailed version of this contract lives in `docs/API_CONTRACT.md`.

Base URL for local development: `http://localhost:8000`

Update this file, `backend/app/schemas.py`, and any frontend fetch calls
together whenever the contract changes.

## Endpoints

This version of the contract covers all seven endpoints, including the
Module 05 semantic search endpoint (`POST /query`).

### GET /health

Reports whether the service is actually able to serve requests.

`status` is `"ok"` only when every upstream credential the five module
endpoints need is configured, and `"degraded"` otherwise — with HTTP
`503` and the specific unset settings named in `missing_config`. It is
not a constant.

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

There is one backend, `watsonx`. An earlier version of this contract
listed `mock` as the alternative, but no mock provider was ever
implemented — `backend` echoed a `BACKEND_MODE` env var that nothing else
read, so a deployment with no credentials returned `{"status": "ok",
"backend": "mock"}` while all five module endpoints returned 500.
`BACKEND_MODE` has been removed.

This checks configuration completeness, not live upstream reachability —
it does not round-trip to watsonx or Zilliz, so it stays cheap to poll.
Credentials that are present but *invalid* still report `"ok"` here and
fail at the endpoint.

### POST /ingest

Ingests mission documents — emergency procedures, sector specifications,
crew medical files, and prior incident records. Chunks the text, embeds it
with Granite, and upserts it into Zilliz.

**Request**
```json
{
  "documents": [
    { "id": "string", "type": "procedure | sector_spec | crew_file | incident_record", "text": "string" }
  ]
}
```

**Response**
```json
{
  "chunks_ingested": 0
}
```

### POST /telemetry/interpret

Takes raw sector metrics for Module 02. Retrieves the matching sector
documentation and returns a plain language read on sector status.

**Request**
```json
{
  "sector_id": "string",
  "metrics": { "key": "value" }
}
```

**Response**
```json
{
  "summary": "string",
  "confidence": 0.0,
  "source": "string"
}
```

### POST /crisis/analyze

Takes the live event feed for Module 01. The feed can span more than one
concurrent failure point — events are grouped by `sector`, and one
procedure match is retrieved per distinct sector (capped at 4 per
request), rather than a single blended match for the whole feed. Returns
one synthesized root cause statement grounded across every matched
procedure, plus the merged, ordered response steps.

**Request**
```json
{
  "events": [
    { "timestamp": "string", "sector": "string", "description": "string" }
  ]
}
```

**Response**
```json
{
  "root_cause": "string",
  "steps": ["string"],
  "step_counts": [0],
  "sources": ["string"],
  "contributing_causes": ["string"]
}
```

`sources` carries one citation line per matched procedure document. For a
feed with a single failure point (the default demo scenario), this is
always a length-1 list — the same shape as before this endpoint supported
compound scenarios, just pluralized. `step_counts` gives, in the same
order as `sources`, how many of the concatenated `steps` came from each
matched sector — `steps` itself stays one flat, continuously-ordered list
so step-index-based UI state (which steps are checked off, out-of-order
detection) doesn't need to change shape for a compound response.
`contributing_causes` pairs each source with the sector it was retrieved
for (`"{sector}: {source line}"`), a deterministic label rather than model
output, so a caller can group or label a compound checklist by which
failure point each step and citation came from.

A sector in the feed that matches no procedure documentation is dropped
rather than failing the whole request — this endpoint 404s only if *no*
sector in the feed matched anything at all, so a compound feed where only
some of the concurrent failures have ingested procedure docs still
returns a grounded (if partial) response for the ones that do.

### POST /triage

Takes a crew member id and a plain English symptom report for Module 03.
Retrieves crew file data and protocol documents, and returns a grounded
triage recommendation.

**Request**
```json
{
  "crew_member_id": "string",
  "symptom_report": "string"
}
```

**Response**
```json
{
  "triage_lead": "string",
  "instructions": ["string"],
  "allergy_check": "string",
  "confidence": 0.0,
  "source": "string"
}
```

`source` cites both retrieved documents (crew file and treatment protocol),
separated by `"; "` — the only endpoint here grounded in two documents
rather than one.

### POST /rationing/simulate

Takes stock level, ration amount, and days until resupply for Module 04.
Returns a rationing narrative and a survival probability.

**Request**
```json
{
  "stock_level": 0,
  "ration_amount": 0,
  "days_until_resupply": 0
}
```

**Response**
```json
{
  "narrative": "string",
  "survival_probability": 0.0,
  "source": "string"
}
```

### POST /query

Optional Module 05. Takes a natural language question for the mission log
search widget. Searches the full embedded mission document corpus in
Zilliz — no document-type filter, unlike the other five endpoints above —
and returns the best-matching passages with source references. Unlike
every other endpoint here, this one does no generation: the retrieved
passages are the answer, so an empty `results` list is a valid response
rather than a 404.

**Request**
```json
{
  "question": "string",
  "top_k": 5
}
```

`top_k` is optional (default `5`, max `20`).

**Response**
```json
{
  "results": [
    { "text": "string", "source": "string", "relevance": 0.0 }
  ]
}
```

## Conventions

Every response is grounded in retrieved documents, never a hand-written
guess. Confidence values are derived from real signals, such as retrieval
strength or distance from a nominal band, not random numbers. Every
endpoint that generates a claim carries a source reference line back to the
document it came from. `POST /query` is the one exception to "generates a
claim": it returns retrieved passages verbatim rather than generating
anything, so its `relevance` field is a retrieval strength score, not a
generation confidence score.
