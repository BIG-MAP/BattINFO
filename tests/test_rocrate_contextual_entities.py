"""The RO-Crate of a deposit describes its people and organisations as entities of their own.

- A person's ``@id`` is the ORCID URL, else ``#person-`` and a slug of the
  name; an organisation's is the ROR URL, else ``#org-`` and a slug of the
  name. The root dataset and each person point at them by ``@id``, so every
  entity is a direct entry of the ``@graph`` (RO-Crate 1.1 is flattened
  JSON-LD).
- Someone listed as a creator and as a contributor is one entity, and it
  keeps the Zenodo contributor type as ``roleName``.
- Two different names never share an ``@id``, and the ids do not depend on
  the order of the names.
- ``ws.validate_rocrate()`` reads the crate with the rocrate library and
  checks that it is flat. ``ws.zenodo()`` runs the same check and only warns
  (see ``test_zenodo_deposit_order.py``).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import battinfo
from battinfo._deposit_files import DepositFile, DepositFilePlan
from battinfo.ws import (
    AuthoringWorkspace,
    _crate_local_ids,
    _planned_deposit_files,
    _rocrate_agents,
    _rocrate_check,
    _rocrate_shape_problems,
)

ORCID = "0000-0002-1825-0097"
ORCID_X = "0000-0002-1694-233X"
ROR = "03yrm5c26"


def _workspace(root: Path) -> AuthoringWorkspace:
    ws = battinfo.workspace(root, registry_url=None)
    spec = battinfo.CellSpec(manufacturer="Example Lab", model="R2032", format="coin", chemistry="li-ion")
    ws.add("cell", spec=spec, serial_numbers=["C01"])
    ws.add("test", type="cycling", cell="C01")
    ws.save()
    return ws


def _entities(crate: dict) -> dict[str, dict]:
    return {node["@id"]: node for node in crate["@graph"]}


def _people(entities: list[dict]) -> dict[str, dict]:
    return {node["@id"]: node for node in entities if node["@type"] == "Person"}


# ── The crate the preview writes ─────────────────────────────────────────────


def test_a_creator_without_an_orcid_and_with_an_affiliation_is_an_entity_of_its_own(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pytest.importorskip("rocrate")
    ws = _workspace(tmp_path)
    creators = [{"name": "Doe, Jane", "affiliation": "Example Lab"}]
    contributors = [{"name": "Lovelace, Ada", "orcid": ORCID, "affiliation": "Example Lab", "type": "DataCurator"}]
    capsys.readouterr()
    path = ws.preview_rocrate(creators=creators, contributors=contributors)
    assert "RO-Crate check: PASS" in capsys.readouterr().out

    crate = json.loads(path.read_text(encoding="utf-8"))
    entities = _entities(crate)
    root = entities["./"]
    assert root["creator"] == {"@id": "#person-doe-jane"}
    assert root["contributor"] == {"@id": f"https://orcid.org/{ORCID}"}
    assert entities["#person-doe-jane"] == {
        "@id": "#person-doe-jane",
        "@type": "Person",
        "name": "Doe, Jane",
        "affiliation": {"@id": "#org-example-lab"},
    }
    assert entities[f"https://orcid.org/{ORCID}"] == {
        "@id": f"https://orcid.org/{ORCID}",
        "@type": "Person",
        "name": "Lovelace, Ada",
        "affiliation": {"@id": "#org-example-lab"},
        "roleName": "DataCurator",
    }
    # One organisation for both people, described once.
    assert entities["#org-example-lab"] == {"@id": "#org-example-lab", "@type": "Organization", "name": "Example Lab"}
    assert [node["@id"] for node in crate["@graph"]].count("#org-example-lab") == 1

    assert _rocrate_shape_problems(crate) == []
    assert _rocrate_check(crate) == ([], "")
    assert ws.validate_rocrate(path) is True
    assert "Valid RO-Crate 1.1" in capsys.readouterr().out


# ── People and organisations ─────────────────────────────────────────────────


def test_a_creator_who_is_also_a_contributor_is_one_entity_that_keeps_the_role() -> None:
    creators = [
        {"name": "Lovelace, Ada", "orcid": ORCID, "affiliation": "Example Lab"},
        {"name": "Doe, Jane", "affiliation": "Example Lab"},
    ]
    contributors = [
        {"name": "Lovelace, Ada", "orcid": ORCID, "type": "DataCurator"},
        {"name": "Doe, Jane", "type": "Supervisor"},
        {"name": "Doe,  Jane", "type": "ProjectLeader"},  # the same name, spaced otherwise
    ]
    creator_refs, contributor_refs, entities = _rocrate_agents(creators, contributors)

    people = _people(entities)
    assert set(people) == {f"https://orcid.org/{ORCID}", "#person-doe-jane"}
    assert creator_refs == [{"@id": f"https://orcid.org/{ORCID}"}, {"@id": "#person-doe-jane"}]
    assert contributor_refs == creator_refs
    assert people[f"https://orcid.org/{ORCID}"]["roleName"] == "DataCurator"
    assert people["#person-doe-jane"]["roleName"] == ["Supervisor", "ProjectLeader"]
    # The affiliation given with the creator entry stays.
    assert people["#person-doe-jane"]["affiliation"] == {"@id": "#org-example-lab"}


def test_an_entry_without_an_orcid_is_the_person_with_the_only_orcid_of_that_name() -> None:
    creators = [{"name": "Lovelace, Ada", "orcid": ORCID}]
    contributors = [{"name": "Lovelace, Ada", "type": "DataCurator"}]
    creator_refs, contributor_refs, entities = _rocrate_agents(creators, contributors)
    assert creator_refs == contributor_refs == [{"@id": f"https://orcid.org/{ORCID}"}]
    assert len(entities) == 1 and entities[0]["roleName"] == "DataCurator"


def test_people_of_one_name_with_different_orcids_stay_apart() -> None:
    creators = [{"name": "Lee, Kim", "orcid": ORCID}, {"name": "Lee, Kim", "orcid": ORCID_X}]
    contributors = [{"name": "Lee, Kim"}]  # which of the two is not known
    creator_refs, contributor_refs, entities = _rocrate_agents(creators, contributors)
    assert creator_refs == [{"@id": f"https://orcid.org/{ORCID}"}, {"@id": f"https://orcid.org/{ORCID_X}"}]
    assert contributor_refs == [{"@id": "#person-lee-kim"}]
    assert len(_people(entities)) == 3


def test_an_organisation_takes_its_ror_and_is_one_entity() -> None:
    creators = [
        {
            "name": "Doe, Jane",
            "affiliation": ["Example Lab", "Second Lab"],
            "affiliation_ror": f"https://ror.org/{ROR}",
        },
        {"name": "Roe, Rick", "affiliation": "Example Lab"},  # the same organisation, without the ROR
    ]
    _creators, _contributors, entities = _rocrate_agents(creators, [])
    people = _people(entities)
    organisations = {node["@id"]: node for node in entities if node["@type"] == "Organization"}
    ror = f"https://ror.org/{ROR}"
    assert organisations == {
        ror: {"@id": ror, "@type": "Organization", "name": "Example Lab"},
        "#org-second-lab": {"@id": "#org-second-lab", "@type": "Organization", "name": "Second Lab"},
    }
    # The ROR names the first affiliation only.
    assert people["#person-doe-jane"]["affiliation"] == [{"@id": ror}, {"@id": "#org-second-lab"}]
    assert people["#person-roe-rick"]["affiliation"] == {"@id": ror}


def test_people_and_organisations_come_after_the_files_and_nothing_is_nested(tmp_path: Path) -> None:
    crate = AuthoringWorkspace._rocrate_metadata(
        [DepositFile(path=tmp_path / "a.csv", name="a b.csv", segment="a%20b.csv")],
        title="T",
        description="D",
        creators=[{"name": "Doe, Jane", "affiliation": "Example Lab"}],
        contributors=[],
        license="cc-by-4.0",
        zenodo_record_id=0,
        prereserved_doi="10.5281/zenodo.RECORD_ID",
    )
    assert [node["@id"] for node in crate["@graph"]] == [
        "ro-crate-metadata.json",
        "./",
        "battinfo.json",
        "a%20b.csv",
        "#person-doe-jane",
        "#org-example-lab",
    ]
    assert _rocrate_shape_problems(crate) == []


# ── Local identifiers ────────────────────────────────────────────────────────


def _digest(name: str, digits: int = 12) -> str:
    return hashlib.sha256(name.encode("utf-8")).hexdigest()[:digits]


def test_names_that_share_a_slug_get_different_ids_whatever_their_order() -> None:
    names = ["Doe, Jane", "Doe Jane", "Lee", "李雷"]  # the last has no ASCII letters
    ids = _crate_local_ids(names, "person")
    assert ids == {
        "Doe, Jane": f"#person-doe-jane-{_digest('Doe, Jane')}",
        "Doe Jane": f"#person-doe-jane-{_digest('Doe Jane')}",
        "Lee": "#person-lee",
        "李雷": f"#person-{_digest(chr(0x674E) + chr(0x96F7))}",
    }
    assert _crate_local_ids(reversed(names), "person") == ids
    assert _crate_local_ids(["Müller, Jürgen"], "person") == {"Müller, Jürgen": "#person-muller-jurgen"}


def test_a_name_whose_slug_is_another_names_id_gets_the_full_digest() -> None:
    clash = f"x y {_digest('x y')}"  # its slug is the id "x y" gets next to "x, y"
    ids = _crate_local_ids(["x y", "x, y", clash], "org")
    assert len(set(ids.values())) == 3
    assert ids["x y"] == f"#org-x-y-{_digest('x y', 64)}"
    assert ids[clash] == f"#org-x-y-{_digest('x y')}-{_digest(clash, 64)}"


# ── The check ────────────────────────────────────────────────────────────────


def _crate(*entities: dict, creator: object = None) -> dict:
    root: dict = {"@id": "./", "@type": "Dataset", "datePublished": "2026-01-01", "hasPart": []}
    if creator is not None:
        root["creator"] = creator
    return {
        "@context": "https://w3id.org/ro/crate/1.1/context",
        "@graph": [
            {
                "@id": "ro-crate-metadata.json",
                "@type": "CreativeWork",
                "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
                "about": {"@id": "./"},
            },
            root,
            *entities,
        ],
    }


def test_the_check_finds_entities_described_in_place_and_ids_that_go_nowhere() -> None:
    nested = {
        "@id": "#person-doe-jane",
        "@type": "Person",
        "name": "Doe, Jane",
        "affiliation": {"@type": "Organization", "name": "Example Lab"},
    }
    [problem] = _rocrate_shape_problems(_crate(creator=[nested]))
    assert problem.startswith("./ describes its 'creator' in place (Person Doe, Jane)")

    [problem] = _rocrate_shape_problems(_crate(creator={"@id": "#person-roe-rick"}))
    assert problem == "./ points at #person-roe-rick under 'creator', which the @graph does not describe"

    person = {"@id": "#p", "@type": "Person", "name": "P"}
    problems = _rocrate_shape_problems(_crate(person, person, {"@type": "Person"}, creator={"@id": "#p"}))
    assert problems == ["#p is described more than once in the @graph", "@graph entry 5 has no @id"]

    # An ORCID or ROR reference need not be described in the crate, and a value object is no entity.
    assert _rocrate_shape_problems(_crate(creator=[{"@id": f"https://orcid.org/{ORCID}"}, {"@value": "x"}])) == []


def test_validate_rocrate_fails_a_crate_the_rocrate_library_alone_would_accept(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pytest.importorskip("rocrate")
    ws = battinfo.workspace(tmp_path, registry_url=None)
    nested = {
        "@id": "#person-doe-jane",
        "@type": "Person",
        "name": "Doe, Jane",
        "affiliation": {"@type": "Organization", "name": "Example Lab"},
    }
    (tmp_path / "ro-crate-metadata.json").write_text(json.dumps(_crate(creator=nested)), encoding="utf-8")
    flat = _crate(
        {"@id": "#person-doe-jane", "@type": "Person", "name": "Doe, Jane", "affiliation": {"@id": "#org-example-lab"}},
        {"@id": "#org-example-lab", "@type": "Organization", "name": "Example Lab"},
        creator={"@id": "#person-doe-jane"},
    )
    (tmp_path / "ro-crate-metadata.preview.json").write_text(json.dumps(flat), encoding="utf-8")
    capsys.readouterr()

    assert ws.validate_rocrate(tmp_path) is False  # the folder: ro-crate-metadata.json
    assert "Validation failed: ./ describes its 'creator' in place (Person Doe, Jane)" in capsys.readouterr().out
    # A file named is the file checked, even with ro-crate-metadata.json beside it.
    assert ws.validate_rocrate(tmp_path / "ro-crate-metadata.preview.json") is True


def test_a_person_without_an_id_fails_with_what_the_rocrate_library_says(tmp_path: Path) -> None:
    pytest.importorskip("rocrate")
    problems, unread = _rocrate_check(_crate(creator={"@type": "Person", "name": "Doe, Jane"}))
    assert unread == ""
    assert problems[0].startswith("the rocrate library cannot read it: no @id in")
    assert problems[1].startswith("./ describes its 'creator' in place (Person Doe, Jane)")


# ── The files of a crate made before the archives are packed ─────────────────


def test_a_zipped_deposit_lists_its_archives_and_the_files_it_keeps(tmp_path: Path) -> None:
    plan = DepositFilePlan(
        root=tmp_path,
        files=[
            DepositFile(path=tmp_path / "a.csv", name="a.csv", segment="a.csv", kind="cycling", archive="cycling.zip"),
            DepositFile(path=tmp_path / "b.csv", name="b.csv", segment="b.csv", kind="cycling", archive="cycling.zip"),
            DepositFile(path=Path(), name="old.csv", segment="old.csv", kept=True),
        ],
        zipped=True,
    )
    assert [entry.name for entry in _planned_deposit_files(plan)] == ["cycling.zip", "old.csv"]
    plan.zipped = False
    assert _planned_deposit_files(plan) == plan.files
