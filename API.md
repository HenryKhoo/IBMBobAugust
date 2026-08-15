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

Returns service status and which backend is active, `mock` or `watsonx`.

**Response**
```json
{
  "status": "ok",
  "backend": "mock"
}
```

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

Takes the live event feed for Module 01. Retrieves the matching emergency
procedure and returns a root cause with ordered response steps.

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
  "source": "string"
}
```

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
