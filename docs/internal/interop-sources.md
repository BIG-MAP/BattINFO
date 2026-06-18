# Interoperability Sources

BattINFO imports external battery-metadata sources into the canonical
spec + instance record model. This is the index of supported sources, their
coverage, and the test-fixture policy. (For the BattINFO Converter seam
specifically, see [converter-compatibility.md](converter-compatibility.md).)

## Importer matrix

| Source | Entry point | Produces | Fixtures |
|--------|-------------|----------|----------|
| **BattINFO Converter** JSON-LD | `import_converter_jsonld[_record]`, `import_converter_package`, `batch_import_converter_directory` | cell-spec → instance, test-spec, test, dataset | `tests/fixtures/converter/*` (v1.1.x RO-Crate, v3.x, legacy shapes) |
| **Solid-state DB** (tabular CSV) | `batch_import_solid_state_db`, `from_solid_state_db_row` | material-spec ×N → cell-spec → instance → test | `tests/fixtures/interop/solid-state-db/*` |
| **BPX** (Battery Parameter eXchange) | `from_bpx` / `to_bpx` / `save_bpx` | cell-spec ⇄ BPX | `examples/cell-spec/A123__ANR26650M1-B.json` |
| **battdat / BDF** (timeseries CSV) | `from_battdat` | test + dataset | synthetic in `test_ingest.py` |
| **Cycler protocols** | `import_aurora_unicycler`, `import_pybamm_experiment`, `import_bmgen_jsonld` | test-spec (structured method) | inline in `test_protocol_importers.py` |

## Solid-state database (tabular metadata)

`battinfo.interop.solid_state_db` is the package's first **generic tabular
metadata** importer (distinct from `from_battdat`, which reads *timeseries*
CSV). It maps a wide, prefix-coded sheet — one row per published cell — into a
full record chain:

```python
from battinfo import batch_import_solid_state_db
results = batch_import_solid_state_db("DB Master Sheet - 245 Entries.csv")
for r in results:
    r.cell_spec, r.cell_instance, r.test, r.material_specs   # one chain per row
```

Notable properties:

- **Solid-state coverage.** First importer to exercise garnet / argyrodite /
  perovskite / polymer electrolytes, Li-metal & LTO anodes, and sulfur / NMC /
  LFP cathodes — chemistries the canonical example corpus does not contain.
- **Column families** mapped: `AAM_*` (anode active), `A_SE_*`/`S_*`/`C_SE_*`
  (solid electrolyte, by layer), `CAM_*`/`C_*` (cathode), `FC_*`/`MC_*`
  (fabrication/measurement conditions), `CLC_*` (constant-current cycle life).
- **Missing-value sentinels** `NR` / `NA` / `None_S` are treated as absent.
- **Deterministic IRIs** are minted from each row's DOI + sheet ID, so import is
  idempotent. These are *staging* identifiers, not published registry entries —
  a curator re-mints canonical `w3id.org` IRIs at publish time.
- **Encoding** is auto-detected (utf-8 / utf-8-sig / cp1252); the real master
  sheet is cp1252.

## Fixture policy (consolidated sources)

Interop fixtures live under `tests/fixtures/interop/<source>/` and follow one
rule: **trimmed, representative, version-pinned samples — never the full
upstream datasets.** Each source directory carries a `PROVENANCE.md` recording
the origin, version, encoding, license/attribution, and how to regenerate the
trim. Full workbooks/CSVs stay out of the repo (size + third-party licensing);
the importers accept a path so the full files can be run locally.

This keeps interop tests hermetic and deterministic without repo bloat. New
sources (e.g. Battery Data Commons, the DIGIBAT Discovery `.eln`, a converter
version matrix) should be added the same way.
