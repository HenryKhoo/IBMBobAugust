"""Diagnose why 'what is Prithvi?' returns the no-grounded-answer fallback,
or (2026-08-26, round 6) why it returns a grounded answer sourced from the
WRONG passage.

Run from the repo root with the venv active and .env configured, exactly
like the ingest script:

    python backend/scripts/diagnose_prithvi.py

It mirrors the running server's own retrieval path (same config, same
embedding provider selection, same get_vector_store) and prints:
  1. which embedding provider + Zilliz collection the server WOULD use now
  2. how many rows that collection actually holds
  3. an UNFILTERED top-5 retrieval for 'what is Prithvi?' (same call
     backend/scripts/diagnose_prithvi.py always made, via run_query)
  4. the EXACT retrieval /ask actually performs for this question --
     same function (relevance_score_hits_or_empty), same k=1, same
     doc_type filter -- so this is a byte-for-byte reproduction of what a
     live /ask call sees, not an approximation of it. Section 3 uses
     run_query's own unfiltered, k=5 search; if section 3's top hit is a
     genuine Prithvi passage but section 4's k=1 filtered hit is a
     DIFFERENT document, that's the concrete evidence retrieval itself
     (not generation) picked the wrong passage for the real endpoint,
     and section 3's earlier "retrieval works" reading was too optimistic
     -- it was never actually run through the same code path /ask uses.

Read every section top-to-bottom: they pinpoint whether the problem is
the wrong/empty collection (section 2), weak relevance across the board
(section 3), or -- new as of round 6 -- a mismatch between the
unfiltered top-5 and the filtered top-1 /ask actually retrieves
(section 4 vs section 3).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings                                    # noqa: E402
from app.services.watsonx import using_gemini_embeddings           # noqa: E402
from app.services.vector_store import (                            # noqa: E402
    get_vector_store,
    relevance_score_hits_or_empty,
)
from app.services.query import run_query                           # noqa: E402

QUESTION = "what is Prithvi?"

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
print(f"3. UNFILTERED top-5 retrieval (run_query): {QUESTION!r}")
print("=" * 64)
resp = run_query(QUESTION, top_k=5)
if not resp.results:
    print("  0 passages returned -> the collection has nothing at all for this")
    print("  query (see section 2).")
else:
    for i, r in enumerate(resp.results, 1):
        src = getattr(r, "source", None)
        print(f"  [{i}] relevance={r.relevance}  source={src}")
        print(f"      {r.text[:160].strip()}...")

print()
print("=" * 64)
print(f"4. EXACT /ask retrieval (relevance_score_hits_or_empty, k=1, "
      f"doc_type filter): {QUESTION!r}")
print("=" * 64)
ask_expr = "doc_type == 'science_reference'"
hits = relevance_score_hits_or_empty(store, QUESTION, k=1, expr=ask_expr)
if not hits:
    print("  0 hits -> /ask would return the no-grounded-answer fallback for")
    print("  BOTH personas right now, regardless of anything in section 3.")
else:
    chunk, relevance_score = hits[0]
    confidence = round(max(0.0, min(1.0, relevance_score)), 2)
    src = f"{chunk.metadata.get('doc_type')}:{chunk.metadata.get('doc_id')}#chunk{chunk.metadata.get('chunk_index')}"
    print(f"  confidence={confidence}  source={src}")
    print(f"  passage: {chunk.page_content[:200].strip()}...")
    print()
    top5_sources = [getattr(r, "source", None) for r in resp.results] if resp.results else []
    if src not in top5_sources:
        print("  >> MISMATCH: this source does not appear anywhere in section 3's")
        print("     unfiltered top-5 at all. That's not a k=1-vs-k=5 ranking quirk --")
        print("     something differs between run_query's search and this one")
        print("     beyond just the doc_type filter (which every doc in this corpus")
        print("     already satisfies, so it should be a no-op here).")
    elif top5_sources and src != top5_sources[0]:
        print(f"  >> MISMATCH: section 3's #1 hit was {top5_sources[0]!r}, but this")
        print("     k=1 filtered call returned a different top hit. This points at")
        print("     Zilliz's AUTOINDEX giving different results for k=1 vs k=5 --")
        print("     an approximate-search recall issue, not a data or code bug.")
    else:
        print("  >> MATCHES section 3's #1 hit. Retrieval is consistent; if /ask")
        print("     still returns the wrong source live, the bug is somewhere")
        print("     between this call and the response (unlikely given both call")
        print("     the same relevance_score_hits_or_empty chokepoint /ask uses).")
