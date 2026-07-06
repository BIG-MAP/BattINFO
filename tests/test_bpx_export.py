"""Tests for exporting a BattINFO cell spec to a BPX document (``to_bpx``)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from battinfo import save_bpx, to_bpx
from battinfo.interop.bpx import BpxExportResult

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
A123 = EXAMPLES / "cell-spec" / "A123__ANR26650M1-B.json"


@pytest.fixture
def a123_record() -> dict:
    return json.loads(A123.read_text(encoding="utf-8"))


def test_returns_partial_bpx_with_header_and_cell(a123_record):
    result = to_bpx(a123_record)
    assert isinstance(result, BpxExportResult)
    header = result.bpx["Header"]
    assert header["Model"] == "Partial"
    assert header["BPX"] == "0.4.0"
    assert header["Title"] == "A123 ANR26650M1-B"
    assert "Cell" in result.bpx["Parameterisation"]


def test_maps_capacity_through_to_bpx_cell(a123_record):
    cell = to_bpx(a123_record).bpx["Parameterisation"]["Cell"]
    assert cell["Nominal cell capacity [A.h]"] == pytest.approx(2.5)


def test_computes_volume_and_surface_area_for_cylindrical(a123_record):
    cell = to_bpx(a123_record).bpx["Parameterisation"]["Cell"]
    # 26 mm diameter, 65 mm height → r = 0.013 m, h = 0.065 m
    r, h = 0.013, 0.065
    assert cell["Volume [m3]"] == pytest.approx(math.pi * r * r * h, rel=1e-4)
    expected_area = 2 * math.pi * r * h + 2 * math.pi * r * r
    assert cell["External surface area [m2]"] == pytest.approx(expected_area, rel=1e-4)


def test_computes_density_from_mass_and_volume(a123_record):
    cell = to_bpx(a123_record).bpx["Parameterisation"]["Cell"]
    volume = cell["Volume [m3]"]
    assert cell["Density [kg.m-3]"] == pytest.approx(0.076 / volume, rel=1e-4)


def test_reports_unfillable_required_parameters(a123_record):
    result = to_bpx(a123_record)
    # A spec gives capacity but not electrode area / electrode-pair count.
    assert "Electrode area [m2]" in result.missing_required
    assert (
        "Number of electrode pairs connected in parallel to make a cell"
        in result.missing_required
    )
    # The A123 datasheet carries no explicit voltage cut-offs.
    assert "Upper voltage cut-off [V]" in result.missing_required
    assert any("physics parameters" in w for w in result.warnings)


def test_reference_temperature_default_and_opt_out(a123_record):
    assert to_bpx(a123_record).bpx["Parameterisation"]["Cell"][
        "Reference temperature [K]"
    ] == pytest.approx(298.15)
    cell = to_bpx(a123_record, reference_temperature_k=None).bpx["Parameterisation"]["Cell"]
    assert "Reference temperature [K]" not in cell


def test_voltage_cutoffs_when_present():
    record = {
        "cell_spec": {"name": "Synthetic", "cell_format": "pouch"},
        "properties": {
            "nominal_capacity": {"value": 5000, "unit": "mAh"},
            "charging_cutoff_voltage": {"value": 4.2, "unit": "V"},
            "discharging_cutoff_voltage": {"value": 2.5, "unit": "V"},
            "width": {"value": 100, "unit": "mm"},
            "height": {"value": 200, "unit": "mm"},
            "thickness": {"value": 8, "unit": "mm"},
        },
    }
    cell = to_bpx(record).bpx["Parameterisation"]["Cell"]
    assert cell["Nominal cell capacity [A.h]"] == pytest.approx(5.0)  # mAh → A.h
    assert cell["Upper voltage cut-off [V]"] == pytest.approx(4.2)
    assert cell["Lower voltage cut-off [V]"] == pytest.approx(2.5)
    assert cell["Volume [m3]"] == pytest.approx(0.1 * 0.2 * 0.008, rel=1e-4)


def test_cell_instance_reference_in_header(a123_record):
    instance = {
        "cell_instance": {
            "id": "https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8",
            "serial_number": "SN0001",
        }
    }
    header = to_bpx(a123_record, cell_instance=instance).bpx["Header"]
    assert "SN0001" in header["References"]


def test_accepts_cellspecification_object():
    from battinfo import CellSpec

    ct = CellSpec.from_record(json.loads(A123.read_text(encoding="utf-8")))
    result = to_bpx(ct)
    assert result.bpx["Parameterisation"]["Cell"]["Nominal cell capacity [A.h]"] == pytest.approx(2.5)


def test_save_writes_valid_json(a123_record, tmp_path):
    out = save_bpx(a123_record, tmp_path / "a123.bpx.json")
    reloaded = json.loads(out.read_text(encoding="utf-8"))
    assert reloaded["Header"]["Model"] == "Partial"


def test_unknown_unit_is_warned_not_crashed():
    record = {"properties": {"nominal_capacity": {"value": 2.5, "unit": "furlongs"}}}
    result = to_bpx(record)
    assert "Nominal cell capacity [A.h]" not in result.bpx["Parameterisation"]["Cell"]
    assert any("furlongs" in w for w in result.warnings)
