# BattINFO Cell-Type Datasheet Standard (Draft v1.0)

## 1. Scope

This standard defines the **operational JSON contract** for battery cell-type datasheets in BattINFO.

- Layer 1 (this document): human-friendly JSON for authoring, review, sharing, and validation.
- Layer 2 (separate pipeline): deterministic conversion into RDF/JSON-LD using schema.org + EMMO domain-battery semantics.

The JSON schema is intentionally practical for battery R&D teams that do not work directly with RDF.

## 2. Design Objectives

- Professional and stable enough for cross-organization exchange.
- Easy to instantiate by humans and scripts.
- Strict enough for CI validation.
- Flexible enough for incomplete legacy datasheets.
- Semantically alignable to schema.org/EMMO without forcing JSON-LD authoring.

## 3. Canonical Schema

- Schema ID: `https://w3id.org/battinfo/schema/cell-type-datasheet.schema.json`
- Source file: `assets/schemas/cell-type-datasheet.schema.json`
- Packaged copy: `src/battinfo/data/schemas/cell-type-datasheet.schema.json`

Validation command:

```bash
battinfo validate assets/datasheets/cell-types/<id>.datasheet.json --profile cell-type-datasheet
```

## 4. Required Core Fields

Top-level required:

- `version`
- `product`
- `specs`
- `lineage`

`product` required:

- `type` (`Product`)
- `identifier` (canonical BattINFO cell-type IRI)
- `short_id`
- `name`
- `brand`
- `manufacturer`
- `model`
- `chemistry` (Li-ion, Na-ion, etc.)
- `positive_electrode_basis`
- `negative_electrode_basis`
- `format`
- `category`

`lineage` required:

- `source_record`
- `source_type`
- `source_file`
- `extracted_at`

## 5. Quantitative Specs

All quantitative values must be under `specs` using `SpecItem`:

- Numeric forms: `value`, `value_min`, `value_max`, `value_typical`
- Text fallback: `value_text`
- Required unit: `unit`
- Optional test context: `conditions` (`temperature_c`, `c_rate`, SOC window, notes)

This keeps the schema simple while preserving enough structure for later semantic lifting.

## 6. Capacity Semantics

- `nominal_capacity`: preferred nominal/typical published value.
- `rated_capacity`: guaranteed/rated value when explicitly provided.
- `min_capacity`: lower-bound spec when explicitly provided.

Do not collapse these into one field if the source distinguishes them.

## 7. Extensions Policy

Use `extensions` for local/vendor fields only.

- Extension keys must match `x-*` (example: `x-battinfo-ingest_batch`).
- Core interoperability fields must not be moved into extensions.

## 8. References and Provenance

- Put bibliographic/source links in `references`.
- Put ingest/provenance trace in `lineage`.
- Keep `lineage` immutable for reproducibility.

## 9. Conformance Levels

### Core (machine-valid)

- JSON validates against `cell-type-datasheet` profile.
- Uses canonical BattINFO cell-type IRI.
- Uses core `product` and `lineage` fields.

### Recommended (publication-ready)

- Includes at least one capacity and voltage spec.
- Includes `references` with URL/identifier/citation.
- Includes test conditions for sensitive specs (for example cycle life, current limits).
- No unresolved `unknown` values except where source truly lacks data.

## 10. Governance for v1.0

- Changes to required fields are breaking and require major schema version updates.
- New optional properties are non-breaking.
- Property renames require deprecation period plus migration script.
- JSON contract remains stable even as RDF mapping evolves.

## 11. Relationship to Semantic Layer

This standard is not JSON-LD.

It is deliberately shaped so a converter can map:

- `product.*` -> schema.org `Product` graph
- battery-domain fields (chemistry/electrode/specs) -> EMMO domain-battery terms

This separation keeps authoring simple while preserving semantic rigor downstream.

## 12. Batch Generation Workflow

Generate a review batch from CellInfo-derived `cells-clean` records:

```bash
python .tools/datasheets/generate_cell_type_datasheet_examples.py --count 10 --strategy diverse --target-dir .battinfo/datasheets/top10 --clean-target --batch-tag cellinfo-top10-diverse-v1
```

Key options:

- `--count`: number of resources to generate.
- `--strategy`: `diverse` (coverage-oriented) or `first` (sorted order).
- `--clean-target`: remove existing datasheet outputs before writing.
- `--dry-run`: preview selected source records without writing files.
- `--infer-negative-electrode-basis`: apply conservative rule-based inference for `product.negative_electrode_basis`.

Validate all generated datasheets:

```bash
python .tools/datasheets/validate_cell_type_datasheets.py --dir .battinfo/datasheets/top10 --profile cell-type-datasheet
```

Generated review artifacts:

- `.battinfo/datasheets/top10/CELLINFO_TOP10_REVIEW.md`
- `.battinfo/datasheets/top10/CELLINFO_TOP10_QA.md`

Quality gate command (CI-ready):

```bash
python .tools/datasheets/check_datasheet_quality.py --dir .battinfo/datasheets/top10 --report .battinfo/reports/cellinfo-top10-gate.md --max-empty-specs 0 --max-unknown-manufacturer 0 --max-unknown-chemistry 0 --max-unknown-positive-electrode-basis 0 --max-unknown-negative-electrode-basis -1 --required-spec nominal_capacity --required-spec nominal_voltage --min-required-spec-coverage 1.0
```

Notes:

- `--max-unknown-negative-electrode-basis -1` disables that gate for now.
- Set `--max-unknown-negative-electrode-basis 0` once negative electrode basis is fully curated.

CI smoke-gate pattern (recommended):

```bash
python .tools/datasheets/generate_cell_type_datasheet_examples.py --count 10 --strategy diverse --target-dir .battinfo/ci-smoke/cell-types --clean-target --batch-tag ci-smoke-v1 --infer-negative-electrode-basis
python .tools/datasheets/validate_cell_type_datasheets.py --dir .battinfo/ci-smoke/cell-types --profile cell-type-datasheet
python .tools/datasheets/check_datasheet_quality.py --dir .battinfo/ci-smoke/cell-types --report .battinfo/reports/ci-smoke-gate.md --max-empty-specs 0 --max-unknown-manufacturer 0 --max-unknown-chemistry 0 --max-unknown-positive-electrode-basis 0 --max-unknown-negative-electrode-basis 0 --required-spec nominal_capacity --required-spec nominal_voltage --min-required-spec-coverage 1.0
```

Curation backlog report:

```bash
python .tools/datasheets/report_datasheet_curation_backlog.py --dir .battinfo/datasheets/top10 --out .battinfo/reports/datasheet-curation-backlog.md --max-list 30
```

Baseline vs enriched delta report:

```bash
python .tools/datasheets/report_datasheet_delta.py --baseline-dir .battinfo/datasheets/pilot100 --enriched-dir .battinfo/datasheets/pilot100-enriched --out .battinfo/reports/pilot100-delta.md
```

