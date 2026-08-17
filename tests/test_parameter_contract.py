"""Contract tests for the parameter-set claim family (IDENTIFIER_POLICY 6.3).

Design rules under test:
- a parameter set targets exactly ONE of material_kind / material_spec_id /
  cell_spec_id; material_kind resolves through the curated vocabulary;
- each claim carries exactly one of quantity / curve / expression, and curves
  must be well-formed (equal-length finite x/y);
- IRIs mint under the shared spec/ namespace, DETERMINISTIC from
  (target, scope, name) so re-importing one source is idempotent;
- the parameter vocabulary + tier contract answers completeness ("can these
  claims support spm?") identically for every consumer, and BPX field
  resolution is block-scoped (electrode 'Conductivity' is electronic,
  electrolyte 'Conductivity' is ionic);
- collation folds many records into {parameter: [claim, ...]} with per-claim
  source context, never picking a winner.
"""
from __future__ import annotations

import re

import pytest

from battinfo.api import (
    create_parameter_set,
    query_parameter_sets,
    save_parameter_set,
    template_parameter_set,
)
from battinfo.interop import from_bpx_parameters, import_bpx_parameters
from battinfo.parameters import (
    cell_completeness,
    collate_claims,
    completeness,
    parameter_entry,
    parameter_keys,
    parameters_vocabulary,
    resolve_bpx_field,
    resolve_parameter,
    tier_keys,
    tier_requirements,
)
from battinfo.validate.record import validate_record_report

SPEC_IRI = re.compile(
    r"^https://w3id\.org/battinfo/spec/[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}$"
)
CELL_SPEC_IRI = "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-dddd"
MATERIAL_SPEC_IRI = "https://w3id.org/battinfo/spec/cccc-dddd-eeee-ffff"


def _claims() -> list[dict]:
    return [
        {
            "parameter": "particle_radius",
            "quantity": {"value": 5.86e-06, "unit": "m"},
            "provenance_class": "fitted",
        },
        {
            "parameter": "ocp",
            "curve": {
                "x_quantity": "stoichiometry",
                "x": [0.0, 0.5, 1.0],
                "y": [1.2, 0.13, 0.05],
                "y_unit": "V",
            },
            "provenance_class": "measured",
            "method": "GITT",
        },
        {
            "parameter": "solid_diffusivity",
            "expression": {"text": "3.3e-14 * x", "language": "bpx", "argument": "x"},
            "provenance_class": "fitted",
        },
    ]


def _record(**overrides):
    fields = {
        "name": "Chen 2020 - graphite",
        "material_kind": "graphite",
        "claims": _claims(),
        "citation_doi": "10.1149/1945-7111/ab9050",
    }
    fields.update(overrides)
    return create_parameter_set(**fields)


# ── identity ──────────────────────────────────────────────────────────────────


def test_parameter_set_mints_under_shared_spec_namespace() -> None:
    record = _record()
    assert SPEC_IRI.fullmatch(record["parameter_set"]["id"])


def test_uid_is_deterministic_from_target_scope_and_name() -> None:
    first = _record()
    second = _record()
    assert first["parameter_set"]["id"] == second["parameter_set"]["id"]


def test_different_name_or_target_mints_a_different_iri() -> None:
    base = _record()["parameter_set"]["id"]
    other_name = _record(name="Mohtat 2020 - graphite")["parameter_set"]["id"]
    other_target = _record(material_kind=None, material_spec_id=MATERIAL_SPEC_IRI)
    assert other_name != base
    assert other_target["parameter_set"]["id"] != base


def test_material_kind_resolves_aliases_to_canonical_key() -> None:
    record = _record(material_kind="NMC 811", name="Chen 2020 - NMC811")
    assert record["parameter_set"]["material_kind"] == "nmc811"


def test_unknown_material_kind_raises_listing_valid_keys() -> None:
    with pytest.raises(ValueError, match="unknown material kind.*graphite"):
        _record(material_kind="unobtainium")


# ── exactly-one-target rule ──────────────────────────────────────────────────


def test_no_target_is_rejected() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        _record(material_kind=None)


def test_two_targets_are_rejected() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        _record(cell_spec_id=CELL_SPEC_IRI)


def test_scope_defaults_follow_the_target() -> None:
    assert _record()["parameter_set"]["scope"] == "material"
    cell = _record(
        material_kind=None, cell_spec_id=CELL_SPEC_IRI, name="Fit - cell"
    )
    assert cell["parameter_set"]["scope"] == "cell"


def test_electrode_polarity_requires_electrode_scope() -> None:
    with pytest.raises(ValueError, match="electrode_polarity"):
        _record(electrode_polarity="negative")


