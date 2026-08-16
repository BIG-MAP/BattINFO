"""Role-based electrode holders: authoring, save gate, and JSON-LD typing.

Upstream ruling (BIG-MAP/BattINFO): *do not use polarity in a half cell — use
reference, working, counter electrode instead of positive or negative
electrode*. A full cell has a positive and a negative side; a half cell or a
three-electrode cell has neither, so its electrodes are named by the role they
play in the measurement.

``working_electrode`` / ``counter_electrode`` are therefore siblings of the
polarity holders, sharing their shape (an inline ``Electrode`` plus a top-level
``*_electrode_spec_id``). Which family a record uses is a statement about the
cell, and the save gate warns — never errors — when the family and the stated
``cell_configuration`` disagree.

Note the division of labour with ``electrode_spec.polarity``: that field is the
DESIGN's intended full-cell side, derived from the electrode kind. Roles are
assigned at the cell level, by the holder an electrode sits in, so a graphite
anode design can be the working electrode of a half cell without either
statement contradicting the other.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from battinfo.bundle import CellSpec, Electrode
from battinfo.jsonld import record_to_jsonld
from battinfo.transform.json_to_jsonld import to_jsonld
from battinfo.validate.record import validate_record_report

SPEC_IRI = "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-dddd"
DESIGN_IRI = "https://w3id.org/battinfo/spec/rkf4-xz0y-h8kz-rmxz"

_IDENTITY = {
    "id": SPEC_IRI, "name": "Graphite half cell", "manufacturer": "Lab",
    "model": "HC-1", "format": "coin", "chemistry": "li-ion",
    "source_type": "manual",
}


def _electrode(active: str) -> Electrode:
    return Electrode(coating={"component": {"active_material": [{"name": active}]}})


def _half_cell(**overrides) -> CellSpec:
    return CellSpec(
        **_IDENTITY, cell_configuration="half_cell",
        working_electrode=_electrode("Graphite"),
        counter_electrode=_electrode("Lithium"),
        **overrides,
    )


# ── Emission ──────────────────────────────────────────────────────────────────

def test_half_cell_emits_role_relations_and_counter_is_also_the_reference() -> None:
    """The counter-as-reference statement: one electrode, both roles.

    A half cell has no third electrode — the counter electrode IS the potential
    reference (the HalfCellDevice axiom, and the reason the three role classes
    are non-disjoint upstream). Stated as a second @type on the one node rather
    than as a second relation, so the graph never claims two electrodes.
    """
    node = record_to_jsonld(_half_cell().to_record(), "cell-spec")

    assert node["hasWorkingElectrode"]["@type"] == "WorkingElectrode"
    assert node["hasCounterElectrode"]["@type"] == ["CounterElectrode", "ReferenceElectrode"]
    # No polarity anywhere on a half cell — that is the whole ruling.
    assert "hasPositiveElectrode" not in node
    assert "hasNegativeElectrode" not in node


def test_role_holders_carry_the_same_composition_as_a_polarity_holder() -> None:
    """An electrode's active-material typing is role-independent."""
    role = record_to_jsonld(_half_cell().to_record(), "cell-spec")["hasWorkingElectrode"]
    polarity = record_to_jsonld(
        CellSpec(**_IDENTITY, positive_electrode=_electrode("Graphite")).to_record(),
        "cell-spec",
    )["hasPositiveElectrode"]

    assert role["hasCoating"] == polarity["hasCoating"]
    assert role["hasCoating"]["hasActiveMaterial"]["@type"] == ["Graphite", "ActiveMaterial"]


def test_three_electrode_cell_types_all_three_roles() -> None:
    """With a real third electrode the counter is only the counter."""
    spec = _half_cell()
    spec.cell_configuration = "three_electrode_cell"
    spec.reference_electrode = "lithium"
    node = record_to_jsonld(spec.to_record(), "cell-spec")

    assert node["hasWorkingElectrode"]["@type"] == "WorkingElectrode"
    assert node["hasCounterElectrode"]["@type"] == "CounterElectrode"
    assert "ReferenceElectrode" not in json.dumps(node["hasCounterElectrode"])
    assert "ThreeElectrodeCellDevice" in node["isDescriptionFor"]["@type"]


def test_cell_typing_is_unchanged_by_the_role_holders() -> None:
    """BatteryHalfCell + HalfCellDevice still come from cell_configuration alone."""
    with_roles = record_to_jsonld(_half_cell().to_record(), "cell-spec")
    without_roles = record_to_jsonld(
        CellSpec(**_IDENTITY, cell_configuration="half_cell").to_record(), "cell-spec"
    )
    assert with_roles["isDescriptionFor"]["@type"] == without_roles["isDescriptionFor"]["@type"]
    assert "BatteryHalfCell" in with_roles["isDescriptionFor"]["@type"]
    assert "HalfCellDevice" in with_roles["isDescriptionFor"]["@type"]


