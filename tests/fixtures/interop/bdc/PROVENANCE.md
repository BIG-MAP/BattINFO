# Fixture: Battery Data Commons (trimmed canonical records)

`canonical/datasets/bdc_*.json` are **real canonical records** copied verbatim
from Battery Data Commons, driving `tests/test_bdc_interop.py`.

## Source

- **Repository:** https://github.com/BatteryCommons/BatteryDataCommons
- **Path:** `canonical/datasets/` (394 active canonical records at the time of
  copy).
- **Pinned commit:** `cb6dbe2` ("chore: automated workflow update [2026-06-14]").
- BDC records are curated metadata about third-party public datasets; these
  copies are retained for interoperability testing only.

## What was kept

8 records chosen to span the case → cell-format mapping and the skip path:

| File | case | format | measurements |
|------|------|--------|--------------|
| `bdc_000001` | CoinCase | coin | discharge_capacity, eis |
| `bdc_000005` | R18650 | cylindrical | discharge_capacity |
| `bdc_000018` | R21700 | cylindrical | discharge_capacity, pseudo_ocv |
| `bdc_000004` | PouchCase | pouch | discharge_capacity |
| `bdc_000002` | PrismaticCase | prismatic | discharge_capacity |
| `bdc_000014` | Unknown | unknown | discharge_capacity, internal_resistance, pseudo_ocv |
| `bdc_000007` | R18650 | cylindrical | discharge_capacity, internal_resistance, pseudo_ocv |
| `bdc_sw_001` | — | — (software tool; **skipped** on import) |

Together they exercise all five cell formats and all four
`available_measurements` → test-kind mappings, plus the software-record skip.

## Regenerating

Pull the BDC repo and copy the records above from `canonical/datasets/` into
`tests/fixtures/interop/bdc/canonical/datasets/`. The importer mints
deterministic IRIs from each record's `id`, so the choice of records maps to
stable BattINFO identifiers.
