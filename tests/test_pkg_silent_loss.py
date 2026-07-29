"""Regression tests for the silent-loss defect class in the authoring package.

Each test pins a case where the package used to accept input and quietly drop or
misstate it (several while printing "Gold-standard: PASS"). Grouped by the
numbered remediation items they close. All tests run offline.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import TestSpec, quantity  # noqa: E402
from battinfo.ws import AuthoringWorkspace  # noqa: E402


# ── shared authoring helpers ───────────────────────────────────────────────────

def _new_ws(tmp_path: Path) -> AuthoringWorkspace:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    (tmp_path / "d.cell-spec.json").write_text(
        '{"manufacturer":"X","model":"Y","format":"pouch","chemistry":"nmc"}',
        encoding="utf-8",
    )
    spec = ws.load(tmp_path / "d.cell-spec.json")
    ws.add("cell", spec=spec, serial_numbers=["SN-1"])
    (tmp_path / "f.csv").write_text("a,b\n0,1\n", encoding="utf-8")
    return ws


def _rich_protocol() -> TestSpec:
    return TestSpec(
        name="500-cycle CCCV",
        kind="cycling",
        experiment=["Discharge at 1C until 2.5V", "Charge at 0.5C until 4.2V"],
        cycles=500,
        conditions={"temperature": quantity(25, "degC")},
        safety={"max_voltage_V": 4.3, "min_voltage_V": 2.4, "max_temperature_degC": 60},
    )


def _read_one(ws: AuthoringWorkspace, subdir: str) -> dict:
    return json.loads(next((ws._ws.source_root / subdir).glob("*.json")).read_text(encoding="utf-8"))


# ── Item 1: ws.add("test", spec=...) never silently drops the protocol ──────────

def test_add_test_with_testspec_object_saves_protocol_and_links(tmp_path: Path) -> None:
    ws = _new_ws(tmp_path)
    ws.add("test", cell="SN-1", data="f.csv", spec=_rich_protocol())
    result = ws.save()

    # The protocol is persisted as its own record (not reduced to a name string).
    assert len(result["test_specs"]) == 1
    proto = _read_one(ws, "test-protocol")
    proto_id = proto["test_spec"]["id"]
    assert proto.get("method"), "the authored method must survive into the record"
    assert proto["safety"]["max_temperature_degC"] == 60
    assert proto["conditions"]["temperature"]["value"] == 25

    # The test record links to the saved protocol by IRI (protocol_id not null).
    test = _read_one(ws, "test")["test"]
    assert test["protocol_id"] == proto_id


def _fresh_session_with_cell(tmp_path: Path, serial: str) -> AuthoringWorkspace:
    """A new session on the SAME workspace root (as a returning user would open),
    carrying a fresh cell to attach a referencing test to."""
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    spec = ws.load(tmp_path / "d.cell-spec.json")
    ws.add("cell", spec=spec, serial_numbers=[serial])
    return ws


def test_add_test_with_protocol_iri_references_existing(tmp_path: Path) -> None:
    ws = _new_ws(tmp_path)
    ws.add("test", cell="SN-1", data="f.csv", spec=_rich_protocol())
    ws.save()
    proto_id = _read_one(ws, "test-protocol")["test_spec"]["id"]
    n_protocols = len(list((ws._ws.source_root / "test-protocol").glob("*.json")))

    # A returning session references the saved protocol purely by IRI.
    ws2 = _fresh_session_with_cell(tmp_path, "SN-2")
    ws2.add("test", cell="SN-2", data="f.csv", spec=proto_id)
    result = ws2.save()

    # Referencing does not mint a duplicate protocol record ...
    assert result["test_specs"] == []
    assert len(list((ws._ws.source_root / "test-protocol").glob("*.json"))) == n_protocols
    # ... but the run still links to the referenced protocol IRI.
    linked = [
        json.loads(p.read_text(encoding="utf-8"))["test"]
        for p in (ws2._ws.source_root / "test").glob("*.json")
    ]
    assert any(t["protocol_id"] == proto_id for t in linked)


def test_add_test_iri_reference_resolves_kind_from_saved_record(tmp_path: Path) -> None:
    ws = _new_ws(tmp_path)
    ws.add("test", cell="SN-1", data="f.csv", spec=_rich_protocol())
    ws.save()
    proto_id = _read_one(ws, "test-protocol")["test_spec"]["id"]

    ws2 = _fresh_session_with_cell(tmp_path, "SN-2")
    # No explicit type= — the kind must be resolved from the referenced record.
    ws2.add("test", cell="SN-2", data="f.csv", spec=proto_id)
    ws2.save()
    linked = [
        json.loads(p.read_text(encoding="utf-8"))["test"]
        for p in (ws2._ws.source_root / "test").glob("*.json")
    ]
    ref = next(t for t in linked if t["protocol_id"] == proto_id)
    assert ref["kind"] == "cycling"


def test_add_test_rejects_plain_string_spec(tmp_path: Path) -> None:
    ws = _new_ws(tmp_path)
    with pytest.raises(ValueError, match="not a test-protocol reference"):
        ws.add("test", type="cycling", cell="SN-1", data="f.csv", spec="my nice protocol")


def test_add_test_rejects_non_testspec_object(tmp_path: Path) -> None:
    ws = _new_ws(tmp_path)
    with pytest.raises(TypeError, match="battinfo.TestSpec"):
        ws.add("test", type="cycling", cell="SN-1", data="f.csv", spec=object())


# ── Item 2: ws.contributor accumulates (no last-write-wins author loss) ─────────

ORCID_A = "0000-0002-1825-0097"
ORCID_B = "0000-0001-5109-3700"
ORCID_A_URL = f"https://orcid.org/{ORCID_A}"
ORCID_B_URL = f"https://orcid.org/{ORCID_B}"


def _contributor_orcids(record: dict) -> list[str]:
    return [c.get("same_as") for c in record.get("contributor", []) if isinstance(c, dict)]


def test_two_contributor_calls_keep_both_authors(tmp_path: Path) -> None:
    ws = _new_ws(tmp_path)
    ws.contributor(ORCID_A, name="Jane Researcher")
    ws.contributor(ORCID_B, name="Alex Coauthor")  # must NOT erase the first author

    state = json.loads((tmp_path / ".battinfo" / "workspace.json").read_text(encoding="utf-8"))
    orcids = [c["orcid"] for c in state["contributor"]]
    assert orcids == [ORCID_A, ORCID_B]  # both kept, in call order


def test_both_contributors_stamped_on_every_record(tmp_path: Path) -> None:
    ws = _new_ws(tmp_path)
    ws.add("test", type="capacity_check", cell="SN-1", data="f.csv")
    ws.contributor(ORCID_A, name="Jane Researcher")
    ws.contributor(ORCID_B, name="Alex Coauthor")
    ws.save(validation_policy="strict")

    for p in ws._records_root.rglob("*.json"):
        if "index" in p.name:
            continue
        rec = json.loads(p.read_text(encoding="utf-8"))
        orcids = _contributor_orcids(rec)
        assert ORCID_A_URL in orcids and ORCID_B_URL in orcids, p.name


def test_repeat_orcid_updates_in_place_no_duplicate(tmp_path: Path) -> None:
    ws = _new_ws(tmp_path)
    ws.contributor(ORCID_A, name="Jane Researcher")
    ws.contributor(ORCID_B, name="Alex Coauthor")
    ws.contributor(ORCID_A, name="Jane Researcher", affiliation="SINTEF")  # same ORCID

    state = json.loads((tmp_path / ".battinfo" / "workspace.json").read_text(encoding="utf-8"))
    entries = state["contributor"]
    assert [c["orcid"] for c in entries] == [ORCID_A, ORCID_B]  # no duplicate, order kept
    assert entries[0]["affiliation"] == "SINTEF"  # updated in place


def test_legacy_scalar_contributor_upgraded_on_load(tmp_path: Path) -> None:
    # A workspace.json written by the old single-valued code carries a scalar dict.
    battinfo_dir = tmp_path / ".battinfo"
    battinfo_dir.mkdir(parents=True, exist_ok=True)
    (battinfo_dir / "workspace.json").write_text(
        json.dumps({"schema_version": "0.1.0",
                    "contributor": {"orcid": ORCID_A, "name": "Jane Researcher"}}),
        encoding="utf-8",
    )
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    refs = ws._get_contributors()
    assert [r.orcid for r in refs] == [ORCID_A]
    # A subsequent add accumulates rather than overwriting the migrated author.
    ws.contributor(ORCID_B, name="Alex Coauthor")
    assert [r.orcid for r in ws._get_contributors()] == [ORCID_A, ORCID_B]


# ── Item 3: contributors reach the publication/preview bundle ───────────────────

def _person_ids(graph: dict) -> set[str]:
    ids: set[str] = set()
    for node in graph.get("@graph", []):
        for person in node.get("schema:contributor", []) or []:
            if isinstance(person, dict) and person.get("@id"):
                ids.add(person["@id"])
    return ids


def test_contributors_appear_in_preview_bundle_without_recreators(tmp_path: Path) -> None:
    ws = _new_ws(tmp_path)
    ws.add("test", type="capacity_check", cell="SN-1", data="f.csv")
    ws.contributor(ORCID_A, name="Jane Researcher")
    ws.contributor(ORCID_B, name="Alex Coauthor")
    ws.save()

    # The publication graph is built with NO creators=/contributors= re-passed;
    # the workspace contributors must still be credited.
    jsonld = ws._build_zenodo_jsonld(
        zenodo_record_id=0,
        prereserved_doi="10.5281/zenodo.RECORD_ID",
        record_url="https://zenodo.org/records/RECORD_ID",
        data_filenames=[],
        title="t",
        description="d",
    )
    ids = _person_ids(jsonld)
    assert ORCID_A_URL in ids and ORCID_B_URL in ids
    # A Person node and the raw ORCID string are present (regression: the bundle
    # emitter used to drop both while printing "Gold-standard: PASS").
    blob = json.dumps(jsonld)
    assert ORCID_A in blob and "schema:Person" in blob


# ── Item 4: the unmapped-property walker reaches every property holder ──────────

def test_unmapped_property_warns_at_every_nested_holder() -> None:
    from battinfo.validate.semantic import validate_semantic_report

    qty = {"value": 1.0, "unit": "1"}
    doc = {
        "cell_spec": {"id": "https://w3id.org/battinfo/spec/x"},
        "positive_electrode": {
            "property": {"bogus_electrode_prop": qty},
            "coating": {
                "property": {"bogus_coating_prop": qty},
                "component": {
                    "active_material": [{"name": "LFP", "property": {"bogus_component_prop": qty}}],
                },
            },
        },
        "housing": {
            "case": {"property": {"bogus_case_prop": qty}},
            "seals": [{"property": {"bogus_seal_prop": qty}}],
            "parts": [{"type": "can", "property": {"bogus_part_prop": qty}}],
        },
    }
    report = validate_semantic_report(doc, policy="publisher")
    warned = {i.path for i in report.issues if i.code == "semantic.property_unmapped"}
    assert warned == {
        "positive_electrode.property.bogus_electrode_prop",
        "positive_electrode.coating.property.bogus_coating_prop",
        "positive_electrode.coating.component.active_material[0].property.bogus_component_prop",
        "housing.case.property.bogus_case_prop",
        "housing.seals[0].property.bogus_seal_prop",
        "housing.parts[0].property.bogus_part_prop",
    }
