"""Admin-only write path for backend/data/preset_qa.json — see frontend/admin.html.

Internal tool, not part of C.O.S.M.O.S.'s public API surface (the routes
that call into this live in `app.main` behind the `ADMIN_TOKEN` gate — see
`app.main._require_admin_token`). Appends a new curated Q&A entry in
exactly the shape `app.services.cosmos._load_preset_cache` already expects,
so a freshly-appended entry is answerable by `POST /ask` the moment
`cosmos.reload_preset_cache()` runs, with no restart or separate migration
step.
"""

from __future__ import annotations

import json
import re

from app.schemas import Domain
from app.services.cosmos import _PRESET_QA_PATH, reload_preset_cache


class DuplicateQuestionError(ValueError):
    """Raised when `question` already keys an entry in preset_qa.json.

    `_load_preset_cache` keys entries by exact (stripped/lowercased)
    question text, so a duplicate would otherwise silently shadow, or be
    shadowed by, the existing entry instead of ever being flagged.
    """


def _slugify(question: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", question.lower()).strip("-")
    return slug[:60] or "entry"


def _unique_id(base_slug: str, existing_ids: set[str]) -> str:
    if base_slug not in existing_ids:
        return base_slug
    suffix = 2
    while f"{base_slug}-{suffix}" in existing_ids:
        suffix += 1
    return f"{base_slug}-{suffix}"


_GENERAL_KNOWLEDGE_CAVEAT = (
    "AI-drafted from general knowledge, not a corpus citation — reviewed and "
    "confirmed accurate by an admin before saving."
)


def append_preset_entry(
    question: str,
    domains: list[Domain],
    baseline_answer: str,
    banter_answer: str,
    source_type: str = "manual",
) -> dict:
    """Append one admin-authored entry to preset_qa.json and reload the live cache.

    Reads `data["entries"]` fresh off disk for both the duplicate check and
    id-uniqueness check, rather than trusting `cosmos`'s in-memory
    `_PRESET_CACHE`, so this is correct even across multiple appends in the
    same process (the cache is only ever swapped, not read back here).
    Raises `DuplicateQuestionError` if `question` (stripped/lowercased)
    already exists.

    `source_type` (`"corpus"` / `"general_knowledge"` / `"manual"`, mirrors
    `AdminGenerateBaselineResponse.source_type`) is saved as `True` for
    every entry regardless — a `general_knowledge` draft only reaches here
    after the admin page's acknowledgment checkbox, i.e. a human has
    already reviewed and vouched for it, the same trust level a `manual`
    entry always had — but it still has no real passage behind it, so it
    gets `match_quality: "no_match"` and an explanatory `caveat` instead of
    the `"strong"`/`None` a corpus-backed entry gets, and the `no_match`
    (not `strong_match`) summary counter is incremented. `use_cache: True`,
    `source: []`, `confidence: None` either way — the admin page supplies
    only question/domains/baseline_answer/banter_answer/source_type, so
    everything else here is filled in to match the shape of every other
    entry in the file.
    """
    key = question.strip().lower()

    with _PRESET_QA_PATH.open() as f:
        data = json.load(f)

    existing_keys = {entry["question"].strip().lower() for entry in data["entries"]}
    if key in existing_keys:
        raise DuplicateQuestionError(f"Question already exists in preset cache: {question!r}")

    existing_ids = {entry["id"] for entry in data["entries"]}
    entry_id = _unique_id(_slugify(question), existing_ids)

    is_general_knowledge = source_type == "general_knowledge"

    entry = {
        "id": entry_id,
        "question": question,
        "domains": [d.value for d in domains],
        "appears_in_all_chip": False,
        "match_quality": "no_match" if is_general_knowledge else "strong",
        "use_cache": True,
        "grounded": True,
        "baseline_answer": baseline_answer,
        "banter_answer": banter_answer,
        "caveat": _GENERAL_KNOWLEDGE_CAVEAT if is_general_knowledge else None,
        "source": [],
        "confidence": None,
    }
    data["entries"].append(entry)
    data["summary"]["total_questions"] = data["summary"].get("total_questions", 0) + 1
    summary_counter = "no_match" if is_general_knowledge else "strong_match"
    data["summary"][summary_counter] = data["summary"].get(summary_counter, 0) + 1

    with _PRESET_QA_PATH.open("w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")

    reload_preset_cache()
    return entry
