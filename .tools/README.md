# .tools

This directory contains maintainer-only repository tooling.

Layout:
- `build/` generated artifacts, schema/model generation, and resolver/library build helpers
- `datasheets/` datasheet generation, validation, quality gates, and curation reporting
- `library/` cell library normalization and validation utilities
- `quality/` policy, repo-quality checks, and alpha verification helpers used in CI
- `semantic/` semantic mapping and publication support utilities

These tools are not the primary user interface for BattINFO.

Supported user-facing workflows should live under:
- `src/battinfo/`
- the `battinfo` CLI
- documented Python API entry points

If a maintainer tool becomes part of the supported product workflow, move its logic into
`src/battinfo/` and expose it through the CLI or documented API instead of adding another
top-level entry point here.
