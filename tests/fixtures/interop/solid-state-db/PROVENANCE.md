# Fixture: solid-state-battery literature database (trimmed sample)

`db-master-sample.csv` is a **trimmed, version-pinned sample** of the
solid-state-battery "DB Master Sheet" — a wide CSV with one row per cell
reported in a published paper.

## Source

- **Original file:** `DB Master Sheet - 245 Entries.csv` (245 data rows, 189
  columns), held at the `battery-genome` repository root, outside this package.
- **Encoding (original):** cp1252 (degree signs in comment columns). This
  sample is re-encoded as UTF-8 for hermetic tests; the importer
  (`battinfo.interop.solid_state_db`) auto-detects utf-8 / utf-8-sig / cp1252.
- **Nature:** a literature meta-analysis — values are extracted from third-party
  publications (each row carries `DOI`, `Journal_Name`, `Lead_Author`). The
  underlying measurements belong to their respective publishers; this sample is
  retained only for interoperability testing, not redistribution of the dataset.

## What was kept

The **full column schema** (all 189 prefix-coded columns: `AAM_*`, `A_SE_*`,
`S_*`, `CAM_*`/`C_*`, `FC_*`/`MC_*`, `CLC_*`, `R1..R8_*`) plus **6 data rows**
chosen for diversity, by original sheet `ID`:

| ID  | cathode | electrolyte (separator) | anode | casing |
|-----|---------|-------------------------|-------|--------|
| 1   | Sulfur  | PEO-based polymer       | Li metal | Pouch |
| 2   | NMC811  | LLZO garnet (tetragonal)| Li metal | Coin  |
| 3   | NMC811  | LLZO garnet (coated)    | Li metal | Coin  |
| 50  | NMC811  | Li6PS5Cl argyrodite     | LTO      | Other |
| 120 | NMC811  | LLZO garnet (cubic)     | Li metal | Coin  |
| 200 | LiFePO4 | LLZO garnet (cubic)     | Li metal | Pouch |

This spans garnet / argyrodite / polymer electrolytes, Li-metal and LTO anodes,
sulfur / NMC / LFP cathodes, and coin / pouch / other formats — the solid-state
chemistry space the canonical example corpus does not cover.

## Regenerating

```python
import csv
src = r"DB Master Sheet - 245 Entries.csv"   # repo root
with open(src, encoding="cp1252", newline="") as fh:
    rows = list(csv.reader(fh))
keep = [rows[0]] + [rows[i] for i in (1, 2, 3, 50, 120, 200)]
with open("db-master-sample.csv", "w", encoding="utf-8", newline="") as fh:
    csv.writer(fh).writerows(keep)
```

The importer mints **deterministic** IRIs from each row's DOI + sheet ID, so
re-running the import is idempotent and these row choices map to stable records.