def test_full_cell_emission_is_untouched() -> None:
    node = record_to_jsonld(
        CellSpec(
            **_IDENTITY, cell_configuration="full_cell",
            positive_electrode_basis="lfp", negative_electrode_basis="graphite",
            positive_electrode=_electrode("LFP"),
            negative_electrode=_electrode("Graphite"),
        ).to_record(),
        "cell-spec",
    )
    assert node["hasPositiveElectrode"]["@type"] == "LithiumIronPhosphateElectrode"
    assert node["hasNegativeElectrode"]["@type"] == "GraphiteElectrode"
    assert "hasWorkingElectrode" not in node
    assert "hasCounterElectrode" not in node
    assert not {"BatteryHalfCell", "HalfCellDevice"} & set(node["isDescriptionFor"]["@type"])


def test_a_chemistry_basis_does_not_invent_a_polarity_electrode_for_a_half_cell() -> None:
    """The bases still type the CELL; they no longer type a polarity ELECTRODE.

    Half-cell records carry ``positive_electrode_basis`` / ``negative_electrode_basis``
    as chemistry descriptors, and those keep stacking the battery classes. What
    they must not do once the role holders say where the electrodes are is emit a
    second, polarity-named electrode node beside them.
    """
    node = record_to_jsonld(
        _half_cell(positive_electrode_basis="graphite", negative_electrode_basis="lithium").to_record(),
        "cell-spec",
    )
    assert "hasPositiveElectrode" not in node
    assert "hasNegativeElectrode" not in node
    # The chemistry survives where it belongs: on the cell.
    assert "LithiumMetalBattery" in node["isDescriptionFor"]["@type"]


def test_an_authored_polarity_holder_is_never_dropped_by_the_configuration() -> None:
    """Suppression applies to the basis fallback only — never to authored data."""
    spec = _half_cell()
    spec.positive_electrode = _electrode("NMC811")
    node = record_to_jsonld(spec.to_record(), "cell-spec")
    assert node["hasPositiveElectrode"]["hasCoating"]["hasActiveMaterial"]["schema:name"] == "NMC811"
    assert node["hasWorkingElectrode"]["@type"] == "WorkingElectrode"


def test_descriptor_path_agrees_with_the_canonical_path() -> None:
    """Emitter convergence: both user-facing emitters type the roles identically."""
    record = _half_cell().to_record()
    canonical = record_to_jsonld(record, "cell-spec")
    descriptor = to_jsonld(record, target="domain-battery")["@graph"][0]

    for relation in ("hasWorkingElectrode", "hasCounterElectrode"):
        assert descriptor[relation]["@type"] == canonical[relation]["@type"]
    assert descriptor["isDescriptionFor"]["@type"] == canonical["isDescriptionFor"]["@type"]


def test_every_emitted_role_term_resolves_in_the_published_context() -> None:
    from importlib import resources

    path = resources.files("battinfo").joinpath("data", "context", "records.context.v1.json")
    with path.open("r", encoding="utf-8") as handle:
        context = json.load(handle)["@context"]

    for term in ("hasWorkingElectrode", "hasCounterElectrode", "hasReferenceElectrode",
                 "WorkingElectrode", "CounterElectrode", "ReferenceElectrode"):
        assert term in context, f"{term} does not resolve in the v1 records context"


# ── The electrode-spec seams ──────────────────────────────────────────────────

def test_role_holders_carry_both_electrode_spec_seams() -> None:
    """The two reference styles the polarity holders have, on the role holders."""
    spec = _half_cell(working_electrode_spec_id=DESIGN_IRI)
    spec.counter_electrode.electrode_spec_id = DESIGN_IRI

    record = spec.to_record()
    assert record["working_electrode_spec_id"] == DESIGN_IRI
    assert record["counter_electrode"]["electrode_spec_id"] == DESIGN_IRI

    node = record_to_jsonld(record, "cell-spec")
    # Top-level reference: the @id merges onto the emitted node (one node).
    assert node["hasWorkingElectrode"]["@id"] == DESIGN_IRI
    # Inline reference: the holder realizes a design without claiming to be it.
    assert node["hasCounterElectrode"]["schema:isVariantOf"] == {"@id": DESIGN_IRI}


def test_a_role_spec_reference_without_an_inline_holder_emits_a_bare_reference() -> None:
    node = record_to_jsonld(
        CellSpec(**_IDENTITY, cell_configuration="half_cell",
                 working_electrode_spec_id=DESIGN_IRI).to_record(),
        "cell-spec",
    )
    assert node["hasWorkingElectrode"] == {"@id": DESIGN_IRI}


def test_role_spec_references_are_validated_at_the_input_boundary() -> None:
    from battinfo.api import save_cell_spec

    spec = _half_cell(counter_electrode_spec_id="not-an-iri")
    with pytest.raises(ValueError, match="counter_electrode_spec_id"):
        save_cell_spec(spec, validate=False)


# ── Round trip + persistence ──────────────────────────────────────────────────

def test_round_trip_is_idempotent() -> None:
    record = _half_cell(working_electrode_spec_id=DESIGN_IRI).to_record()
    assert CellSpec.from_record(record).to_record() == record


