"""The people and organizations of a dataset: what the model keeps, refuses and writes out.

An organization of a dataset, cell, test or test-protocol record may carry its
BattINFO organization IRI as ``id``, as in every other record type. The
``Dataset`` model keeps a valid one on the publisher, the creators, the funders
and a person's affiliations, and refuses any other value; the JSON-LD writers
make it the organization node's ``@id``.
"""

from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import Dataset, save_dataset  # noqa: E402
from battinfo.jsonld import record_to_jsonld  # noqa: E402
from battinfo.namespace import record_iri_forms  # noqa: E402
from battinfo.validate import record_fidelity_report  # noqa: E402
from battinfo.validate.schema import schema_for_rel_path, validate_schema_data  # noqa: E402
from battinfo.ws import AuthoringWorkspace  # noqa: E402

UID = "b6yn-0sxe-t2qk-9mjv"
OLD_FORM = f"https://w3id.org/battinfo/organization/{UID}"
PREFIXED = f"https://w3id.org/battinfo/id/1001/organization/{UID}"
THING = f"https://w3id.org/battinfo/id/{UID}"
ROR = "https://ror.org/01f677e56"
ORCID = "https://orcid.org/0000-0002-1825-0097"
ORGANIZATION_FORMS = record_iri_forms("organization", things=True)


def _organization(iri: Any, name: str = "Example Lab") -> dict[str, Any]:
    return {"type": "Organization", "name": name, "id": iri}


def _dataset(**fields: Any) -> Dataset:
    return Dataset(name="data", access_url="https://example.org/data", **fields)


def _saved(dataset: Dataset, root: Path) -> dict[str, Any]:
    result = save_dataset(dataset, source_root=root, resolve_references=False)
    return json.loads(Path(result["path"]).read_text(encoding="utf-8"))


def _example(relative: str) -> dict[str, Any]:
    return json.loads((ROOT / "examples" / relative).read_text(encoding="utf-8"))


# ── The model keeps an organization's id ─────────────────────────────────────


def test_a_publisher_keeps_its_organization_iri() -> None:
    dataset = Dataset(name="data", publisher=_organization(PREFIXED))
    assert dataset.publisher == {"name": "Example Lab", "type": "Organization", "id": PREFIXED}


@pytest.mark.parametrize("iri", [OLD_FORM, PREFIXED, f"https://w3id.org/battinfo/id/1002/organization/{UID}", THING])
def test_every_organization_of_a_dataset_keeps_its_iri_in_each_accepted_form(iri: str) -> None:
    dataset = _dataset(
        publisher=_organization(iri),
        creators=[_organization(iri), {"name": "Doe, Jane", "affiliation": {"name": "Example Lab", "id": iri}}],
        funders=[
            {"name": "Example Fund", "id": iri},
            {"type": "Person", "name": "Patron, Pat", "affiliation": [_organization(iri), {"name": "Second Lab"}]},
        ],
    )
    assert dataset.publisher is not None and dataset.publisher["id"] == iri
    assert dataset.creators[0]["id"] == iri
    assert dataset.creators[1]["affiliation"] == {"name": "Example Lab", "type": "Organization", "id": iri}
    assert dataset.funders[0] == {"name": "Example Fund", "type": "Organization", "id": iri}
    assert [org.get("id") for org in dataset.funders[1]["affiliation"]] == [iri, None]


@pytest.mark.parametrize(
    "iri",
    [
        ROR,
        f"https://w3id.org/battinfo/cell/{UID}",
        f"https://w3id.org/battinfo/id/1/organization/{UID}",
        f"https://w3id.org/battinfo/organization/{UID}/",
        f"{OLD_FORM}\n",
        UID,
        7,
    ],
)
def test_an_id_that_is_not_an_organization_iri_is_refused_wherever_it_is_given(iri: Any) -> None:
    affiliated = {"name": "Doe, Jane", "affiliation": _organization(iri)}
    for fields in (
        {"publisher": _organization(iri)},
        {"creators": [_organization(iri)]},
        {"funders": [_organization(iri)]},
        {"creators": [affiliated]},
        {"funders": [affiliated]},
    ):
        with pytest.raises(ValueError, match=re.escape(ORGANIZATION_FORMS)) as refused:
            Dataset(name="data", **fields)
        assert "'Example Lab'" in str(refused.value)
        assert repr(iri) in str(refused.value)


def test_a_stored_record_with_a_bad_organization_id_does_not_load() -> None:
    record = _saved_record_with(publisher=_organization(ROR))
    with pytest.raises(ValueError, match=re.escape(ORGANIZATION_FORMS)):
        Dataset.from_record(record)


def _saved_record_with(**dataset_fields: Any) -> dict[str, Any]:
    record = _example("dataset/dataset-1f8r-6v2k-9p4m-3t7x.json")
    record["dataset"].update(dataset_fields)
    return record


@pytest.mark.parametrize("blank", [None, ""])
def test_an_empty_id_is_left_out(blank: Any) -> None:
    dataset = Dataset(name="data", publisher=_organization(blank), creators=[_organization(blank)])
    assert dataset.publisher == {"name": "Example Lab", "type": "Organization"}
    assert dataset.creators == [{"name": "Example Lab", "type": "Organization"}]


