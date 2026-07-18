"""Regression tests for the P1 lab-engineer campaign: six silent-data-loss/authoring traps.

Source: docs/internal/LAB-ENGINEER-CAMPAIGN-2026-07-17.md, clusters C2 + the C3
template item. Each test pins the FIXED behavior so the trap cannot silently
return:

1. ws.convert / convert_csv never green-light a lossy conversion silently.
2. Dangling ``*_spec_id`` references fail save by default (opt-out kwarg).
3. query_* never silently searches the wheel's bundled examples.
4. Cell-instance IRIs are deterministic across every minting surface.
5. ws.add("cell") does not fabricate measurements from spec ratings.
6. ws.template("test-spec") round-trips through ws.load(), and a voltage
   window is expressible in the Quantity model + schema.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import battinfo
from battinfo import api
from battinfo.bundle import BatteryTestType, Cell, CellSpec
from battinfo.testmethod import Quantity
from battinfo.validate.record import validate_record_report
from battinfo.ws import AuthoringWorkspace

# ── Fix 1: convert must report unmapped/dropped source columns ────────────────

def test_convert_reports_unmapped_source_columns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A conversion that discards source columns (the Digatron-via-wrong-plugin
    red-team case: AhStep[Ah]/Step/Mode gone behind a success message) must
    print a loud per-file report naming every dropped column and pointing at
    ws.bdf_columns() / convert_csv(hints=...)."""
    pytest.importorskip("bdf")
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    src = tmp_path / "digatron_export.csv"
    src.write_text(
        "test_time_second,voltage_volt,current_ampere,AhStep[Ah],Step,Mode\n"
        "0,3.7,1.0,0.0,1,CC\n"
        "1,3.71,1.0,0.001,1,CC\n",
        encoding="utf-8",
    )

    written = ws.convert("*.csv")

    assert len(written) == 1
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "AhStep[Ah]" in out and "Step" in out and "Mode" in out
    assert "bdf_columns()" in out
    assert "convert_csv" in out
    assert "DATA-LOSS WARNING" in out
    # And the loss is recorded durably in the conversion manifest, without
    # breaking raw-source provenance lookup.
    manifest = json.loads((tmp_path / ".battinfo" / "conversions.json").read_text(encoding="utf-8"))
    entry = manifest[str(written[0].resolve())]
    assert entry["source"] == str(src.resolve())
    assert set(entry["unmapped_columns"]) == {"AhStep[Ah]", "Step", "Mode"}
    assert ws._resolve_raw_source(written[0]) == src.resolve()


def test_convert_clean_file_has_no_loss_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pytest.importorskip("bdf")
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    (tmp_path / "clean.csv").write_text(
        "test_time_second,voltage_volt,current_ampere\n0,3.7,1.0\n1,3.71,1.0\n",
        encoding="utf-8",
    )
    written = ws.convert("*.csv")
    assert len(written) == 1
    out = capsys.readouterr().out
    assert "DATA-LOSS WARNING" not in out
    # Legacy plain-string manifest form is kept for lossless conversions.
    manifest = json.loads((tmp_path / ".battinfo" / "conversions.json").read_text(encoding="utf-8"))
    assert isinstance(manifest[str(written[0].resolve())], str)


def test_convert_csv_warns_on_non_canonical_columns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pd = pytest.importorskip("pandas")
    src = tmp_path / "maccor.csv"
    pd.DataFrame({"Cycle": [1, 2], "Voltage(V)": [3.7, 3.6], "Weird Col": [0, 1]}).to_csv(
        src, index=False
    )
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    ws.convert_csv(src, hints={"Cycle": "cycle_count", "Voltage(V)": "voltage_volt"}, validate=False)
    out = capsys.readouterr().out
    assert "WARNING" in out and "Weird Col" in out
    assert "bdf_columns()" in out
    # Mapped columns are not flagged.
    assert "- cycle_count" not in out and "- voltage_volt" not in out


def test_resolve_raw_source_accepts_legacy_manifest_entries(tmp_path: Path) -> None:
    """Manifests written before the loss report (plain out->src strings) keep working."""
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    src = tmp_path / "raw.csv"
    src.write_text("a\n1\n", encoding="utf-8")
    out = tmp_path / "bdf" / "raw.bdf.csv"
    out.parent.mkdir()
    out.write_text("a\n1\n", encoding="utf-8")
    manifest_path = tmp_path / ".battinfo" / "conversions.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps({str(out.resolve()): str(src.resolve())}), encoding="utf-8"
    )
    assert ws._resolve_raw_source(out) == src.resolve()


