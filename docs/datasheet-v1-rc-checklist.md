# BattINFO Cell-Type Datasheet v1.0 RC Checklist

This checklist is the go/no-go gate for promoting the draft datasheet contract to a stable v1.0 first release candidate.

## 1. Contract Freeze

- [ ] Confirm schema scope for v1.0:
  - `product` block (core identity + chemistry + form factor)
  - `specs` block (all quantitative values)
  - `lineage` block (source traceability)
  - optional `quality`, `references`, `notes`, `extensions`
- [ ] No breaking renames or removals after RC freeze.
- [ ] Any non-critical new fields deferred to v1.1 backlog.

## 2. Validation + CI Enforcement

- [x] JSON schema exists at `assets/schemas/cell-type-datasheet.schema.json`.
- [x] Packaged schema copy exists at `src/battinfo/data/schemas/cell-type-datasheet.schema.json`.
- [x] Validation profile wired (`cell-type-datasheet`).
- [x] CI generates deterministic datasheet smoke batch:
  - `python .tools/datasheets/generate_cell_type_datasheet_examples.py --count 10 --strategy diverse --target-dir .battinfo/ci-smoke/cell-types --clean-target --batch-tag ci-smoke-v1 --infer-negative-electrode-basis`
- [x] CI runs schema validation:
  - `python .tools/datasheets/validate_cell_type_datasheets.py --dir .battinfo/ci-smoke/cell-types --profile cell-type-datasheet`
- [x] CI runs quality gates:
  - `python .tools/datasheets/check_datasheet_quality.py --dir .battinfo/ci-smoke/cell-types ...`
- [x] CI enforces strict unknown-negative gate for smoke batch (`unknown_negative_electrode_basis == 0`).

## 3. Data Quality Targets (v1.0 Minimum)

- [x] 0 schema-invalid datasheets in canonical batch.
- [x] 0 empty `specs` blocks in canonical batch.
- [x] 0 unknown `manufacturer` in canonical batch.
- [x] 0 unknown `chemistry` in canonical batch.
- [x] 0 unknown `positive_electrode_basis` in canonical batch.
- [x] 100% coverage for `specs.nominal_capacity`.
- [x] 100% coverage for `specs.nominal_voltage`.
- [ ] Unknown `negative_electrode_basis` reduced to zero for canonical repository batch (outside CI smoke batch).

## 4. Identifier + Provenance Discipline

- [x] Product identifiers are canonical BattINFO cell-type IRIs.
- [x] `short_id` is present and non-canonical (usability only).
- [x] No serial numbers used in BattINFO canonical identifiers.
- [x] Lineage fields retained for reproducibility:
  - `source_record`, `source_type`, `source_file`, `extracted_at`
- [ ] Add checksum coverage policy for source files (`lineage.source_checksum`) where feasible.

## 5. Authoring + Adoption UX

- [x] Draft standard documented in `docs/datasheet-standard.md`.
- [x] Example generation script supports repeatable batch builds.
- [x] Review + QA markdown artifacts generated for human curation.
- [x] Notebook and CLI examples available for query/create/publish pathways.
- [ ] Publish a compact "getting started datasheet author guide" (single-page, copy-paste template).

## 6. Semantic Pipeline Readiness (JSON -> RDF)

- [ ] Implement deterministic exporter from datasheet JSON to RDF (schema.org + EMMO mapping rules).
- [ ] Add automated tests for exporter output shape and key triples.
- [ ] Document mapping table from JSON keys to semantic predicates.
- [ ] Define policy for unknown values in semantic export.

## 7. Release Artifacts for v1.0 RC

- [ ] Tag schema version and changelog entry for RC cut.
- [ ] Lock CI gates at current thresholds for RC branch.
- [ ] Provide at least:
  - one canonical 10-example reviewed batch
  - one 100-example pilot batch with QA/backlog report
  - one baseline-vs-enriched delta report
- [ ] Publish migration notes for any pre-v1 datasheet files.

## 8. Decision Record

Promote to v1.0 RC only when sections 1-4 are fully complete and section 6 has an agreed implementation timeline.

