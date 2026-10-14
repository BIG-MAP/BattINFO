# Examples

Canonical example records for the BattINFO data model. This folder is the
**single source of truth** for example fixtures.

This folder is part of the supported repository surface. Use it for canonical
fixtures and examples that are meant to be validated, queried, published, or
referenced from tests and docs.

> A read-only copy of this folder is generated into
> `src/battinfo/data/examples/` so the records ship inside the installed wheel.
> **Never edit that copy** — edit the files here and run
> `python scripts/sync_examples.py` to regenerate it.

Key folders:
- `cell-spec/` Cell spec records. `A123__ANR26650M1-B.json` is a commercial cell with values from A123's datasheet. The others are illustrative cells from "Example Lab": full and half coin cells, a three-electrode pouch cell and a prismatic cell. `cell-spec/research/` holds material-grade descriptor examples with electrode/electrolyte/separator detail.
- `cell-instance/` Physical cell instance records linked to a cell spec.
- `test/` Test activity records — one per canonical test kind (cycling, rate_capability, formation, HPPC, ICI, GITT, DCIR, EIS).
- `test-protocol/` Reusable test protocol records referenced by tests.
- `dataset/` Dataset records linked to cells and tests.
- `organization/` Organisation records for labs and manufacturers.
- `profiles/` Compliance/profile fixtures (e.g. Battery Passport minimal).
