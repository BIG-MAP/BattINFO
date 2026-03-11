# BattINFO Ingestion Pipeline (CellInfo + Local Datasheets)

This workflow supports two source lanes:

- CellInfo-derived structured JSON
- Local manufacturer PDF datasheets (for example `<path-to-datasheets>`)

The goal is deterministic ingest, explicit dedup decisions, and traceable curation.

## 1. Build Source Manifest

Build an immutable manifest containing checksum, source type, path, and filename hints.

```bash
python .tools/build/build_datasheet_source_manifest.py --cellinfo-dir src/battinfo/data/examples/cells-clean --pdf-dir <path-to-datasheets> --recursive --out .battinfo/ingest/manifests/datasheet-sources.manifest.json --summary-md .battinfo/ingest/manifests/datasheet-sources.summary.md
```

Notes:

- Duplicate files are detected by SHA-256 checksum and marked `status=duplicate`.
- Filenames like `LG__E101A__E72B__...pdf` are recognized as multi-cell candidates.

## 2. Convert Sources to Candidate Records

### 2.1 CellInfo JSON -> normalized candidates

```bash
python .tools/ingest/ingest_cellinfo_candidates.py --source-dir src/battinfo/data/examples/cells-clean --target-dir .battinfo/ingest/candidates/cellinfo --clean-target --validate --summary-md .battinfo/ingest/candidates/cellinfo/CELLINFO_CANDIDATES_SUMMARY.md
```

### 2.2 PDF manifest entries -> seeded candidates

This step creates one candidate per hinted model from each PDF source entry.

```bash
python .tools/ingest/seed_pdf_candidates_from_manifest.py --manifest .battinfo/ingest/manifests/datasheet-sources.manifest.json --target-dir .battinfo/ingest/candidates/pdf-seeded --clean-target
```

Notes:

- Seeded PDF candidates are intentionally incomplete.
- They are placeholders to attach parser/OCR outputs and manual curation later.

## 3. Match Candidates Against Existing Library

Run deterministic matching against current BattINFO datasheets:

```bash
python .tools/ingest/report_candidate_matches.py --candidate-dir .battinfo/ingest/candidates/cellinfo --existing-dir assets/datasheets/cell-types --out .battinfo/ingest/reports/cellinfo-match-report.md --json-out .battinfo/ingest/reports/cellinfo-match-report.json
```

Decisions produced:

- `match_existing`
- `new_cell_type`
- `ambiguous_match`
- `conflict_manual_review`

## 4. Curation and Publication

- Review `ambiguous_match` and `conflict_manual_review` first.
- Promote only curated records into canonical published datasheets.
- Keep source manifest and candidate outputs as immutable ingestion evidence.

## 5. Recommended Production Layout

- `.battinfo/ingest/manifests/` source snapshots
- `.battinfo/ingest/candidates/cellinfo/` normalized candidates from CellInfo
- `.battinfo/ingest/candidates/pdf-seeded/` initial PDF candidate stubs
- `.battinfo/ingest/reports/` dedup/conflict triage reports
- `assets/datasheets/cell-types/` canonical published datasheet library