# ── Fix 2: dangling *_spec_id references fail save by default ─────────────────

def test_save_cell_spec_rejects_dangling_component_reference(tmp_path: Path) -> None:
    spec = CellSpec(
        manufacturer="Acme",
        model="X3",
        format="pouch",
        chemistry="Li-ion",
        electrolyte_spec_id="https://w3id.org/battinfo/spec/zzzz-zzzz-zzzz-zzzz",
    )
    with pytest.raises(ValueError) as excinfo:
        api.save_cell_spec(spec, source_root=tmp_path)
    message = str(excinfo.value)
    assert "Reference validation failed" in message
    assert "https://w3id.org/battinfo/spec/zzzz-zzzz-zzzz-zzzz" in message
    # Staged workflows opt out explicitly.
    payload = api.save_cell_spec(spec, source_root=tmp_path, resolve_references=False)
    assert payload["status"] == "created"


def test_save_cell_spec_accepts_existing_component_reference(tmp_path: Path) -> None:
    saved = api.save_electrolyte_spec(
        api.create_electrolyte_spec(
            name="1M LiPF6 EC:DMC", uid="2222222222222222", body={"family": "organic"}
        ),
        source_root=tmp_path,
    )
    electrolyte_id = saved["id"]
    payload = api.save_cell_spec(
        CellSpec(
            manufacturer="Acme",
            model="X4",
            format="pouch",
            chemistry="Li-ion",
            electrolyte_spec_id=electrolyte_id,
        ),
        source_root=tmp_path,
    )
    assert payload["status"] == "created"


def test_save_material_rejects_dangling_material_spec_reference(tmp_path: Path) -> None:
    material = api.create_material(
        uid="1234abcd5678ef90",
        material_spec_id="https://w3id.org/battinfo/spec/zzzz-zzzz-zzzz-zzzz",
        lot_id="LOT-9",
    )
    with pytest.raises(ValueError, match="Reference validation failed"):
        api.save_material(material, source_root=tmp_path)
    payload = api.save_material(material, source_root=tmp_path, resolve_references=False)
    assert payload["status"] == "created"


# ── Fix 3: query_* never silently searches the wheel's bundled examples ───────

