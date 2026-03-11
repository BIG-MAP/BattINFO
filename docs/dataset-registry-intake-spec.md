# BattINFO Dataset Registry Intake Spec (v1 Draft)

## 1. Scope

This document defines a normalized spreadsheet contract for dataset metadata intake, and a deterministic mapping into BattINFO canonical dataset records.

This is an intake contract, not the canonical storage format.

- Intake format: Excel worksheet (`DatasetRegistry` tab)
- Canonical format: BattINFO JSON (`dataset.schema.json` + registry extension)

## 2. Decision

Yes, the source workbook should be changed.

Reason:

- Current workbook is excellent for curation but not robust for deterministic ingestion at scale.
- It contains merged headers, sheet-specific column variants, sentinel values (`Unknown`, `N/A`, `#REF!`), and inconsistent typing.
- A normalized tab materially reduces ingestion complexity, conflict rate, and maintenance cost.

## 3. Workbook Structure (recommended)

Use one workbook with these tabs:

- `DatasetRegistry`: one row per dataset record (machine-ingestable)
- `Vocab`: controlled vocab values used by dropdown validation
- `README`: human instructions and examples
- `Changelog`: row-level curation changes (optional but recommended)
- Existing thematic tabs: keep as legacy curation view until migration completes

## 4. Row Model

Each row in `DatasetRegistry` represents one dataset resource.

If one publication exposes multiple independent dataset resources, create one row per resource and connect them by `collection_group`.

## 5. Required Columns (core)

The following columns are required for every row.

| Column | Type | Example | Notes |
|---|---|---|---|
| `source_dataset_key` | string | `bdc-2026-000123` | Stable intake key, unique in workbook |
| `kind` | enum | `PerformanceData` | Controlled vocab |
| `title` | string | `CALCE 18650 aging cycles` | Human title |
| `dataset_url` | uri | `https://doi.org/10.5281/zenodo.3633834` | Primary landing URL |
| `owner` | string | `University of Maryland` | Data owner or publisher |
| `license_id` | enum/string | `CC-BY-4.0` | Prefer SPDX-like ID |
| `year` | integer | `2020` | 4-digit year |
| `battery_scale` | enum | `BatteryCell` | Controlled vocab |
| `manufacturer` | string | `A123` | Use `unknown` only if truly unavailable |
| `format` | enum | `R18650` | Controlled vocab; cell form factor |
| `data_modality` | enum | `TimeSeriesDataSet` | Controlled vocab |
| `ingest_status` | enum | `ready` | `ready|needs_review|blocked` |

## 6. Optional Columns (standard)

| Column | Type | Example | Notes |
|---|---|---|---|
| `dataset_doi` | string | `10.5281/zenodo.3633834` | Normalized DOI token |
| `download_url` | uri | `https://zenodo.org/api/records/...` | Direct archive link |
| `article_url` | uri | `https://doi.org/10.1038/...` | Primary article link |
| `article_doi` | string | `10.1038/...` | Normalized DOI token |
| `citation_data_key` | string | `zhang_2020` | Bib key |
| `citation_article_key` | string | `zhang2020identifying` | Bib key |
| `description` | string | `Cycling + EIS...` | Free text summary |
| `feature_of_interest` | string | `20,000 EIS spectra` | Sheet-specific in legacy workbook |
| `processing_code_available` | enum | `yes` | `yes|no|unknown` |
| `processing_code_language` | enum/string | `Python` | Controlled list + `other` |
| `cycler_raw_files_available` | enum | `yes` | `yes|no|not_applicable|unknown` |
| `repository_self_explanatory` | enum | `no` | `yes|no|unknown` |
| `anomaly_mentioned` | enum | `no` | `yes|no|unknown` |
| `sampling_text` | string | `1 s` | Preserve raw text |
| `duration_text` | string | `55 days` | Preserve raw text |
| `size_text` | string | `119 MB` | Preserve raw text |
| `model_name` | string | `ANR26650M1-B` | Canonical model label |
| `iec_battery_code` | string | `ICR2032` | Optional |
| `positive_electrode_basis` | enum/string | `LFP` | Controlled + `other` |
| `negative_electrode_basis` | enum/string | `Graphite` | Controlled + `other` |
| `chemistry` | enum | `Li-ion` | Family, not electrode material |
| `rated_capacity_value` | number | `2.5` | Numeric only |
| `rated_capacity_unit` | enum | `Ah` | Controlled |
| `cell_count` | integer | `12` | Number of specimens |
| `temperature_text` | string | `25, 35, 45` | Raw test temperatures |
| `current_text` | string | `1C charge, 2C discharge` | Raw profile |
| `source_sheet` | string | `Performance data` | Source lineage |
| `source_row` | integer | `47` | Source lineage |
| `source_workbook` | string | `BatteryDataCommons (3).xlsx` | Source lineage |
| `source_workbook_sha256` | string | `...` | Source lineage |
| `notes` | string | `link resolved manually` | Curation notes |

## 7. Controlled Vocabulary (minimum)

Use data validation dropdowns in Excel for these fields.

### 7.1 `kind`

- `PerformanceData`
- `DurabilityData`
- `FieldData`
- `ModelingData`
- `SafetyData`
- `OtherData`

