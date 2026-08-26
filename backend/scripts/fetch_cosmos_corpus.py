"""Dev-time fetch: NASA SMD Q&A benchmark -> backend/data/cosmos_corpus.json.

Run once, from the repo root, with backend/requirements.txt installed:

    python backend/scripts/fetch_cosmos_corpus.py

Pulls nasa-impact/nasa-smd-qa-benchmark via the Hugging Face
datasets-server `/rows` endpoint (public, no auth token needed) and
flattens its nested SQuAD-style structure -- one row per split holds
`data[].paragraphs[].qas[]`, not one row per question -- into a flat list
of {id, type, text} documents ready for backend/scripts/
ingest_cosmos_corpus.py (or a direct POST /ingest). Each document's
`text` combines the source paragraph with its question/answer pair, so
retrieval can match on the paragraph's own wording or a real question's
phrasing, and generation has real context to work from, not just an
isolated answer sentence.

This talks to the public internet and needs to run somewhere with normal,
unrestricted access -- your own machine's terminal, not a sandboxed
bridge/proxy environment. If it produces zero documents, the dataset's row
shape probably doesn't match what `_flatten` expects below; the error
message tells you how to inspect a raw row and adjust.

Only needs re-running if the corpus itself changes -- the output is
committed to the repo, not fetched at request time or app startup.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

DATASET = "nasa-impact/nasa-smd-qa-benchmark"
CONFIG = "default"
SPLIT = "train"
BASE_URL = "https://datasets-server.huggingface.co/rows"
PAGE_SIZE = 100
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "cosmos_corpus.json"


def _fetch_all_rows() -> list[dict]:
    rows: list[dict] = []
    offset = 0
    with httpx.Client(timeout=30.0) as client:
        while True:
            response = client.get(
                BASE_URL,
                params={
                    "dataset": DATASET,
                    "config": CONFIG,
                    "split": SPLIT,
                    "offset": offset,
                    "length": PAGE_SIZE,
                },
            )
            response.raise_for_status()
            payload = response.json()
            batch = payload.get("rows", [])
            if not batch:
                break
            rows.extend(batch)
            if len(batch) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
    return rows


def _flatten(rows: list[dict]) -> list[dict]:
    """Flatten the SQuAD-style data[].paragraphs[].qas[] nesting.

    Each row is expected to hold (under a `"row"` key, or at the top level
    if the API shape differs) a `data` list of articles, each with
    `paragraphs`, each with `context` and a `qas` list of
    {question, answers: [{text, ...}, ...]}. One document is built per QA
    pair, paired with its own source paragraph.
    """
    documents: list[dict] = []
    seen_ids: set[str] = set()

    for row_wrapper in rows:
        row = row_wrapper.get("row", row_wrapper)
        for article in row.get("data", []):
            source_title = article.get("title", "NASA SMD")
            for paragraph in article.get("paragraphs", []):
                context = (paragraph.get("context") or "").strip()
                if not context:
                    continue
                for qa in paragraph.get("qas", []):
                    question = (qa.get("question") or "").strip()
                    answers = qa.get("answers") or []
                    answer_text = (answers[0].get("text") if answers else "").strip()
                    if not question or not answer_text:
                        continue
                    raw_id = str(qa.get("id") or f"{source_title}-{len(documents)}")
                    doc_id = f"nasa-smd-{raw_id}".replace(" ", "-").lower()[:200]
                    if doc_id in seen_ids:
                        doc_id = f"{doc_id}-{len(documents)}"
                    seen_ids.add(doc_id)
                    documents.append(
                        {
                            "id": doc_id,
                            "type": "science_reference",
                            "text": (
                                f"Source: {source_title}\n\n{context}\n\n"
                                f"Q: {question}\nA: {answer_text}"
                            ),
                        }
                    )
    return documents


def main() -> None:
    print(f"Fetching {DATASET} ({CONFIG}/{SPLIT}) from datasets-server...")
    rows = _fetch_all_rows()
    print(f"Fetched {len(rows)} raw rows.")

    documents = _flatten(rows)
    print(f"Flattened into {len(documents)} science_reference documents.")

    if not documents:
        raise SystemExit(
            "No documents produced. The dataset's row shape likely doesn't "
            "match what _flatten() expects. Inspect one raw row directly, "
            "e.g. add `print(json.dumps(rows[0], indent=2)[:2000])` right "
            "after the fetch above and re-run, then adjust _flatten()'s "
            "key names to match what you see."
        )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(documents, indent=2))
    print(f"Wrote {len(documents)} documents to {OUTPUT_PATH}")
    print("Sample document:")
    print(json.dumps(documents[0], indent=2)[:600])


if __name__ == "__main__":
    main()
