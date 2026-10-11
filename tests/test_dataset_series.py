"""DCAT dataset-series support: a collection is an ordinary dataset record
flavored as a series (additional_type = "DatasetSeries"), membership is the
series_id edge. No new record type; DCAT 3 declares dcat:DatasetSeries a
subclass of dcat:Dataset."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.api import save_dataset  # noqa: E402
from battinfo.api._resolver import _resolver_jsonld  # noqa: E402
from battinfo.bundle import Dataset, ProvenanceInfo  # noqa: E402
from battinfo.jsonld import dataset_to_jsonld  # noqa: E402
from battinfo.publication import _dataset_jsonld_node  # noqa: E402
from battinfo.validate.record import validate_record_report  # noqa: E402
from battinfo.ws import AuthoringWorkspace  # noqa: E402

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
    # Deliberately no cell link: a collection is a grouping record whose members
    # carry the cell links (and point here via series_id).
    return Dataset(
        id=SERIES_IRI,
        name="Half-cell OCV collection",
        access_url="https://doi.org/10.5281/zenodo.20086298",
        additional_type=["DatasetSeries"],
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


def test_series_without_cell_link_is_exempt_but_plain_dataset_is_not() -> None:
    # The dataset_missing_cell_link rule stays for ordinary datasets; only the
    # series flavor is exempt (its members carry the cell links).
    plain = Dataset(
        id=MEMBER_IRI,
        name="no links at all",
        access_url="https://example.org/datasets/orphan",
        source=_PROVENANCE,
    )
    report = validate_record_report(plain.to_record(), policy="strict")
    assert any(issue.code == "semantic.dataset_missing_cell_link" for issue in report.issues)

    series_report = validate_record_report(_series().to_record(), policy="strict")
    assert not any(
        issue.code == "semantic.dataset_missing_cell_link" for issue in series_report.issues
    )


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


# ── Members authored with ws.add("test", data=..., series_id=...) ──────────────

def _workspace_with_cell(root: Path) -> AuthoringWorkspace:
    root.mkdir(parents=True, exist_ok=True)
    draft = {"manufacturer": "Flores Lab", "model": "Gr half cell", "format": "coin", "chemistry": "li-ion"}
    (root / "gr.cell-spec.json").write_text(json.dumps(draft), encoding="utf-8")
    for name in ("C01-a.csv", "C01-b.csv"):
        (root / name).write_text("unix_time_second,voltage\n0,1\n", encoding="utf-8")
    ws = AuthoringWorkspace(root=root, registry_url=None)
    ws.add("cell", spec=ws.load(root / "gr.cell-spec.json"), serial_numbers=["C01"])
    return ws


def _saved(root: Path, folder: str) -> list[dict]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((root / ".battinfo" / "records" / folder).glob("*.json"))
    ]


def test_ws_add_test_puts_every_dataset_from_data_in_the_collection(tmp_path: Path) -> None:
    ws = _workspace_with_cell(tmp_path)
    ws.add("test", type="quasi_ocv", cell="C01", data=["C01-a.csv", "C01-b.csv"], series_id=SERIES_IRI)
    ws.save()
    datasets = _saved(tmp_path, "dataset")
    assert len(datasets) == 2
    assert [d["dataset"]["series_id"] for d in datasets] == [SERIES_IRI, SERIES_IRI]
    (test,) = _saved(tmp_path, "test")
    assert "series_id" not in test["test"]


def test_ws_add_members_are_in_series_in_the_deposit_graph(tmp_path: Path) -> None:
    ws = _workspace_with_cell(tmp_path)
    collection = save_dataset(
        Dataset(
            name="Half-cell OCV collection",
            additional_type=["DatasetSeries"],
            access_url="https://doi.org/10.5281/zenodo.20086298",
            source=_PROVENANCE,
        ),
        source_root=tmp_path / ".battinfo" / "records", mode="upsert",
        validation_policy="strict", build_jsonld=False, build_html=False,
    )
    ws.add("test", type="quasi_ocv", cell="C01", data="C01-a.csv", series_id=collection["id"])
    ws.save()
    preview = ws.preview_jsonld(output=tmp_path / "preview.jsonld")
    graph = json.loads(preview.read_text(encoding="utf-8"))["@graph"]
    nodes = {node["@id"]: node for node in graph if "@id" in node}
    (member,) = [node for node in graph if "dcat:inSeries" in node]
    assert member["dcat:inSeries"] == {"@id": collection["id"]}
    assert member["schema:isPartOf"] == {"@id": collection["id"]}
    assert "dcat:DatasetSeries" in nodes[collection["id"]]["@type"]


@pytest.mark.parametrize(("kwargs", "message"), [
    ({"cell": "C01", "data": "C01-a.csv", "series_id": TEST_IRI}, "not a dataset IRI"),
    ({"cell": "C01", "data": "C01-a.csv", "series_id": "aaaa-bbbb-cccc-dddd"}, "not a dataset IRI"),
    ({"cell": "C01", "data": "C01-a.csv", "series_id": f"{SERIES_IRI}/"}, "not a dataset IRI"),
    ({"cell": "C01", "series_id": SERIES_IRI}, "data="),
    ({"datasets": "*.csv", "series_id": SERIES_IRI}, "data="),
])
def test_ws_add_refuses_a_bad_series_id_before_anything_is_created(
    tmp_path: Path, kwargs: dict, message: str
) -> None:
    ws = _workspace_with_cell(tmp_path)
    with pytest.raises(ValueError, match=message):
        ws.add("test", type="quasi_ocv", **kwargs)
    assert not ws._ws.tests
    assert not ws._ws.datasets


def test_series_id_does_not_move_the_test_or_dataset_iris(tmp_path: Path) -> None:
    """Membership is not identity: the same test and data files mint the same
    IRIs with and without series_id."""
    minted = []
    for series_id in (None, SERIES_IRI):
        shutil.rmtree(tmp_path / ".battinfo", ignore_errors=True)
        ws = _workspace_with_cell(tmp_path)
        ws.add("test", type="quasi_ocv", cell="C01", data=["C01-a.csv", "C01-b.csv"], series_id=series_id)
        ws.save()
        minted.append((
            [test["test"]["id"] for test in _saved(tmp_path, "test")],
            [dataset["dataset"]["id"] for dataset in _saved(tmp_path, "dataset")],
        ))
    assert minted[0] == minted[1]
    assert len(minted[0][1]) == 2
