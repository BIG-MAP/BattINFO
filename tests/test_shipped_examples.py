"""The example records that ship in the wheel pass strict validation and say
only what their sources support.

The examples under ``examples/`` are copied into ``battinfo/data/examples`` and
the cell-spec library ships in ``battinfo/data/library``, so every one of them
reaches users and none can change once a release is on PyPI. The strict policy
turns semantic findings into errors; every example passes it with its links
resolved. The other tests pin data fixes that strict validation cannot see:
full-cell voltages against the electrode material's potential, protocols that
fit the cell chemistry, provenance that matches where the values came from.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from battinfo.bundle import CellSpec
from battinfo.validate import validate_record_report

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
PACKAGED_EXAMPLES = ROOT / "src" / "battinfo" / "data" / "examples"
LIBRARY = ROOT / "src" / "battinfo" / "data" / "library" / "cell-spec"

# Folders of fixtures that are not records of any kind.
NOT_RECORDS = {"profiles"}

SPEC = "https://w3id.org/battinfo/spec/"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _record_paths(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.json") if path.relative_to(root).parts[0] not in NOT_RECORDS)


def _by_id(record_key: str, subdir: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for path in sorted((EXAMPLES / subdir).glob("*.json")):
        doc = _load(path)
        out[doc[record_key]["id"]] = doc
    return out


def _cell_spec(uid: str) -> dict[str, Any]:
    return _load(EXAMPLES / "cell-spec" / f"cell-spec-{uid}.json")


# ── strict validation of everything that ships ──────────────────────────────


@pytest.mark.parametrize("root", [EXAMPLES, PACKAGED_EXAMPLES], ids=["examples", "packaged-copy"])
def test_every_example_record_passes_strict_validation(root: Path) -> None:
    paths = _record_paths(root)
    assert len(paths) > 100, f"found only {len(paths)} example records under {root}"
    failures: dict[str, list[str]] = {}
    for path in paths:
        report = validate_record_report(_load(path), source_root=root, policy="strict")
        if not report.ok:
            failures[path.relative_to(root).as_posix()] = report.render_errors()
    assert not failures, json.dumps(failures, indent=2, ensure_ascii=False)


def test_every_packaged_library_record_passes_strict_validation() -> None:
    paths = sorted(LIBRARY.glob("*.json"))
    assert paths
    failures: dict[str, list[str]] = {}
    for path in paths:
        report = validate_record_report(CellSpec.from_path(path).to_record(), policy="strict")
        if not report.ok:
            failures[path.name] = report.render_errors()
    assert not failures, json.dumps(failures, indent=2, ensure_ascii=False)


def test_no_packaged_library_record_points_at_example_org() -> None:
    for path in sorted(LIBRARY.glob("*.json")):
        assert "example.org" not in path.read_text(encoding="utf-8"), path.name


def test_the_packaged_library_readme_names_cell_specs() -> None:
    text = (LIBRARY / "README.md").read_text(encoding="utf-8")
    assert "cell-type" not in text.lower()
    assert "cell-spec" in text


# ── the Energizer CR2032 library record ─────────────────────────────────────

ENERGIZER_DATASHEET_URL = "https://data.energizer.com/pdfs/cr2032.pdf"
ENERGIZER_DATASHEET_SHA256 = "ff05548e1efc6164fc779836976b0de4859ddcfa0c4f058dd55147bdc239d41f"


def test_cr2032_library_record_holds_the_energizer_datasheet_values() -> None:
    # Energizer CR2032 product datasheet, form no. 2032NA0618.
    record = _load(LIBRARY / "ENERGIZER__CR2032.json")
    spec = record["specification"]
    assert spec["id"] == SPEC + "7r2m-4q8v-k6nt-c3pj"
    assert spec["chemistry"] == "li-mno2"
    assert spec["rechargeable"] is False
    assert spec["size_code"] == "R2032"
    values = {key: (quantity.get("value"), quantity.get("unit")) for key, quantity in spec["property"].items()}
    assert values == {
        "nominal_voltage": (3.0, "V"),
        "typical_capacity": (235, "mAh"),
        "mass": (3.0, "g"),
        "volume": (1.0, "cm3"),
        "specific_energy": (198, "Wh/kg"),
        "energy_density": (653, "Wh/L"),
        "operating_temperature_min": (-30, "°C"),
        "operating_temperature_max": (60, "°C"),
        "diameter": (20.0, "mm"),
        "height": (3.2, "mm"),
    }
    capacity_conditions = spec["property"]["typical_capacity"]["conditions"]
    assert capacity_conditions["lower_voltage_limit"] == {"value": 2.0, "unit": "V"}
    assert capacity_conditions["load_resistance"] == {"value": 15000, "unit": "Ω"}
    assert capacity_conditions["temperature"] == {"value": 21, "unit": "°C"}
    # The datasheet's drawing gives the IEC maxima, 20.00 by 3.20 mm.
    assert "20.00 (0.787) maximum" in spec["property"]["diameter"]["raw"]["text"]
    assert "3.20 (0.126) maximum" in spec["property"]["height"]["raw"]["text"]

    provenance = record["provenance"]
    assert provenance["source_type"] == "datasheet"
    assert provenance["source_url"] == ENERGIZER_DATASHEET_URL
    assert provenance["file_hash"] == ENERGIZER_DATASHEET_SHA256


def test_cr2032_library_record_loads_as_a_primary_li_mno2_cell() -> None:
    cell_spec = CellSpec.from_path(LIBRARY / "ENERGIZER__CR2032.json")
    record = cell_spec.to_record()
    assert record["cell_spec"]["chemistry"] == "li-mno2"
    assert record["cell_spec"]["rechargeable"] is False
    report = validate_record_report(record, policy="strict")
    assert not [issue.code for issue in report.issues if issue.code.startswith("semantic.controlled_value")]


# ── full-cell voltages against the positive material's potential ────────────


def _average_voltage(material: dict[str, Any]) -> dict[str, Any]:
    return material["material_spec"]["property"]["average_voltage"]


def test_material_average_voltages_state_their_lithium_reference() -> None:
    found = 0
    for path in sorted((EXAMPLES / "material-spec").glob("*.json")):
        properties = _load(path)["material_spec"].get("property", {})
        if "average_voltage" not in properties:
            continue
        found += 1
        reference = properties["average_voltage"].get("conditions", {}).get("voltage_reference")
        assert reference == {"value_text": "Li/Li+"}, path.name
    assert found >= 6


@pytest.mark.parametrize(
    ("uid", "volts"),
    [
        ("venv-ff8p-nbk3-bxcn", 4.6),  # LNMO || graphite
        ("tme2-0sy6-q89b-8m92", 3.65),  # NMC811 || graphite
        ("944g-byr3-afdy-vha5", 3.7),  # LMFP || graphite
        ("0hpw-gkhk-gcg8-23x1", 3.6),  # NMC622 || graphite
    ],
)
def test_full_cell_nominal_voltage(uid: str, volts: float) -> None:
    assert _cell_spec(uid)["properties"]["nominal_voltage"] == {"value": volts, "unit": "V"}


def test_graphite_full_cells_sit_below_their_positive_material_against_lithium() -> None:
    # A graphite negative electrode works at about 0.1 to 0.2 V against Li/Li+,
    # so a full cell's nominal voltage is below its positive material's average
    # voltage against lithium, never equal to it.
    electrodes = _by_id("electrode_spec", "electrode-spec")
    materials = _by_id("material_spec", "material-spec")
    checked = 0
    for path in sorted((EXAMPLES / "cell-spec").glob("cell-spec-*.json")):
        doc = _load(path)
        if doc["cell_spec"].get("negative_electrode_basis") != "graphite":
            continue
        positive = electrodes[doc["positive_electrode_spec_id"]]["electrode_spec"]
        material = materials[positive["active_material_spec_id"]]
        cell_volts = doc["properties"]["nominal_voltage"]["value"]
        assert cell_volts < _average_voltage(material)["value"], doc["cell_spec"]["model"]
        checked += 1
    assert checked >= 6


# ── protocols that fit the cell ──────────────────────────────────────────────

LFP_UPPER_VOLTAGE = 3.65


def _charge_cutoffs(protocol: dict[str, Any]) -> list[float]:
    cutoffs: list[float] = []

    def walk(steps: list[dict[str, Any]]) -> None:
        for step in steps:
            walk(step.get("steps", []))
            for limit in step.get("termination", []):
                if limit.get("quantity") == "voltage" and limit.get("direction") == "above":
                    cutoffs.append(float(limit["value"]))

    walk(protocol.get("method", []))
    return cutoffs


def test_tests_on_lfp_cells_run_lfp_protocols() -> None:
    cells = _by_id("cell_instance", "cell-instance")
    specs = _by_id("cell_spec", "cell-spec")
    protocols = _by_id("test_spec", "test-protocol")
    checked = 0
    for path in sorted((EXAMPLES / "test").glob("*.json")):
        test = _load(path)["test"]
        if not test.get("protocol_id"):
            continue
        spec = specs[cells[test["cell_id"]]["cell_instance"]["cell_spec_id"]]
        if spec["cell_spec"].get("positive_electrode_basis") != "LFP":
            continue
        protocol = protocols[test["protocol_id"]]
        cutoffs = _charge_cutoffs(protocol)
        assert cutoffs and max(cutoffs) <= LFP_UPPER_VOLTAGE, (test["name"], cutoffs)
        window = protocol.get("facets", {}).get("voltage_window_V")
        assert window and max(window) <= LFP_UPPER_VOLTAGE, (test["name"], window)
        checked += 1
    assert checked >= 1


def test_lfp_coin_baseline_cycling_keeps_its_iri_and_runs_the_lfp_protocol() -> None:
    test = _load(EXAMPLES / "test" / "test-8439-2h04-w77p-8hdj.json")["test"]
    assert test["id"] == "https://w3id.org/battinfo/test/8439-2h04-w77p-8hdj"
    assert test["protocol_id"] != SPEC + "8r2m-4v6k-9p3t-7n5x"


# ── provenance that matches the source ──────────────────────────────────────

DESIGN_TOOL_CELLS = {
    "0hpw-gkhk-gcg8-23x1": "COIN-NMC622-D",
    "77tx-95x5-8tvd-n33a": "COIN-LFP-D",
    "86k6-6tzd-c4sf-5s01": "PRISM-LFP-100AH",
    "944g-byr3-afdy-vha5": "COIN-LMFP-D",
    "jgyy-x3h5-drmv-5tn5": "COIN-ZNMNO2-ALK",
    "st13-tf1d-z9b3-k1hf": "COIN-LCO-D",
    "tme2-0sy6-q89b-8m92": "COIN-NMC811-D",
    "venv-ff8p-nbk3-bxcn": "COIN-LNMO-D",
}


@pytest.mark.parametrize(("uid", "model"), sorted(DESIGN_TOOL_CELLS.items()))
def test_design_tool_cells_name_an_example_lab_and_a_manual_source(uid: str, model: str) -> None:
    doc = _cell_spec(uid)
    cell_spec = doc["cell_spec"]
    assert cell_spec["id"] == SPEC + uid
    assert cell_spec["model"] == model
    assert cell_spec["manufacturer"] == {"type": "Organization", "name": "Example Lab"}
    assert cell_spec["name"] == f"Example Lab {model}"
    assert doc["provenance"]["source_type"] == "manual"


def test_no_example_cell_spec_claims_an_unnamed_datasheet() -> None:
    # A datasheet source says which datasheet: its name, its URL or its hash.
    for path in sorted((EXAMPLES / "cell-spec").rglob("*.json")):
        provenance = _load(path).get("provenance", {})
        if provenance.get("source_type") != "datasheet":
            continue
        named = provenance.get("source_name") or provenance.get("source_url") or provenance.get("file_hash")
        assert named, path.relative_to(EXAMPLES).as_posix()


# ── single values the reviews found wrong ───────────────────────────────────


def test_single_layer_coin_cell_capacity_fits_its_size() -> None:
    doc = _load(EXAMPLES / "cell-spec" / "research" / "coin-detailed.example.json")
    assert doc["properties"]["nominal_capacity"] == {"value": 0.004, "unit": "Ah"}


@pytest.mark.parametrize(
    ("name", "size_code"),
    [("coin-detailed.example.json", "R2032"), ("cylindrical-detailed.example.json", "R18650")],
)
def test_research_examples_use_iec_size_codes(name: str, size_code: str) -> None:
    doc = _load(EXAMPLES / "cell-spec" / "research" / name)
    assert doc["cell_spec"]["size_code"] == size_code


def test_alkaline_coin_cell_links_a_separator_that_takes_aqueous_electrolyte() -> None:
    cell = _cell_spec("jgyy-x3h5-drmv-5tn5")
    separators = _by_id("separator_spec", "separator-spec")
    separator = separators[cell["separator_spec_id"]]["separator_spec"]
    assert separator["material"] not in {"polypropylene", "polyethylene"}
    assert separator["id"] != SPEC + "wgym-4xfa-pws1-ek1b"


def test_powder_xrd_dataset_is_about_the_material_lot_it_measures() -> None:
    doc = _load(EXAMPLES / "dataset" / "dataset-nxv4-ecrt-9wnm-a2yt.json")
    lot = _load(EXAMPLES / "material" / "material-syzh-8sbd-ygb1-kfgg.json")["material"]
    assert lot["id"] in doc["dataset"]["about"]
    assert lot["material_spec_id"] in doc["dataset"]["about"]


NCR18650B_FILES = [
    ROOT / "README.md",
    ROOT / "QUICKSTART.md",
    ROOT / ".github" / "workflows" / "install-smoke.yml",
    ROOT / "docs" / "guides" / "01-concepts.ipynb",
]


@pytest.mark.parametrize("path", NCR18650B_FILES, ids=lambda path: path.name)
def test_ncr18650b_snippets_use_the_rated_capacity(path: Path) -> None:
    # Panasonic's NCR18650B datasheet: rated capacity 3200 mAh (min., 20 °C),
    # typical 3350 mAh. 3.4 Ah is a reseller figure.
    text = path.read_text(encoding="utf-8")
    assert "NCR18650B" in text
    assert not re.search(r'"value": 3\.4, "unit": "Ah"|cell, 3\.4 Ah', text)
    assert re.search(r'"value": 3\.2, "unit": "Ah"|cell, 3\.2 Ah', text)
