# BattINFO

BattINFO is the implementation and interoperability layer for the
domain-battery ontology. It provides canonical JSON schemas, mappings,
examples, and tooling so data engineers and lab scientists can create,
validate, and transform battery metadata without touching RDF directly.

Status: Pilot-quality baseline.
- Core query/create/publish/index workflows are implemented and tested.
- Interfaces may evolve during pilot trials based on real workflow feedback.

Core principles
- Domain-battery remains the normative ontology (semantics and terms).
- BattINFO is non-normative and operational (schemas, mappings, tooling).
- Canonical contract is JSON Schema; Pydantic models are generated for the CLI.
- Battery Pass JSON-LD outputs are supported and pinned per release.

What BattINFO does
- Validate battery metadata as plain JSON (JSON Schema / Pydantic).
- Map JSON inputs into domain-battery aligned JSON-LD.
- Produce Battery Pass JSON-LD (pinned to v1.2.0).
- Provide profiles, examples, and mapping rules for common workflows.
- Enforce persistent, opaque BattINFO identifiers under `https://w3id.org/battinfo/`.

Quick start
```
battinfo validate input.json --profile base
battinfo validate input.json --profile batterypass
battinfo map input.json --target domain-battery --out output.domain.jsonld
battinfo map input.json --target batterypass --out output.jsonld
battinfo query cell-types --manufacturer A123 --chemistry LFP --format json
battinfo create cell-instance --model-name ANR26650M1-B --manufacturer A123 --format json
battinfo publish batch --source-dir assets/examples/cell-instances --format json
battinfo index build --source-root assets/examples --out .battinfo/index.json --format json
battinfo index stats --index .battinfo/index.json --format json
```

Python API quick start
```python
from battinfo.api import query_cell_types, create_cell_instance, publish_record

rows = query_cell_types(manufacturer="A123", chemistry="LFP", limit=5)
cell = create_cell_instance(
    model_name="ANR26650M1-B",
    manufacturer="A123",
    serial_number="LAB-001",
)
publish_record(cell, target_root="registry/site")
```
- Full API guide: `docs/python-api.md`

Identifier policy
- See `IDENTIFIER_POLICY.md` for canonical identifier and minting governance.

Notebooks
- See `notebooks/README.md` for guided, executable examples for validation, mapping, ID policy checks, and resolver artifacts.

CLI roadmap
- See `docs/cli-spec.md` for the concrete `query` / `create` / `publish` / `index` command specification.

Resolver artifact build (first draft)
```
python scripts/build_resolver_artifacts.py
python scripts/lint_identifier_policy.py
python scripts/validate_cells_clean.py
```
This generates static resolution artifacts under `registry/site/` for:
- `cell`
- `cell-type`
- `dataset`

Repository layout
- `assets/` Canonical schemas, mappings, and examples (source of truth)
- `src/battinfo/` Python package + CLI
- `registry/compat.yaml` Version pinning for domain-battery and Battery Pass
- `registry/site/` Generated resolver artifacts (HTML + JSON + JSON-LD)
- `docs/` Adoption and usage docs
- `legacy/` Prior ontology artifacts and docs (archived)

Compatibility
See `registry/compat.yaml`.

Notes
- BattINFO does not host or modify the domain-battery ontology.
- BattINFO does not publish authoritative Battery Pass artifacts.
