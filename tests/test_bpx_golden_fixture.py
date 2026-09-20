"""The BPX golden-fixture contract: nothing a BPX file says is silently lost.

The fixture is a synthetic structural twin of a published full-DFN BattMo
export (Schmitt et al. 2026 — GPL-3.0, so the real file cannot be vendored):
Header lineage, all five Parameterisation blocks, curve-valued parameters, a
populated User-defined block, and a Validation section. The contract pinned
here is the BPX Phase 0 exit criterion: every parameter in the file is either
a claim, a spec property, or a NAMED warning — never a silent drop.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.interop import from_bpx, from_bpx_parameters  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "interop" / "bpx-dfn-full.bpx.json"


def _doc() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_physics_blocks_import_completely() -> None:
    """Every electrode/separator/electrolyte parameter becomes a claim."""
    res = from_bpx_parameters(FIXTURE)
    counts = {block: len(claims) for block, claims in res.claims.items()}
    assert counts == {
        "negative_material": 9,
        "negative_electrode": 5,
        "positive_material": 10,
        "positive_electrode": 5,
        "separator": 3,
        "electrolyte": 4,
    }
    # Curves stay curves: both OCPs and both electrolyte transport tables.
    curve_params = {
        c["parameter"]
        for claims in res.claims.values()
        for c in claims
        if "curve" in c
    }
    assert curve_params == {"ocp", "electrolyte_diffusivity", "ionic_conductivity"}
    # No unmapped-field warnings for the physics blocks themselves.
    assert not any("no parameter mapping" in w for w in res.warnings), res.warnings


def test_nothing_in_the_file_is_silently_dropped() -> None:
    """Phase 0 exit criterion: claim, spec property, or a warning that NAMES it."""
    doc = _doc()
    res = from_bpx_parameters(FIXTURE)
    cell = from_bpx(FIXTURE)
    all_warnings = " | ".join(res.warnings + list(cell.warnings))

    physics_blocks = ("Negative electrode", "Positive electrode", "Separator", "Electrolyte")
    claimed = sum(len(c) for c in res.claims.values())
    assert claimed == sum(len(doc["Parameterisation"][b]) for b in physics_blocks)

    spec_props = cell.specs
    for key in doc["Parameterisation"]["Cell"]:
        mapped = key in all_warnings
        # The mapped trio: capacity + the two voltage cut-offs become spec
        # properties rather than warnings.
        if not mapped:
            assert spec_props, f"Cell key {key!r} neither warned about nor mapped"
    assert {"nominal_capacity", "discharging_cutoff_voltage", "charging_cutoff_voltage"} <= set(spec_props)

    # The User-defined block is warned about BY NAME — BPX's extension point
    # carries no standard semantics, but ignoring it must never be silent.
    for key in doc["Parameterisation"]["User-defined"]:
        assert key in all_warnings, f"User-defined key {key!r} not named in warnings"


def test_header_lineage_lands_on_the_minted_records() -> None:
    res = from_bpx_parameters(FIXTURE)
    records = res.to_records(materials={"negative": "graphite", "positive": "nmc811"})
    assert records, res.warnings
    for record in records:
        body = record["parameter_set"]
        # Description rides the record; the model context says which model the
        # values were fitted under (a DFN-fitted constant is not model-free).
        assert body["description"].startswith("Structural twin")
        assert body["model_context"] == {
            "tool": "BPX",
            "name": "Synthetic DFN parameter set (golden fixture)",
            "model": "DFN",
            "version": "1.0",
        }
        # Header.References is free text here (not a URL/DOI), so it rides a
        # note verbatim — provenance.citation is URI-typed by the schema.
        assert any("Schmitt et al. 2026" in n for n in record.get("notes", []))


def test_caller_supplied_lineage_wins_over_the_header() -> None:
    res = from_bpx_parameters(FIXTURE)
    records = res.to_records(
        materials={"negative": "graphite"},
        description="Curated re-description.",
        citation="10.5281/zenodo.0000000",
    )
    body = records[0]["parameter_set"]
    assert body["description"] == "Curated re-description."
    assert records[0]["provenance"]["citation"] == "https://doi.org/10.5281/zenodo.0000000"


def test_emitted_jsonld_uses_the_records_context_and_absolute_license() -> None:
    """Parameter-set records are the BPX Metadata payload: they must expand
    against the hosted, versioned records context, and a license slug must
    never emit as a relative IRI."""
    from battinfo.jsonld import record_to_jsonld

    res = from_bpx_parameters(FIXTURE)
    record = res.to_records(materials={"negative": "graphite"})[0]
    record["license"] = "cc-by-sa-4.0"

    hosted = record_to_jsonld(record, "parameter-set")
    assert hosted["@context"] == "https://w3id.org/battinfo/context/records/v1.json"
    assert hosted["dcterms:license"] == {"@id": "https://spdx.org/licenses/CC-BY-SA-4.0.html"}

    inline = record_to_jsonld(record, "parameter-set", context="inline")
    context = inline["@context"]
    assert isinstance(context, dict)

    def bare_terms(value, out):
        if isinstance(value, list):
            for item in value:
                bare_terms(item, out)
        elif isinstance(value, dict):
            for k, v in value.items():
                if not k.startswith("@") and ":" not in k:
                    out.add(k)
                if k == "@type":
                    for t in (v if isinstance(v, list) else [v]):
                        if isinstance(t, str) and ":" not in t:
                            out.add(t)
                else:
                    bare_terms(v, out)

    terms: set[str] = set()
    bare_terms({k: v for k, v in inline.items() if k != "@context"}, terms)
    unresolved = sorted(t for t in terms if t not in context)
    assert not unresolved, f"terms missing from the inline records context: {unresolved}"
