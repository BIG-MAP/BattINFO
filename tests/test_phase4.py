from __future__ import annotations

import json
from pathlib import Path

import pytest

from battinfo.validate.record import validate_record

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


def test_every_family_has_at_least_one_instance():
    for subdir in ("material", "electrode", "separator", "current-collector", "electrolyte",
                   "housing", "cell-instance", "test"):
        files = list((EXAMPLES / subdir).glob("*.json"))
        assert files, f"no instances under examples/{subdir}"


@pytest.mark.parametrize("subdir", ["current-collector", "electrolyte"])
def test_new_component_instances_resolve_references(subdir):
    for path in sorted((EXAMPLES / subdir).glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert validate_record(doc, source_root=EXAMPLES).ok, path.name


def test_fleet_manufacturer_ids_resolve_to_org_records():
    org_ids = {
        json.loads(p.read_text(encoding="utf-8"))["organization"]["id"]
        for p in (EXAMPLES / "organization").glob("*.json")
    }
    linked = 0
    for path in (EXAMPLES / "cell-spec").glob("*.json"):
        mfr = json.loads(path.read_text(encoding="utf-8")).get("cell_spec", {}).get("manufacturer", {})
        if isinstance(mfr, dict) and "id" in mfr:
            assert mfr["id"] in org_ids, f"{path.name}: manufacturer.id {mfr['id']} has no org record"
            linked += 1
    assert linked >= 8  # the 8 fleet cells + A123


def test_lfp_coin_chain_resolves_end_to_end():
    from battinfo._workspace import _stable_uid

    lfp_cell = f"https://w3id.org/battinfo/spec/{_stable_uid('cell-spec:COIN-LFP-D')}"
    inst = json.loads((EXAMPLES / "cell-instance" / f"cell-{_stable_uid('cell:DISCOVERY-LFP-001')}.json").read_text(encoding="utf-8"))
    assert validate_record(inst, source_root=EXAMPLES).ok
    assert inst["cell_instance"]["cell_spec_id"] == lfp_cell
    test = json.loads((EXAMPLES / "test" / f"test-{_stable_uid('test:LFP-cycling')}.json").read_text(encoding="utf-8"))
    assert validate_record(test, source_root=EXAMPLES).ok


def test_material_lot_links_characterization_dataset():
    from battinfo._workspace import _stable_uid

    lot = json.loads((EXAMPLES / "material" / f"material-{_stable_uid('material:CANRUD-NMC811-2026-04')}.json").read_text(encoding="utf-8"))
    datasets = lot["material"].get("datasets", [])
    assert datasets and datasets[0]["id"].startswith("https://w3id.org/battinfo/dataset/")
    assert validate_record(lot, source_root=EXAMPLES).ok
