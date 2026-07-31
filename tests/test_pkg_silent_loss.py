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


# ── Item 5: out-of-vocabulary hardware part keeps its label ─────────────────────

def test_unknown_hardware_part_preserves_label_and_warns() -> None:
    import warnings

    from battinfo.transform.json_to_jsonld import _descriptor_housing_to_jsonld

    housing = {"parts": [{"type": "vent", "material": "Al"},
                         {"type": "wave spring", "material": "steel"}]}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        relations = _descriptor_housing_to_jsonld(housing, "cylindrical")

    blob = json.dumps(relations)
    # The authored strings survive (regression: they used to vanish under schema:Thing).
    assert "vent" in blob and "wave spring" in blob
    assert '"skos:prefLabel": "vent"' in blob
    assert '"schema:additionalType": "wave spring"' in blob
    # And an unmapped warning fires for each.
    messages = [str(w.message) for w in caught]
    assert sum("semantic.hardware_part_unmapped" in m for m in messages) == 2


# ── Item 6: close the audited silent drops ──────────────────────────────────────

def test_separator_manufacturer_and_product_id_are_emitted() -> None:
    from battinfo.transform.json_to_jsonld import _descriptor_separator_to_jsonld

    node = _descriptor_separator_to_jsonld(
        {"material": "PE", "manufacturer": "Celgard", "product_id": "2500"}
    )
    blob = json.dumps(node)
    assert "Celgard" in blob  # supplier traceability, previously dropped
    assert node["schema:productID"] == "2500"


def test_record_notes_reach_publication_graph(tmp_path: Path) -> None:
    ws = _new_ws(tmp_path)
    ws.add("test", type="capacity_check", cell="SN-1", data="f.csv")
    ws.save()

    # Plant notes on the saved cell-spec record, then re-emit the publication graph.
    spec_path = next((ws._ws.source_root / "cell-spec").glob("*.json"))
    rec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec_id = rec["cell_spec"]["id"]
    rec["notes"] = ["handled in a dry room", "second note"]
    spec_path.write_text(json.dumps(rec), encoding="utf-8")

    jsonld = ws._build_zenodo_jsonld(
        zenodo_record_id=0, prereserved_doi="10.5281/zenodo.X",
        record_url="https://zenodo.org/records/X", data_filenames=[], title="t", description="d",
    )
    node = next(n for n in jsonld["@graph"] if n.get("@id") == spec_id)
    assert node["schema:comment"] == ["handled in a dry room", "second note"]


def test_protocol_safety_reaches_publication_graph(tmp_path: Path) -> None:
    ws = _new_ws(tmp_path)
    tp = TestSpec(name="CCCV", kind="cycling", experiment=["Charge at 0.5C until 4.2V"],
                  cycles=10, safety={"max_voltage_V": 4.3, "max_temperature_degC": 60})
    ws.add("test", cell="SN-1", data="f.csv", spec=tp)
    ws.save()

    jsonld = ws._build_zenodo_jsonld(
        zenodo_record_id=0, prereserved_doi="10.5281/zenodo.X",
        record_url="https://zenodo.org/records/X", data_filenames=[], title="t", description="d",
    )
    proto = next(n for n in jsonld["@graph"] if "prov:Plan" in (n.get("@type") or []))
    safety = {
        p["schema:name"]: p["schema:value"]
        for p in proto.get("schema:additionalProperty", [])
        if p.get("schema:propertyID") == "safety"
    }
    assert safety == {"max_voltage_V": 4.3, "max_temperature_degC": 60}


def test_conformance_deviation_step_is_preserved(tmp_path: Path) -> None:
    from battinfo.bundle import Deviation

    # `step` (the generated-model field name) is preserved as the canonical step_index.
    assert Deviation.from_record({"category": "other", "step": 4}).step_index == 4
    assert Deviation.from_record({"category": "other", "step": "7"}).step_index == 7

    # End-to-end through ws.add(..., conformance=...): the step survives the save.
    ws = _new_ws(tmp_path)
    ws.add(
        "test", type="cycling", cell="SN-1", data="f.csv",
        conformance={"status": "non-conformant",
                     "deviations": [{"category": "operator_intervention", "step": 3}]},
    )
    ws.save()
    test = _read_one(ws, "test")["test"]
    dev = test["conformance"]["deviations"][0]
    assert dev["step_index"] == 3


def test_test_protocol_safety_schema_accepts_temperature() -> None:
    import jsonschema

    schema = json.loads(
        (ROOT / "src" / "battinfo" / "data" / "schemas" / "test-protocol.schema.json")
        .read_text(encoding="utf-8")
    )
    safety_props = schema["properties"]["safety"]["properties"]
    assert "max_temperature_degC" in safety_props
    assert "min_temperature_degC" in safety_props
    # A temperature limit now validates against the safety sub-schema.
    jsonschema.validate({"max_temperature_degC": 60}, schema["properties"]["safety"])


# ── Item 7: an identical re-save reads as [unchanged], not [updated] ─────────────

def test_identical_resave_reports_unchanged(tmp_path: Path, capsys) -> None:
    ws = _new_ws(tmp_path)
    ws.save()
    capsys.readouterr()  # drop the first save's output
    ws.save()  # byte-identical re-save
    out = capsys.readouterr().out
    assert "[unchanged]" in out
    assert "[updated]" not in out


def _record_files(ws: AuthoringWorkspace) -> list[Path]:
    root = ws._ws.source_root
    return sorted(p for p in root.rglob("*.json") if "index" not in p.name)


