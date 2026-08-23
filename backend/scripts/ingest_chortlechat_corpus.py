"""Dev-time ingest: backend/data/chortlechat_corpus.json -> Zilliz.

Run once, from the repo root, with the venv active and .env configured
with real WATSONX_*/ZILLIZ_* credentials (this hits both live services):

    python backend/scripts/ingest_chortlechat_corpus.py

Reads the flattened corpus fetch_chortlechat_corpus.py produced, builds one
MissionDocument (doc_type=science_reference) per entry, and calls the
same chunk-embed-upsert pipeline POST /ingest uses -- this script exists
so ingestion can happen once, at dev time, without needing the FastAPI
server running.

Run backend/scripts/tag_corpus_domains.py first (or after re-fetching the
corpus) if you want mission-based domain filtering to actually have
something to match against -- this script reads whatever `domain` each
entry already has (defaulting to "other" if that step hasn't been run
yet) rather than computing it itself.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make `app.*` importable regardless of the working directory this is run
# from (repo root, backend/, or backend/scripts/).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.schemas import Domain, DocumentType, MissionDocument  # noqa: E402
from app.services.ingestion import ingest_and_upsert  # noqa: E402

CORPUS_PATH = Path(__file__).resolve().parent.parent / "data" / "chortlechat_corpus.json"


def main() -> None:
    if not CORPUS_PATH.exists():
        raise SystemExit(
            f"{CORPUS_PATH} not found. Run "
            "backend/scripts/fetch_chortlechat_corpus.py first."
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
    print(f"Ingesting {len(documents)} science_reference documents into Zilliz...")

    chunks_ingested = ingest_and_upsert(documents)
    print(f"Done. {chunks_ingested} chunks embedded and upserted.")


if __name__ == "__main__":
    main()
