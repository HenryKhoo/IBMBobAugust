"""Dev-time ingest: backend/data/talkback_corpus.json -> Zilliz.

Run once, from the repo root, with the venv active and .env configured
with real WATSONX_*/ZILLIZ_* credentials (this hits both live services):

    python backend/scripts/ingest_talkback_corpus.py

Reads the flattened corpus fetch_talkback_corpus.py produced, builds one
MissionDocument (doc_type=science_reference) per entry, and calls the
same chunk-embed-upsert pipeline POST /ingest uses -- this script exists
so ingestion can happen once, at dev time, without needing the FastAPI
server running.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Make `app.*` importable regardless of the working directory this is run
# from (repo root, backend/, or backend/scripts/).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.schemas import DocumentType, MissionDocument  # noqa: E402
from app.services.ingestion import ingest_and_upsert  # noqa: E402

CORPUS_PATH = Path(__file__).resolve().parent.parent / "data" / "talkback_corpus.json"


def main() -> None:
    if not CORPUS_PATH.exists():
        raise SystemExit(
            f"{CORPUS_PATH} not found. Run "
            "backend/scripts/fetch_talkback_corpus.py first."
        )

    raw_documents = json.loads(CORPUS_PATH.read_text())
    documents = [
        MissionDocument(id=entry["id"], type=DocumentType.SCIENCE_REFERENCE, text=entry["text"])
        for entry in raw_documents
    ]
    print(f"Ingesting {len(documents)} science_reference documents into Zilliz...")

    chunks_ingested = ingest_and_upsert(documents)
    print(f"Done. {chunks_ingested} chunks embedded and upserted.")


if __name__ == "__main__":
    main()
