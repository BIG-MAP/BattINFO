"""Tests for Phase 4 interoperability modules: from_battdat and from_bpx."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd

from battinfo.bundle import SCHEMA_VERSION
from battinfo.interop.battdat import (
    BattdatImportResult,
    _extract_timestamps,
    _infer_kind,
    _to_variable_measured,
    from_battdat,
)
from battinfo.interop.bpx import BpxImportResult, from_bpx

# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_cycling_df() -> pd.DataFrame:
    """Minimal BDF-format DataFrame for a cycling test."""
    return pd.DataFrame({
        "test_time_second": [0.0, 10.0, 20.0, 30.0],
        "unix_time_second": [1_700_000_000, 1_700_000_010, 1_700_000_020, 1_700_000_030],
        "voltage_volt":     [3.30, 3.45, 3.50, 3.28],
        "current_ampere":   [2.5, 2.5, -2.5, -2.5],
        "cycle_count":      [0, 0, 0, 1],
    })


def _make_eis_df() -> pd.DataFrame:
    """Minimal BDF-format DataFrame that looks like EIS data."""
    return pd.DataFrame({
        "freq":            [1e4, 1e3, 1e2, 10.0, 1.0],
        "re_z":            [0.01, 0.015, 0.02, 0.025, 0.03],
        "im_z":            [-0.005, -0.008, -0.012, -0.018, -0.025],
        "voltage_volt":    [3.5, 3.5, 3.5, 3.5, 3.5],
    })


def _make_bpx_dict() -> dict:
    return {
        "Header": {
            "BPX": "1.0.0",
            "Title": "Test Cell NMC532",
            "Description": "NMC532 pouch cell parameters",
            "Model": "SPMe",
        },
        "Parameterisation": {
            "Cell": {
                "Nominal cell capacity [A.h]": 3.0,
                "Upper voltage cut-off [V]": 4.2,
                "Lower voltage cut-off [V]": 2.5,
                "Nominal cell voltage [V]": 3.7,
                "Cell mass [kg]": 0.065,
                "Electrode height [m]": 0.065,
                "Electrode width [m]": 0.1,
                "Initial temperature [K]": 298.15,
                "Ambient temperature [K]": 298.15,
                "Specific heat capacity [J.K-1.kg-1]": 1100.0,
                "Thermal conductivity [W.m-1.K-1]": 1.48,
            },
            "Electrolyte": {
                "Initial concentration [mol.m-3]": 1000.0,
            },
            "Negative electrode": {
                "Thickness [m]": 85.2e-6,
                "Porosity": 0.37,
            },
            "Positive electrode": {
                "Thickness [m]": 67.5e-6,
                "Porosity": 0.33,
            },
            "Separator": {
                "Thickness [m]": 25e-6,
            },
        },
    }


CELL_ID = "urn:staging:test-cell-001"


# ── _infer_kind ────────────────────────────────────────────────────────────────

def test_infer_kind_cycling() -> None:
    df = _make_cycling_df()
    assert _infer_kind(df) == "cycling"


def test_infer_kind_eis() -> None:
    df = _make_eis_df()
    assert _infer_kind(df) == "eis"


def test_infer_kind_returns_none_for_unknown() -> None:
    df = pd.DataFrame({"col_a": [1, 2], "col_b": [3, 4]})
    assert _infer_kind(df) is None


# ── _extract_timestamps ────────────────────────────────────────────────────────

def test_extract_timestamps_present() -> None:
    df = _make_cycling_df()
    started, ended = _extract_timestamps(df)
    assert started == 1_700_000_000
    assert ended == 1_700_000_030


def test_extract_timestamps_missing_column() -> None:
    df = pd.DataFrame({"voltage_volt": [3.3, 3.4]})
    started, ended = _extract_timestamps(df)
    assert started is None
    assert ended is None


# ── _to_variable_measured ──────────────────────────────────────────────────────

def test_to_variable_measured_maps_known_columns() -> None:
    df = _make_cycling_df()
    vars_measured = _to_variable_measured(df)
    names = {v["name"] for v in vars_measured}
    assert "voltage" in names
    assert "current" in names
    assert "cycle_index" in names


def test_to_variable_measured_skips_unknown_columns() -> None:
    df = pd.DataFrame({"mystery_col": [1, 2], "voltage_volt": [3.3, 3.4]})
    vars_measured = _to_variable_measured(df)
    assert all(v["name"] != "mystery_col" for v in vars_measured)


# ── from_battdat — DataFrame input ────────────────────────────────────────────

def test_from_battdat_dataframe_produces_test_record() -> None:
    df = _make_cycling_df()
    result = from_battdat(df, cell_id=CELL_ID)
    assert isinstance(result, BattdatImportResult)
    assert result.test_record["schema_version"] == SCHEMA_VERSION
    test = result.test_record["test"]
    assert test["cell_id"] == CELL_ID
    assert test["kind"] == "cycling"
    assert test["started_at"] == 1_700_000_000
    assert test["ended_at"] == 1_700_000_030


def test_from_battdat_dataframe_no_dataset_record() -> None:
    df = _make_cycling_df()
    result = from_battdat(df, cell_id=CELL_ID)
    assert result.dataset_record is None


def test_from_battdat_explicit_kind_overrides_inferred() -> None:
    df = _make_cycling_df()
    result = from_battdat(df, cell_id=CELL_ID, kind="formation")
    assert result.test_record["test"]["kind"] == "formation"


def test_from_battdat_explicit_name() -> None:
    df = _make_cycling_df()
    result = from_battdat(df, cell_id=CELL_ID, name="My test run")
    assert result.test_record["test"]["name"] == "My test run"


def test_from_battdat_instrument_stored() -> None:
    df = _make_cycling_df()
    result = from_battdat(df, cell_id=CELL_ID, instrument="Biologic VMP3")
    assert result.test_record["test"]["instrument_name"] == "Biologic VMP3"


def test_from_battdat_unknown_columns_produce_warning() -> None:
    df = pd.DataFrame({"col_a": [1, 2]})
    result = from_battdat(df, cell_id=CELL_ID)
    assert any("inferred" in w.lower() or "kind" in w.lower() for w in result.warnings)


def test_from_battdat_inferred_kind_attribute() -> None:
    df = _make_cycling_df()
    result = from_battdat(df, cell_id=CELL_ID)
    assert result.inferred_kind == "cycling"


# ── from_battdat — file path input ────────────────────────────────────────────

def test_from_battdat_csv_path_produces_dataset_record(tmp_path: Path) -> None:
    csv_file = tmp_path / "2024-01-01__cycling__25degC.csv"
    df = _make_cycling_df()
    df.to_csv(csv_file, index=False)

    result = from_battdat(csv_file, cell_id=CELL_ID)
    assert result.dataset_record is not None
    ds = result.dataset_record["dataset"]
    assert "about" in ds
    assert CELL_ID in ds["about"]
    assert "distributions" in ds
    assert ds["distributions"][0]["encoding_format"] == "text/csv"


def test_from_battdat_csv_path_checksum_present(tmp_path: Path) -> None:
    csv_file = tmp_path / "cycling.csv"
    _make_cycling_df().to_csv(csv_file, index=False)
    result = from_battdat(csv_file, cell_id=CELL_ID)
    dist = result.dataset_record["dataset"]["distributions"][0]
    assert "checksum" in dist
    assert len(dist["checksum"]["value"]) == 64  # SHA-256 hex


def test_from_battdat_csv_variable_measured_populated(tmp_path: Path) -> None:
    csv_file = tmp_path / "cycling.csv"
    _make_cycling_df().to_csv(csv_file, index=False)
    result = from_battdat(csv_file, cell_id=CELL_ID)
    vm = result.dataset_record["dataset"].get("variable_measured", [])
    assert any(v["name"] == "voltage" for v in vm)
    assert any(v["name"] == "current" for v in vm)


def test_from_battdat_csv_measurement_techniques(tmp_path: Path) -> None:
    csv_file = tmp_path / "cycling.csv"
    _make_cycling_df().to_csv(csv_file, index=False)
    result = from_battdat(csv_file, cell_id=CELL_ID)
    techniques = result.dataset_record["dataset"].get("measurement_techniques", [])
    assert any("cycling" in t.lower() for t in techniques)


def test_from_battdat_license_propagated(tmp_path: Path) -> None:
    csv_file = tmp_path / "cycling.csv"
    _make_cycling_df().to_csv(csv_file, index=False)
    result = from_battdat(
        csv_file, cell_id=CELL_ID, license="https://creativecommons.org/licenses/by/4.0/"
    )
    assert result.dataset_record["dataset"]["license"].startswith("https://")


# ── from_battdat — top-level import ──────────────────────────────────────────

def test_from_battdat_accessible_from_battinfo() -> None:
    import battinfo
    assert callable(battinfo.from_battdat)
    assert battinfo.BattdatImportResult is BattdatImportResult


# ── from_bpx — spec extraction ────────────────────────────────────────────────

def test_from_bpx_dict_extracts_capacity() -> None:
    result = from_bpx(_make_bpx_dict())
    assert "nominal_capacity" in result.specs
    assert result.specs["nominal_capacity"]["value"] == 3.0
    assert result.specs["nominal_capacity"]["unit"] == "Ah"


def test_from_bpx_dict_extracts_voltage_limits() -> None:
    result = from_bpx(_make_bpx_dict())
    assert result.specs["charging_cutoff_voltage"]["value"] == pytest.approx(4.2)
    assert result.specs["discharging_cutoff_voltage"]["value"] == pytest.approx(2.5)


def test_from_bpx_dict_scales_mass_to_grams() -> None:
    result = from_bpx(_make_bpx_dict())
    # 0.065 kg × 1000 = 65 g
    assert result.specs["mass"]["value"] == pytest.approx(65.0)
    assert result.specs["mass"]["unit"] == "g"


def test_from_bpx_dict_scales_dimensions_to_mm() -> None:
    result = from_bpx(_make_bpx_dict())
    # Electrode height 0.065 m → 65 mm
    assert result.specs["height"]["value"] == pytest.approx(65.0)
    assert result.specs["height"]["unit"] == "mm"
    # Electrode width 0.1 m → 100 mm
    assert result.specs["width"]["value"] == pytest.approx(100.0)


def test_from_bpx_dict_reads_header() -> None:
    result = from_bpx(_make_bpx_dict())
    assert result.title == "Test Cell NMC532"
    assert result.bpx_version == "1.0.0"
    assert result.model_type == "SPMe"


def test_from_bpx_dict_physics_params_produce_warning() -> None:
    result = from_bpx(_make_bpx_dict())
    # Specific heat capacity etc. should appear in warnings
    assert any("physics" in w.lower() or "transport" in w.lower() for w in result.warnings)


def test_from_bpx_dict_unknown_physics_params_produce_warning() -> None:
    bpx = _make_bpx_dict()
    bpx["Parameterisation"]["Cell"]["Mystery thermal param [W.K-1]"] = 99.0
    result = from_bpx(bpx)
    # The unknown key should appear in warnings
    assert any("Mystery" in w for w in result.warnings)


def test_from_bpx_file_path(tmp_path: Path) -> None:
    bpx_path = tmp_path / "cell.bpx.json"
    bpx_path.write_text(json.dumps(_make_bpx_dict()), encoding="utf-8")
    result = from_bpx(bpx_path)
    assert result.specs["nominal_capacity"]["value"] == 3.0
    assert result.source_file == "cell.bpx.json"


def test_from_bpx_missing_parameterisation_returns_empty() -> None:
    result = from_bpx({"Header": {"BPX": "1.0.0", "Title": "empty"}})
    assert result.specs == {}
    assert result.title == "empty"
    assert any("Parameterisation" in w for w in result.warnings)


def test_from_bpx_to_cell_spec_kwargs() -> None:
    result = from_bpx(_make_bpx_dict())
    kwargs = result.to_cell_spec_kwargs()
    assert "properties" in kwargs
    assert kwargs["properties"]["nominal_capacity"]["value"] == 3.0
    assert kwargs.get("name") == "Test Cell NMC532"


def test_from_bpx_accessible_from_battinfo() -> None:
    import battinfo
    assert callable(battinfo.from_bpx)
    assert battinfo.BpxImportResult is BpxImportResult


# ── Workspace integration ─────────────────────────────────────────────────────

def test_workspace_from_battdat_returns_test(tmp_path: Path) -> None:
    from battinfo._workspace import Workspace

    csv_file = tmp_path / "cycling.csv"
    _make_cycling_df().to_csv(csv_file, index=False)

    ws = Workspace()
    cell_spec = ws.cell_spec(
        manufacturer="TestMfg",
        model="XR-1234",
        format="cylindrical",
        chemistry="Li-ion",
        specs={"nominal_capacity": {"value": 2.5, "unit": "Ah"}},
    )
    cell = ws.cell(cell_spec, serial_number="SN-TEST-001")

    test = ws.from_battdat(cell, csv_file)
    assert test is not None
    assert test.test_kind == "cycling"
    # test should appear in workspace.tests
    assert test in ws.tests


def test_workspace_from_bpx_creates_cell_spec(tmp_path: Path) -> None:
    from battinfo._workspace import Workspace

    bpx_path = tmp_path / "params.json"
    bpx_path.write_text(json.dumps(_make_bpx_dict()), encoding="utf-8")

    ws = Workspace()
    cell_spec = ws.from_bpx(
        bpx_path,
        manufacturer="TestMfg",
        format="pouch",
        chemistry="NMC",
    )
    assert cell_spec is not None
    # model should fall back to BPX Header.Title
    assert "NMC532" in (cell_spec.model or "")
    # capacity spec should be present
    assert cell_spec in ws.cell_specs


def test_workspace_from_bpx_specs_accessible(tmp_path: Path) -> None:
    from battinfo._workspace import Workspace

    bpx_path = tmp_path / "params.json"
    bpx_path.write_text(json.dumps(_make_bpx_dict()), encoding="utf-8")

    ws = Workspace()
    cell_spec = ws.from_bpx(bpx_path, manufacturer="TestMfg", format="pouch")
    # properties dict should contain nominal_capacity
    props = cell_spec.properties or {}
    assert "nominal_capacity" in props
    assert props["nominal_capacity"]["value"] == pytest.approx(3.0)
