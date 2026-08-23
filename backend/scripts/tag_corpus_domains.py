"""One-time reclassification: tag backend/data/chortlechat_corpus.json with `domain`.

Run once, from the repo root:

    python backend/scripts/tag_corpus_domains.py

Every existing corpus document's text begins with a "Source: <topic>"
line (see fetch_chortlechat_corpus.py's `_flatten`). This maps each of the
24 distinct topic strings actually present in the committed corpus to one
of the five `Domain` values (mission-based domain selection), writes
`domain` onto every document in place, and prints a per-domain count
summary so the classification is reviewable at a glance rather than a
silent, unverifiable transform.

This only rewrites backend/data/chortlechat_corpus.json — it does not touch
Zilliz. Re-run backend/scripts/ingest_chortlechat_corpus.py afterward (with
real WATSONX_*/ZILLIZ_* credentials configured) to actually get `domain`
into the vector store's metadata; until that re-ingest happens, /ask and
/query's domain filter has nothing tagged to match against and will fall
back to an unscoped search for every domain (see
app.services.chortlechat._retrieval_expr's fallback).

If a future corpus refresh (re-running fetch_chortlechat_corpus.py) ever
introduces a `Source:` topic not listed in TOPIC_TO_DOMAIN below, this
raises rather than silently defaulting it to "other" — a new topic should
be a deliberate classification decision, not a side effect of forgetting
to update this table.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.schemas import Domain  # noqa: E402

CORPUS_PATH = Path(__file__).resolve().parent.parent / "data" / "chortlechat_corpus.json"

# Every "Source: <topic>" string present in the corpus as fetched by
# fetch_chortlechat_corpus.py, classified by hand against the five domains a
# user picks from before asking a question. Topics genuinely span more
# than one theme (e.g. the two "Airborne Dust, Tropical Cyclone[s], ..."
# topics) are placed by their primary subject — dust's effect on cyclones
# reads as a dust-storm topic first — not split or duplicated.
TOPIC_TO_DOMAIN: dict[str, Domain] = {
    # --- Tropical Cyclone Dynamics ---
    "Tropical Cyclone": Domain.TROPICAL_CYCLONE_DYNAMICS,
    "Tropical Cyclones": Domain.TROPICAL_CYCLONE_DYNAMICS,
    "hurricane eyewall mesovortex dynamics": Domain.TROPICAL_CYCLONE_DYNAMICS,
    # --- Saharan Dust ---
    "Airborne Dust, Tropical Cyclone, Atlantic": Domain.SAHARAN_DUST,
    "Airborne Dust, Tropical Cyclones": Domain.SAHARAN_DUST,
    "Asian Sand and Dust Storms": Domain.SAHARAN_DUST,
    "Dust Spectrum Characterization Analysis": Domain.SAHARAN_DUST,
    "Impact of Saharan Dust": Domain.SAHARAN_DUST,
    # --- Climate Reconstruction ---
    "Climate change": Domain.CLIMATE_RECONSTRUCTION,
    "climate change": Domain.CLIMATE_RECONSTRUCTION,
    "Drought, Precipitation Reconstruction": Domain.CLIMATE_RECONSTRUCTION,
    "ground validation of satellite-based precipitation observations": Domain.CLIMATE_RECONSTRUCTION,
    # --- Environmental Hazards ---
    "Environmental Degradation": Domain.ENVIRONMENTAL_HAZARDS,
    "Environmental degradation": Domain.ENVIRONMENTAL_HAZARDS,
    "Environmental change": Domain.ENVIRONMENTAL_HAZARDS,
    "GIS": Domain.ENVIRONMENTAL_HAZARDS,
    "Pollution": Domain.ENVIRONMENTAL_HAZARDS,
    "Water quality": Domain.ENVIRONMENTAL_HAZARDS,
    "Wildland fires": Domain.ENVIRONMENTAL_HAZARDS,
    "environmental statistics": Domain.ENVIRONMENTAL_HAZARDS,
    # --- Other ---
    # Mesoscale/local-convective phenomena that aren't specifically about
    # tropical cyclones, dust, climate reconstruction, or a named hazard —
    # a real catch-all bucket, not "unclassified". See Domain.OTHER's
    # docstring in app/schemas.py.
    "Cold-Air Damming": Domain.OTHER,
    "Drylines": Domain.OTHER,
    "Severe weather": Domain.OTHER,
    "mesoscale forecasting, severe thunderstorms": Domain.OTHER,
}

_SOURCE_LINE = re.compile(r"^Source: (.+)$", re.MULTILINE)


def _topic_of(text: str) -> str:
    match = _SOURCE_LINE.search(text)
    if not match:
        raise ValueError(f"Document has no 'Source: ...' line to classify:\n{text[:200]!r}")
    return match.group(1).strip()


def main() -> None:
    if not CORPUS_PATH.exists():
        raise SystemExit(
            f"{CORPUS_PATH} not found. Run backend/scripts/fetch_chortlechat_corpus.py first."
        )

    documents = json.loads(CORPUS_PATH.read_text())
    counts: Counter[str] = Counter()
    unclassified: set[str] = set()

    for doc in documents:
        topic = _topic_of(doc["text"])
        domain = TOPIC_TO_DOMAIN.get(topic)
        if domain is None:
            unclassified.add(topic)
            continue
        doc["domain"] = domain.value
        counts[domain.value] += 1

    if unclassified:
        raise SystemExit(
            "Found Source: topic(s) with no entry in TOPIC_TO_DOMAIN — classify "
            "them there before re-running:\n  " + "\n  ".join(sorted(unclassified))
        )

    CORPUS_PATH.write_text(json.dumps(documents, indent=2) + "\n")

    print(f"Tagged {len(documents)} documents with domain. Breakdown:")
    for domain in Domain:
        print(f"  {domain.value:<28} {counts.get(domain.value, 0)}")
    print(
        f"\nWrote {CORPUS_PATH}. Re-run backend/scripts/ingest_chortlechat_corpus.py "
        "(with real credentials) to get these tags into Zilliz."
    )


if __name__ == "__main__":
    main()
