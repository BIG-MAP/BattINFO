# Interoperability Sources

BattINFO imports external battery-metadata sources into the canonical
spec + instance record model. This is the index of supported sources, their
coverage, and the test-fixture policy. (For the BattINFO Converter seam
specifically, see [converter-compatibility.md](converter-compatibility.md).)

## Importer matrix

| Source | Entry point | Produces | Fixtures |
|--------|-------------|----------|----------|
| **BattINFO Converter** JSON-LD | `import_converter_jsonld[_record]`, `import_converter_package`, `batch_import_converter_directory` | cell-spec → instance, test-spec, test, dataset | `tests/fixtures/converter/*` (RO-Crate / BatteryTest shapes); `tests/fixtures/interop/converter-versions/*` (real tool outputs v1.0.0–v1.1.17) |
| **Solid-state DB** (tabular CSV) | `batch_import_solid_state_db`, `from_solid_state_db_row` | material-spec ×N → cell-spec → instance → test | `tests/fixtures/interop/solid-state-db/*` |
| **Discovery-Benchmark** (`.eln` RO-Crate) | `import_discovery_eln` | material-spec → electrode-spec → cell-spec → instance → test → dataset (+ electrolyte-spec) | `tests/fixtures/interop/discovery/ro-crate-metadata.sample.json` |
| **Discovery-Benchmark** (`.xlsx`) | `import_discovery_xlsx` | material-spec + electrolyte-spec + cell-spec → instance → test | `tests/fixtures/interop/discovery/discovery-benchmark.sample.xlsx` |
| **Battery Data Commons** (registry JSON) | `batch_import_bdc` / `import_bdc_record`; `to_bdc_record` (export) | dataset + cell-spec → instance + material-spec ×N + test per measurement | `tests/fixtures/interop/bdc/canonical/datasets/*` |
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
sources should be added the same way.

### Battery Data Commons (two-way seam)

`battinfo.interop.battery_data_commons` is a **two-way** seam with the BDC dataset
registry — the first step toward native BattINFO integration into BDC. See the
field mapping and integration plan in
[battery-data-commons.md](battery-data-commons.md). `import_bdc_record` maps a BDC
canonical record into a dataset + cell-spec → instance + electrode material-specs
+ a test per reported measurement; `to_bdc_record` exports a BattINFO cell back to
the BDC shape. Software-tool records are skipped (no cell).

### Discovery-Benchmark (two shapes, one dataset)

The DIGIBAT Discovery-Benchmark ships as both a BattINFO-annotated RO-Crate
(`.eln`) and a flat workbook (`.xlsx`) describing the same ~259 coin cells.
`battinfo.interop.discovery` offers an entry point for each:

- `import_discovery_eln(path)` — the rich path. 259 cells share 13 characterized
  electrodes and 9 electrolytes, so it mints **deduplicated** material-specs,
  electrode-specs and electrolyte-specs and wires each cell-spec to them by IRI,
  plus a cycling test and a dataset per cell.
- `import_discovery_xlsx(path)` — the flat path. One row per cell → material-spec
  + electrolyte-spec + cell-spec → instance → test (no electrode-specs; the sheet
  has no separable electrode entities).

Both return a `DiscoveryImportPackage` and mint identifiers deterministically from
each entity's Discovery refcode / item id, so re-import is idempotent (modulo the
provenance retrieval timestamp) and a shared entity (e.g. an electrolyte named
identically in both shapes) maps to the **same** IRI across the two importers.

### Converter version matrix

`tests/fixtures/interop/converter-versions/` pins **real** `convert_excel_to_jsonld`
outputs for a spread of the BattInfoConverter tool's filled templates
(v1.0.0 … v1.1.17), regenerated by `scripts/generate_converter_version_fixtures.py`.
This covers the tool's structural drift — the cell-component holder switched from
`hasConstituent` (≤ v1.1.11) to `hasComponent` (≥ v1.1.15); both must import.
Fixtures are committed JSON-LD, so the test carries no converter dependency.
