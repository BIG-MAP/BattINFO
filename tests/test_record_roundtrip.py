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


def test_manufacturer_id_provenance_and_component_refs_round_trip() -> None:
    # PR A: complete the model. Three fields the canonical record supports but the model used to drop
    # on save — the manufacturer organization id, the extra provenance fields the converter populates,
    # and the standalone component-spec references — must now survive to_record/from_record losslessly.
    from battinfo.bundle import CellSpecification, ProvenanceInfo

    spec = CellSpecification(
        id="https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-dddd",
        name="Acme X", manufacturer="Acme", model="X", format="coin", chemistry="Li-ion",
        size_code="R2032",
        manufacturer_id="https://w3id.org/battinfo/organization/1111-2222-3333-4444",
        positive_electrode_spec_id="https://w3id.org/battinfo/electrode-spec/5555-6666-7777-8888",
        electrolyte_spec_id="https://w3id.org/battinfo/electrolyte-spec/9999-aaaa-bbbb-cccc",
        source=ProvenanceInfo(type="converter-jsonld", name="BattINFO Converter",
                              workflow_version="app=1.1.17", comment="blended salt note"),
    )
    rec = spec.to_record()

    # manufacturer is emitted as an Organization node carrying the id (not a bare string).
    assert rec["cell_spec"]["manufacturer"]["id"] == spec.manufacturer_id
    # component refs are top-level siblings of cell_spec (per the schema), not under cell_spec.
    assert rec["positive_electrode_spec_id"] == spec.positive_electrode_spec_id
    assert "positive_electrode_spec_id" not in rec["cell_spec"]
    # the previously-dropped provenance fields are present.
    assert rec["provenance"]["source_name"] == "BattINFO Converter"
    assert rec["provenance"]["workflow_version"] == "app=1.1.17"
    assert rec["provenance"]["comment"] == "blended salt note"

    assert validate_record(rec).ok, [str(e) for e in validate_record(rec).errors][:3]

    back = CellSpecification.from_record(rec)
    assert back.manufacturer_id == spec.manufacturer_id
    assert back.positive_electrode_spec_id == spec.positive_electrode_spec_id
    assert back.electrolyte_spec_id == spec.electrolyte_spec_id
    assert (back.source.name, back.source.workflow_version, back.source.comment) == (
        "BattINFO Converter", "app=1.1.17", "blended salt note")
    assert back.to_record() == rec  # fully idempotent


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
