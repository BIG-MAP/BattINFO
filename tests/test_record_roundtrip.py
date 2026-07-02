"""Phase 1a: the canonical record serialization must be LOSSLESS.

Previously CellSpecification.to_record() dropped the entire datasheet structure (electrodes,
electrolyte, separator, housing, construction) — the "electrode-drop" data-loss bug: authoring a
rich cell spec and saving it silently discarded the structure on disk. These tests pin that
to_record()/from_record() now round-trip the full structure and that the emitted record still
validates against the canonical schema."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import validate_record
from battinfo.bundle import CellSpecification

_STRUCTURE = ("positive_electrode", "negative_electrode", "electrolyte", "separator", "housing")
_DETAILED = sorted((ROOT / "src/battinfo/data/examples/cell-spec/research").glob("*detailed*.json"))


@pytest.mark.parametrize("path", _DETAILED, ids=lambda p: p.name)
def test_canonical_roundtrip_is_lossless_and_valid(path: Path) -> None:
    spec = CellSpecification.from_path(path)  # auto-detects canonical vs library
    rec1 = spec.to_record()

    # Every structure component the spec carries must survive serialization (not be dropped).
    present = [k for k in _STRUCTURE if getattr(spec, k) is not None] + (
        ["construction"] if spec.construction else []
    )
    for key in present:
        assert key in rec1, f"{path.name}: to_record dropped {key!r}"

    # The emitted canonical record validates.
    report = validate_record(rec1)
    assert report.ok, f"{path.name}: {[i.message for i in report.errors][:3]}"

    # from_record → to_record is idempotent (no drift, no loss) at the record level.
    rec2 = CellSpecification.from_record(rec1).to_record()
    assert rec1 == rec2, f"{path.name}: canonical round-trip is not idempotent"


def test_detailed_fixtures_actually_carry_structure() -> None:
    # Guard against the round-trip test passing vacuously because no fixture has structure.
    assert _DETAILED, "no detailed example fixtures found"
    any_structure = any(
        any(k in json.loads(p.read_text(encoding="utf-8")) for k in _STRUCTURE) for p in _DETAILED
    )
    assert any_structure, "no detailed fixture carries datasheet structure"


def test_inline_component_schema_reconciled_with_model() -> None:
    # The inline datasheet structure is strictly validated. Pins the component-schema reconciliation:
    # a material component carrying molecular_formula, and a current_collector with no name, are both
    # valid — the CellSpecification models allow them, and the schemas now match the models.
    base = json.loads(
        next(p for p in _DETAILED if "cell_spec" in json.loads(p.read_text(encoding="utf-8"))).read_text(
            encoding="utf-8"
        )
    )
    base["positive_electrode"] = {
        "coating": {"component": {"active_material": [{"name": "LFP", "molecular_formula": "LiFePO4"}]}},
        "current_collector": {"manufacturer": "Acme"},  # deliberately no 'name' (optional in the model)
    }
    report = validate_record(base)
    assert report.ok, [i.message for i in report.errors][:5]


def test_electrode_drop_regression() -> None:
    # The specific bug: a spec with electrodes must not lose them through canonical serialization.
    rich = next(
        p for p in _DETAILED if "positive_electrode" in json.loads(p.read_text(encoding="utf-8"))
    )
    spec = CellSpecification.from_path(rich)
    assert spec.positive_electrode is not None and spec.electrolyte is not None  # fixture sanity

    rec = spec.to_record()
    assert "positive_electrode" in rec and "electrolyte" in rec  # not dropped on save

    reloaded = CellSpecification.from_record(rec)
    assert reloaded.positive_electrode is not None  # not dropped on load
    # byte-lossless on the electrode subtree
    src = json.loads(rich.read_text(encoding="utf-8"))
    assert json.dumps(rec["positive_electrode"], sort_keys=True) == json.dumps(
        src["positive_electrode"], sort_keys=True
    )
