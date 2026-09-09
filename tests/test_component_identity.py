"""Chemical-identity fields on components and salts: schema acceptance, model
validation, resolver stamping shape, and JSON-LD emission. Offline."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from battinfo.api import create_electrolyte_spec
from battinfo.bundle import MaterialComponent, Salt
from battinfo.substances import resolve
from battinfo.transform.json_to_jsonld import _typed_constituent_node
from battinfo.validate.record import validate_record

EC = {
    "name": "EC",
    "label": "ethylene carbonate",
    "inchikey": "KMTRUDSVKNLOMY-UHFFFAOYSA-N",
    "pubchem_cid": 7303,
    "cas_number": "96-49-1",
    "smiles": "C1COC(=O)O1",
    "property": {"volume_fraction": {"value": 0.3, "unit": "1"}},
}


# ── models ──────────────────────────────────────────────────────────────────────

def test_material_component_accepts_identity_fields():
    comp = MaterialComponent(**EC)
    assert comp.inchikey == "KMTRUDSVKNLOMY-UHFFFAOYSA-N"
    assert comp.pubchem_cid == 7303


def test_salt_accepts_identity_fields():
    salt = Salt(name="LiPF6", inchikey="AXPLOJNSKRXQPA-UHFFFAOYSA-N",
                pubchem_cid=23688915, cation="Li+", anion="PF6-")
    assert salt.inchikey == "AXPLOJNSKRXQPA-UHFFFAOYSA-N"


@pytest.mark.parametrize("bad", ["not-a-key", "KMTRUDSVKNLOMY-UHFFFAOYSA", "kmtrudsvknlomy-uhfffaoysa-n"])
def test_malformed_inchikey_is_rejected(bad):
    with pytest.raises(ValidationError):
        MaterialComponent(name="EC", inchikey=bad)
    with pytest.raises(ValidationError):
        Salt(name="LiPF6", inchikey=bad)


def test_malformed_cas_is_rejected():
    with pytest.raises(ValidationError):
        MaterialComponent(name="EC", cas_number="96491")


# ── schema validation of a full record ──────────────────────────────────────────

def test_electrolyte_spec_with_identity_fields_validates(tmp_path):
    spec = create_electrolyte_spec(
        name="1M LiPF6 in EC:EMC 3:7 (identity-stamped)",
        body={
            "family": "organic",
            "salt": {
                "name": "LiPF6",
                "label": "lithium hexafluorophosphate",
                "inchikey": "AXPLOJNSKRXQPA-UHFFFAOYSA-N",
                "pubchem_cid": 23688915,
                "cation": "Li+",
                "anion": "PF6-",
                "property": {"concentration": {"value": 1.0, "unit": "mol/L"}},
            },
            "solvent_mixture": {"component": [EC]},
        },
        validate=False,
    )
    result = validate_record(spec, source_root=tmp_path)
    assert result.ok, getattr(result, "errors", result)


# ── resolver -> record stamping shape ───────────────────────────────────────────

def test_resolver_identity_fields_fit_the_component_model():
    fields = resolve("EC", slot="solvent").identity_fields()
    comp = MaterialComponent(name="EC", **fields)
    assert comp.inchikey and comp.smiles and comp.label


def test_resolver_identity_fields_fit_the_salt_model():
    fields = resolve("LiTFSI").identity_fields()
    salt = Salt(name="LiTFSI", **fields)
    assert salt.inchikey == "QSZMZKBZAYQGRS-UHFFFAOYSA-N"


# ── JSON-LD emission ────────────────────────────────────────────────────────────

def test_constituent_node_emits_identity_triples():
    node = _typed_constituent_node(EC, "Solvent")
    assert node["schema:inChIKey"] == "KMTRUDSVKNLOMY-UHFFFAOYSA-N"
    assert node["schema:smiles"] == "C1COC(=O)O1"
    assert node["schema:sameAs"] == {"@id": "https://pubchem.ncbi.nlm.nih.gov/compound/7303"}


def test_constituent_node_without_identity_is_unchanged():
    node = _typed_constituent_node({"name": "EC"}, "Solvent")
    assert "schema:inChIKey" not in node
    assert "schema:sameAs" not in node
    assert node["schema:name"] == "EC"


# ── authoring auto-stamp ────────────────────────────────────────────────────────

def test_electrolyte_recipe_stamps_identity_from_names():
    from battinfo.authoring import electrolyte_recipe, material

    elyte = electrolyte_recipe(
        family="organic",
        solvents=[material("EC", volume_fraction={"value": 0.3, "unit": "1"}), "EMC"],
        salt="LiPF6",
        salt_concentration={"value": 1.0, "unit": "mol/L"},
        additives="VC",
    )
    ec, emc = elyte.solvent_mixture.component
    assert ec.inchikey == "KMTRUDSVKNLOMY-UHFFFAOYSA-N"
    assert ec.label == "Ethylene carbonate"
    assert emc.inchikey == "JBTWLSYIZRCDFO-UHFFFAOYSA-N"
    assert elyte.salt.inchikey == "AXPLOJNSKRXQPA-UHFFFAOYSA-N"
    # ion display strings derived from the vocabulary's decomposition
    assert elyte.salt.cation == "Li+"
    assert elyte.salt.anion == "PF6-"
    assert elyte.additive[0].inchikey  # VC resolved
    # explicit properties survive stamping
    assert ec.property["volume_fraction"]["value"] == 0.3
    assert elyte.salt.property["concentration"]["value"] == 1.0


def test_electrolyte_recipe_leaves_unknown_names_unstamped():
    from battinfo.authoring import electrolyte_recipe

    elyte = electrolyte_recipe(family="organic", solvents="mystery-solvent-x", salt="LiPF6")
    assert elyte.solvent_mixture.component[0].inchikey is None


def test_electrolyte_recipe_never_overwrites_explicit_identity():
    from battinfo.authoring import electrolyte_recipe
    from battinfo.bundle import MaterialComponent

    explicit = MaterialComponent(name="EC", inchikey="XXXXXXXXXXXXXX-XXXXXXXXXX-X")
    elyte = electrolyte_recipe(family="organic", solvents=explicit, salt=None)
    assert elyte.solvent_mixture.component[0].inchikey == "XXXXXXXXXXXXXX-XXXXXXXXXX-X"


# ── save-gate warnings for unresolved substances ────────────────────────────────

def test_unresolved_substance_warns_at_validation():
    from battinfo.validate.semantic import validate_semantic_report

    doc = {
        "schema_version": "0.2.0",
        "electrolyte_spec": {
            "id": "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-dddd",
            "name": "mystery mix",
            "family": "organic",
            "salt": {"name": "LiPF6"},
            "solvent_mixture": {"component": [{"name": "unobtainium-ether"}]},
        },
        "provenance": {"source_type": "manual"},
    }
    report = validate_semantic_report(doc)
    codes = [i.code for i in report.issues]
    assert "semantic.substance_unresolved" in codes
    # LiPF6 resolves, so only the unknown solvent warns
    assert codes.count("semantic.substance_unresolved") == 1


def test_typo_warning_carries_suggestion():
    from battinfo.validate.semantic import validate_semantic_report

    doc = {
        "schema_version": "0.2.0",
        "electrolyte_spec": {
            "id": "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-dddd",
            "name": "typo mix",
            "family": "organic",
            "solvent_mixture": {"component": [{"name": "EMC2"}]},
        },
        "provenance": {"source_type": "manual"},
    }
    report = validate_semantic_report(doc)
    warning = next(i for i in report.issues if i.code == "semantic.substance_unresolved")
    assert "EMC" in warning.message


def test_stamped_and_resolvable_components_do_not_warn():
    from battinfo.validate.semantic import validate_semantic_report

    doc = {
        "schema_version": "0.2.0",
        "electrolyte_spec": {
            "id": "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-dddd",
            "name": "clean mix",
            "family": "organic",
            "salt": {"name": "LiPF6"},
            "solvent_mixture": {"component": [EC, {"name": "EMC"}]},
        },
        "provenance": {"source_type": "manual"},
    }
    report = validate_semantic_report(doc)
    assert not [i for i in report.issues if i.code.startswith("semantic.substance")]
