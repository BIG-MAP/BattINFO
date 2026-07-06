"""Regression tests for the Phase 0 record-correctness fixes (beta-hardening plan 0.1/0.3/0.5).

0.1 — dataset agents preserve ORCID and classify people as Person (regression introduced by
      the DatasetInput retirement: the old builder passed creator dicts through verbatim).
0.3 — timestamp conversion symmetry: expires_at converts like manufactured_at; provenance
      retrieved_at accepts ISO strings on every builder, preserves epoch zero, and raises on
      garbage instead of silently substituting the current time.
0.5 — a flat string ``citation`` is provenance even when an explicit ``source`` is given.
"""

import pytest

from battinfo.api import (
    _record_from_cell_instance,
    _record_from_cell_spec,
    _record_from_dataset,
    _record_from_test,
    _record_from_test_protocol,
)
from battinfo.bundle import (
    Cell,
    CellSpec,
    Dataset,
    ProvenanceInfo,
    Test,
    TestSpec,
    _canonical_agent,
)

UID = "ffffffffffffffff"
SPEC_IRI = "https://w3id.org/battinfo/spec/aaaa-aaaa-aaaa-aaaa"
CELL_IRI = "https://w3id.org/battinfo/cell/bbbb-bbbb-bbbb-bbbb"
ORCID = "https://orcid.org/0000-0002-1825-0097"
JAN_2024 = 1704067200  # 2024-01-01T00:00:00Z
JAN_2030 = 1893456000  # 2030-01-01T00:00:00Z


# --- 0.1 ORCID preservation -------------------------------------------------------------


def test_dataset_creator_orcid_survives_and_is_a_person() -> None:
    dataset = Dataset(
        "d.csv", creators=[{"name": "Jane Doe", "orcid": ORCID}], uid=UID,
        access_url="https://data.example.com/d",
    )
    record = _record_from_dataset(dataset)
    (creator,) = record["dataset"]["creators"]
    assert creator["orcid"] == ORCID
    assert creator["type"] == "Person"


def test_dataset_funder_and_publisher_orcid_survive() -> None:
    dataset = Dataset(
        "d.csv",
        funders=[{"name": "Jane Doe", "orcid": ORCID}],
        publisher={"name": "Jane Doe", "orcid": ORCID},
        uid=UID,
    )
    assert dataset.funders[0]["orcid"] == ORCID
    assert dataset.publisher is not None and dataset.publisher["orcid"] == ORCID


def test_agent_without_person_signals_stays_organization() -> None:
    assert _canonical_agent({"name": "SINTEF"}) == {"name": "SINTEF", "type": "Organization"}


def test_agent_name_parts_signal_a_person() -> None:
    out = _canonical_agent({"name": "Jane Doe", "given_name": "Jane", "family_name": "Doe"})
    assert out is not None and out["type"] == "Person"


def test_explicit_agent_type_wins_but_orcid_is_kept() -> None:
    out = _canonical_agent({"name": "ACME Lab", "type": "Organization", "orcid": ORCID})
    assert out is not None
    assert out["type"] == "Organization"
    assert out["orcid"] == ORCID


# --- 0.5 citation routing ---------------------------------------------------------------


def test_dataset_flat_citation_with_explicit_source_goes_to_provenance() -> None:
    dataset = Dataset(
        "d.csv",
        citation="https://doi.org/10.1234/prov",
        source=ProvenanceInfo(type="repository"),
        uid=UID,
        access_url="https://data.example.com/d",
    )
    assert dataset.citations == []
    assert dataset.source.citation == "https://doi.org/10.1234/prov"
    assert dataset.source.type == "repository"
    record = _record_from_dataset(dataset)
    assert record["provenance"]["citation"] == "https://doi.org/10.1234/prov"
    assert "citations" not in record["dataset"]


def test_dataset_flat_citation_without_source_still_provenance() -> None:
    dataset = Dataset("d.csv", citation="https://doi.org/10.1234/prov", uid=UID)
    assert dataset.citations == []
    assert dataset.source.citation == "https://doi.org/10.1234/prov"


def test_dataset_citation_list_is_still_bibliographic() -> None:
    dataset = Dataset("d.csv", citation=["https://doi.org/10.1234/paper"], uid=UID)
    assert dataset.citations == [{"url": "https://doi.org/10.1234/paper"}]
    assert dataset.source.citation is None


def test_explicit_source_citation_wins_over_flat_kwarg() -> None:
    dataset = Dataset(
        "d.csv",
        citation="https://doi.org/10.1234/flat",
        source=ProvenanceInfo(citation="https://doi.org/10.1234/explicit"),
        uid=UID,
    )
    assert dataset.source.citation == "https://doi.org/10.1234/explicit"


# --- 0.3 timestamp conversion symmetry ----------------------------------------------------


def test_expires_at_converts_like_manufactured_at() -> None:
    instance = Cell(
        cell_spec_id=SPEC_IRI, manufactured_at="2024-01-01", expires_at="2030-01-01", uid=UID
    )
    record = _record_from_cell_instance(instance)
    assert record["cell_instance"]["manufactured_at"] == JAN_2024
    assert record["cell_instance"]["expires_at"] == JAN_2030


def test_expires_at_garbage_raises() -> None:
    instance = Cell(cell_spec_id=SPEC_IRI, expires_at="not a date", uid=UID)
    with pytest.raises(ValueError, match="expires_at"):
        _record_from_cell_instance(instance)


def test_retrieved_at_iso_string_converts_on_every_builder() -> None:
    spec_rec = _record_from_cell_spec(
        CellSpec(manufacturer="ACME", model="X1", retrieved_at="2024-01-01", uid=UID)
    )
    assert spec_rec["provenance"]["retrieved_at"] == JAN_2024
    inst_rec = _record_from_cell_instance(
        Cell(cell_spec_id=SPEC_IRI, retrieved_at="2024-01-01", uid=UID)
    )
    assert inst_rec["provenance"]["retrieved_at"] == JAN_2024
    test_rec = _record_from_test(
        Test(cell_instance_id=CELL_IRI, test_type="cycling", retrieved_at="2024-01-01", uid=UID)
    )
    assert test_rec["provenance"]["retrieved_at"] == JAN_2024
    proto_rec = _record_from_test_protocol(TestSpec(name="P", retrieved_at="2024-01-01", uid=UID))
    assert proto_rec["provenance"]["retrieved_at"] == JAN_2024
    ds_rec = _record_from_dataset(
        Dataset("d.csv", retrieved_at="2024-01-01", uid=UID, access_url="https://data.example.com/d")
    )
    assert ds_rec["provenance"]["retrieved_at"] == JAN_2024


def test_retrieved_at_epoch_zero_is_preserved() -> None:
    record = _record_from_test_protocol(TestSpec(name="P", retrieved_at=0, uid=UID))
    assert record["provenance"]["retrieved_at"] == 0


def test_retrieved_at_garbage_raises_instead_of_becoming_now() -> None:
    spec = CellSpec(manufacturer="ACME", model="X1", retrieved_at="not a date", uid=UID)
    with pytest.raises(ValueError, match="retrieved_at"):
        _record_from_cell_spec(spec)


def test_retrieved_at_absent_still_defaults_to_now() -> None:
    record = _record_from_cell_spec(CellSpec(manufacturer="ACME", model="X1", uid=UID))
    assert isinstance(record["provenance"]["retrieved_at"], int)
