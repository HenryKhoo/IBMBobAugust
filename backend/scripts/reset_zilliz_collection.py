"""One-time fix-up: drop the Zilliz collection so it gets recreated with
the COSINE metric type (see the comment on `vector_store._INDEX_PARAMS`).

Only needed if ZILLIZ_COLLECTION_NAME already has data ingested under the
old default (no explicit index_params -> Milvus/Zilliz defaulted to L2).
Safe to run even if the collection doesn't exist yet -- it just no-ops.

Run once, from the repo root, with the venv active and .env configured:

    python backend/scripts/reset_zilliz_collection.py

Then re-run backend/scripts/ingest_talkback_corpus.py to recreate the
collection and re-embed the corpus under the new metric type.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pymilvus import MilvusClient  # noqa: E402

from app.config import settings  # noqa: E402


def main() -> None:
    missing = [
        name
        for name, value in (("ZILLIZ_URI", settings.ZILLIZ_URI), ("ZILLIZ_TOKEN", settings.ZILLIZ_TOKEN))
        if not value
    ]
    if missing:
        raise SystemExit(f"Missing Zilliz credentials in .env: {', '.join(missing)}")

    client = MilvusClient(uri=settings.ZILLIZ_URI, token=settings.ZILLIZ_TOKEN)
    name = settings.ZILLIZ_COLLECTION_NAME

    if not client.has_collection(name):
        print(f"Collection {name!r} doesn't exist yet -- nothing to reset.")
        return

    client.drop_collection(name)
    print(f"Dropped collection {name!r}. Re-run ingest_talkback_corpus.py to recreate it.")


if __name__ == "__main__":
    main()
