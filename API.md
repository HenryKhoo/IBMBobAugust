# API Contract — The North Star

Short-form endpoint reference for judges and contributors. The longer,
detailed version of this contract lives in `docs/API_CONTRACT.md`.

Base URL for local development: `http://localhost:8000`

Update this file, `backend/app/schemas.py`, and any frontend fetch calls
together whenever the contract changes.

## Endpoints

This version of the contract covers the six core endpoints. The optional
Module 05 semantic search endpoint (`POST /query`) is added later and
documented once it exists.

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
with Granite, and upserts it into Pinecone.

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
  "confidence": 0.0
}
```

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

## Conventions

Every response is grounded in retrieved documents, never a hand-written
guess. Confidence values are derived from real signals, such as retrieval
strength or distance from a nominal band, not random numbers. Every
endpoint that generates a claim carries a source reference line back to the
document it came from.
