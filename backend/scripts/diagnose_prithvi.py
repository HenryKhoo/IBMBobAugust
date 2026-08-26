"""Diagnose why 'what is Prithvi?' returns the no-grounded-answer fallback.

Run from the repo root with the venv active and .env configured, exactly
like the ingest script:

    python backend/scripts/diagnose_prithvi.py

It mirrors the running server's own retrieval path (same config, same
embedding provider selection, same get_vector_store) and prints:
  1. which embedding provider + Zilliz collection the server WOULD use now
  2. how many rows that collection actually holds
  3. the live retrieval result for 'what is Prithvi?' with relevance scores

Read the three sections top-to-bottom: they pinpoint whether the problem is
the wrong/empty collection (section 2) or genuinely weak relevance
(section 3).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings                                    # noqa: E402
from app.services.watsonx import using_gemini_embeddings           # noqa: E402
from app.services.vector_store import get_vector_store             # noqa: E402
from app.services.query import run_query                           # noqa: E402

print("=" * 64)
print("1. ACTIVE RETRIEVAL PATH (what the running server would use now)")
print("=" * 64)
gem = using_gemini_embeddings()
collection = (
    settings.ZILLIZ_COLLECTION_NAME_GEMINI if gem
    else settings.ZILLIZ_COLLECTION_NAME
)
print(f"  using_gemini_embeddings(): {gem}")
print(f"  GEMINI_API_KEY set:        {bool(settings.GEMINI_API_KEY)}")
print(f"  -> collection queried:     {collection!r}")
print(f"  (watsonx collection:       {settings.ZILLIZ_COLLECTION_NAME!r})")
print(f"  (gemini  collection:       {settings.ZILLIZ_COLLECTION_NAME_GEMINI!r})")

print()
print("=" * 64)
print("2. COLLECTION ROW COUNT (is the data actually in there?)")
print("=" * 64)
store = get_vector_store()
count = None
for attr in ("client", "_milvus_client"):
    c = getattr(store, attr, None)
    if c is not None:
        try:
            stats = c.get_collection_stats(collection)
            count = stats.get("row_count", stats)
            break
        except Exception as e:  # noqa: BLE001
            print(f"  (stats via {attr} failed: {e})")
if count is None:
    col = getattr(store, "col", None)
    if col is not None:
        try:
            col.flush()
            count = col.num_entities
        except Exception as e:  # noqa: BLE001
            print(f"  (num_entities failed: {e})")
print(f"  rows in {collection!r}: {count}")
if count in (0, None):
    print("  >> EMPTY/UNREACHABLE: this is why /query returns 'no grounded")
    print("     answer'. The server is pointed at a collection with no Prithvi")
    print("     content. Re-ingest into THIS collection, or fix which collection")
    print("     is selected, then restart the backend.")

print()
print("=" * 64)
print("3. LIVE RETRIEVAL: 'what is Prithvi?'")
print("=" * 64)
resp = run_query("what is Prithvi?", top_k=5)
if not resp.results:
    print("  0 passages returned -> frontend shows the no-grounded-answer")
    print("  fallback. With no score threshold in run_query, 0 passages means")
    print("  the collection returned zero rows (see section 2).")
else:
    for i, r in enumerate(resp.results, 1):
        src = getattr(r, "source", None)
        print(f"  [{i}] relevance={r.relevance}  source={src}")
        print(f"      {r.text[:160].strip()}...")
    print()
    print("  >> If the top hit is a Prithvi passage with a healthy relevance,")
    print("     retrieval works and any remaining failure is downstream")
    print("     (generation/500 -- open item #1), not retrieval.")
