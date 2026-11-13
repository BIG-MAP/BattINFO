"""What the ``Dataset`` model keeps, refuses and writes out for the people and organizations of a dataset.

An organization of a dataset, cell, test or test-protocol record may carry its BattINFO organization IRI as ``id``, as in every other record type. The ``Dataset`` model keeps a valid one on the publisher, the creators, the funders and a person's affiliations, and refuses any other value. The JSON-LD writers make it the organization node's ``@id``.

A person's ``orcid`` is saved as the ``same_as`` link, the one place the dataset schema has for it. A publisher or an affiliation that states no type is an organization, whatever its other keys.

An organization given with an email is refused when the model is made, since no schema's ``Organization`` takes one, and a person keeps their email.
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


# ── A person's ORCID is their same_as link ───────────────────────────────────

ORCID_ID = "0000-0002-1825-0097"
OTHER_ORCID = "https://orcid.org/0000-0001-5109-3700"


@pytest.mark.parametrize(
    "orcid",
    [ORCID_ID, ORCID, f"http://orcid.org/{ORCID_ID}", f"orcid.org/{ORCID_ID}", f" {ORCID_ID} ", f"{ORCID}/"],
)
def test_a_persons_orcid_becomes_the_same_as_link(orcid: str) -> None:
    dataset = _dataset(
        creators=[{"name": "Carberry, Josiah", "orcid": orcid}],
        funders=[{"name": "Carberry, Josiah", "orcid": orcid, "email": "jc@example.org"}],
    )
    assert dataset.creators == [{"name": "Carberry, Josiah", "type": "Person", "same_as": ORCID}]
    assert dataset.funders == [
        {"name": "Carberry, Josiah", "type": "Person", "email": "jc@example.org", "same_as": ORCID}
    ]


def test_a_dataset_whose_creator_has_an_orcid_saves_and_validates(tmp_path: Path) -> None:
    record = _saved(_dataset(creators=[{"name": "Carberry, Josiah", "orcid": ORCID_ID}]), tmp_path)
    assert record["dataset"]["creators"] == [{"name": "Carberry, Josiah", "type": "Person", "same_as": ORCID}]
    assert validate_schema_data(record, schema_for_rel_path("dataset.schema.json")).issues == ()
    node = record_to_jsonld(record, "dataset")
    assert node["dcterms:creator"] == [{"@type": "schema:Person", "@id": ORCID, "schema:name": "Carberry, Josiah"}]
    assert Dataset.from_record(record).creators == record["dataset"]["creators"]


@pytest.mark.parametrize("orcid", ["not-an-orcid", "0000-0002-1825-009Y", "https://ror.org/01f677e56"])
def test_an_orcid_that_is_none_is_refused_as_ws_contributor_refuses_it(orcid: str, tmp_path: Path) -> None:
    workspace = AuthoringWorkspace(tmp_path, registry_url=None)
    with pytest.raises(ValueError) as from_workspace:
        workspace.contributor(orcid, name="Carberry, Josiah")
    message = str(from_workspace.value)
    assert message.startswith("invalid ORCID iD: ")
    for fields in (
        {"creators": [{"name": "Carberry, Josiah", "orcid": orcid}]},
        {"funders": [{"name": "Carberry, Josiah", "orcid": orcid}]},
    ):
        with pytest.raises(ValueError, match=re.escape(message)):
            Dataset(name="data", **fields)


@pytest.mark.parametrize("same_as", [OTHER_ORCID, "https://example.org/people/jc", "0000-0001-5109-3700"])
def test_an_orcid_beside_another_same_as_is_refused_and_both_are_named(same_as: str) -> None:
    with pytest.raises(ValueError) as refused:
        Dataset(name="data", creators=[{"name": "Carberry, Josiah", "orcid": ORCID_ID, "same_as": same_as}])
    assert repr(ORCID_ID) in str(refused.value)
    assert repr(same_as) in str(refused.value)
    assert "'Carberry, Josiah'" in str(refused.value)


@pytest.mark.parametrize(
    ("same_as", "kept"),
    [(ORCID, ORCID), (f"http://orcid.org/{ORCID_ID}", f"http://orcid.org/{ORCID_ID}"), (ORCID_ID, ORCID)],
)
def test_an_orcid_beside_the_same_orcid_as_same_as_gives_one_link(same_as: str, kept: str) -> None:
    dataset = Dataset(name="data", creators=[{"name": "Carberry, Josiah", "orcid": ORCID_ID, "same_as": same_as}])
    assert dataset.creators == [{"name": "Carberry, Josiah", "type": "Person", "same_as": kept}]


def test_an_organizations_orcid_stays_as_it_was_given() -> None:
    dataset = Dataset(name="data", creators=[{"type": "Organization", "name": "ACME Lab", "orcid": ORCID}])
    assert dataset.creators == [{"name": "ACME Lab", "type": "Organization", "orcid": ORCID}]


# ── A publisher and an affiliation are organizations ─────────────────────────


@pytest.mark.parametrize(
    "extra",
    [{"given_name": "Example"}, {"orcid": ORCID}, {"affiliation": {"name": "Parent"}}],
)
def test_a_publisher_without_a_type_is_an_organization_whatever_its_keys(extra: dict[str, Any]) -> None:
    dataset = Dataset(name="data", publisher={"name": "Example Lab", **extra})
    assert dataset.publisher is not None and dataset.publisher["type"] == "Organization"
    # The same value among the creators is still read as a person.
    assert Dataset(name="data", creators=[{"name": "Example Lab", **extra}]).creators[0]["type"] == "Person"


def test_an_affiliation_without_a_type_is_an_organization() -> None:
    person = {"name": "Doe, Jane", "affiliation": {"name": "Example Lab", "given_name": "Example"}}
    dataset = Dataset(name="data", creators=[person])
    assert dataset.creators[0]["affiliation"]["type"] == "Organization"


def test_a_stated_type_is_kept_and_agents_that_worked_are_typed_as_before() -> None:
    dataset = Dataset(
        name="data",
        publisher={"type": "Person", "name": "Doe, Jane"},
        creators=[
            {"name": "SINTEF"},
            {"name": "Doe, Jane", "email": "jane@example.org"},
            {"type": "Organization", "name": "Example Lab", "given_name": "Example"},
            {"@type": "schema:Person", "name": "Roe, Richard"},
        ],
    )
    assert dataset.publisher == {"name": "Doe, Jane", "type": "Person"}
    assert [creator["type"] for creator in dataset.creators] == ["Organization", "Person", "Organization", "Person"]
    assert Dataset(name="data", publisher={"name": "Example Lab", "url": "https://example.org"}).publisher == {
        "name": "Example Lab",
        "type": "Organization",
        "url": "https://example.org",
    }


# ── An organization carries no email ─────────────────────────────────────────

EMAIL_REFUSAL = (
    "The organization 'Example Lab' is given an email, and BattINFO records carry no email for an organization. "
    "Leave the email out, or give the organization's web page as url."
)


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({"publisher": {"name": "Example Lab", "email": "lab@example.org"}}, id="publisher"),
        pytest.param(
            {"publisher": {"type": "Organization", "name": "Example Lab", "schema:email": "lab@example.org"}},
            id="publisher-typed",
        ),
        pytest.param(
            {"creators": [{"type": "Organization", "name": "Example Lab", "email": "lab@example.org"}]}, id="creator"
        ),
        pytest.param(
            {"funders": [{"@type": "schema:Organization", "name": "Example Lab", "email": "lab@example.org"}]},
            id="funder",
        ),
        pytest.param(
            {"creators": [{"name": "Doe, Jane", "affiliation": {"name": "Example Lab", "email": "lab@example.org"}}]},
            id="creator-affiliation",
        ),
        pytest.param(
            {
                "funders": [
                    {
                        "type": "Person",
                        "name": "Patron, Pat",
                        "email": "pat@example.org",
                        "affiliation": [{"name": "Second Lab"}, {"name": "Example Lab", "email": "lab@example.org"}],
                    }
                ]
            },
            id="funder-affiliation",
        ),
    ],
)
def test_an_organization_with_an_email_is_refused_when_the_dataset_is_made(fields: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match=re.escape(EMAIL_REFUSAL)):
        _dataset(**fields)


def test_a_stored_record_whose_publisher_has_an_email_does_not_load() -> None:
    record = _saved_record_with(publisher={"type": "Organization", "name": "Example Lab", "email": "lab@example.org"})
    with pytest.raises(ValueError, match=re.escape(EMAIL_REFUSAL)):
        Dataset.from_record(record)


def test_a_persons_email_is_kept_and_saved_beside_an_organization_with_a_url(tmp_path: Path) -> None:
    lab = {"name": "Example Lab", "url": "https://example.org"}
    dataset = _dataset(
        publisher=lab,
        creators=[{"name": "Doe, Jane", "email": "jane@example.org", "affiliation": lab}],
        funders=[{"name": "Patron, Pat", "email": "pat@example.org"}],
    )
    organization = {**lab, "type": "Organization"}
    assert dataset.publisher == organization
    # A creator or funder that states no type and has an email is a person, as before.
    assert dataset.creators == [
        {"name": "Doe, Jane", "type": "Person", "email": "jane@example.org", "affiliation": organization}
    ]
    assert dataset.funders == [{"name": "Patron, Pat", "type": "Person", "email": "pat@example.org"}]
    record = _saved(dataset, tmp_path)
    assert validate_schema_data(record, schema_for_rel_path("dataset.schema.json")).issues == ()
