# D-data to BattINFO/BDF Pipeline (Draft)

## Purpose

Convert `<path-to-ddata-root>` battery metadata into:

- Canonical BattINFO records (`cell-type`, `cell-instance`, `dataset`)
- Deterministic BDF conversion job manifests

This is an ingestion bridge. It preserves source lineage and keeps BattINFO IDs/records as the registry layer.

## Sidecar Generation

If you want each contribution folder to carry BattINFO-aligned `battery.json` and `contribution.json` files, generate them from the same contracts:

```bash
python .tools/ingest/generate_ddata_sidecars.py \
  --data-root <path-to-ddata-root> \
  --out-root .battinfo/ingest/ddata-sidecars \
  --overwrite
```

Use `--in-place` to write directly into `<path-to-ddata-root>`.

## Command

```bash
python .tools/ingest/ingest_ddata_registry.py \
  --data-root <path-to-ddata-root> \
  --source-root .battinfo/ingest/ddata-registry \
  --report-out .battinfo/ingest/reports/ddata-ingest-report.json \
  --bdf-jobs-out .battinfo/ingest/reports/ddata-bdf-jobs.json \
  --dry-run
```

Remove `--dry-run` to emit canonical JSON records.

Use `--strict` if malformed JSON should fail the run.

## Outputs

- `.battinfo/ingest/ddata-registry/cell-types/*.json`
- `.battinfo/ingest/ddata-registry/cell-instances/*.json`
- `.battinfo/ingest/ddata-registry/datasets/*.json`
- `.battinfo/ingest/reports/ddata-ingest-report.json`
- `.battinfo/ingest/reports/ddata-bdf-jobs.json`

## Notes

- The script handles both newer and legacy `battery.json` variants.
- Malformed legacy files are skipped by default and listed in the report (`skipped_invalid`).
- Dataset-to-cell links are generated through registered cell instances.
- BDF conversion is represented as job metadata (source paths/globs + target path); the actual converter is the next integration step.