# ── claim validation ─────────────────────────────────────────────────────────


def test_claim_without_a_value_form_is_rejected() -> None:
    with pytest.raises(ValueError, match="exactly one of quantity"):
        _record(claims=[{"parameter": "porosity", "provenance_class": "assumed"}])


def test_claim_with_two_value_forms_is_rejected() -> None:
    with pytest.raises(ValueError, match="exactly one of quantity"):
        _record(claims=[{
            "parameter": "porosity",
            "quantity": {"value": 0.3, "unit": "1"},
            "expression": {"text": "0.3", "language": "bpx"},
        }])


def test_curve_with_mismatched_lengths_is_rejected() -> None:
    with pytest.raises(ValueError, match="equal length"):
        _record(claims=[{
            "parameter": "ocp",
            "curve": {"x_quantity": "stoichiometry", "x": [0, 1], "y": [1.0], "y_unit": "V"},
        }])


def test_curve_with_non_finite_values_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        _record(claims=[{
            "parameter": "ocp",
            "curve": {
                "x_quantity": "stoichiometry",
                "x": [0.0, 1.0],
                "y": [float("nan"), 0.05],
                "y_unit": "V",
            },
        }])


def test_default_provenance_class_fills_only_missing() -> None:
    record = _record(
        default_provenance_class="literature",
        claims=[
            {"parameter": "density", "quantity": {"value": 2.26, "unit": "g/cm3"}},
            {
                "parameter": "particle_radius",
                "quantity": {"value": 5.9e-06, "unit": "m"},
                "provenance_class": "measured",
            },
        ],
    )
    classes = [c["provenance_class"] for c in record["parameter_set"]["claims"]]
    assert classes == ["literature", "measured"]


def test_bad_provenance_class_is_rejected() -> None:
    with pytest.raises(ValueError, match="provenance_class"):
        _record(claims=[{
            "parameter": "density",
            "quantity": {"value": 2.26, "unit": "g/cm3"},
            "provenance_class": "vibes",
        }])


def test_unknown_parameter_key_is_tolerated() -> None:
    record = _record(claims=[{
        "parameter": "frobnication_index",
        "quantity": {"value": 42.0, "unit": "1"},
        "provenance_class": "assumed",
    }])
    assert record["parameter_set"]["claims"][0]["parameter"] == "frobnication_index"


# ── schema round-trip ────────────────────────────────────────────────────────


def test_created_record_passes_strict_schema_validation() -> None:
    report = validate_record_report(_record())
    assert report.ok, report.errors


def test_template_record_passes_strict_schema_validation() -> None:
    report = validate_record_report(template_parameter_set())
    assert report.ok, report.errors


def test_save_and_query_round_trip(tmp_path) -> None:
    record = _record()
    saved = save_parameter_set(record, source_root=tmp_path)
    assert saved["status"] == "created"
    rows = query_parameter_sets(source_root=tmp_path, material_kind="Graphite")
    assert len(rows) == 1
    assert rows[0]["id"] == record["parameter_set"]["id"]
    assert "particle_radius" in rows[0]["parameters"]
    by_parameter = query_parameter_sets(source_root=tmp_path, parameter="ocp")
    assert len(by_parameter) == 1


# ── vocabulary + tiers ───────────────────────────────────────────────────────


def test_vocabulary_keys_resolve_and_tiers_are_declared() -> None:
    keys = parameter_keys()
    assert "solid_diffusivity" in keys
    assert resolve_parameter("Solid-phase diffusivity") == "solid_diffusivity"
    assert resolve_parameter("no_such_parameter") is None
    assert tier_keys() == ["bote", "spm", "spme", "p2d"]


def test_every_tier_requirement_is_a_declared_parameter_with_that_scope() -> None:
    vocab = parameters_vocabulary()["parameters"]
    for tier in tier_keys():
        for scope, keys in tier_requirements(tier).items():
            for key in keys:
                assert key in vocab, f"{tier}.{scope} requires undeclared key {key}"
                assert scope in vocab[key]["scopes"], (
                    f"{tier} requires {key} at scope {scope}, but the vocabulary "
                    f"scopes it {vocab[key]['scopes']}"
                )


def test_tiers_are_monotone_in_material_requirements() -> None:
    bote = set(tier_requirements("bote")["material"])
    spm = set(tier_requirements("spm")["material"])
    assert bote <= spm


def test_unknown_tier_raises_listing_valid_ones() -> None:
    with pytest.raises(ValueError, match="valid tiers"):
        tier_requirements("dfn9000")


