"""Dev-time ingest: backend/data/cosmos_corpus.json -> Zilliz.

Run once, from the repo root, with the venv active and .env configured
with real WATSONX_*/ZILLIZ_* (and, on the Gemini embedding path,
GEMINI_API_KEY) credentials (this hits live services):

    python backend/scripts/ingest_cosmos_corpus.py

Reads the flattened corpus fetch_cosmos_corpus.py produced, builds one
MissionDocument (doc_type=science_reference) per entry, chunks it exactly
the way POST /ingest does (`app.services.ingestion.chunk_documents`), then
upserts those chunks into Zilliz in paced batches — see `_DOC_BATCH_SIZE`
and `_GEMINI_BATCH_PAUSE_SECONDS` below for why this doesn't just call
`ingest_and_upsert(documents)` in one shot the way it used to.

Run backend/scripts/tag_corpus_domains.py first (or after re-fetching the
corpus) if you want mission-based domain filtering to actually have
something to match against -- this script reads whatever `domain` each
entry already has (defaulting to "other" if that step hasn't been run
yet) rather than computing it itself.

If a previous run of this script was interrupted partway through (e.g. hit
the Gemini rate limit below), run backend/scripts/reset_zilliz_collection.py
first — Zilliz inserts use auto_id, so there's no dedup on a retry; a
partial collection plus a fresh full ingest on top just produces duplicate
chunks for whatever got in before the interruption.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# Make `app.*` importable regardless of the working directory this is run
# from (repo root, backend/, or backend/scripts/).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.schemas import Domain, DocumentType, MissionDocument  # noqa: E402
from app.services.ingestion import chunk_documents  # noqa: E402
from app.services.vector_store import upsert_chunks  # noqa: E402
from app.services.watsonx import using_gemini_embeddings  # noqa: E402

CORPUS_PATH = Path(__file__).resolve().parent.parent / "data" / "cosmos_corpus.json"

# Gemini's free tier caps embed_content at 100 requests/minute (see
# .env.example's Gemini section) — sending the whole corpus's chunks in one
# burst trips it partway through (a real run against 91 documents / ~200
# chunks hit this on 2026-08-26). Splitting the DOCUMENT list into small
# groups and pausing between groups, rather than trying to guess exactly
# how many embedding requests each group turns into internally, is what
# actually keeps this under the limit regardless of langchain_google_genai's
# own internal request batching. Watsonx has no equivalent published
# per-minute cap here, so this pacing only applies on the Gemini path (see
# `using_gemini_embeddings()` below) — a watsonx-only run still ingests in
# one shot, exactly as before this existed.
_DOC_BATCH_SIZE = 20
_GEMINI_BATCH_PAUSE_SECONDS = 70


def main() -> None:
    if not CORPUS_PATH.exists():
        raise SystemExit(
            f"{CORPUS_PATH} not found. Run "
            "backend/scripts/fetch_cosmos_corpus.py first."
        )

    raw_documents = json.loads(CORPUS_PATH.read_text())
    # `.get("domain", "other")` rather than a required key: this script also
    # has to work against a corpus file from before mission-based domains
    # existed (or before backend/scripts/tag_corpus_domains.py has been run
    # on a freshly re-fetched one), where no document has a `domain` key at
    # all — those ingest as Domain.OTHER, same as MissionDocument's own
    # default, rather than failing the whole run.
    documents = [
        MissionDocument(
            id=entry["id"],
            type=DocumentType.SCIENCE_REFERENCE,
            text=entry["text"],
            domain=Domain(entry.get("domain", Domain.OTHER.value)),
        )
        for entry in raw_documents
    ]
    paced = using_gemini_embeddings()
    print(
        f"Ingesting {len(documents)} science_reference documents into Zilliz"
        + (f" ({_DOC_BATCH_SIZE} docs/batch, {_GEMINI_BATCH_PAUSE_SECONDS}s between batches — Gemini free-tier pacing)..." if paced else "...")
    )

    total_chunks = 0
    doc_batches = [
        documents[i : i + _DOC_BATCH_SIZE] for i in range(0, len(documents), _DOC_BATCH_SIZE)
    ] if paced else [documents]

    for batch_index, doc_batch in enumerate(doc_batches, start=1):
        chunks = chunk_documents(doc_batch)
        if chunks:
            texts = [chunk.text for chunk in chunks]
            metadatas = [chunk.metadata() for chunk in chunks]
            total_chunks += upsert_chunks(texts, metadatas)
        if paced:
            print(
                f"  batch {batch_index}/{len(doc_batches)}: {len(doc_batch)} docs, "
                f"{len(chunks)} chunks — {total_chunks} total so far"
            )
            if batch_index < len(doc_batches):
                time.sleep(_GEMINI_BATCH_PAUSE_SECONDS)

    print(f"Done. {total_chunks} chunks embedded and upserted.")


if __name__ == "__main__":
    main()