def test_authoring_round_trips_through_save_and_emission(tmp_path: Path) -> None:
    from battinfo.api import save_cell_spec

    # Strict validation: a role-holder half cell must pass the save gate.
    save_cell_spec(_half_cell(), source_root=tmp_path, validation_policy="strict")

    written = next((tmp_path / "cell-spec").rglob("*.json"))
    record = json.loads(written.read_text(encoding="utf-8"))
    assert record["working_electrode"]["coating"]["component"]["active_material"][0]["name"] == "Graphite"
    assert record["counter_electrode"]["coating"]["component"]["active_material"][0]["name"] == "Lithium"

    node = record_to_jsonld(record, "cell-spec")
    assert node["hasCounterElectrode"]["@type"] == ["CounterElectrode", "ReferenceElectrode"]


# ── The save-gate coherence warnings ──────────────────────────────────────────

def _codes(spec: CellSpec) -> set[str]:
    report = validate_record_report(spec.to_record(), policy="strict")
    assert report.ok, f"coherence must never block a save: {report.render_errors()}"
    return {issue.code for issue in report.warnings}


def test_polarity_holders_on_a_half_cell_warn() -> None:
    spec = CellSpec(**_IDENTITY, cell_configuration="half_cell",
                    positive_electrode=_electrode("Graphite"),
                    negative_electrode=_electrode("Lithium"))
    assert "semantic.electrode_role_expected" in _codes(spec)


def test_polarity_holders_on_a_three_electrode_cell_warn() -> None:
    spec = CellSpec(**_IDENTITY, cell_configuration="three_electrode_cell",
                    positive_electrode=_electrode("NMC811"))
    assert "semantic.electrode_role_expected" in _codes(spec)


@pytest.mark.parametrize("configuration", ["full_cell", None])
def test_role_holders_on_a_full_cell_warn(configuration: str | None) -> None:
    spec = CellSpec(**_IDENTITY, cell_configuration=configuration,
                    working_electrode=_electrode("Graphite"))
    assert "semantic.electrode_polarity_expected" in _codes(spec)


def test_both_families_populated_warns_once_and_names_the_preferred_one() -> None:
    spec = _half_cell()
    spec.positive_electrode = _electrode("Graphite")
    report = validate_record_report(spec.to_record(), policy="strict")
    coherence = [i for i in report.warnings if i.code.startswith("semantic.electrode_")]

    assert [i.code for i in coherence] == ["semantic.electrode_holders_mixed"]
    assert "working_electrode / counter_electrode" in coherence[0].message


def test_both_families_on_a_full_cell_names_the_polarity_pair() -> None:
    spec = CellSpec(**_IDENTITY, cell_configuration="full_cell",
                    positive_electrode=_electrode("NMC811"),
                    working_electrode=_electrode("NMC811"))
    report = validate_record_report(spec.to_record(), policy="strict")
    mixed = [i for i in report.warnings if i.code == "semantic.electrode_holders_mixed"]
    assert len(mixed) == 1
    assert "positive_electrode / negative_electrode" in mixed[0].message


def test_a_spec_id_reference_counts_as_a_populated_holder() -> None:
    """A reference places an electrode just as an inline holder does."""
    spec = CellSpec(**_IDENTITY, cell_configuration="half_cell",
                    positive_electrode_spec_id=DESIGN_IRI)
    assert "semantic.electrode_role_expected" in _codes(spec)


def test_the_reference_electrode_marker_is_read_as_a_half_cell() -> None:
    """The gate agrees with the emitter's own unstated-configuration fallback."""
    spec = CellSpec(**_IDENTITY, reference_electrode="lithium",
                    positive_electrode=_electrode("Graphite"))
    assert "semantic.electrode_role_expected" in _codes(spec)


@pytest.mark.parametrize("spec", [
    _half_cell(),
    CellSpec(**_IDENTITY, cell_configuration="full_cell", positive_electrode=_electrode("NMC811")),
    CellSpec(**_IDENTITY),
])
def test_a_coherent_record_warns_about_nothing(spec: CellSpec) -> None:
    assert not {code for code in _codes(spec) if code.startswith("semantic.electrode_")}


# ── Parity with the polarity holders ──────────────────────────────────────────

def test_role_holders_reach_the_component_lifting_bridge() -> None:
    """A role holder lifts to a standalone electrode-spec like a polarity one."""
    from battinfo.components import extract_component_specs

    names = [spec["electrode_spec"]["name"] for spec in extract_component_specs(_half_cell().to_record())]
    assert any("working electrode" in name.lower() for name in names), names
    assert any("counter electrode" in name.lower() for name in names), names


def test_role_holder_materials_are_extracted_without_a_polarity() -> None:
    """The powders are still harvested; none of them is assigned a side."""
    from battinfo.materials import extract_material_specs

    specs = extract_material_specs(_half_cell().to_record())
    names = {s["material_spec"]["name"] for s in specs}
    assert {"Graphite", "Lithium"} <= names
    for spec in specs:
        assert spec["material_spec"].get("electrode_polarity") in (None, "none")