def test_query_defaults_do_not_return_packaged_examples(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """query_material_specs() (and siblings) in an empty directory must return
    nothing — not present BattINFO's shipped example fleet as the user's lab."""
    monkeypatch.chdir(tmp_path)
    assert api.query_material_specs() == []
    assert api.query_materials() == []
    assert api.query_cell_specs() == []
    assert api.query_cell_instances() == []
    assert api.query_datasets() == []
    assert api.query_tests() == []
    assert api.query_test_specs() == []
    assert api.query_electrode_specs() == []


def test_query_packaged_examples_require_explicit_opt_in_and_are_labeled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    rows = api.query_material_specs(include_packaged_examples=True)
    assert rows
    assert all(row["origin"] == "packaged-example" for row in rows)
    specs = api.query_cell_specs(manufacturer="A123", include_packaged_examples=True)
    assert specs
    assert all(row["origin"] == "packaged-example" for row in specs)


def test_query_source_root_matches_save_location(tmp_path: Path) -> None:
    api.save_material_spec(
        api.create_material_spec(name="LFP powder", uid="1111111111111111"),
        source_root=tmp_path,
    )
    rows = api.query_material_specs(source_root=tmp_path)
    assert [row["name"] for row in rows] == ["LFP powder"]
    assert rows[0]["origin"] == "local"


def test_query_directory_alias_is_deprecated_but_works(tmp_path: Path) -> None:
    api.save_material_spec(
        api.create_material_spec(name="NMC811 powder", uid="3333333333333333"),
        source_root=tmp_path,
    )
    with pytest.warns(DeprecationWarning, match="directory= is deprecated"):
        rows = api.query_material_specs(directory=tmp_path / "material-spec")
    assert [row["name"] for row in rows] == ["NMC811 powder"]

    with pytest.raises(ValueError, match="not both"):
        api.query_material_specs(source_root=tmp_path, directory=tmp_path / "material-spec")


# ── Fix 4: deterministic instance IRIs across every minting surface ───────────

def test_cell_instance_iri_is_deterministic_across_surfaces(tmp_path: Path) -> None:
    """The same (spec IRI, serial) must mint the SAME cell IRI via the
    workspace, save_cell_instance, and create_cell_instance — one identity, not
    one per surface/record store."""
    # Surface 1: workspace authoring.
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    ws = battinfo.workspace(str(ws_root))
    ws.add(
        "cell",
        spec=CellSpec(manufacturer="Acme", model="X1", format="cylindrical", chemistry="Li-ion"),
        serial_numbers=["SN-42"],
    )
    ws.save()
    ws_iri = None
    spec_iri = None
    for path in sorted(ws_root.rglob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(doc.get("cell_instance"), dict):
            ws_iri = doc["cell_instance"]["id"]
            spec_iri = doc["cell_instance"]["cell_spec_id"]
    assert ws_iri is not None and spec_iri is not None

    # Surface 2: low-level save_cell_instance (separate record store).
    api_root = tmp_path / "api"
    saved_spec = api.save_cell_spec(
        CellSpec(manufacturer="Acme", model="X1", format="cylindrical", chemistry="Li-ion"),
        source_root=api_root,
    )
    assert saved_spec["id"] == spec_iri  # spec identity converges too
    saved = api.save_cell_instance(
        Cell(cell_spec_id=saved_spec["id"], serial_number="SN-42"), source_root=api_root
    )
    assert saved["id"] == ws_iri

    # Surface 3: create_cell_instance (previously minted a fresh random uid).
    created = api.create_cell_instance(cell_spec_id=saved_spec["id"], serial_number="SN-42")
    assert created["cell_instance"]["id"] == ws_iri


def test_anonymous_cell_instances_never_dedup(tmp_path: Path) -> None:
    """A cell with no serial/batch/name has no identity: two of them must mint
    DIFFERENT IRIs (random), never silently collapse into one record."""
    spec = api.save_cell_spec(
        CellSpec(manufacturer="Acme", model="X9", format="pouch", chemistry="Li-ion"),
        source_root=tmp_path,
    )
    first = api.create_cell_instance(cell_spec_id=spec["id"])
    second = api.create_cell_instance(cell_spec_id=spec["id"])
    assert first["cell_instance"]["id"] != second["cell_instance"]["id"]


# ── Fix 5: no fabricated measurements on ws.add("cell") ───────────────────────

def test_ws_add_cell_does_not_copy_spec_ratings_into_measured(tmp_path: Path) -> None:
    """Rated/nominal spec values are not measurements. The instance record must
    not carry a measured={...} block auto-copied from the spec under
    provenance type='measurement'."""
    ws = battinfo.workspace(str(tmp_path))
    spec = CellSpec(
        manufacturer="Acme",
        model="X2",
        format="cylindrical",
        chemistry="Li-ion",
        properties={"nominal_capacity": {"value": 5.0, "unit": "Ah"}},
    )
    cells = ws.add("cell", spec=spec, serial_numbers=["A1"])
    assert cells[0].measured in (None, {})
    ws.save()
    instance_docs = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in tmp_path.rglob("*.json")
        if p.name.startswith("cell-") and "cell-spec" not in p.name
    ]
    instance_docs = [d for d in instance_docs if isinstance(d.get("cell_instance"), dict)]
    assert instance_docs
    for doc in instance_docs:
        assert not doc.get("measured")
        assert not doc["cell_instance"].get("measured")


def test_ws_cell_still_accepts_genuine_measured_values(tmp_path: Path) -> None:
    ws = battinfo.workspace(str(tmp_path))
    spec = CellSpec(manufacturer="Acme", model="X2", format="cylindrical", chemistry="Li-ion")
    cell = ws._ws.cell(spec, serial_number="B1", measured={"capacity": {"value": 4.87, "unit": "Ah"}})
    assert cell.measured["capacity"]["value"] == 4.87


# ── Fix 6: template <-> load round-trip + Quantity windows ────────────────────

def test_test_spec_template_round_trips_through_load(tmp_path: Path) -> None:
    """ws.load(ws.template('test-spec', ...)) must work with only the user
    filling values — no scalar/min-max shape rejections, no null-placeholder
    errors (the 14-pydantic-error red-team case)."""
    ws = battinfo.workspace(str(tmp_path))
    path = ws.template(
        "test-spec",
        name="CC discharge C/5",
        type="capacity_check",
        description="Constant-current discharge at C/5 to 2.5 V cutoff.",
        temperature_degC=25,
        voltage_window_volt={"min": 2.5, "max": 4.2},
    )
    tp = ws.load(path)
    assert tp.name == "CC discharge C/5"
    assert tp.test_type == BatteryTestType.CAPACITY_CHECK
    assert tp.conditions["temperature"].value == 25.0
    window = tp.conditions["voltage_window"]
    assert (window.min_value, window.max_value, window.unit) == (2.5, 4.2, "V")
    # Unfilled placeholders are dropped, not errors.
    assert "c_rate" not in tp.conditions and "applied_pressure" not in tp.conditions


def test_test_spec_template_placeholders_only_still_loads(tmp_path: Path) -> None:
    ws = battinfo.workspace(str(tmp_path))
    path = ws.template("test-spec", name="Bare", type="cycling")
    tp = ws.load(path)
    assert tp.conditions == {}
    assert tp.method == []


def test_voltage_window_survives_save_and_validates(tmp_path: Path) -> None:
    """Acceptance: a 2.5-4.2 V voltage window is expressible and the saved
    record passes schema validation (model and schema agree on min/max names)."""
    ws = battinfo.workspace(str(tmp_path))
    path = ws.template(
        "test-spec", name="Window", type="cycling", voltage_window_volt=(2.5, 4.2)
    )
    ws.load(path)
    ws.save()
    docs = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in tmp_path.rglob("*.json")
        if "test-protocol" in p.name
    ]
    docs = [d for d in docs if isinstance(d.get("test_spec"), dict)]
    assert docs
    record = docs[0]
    assert record["conditions"]["voltage_window"] == {
        "min_value": 2.5,
        "max_value": 4.2,
        "unit": "V",
    }
    report = validate_record_report(record)
    assert report.ok, [issue.message for issue in report.errors]


