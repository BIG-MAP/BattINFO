# Battery Data Commons alignment

The strategic goal is **native BattINFO integration into Battery Data Commons
(BDC)** — for BattINFO to be a first-class format the commons can read and write.
This document records the data-model alignment and the tested seam that is the
first step toward it.

- BDC: https://github.com/BatteryCommons/BatteryDataCommons — a curated registry
  of public battery datasets. Each `canonical/datasets/bdc_NNNNNN.json` record
  catalogues a dataset and describes the cell it measured, already using
  EMMO-flavoured terms (`CoinCase`, `BatteryCell`, `LithiumIronPhosphate`, …).
- BattINFO side: `battinfo.interop.battery_data_commons`
  (`import_bdc_record` / `batch_import_bdc`, `to_bdc_record`).

## What a BDC record is

A BDC record is fundamentally a **dataset catalogue entry** with an embedded
**cell descriptor**. That shape maps cleanly onto BattINFO's dataset + cell-spec
model, which is why the two are a good integration target.

## Field mapping

| BDC field | BattINFO target | Notes |
|-----------|-----------------|-------|
| `id` | dataset / cell-spec / instance UID seed | deterministic, idempotent import |
| `title` / `overview.feature` / `comment` | `dataset.name` | first non-empty |
| `source_metadata.purpose` | `dataset.description` | |
| `source_urls` | `dataset.access_url`, `dataset.same_as` | |
| `download_urls` | `dataset.distributions[].content_url` | MIME inferred from suffix |
| `license{.url}` / `license_url` | `dataset.license` | |
| `categories` | `dataset.keywords` | `software` → record skipped (no cell) |
| `publications[].url` / `source_urls` | `provenance.citation` | DOI preferred |
| `overview.case` | `cell_spec.cell_format` (+ `size_code`) | `CoinCase`→coin, `PouchCase`→pouch, `PrismaticCase`→prismatic, `R18650`/`R21700`→cylindrical (case becomes the size code), `Unknown`→unknown, `Multiple`/`Synthetic cycles`→other |
| `overview.manufacturer` | `cell_spec.manufacturer` | |
| `overview.battery_model` | `cell_spec.model` | |
| `overview.iec_battery_code` | `cell_spec.iec_code` | |
| `electrodes.positive` / `.negative` | `cell_spec.positive/negative_electrode_basis` + a `material_spec` each | EMMO class names kept as `material_spec.emmo_type`; `Unknown`/`Multiple` dropped |
| `reported_values.rated_capacity_Ah` | `cell_spec.properties.nominal_capacity` (Ah) | |
| `available_measurements.*` | one `test` each + `dataset.measurement_techniques` | `discharge_capacity`→capacity_check, `eis`→eis, `internal_resistance`→dcir, `pseudo_ocv`→quasi_ocv |
| `source_metadata.data_modality` / `.owner` | `cell_spec.notes` | no structured home yet |

One BDC record therefore imports to: *N* deduplicated electrode `material_spec`s,
one `cell_spec` → `cell_instance`, one `test` per reported measurement, and one
`dataset` that ties them together.

## Round-trip (export)

`to_bdc_record(cell_spec, dataset=…)` renders a BattINFO cell-spec back into the
BDC canonical shape (`overview`, `electrodes`, `reported_values`, `source_urls`,
`download_urls`, `license`, `provenance`), so a BattINFO-authored cell can be
contributed to the commons. The case vocabulary (`CoinCase`/`PouchCase`/
`PrismaticCase`/`R18650`) round-trips; `cylindrical` without a size code exports
as the R-code when present.

## Gaps / not yet aligned

- **Software-tool records** (`categories: [software]`) have no cell and are
  skipped on import; BattINFO has no tool/software record type yet.
- **Category detail blocks** (`performance_details`, `durability`, `field_data`,
  `modeling`) are not yet mapped — only the common cell descriptor is.
- **`Multiple` / `Unknown`** electrodes and cases are imported as `other` /
  `unknown` with no material-spec; a multi-cell dataset is represented as a
  single descriptor.
- Export currently emits the `performance` category and a `TimeSeriesDataSet`
  modality by default; richer category/modality inference is future work.

## Toward native integration

The natural next steps (post-publish) are: (1) a BDC **submission adapter** that
emits `to_bdc_record` output in the BDC candidate-staging shape
(`staging/candidates/`), so BattINFO records can be opened as BDC contributions;
and (2) agreeing the EMMO term set BDC already uses (`CoinCase`,
`LithiumIronPhosphate`, …) against BattINFO's allowlist so the two share one
vocabulary rather than mapping between two.
