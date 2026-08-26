"""One-time fix-up: drop the active Zilliz collection so a re-ingest starts clean.

Originally written to force a recreate under the COSINE metric type (see
the comment on `vector_store._INDEX_PARAMS`); also the right tool whenever
a re-ingest was interrupted partway through (e.g. hit a rate limit — see
`ingest_chortlechat_corpus.py`'s pacing comment) and might have left a
partial set of chunks behind. Since Zilliz inserts use `auto_id=True`,
there's no natural dedup on a retry — a partial collection plus a full
re-ingest on top produces duplicate chunks for whatever got in before the
interruption, not a clean corpus. Dropping first guarantees the next
ingest starts from empty.

Drops whichever collection `app.services.vector_store.get_vector_store`
would currently write to — `ZILLIZ_COLLECTION_NAME_GEMINI` when
`GEMINI_API_KEY` is set, `ZILLIZ_COLLECTION_NAME` (the watsonx collection)
otherwise — so this always matches the provider actually active in `.env`
rather than hardcoding the watsonx name and silently dropping the wrong
collection on a Gemini setup. Safe to run even if the collection doesn't
exist yet -- it just no-ops.

Run once, from the repo root, with the venv active and .env configured:

    python backend/scripts/reset_zilliz_collection.py

Then re-run backend/scripts/ingest_chortlechat_corpus.py to recreate the
collection and re-embed the corpus.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pymilvus import MilvusClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.services.watsonx import using_gemini_embeddings  # noqa: E402


def main() -> None:
    missing = [
        name
        for name, value in (("ZILLIZ_URI", settings.ZILLIZ_URI), ("ZILLIZ_TOKEN", settings.ZILLIZ_TOKEN))
        if not value
    ]
    if missing:
        raise SystemExit(f"Missing Zilliz credentials in .env: {', '.join(missing)}")

    client = MilvusClient(uri=settings.ZILLIZ_URI, token=settings.ZILLIZ_TOKEN)
    # Mirror app.services.vector_store.get_vector_store's own collection
    # choice exactly — see the module docstring above for why this must
    # never hardcode ZILLIZ_COLLECTION_NAME.
    name = (
        settings.ZILLIZ_COLLECTION_NAME_GEMINI
        if using_gemini_embeddings()
        else settings.ZILLIZ_COLLECTION_NAME
    )

    if not client.has_collection(name):
        print(f"Collection {name!r} doesn't exist yet -- nothing to reset.")
        return

    client.drop_collection(name)
    print(f"Dropped collection {name!r}. Re-run ingest_chortlechat_corpus.py to recreate it.")


if __name__ == "__main__":
    main()
