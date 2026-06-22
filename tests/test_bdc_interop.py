"""Interop coverage: the Battery Data Commons (BDC) seam.

Two-way mapping with the BDC dataset registry
(github.com/BatteryCommons/BatteryDataCommons):

- `batch_import_bdc` / `import_bdc_record` — BDC canonical record → BattINFO
  dataset + cell-spec → instance + electrode material-specs + a test per reported
  measurement;
- `to_bdc_record` — the reverse, for contributing BattINFO cells back to BDC.

Fixtures are trimmed real canonical records spanning the formats and a software
record (skipped) — see tests/fixtures/interop/bdc/PROVENANCE.md.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import batch_import_bdc, import_bdc_record, to_bdc_record  # noqa: E402
from battinfo.transform import to_jsonld  # noqa: E402
from battinfo.validate import validate_record  # noqa: E402

FX = ROOT / "tests" / "fixtures" / "interop" / "bdc"
DATASETS = FX / "canonical" / "datasets"


def _record(name: str) -> dict:
    return json.loads((DATASETS / name).read_text(encoding="utf-8"))


# ── BDC → BattINFO ───────────────────────────────────────────────────────────


def test_batch_import_skips_software_and_builds_chains() -> None:
    pkg = batch_import_bdc(FX, validate=True)
    ids = {imp.bdc_id for imp in pkg.imports}
    assert "bdc_sw_001" not in ids  # software-tool record has no cell
    assert len(pkg.imports) == 7
    for imp in pkg.imports:
        assert imp.cell_spec["cell_spec"]["id"].startswith("https://w3id.org/battinfo/spec/")
        assert imp.cell_instance["cell_instance"]["cell_spec_id"] == imp.cell_spec["cell_spec"]["id"]
        assert imp.dataset["dataset"]["name"]
        # the dataset relates to the imported cell instance (schema.org `about`)
        assert imp.cell_instance["cell_instance"]["id"] in imp.dataset["dataset"].get("about", [])


def test_case_maps_to_cell_format() -> None:
    pkg = batch_import_bdc(FX, validate=False)
    fmt = {imp.bdc_id: imp.cell_spec["cell_spec"]["cell_format"] for imp in pkg.imports}
    assert fmt["bdc_000001"] == "coin"        # CoinCase
    assert fmt["bdc_000005"] == "cylindrical"  # R18650
    assert fmt["bdc_000004"] == "pouch"        # PouchCase
    assert fmt["bdc_000002"] == "prismatic"    # PrismaticCase
    assert fmt["bdc_000014"] == "unknown"      # Unknown
    # the R-code becomes the size code
    r18650 = next(i for i in pkg.imports if i.bdc_id == "bdc_000005")
    assert r18650.cell_spec["cell_spec"]["size_code"] == "R18650"


def test_available_measurements_become_tests() -> None:
    imp = import_bdc_record(_record("bdc_000001.json"))  # discharge_capacity + eis
    kinds = {t["test"]["kind"] for t in imp.tests}
    assert kinds == {"capacity_check", "eis"}
    # multi-measurement record exercises dcir + quasi_ocv too
    multi = import_bdc_record(_record("bdc_000007.json"))
    assert {"dcir", "quasi_ocv"} <= {t["test"]["kind"] for t in multi.tests}


def test_software_record_returns_none() -> None:
    assert import_bdc_record(_record("bdc_sw_001.json")) is None


def test_electrode_materials_deduped_and_linked() -> None:
    pkg = batch_import_bdc(FX, validate=False)
    names = [m["material_spec"]["name"] for m in pkg.material_specs]
    assert len(names) == len(set(names))  # deduped across records
    assert "LithiumCobaltOxide" in names  # shared by several fixtures → one spec


def test_every_record_validates_and_emits_jsonld() -> None:
    for record in batch_import_bdc(FX, validate=False).records():
        assert validate_record(record).ok, record
        to_jsonld(record, target="domain-battery")


def test_all_iris_unique() -> None:
    records = batch_import_bdc(FX, validate=False).records()
    iris = [b["id"] for r in records for b in r.values() if isinstance(b, dict) and isinstance(b.get("id"), str)]
    assert len(iris) == len(set(iris))


def test_import_is_idempotent() -> None:
    a = [i.bdc_id for i in batch_import_bdc(FX, validate=False).imports]
    iris = lambda pkg: sorted(  # noqa: E731
        b["id"] for r in pkg.records() for b in r.values()
        if isinstance(b, dict) and isinstance(b.get("id"), str)
    )
    assert iris(batch_import_bdc(FX, validate=False)) == iris(batch_import_bdc(FX, validate=False))
    assert a  # sanity


# ── BattINFO → BDC ───────────────────────────────────────────────────────────


def test_to_bdc_record_converts_mah_capacity_to_ah() -> None:
    """mAh capacity must be scaled to the Ah-typed BDC field, not copied verbatim.

    Regression: ``to_bdc_record`` wrote ``capacity["value"]`` straight into
    ``rated_capacity_Ah`` with no unit conversion, so a 45 mAh coin cell (the
    idiomatic unit) was contributed to the commons as 45 Ah — a 1000× error.
    """
    record = to_bdc_record(
        {
            "cell_spec": {"model": "Y", "cell_format": "coin"},
            "properties": {"nominal_capacity": {"value": 45.0, "unit": "mAh"}},
        }
    )
    assert record["reported_values"]["rated_capacity_Ah"] == 0.045


def test_to_bdc_record_preserves_ah_capacity_and_drops_unknown_units() -> None:
    ah = to_bdc_record(
        {"cell_spec": {"model": "Y"}, "properties": {"nominal_capacity": {"value": 2.5, "unit": "Ah"}}}
    )
    assert ah["reported_values"]["rated_capacity_Ah"] == 2.5

    # An unconvertible unit is omitted rather than written verbatim under an Ah key.
    weird = to_bdc_record(
        {"cell_spec": {"model": "Y"}, "properties": {"nominal_capacity": {"value": 2.5, "unit": "C"}}}
    )
    assert "rated_capacity_Ah" not in weird.get("reported_values", {})


def test_to_bdc_round_trips_core_descriptor() -> None:
    imp = import_bdc_record(_record("bdc_000001.json"))
    out = to_bdc_record(imp.cell_spec, dataset=imp.dataset, bdc_id=imp.bdc_id)
    assert out["overview"]["case"] == "CoinCase"
    assert out["overview"]["manufacturer"] == "Eunicell"
    assert out["overview"]["battery_model"] == "LIR2032"
    assert out["electrodes"] == {"positive": "LithiumCobaltOxide", "negative": "Carbon"}
    assert out["reported_values"]["rated_capacity_Ah"] == 0.045
    assert out["provenance"][0]["source"] == "battinfo"


@pytest.mark.parametrize("name", ["bdc_000001.json", "bdc_000005.json", "bdc_000004.json", "bdc_000002.json"])
def test_to_bdc_preserves_format_through_round_trip(name: str) -> None:
    original = _record(name)
    imp = import_bdc_record(original)
    out = to_bdc_record(imp.cell_spec, dataset=imp.dataset)
    # case survives import→export for the canonical case vocabulary
    if original["overview"]["case"] in ("CoinCase", "PouchCase", "PrismaticCase", "R18650"):
        assert out["overview"]["case"] == original["overview"]["case"]
