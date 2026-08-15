"""Alias map from raw telemetry metric keys to sector-spec threshold names.

A Module 02 request's `metrics` dict uses short raw keys — `eff`, `o2pp`,
`humidity` for the oxygen sector, per `TelemetryInterpretRequest`'s
docstring and `mission-console.html`'s per-sector `state` shapes. A
sector-spec document's nominal-band thresholds (see
`app.services.extraction.extract_sector_thresholds`) are written in prose,
e.g. "O2 saturation: 19.5-23.5%" or "Cabin pressure (kPa): 95-105". These
two vocabularies don't line up lexically, so `telemetry.py`'s confidence
scoring (dev plan Aug 19, Task 2) needs an explicit bridge between them
rather than a fuzzy/substring guess.

This map is intentionally sparse. No real sector-spec documents have been
authored or ingested yet (see the day-18 ingestion/extraction plan) — only
a synthetic test fixture exists (`tests/fixtures/sample_sector_spec.txt`).
Guessing an alias for a metric this map hasn't confirmed risks silently
grounding a confidence number in the wrong physical quantity — e.g.
matching the oxygen sector's "O2 partial pressure" reading against an
unrelated "O2 saturation" threshold. That's a worse failure than reporting
no band signal for that metric at all (see `telemetry._band_conformity`,
which treats an unmapped or unmatched key as "no band signal", not a
fabricated one).

Extend this map once real, ingested sector-spec content exists to verify
each entry against — don't add speculative entries ahead of that.
"""

from __future__ import annotations

# Raw metric key (as sent in a request's `metrics` dict, matched
# case-insensitively) -> the canonical threshold name it corresponds to in
# sector-spec prose. The canonical name is matched against
# `SectorThreshold.metric` after both sides are normalized — see
# `telemetry._normalize_metric_name` — so exact wording/casing/punctuation
# doesn't need to match, but the underlying quantity must.
METRIC_ALIASES: dict[str, str] = {
    # Verified only against the day-18 synthetic fixture
    # (sample_sector_spec.txt), not against any real sector-spec document.
    "humidity": "humidity",
}