def test_a_dataset_with_organization_iris_saves_validates_and_reads_back(tmp_path: Path) -> None:
    dataset = _dataset(
        publisher={**_organization(PREFIXED), "same_as": ROR},
        creators=[_organization(OLD_FORM), {"name": "Doe, Jane", "affiliation": _organization(THING)}],
        funders=[_organization(PREFIXED, "Example Fund")],
    )
    record = _saved(dataset, tmp_path)
    body = record["dataset"]
    assert body["publisher"] == {"name": "Example Lab", "type": "Organization", "id": PREFIXED, "same_as": ROR}
    assert body["creators"][0]["id"] == OLD_FORM
    assert body["creators"][1]["affiliation"]["id"] == THING
    assert body["funders"][0]["id"] == PREFIXED
    assert validate_schema_data(record, schema_for_rel_path("dataset.schema.json")).issues == ()
    loaded = Dataset.from_record(record)
    assert loaded.publisher == dataset.publisher
    assert loaded.creators == dataset.creators
    assert loaded.funders == dataset.funders
    assert loaded.to_record()["dataset"] == body


# ── The JSON-LD writers make it the node's @id ───────────────────────────────


def test_the_jsonld_of_a_dataset_names_each_organization_by_its_iri() -> None:
    record = _saved_record_with(
        publisher={**_organization(PREFIXED), "same_as": ROR},
        creators=[
            _organization(OLD_FORM),
            {"type": "Person", "name": "Doe, Jane", "affiliation": _organization(THING)},
        ],
        funders=[
            _organization(PREFIXED, "Example Fund"),
            {"type": "Person", "name": "Patron, Pat", "same_as": ORCID, "affiliation": _organization(OLD_FORM)},
        ],
    )
    node = record_to_jsonld(record, "dataset")
    assert node["dcterms:publisher"] == {
        "@id": PREFIXED,
        "@type": "schema:Organization",
        "schema:name": "Example Lab",
        "schema:sameAs": {"@id": ROR},
    }
    organization, person = node["dcterms:creator"]
    assert organization == {"@id": OLD_FORM, "@type": "schema:Organization", "schema:name": "Example Lab"}
    assert person["schema:affiliation"] == {"@id": THING, "@type": "schema:Organization", "schema:name": "Example Lab"}
    fund, patron = node["schema:funder"]
    assert fund == {"@id": PREFIXED, "@type": "schema:Organization", "schema:name": "Example Fund"}
    assert patron["@id"] == ORCID
    assert patron["schema:affiliation"]["@id"] == OLD_FORM


def test_a_dataset_without_funders_writes_no_funder() -> None:
    node = record_to_jsonld(_example("dataset/dataset-1f8r-6v2k-9p4m-3t7x.json"), "dataset")
    assert "schema:funder" not in node


@pytest.mark.parametrize(
    ("kind", "relative"),
    [
        ("dataset", "dataset/dataset-1f8r-6v2k-9p4m-3t7x.json"),
        ("cell-instance", "cell-instance/cell-3m6k-9t2p-7x4h-9nq8.json"),
        ("test", "test/test-5p7v-2n8k-4m3t-6q9r.json"),
        ("test-protocol", "test-protocol/test-protocol-2k9p-7t4r-3m6x-5n1v.json"),
    ],
)
def test_the_jsonld_of_each_record_type_names_a_contributors_affiliation_by_its_iri(kind: str, relative: str) -> None:
    record = _example(relative)
    record["contributor"] = [
        {"type": "Person", "name": "Doe, Jane", "same_as": ORCID, "affiliation": _organization(PREFIXED)}
    ]
    (person,) = record_to_jsonld(record, kind)["schema:contributor"]
    assert person["schema:affiliation"] == {
        "@id": PREFIXED,
        "@type": "schema:Organization",
        "schema:name": "Example Lab",
    }


def test_a_deposits_member_dataset_names_its_organizations_and_the_check_names_its_funders() -> None:
    """The deposit graph writes a member's publisher and creators as the record's own JSON-LD does.

    It carries no funders, which the record fidelity check reports by name.
    """
    dataset_id = "https://w3id.org/battinfo/dataset/aaaa-bbbb-cccc-3000"
    cell_id = "https://w3id.org/battinfo/cell/aaaa-bbbb-cccc-1000"
    test_id = "https://w3id.org/battinfo/test/aaaa-bbbb-cccc-2000"
    dataset = {
        "dataset": {
            "id": dataset_id,
            "name": "d1",
            "about": [cell_id, test_id],
            "publisher": _organization(PREFIXED),
            "creators": [
                _organization(OLD_FORM),
                {"type": "Person", "name": "Doe, Jane", "affiliation": _organization(THING)},
            ],
            "funders": [_organization(PREFIXED, "Example Fund")],
        }
    }
    record_sets = {
        "cell-spec": [],
        "cell-instance": [{"cell_instance": {"id": cell_id, "name": "c1"}}],
        "test": [{"test": {"id": test_id, "cell_id": cell_id, "kind": "cycling", "dataset_ids": [dataset_id]}}],
        "test-protocol": [],
        "dataset": [dataset],
    }
    graph = AuthoringWorkspace._assemble_zenodo_jsonld(
        copy.deepcopy(record_sets),
        zenodo_record_id=0,
        prereserved_doi="10.5281/zenodo.1",
        record_url="https://zenodo.org/records/1",
        data_filenames=[],
        title="t",
        description="d",
        creators=[{"name": "Deposit Person"}],
        license="cc-by-4.0",
    )
    member = next(node for node in graph["@graph"] if node.get("@id") == dataset_id)
    assert member["dcterms:publisher"]["@id"] == PREFIXED
    assert member["schema:creator"][0]["@id"] == OLD_FORM
    assert member["schema:creator"][1]["schema:affiliation"]["@id"] == THING
    assert "schema:funder" not in member
    report = record_fidelity_report(graph, record_sets)
    assert [issue.path for issue in report.issues if issue.path.endswith(".funders")] == [
        f"dataset:{dataset_id}.funders"
    ]