def test_bpx_field_resolution_is_block_scoped() -> None:
    assert resolve_bpx_field("electrode", "Conductivity [S.m-1]") == "electronic_conductivity"
    assert resolve_bpx_field("electrolyte", "Conductivity [S.m-1]") == "ionic_conductivity"
    assert resolve_bpx_field("electrode", "Diffusivity [m2.s-1]") == "solid_diffusivity"
    assert resolve_bpx_field("electrolyte", "Diffusivity [m2.s-1]") == "electrolyte_diffusivity"
    assert resolve_bpx_field("electrode", "Made-up field") is None


def test_completeness_reports_satisfied_and_missing() -> None:
    bote_claims = ["specific_capacity", "density", "ocp", "first_cycle_efficiency"]
    result = completeness(bote_claims)
    assert result["bote"] == {"satisfied": True, "missing": []}
    assert not result["spm"]["satisfied"]
    assert "particle_radius" in result["spm"]["missing"]
    assert parameter_entry("particle_radius")["unit"] == "m"


def test_completeness_ignores_unknown_keys_and_checks_scope() -> None:
    result = completeness(["frobnication_index"], scope="separator")
    assert set(result) == {"spme", "p2d"}
    assert not result["spme"]["satisfied"]
    with pytest.raises(ValueError, match="valid scopes"):
        completeness([], scope="warp_core")


def test_cell_completeness_distinguishes_electrode_sides() -> None:
    sep = ["thickness", "porosity", "transport_efficiency"]
    ely = ["initial_concentration", "transference_number", "ionic_conductivity",
           "electrolyte_diffusivity"]
    spm_material = tier_requirements("spm")["material"]
    result = cell_completeness({
        "material_negative": spm_material,
        "material_positive": ["ocp"],
        "electrode": sep,
        "separator": sep,
        "electrolyte": ely,
    })
    assert not result["spme"]["satisfied"]
    assert "material_positive" in result["spme"]["missing"]
    assert "material_negative" not in result["spme"]["missing"]


# ── collation ────────────────────────────────────────────────────────────────


def test_collate_claims_folds_records_and_attaches_source() -> None:
    chen = _record()
    mohtat = _record(
        name="Mohtat 2020 - graphite",
        citation_doi="10.1149/1945-7111/aba5d1",
        claims=[{
            "parameter": "particle_radius",
            "quantity": {"value": 2.5e-06, "unit": "m"},
            "provenance_class": "fitted",
        }],
    )
    collated = collate_claims([chen, mohtat])
    radii = collated["particle_radius"]
    assert len(radii) == 2
    names = {c["source"]["name"] for c in radii}
    assert names == {"Chen 2020 - graphite", "Mohtat 2020 - graphite"}
    dois = {c["source"]["citation_doi"] for c in radii}
    assert dois == {"10.1149/1945-7111/ab9050", "10.1149/1945-7111/aba5d1"}


def test_collate_claims_prefers_claim_level_citation() -> None:
    record = _record(claims=[{
        "parameter": "density",
        "quantity": {"value": 2.26, "unit": "g/cm3"},
        "provenance_class": "literature",
        "citation_doi": "10.1039/D0SE00175A",
    }])
    collated = collate_claims([record])
    assert collated["density"][0]["source"]["citation_doi"] == "10.1039/D0SE00175A"


# ── BPX physics import ───────────────────────────────────────────────────────


def _bpx() -> dict:
    return {
        "Header": {"BPX": "0.4.0", "Model": "DFN", "Title": "Chen2020 LG M50"},
        "Parameterisation": {
            "Cell": {"Nominal cell capacity [A.h]": 5.0},
            "Negative electrode": {
                "Particle radius [m]": 5.86e-06,
                "Thickness [m]": 8.52e-05,
                "Diffusivity [m2.s-1]": "3.3e-14 * exp(-1)",
                "OCP [V]": {"x": [0.0, 0.5, 1.0], "y": [1.2, 0.13, 0.05]},
                "Conductivity [S.m-1]": 215.0,
                "Porosity": 0.25,
                "Maximum concentration [mol.m-3]": 33133.0,
                "Mystery field [X]": 1.0,
            },
            "Positive electrode": {
                "Particle radius [m]": 5.22e-06,
                "Thickness [m]": 7.56e-05,
            },
            "Separator": {"Thickness [m]": 1.2e-05, "Porosity": 0.47},
            "Electrolyte": {
                "Initial concentration [mol.m-3]": 1000.0,
                "Conductivity [S.m-1]": "0.95 * c",
            },
        },
    }