def test_legacy_template_shapes_still_load(tmp_path: Path) -> None:
    """Old drafts written by the pre-fix template (scalar temperature_degC,
    {min,max} windows, null placeholders, dict step placeholder) must load."""
    ws = battinfo.workspace(str(tmp_path))
    draft = {
        "name": "Legacy",
        "type": "capacity_check",
        "description": None,
        "instrument": None,
        "steps": [{"description": "Fill in test steps here"}],
        "conditions": {
            "temperature_degC": 25,
            "applied_pressure_kilopascal": None,
            "atmosphere": "argon",
            "voltage_window_volt": {"min": 2.5, "max": 4.2},
            "soc_window": {"min": None, "max": None},
            "c_rate": None,
            "d_rate": None,
        },
        "citation": None,
        "source_file": None,
    }
    path = tmp_path / "legacy.test-spec.json"
    path.write_text(json.dumps(draft, indent=2), encoding="utf-8")
    tp = ws.load(path)
    assert tp.conditions["temperature"].value == 25.0
    window = tp.conditions["voltage_window"]
    assert (window.min_value, window.max_value, window.unit) == (2.5, 4.2, "V")
    # Non-quantity information is preserved as a note, not silently dropped.
    assert any("atmosphere: argon" in note for note in tp.comment)


def test_template_missing_type_error_lists_allowed_values(tmp_path: Path) -> None:
    ws = battinfo.workspace(str(tmp_path))
    path = ws.template("test-spec", name="No type yet")
    with pytest.raises(ValueError) as excinfo:
        ws.load(path)
    message = str(excinfo.value)
    assert "type" in message
    assert "cycling" in message and "capacity_check" in message and "other" in message


def test_quantity_model_supports_min_max_windows() -> None:
    window = Quantity(min_value=2.5, max_value=4.2, unit="V")
    assert window.value is None
    with pytest.raises(ValueError, match="at least one of"):
        Quantity(unit="V")
    with pytest.raises(ValueError, match="must not exceed"):
        Quantity(min_value=4.2, max_value=2.5, unit="V")
    # Scalar form unchanged.
    assert Quantity(value=25, unit="degC").value == 25.0


def test_template_no_arg_error_lists_supported_kinds(tmp_path: Path) -> None:
    ws = battinfo.workspace(str(tmp_path))
    with pytest.raises(ValueError) as excinfo:
        ws.template()
    message = str(excinfo.value)
    assert "cell-spec" in message and "test-spec" in message and "equipment-spec" in message


def test_template_empty_name_writes_sane_filenames(tmp_path: Path) -> None:
    ws = battinfo.workspace(str(tmp_path))
    cell_path = ws.template("cell-spec")
    assert cell_path.name == "cell-spec.cell-spec.json"
    test_path = ws.template("test-spec", type="cycling")
    assert test_path.name == "test-spec.test-spec.json"
