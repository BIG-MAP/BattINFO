<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="brand/assets/logo/logo-horizontal-dark.png">
  <img alt="BattINFO" src="brand/assets/logo/logo-horizontal-light.png" width="420">
</picture>

### The semantic data layer for battery technology

Create, validate, and publish battery metadata as machine-readable Linked Data —
typed against [EMMO domain-battery](https://github.com/emmo-repo/domain-battery)
and resolvable through persistent `https://w3id.org/battinfo/` identifiers.

<!-- Badges · status -->
[![CI](https://github.com/BIG-MAP/BattINFO/actions/workflows/refactor_checks.yml/badge.svg?branch=main)](https://github.com/BIG-MAP/BattINFO/actions/workflows/refactor_checks.yml)
[![Python](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2FBIG-MAP%2FBattINFO%2Fmain%2Fpyproject.toml&logo=python&logoColor=white)](https://github.com/BIG-MAP/BattINFO/blob/main/pyproject.toml)
[![Version](https://img.shields.io/badge/version-0.7.0-blue)](https://github.com/BIG-MAP/BattINFO/releases)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
<br/>
<!-- Badges · activity & quality -->
[![Contributors](https://img.shields.io/github/contributors/BIG-MAP/BattINFO?color=informational)](https://github.com/BIG-MAP/BattINFO/graphs/contributors)
[![Last commit](https://img.shields.io/github/last-commit/BIG-MAP/BattINFO/main)](https://github.com/BIG-MAP/BattINFO/commits/main)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-261230.svg)](https://github.com/astral-sh/ruff)
[![Typed](https://img.shields.io/badge/typing-mypy-2A6DB2.svg)](http://mypy-lang.org/)
<br/>
<!-- Badges · domain alignment -->
[![Ontology: EMMO domain-battery](https://img.shields.io/badge/ontology-EMMO%20domain--battery-6E4C9F.svg)](https://github.com/emmo-repo/domain-battery)
[![Battery Pass](https://img.shields.io/badge/Battery%20Pass-v1.2.0-1B998B.svg)](https://thebatterypass.eu/)
<br/>
<!-- Badges · learn & cite -->
[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/BIG-MAP/BattINFO/blob/main/docs/guides/01-concepts.ipynb)
[![nbviewer](https://img.shields.io/badge/render-nbviewer-F37726?logo=jupyter&logoColor=white)](https://nbviewer.org/github/BIG-MAP/BattINFO/tree/main/docs/guides/)
<!-- DOI: replace the placeholder with the concept DOI minted on the first Zenodo release -->
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.XXXXXXX.svg)](https://doi.org/10.5281/zenodo.XXXXXXX)

[**Quickstart**](QUICKSTART.md) ·
[**Documentation**](docs/index.md) ·
[**Guide notebooks**](#guide-notebooks) ·
[**Contributing**](#contributing) ·
[**Cite**](#citation)

</div>

---

BattINFO provides a Python library, a CLI, and a canonical asset suite — JSON
Schemas, ontology mappings, profiles, and examples — that make it straightforward
to describe batteries as **valid, machine-readable Linked Data**.

Every record published through BattINFO is a valid RDF document, typed against
EMMO domain-battery and resolvable through persistent `https://w3id.org/battinfo/`
IRIs. The result is battery metadata that is interoperable by construction,
queryable with SPARQL, and Battery Pass-compatible out of the box.

## Table of contents

- [Why BattINFO](#why-battinfo)
- [Installation](#installation)
- [Quickstart](#quickstart)
- [Guide notebooks](#guide-notebooks)
- [What BattINFO does](#what-battinfo-does)
- [Semantic foundation](#semantic-foundation)
- [Project status](#project-status)
- [Repository layout](#repository-layout)
- [Core principles](#core-principles)
- [Contributing](#contributing)
- [Citation](#citation)
- [License](#license)

## Why BattINFO

Battery data is fragmented across spreadsheets, vendor datasheets, and ad-hoc
JSON. BattINFO turns that into a single, semantically-grounded record model:

- **Write plain JSON or Python** — get validated, EMMO-aligned JSON-LD.
- **Interoperable by construction** — records share one ontology, one context, and one identifier scheme.
- **Provenance built in** — a `CellSpecification → CellInstance → Test → Dataset` chain links every measurement back to the cell that produced it.
- **Standards-ready** — Battery Pass-compatible output, pinned per release.

## Installation

Requires **Python 3.11+**.

```bash
pip install battinfo
```

Optional extras: `battinfo[storage]` (S3), `battinfo[processing]` (data
analysis), `battinfo[docs]` (Sphinx), and `battinfo[dev]` (full test/lint/build
toolchain).

**Developing on BattINFO?** This repo uses [uv](https://docs.astral.sh/uv/):

```powershell
uv sync --all-extras   # creates .venv and installs from uv.lock
```

## Quickstart

```python
from battinfo import CellSpecification, publish

result = publish(
    CellSpecification(
        manufacturer="Panasonic",
        model="NCR18650B",
        format="cylindrical",
        chemistry="Li-ion",
        nominal_capacity={"value": 3.4, "unit": "Ah"},
    ),
    destination="local",
    root=".battinfo/my-library",
)
print(result.canonical_iri)
# https://w3id.org/battinfo/spec/xxxx-xxxx-xxxx-xxxx
```

Or from the command line:

```powershell
battinfo --help
```

**→ Read the [full quickstart](QUICKSTART.md) and the [documentation index](docs/index.md).**

## Guide notebooks

Interactive Jupyter notebooks in [`docs/guides/`](docs/guides/) — open from the
repo root with the `.venv` kernel.

| Notebook | What you'll learn |
|---|---|
| [01 — Concepts](docs/guides/01-concepts.ipynb) | Data model, record types, IRIs, and the semantic layer |
| [02 — First cell spec](docs/guides/02-first-cell-type.ipynb) | Materials → components → cell spec → publish |
| [03 — Linked records](docs/guides/03-linked-records.ipynb) | Cell instance → test → dataset → registry submission |
| [04 — Semantic layer](docs/guides/04-semantic-layer.ipynb) | JSON-LD anatomy, EMMO type stacking, RDF and SPARQL |
| [05 — Descriptors](docs/guides/05-descriptors.ipynb) | Research-grade descriptors: electrodes, electrolyte, separator |

## What BattINFO does

- Validates battery metadata as plain JSON (JSON Schema / Pydantic) **and** as semantic RDF (JSON-LD + URDNA2015 normalisation).
- Maps JSON inputs into domain-battery-aligned JSON-LD using authoritative curated property and unit mappings.
- Produces **Battery Pass-compatible JSON-LD** (pinned to v1.2.0).
- Provides profiles, examples, and mapping rules for all common battery record types.
- Supports a reusable cell-spec library, curated once as BattINFO descriptors and published as generated RDF/JSON-LD.
- Publishes dataset metadata with a core `CellSpecification → CellInstance → Test → Dataset` provenance chain.

## Semantic foundation

| Layer | What it provides |
|-------|-----------------|
| `battinfo.ttl` | OWL application ontology; imports EMMO domain-battery 0.19.0 and domain-electrochemistry 0.34.0 with pinned versioned IRIs |
| [`assets/mappings/domain-battery/`](assets/mappings/domain-battery/) | 47 curated property→EMMO-IRI mappings and 27 unit→EMMO-IRI mappings; drives JSON→JSON-LD transformation |
| `assets/schemas/` | 23 JSON Schema (draft 2020-12) files covering cell specs, cell instances, electrodes, electrolytes, separators, tests, datasets, and organisations |
| [`src/battinfo/transform/json_to_jsonld.py`](src/battinfo/transform/json_to_jsonld.py) | Deterministic, mapping-table-driven transformation to EMMO-aligned JSON-LD using the canonical domain-battery context |
| [`src/battinfo/validate/`](src/battinfo/validate/) | Multi-layer validation: JSON Schema, Pydantic, JSON-LD (URDNA2015), semantic rules, referential integrity, publication |

Published records use:

- `hasProperty` → `[ClassName, ConventionalProperty]` → `hasNumericalPart` → `hasNumericalValue` (canonical EMMO quantity pattern)
- `hasMeasurementUnit` → full EMMO or QUDT IRI (never a bare string)
- `@type` stacking: a cylindrical LFP cell is simultaneously `BatteryCell`, `CylindricalBattery`, `LithiumIonBattery`, `LithiumIronPhosphateBattery`, and `LithiumIonGraphiteBattery`

## Project status

> **Pre-release (alpha).** **938 tests** pass across Python 3.11 and 3.12 on Linux
> and Windows. Ontology dependency versions are pinned and verified.
> See [`docs/alpha-scope.md`](docs/alpha-scope.md).

**In scope for alpha**
- Cell-descriptor validation and mapping, canonical record query/save/publish/index flows, JSON-LD-first publication, and validation policies.
- CLI and Python API covering `cell-spec`, `cell-instance`, `test`, `dataset`, and `test-protocol` records.

**Preview (may still change)**
- Reusable cell-spec library flows beyond the alpha walkthrough fixtures.

**In development (no stability promise)**
- Registry sync/query (`battinfo push`, `battinfo registry`).
- Large-scale reference validation.

Run the alpha verification gate locally:

```powershell
.venv\Scripts\python .tools/quality/run_alpha_verification.py
```

## Repository layout

| Path | Contents |
|------|----------|
| `battinfo.ttl` | OWL application ontology |
| [`assets/`](assets/) | Canonical schemas and mapping assets |
| [`examples/`](examples/) | Canonical example records and guide notebooks |
| [`src/battinfo/`](src/battinfo/) | Python package and CLI |
| [`docs/`](docs/) | Adoption and usage documentation |
| `.tools/` | Maintainer tooling: `build/`, `datasheets/`, `library/`, `quality/`, `semantic/` |
| [`tests/`](tests/) | Regression and contract tests |

## Core principles

- **Domain-battery is the normative ontology** (semantics and terms). BattINFO is non-normative and operational (schemas, mappings, tooling).
- **The canonical contract is JSON Schema**; Pydantic models are generated for the CLI and Python API.
- **JSON-LD-first publication**: every record rendered for the resolver or registry is valid RDF aligned to domain-battery.
- **Stable, opaque identifiers**: all published entities carry a `https://w3id.org/battinfo/{type}/{uid}` IRI, governed by [`IDENTIFIER_POLICY.md`](IDENTIFIER_POLICY.md).
- Battery Pass JSON-LD outputs are supported and pinned per release.
- BattINFO does not host or modify the domain-battery ontology.

## Contributing

Contributions are welcome. Please open an issue to discuss substantial changes
before submitting a pull request, and make sure the full quality gate passes:

```powershell
uv sync --all-extras
uv run ruff check src tests
uv run mypy
uv run pytest -q tests
```

CI runs the same checks across Python 3.11/3.12 on Linux and Windows via the
[Refactor Checks](.github/workflows/refactor_checks.yml) workflow.

## Citation

If you use BattINFO in your research, please cite it. Once the first release is
archived on Zenodo, the concept DOI badge above will resolve to a citable record:

```bibtex
@software{battinfo,
  title        = {BattINFO: The semantic data layer for battery technology},
  author       = {Clark, Simon and Friis, Jesper and L{\o}nstad Bleken, Francesca and Flores, Eibar and Stier, Simon and Battaglia, Corsin},
  year         = {2026},
  publisher    = {Zenodo},
  doi          = {10.5281/zenodo.XXXXXXX},
  url          = {https://github.com/BIG-MAP/BattINFO}
}
```

> **Maintainers:** mint a Zenodo concept DOI on the first tagged release and
> replace `zenodo.XXXXXXX` (in the badge and the citation above) with the real
> identifier.

## License

Distributed under the **Apache License 2.0**. See [`LICENSE`](LICENSE).

## Acknowledgements

Built on the [EMMO](https://github.com/emmo-repo) ontology suite — in particular
[domain-battery](https://github.com/emmo-repo/domain-battery) and
domain-electrochemistry — and aligned with the
[Battery Pass](https://thebatterypass.eu/) data content guidance.
