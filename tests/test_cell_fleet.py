from __future__ import annotations

import json
from pathlib import Path

import battinfo as bi
from battinfo.bundle import CellSpecification
from battinfo.transform.json_to_jsonld import to_jsonld
from battinfo.validate.record import validate_record

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


def _fleet_cells() -> list[dict]:
    """Cell-specs that use the component-spec reference seam."""
    out = []
    for path in sorted((EXAMPLES / "cell-spec").glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if any(k.endswith("_spec_id") for k in doc):
            out.append(doc)
    return out


def test_fleet_exists():
    assert len(_fleet_cells()) >= 8


def test_fleet_cells_validate_with_component_references():
    for doc in _fleet_cells():
        result = validate_record(doc, source_root=EXAMPLES)
        assert result.ok, f"{doc['cell_spec']['model']}: {result.errors[:1]}"


def test_fleet_cells_emit_component_reference_nodes():
    for doc in _fleet_cells():
        node = to_jsonld(doc, target="domain-battery")["@graph"][0]
        # electrode + electrolyte + separator references emit @id (housing → hasConstituent)
        pos = node.get("hasPositiveElectrode")
        assert isinstance(pos, dict) and "@id" in pos
        assert isinstance(node.get("hasElectrolyte"), dict) and "@id" in node["hasElectrolyte"]
        assert isinstance(node.get("hasSeparator"), dict) and "@id" in node["hasSeparator"]


def test_fleet_chemistry_coverage():
    chems = {d["cell_spec"]["model"] for d in _fleet_cells()}
    expected = {"COIN-NMC811-D", "COIN-LFP-D", "COIN-LCO-D", "COIN-LMFP-D",
                "COIN-NMC622-D", "PRISM-LFP-100AH", "COIN-ZNMNO2-ALK", "COIN-LNMO-D"}
    assert expected.issubset(chems), f"missing: {expected - chems}"


def test_nmc811_chain_resolves_end_to_end():
    # cell-instance → cell-spec; test → instance + protocol; dataset
    inst = json.loads((EXAMPLES / "cell-instance" / "cell-ag7d-b4fp-r0sv-226m.json").read_text(encoding="utf-8"))
    assert validate_record(inst, source_root=EXAMPLES).ok
    test = json.loads((EXAMPLES / "test" / "test-ezwb-tj8t-0474-7dgh.json").read_text(encoding="utf-8"))
    assert validate_record(test, source_root=EXAMPLES).ok
    ds = json.loads((EXAMPLES / "dataset" / "dataset-nns1-gh5p-v5n1-td17.json").read_text(encoding="utf-8"))
    assert validate_record(ds, source_root=EXAMPLES).ok
    # the instance points at the NMC811 coin cell-spec
    nmc811 = next(d for d in _fleet_cells() if d["cell_spec"]["model"] == "COIN-NMC811-D")
    assert inst["cell_instance"]["cell_spec_id"] == nmc811["cell_spec"]["id"]


def test_missing_component_reference_is_flagged(tmp_path):
    from battinfo import api
    rec = api._record_from_cell_spec(CellSpecification(
        uid="cmiss123456789ab", model_name="X", manufacturer="Y", format="coin", chemistry="Li-ion",
        electrolyte_spec_id="https://w3id.org/battinfo/electrolyte-spec/0000-0000-0000-0000"))
    result = validate_record(rec, source_root=tmp_path)
    assert any(i.code == "reference.missing" for i in result.issues)


def test_extract_component_specs_from_inline_cell():
    rec = json.loads((EXAMPLES / "cell-spec" / "research" / "extended.example.json").read_text(encoding="utf-8"))
    specs = bi.extract_component_specs(rec)
    keys = {next(k for k in s if k.endswith("_spec")) for s in specs}
    assert {"electrode_spec", "electrolyte_spec", "separator_spec"}.issubset(keys)
    for spec in specs:
        assert validate_record(spec).ok
