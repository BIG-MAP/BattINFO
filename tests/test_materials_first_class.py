"""First-class materials model: identity (H1), attribution (H2), emission (M6), kind.

Regression tests for the three-level materials model. Each maps to a readiness
finding (battinfo-records#6 READINESS-REPORT.md) the model fixes.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import battinfo
import battinfo.api as api
from battinfo.materials import resolve_material_kind

# ── H1: deterministic, content-derived ids (was: random id every call) ──────────

def test_h1_material_spec_is_deterministic_and_dedupes() -> None:
    ids = [
        api.create_material_spec(name="Graphite", formula="C", validate=False)["material_spec"]["id"]
        for _ in range(3)
    ]
    assert len(set(ids)) == 1  # identical create calls -> one id (H1 dead)
    assert ids[0].startswith("https://w3id.org/battinfo/spec/")


def test_h1_identity_basis_is_manufacturer_product_grade() -> None:
    a = api.create_material_spec(name="NMC811", kind="nmc811", manufacturer="Targray", grade="X", validate=False)
    b = api.create_material_spec(name="NMC811", kind="nmc811", manufacturer="Targray", grade="X", validate=False)
    c = api.create_material_spec(name="NMC811", kind="nmc811", manufacturer="Targray", grade="Y", validate=False)
    assert a["material_spec"]["id"] == b["material_spec"]["id"]
    assert a["material_spec"]["id"] != c["material_spec"]["id"]  # grade is part of identity


def test_h1_material_instance_id_from_spec_and_lot() -> None:
    spec = api.create_material_spec(name="LFP", validate=False)["material_spec"]["id"]
    m1 = api.create_material(material_spec_id=spec, lot="LOT-1", validate=False)["material"]["id"]
    m2 = api.create_material(material_spec_id=spec, lot="LOT-1", validate=False)["material"]["id"]
    m3 = api.create_material(material_spec_id=spec, lot="LOT-2", validate=False)["material"]["id"]
    assert m1 == m2 and m1 != m3


def test_h1_resave_is_unchanged(tmp_path: Path) -> None:
    ws_root = tmp_path / "proj"
    ws_root.mkdir()

    def author():
        ws = battinfo.workspace(str(ws_root))
        ws.add("material_spec", name="LFP", kind="lfp", manufacturer="Canrud", grade="std",
               property={"specific_capacity": {"value": 160, "unit": "mAh/g"}})
        return ws.save()

    first = author()
    assert first["material_specs"][0]["status"] == "created"
    second = author()
    item = second["material_specs"][0]
    # A same-IRI re-save of identical content is a no-op (content_changed False).
    assert item.get("content_changed") is False


# ── H2: attribution allowed on the schema and stamped by ws.save ────────────────

def test_h2_attribution_stamped_on_both_material_types(tmp_path: Path) -> None:
    ws = battinfo.workspace(str(tmp_path))
    ws.license("cc-by-4.0")
    ws.contributor(orcid="0000-0002-1825-0097", name="Josiah Carberry")
    spec = ws.add("material_spec", name="LFP", kind="lfp")[0]
    ws.add("material", spec=spec, lot="LOT-9")
    ws.save()

    for subdir, key in (("material-spec", "material_spec"), ("material", "material")):
        files = list((tmp_path / ".battinfo" / "records" / subdir).glob("*.json"))
        assert files, f"no {subdir} record written"
        doc = json.loads(files[0].read_text(encoding="utf-8"))
        assert doc.get("license") == "cc-by-4.0", f"{subdir} missing stamped license (H2)"
        assert doc.get("contributor"), f"{subdir} missing stamped contributor (H2)"
        assert doc["contributor"][0]["same_as"].endswith("0000-0002-1825-0097")


def test_h2_material_spec_schema_permits_attribution() -> None:
    from battinfo.validate.record import validate_record

    spec = api.create_material_spec(name="LFP", kind="lfp", validate=False)
    spec["license"] = "cc-by-4.0"
    spec["contributor"] = [{"type": "Person", "name": "A", "same_as": "https://orcid.org/0000-0002-1825-0097"}]
    spec["funding"] = {"type": "Grant", "identifier": "101069765"}
    assert validate_record(spec).ok  # no additionalProperties error (was H2)


# ── M6 / M5: JSON-LD emitted for both material types ────────────────────────────

def test_m6_jsonld_emitted_for_spec_and_instance() -> None:
    from battinfo.jsonld import record_to_jsonld

    spec = api.create_material_spec(name="LFP", kind="lfp", validate=False)
    ld = record_to_jsonld(spec, "material-spec")
    assert ld["@type"] == "LithiumIronPhosphate"
    assert ld["schema:sameAs"]["@id"].startswith(
        "https://w3id.org/emmo/domain/chemical-substance#"
    )  # kind -> chemical-substance class node

    inst = api.create_material(material_spec_id=spec["material_spec"]["id"], lot="L1", validate=False)
    ldm = record_to_jsonld(inst, "material")
    assert ldm["schema:isVariantOf"]["@id"] == spec["material_spec"]["id"]


def test_m6_kind_without_emmo_class_uses_labeled_fallback() -> None:
    from battinfo.jsonld import record_to_jsonld

    # mno2 is anchored in chemical-substance but has no domain-battery class the
    # bundled context resolves, so the node falls back to a labeled
    # schema:ChemicalSubstance that still carries the chemsub link.
    spec = api.create_material_spec(name="EMD cathode powder", kind="mno2", validate=False)
    ld = record_to_jsonld(spec, "material-spec")
    assert ld["@type"] == "schema:ChemicalSubstance"  # labeled fallback, not invented term
    assert ld["schema:sameAs"]["@id"].startswith(
        "https://w3id.org/emmo/domain/chemical-substance#"
    )


# ── kind vocabulary + validation ────────────────────────────────────────────────

def test_kind_alias_resolution() -> None:
    assert resolve_material_kind("NMC 811") == "nmc811"
    assert resolve_material_kind("LiNi0.8Mn0.1Co0.1O2") == "nmc811"
    assert resolve_material_kind("Si/Gr") == "silicon_graphite"
    assert resolve_material_kind("nonsense") is None


def test_unknown_kind_rejected_with_helpful_message() -> None:
    with pytest.raises(ValueError) as exc:
        api.create_material_spec(name="X", kind="unobtanium", validate=False)
    msg = str(exc.value)
    assert "Unknown material kind" in msg and "unobtanium" in msg
    assert "graphite" in msg  # lists valid keys


def test_missing_kind_blocks_strict_save_only(tmp_path: Path) -> None:
    from battinfo.validate.record import validate_record

    spec = api.create_material_spec(uid="abcd23456789abcd", name="Mystery Powder", validate=False)
    assert "kind" not in spec["material_spec"]
    # default policy: warning (tolerant flows validate)
    assert validate_record(spec).ok
    # strict policy (ws.save): missing kind is an error
    assert not validate_record(spec, policy="strict").ok


def test_kinds_carry_chemsub_or_are_flagged_gaps() -> None:
    kinds = battinfo.material_kinds()["kinds"]
    # the full seed set the model requires is present
    required = {"graphite", "silicon", "silicon_graphite", "hard_carbon", "lto",
                "lnmo", "lfp", "lmo", "nmc111", "nmc532", "nmc622", "nmc811",
                "lithium_metal", "pvdf", "carbon_black", "lipf6", "litfsi",
                "lifsi", "nmp"}
    assert required.issubset(kinds)
    # every chemsub anchor is a chemical-substance class IRI; none is invented
    for key, entry in kinds.items():
        chemsub = entry.get("chemsub")
        assert chemsub is None or chemsub.startswith(
            "https://w3id.org/emmo/domain/chemical-substance#substance_"
        ), f"{key} carries a non-chemical-substance anchor"
    # silicon_graphite was the seed's ontology gap; chemical-substance 0.15.0
    # published SiliconGraphite, so it now anchors like the rest
    assert kinds["silicon_graphite"]["emmo"] == "SiliconGraphite"


def test_every_kind_emmo_class_resolves_in_the_bundled_context() -> None:
    """A kind's ``emmo`` class must be a term the domain-battery context resolves,
    and must name the same substance as its ``chemsub`` anchor."""
    import json
    from importlib import resources

    ctx_file = resources.files("battinfo").joinpath("data", "context", "domain-battery.context.json")
    with ctx_file.open("r", encoding="utf-8") as handle:
        context = json.load(handle)["@context"]
    for key, entry in battinfo.material_kinds()["kinds"].items():
        emmo_class = entry.get("emmo")
        if emmo_class is None:
            continue
        assert emmo_class in context, f"{key}: {emmo_class} does not resolve in the bundled context"
        if entry.get("chemsub"):
            assert context[emmo_class] == entry["chemsub"], f"{key}: emmo/chemsub disagree"


def test_external_identity_anchors_emit_as_exact_match() -> None:
    from battinfo.jsonld import record_to_jsonld

    spec = api.create_material_spec(name="SLP30", kind="graphite", validate=False)
    matches = {m["@id"] for m in record_to_jsonld(spec, "material-spec")["skos:exactMatch"]}
    assert matches == {
        "http://www.wikidata.org/entity/Q5309",
        "https://pubchem.ncbi.nlm.nih.gov/compound/5462310",
        "https://next-gen.materialsproject.org/materials/mp-48",
    }
    # a kind with no verified anchors emits none, rather than a guessed one
    plain = api.create_material_spec(name="PVDF binder", kind="pvdf", validate=False)
    assert "skos:exactMatch" not in record_to_jsonld(plain, "material-spec")


def test_no_inchikeys_are_guessed() -> None:
    """The field exists on the schema; molecular-species curation follows later.
    Populating it with anything unverified is the failure mode this guards."""
    kinds = battinfo.material_kinds()["kinds"]
    assert not [k for k, e in kinds.items() if e.get("inchikey")]


def test_anchor_fields_stay_inside_the_declared_set() -> None:
    """A typo'd anchor key would silently emit nothing; pin the field names."""
    from battinfo.materials import EXTERNAL_ID_FIELDS, EXTERNAL_ID_IRI_TEMPLATES

    known = {"label", "roles", "roles_note", "formula", "chemsub", "emmo",
             "aliases", "reference_properties", *EXTERNAL_ID_FIELDS}
    for key, entry in battinfo.material_kinds()["kinds"].items():
        unexpected = set(entry) - known
        assert not unexpected, f"{key} carries unrecognised fields {unexpected}"
    assert set(EXTERNAL_ID_IRI_TEMPLATES).issubset(EXTERNAL_ID_FIELDS)
