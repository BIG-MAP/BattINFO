# Substance vocabulary

Phase 1-2 of the substance-identity plan (battery-genome/substance-identity-plan.md). Status 2026-08-29: seed complete and fully verified, vocabulary generated, resolver shipped with tests.

## Files

- `seed.csv` — 73 rows (symbol, pubchem_cid, roles, cation_ref, anion_ref, status, note). The only hand-maintained input. Every CID was verified against PubChem (batch property lookup); every salt/IL row's SMILES was checked to equal the dot-join of its referenced ions' SMILES. One label-basis row (EC = ethyl cellulose, a polymer) carries no CID by design.
- `build_vocab.py` — the generator. Joins seed + PubChem (Title, InChIKey, SMILES, formula, molar mass, CAS via synonyms) + domain-chemical-substance (EMMO class IRI, matched by PubChem CID, InChI connectivity cross-checked). Emits `src/battinfo/data/vocab/substances.json`. Fails loudly on any disagreement. Network only on `--refresh`; otherwise runs from `fixtures/`.
- `fixtures/` — cached PubChem responses; the offline SSoT for tests and deterministic rebuilds.
- `oedb_crosswalk.json` — the 26 solvents + 9 anions harvested from OEDB (oedb.jp, CC BY 4.0, cite DOI 10.1038/s41524-026-02093-y). Note their nonstandard abbreviations: OEDB's "MA" is methyl acetoacetate (our MAA) and their "MP" is methyl pyruvate (our MPyr); battery-convention MA/MP (methyl acetate/propionate) are separate seed rows.
- `pubchem_verify.json` — legacy first-pass verification snapshot (superseded by fixtures/).

## Runtime pieces

- `src/battinfo/substances.py` — the resolver: `resolve(name, slot=None)` (exact match; slot breaks symbol collisions like EC solvent vs EC binder), `suggest(name)` for did-you-mean hints, `Substance.identity_fields()` for what a builder stamps into records. Offline always.
- `tests/test_substances.py` — resolution, collision, miss, stamping, and vocabulary-integrity tests. No network.

## Curation notes for the next review pass

- CAS selection takes the first CAS-shaped synonym PubChem lists; for LiTFSI that yielded 2043073-41-0 rather than the commonly cited 90076-65-6 (both registered). Decide whether to pin preferred CAS numbers in the seed as an optional column.
- 33 substances have no domain-chemical-substance class yet; the list (with full identifiers) is in docs/internal/ontology-additions-needed.md and is re-emitted by every generator run.

## Regenerating

    python tools/substances/build_vocab.py            # offline, from fixtures
    python tools/substances/build_vocab.py --refresh  # refetch PubChem into fixtures

The output records the seed's SHA-256 and the chemsub git version, so a vocabulary can always be traced to its exact inputs.
