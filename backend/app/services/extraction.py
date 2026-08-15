"""Structured field extraction for mission documents.

Runs downstream of ingestion (see `app.services.ingestion`) but works from
the same raw document text, not the vector store — extraction pulls out the
specific structured fields each module's grounded response needs on top of
(not instead of) the embedded chunks: procedure steps for
`/crisis/analyze`, sector thresholds for `/telemetry/interpret`'s
confidence scoring, and allergy records for `/triage`'s allergy cross check
(see dev plan Section 4/7 and API.md).

Mission documents are free text written by mission planners, not JSON, so
extraction is pattern-based rather than schema-based: each `DocumentType`
gets a small parser tuned to how that document type is conventionally
formatted (see each function's docstring for the expected line shapes).
Nothing here calls watsonx — extraction is deterministic parsing of the
document's own text, kept separate from the LLM-generated summaries the API
endpoints produce from retrieved chunks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.schemas import DocumentType, MissionDocument

# --- Procedure steps ---------------------------------------------------

# Matches a numbered line ("1. Vent the compartment", "1) Vent..."), a
# "Step N:" prefixed line, or a bulleted line ("- Vent..." / "* Vent...").
_STEP_LINE = re.compile(
    r"^\s*(?:(?P<num>\d+)[.)]|Step\s+(?P<step_num>\d+)\s*:|[-*])\s*(?P<text>\S.*)$",
    re.IGNORECASE,
)


def extract_procedure_steps(text: str) -> list[str]:
    """Pull an ordered list of steps out of a procedure document.

    Recognizes three common authoring styles line by line: numbered
    ("1. Vent the compartment"), "Step N:" prefixed, and bulleted ("- " or
    "* "). Lines that don't match any of these are prose (a heading, a
    caveat) and are skipped rather than guessed at — a step list built from
    only clearly-marked steps is safer to ground a crisis response in than
    one padded with misclassified prose.

    Steps are returned in document order, regardless of which style each
    one used, since a single procedure document sticks to one style but the
    corpus as a whole doesn't have to.
    """
    steps: list[str] = []
    for line in text.splitlines():
        match = _STEP_LINE.match(line)
        if match:
            steps.append(match.group("text").strip())
    return steps


# --- Sector thresholds ---------------------------------------------------


@dataclass(frozen=True)
class SectorThreshold:
    """A single metric's nominal operating band from a sector spec."""

    metric: str
    low: float
    high: float
    unit: str = ""


# Matches a "<metric>: <low>-<high><unit>" line, with an optional "nominal
# band"/"nominal range" phrase before the numbers, e.g.
# "O2 saturation: 19.5-23.5%" or "Hull temperature: nominal band -40 to -10 C".
_THRESHOLD_LINE = re.compile(
    r"^\s*(?P<metric>[A-Za-z][\w ./-]*?)\s*:\s*"
    r"(?:nominal\s*(?:band|range)?\s*:?\s*)?"
    r"(?P<low>-?\d+(?:\.\d+)?)\s*(?:-|to|–|—)\s*(?P<high>-?\d+(?:\.\d+)?)"
    r"\s*(?P<unit>[%A-Za-zµ°/]*)\s*$",
    re.IGNORECASE,
)


def extract_sector_thresholds(text: str) -> list[SectorThreshold]:
    """Pull nominal-band thresholds out of a sector spec document.

    Looks for lines of the shape `<metric>: <low>-<high><unit>`. This is
    the nominal band `/telemetry/interpret`'s confidence scoring measures
    live readings against (dev plan Section 4/7): a reading's distance from
    `(low, high)` is one of the signals that score is derived from, so a
    sector spec line that doesn't parse yields no threshold for that metric
    rather than a fabricated one — better a missing threshold than a wrong
    one feeding a confidence score.

    `low`/`high` are normalized so `low <= high` regardless of which order
    the document listed them in.
    """
    thresholds: list[SectorThreshold] = []
    for line in text.splitlines():
        match = _THRESHOLD_LINE.match(line)
        if not match:
            continue
        low = float(match.group("low"))
        high = float(match.group("high"))
        if low > high:
            low, high = high, low
        thresholds.append(
            SectorThreshold(
                metric=match.group("metric").strip(),
                low=low,
                high=high,
                unit=match.group("unit").strip(),
            )
        )
    return thresholds


# --- Allergy records -------------------------------------------------------

_ALLERGY_LINE = re.compile(
    r"^\s*(?:known\s+)?allerg(?:y|ies)\s*:\s*(?P<value>.+)$", re.IGNORECASE
)
_NONE_TOKENS = {"none", "none known", "n/a", "no known allergies", "nka"}


def extract_allergies(text: str) -> list[str]:
    """Pull the allergy list out of a crew file document.

    Looks for an "Allergies:" or "Known allergies:" line and splits its
    value on commas, semicolons, or a standalone "and". A value that reads
    as a none-token ("None", "N/A", "No known allergies", "NKA") returns an
    empty list rather than a one-item list containing that phrase —
    `/triage`'s allergy cross check (API.md) needs a clean list to check a
    proposed treatment against, not a phrase to also treat as an allergen.

    A crew file with no allergy line at all also returns an empty list.
    Callers that must distinguish "confirmed no allergies" from "allergy
    status unknown" need to check for the line's presence themselves —
    that distinction matters for a medical protocol, but extraction here
    only reports what it found.
    """
    for line in text.splitlines():
        match = _ALLERGY_LINE.match(line)
        if not match:
            continue
        value = match.group("value").strip().rstrip(".")
        if value.lower() in _NONE_TOKENS:
            return []
        parts = re.split(r",|;|\band\b", value, flags=re.IGNORECASE)
        return [part.strip() for part in parts if part.strip()]
    return []


# --- Dispatch --------------------------------------------------------------


@dataclass(frozen=True)
class ExtractedFields:
    """Structured fields pulled from one mission document.

    Only the field(s) relevant to the document's `DocumentType` are
    populated; the rest are left at their empty default. `doc_id` carries
    through so a caller batching `extract_fields` over `POST /ingest`'s
    document list can still tell which document each result came from.
    """

    doc_id: str
    doc_type: DocumentType
    procedure_steps: list[str] = field(default_factory=list)
    sector_thresholds: list[SectorThreshold] = field(default_factory=list)
    allergies: list[str] = field(default_factory=list)


def extract_fields(document: MissionDocument) -> ExtractedFields:
    """Extract the structured fields relevant to one document's type.

    Dispatches on `document.type`: a `PROCEDURE` document gets its steps
    extracted, a `SECTOR_SPEC` document gets its thresholds, a `CREW_FILE`
    document gets its allergy list. `INCIDENT_RECORD` documents have no
    extractor yet — they come back with every list empty, same as a
    document whose text didn't match its type's expected format.
    """
    if document.type == DocumentType.PROCEDURE:
        return ExtractedFields(
            doc_id=document.id,
            doc_type=document.type,
            procedure_steps=extract_procedure_steps(document.text),
        )
    if document.type == DocumentType.SECTOR_SPEC:
        return ExtractedFields(
            doc_id=document.id,
            doc_type=document.type,
            sector_thresholds=extract_sector_thresholds(document.text),
        )
    if document.type == DocumentType.CREW_FILE:
        return ExtractedFields(
            doc_id=document.id,
            doc_type=document.type,
            allergies=extract_allergies(document.text),
        )
    return ExtractedFields(doc_id=document.id, doc_type=document.type)


def extract_documents(documents: list[MissionDocument]) -> list[ExtractedFields]:
    """Extract structured fields from a batch of documents, in order."""
    return [extract_fields(document) for document in documents]
