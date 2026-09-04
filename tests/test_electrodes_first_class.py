"""First-class electrodes: identity, kind, attribution, emission, cell linkage.

The material spec describes the powder; the electrode spec describes the
electrode. These tests pin the four things that promotion had to deliver, each
mirroring its material counterpart in ``test_materials_first_class.py``:

* deterministic content-derived ids (with the processing route in the seed);
* a required ``kind`` naming the ACTIVE material, with the powder reference
  OPTIONAL so a purchased electrode stays expressible;
* attribution stamped by ws.save onto both record types;
* JSON-LD emission that types the node from the kind and hangs the processing
  route off ``prov:wasGeneratedBy``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import battinfo
import battinfo.api as api
from battinfo.electrodes import (
    electrode_kind_keys,
    is_active_kind,
    resolve_electrode_kind,
)

SPEC_IRI = "https://w3id.org/battinfo/spec/abcd-2345-6789-abcd"


# ── Identity: deterministic, content-derived, route-aware ──────────────────────

def test_electrode_spec_id_is_deterministic() -> None:
    ids = [
        api.create_electrode_spec(name="Graphite anode", kind="graphite", validate=False)[
            "electrode_spec"
        ]["id"]
        for _ in range(3)
    ]
    assert len(set(ids)) == 1
    assert ids[0].startswith("https://w3id.org/battinfo/spec/")


def test_identity_basis_is_producer_product_grade() -> None:
    def spec(**kw):
        return api.create_electrode_spec(
            name="NMC811 cathode", kind="nmc811", manufacturer="Canrud", validate=False, **kw
        )["electrode_spec"]["id"]

    assert spec(grade="A") == spec(grade="A")
    assert spec(grade="A") != spec(grade="B")


def test_processing_route_is_part_of_spec_identity() -> None:
    """An aqueous electrode is a different design from an NMP one, so a different IRI.

    This is the one deliberate divergence from the material-spec seed, where
    processing is an instance property. Collapsing the two here would silently
    overwrite one design with the other.
    """
    def spec(route: str | None):
        kwargs = {"processing": {"route": route}} if route else {}
        return api.create_electrode_spec(
            name="Si-Gr anode", kind="silicon_graphite", manufacturer="SINTEF",
            validate=False, **kwargs,
        )["electrode_spec"]["id"]

    assert spec("aqueous") != spec("nmp")
    assert spec("aqueous") == spec("aqueous")


def test_electrode_batch_id_from_spec_and_batch() -> None:
    spec_id = api.create_electrode_spec(name="LFP cathode", kind="lfp", validate=False)[
        "electrode_spec"
    ]["id"]
    a = api.create_electrode(electrode_spec_id=spec_id, batch="B-1", validate=False)["electrode"]["id"]
    b = api.create_electrode(electrode_spec_id=spec_id, batch="B-1", validate=False)["electrode"]["id"]
    c = api.create_electrode(electrode_spec_id=spec_id, batch="B-2", validate=False)["electrode"]["id"]
    assert a == b and a != c
    assert a.startswith("https://w3id.org/battinfo/electrode/")


def test_resave_of_identical_content_is_unchanged(tmp_path: Path) -> None:
    def author():
        ws = battinfo.workspace(str(tmp_path))
        spec = ws.add("electrode_spec", name="Graphite anode", kind="graphite",
                      manufacturer="Canrud",
                      property={"loading": {"value": 11.5, "unit": "mg/cm2"}})[0]
        ws.add("electrode", spec=spec, batch="GR-1")
        return ws.save()

    first = author()
    assert first["electrode_specs"][0]["status"] == "created"
    assert first["electrodes"][0]["status"] == "created"
    second = author()
    assert second["electrode_specs"][0].get("content_changed") is False
    assert second["electrodes"][0].get("content_changed") is False


# ── Kind: required, controlled, and the ACTIVE material ────────────────────────

def test_kind_resolves_through_the_material_vocabulary() -> None:
    assert resolve_electrode_kind("Si/Gr") == "silicon_graphite"
    assert resolve_electrode_kind("NMC 811") == "nmc811"
    assert resolve_electrode_kind("nonsense") is None


def test_advertised_kinds_are_the_active_materials() -> None:
    keys = electrode_kind_keys()
    assert "graphite" in keys and "nmc811" in keys and "lithium_metal" in keys
    assert "pvdf" not in keys and "lipf6" not in keys  # binders/salts are not electrodes
    assert all(is_active_kind(k) for k in keys)


def test_polarity_is_authored_never_derived() -> None:
    # The vocabulary assigns no side to an active material (system-relative:
    # graphite is the positive electrode of a lithium-counter half cell), so a
    # spec carries polarity only when its author states it.
    spec = api.create_electrode_spec(name="LFP electrode", kind="lfp", validate=False)
    assert "polarity" not in spec["electrode_spec"]

    authored = api.create_electrode_spec(
        name="LFP positive electrode", kind="lfp", polarity="positive", validate=False
    )
    assert authored["electrode_spec"]["polarity"] == "positive"


def test_unknown_kind_rejected_with_helpful_message() -> None:
    with pytest.raises(ValueError) as exc:
        api.create_electrode_spec(name="X", kind="unobtanium", validate=False)
    msg = str(exc.value)
    assert "Unknown electrode kind" in msg and "unobtanium" in msg
    assert "graphite" in msg


def test_missing_kind_blocks_strict_save_only() -> None:
    from battinfo.validate.record import validate_record

    spec = api.create_electrode_spec(uid="abcd23456789abcd", name="Mystery electrode", validate=False)
    assert "kind" not in spec["electrode_spec"]
    assert validate_record(spec).ok               # tolerant flows still validate
    assert not validate_record(spec, policy="strict").ok  # ws.save requires it


def test_non_active_kind_warns_rather_than_failing() -> None:
    from battinfo.validate.semantic import validate_semantic_report

    spec = api.create_electrode_spec(uid="abcd23456789abcd", name="Binder layer", kind="pvdf",
                                     validate=False)
    report = validate_semantic_report(spec, policy="default")
    issue = next(i for i in report.issues if i.code == "semantic.electrode_kind_not_active")
    assert issue.severity == "warning"


def test_authored_polarity_never_conflicts_with_the_kind() -> None:
    # Retired check: with no vocabulary-assigned side there is nothing for an
    # authored polarity to disagree with (an "LFP negative electrode" is a
    # legitimate design in a lithium-counter half cell).
    from battinfo.validate.semantic import validate_semantic_report

    spec = api.create_electrode_spec(uid="abcd23456789abcd", name="LFP working electrode",
                                     kind="lfp", polarity="negative", validate=False)
    report = validate_semantic_report(spec, policy="default")
    assert not any(i.code == "semantic.electrode_polarity_conflict" for i in report.issues)


def test_purchased_electrode_needs_no_material_spec() -> None:
    """The point of a required kind and an optional powder reference."""
    spec = api.create_electrode_spec(
        name="Vendor NMC811 cathode sheet", kind="nmc811", manufacturer="Some Vendor",
        validate=False,
    )["electrode_spec"]
    assert spec["kind"] == "nmc811"
    assert "active_material_spec_id" not in spec


# ── Composition: the cell-spec coating shape, not a divergent one ──────────────

def test_composition_shorthand_expands_to_the_canonical_coating_shape() -> None:
    spec = api.create_electrode_spec(
        name="Graphite anode", kind="graphite",
        composition={"active": 0.95,
                     "binder": {"name": "CMC", "fraction": 0.04},
                     "conductive_additive": {"name": "Carbon black", "fraction": 0.01}},
        validate=False,
    )["electrode_spec"]
    component = spec["coating"]["component"]
    assert component["active_material"][0]["name"] == "Graphite"  # derived from the kind
    assert component["active_material"][0]["property"]["mass_fraction"] == {"value": 0.95, "unit": "1"}
    assert component["binder"][0]["name"] == "CMC"
    assert component["additive"][0]["name"] == "Carbon black"


def test_active_material_reference_reaches_the_coating_holder() -> None:
    spec = api.create_electrode_spec(
        name="Graphite anode", kind="graphite", active_material_spec_id=SPEC_IRI,
        composition={"active": 0.95}, validate=False,
    )["electrode_spec"]
    holder = spec["coating"]["component"]["active_material"][0]
    assert holder["material_spec_id"] == SPEC_IRI


def test_bare_fraction_without_a_derivable_name_is_a_helpful_error() -> None:
    with pytest.raises(ValueError, match="bare weight fraction"):
        api.create_electrode_spec(
            name="X", kind="graphite", composition={"binder": 0.04}, validate=False
        )


# ── Attribution: stamped like every other record type ─────────────────────────

def test_attribution_stamped_on_both_electrode_types(tmp_path: Path) -> None:
    ws = battinfo.workspace(str(tmp_path))
    ws.license("cc-by-4.0")
    ws.contributor(orcid="0000-0002-1825-0097", name="Josiah Carberry")
    spec = ws.add("electrode_spec", name="Graphite anode", kind="graphite")[0]
    ws.add("electrode", spec=spec, batch="GR-1")
    ws.save()

    for subdir in ("electrode-spec", "electrode"):
        files = list((tmp_path / ".battinfo" / "records" / subdir).glob("*.json"))
        assert files, f"no {subdir} record written"
        doc = json.loads(files[0].read_text(encoding="utf-8"))
        assert doc.get("license") == "cc-by-4.0", f"{subdir} missing stamped license"
        assert doc.get("contributor"), f"{subdir} missing stamped contributor"
        assert doc["contributor"][0]["same_as"].endswith("0000-0002-1825-0097")


def test_electrode_schemas_permit_attribution() -> None:
    from battinfo.validate.record import validate_record

    for record, key in (
        (api.create_electrode_spec(name="LFP cathode", kind="lfp", validate=False), "electrode_spec"),
        (api.create_electrode(electrode_spec_id=SPEC_IRI, batch="B-1", validate=False), "electrode"),
    ):
        record["license"] = "cc-by-4.0"
        record["contributor"] = [
            {"type": "Person", "name": "A", "same_as": "https://orcid.org/0000-0002-1825-0097"}
        ]
        record["funding"] = {"type": "Grant", "identifier": "101069765"}
        assert validate_record(record).ok, key


# ── Emission ──────────────────────────────────────────────────────────────────

def test_kind_types_the_node_and_authored_polarity_stacks() -> None:
    from battinfo.jsonld import record_to_jsonld

    spec = api.create_electrode_spec(name="Si-Gr electrode", kind="silicon_graphite", validate=False)
    assert record_to_jsonld(spec, "electrode-spec")["@type"] == "SiliconGraphiteElectrode"

    cathode = api.create_electrode_spec(
        name="LFP positive electrode", kind="lfp", polarity="positive", validate=False
    )
    assert record_to_jsonld(cathode, "electrode-spec")["@type"] == [
        "LithiumIronPhosphateElectrode", "PositiveElectrode",
    ]


def test_every_electrode_kind_types_the_node() -> None:
    """No advertised kind falls back to a bare Electrode — that would be a silent gap.

    ``nca`` is the one kind with no chemistry electrode class in the curated entity
    map: that omission is deliberate and pinned by ``test_mapping_governance``
    (NCA carries its chemistry on the cell's battery class instead). It still gets
    its polarity class, so no kind emits an untyped node.
    """
    from battinfo.jsonld import record_to_jsonld

    chemistry_free = {"nca"}
    for kind in electrode_kind_keys():
        spec = api.create_electrode_spec(name=f"{kind} electrode", kind=kind, validate=False)
        types = record_to_jsonld(spec, "electrode-spec")["@type"]
        if kind in chemistry_free:
            # No chemistry electrode class (deliberate; NCA chemistry lives on
            # the cell's battery class) and no vocabulary-assigned side: the
            # generic Electrode class keeps the node typed.
            assert types == "Electrode", f"{kind} typed as {types}"
            continue
        assert types and "Electrode" in str(types), f"{kind} untyped: {types}"


def test_active_material_reference_emits_as_a_linked_node() -> None:
    from battinfo.jsonld import record_to_jsonld

    spec = api.create_electrode_spec(
        name="Graphite anode", kind="graphite", active_material_spec_id=SPEC_IRI, validate=False
    )
    ld = record_to_jsonld(spec, "electrode-spec")
    assert ld["hasActiveMaterial"] == {"@id": SPEC_IRI, "@type": "ActiveMaterial"}


def test_processing_emits_as_a_manufacturing_process() -> None:
    from battinfo.jsonld import record_to_jsonld

    spec = api.create_electrode_spec(
        name="Si-Gr anode", kind="silicon_graphite",
        processing={"route": "nmp", "detail": "planetary mixing"}, validate=False,
    )
    node = record_to_jsonld(spec, "electrode-spec")["prov:wasGeneratedBy"]
    assert node["@type"] == "Manufacturing"
    assert node["dcterms:type"]["schema:termCode"] == "nmp"
    assert node["hasSolvent"]["schema:name"] == "nmp"  # the route names its own solvent
    assert node["schema:description"] == "planetary mixing"


def test_design_values_map_to_emmo_classes() -> None:
    from battinfo.jsonld import record_to_jsonld

    spec = api.create_electrode_spec(
        name="Graphite anode", kind="graphite",
        property={"loading": {"value": 11.5, "unit": "mg/cm2"},
                  "dry_thickness": {"value": 80, "unit": "um"},
                  "calendered_thickness": {"value": 72, "unit": "um"},
                  "areal_capacity": {"value": 4.2, "unit": "mAh/cm2"}},
        validate=False,
    )
    types = {t for p in record_to_jsonld(spec, "electrode-spec")["hasProperty"] for t in p["@type"]}
    assert {"ActiveMassLoading", "DryCoatingThickness", "CalenderedCoatingThickness",
            "AreicCapacity"} <= types


def test_batch_emits_its_spec_link_and_batch_identifier() -> None:
    from battinfo.jsonld import record_to_jsonld

    batch = api.create_electrode(electrode_spec_id=SPEC_IRI, batch="Si-AQ-1", validate=False)
    ld = record_to_jsonld(batch, "electrode")
    assert ld["schema:isVariantOf"]["@id"] == SPEC_IRI
    assert ld["schema:identifier"]["schema:value"] == "Si-AQ-1"


def test_attribution_reaches_the_emitted_electrode_node() -> None:
    from battinfo.jsonld import record_to_jsonld

    spec = api.create_electrode_spec(name="LFP cathode", kind="lfp", validate=False)
    spec["license"] = "cc-by-4.0"
    spec["funding"] = {"type": "Grant", "identifier": "101069765"}
    ld = record_to_jsonld(spec, "electrode-spec")
    assert ld["dcterms:license"] == {"@id": "cc-by-4.0"}
    assert ld["schema:funding"]["schema:identifier"] == "101069765"


# ── Cell-spec linkage ─────────────────────────────────────────────────────────

def test_cell_spec_electrode_holder_may_cite_an_electrode_spec() -> None:
    from battinfo.transform.json_to_jsonld import to_jsonld
    from battinfo.validate.record import validate_record

    record = {
        "schema_version": "0.2.0",
        "cell_spec": {
            "id": "https://w3id.org/battinfo/spec/1111-2222-3333-4444",
            "name": "Demo cell", "model": "Demo", "cell_format": "coin",
            "manufacturer": {"name": "Demo Co"}, "chemistry": "lithium_ion",
            "negative_electrode_basis": "graphite",
        },
        "negative_electrode": {
            "electrode_spec_id": SPEC_IRI,
            "coating": {"component": {"active_material": [{"name": "Graphite"}]}},
        },
        "provenance": {"source_type": "datasheet"},
    }
    # Additive and tolerant: the embedded fields stay valid alongside the reference.
    assert validate_record(record).ok, validate_record(record).errors
    node = to_jsonld(record, target="domain-battery")["@graph"][0]
    assert node["hasNegativeElectrode"]["schema:isVariantOf"] == {"@id": SPEC_IRI}


def test_both_electrode_spec_seams_are_authorable_and_round_trip() -> None:
    """E1: the inline seam was schema-only, so only one of the two was authorable.

    Both must survive to_record -> from_record. They do NOT emit the same
    statement, and must not: the top-level field says the cell spec's electrode
    IS that design (the @id merges onto the electrode node), the inline field
    says this holder is a variant OF it (schema:isVariantOf). See
    docs/electrodes-model.md for which to reach for.
    """
    from battinfo.bundle import CellSpec, Electrode
    from battinfo.transform.json_to_jsonld import to_jsonld

    cs = CellSpec(
        id="https://w3id.org/battinfo/spec/1111-2222-3333-4444",
        name="Demo cell", manufacturer="Demo Co", model="Demo",
        format="coin", chemistry="lithium_ion",
        positive_electrode_spec_id=SPEC_IRI,
        negative_electrode=Electrode(
            coating={"component": {"active_material": [{"name": "Graphite"}]}},
        ),
    )
    cs.negative_electrode.electrode_spec_id = SPEC_IRI

    record = cs.to_record()
    assert record["positive_electrode_spec_id"] == SPEC_IRI
    assert record["negative_electrode"]["electrode_spec_id"] == SPEC_IRI

    reloaded = CellSpec.from_record(record)
    assert reloaded.positive_electrode_spec_id == SPEC_IRI
    assert reloaded.negative_electrode.electrode_spec_id == SPEC_IRI
    assert reloaded.to_record() == record

    node = to_jsonld(record, target="domain-battery")["@graph"][0]
    assert node["hasPositiveElectrode"]["@id"] == SPEC_IRI
    assert node["hasNegativeElectrode"]["schema:isVariantOf"] == {"@id": SPEC_IRI}


def test_inline_current_collector_cites_its_foil_material_spec() -> None:
    """Found by extending the parity guard to nested holders, same family as E1."""
    from battinfo.bundle import CellSpec, CurrentCollector, Electrode
    from battinfo.transform.json_to_jsonld import to_jsonld

    material_spec = "https://w3id.org/battinfo/spec/9999-8888-7777-6666"
    cs = CellSpec(
        id="https://w3id.org/battinfo/spec/1111-2222-3333-4444",
        name="Demo cell", manufacturer="Demo Co", model="Demo",
        format="coin", chemistry="lithium_ion",
        positive_electrode=Electrode(
            current_collector=CurrentCollector(
                name="Aluminium foil", material_spec_id=material_spec,
            ),
        ),
    )
    record = cs.to_record()
    assert record["positive_electrode"]["current_collector"]["material_spec_id"] == material_spec
    assert CellSpec.from_record(record).to_record() == record

    node = to_jsonld(record, target="domain-battery")["@graph"][0]
    collector = node["hasPositiveElectrode"]["hasCurrentCollector"]
    assert collector["schema:isVariantOf"] == {"@id": material_spec}


def test_electrode_spec_reference_only_holder_is_valid() -> None:
    from battinfo.validate.record import validate_record

    record = {
        "schema_version": "0.2.0",
        "cell_spec": {
            "id": "https://w3id.org/battinfo/spec/1111-2222-3333-4444",
            "name": "Demo cell", "model": "Demo", "cell_format": "coin",
            "manufacturer": {"name": "Demo Co"}, "chemistry": "lithium_ion",
        },
        "positive_electrode": {"electrode_spec_id": SPEC_IRI},
        "provenance": {"source_type": "datasheet"},
    }
    assert validate_record(record).ok, validate_record(record).errors


# ── Submission ────────────────────────────────────────────────────────────────

def test_submit_covers_every_saved_record_type() -> None:
    """_SUBDIRS must list every directory ws.save() can write.

    A type ws.save() writes but ws.submit() does not enumerate is a record that
    is saved, reported as saved, and silently never reaches the registry.
    """
    import inspect

    from battinfo.entities import ENTITY_KINDS
    from battinfo.ws import AuthoringWorkspace

    source = inspect.getsource(AuthoringWorkspace.submit)
    saved_subdirs = {
        kind.subdir for kind in ENTITY_KINDS
        if kind.entity_type in {"cell-spec", "cell", "test-protocol", "test", "dataset",
                                "material-spec", "material", "electrode-spec", "electrode"}
    }
    for subdir in saved_subdirs:
        assert f'"{subdir}"' in source, f"ws.submit() never enumerates {subdir}/"
