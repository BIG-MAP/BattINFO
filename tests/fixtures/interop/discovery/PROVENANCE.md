# Fixture: DIGIBAT Discovery-Benchmark (trimmed samples)

Two trimmed samples of the DIGIBAT Discovery-Benchmark coin-cell dataset, one per
import path of `battinfo.interop.discovery`. Both describe the *same* benchmark
cells in different shapes.

## Sources (full datasets held outside this package)

- **`ro-crate-metadata.sample.json`** — a trimmed BattINFO-annotated RO-Crate.
  Original: `discovery-benchmark-battinfo.eln/Discovery-Benchmark/ro-crate-metadata.json`
  (~2.4 MB, 259 cells + ~5400 file entities + characterization). The sample keeps
  the `@context`, the root metadata nodes, and a **connected subgraph** of 5 cells
  (one per cathode chemistry: NMC811, NMC622, LFP, LCO, LMFP) with their shared
  electrode / electrolyte / active-material nodes. Per-cell `hasPart` lists are
  pruned to just the cycling `.xlsx` reference; the large binary files (cycling
  `.xlsx`/`.parquet`, SEM/TEM/XRD/XPS) are **not** included.
- **`discovery-benchmark.sample.xlsx`** — a trimmed copy of the flat workbook.
  Original: `Discovery-benchmark.xlsx` ("Automated cells" sheet, 259 rows × 34
  cols) at the battery-genome root. The sample keeps the full header row and the
  first row of each of the 5 cathode chemistries.

The benchmark is third-party research data (DIGIBAT); these trims are retained for
interoperability testing only, not redistribution of the dataset.

## What the importer needs

- The `.eln` reader uses only `ro-crate-metadata.json` (single file). It resolves
  `hasPositiveElectrode` / `hasNegativeElectrode` / `hasElectrolyte`, each
  electrode's `hasActiveMaterial`, EMMO quantity properties (`MassLoading`,
  `MassFraction`, electrolyte `Volume`), and the cycling `.xlsx` in `hasPart`.
- The `.xlsx` reader uses openpyxl on the "Automated cells" sheet.

## Regenerating

The `.eln` sample is a connected-subgraph extraction (pick the first cell of each
cathode chemistry; keep its referenced electrode / electrolyte / active-material
nodes; prune `hasPart` to the `.xlsx`). The `.xlsx` sample is the header plus the
first row of each chemistry. Identifiers are minted deterministically from each
entity's Discovery refcode / item id, so shared electrodes/electrolytes dedupe and
re-import is idempotent (modulo the provenance retrieval timestamp).