def test_identical_resave_with_contributor_reports_unchanged(tmp_path: Path, capsys) -> None:
    # Regression: a contributor (ORCID) stamped on every record used to make a
    # byte-identical re-save print [updated] and needlessly rewrite each file,
    # because the stamp was applied after the content comparison. The stamp is now
    # applied to the candidate before the comparison, so the re-save is a true
    # no-op: [unchanged], identical bytes, and untouched mtimes.
    ws = _new_ws(tmp_path)
    ws.contributor("0000-0002-1825-0097", name="Jane Researcher")
    ws.save()
    files = _record_files(ws)
    assert files
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in files}

    capsys.readouterr()  # drop the first save's output
    ws.save()  # byte-identical re-save
    out = capsys.readouterr().out
    assert "[unchanged]" in out
    assert "[updated]" not in out

    after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in files}
    assert after == before, "an unchanged re-save must not rewrite record files"


def test_resave_with_contributor_and_real_change_reports_updated(tmp_path: Path, capsys) -> None:
    # A genuine edit to an already-stamped record still reports [updated].
    ws = _new_ws(tmp_path)
    ws.contributor("0000-0002-1825-0097", name="Jane Researcher")
    ws.save()

    ws._ws.cell_specs[0].name = "Renamed cell spec"  # genuine content change
    capsys.readouterr()
    ws.save()
    out = capsys.readouterr().out
    assert "[updated]" in out


def test_adding_second_contributor_reports_updated(tmp_path: Path, capsys) -> None:
    # Adding a contributor between saves legitimately changes the record bytes, so
    # the re-save must report [updated], not [unchanged].
    ws = _new_ws(tmp_path)
    ws.contributor("0000-0002-1825-0097", name="Jane Researcher")
    ws.save()

    ws.contributor("0000-0001-5109-3700", name="Second Author")
    capsys.readouterr()
    ws.save()
    out = capsys.readouterr().out
    assert "[updated]" in out
    assert "[unchanged]" not in out


# ── Item 8: error-text fixes (phantom command + key-request URL) ────────────────

def test_save_gate_message_uses_real_command() -> None:
    from jsonschema import ValidationError

    from battinfo.validate.schema import _enhance_message

    err = ValidationError(
        "Additional properties are not allowed",
        validator="additionalProperties",
        path=["properties"],
    )
    msg = _enhance_message(err)
    assert "battinfo properties list" in msg
    assert "battinfo specs list" not in msg


def test_no_phantom_specs_list_command_in_source() -> None:
    src = ROOT / "src" / "battinfo"
    offenders = [
        p
        for p in src.rglob("*.py")
        if "battinfo specs list" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"phantom command 'battinfo specs list' still referenced in {offenders}"


def test_publish_no_key_error_points_at_battinfo_publish(tmp_path: Path, monkeypatch) -> None:
    for var in ("BATTINFO_API_KEY", "BATTINFO_WORKSPACE_ID", "BATTINFO_PUBLISHER_ID",
                "BATTINFO_REGISTRY_URL"):
        monkeypatch.delenv(var, raising=False)
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    with pytest.raises(RuntimeError) as exc:
        ws.submit(registry_url="https://registry.example")
    msg = str(exc.value)
    assert "https://battinfo.org/publish" in msg
    assert "battery-genome.org" not in msg


# ── Item 9: registry conflict is detected from the structured 409, not a string ─

def test_registry_conflict_detail_parses_status_and_body() -> None:
    from battinfo.api._registry import RegistryClientError
    from battinfo.ws import _registry_conflict_detail

    body = json.dumps({"detail": {"keys": {"model": "Y"}, "existing_id": "spec/abc",
                                  "existing_status": "validated", "context": "cell_spec"}})
    exc = RegistryClientError("Registry returned HTTP 409", status_code=409, response_body=body)
    detail = _registry_conflict_detail(exc)
    assert detail is not None
    assert detail["existing_id"] == "spec/abc"
    assert detail["existing_status"] == "validated"

    # A non-conflict client error is not treated as a conflict.
    other = RegistryClientError("bad request", status_code=400, response_body='{"detail": "nope"}')
    assert _registry_conflict_detail(other) is None

    # String fallback still works when neither status nor body is available.
    assert _registry_conflict_detail(RuntimeError("boom 409 boom")) == {}
    assert _registry_conflict_detail(RuntimeError("all good")) is None


def test_do_submit_retries_on_structured_409(monkeypatch) -> None:
    import battinfo.ws as ws_module
    from battinfo.api._registry import RegistryClientError

    attempts = {"n": 0}
    seen_versions: list = []

    def fake(payload, *, registry_base_url, api_key, **kw):
        attempts["n"] += 1
        seen_versions.append(payload.get("source_version"))
        if attempts["n"] == 1:
            raise RegistryClientError(
                "Registry returned HTTP 409",
                status_code=409,
                response_body=json.dumps({"detail": {"existing_id": "spec/abc",
                                                      "existing_status": "validated"}}),
            )
        return {"response": {"status": "validated", "resources": [{"canonical_iri": "spec/xyz"}]}}

    monkeypatch.setattr("battinfo.api.submit_publication_package", fake)
    outcome = ws_module._do_submit(
        {"source_version": "v1", "resource": {"source_version": "v1"}},
        "https://r", "k", "T",
    )
    assert attempts["n"] == 2  # retried after the structured 409
    assert outcome["ok"] and outcome["version_bumped"] == "v1-v2"
    assert seen_versions == ["v1", "v1-v2"]  # bumped on the retry
