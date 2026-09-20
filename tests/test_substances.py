"""Substance vocabulary and resolver tests. Fully offline: the vocabulary ships
with the package; nothing here touches the network."""

import re

import pytest

from battinfo import substances
from battinfo.substances import AmbiguousSubstanceError, resolve, suggest

INCHIKEY_RE = re.compile(r"^[A-Z]{14}-[A-Z]{10}-[A-Z]$")


# ── resolution: the everyday cases ──────────────────────────────────────────────

def test_unique_symbol_resolves_without_slot():
    sub = resolve("LiPF6")
    assert sub is not None
    assert sub.inchikey == "AXPLOJNSKRXQPA-UHFFFAOYSA-N"
    assert sub.pubchem_cid == 23688915
    assert sub.identity_basis == "structure"


def test_resolution_is_case_and_separator_insensitive():
    for spelling in ("lipf6", "LiPF6", "LIPF6", "li pf6"):
        assert resolve(spelling).pubchem_cid == 23688915
    assert resolve("emim-tfsi").symbol == "EMIM-TFSI"
    assert resolve("EMIMTFSI").symbol == "EMIM-TFSI"


def test_full_name_resolves_like_symbol():
    assert resolve("ethylene carbonate").pubchem_cid == 7303
    assert resolve("Ethylene Carbonate").symbol == "EC"
    # chemsub CamelCase label works as an alias
    assert resolve("EthyleneCarbonate").pubchem_cid == 7303


def test_unique_symbol_resolves_regardless_of_slot():
    # roles are collision discriminators, never usage constraints:
    # VC used in an unusual slot still resolves.
    assert resolve("VC", slot="solvent").pubchem_cid == 13385


# ── collisions: EC is the canonical case ────────────────────────────────────────

def test_colliding_symbol_needs_slot():
    with pytest.raises(AmbiguousSubstanceError):
        resolve("EC")


def test_colliding_symbol_resolved_by_slot():
    solvent = resolve("EC", slot="solvent")
    assert solvent.pubchem_cid == 7303
    binder = resolve("EC", slot="binder")
    assert binder.identity_basis == "label"
    assert binder.pubchem_cid is None


def test_ambiguity_error_names_the_candidates():
    with pytest.raises(AmbiguousSubstanceError) as exc:
        resolve("EC")
    message = str(exc.value)
    assert "slot=" in message
    assert "binder" in message


# ── misses: honest None plus suggestions, never auto-accept ─────────────────────

def test_unknown_name_returns_none():
    assert resolve("definitely-not-a-substance") is None
    assert resolve("") is None
    assert resolve("   ") is None


def test_typo_gets_a_suggestion_but_not_a_result():
    assert resolve("EMD") is None
    hints = suggest("EMC2")
    assert "EMC" in hints


# ── identity stamping ───────────────────────────────────────────────────────────

def test_identity_fields_contain_only_known_values():
    fields = resolve("LiTFSI").identity_fields()
    assert fields["inchikey"] == "QSZMZKBZAYQGRS-UHFFFAOYSA-N"
    assert fields["pubchem_cid"] == 3816071
    assert "smiles" in fields
    label_only = resolve("EC", slot="binder").identity_fields()
    assert "inchikey" not in label_only
    assert label_only["label"]


def test_salt_ion_decomposition_resolves_within_vocabulary():
    for salt_symbol in ("LiPF6", "LiTFSI", "NaPF6", "KOH", "EMIM-TFSI"):
        salt = resolve(salt_symbol, slot="solvent") if salt_symbol == "EMIM-TFSI" else resolve(salt_symbol)
        assert salt.ions, salt_symbol
        cation = resolve(salt.ions["cation"])
        anion = resolve(salt.ions["anion"])
        assert cation is not None and anion is not None
        # the pinned salt SMILES is exactly the dot-join of its ions
        assert sorted(salt.smiles.split(".")) == sorted([cation.smiles, anion.smiles])


# ── vocabulary integrity ────────────────────────────────────────────────────────

def test_every_structure_entry_has_a_valid_inchikey():
    for sub in substances._vocab():
        if sub.identity_basis == "structure":
            assert sub.inchikey and INCHIKEY_RE.match(sub.inchikey), sub.symbol
            assert sub.pubchem_cid, sub.symbol
        else:
            assert sub.inchikey is None


def test_inchikeys_are_unique():
    keys = [s.inchikey for s in substances._vocab() if s.inchikey]
    assert len(keys) == len(set(keys))


def test_colliding_symbols_have_disjoint_roles():
    by_symbol: dict[str, list] = {}
    for sub in substances._vocab():
        by_symbol.setdefault(sub.symbol, []).append(sub)
    for symbol, group in by_symbol.items():
        if len(group) > 1:
            role_sets = [set(g.roles) for g in group]
            for i, a in enumerate(role_sets):
                for b in role_sets[i + 1:]:
                    assert a and b and not (a & b), f"{symbol}: colliding entries need disjoint roles"


def test_oedb_core_coverage():
    # the OEDB crosswalk that seeded the vocabulary stays resolvable
    for symbol in ("AN", "DMC", "DEC", "EMC", "PC", "GBL", "FEC",
                   "PF6-", "TFSI-", "FSI-", "BF4-", "Li+", "Na+", "K+"):
        assert resolve(symbol, slot="solvent") is not None, symbol


def test_vocabulary_version_present():
    assert substances.vocabulary_version() != "0"
