"""The Zenodo deposit graph carries dataset collections and dataset ``about``.

Two defects, both found on the Flores half-cell corpus (95 errors on 96
datasets):

* The deposit builder took a member's schema:about only from the reverse
  mapping ``test.dataset_ids``. A corpus whose datasets name their cell and test
  in ``about`` (and whose tests list no ``dataset_ids``) got no schema:about on
  any member, and the publication validator refused the deposit.
* The deposit graph was not series-aware: a collection (``additional_type =
  "DatasetSeries"``) was emitted as an ordinary member with empty distribution
  arrays, and members carried no dcat:inSeries.

These tests build the record sets directly and assemble the graph with the
shared builder, so they exercise exactly what ``preview_jsonld`` and the Zenodo
upload validate.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.bundle import Cell, CellSpec, Dataset, ProvenanceInfo, Test  # noqa: E402
from battinfo.metadata import checksum, distribution  # noqa: E402
from battinfo.validate import validate_publication_report  # noqa: E402
from battinfo.ws import AuthoringWorkspace  # noqa: E402

CELL_SPEC_IRI = "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-0000"
SERIES_IRI = "https://w3id.org/battinfo/dataset/aaaa-bbbb-cccc-5555"
CREATORS = [{"name": "Doe, Jane", "orcid": "0000-0002-1825-0097"}]


def _cell(n: int) -> str:
    return f"https://w3id.org/battinfo/cell/aaaa-bbbb-cccc-000{n}"


def _test(n: int) -> str:
    return f"https://w3id.org/battinfo/test/aaaa-bbbb-cccc-100{n}"


def _dataset(n: int) -> str:
    return f"https://w3id.org/battinfo/dataset/aaaa-bbbb-cccc-200{n}"


def _record_sets(*, tests_list_datasets: bool, with_series: bool = True) -> dict[str, list[dict]]:
    """One collection plus two member datasets, each on its own cell and test.

    ``tests_list_datasets`` switches between the two ways a corpus links a
    dataset to its test: on the dataset (``about``) only, or also on the test
    (``dataset_ids``).
    """
    sets: dict[str, list[dict]] = {
        "cell-spec": [
            CellSpec(
                id=CELL_SPEC_IRI, name="Demo coin cell", manufacturer="Demo Co", model="DEMO-1",
                format="coin", chemistry="lithium_ion", source=ProvenanceInfo(type="datasheet"),
            ).to_record()
        ],
        "cell-instance": [],
        "test": [],
        "dataset": [],
    }
    for n in (1, 2):
        sets["cell-instance"].append(
            Cell(
                id=_cell(n), name=f"cell-{n}", cell_spec_id=CELL_SPEC_IRI, serial_number=f"SN-{n}",
                source=ProvenanceInfo(type="measurement"),
            ).to_record()
        )
        sets["test"].append(
            Test(
                id=_test(n), name=f"pOCV run {n}", kind="cycling", cell_id=_cell(n),
                dataset_ids=[_dataset(n)] if tests_list_datasets else [],
                source=ProvenanceInfo(type="measurement"),
            ).to_record()
        )
        sets["dataset"].append(
            Dataset(
                id=_dataset(n), name=f"pOCV curves, cell {n}",
                cell_instance_id=_cell(n), test_id=_test(n),
                series_id=SERIES_IRI if with_series else None,
                access_url=f"https://example.org/data/cell-{n}",
                distributions=[
                    distribution(
                        f"https://example.org/data/cell-{n}.bdf.csv",
                        encoding_format="text/csv",
                        checksum_value=checksum("sha256", f"{n}" * 64),
                    )
                ],
                source=ProvenanceInfo(type="measurement"),
            ).to_record()
        )
    if with_series:
        sets["dataset"].append(
            Dataset(
                id=SERIES_IRI, name="pOCV collection", additional_type=["DatasetSeries"],
                access_url="https://example.org/data", source=ProvenanceInfo(type="measurement"),
            ).to_record()
        )
    return sets


def _graph(record_sets: dict[str, list[dict]]) -> dict:
    return AuthoringWorkspace._assemble_zenodo_jsonld(
        record_sets,
        zenodo_record_id=1,
        prereserved_doi="10.5281/zenodo.1",
        record_url="https://zenodo.org/records/1",
        data_filenames=[],
        title="collection deposit",
        creators=CREATORS,
        license="cc-by-4.0",
    )


def _nodes(doc: dict) -> dict[str, dict]:
    return {n["@id"]: n for n in doc["@graph"] if isinstance(n, dict) and "@id" in n}


def _errors(doc: dict) -> list[str]:
    report = validate_publication_report(doc, policy="publisher")
    return [f"{i.code}: {i.message}" for i in report.issues if i.severity == "error"]


def test_collection_deposit_without_dataset_ids_validates_clean() -> None:
    doc = _graph(_record_sets(tests_list_datasets=False))
    assert _errors(doc) == []
    report = validate_publication_report(doc, policy="publisher")
    assert not [i for i in report.issues if "series" in i.code], report.issues


def test_members_carry_their_own_about_and_series_membership() -> None:
    nodes = _nodes(_graph(_record_sets(tests_list_datasets=False)))
    for n in (1, 2):
        member = nodes[_dataset(n)]
        assert member["schema:about"] == [{"@id": _cell(n)}, {"@id": _test(n)}]
        assert member["dcat:inSeries"] == {"@id": SERIES_IRI}
        assert member["schema:isPartOf"] == {"@id": SERIES_IRI}
        # The catalog link is kept next to the series link.
        assert member["dcterms:isPartOf"] == {"@id": "https://zenodo.org/records/1"}
        # The test and cell come from about when no test lists the dataset.
        dist = member["dcat:distribution"][0]
        assert dist["prov:wasGeneratedBy"] == {"@id": _test(n)}
        # ... and the test lists the dataset as its output in return.
        assert nodes[_test(n)]["prov:generated"] == [{"@id": _dataset(n)}]


def test_collection_node_is_a_series_without_distributions() -> None:
    nodes = _nodes(_graph(_record_sets(tests_list_datasets=False)))
    series = nodes[SERIES_IRI]
    assert series["@type"] == ["dcat:Dataset", "schema:Dataset", "dcat:DatasetSeries"]
    assert "dcat:distribution" not in series
    assert "schema:distribution" not in series
    assert "schema:about" not in series
    assert "dcat:inSeries" not in series


def test_dataset_ids_path_still_links_members() -> None:
    """Regression: a corpus whose tests list dataset_ids (and whose datasets carry
    no about of their own) keeps its about link and generated-by provenance."""
    sets = _record_sets(tests_list_datasets=True, with_series=False)
    for rec in sets["dataset"]:
        rec["dataset"].pop("about", None)
    doc = _graph(sets)
    assert _errors(doc) == []
    nodes = _nodes(doc)
    for n in (1, 2):
        member = nodes[_dataset(n)]
        assert member["schema:about"] == [{"@id": _cell(n)}]
        assert member["dcat:distribution"][0]["prov:wasGeneratedBy"] == {"@id": _test(n)}
        assert "dcat:inSeries" not in member
        assert nodes[_test(n)]["prov:generated"] == [{"@id": _dataset(n)}]


def test_both_links_present_are_unioned_without_duplicates() -> None:
    nodes = _nodes(_graph(_record_sets(tests_list_datasets=True)))
    assert nodes[_dataset(1)]["schema:about"] == [{"@id": _cell(1)}, {"@id": _test(1)}]
    assert nodes[_test(1)]["prov:generated"] == [{"@id": _dataset(1)}]


def test_validator_still_requires_about_and_files_on_an_ordinary_dataset() -> None:
    sets = _record_sets(tests_list_datasets=False)
    doc = _graph(sets)
    member = _nodes(doc)[_dataset(1)]
    del member["schema:about"]
    member["schema:distribution"] = []
    codes = {e.split(":", 1)[0] for e in _errors(doc)}
    assert "publication.dataset_about_missing" in codes
    assert "publication.dataset_distribution_missing" in codes


def test_series_member_whose_collection_is_elsewhere_only_warns() -> None:
    """Publishing members after their collection (in another deposit) is the
    documented order, so a dcat:inSeries target outside the package warns."""
    sets = _record_sets(tests_list_datasets=False)
    sets["dataset"] = [r for r in sets["dataset"] if r["dataset"]["id"] != SERIES_IRI]
    doc = _graph(sets)
    assert _errors(doc) == []
    report = validate_publication_report(doc, policy="publisher")
    assert sum(i.code == "publication.series_not_in_package" for i in report.issues) == 2


def test_series_target_that_is_not_a_series_is_an_error() -> None:
    sets = _record_sets(tests_list_datasets=False)
    for rec in sets["dataset"]:
        if rec["dataset"]["id"] == SERIES_IRI:
            rec["dataset"].pop("additional_type")
    doc = _graph(sets)
    errors = _errors(doc)
    assert any(e.startswith("publication.series_target_not_series") for e in errors), errors
