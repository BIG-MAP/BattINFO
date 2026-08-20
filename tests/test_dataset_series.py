"""DCAT dataset-series support: a collection is an ordinary dataset record
flavored as a series (additional_type = "DatasetSeries"), membership is the
series_id edge. No new record type; DCAT 3 declares dcat:DatasetSeries a
subclass of dcat:Dataset."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.api._resolver import _resolver_jsonld  # noqa: E402
from battinfo.bundle import Dataset, ProvenanceInfo  # noqa: E402
from battinfo.jsonld import dataset_to_jsonld  # noqa: E402
from battinfo.publication import _dataset_jsonld_node  # noqa: E402
from battinfo.validate.record import validate_record_report  # noqa: E402

SERIES_IRI = "https://w3id.org/battinfo/dataset/aaaa-bbbb-cccc-dddd"
MEMBER_IRI = "https://w3id.org/battinfo/dataset/aaaa-bbbb-cccc-ffff"
CELL_IRI = "https://w3id.org/battinfo/cell/aaaa-bbbb-cccc-eeee"
TEST_IRI = "https://w3id.org/battinfo/test/aaaa-bbbb-cccc-gggg"
CONTEXT_DIR = ROOT / "src" / "battinfo" / "data" / "context"

_PROVENANCE = ProvenanceInfo(
    type="catalog",
    url="https://doi.org/10.5281/zenodo.20086298",
    retrieved_at=1755648000,
)


def _series() -> Dataset:
    return Dataset(
        id=SERIES_IRI,
        name="Half-cell OCV collection",
        access_url="https://doi.org/10.5281/zenodo.20086298",
        additional_type=["DatasetSeries"],
        cell_instance_id=CELL_IRI,
        source=_PROVENANCE,
    )


def _member() -> Dataset:
    return Dataset(
        id=MEMBER_IRI,
        name="Half-cell OCV, cell 1",
        access_url="https://example.org/datasets/member",
        series_id=SERIES_IRI,
        cell_instance_id=CELL_IRI,
        source=_PROVENANCE,
    )


def test_series_id_round_trips_through_the_record() -> None:
    record = _member().to_record()
    assert record["dataset"]["series_id"] == SERIES_IRI
    assert Dataset.from_record(record).series_id == SERIES_IRI


def test_series_flavor_round_trips_through_the_record() -> None:
    record = _series().to_record()
    assert record["dataset"]["additional_type"] == ["DatasetSeries"]
    loaded = Dataset.from_record(record)
    assert loaded.additional_type == ["DatasetSeries"]
    assert loaded.series_id is None


def test_member_emits_both_membership_edges() -> None:
    doc = dataset_to_jsonld(_member().to_record())
    assert doc["dcat:inSeries"] == {"@id": SERIES_IRI}
    assert doc["schema:isPartOf"] == {"@id": SERIES_IRI}
    assert doc["@type"] == "http://www.w3.org/ns/dcat#Dataset"


def test_series_carries_the_dataset_series_type() -> None:
    doc = dataset_to_jsonld(_series().to_record())
    assert doc["@type"] == [
        "http://www.w3.org/ns/dcat#Dataset",
        "http://www.w3.org/ns/dcat#DatasetSeries",
    ]
    assert "dcat:inSeries" not in doc


def test_series_and_member_validate_clean_in_strict_mode() -> None:
    for dataset in (_series(), _member()):
        report = validate_record_report(dataset.to_record(), policy="strict")
        assert not report.issues, [issue.message for issue in report.issues]


def test_schema_rejects_a_non_dataset_series_iri() -> None:
    record = _member().to_record()
    record["dataset"]["series_id"] = "https://example.org/not-a-dataset-iri"
    report = validate_record_report(record, policy="strict")
    assert any(issue.path.endswith("series_id") for issue in report.issues)


def test_publication_node_emits_series_edges_and_type(tmp_path: Path) -> None:
    node = _dataset_jsonld_node(
        _member(), [], tmp_path, TEST_IRI, CELL_IRI, distribution_entries=[]
    )
    assert node["dcat:inSeries"] == {"@id": SERIES_IRI}
    assert node["schema:isPartOf"] == {"@id": SERIES_IRI}

    series_node = _dataset_jsonld_node(
        _series(), [], tmp_path, TEST_IRI, CELL_IRI, distribution_entries=[]
    )
    assert "dcat:DatasetSeries" in series_node["@type"]
    assert "dcat:inSeries" not in series_node


def test_resolver_emits_series_edges_and_type() -> None:
    member_doc = _resolver_jsonld(_member().to_record())
    assert member_doc["dcat:inSeries"] == {"@id": SERIES_IRI}
    assert member_doc["schema:isPartOf"] == {"@id": SERIES_IRI}
    assert member_doc["@type"] == "schema:Dataset"

    series_doc = _resolver_jsonld(_series().to_record())
    assert series_doc["@type"] == ["schema:Dataset", "dcat:DatasetSeries"]


def test_records_contexts_define_the_series_terms() -> None:
    for filename in ("records.context.json", "records.context.v1.json"):
        context = json.loads((CONTEXT_DIR / filename).read_text(encoding="utf-8"))["@context"]
        assert context["DatasetSeries"] == "dcat:DatasetSeries"
        assert context["inSeries"] == {"@id": "dcat:inSeries", "@type": "@id"}


def test_data_catalog_membership_reaches_the_record_emitter() -> None:
    member = _member()
    member.included_in_data_catalog = {
        "type": "DataCatalog",
        "id": "https://example.org/catalog",
        "name": "Example Battery Catalog",
        "url": "https://example.org/catalog",
    }
    doc = dataset_to_jsonld(member.to_record())
    catalog = doc["schema:includedInDataCatalog"]
    assert catalog["@id"] == "https://example.org/catalog"
    assert catalog["schema:name"] == "Example Battery Catalog"

    member.included_in_data_catalog = "https://example.org/catalog"
    doc = dataset_to_jsonld(member.to_record())
    assert doc["schema:includedInDataCatalog"] == {"@id": "https://example.org/catalog"}
