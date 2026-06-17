# BattINFO

BattINFO is the **semantic data layer for battery science**. It provides a
Python library, CLI, and canonical asset suite — JSON schemas, ontology
mappings, and examples — that make it straightforward to create, validate,
and publish battery metadata as machine-readable Linked Data.

Every record published through BattINFO is a valid RDF document, typed against
[EMMO domain-battery](https://github.com/emmo-repo/domain-battery) and
resolvable through persistent `https://w3id.org/battinfo/` IRIs.

## Get started

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e .
```

```python
from battinfo import CellSpecification, publish

result = publish(
    CellSpecification(manufacturer="Panasonic", model="NCR18650B",
                      format="cylindrical", chemistry="Li-ion",
                      nominal_capacity={"value": 3.4, "unit": "Ah"}),
    destination="local",
    root=".battinfo/my-library",
)
print(result.canonical_iri)
# https://w3id.org/battinfo/spec/xxxx-xxxx-xxxx-xxxx
```

**→ [Full quickstart](QUICKSTART.md)** · **[Documentation index](docs/index.md)**

---

## Guide notebooks

Interactive Jupyter notebooks in `docs/guides/` — open from the repo root with the `.venv` kernel.

| Notebook | What you'll learn |
|---|---|
| [01 — Concepts](docs/guides/01-concepts.ipynb) | Data model, record types, IRIs, and the semantic layer |
| [02 — First cell spec](docs/guides/02-first-cell-type.ipynb) | Materials → components → cell spec → publish |
| [03 — Linked records](docs/guides/03-linked-records.ipynb) | Cell instance → test → dataset → registry submission |
| [04 — Semantic layer](docs/guides/04-semantic-layer.ipynb) | JSON-LD anatomy, EMMO type stacking, RDF and SPARQL |
| [05 — Descriptors](docs/guides/05-descriptors.ipynb) | Research-grade descriptors: electrodes, electrolyte, separator |

---

## What BattINFO does

- Validates battery metadata as plain JSON (JSON Schema / Pydantic) and as semantic RDF (JSON-LD + URDNA2015 normalisation).
- Maps JSON inputs into domain-battery-aligned JSON-LD using authoritative curated property and unit mappings.
- Produces Battery Pass-compatible JSON-LD (pinned to v1.2.0).
- Provides profiles, examples, and mapping rules for all common battery record types.
- Supports a reusable cell-spec library curated once as BattINFO descriptors and published as generated RDF/JSON-LD.
- Publishes dataset metadata as JSON-LD with a core `CellSpecification → CellInstance → Test → Dataset` provenance chain.

---

## Semantic foundation

| Layer | What it provides |
|-------|-----------------|
| `battinfo.ttl` | OWL application ontology; imports EMMO domain-battery 0.18.8 and domain-electrochemistry 0.34.0 with pinned versioned IRIs |
| `assets/mappings/domain-battery/` | 47 curated property→EMMO-IRI mappings and 27 unit→EMMO-IRI mappings; drives JSON→JSON-LD transformation |
| `assets/schemas/` | 23 JSON Schema (draft 2020-12) files covering cell specs, cell instances, electrodes, electrolytes, separators, tests, datasets, and organisations |
| `src/battinfo/transform/json_to_jsonld.py` | Deterministic, mapping-table-driven transformation to EMMO-aligned JSON-LD using the canonical domain-battery context |
| `src/battinfo/validate/` | Multi-layer validation: JSON Schema, Pydantic, JSON-LD (URDNA2015), semantic rules, referential integrity, publication |

Published records use:
- `hasProperty` → `[ClassName, ConventionalProperty]` → `hasNumericalPart` → `hasNumericalValue` (canonical EMMO quantity pattern)
- `hasMeasurementUnit` → full EMMO or QUDT IRI (never a bare string)
- `@type` stacking: a cylindrical LFP cell is simultaneously `BatteryCell`, `CylindricalBattery`, `LithiumIonBattery`, `LithiumIronPhosphateBattery`, and `LithiumIonGraphiteBattery`

---

## Status

Pre-release (alpha). 468 tests pass across Python 3.10 and 3.11.
Ontology dependency versions are pinned and verified. See [`docs/alpha-scope.md`](docs/alpha-scope.md).

**In scope for alpha:**
- Cell-descriptor validation and mapping, canonical record query/save/publish/index flows, JSON-LD-first publication, and validation policies.
- CLI and Python API covering `cell-spec`, `cell-instance`, `test`, `dataset`, and `test-protocol` records.

**Preview (may still change):**
- Reusable cell-spec library flows beyond the alpha walkthrough fixtures.

**In development (no stability promise):**
- Registry sync/query (`battinfo push`, `battinfo registry`).
- Large-scale reference validation.

Alpha verification:
```powershell
.venv\Scripts\python .tools/quality/run_alpha_verification.py
```

---

## Repository layout

| Path | Contents |
|------|----------|
| `battinfo.ttl` | OWL application ontology |
| `assets/` | Canonical schemas and mapping assets |
| `examples/` | Canonical example records and guide notebooks |
| `src/battinfo/` | Python package and CLI |
| `docs/` | Adoption and usage documentation |
| `.tools/` | Maintainer tooling: `build/`, `datasheets/`, `library/`, `quality/`, `semantic/` |
| `tests/` | Regression and contract tests |

---

## Core principles

- **Domain-battery is the normative ontology** (semantics and terms). BattINFO is non-normative and operational (schemas, mappings, tooling).
- **Canonical contract is JSON Schema**; Pydantic models are generated for the CLI and Python API.
- **JSON-LD-first publication**: every record rendered for the resolver or registry is valid RDF aligned to domain-battery.
- **Stable, opaque identifiers**: all published entities carry a `https://w3id.org/battinfo/{type}/{uid}` IRI, governed by the identifier policy in `IDENTIFIER_POLICY.md`.
- Battery Pass JSON-LD outputs are supported and pinned per release.
- BattINFO does not host or modify the domain-battery ontology.
