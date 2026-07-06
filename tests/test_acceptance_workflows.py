"""End-to-end acceptance tests for the golden-path user workflows.

Unlike the unit tests, these exercise BattINFO the way a downstream user would: only through the
public, top-level API (``from battinfo import ...``), following the documented workflows. They
double as (a) a regression guard on the whole spine and (b) the concrete evidence of which public
surface the real workflows actually depend on. All offline and deterministic.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


# ── Golden path 1: the quickstart product surface (author -> publish -> inspect) ──
def test_quickstart_product_publish(tmp_path: Path) -> None:
    from battinfo import CellSpec, publish

    cell_spec = CellSpec(
        manufacturer="Panasonic", model="NCR18650B", format="cylindrical", chemistry="Li-ion",
        size_code="R18650",
        nominal_capacity={"value": 3.4, "unit": "Ah"},
        nominal_voltage={"value": 3.6, "unit": "V"},
        mass={"value": 48.0, "unit": "g"},
    )
    result = publish(cell_spec, destination="local", root=str(tmp_path / "quickstart"))

    assert result.canonical_iri and "/spec/" in result.canonical_iri
    record = json.loads(Path(result.debug_paths["canonical_record_path"]).read_text())
    # manufacturer is normalised to a structured schema.org Organization, not a bare string.
    assert record["cell_spec"]["manufacturer"]["name"] == "Panasonic"


# ── Golden path 2: the full linked-records chain + EMMO type stacking ──
def test_full_chain_and_type_stacking(tmp_path: Path) -> None:
    from battinfo import Workspace

    data_csv = tmp_path / "FAC-001.csv"
    data_csv.write_text("time_s,voltage_v,current_a\n0,3.6,0\n60,3.55,-0.5\n120,3.5,-0.5\n", encoding="utf-8")

    w = Workspace(root=tmp_path / "workspace")
    spec = w.cell_spec(
        manufacturer="Panasonic", model="NCR18650B", format="cylindrical", chemistry="Li-ion",
        size_code="R18650",
        specs={"nominal_capacity": {"value": 3.4, "unit": "Ah"},
               "nominal_voltage": {"value": 3.6, "unit": "V"}},
    )
    cell = w.cell(spec, serial_number="FAC-001")
    test = w.test(cell, type="capacity_check", instrument="Maccor 4200")
    dataset = w.dataset(cell, title="FAC-001 capacity check", test=test, path=data_csv, format="text/csv")

    saved = w.save()  # strict validation runs here
    assert len(saved["cell_specs"]) == 1 and len(saved["datasets"]) == 1

    pub = w.build_publication_package(dataset, publication_root=str(tmp_path / "publication"))
    jsonld_path = pub.get("publish_path") or pub.get("jsonld_path")
    graph = json.loads(Path(jsonld_path).read_text(encoding="utf-8")).get("@graph", [])
    types = {t for node in graph for t in (node.get("@type") or []) if isinstance(node.get("@type"), list)}
    # The whole point of the cell format+chemistry model: types stack automatically.
    assert {"CylindricalBattery", "LithiumIonBattery"} <= types


# ── Golden path 3: express an external record in BattINFO (adoption funnel) ──
def test_interop_import_produces_valid_record() -> None:
    from battinfo import import_converter_jsonld_record, validate_record

    source = {
        "@type": "CoinCell",
        "schema:manufacturer": {"schema:name": "Acme"},
        "schema:productID": "R2032-DEMO",
        "hasCase": {"@type": "R2032"},
    }
    result = import_converter_jsonld_record(source)  # validates its own output (D-6)
    # FRICTION (reported): result.record is a *library* record; the public validate_record() only
    # accepts the *canonical* form, so the obvious `validate_record(result.record)` raises
    # "Unsupported record type". The working path is the canonical projection:
    report = validate_record(result.specification.to_record())
    assert report.ok, [i.message for i in report.errors]


# ── Golden path 4: the unhappy path fails closed and loud, not silently ──
def test_invalid_spec_fails_closed_at_save(tmp_path: Path) -> None:
    import pytest

    from battinfo import Workspace

    w = Workspace(root=tmp_path / "workspace")
    w.cell_spec(
        manufacturer="Acme", model="X", format="coin", chemistry="Li-ion", size_code="R2032",
        specs={"nominal_capacity": {"value": 2.5, "unit": "furlongs"}},  # nonsense unit
    )
    with pytest.raises(Exception):  # strict save must reject an implausible unit, not persist it
        w.save(validation_policy="strict")
