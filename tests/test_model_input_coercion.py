"""Step B (foundation): the CellSpec model accepts the flat authoring/input shape directly
(the fields the separate CellSpecificationInput DTO used to carry), so one model can be both the
source of truth and the thing importers/CLI/tests construct. This is what makes retiring the DTO
possible; the retirement + caller repoint follows."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.bundle import CellSpec


def test_model_absorbs_flat_authoring_input() -> None:
    spec = CellSpec(
        uid="1c4m-7p9q-2k6t-8v3r",
        model_name="CR2032",  # -> model
        manufacturer={"type": "Organization", "name": "Energizer",
                      "id": "https://w3id.org/battinfo/organization/1111-2222-3333-4444"},
        format="coin", chemistry="Li-primary",
        specs={"nominal_capacity": {"value": 0.24, "unit": "Ah"}},  # -> properties
        source_type="datasheet", source_file="m.json",  # -> nested source
        notes=["n"],  # -> comment
    )
    assert spec.model == "CR2032"
    assert spec.manufacturer == "Energizer"  # dict split to name + id
    assert spec.manufacturer_id == "https://w3id.org/battinfo/organization/1111-2222-3333-4444"
    assert spec.uid == "1c4m-7p9q-2k6t-8v3r"
    assert spec.properties == {"nominal_capacity": {"value": 0.24, "unit": "Ah"}}
    assert spec.source.type == "datasheet" and spec.source.file == "m.json"
    assert spec.comment == ["n"]
    assert spec.name == "Energizer CR2032"  # auto-populated from manufacturer + model


def test_uid_is_transient_and_not_serialized() -> None:
    spec = CellSpec(uid="1c4m-7p9q-2k6t-8v3r", manufacturer="A", model="M",
                             format="coin", chemistry="Li-ion")
    assert spec.uid == "1c4m-7p9q-2k6t-8v3r"
    assert "uid" not in spec.model_dump()  # excluded from serialization
