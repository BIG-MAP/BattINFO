"""PR B (step A): the CellSpecificationInput save path builds its canonical record THROUGH the one
model (CellSpecification.to_record), not a parallel hand-assembled dict. These pin that the routed
builder preserves everything the input carries — including product_type, which the old hand-builder
silently dropped — and still derives the id/short_id/identifier the same way."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import validate_record
from battinfo.api import CellSpecificationInput, _record_from_cell_spec


def test_routed_builder_preserves_all_fields_and_validates() -> None:
    rec = _record_from_cell_spec(CellSpecificationInput(
        uid="1c4m-7p9q-2k6t-8v3r", model_name="CR2032",
        manufacturer={"name": "Energizer", "id": "https://w3id.org/battinfo/organization/1111-2222-3333-4444"},
        format="coin", chemistry="Li-primary", product_type="commercial", size_code="R2032",
        positive_electrode_spec_id="https://w3id.org/battinfo/electrode-spec/5555-6666-7777-8888",
        specs={"nominal_capacity": {"value": 0.24, "unit": "Ah"}}, notes=["note"],
    ))
    assert validate_record(rec).ok, [str(e) for e in validate_record(rec).errors][:3]
    cs = rec["cell_spec"]
    assert cs["manufacturer"]["id"] == "https://w3id.org/battinfo/organization/1111-2222-3333-4444"
    assert cs["product_type"] == "commercial"  # regression: the hand-builder dropped product_type
    assert rec["positive_electrode_spec_id"] == "https://w3id.org/battinfo/electrode-spec/5555-6666-7777-8888"
    assert rec["notes"] == ["note"]


def test_routed_builder_mints_id_short_id_and_identifier_from_uid() -> None:
    rec = _record_from_cell_spec(CellSpecificationInput(
        uid="1c4m-7p9q-2k6t-8v3r", model_name="X", manufacturer="Acme", format="coin", chemistry="Li-ion",
    ))
    cs = rec["cell_spec"]
    assert cs["id"] == "https://w3id.org/battinfo/spec/1c4m-7p9q-2k6t-8v3r"
    assert cs["short_id"] == "1c4m7p"
    assert cs["identifier"] == "cell-spec:1c4m-7p9q-2k6t-8v3r"
    assert cs["name"] == "Acme X"