### 7.2 `battery_scale`

- `BatteryCell`
- `BatteryModule`
- `BatteryPack`
- `Grid`
- `Electrode`
- `Multiple`
- `unknown`

### 7.3 `data_modality`

- `TimeSeriesDataSet`
- `TabularDataSet`
- `ImageDataSet`
- `VideoDataSet`
- `SimulationDataSet`
- `ModelParameterSet`
- `MixedDataSet`
- `unknown`

### 7.4 Tri-state and yes/no fields

For `processing_code_available`, `repository_self_explanatory`, `anomaly_mentioned`:

- `yes`
- `no`
- `unknown`

For `cycler_raw_files_available`:

- `yes`
- `no`
- `not_applicable`
- `unknown`

### 7.5 Null policy

Use empty cell for null. Do not use `N/A`, `Unknown`, `Not available`, `#REF!`.

If "unknown" is semantically meaningful, use explicit enum value `unknown`.

## 8. Data Quality Rules

Hard validation rules:

- `source_dataset_key` unique and non-empty.
- `dataset_url` must be valid URI.
- `year` must be integer between 1900 and current year + 1.
- `kind`, `battery_scale`, `data_modality`, status fields must match allowed enums.
- If `rated_capacity_value` is present, `rated_capacity_unit` is required.
- If `dataset_doi` is present, normalize to bare DOI string (no resolver prefix).

Soft validation rules:

- Flag duplicate `dataset_url` for dedup review.
- Flag missing `license_id`.
- Flag `manufacturer=unknown` and missing `model_name`.
- Flag multi-value free-text fields for parsing review.

## 9. Mapping from Current Workbook

Map all source sheets into the normalized `DatasetRegistry` columns.

### 9.1 Common mapping rules

| New column | Source column(s) |
|---|---|
| `kind` | `Kind of Data` (or sheet default) |
| `dataset_url` | `Link for dataset` |
| `download_url` | `Link for downloading full dataset (empty cells to be filled)` or `Link for downloading data (empty cells to be filled)` |
| `article_url` | `Link for article` |
| `citation_data_key` | `Bib citation for data` |
| `citation_article_key` | `Bib citation for article` |
| `owner` | `Owner` |
| `license_id` | `License` (normalized) |
| `year` | `Year` |
| `data_modality` | `Data modality` |
| `manufacturer` | `Battery Manufacturer` |
| `iec_battery_code` | `IEC Battery Code` |
| `positive_electrode_basis` | `PositiveElectrode` |
| `negative_electrode_basis` | `NegativeElectrode` |
| `feature_of_interest` | `Feature of interest` |
| `processing_code_available` | `Data processing code available` |
| `processing_code_language` | `Language of the data processing code` |
| `repository_self_explanatory` | `Repository is self explanatory` |
| `anomaly_mentioned` | `Anomaly mentionned` |
| `sampling_text` | `Sampling` |
| `size_text` | `Size` |

### 9.2 Scale/model/format field harmonization

| New column | Performance | Durability | Field | Modeling | Safety |
|---|---|---|---|---|---|
| `battery_scale` | `Cell/Module/Pack` | `Cell/Module/Pack` | `Battery Scale (Cell/Module/Pack)` | inferred from scope row, else null | `Cell/Module/Pack` |
| `model_name` | `Model/Battery type (Link to the other website https://battdat.org/celldatarepo)` | `Battery Type / Model` | `Model/Battery type (Link to the other website https://battdat.org/celldatarepo)` | `Battery Type / Model` | `Battery Type / Model` |
| `format` | `Format` | `Form` | derive from model/form factor text | `Format` | `Format` |
| `rated_capacity_value` | `Capacity (Ah)` | `Capacity` | `Capacity (Ah)` | `Capacity` | `Capacity` |
| `cell_count` | `Number` | `Number` | null | `Number` | `Number` |

### 9.3 Sheet-level default values

If `kind` is missing, set from source sheet:

- `Performance data` -> `PerformanceData`
- `Durability data` -> `DurabilityData`
- `Field data` -> `FieldData`
- `Modeling data` -> `ModelingData`
- `Safety data` -> `SafetyData`

## 10. Canonical BattINFO Record Emission

Each normalized row should emit one BattINFO dataset record with:

- canonical opaque IRI `https://w3id.org/battinfo/dataset/{uid}`
- normalized metadata fields in `dataset`
- lineage and curation fields in `provenance`
- optional quality flags in `notes` or `quality`

Do not encode semantics in the UID.

## 11. Migration Plan

1. Freeze current workbook snapshot with checksum.
2. Create new `DatasetRegistry` tab and `Vocab` tab.
3. Auto-fill `DatasetRegistry` from current sheets via migration script.
4. Run validation and produce conflict report.
5. Curate conflicts, set `ingest_status=ready`.
6. Export rows to canonical BattINFO JSON and register in batch.

## 12. Practical Adoption Notes

- Keep curator-friendly thematic tabs if needed, but ingestion reads only `DatasetRegistry`.
- Treat spreadsheet as UI, not source of truth.
- Treat canonical JSON registry as source of truth.