def test_bpx_claims_split_material_from_build_scope() -> None:
    result = from_bpx_parameters(_bpx())
    negative_material = {c["parameter"] for c in result.claims["negative_material"]}
    negative_build = {c["parameter"] for c in result.claims["negative_electrode"]}
    assert "particle_radius" in negative_material
    assert "solid_diffusivity" in negative_material
    assert "thickness" in negative_build
    assert "electronic_conductivity" in negative_build
    assert negative_material.isdisjoint(negative_build)


def test_bpx_value_forms_map_to_claim_forms() -> None:
    result = from_bpx_parameters(_bpx())
    by_key = {c["parameter"]: c for c in result.claims["negative_material"]}
    assert by_key["particle_radius"]["quantity"] == {"value": 5.86e-06, "unit": "m"}
    assert by_key["solid_diffusivity"]["expression"]["language"] == "bpx"
    assert by_key["ocp"]["curve"]["x_quantity"] == "stoichiometry"
    assert by_key["ocp"]["curve"]["y_unit"] == "V"
    electrolyte = {c["parameter"]: c for c in result.claims["electrolyte"]}
    assert electrolyte["ionic_conductivity"]["expression"]["text"] == "0.95 * c"


def test_bpx_unknown_fields_are_warned_never_silent() -> None:
    result = from_bpx_parameters(_bpx())
    assert any("Mystery field" in w for w in result.warnings)


def test_bpx_to_records_targets_and_scopes() -> None:
    records = import_bpx_parameters(
        _bpx(),
        materials={"negative": "graphite", "positive": "NMC 811"},
        cell_spec_id=CELL_SPEC_IRI,
        citation_doi="10.1149/1945-7111/ab9050",
    )
    by_name = {r["parameter_set"]["name"]: r["parameter_set"] for r in records}
    negative = by_name["Chen2020 LG M50 - negative electrode material"]
    assert negative["material_kind"] == "graphite"
    assert negative["scope"] == "material"
    build = by_name["Chen2020 LG M50 - negative electrode build"]
    assert build["cell_spec_id"] == CELL_SPEC_IRI
    assert build["scope"] == "electrode"
    assert build["electrode_polarity"] == "negative"
    assert by_name["Chen2020 LG M50 - separator"]["scope"] == "separator"
    assert by_name["Chen2020 LG M50 - electrolyte"]["scope"] == "electrolyte"
    positive = by_name["Chen2020 LG M50 - positive electrode material"]
    assert positive["material_kind"] == "nmc811"
    for record in records:
        report = validate_record_report(record)
        assert report.ok, report.errors


def test_bpx_records_without_targets_skip_with_warnings() -> None:
    result = from_bpx_parameters(_bpx())
    records = result.to_records()
    assert records == []
    assert any("pass materials=" in w for w in result.warnings)
    assert any("cell_spec_id" in w for w in result.warnings)


def test_bpx_reimport_is_idempotent() -> None:
    kwargs = {"materials": {"negative": "graphite"}, "cell_spec_id": CELL_SPEC_IRI}
    first = {r["parameter_set"]["name"]: r["parameter_set"]["id"]
             for r in import_bpx_parameters(_bpx(), **kwargs)}
    second = {r["parameter_set"]["name"]: r["parameter_set"]["id"]
              for r in import_bpx_parameters(_bpx(), **kwargs)}
    assert first == second


# ── workspace integration ────────────────────────────────────────────────────


def test_ws_add_and_save_round_trip(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    import battinfo.ws as bws

    ws = bws.workspace("params")
    ws.add(
        "parameter_set",
        name="Chen 2020 - graphite",
        material="Graphite",
        citation_doi="10.1149/1945-7111/ab9050",
        default_provenance_class="fitted",
        claims=[{"parameter": "particle_radius", "quantity": {"value": 5.86e-06, "unit": "m"}}],
    )
    result = ws.save()
    saved = [r for r in result.get("parameter_sets", []) if isinstance(r, dict)]
    assert len(saved) == 1
    assert saved[0]["status"] == "created"
    rows = query_parameter_sets(source_root=ws._ws.source_root, material_kind="graphite")
    assert len(rows) == 1
    # attribution stamping reached the record through the shared side-record path
    assert "provenance" in rows[0]["record"]


def test_ws_add_rejects_ambiguous_target(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    import battinfo.ws as bws

    ws = bws.workspace("params-ambiguous")
    with pytest.raises(ValueError, match="not both"):
        ws.add(
            "parameter_set",
            name="X - y",
            material="graphite",
            material_kind="graphite",
            claims=[{"parameter": "density", "quantity": {"value": 2.26, "unit": "g/cm3"}}],
        )
