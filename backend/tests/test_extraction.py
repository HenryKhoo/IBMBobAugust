from pathlib import Path

import pytest

from app.schemas import DocumentType, MissionDocument
from app.services.extraction import (
    SectorThreshold,
    extract_allergies,
    extract_documents,
    extract_fields,
    extract_procedure_steps,
    extract_sector_thresholds,
)
from app.services.ingestion import DEFAULT_CHUNK_SIZE, chunk_documents

FIXTURES = Path(__file__).parent / "fixtures"


# --- extract_procedure_steps ------------------------------------------------


def test_extract_procedure_steps_handles_numbered_step_and_bullet_styles_in_order():
    text = "Overview\n1. Sound the alarm.\nStep 2: Seal the bulkhead.\n- Log the incident.\n"
    assert extract_procedure_steps(text) == [
        "Sound the alarm.",
        "Seal the bulkhead.",
        "Log the incident.",
    ]


def test_extract_procedure_steps_skips_prose_and_headings():
    text = (
        "Isolation Sequence\n"
        "A hull breach requires immediate action.\n"
        "1. Vent the compartment.\n"
    )
    assert extract_procedure_steps(text) == ["Vent the compartment."]


def test_extract_procedure_steps_does_not_misparse_decimal_numbers_in_prose():
    # Regression test: "1.5 liters..." used to be misread as step "5
    # liters...", because the numbered-step marker didn't require
    # whitespace before the step text. See extraction._STEP_LINE.
    text = (
        "1. Vent the compartment to vacuum.\n"
        "1.5 liters of coolant were vented before the seal engaged.\n"
        "2. Confirm hull pressure has stabilized.\n"
    )
    assert extract_procedure_steps(text) == [
        "Vent the compartment to vacuum.",
        "Confirm hull pressure has stabilized.",
    ]


# --- extract_sector_thresholds ----------------------------------------------


def test_extract_sector_thresholds_parses_a_simple_range():
    thresholds = extract_sector_thresholds("O2 saturation: 19.5-23.5%")
    assert thresholds == [
        SectorThreshold(metric="O2 saturation", low=19.5, high=23.5, unit="%")
    ]


def test_extract_sector_thresholds_parses_nominal_band_phrasing_and_negative_range():
    thresholds = extract_sector_thresholds("Hull temperature: nominal band -40 to -10 C")
    assert thresholds == [
        SectorThreshold(metric="Hull temperature", low=-40.0, high=-10.0, unit="C")
    ]


def test_extract_sector_thresholds_normalizes_low_high_order():
    thresholds = extract_sector_thresholds("Cabin CO2: 0.5-0%")
    assert thresholds == [SectorThreshold(metric="Cabin CO2", low=0.0, high=0.5, unit="%")]


def test_extract_sector_thresholds_handles_parenthesized_metric_names():
    # Regression test: a metric name with a unit noted in parentheses used
    # to fail to match at all. See extraction._THRESHOLD_LINE.
    thresholds = extract_sector_thresholds("Cabin pressure (kPa): 95-105")
    assert thresholds == [
        SectorThreshold(metric="Cabin pressure (kPa)", low=95.0, high=105.0, unit="")
    ]


def test_extract_sector_thresholds_skips_non_matching_lines():
    text = "Nominal Operating Bands\nO2 saturation: 19.5-23.5%\nNotes\n"
    thresholds = extract_sector_thresholds(text)
    assert [t.metric for t in thresholds] == ["O2 saturation"]


# --- extract_allergies -------------------------------------------------------


def test_extract_allergies_splits_a_comma_and_and_joined_list():
    assert extract_allergies("Allergies: penicillin, shellfish and latex") == [
        "penicillin",
        "shellfish",
        "latex",
    ]


@pytest.mark.parametrize(
    "phrase", ["None", "N/A", "No known allergies", "NKA", "None known."]
)
def test_extract_allergies_treats_none_tokens_as_empty(phrase):
    assert extract_allergies(f"Allergies: {phrase}") == []


def test_extract_allergies_returns_empty_when_no_allergy_line_present():
    text = "Name: J. Alvarez\nRole: Systems Engineer\n"
    assert extract_allergies(text) == []


# --- extract_fields / extract_documents dispatch -----------------------------


def test_extract_fields_dispatches_by_document_type():
    procedure = MissionDocument(id="p1", type=DocumentType.PROCEDURE, text="1. Vent the area.")
    sector = MissionDocument(
        id="s1", type=DocumentType.SECTOR_SPEC, text="O2 saturation: 19.5-23.5%"
    )
    crew = MissionDocument(id="c1", type=DocumentType.CREW_FILE, text="Allergies: shellfish")
    incident = MissionDocument(
        id="i1", type=DocumentType.INCIDENT_RECORD, text="A micrometeorite impact occurred."
    )

    results = {f.doc_id: f for f in extract_documents([procedure, sector, crew, incident])}

    assert results["p1"].procedure_steps == ["Vent the area."]
    assert results["p1"].sector_thresholds == []
    assert results["p1"].allergies == []

    assert results["s1"].sector_thresholds == [
        SectorThreshold(metric="O2 saturation", low=19.5, high=23.5, unit="%")
    ]
    assert results["s1"].procedure_steps == []

    assert results["c1"].allergies == ["shellfish"]
    assert results["c1"].procedure_steps == []

    # No extractor exists yet for INCIDENT_RECORD: every list comes back
    # empty rather than raising.
    assert results["i1"].procedure_steps == []
    assert results["i1"].sector_thresholds == []
    assert results["i1"].allergies == []
    assert results["i1"] == extract_fields(incident)


# --- End-to-end against the sample mission documents --------------------------

_SAMPLE_DOCS = [
    ("sample_emergency_procedure.txt", DocumentType.PROCEDURE),
    ("sample_sector_spec.txt", DocumentType.SECTOR_SPEC),
    ("sample_crew_file.txt", DocumentType.CREW_FILE),
    ("sample_incident_record.txt", DocumentType.INCIDENT_RECORD),
]


def _load_sample_documents() -> list[MissionDocument]:
    return [
        MissionDocument(id=filename, type=doc_type, text=(FIXTURES / filename).read_text())
        for filename, doc_type in _SAMPLE_DOCS
    ]


def test_extraction_pipeline_runs_end_to_end_against_sample_documents():
    documents = _load_sample_documents()
    results = {f.doc_id: f for f in extract_documents(documents)}

    procedure = results["sample_emergency_procedure.txt"]
    assert len(procedure.procedure_steps) == 10
    assert not any("1.5 liters" in step for step in procedure.procedure_steps)

    sector = results["sample_sector_spec.txt"]
    assert [t.metric for t in sector.sector_thresholds] == [
        "O2 saturation",
        "CO2 concentration",
        "Cabin pressure (kPa)",
        "Hull temperature",
        "Humidity",
    ]

    crew = results["sample_crew_file.txt"]
    assert crew.allergies == ["penicillin", "shellfish", "latex"]

    incident = results["sample_incident_record.txt"]
    assert incident.procedure_steps == []
    assert incident.sector_thresholds == []
    assert incident.allergies == []


def test_chunking_pipeline_runs_end_to_end_against_sample_documents():
    documents = _load_sample_documents()
    chunks = chunk_documents(documents)

    assert chunks
    doc_ids = {document.id for document in documents}
    assert {chunk.doc_id for chunk in chunks} <= doc_ids
    for chunk in chunks:
        assert len(chunk.text) <= DEFAULT_CHUNK_SIZE
