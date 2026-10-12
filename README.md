<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="brand/assets/logo/logo-horizontal-on-dark.svg">
  <img alt="BattINFO" src="brand/assets/logo/logo-horizontal.svg" width="420">
</picture>

### The semantic data layer for battery technology

Create, validate, and publish battery metadata as machine-readable Linked Data —
typed against [EMMO domain-battery](https://github.com/emmo-repo/domain-battery)
and resolvable through persistent `https://w3id.org/battinfo/` identifiers.

<!-- Badges · status -->
[![CI](https://github.com/BIG-MAP/BattINFO/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/BIG-MAP/BattINFO/actions/workflows/ci.yml)
[![Python](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2FBIG-MAP%2FBattINFO%2Fmain%2Fpyproject.toml&logo=python&logoColor=white)](https://github.com/BIG-MAP/BattINFO/blob/main/pyproject.toml)
[![PyPI](https://img.shields.io/pypi/v/battinfo?label=PyPI)](https://pypi.org/project/battinfo/)
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
<!-- DOI: the Zenodo concept DOI; it resolves to the latest archived release -->
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.6304782.svg)](https://doi.org/10.5281/zenodo.6304782)

[**Quickstart**](QUICKSTART.md) ·
[**Documentation**](docs/index.md) ·
[**How-to guides**](docs/pages/howto.md) ·
[**Tutorials**](#tutorials) ·
[**Contributing**](#contributing) ·
[**Cite**](#citation)

New words? The [plain-language glossary](docs/pages/glossary.md) decodes
*Linked Data*, *EMMO*, *IRI*, and friends in two sentences each.

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
- [Tutorials](#tutorials)
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
- **Provenance built in** — a `CellSpec → Cell → Test → Dataset` chain links every measurement back to the cell that produced it.
- **Standards-ready** — Battery Pass-compatible output, pinned per release.

## Installation

Requires **Python 3.11+**. Install it from PyPI into a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install battinfo
```

Optional extras: `battinfo[processing]` (cycler-file conversion via `ws.convert()` + plotting), `battinfo[tabular]` (CSV/Parquet/XLSX readers), `battinfo[publish]` (RO-Crate validation), `battinfo[storage]` (S3), `battinfo[docs]` (Sphinx), and `battinfo[dev]` (full test/lint/build toolchain). To convert raw cycler files, install the converter and the plotting libraries with:

```bash
pip install "battinfo[processing]"
```

The `processing` extra requires `batterydf[nda,excel,mat]>=0.2.0rc2,<0.3`, so pip installs the batterydf 0.2.0 release candidate until 0.2.0 itself is published.

To try the development version from GitHub instead: `pip install "git+https://github.com/BIG-MAP/BattINFO.git"`. Working on BattINFO itself? See [Contributing](#contributing).

## Quickstart

```python
from battinfo import CellSpec, publish

result = publish(
    CellSpec(
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

That IRI is **permanent, but not yet resolvable on the web** — opening it in a
browser returns 404 for a record published locally. A local publish mints the
identity; it becomes dereferenceable once you publish the record to the
registry (`ws.publish()`, see [Tutorial 6](docs/guides/06-publish-your-data.ipynb)).

`destination="local"` writes to a `.battinfo/` directory (a dot-directory —
`ls -a` to see it):

```text
.battinfo/my-library/
├── index.json
└── examples/cell-spec/cell-spec-<id>.json   # the canonical record JSON
```

Or from the command line:

```powershell
battinfo --help
```

For interactive, multi-record work — cells, tests, datasets, equipment — the
authoring workspace is the blessed surface:

```python
import battinfo
ws = battinfo.workspace(".")
ws.quickstart()   # prints a copy-pasteable end-to-end example
```

**Lab work?** Start at the [how-to guides](docs/pages/howto.md), where bench tasks such as registering materials, building a cell from components, labelling cells, converting cycler exports and publishing each map to a runnable recipe. The
[capability table](docs/workspace-authoring.md#what-each-surface-can-author-today)
shows which surface (workspace, `battinfo.api`, CLI) authors which record types today.

**→ Read the [full quickstart](QUICKSTART.md) and the [documentation index](docs/index.md).**

## Tutorials

Six tutorial notebooks in [`docs/guides/`](docs/guides/) — one story, from the
record model to a published dataset. Each runs from its own folder and writes
only to a throwaway `_scratch/` directory next to it.

| Tutorial | What you'll learn |
|---|---|
| [1 — Concepts](docs/guides/01-concepts.ipynb) | The record model, IRIs, and the semantic layer |
| [2 — Describing a cell](docs/guides/02-first-cell-type.ipynb) | Author and publish a cell spec, with a taste of material-level depth |
| [3 — Linked records](docs/guides/03-linked-records.ipynb) | Cells, test specs, tests, and datasets with the workspace |
| [4 — Semantic layer](docs/guides/04-semantic-layer.ipynb) | JSON-LD anatomy, EMMO type stacking, RDF and SPARQL |
| [5 — Cell descriptors](docs/guides/05-descriptors.ipynb) | Research-grade composition: materials, BOMs, electrodes, electrolyte |
| [6 — Publish your first dataset](docs/guides/06-publish-your-data.ipynb) | End to end: raw cycler CSV → validated records → DOI + registry |

## What BattINFO does

- Validates battery metadata as plain JSON (JSON Schema / Pydantic) **and** as semantic RDF (JSON-LD + URDNA2015 normalisation).
- Maps JSON inputs into domain-battery-aligned JSON-LD using authoritative curated property and unit mappings.
- Produces **Battery Pass-compatible JSON-LD** (pinned to v1.2.0).
- Provides profiles, examples, and mapping rules for all common battery record types.
- Supports a reusable cell-spec library, curated once as BattINFO descriptors and published as generated RDF/JSON-LD.
- Publishes dataset metadata with a core `CellSpec → Cell → Test → Dataset` provenance chain.

## Semantic foundation

| Layer | What it provides |
|-------|-----------------|
| `battinfo.ttl` | OWL application ontology; imports EMMO domain-battery 0.20.2 and domain-electrochemistry 0.37.2 with pinned versioned IRIs |
| [`assets/mappings/domain-battery/`](assets/mappings/domain-battery/) | 114 curated property→EMMO-IRI mappings and 63 unit→EMMO-IRI mappings; drives JSON→JSON-LD transformation |
| `assets/schemas/` | 25 JSON Schema (draft 2020-12) files: one for each of the 22 record types, plus the shared base, the canonical cell description and the ingest manifest |
| [`src/battinfo/transform/json_to_jsonld.py`](src/battinfo/transform/json_to_jsonld.py) | Deterministic, mapping-table-driven transformation to EMMO-aligned JSON-LD using the canonical domain-battery context |
| [`src/battinfo/validate/`](src/battinfo/validate/) | Multi-layer validation: JSON Schema, Pydantic, JSON-LD (URDNA2015), semantic rules, referential integrity, publication |

Published records use:

- `hasProperty` → `[ClassName, ConventionalProperty]` → `hasNumericalPart` → `hasNumberValue` (canonical EMMO quantity pattern)
- `hasMeasurementUnit` → full EMMO or QUDT IRI (never a bare string)
- `@type` stacking: a cylindrical LFP cell is simultaneously `BatteryCell`, `CylindricalBattery`, `LithiumIonBattery`, `LithiumIronPhosphateBattery`, and `LithiumIonGraphiteBattery`

## Project status

> **Beta.** The test suite (3,221 tests at the 0.8.0 release) runs in CI on Python 3.11 and 3.12, on Linux and Windows. Ontology dependency versions are pinned and verified. See [`docs/scope.md`](docs/scope.md) for the full capability map and the [known limitations](docs/scope.md#known-limitations-in-080) of this release.

**Supported**
- Cell-descriptor validation and mapping, canonical record query/save/publish/index flows, JSON-LD-first publication, and validation policies.
- CLI and Python API covering `cell-spec`, `cell-instance`, `test`, `dataset`, and `test-protocol` records.

**Preview (may still change)**
- Reusable cell-spec library flows beyond the walkthrough fixtures.

**In development (no stability promise)**
- The folder-based batch path: `battinfo push` processes a folder of raw cycler files, packages it and deposits it on Zenodo; `battinfo batch` and `battinfo dataset` run the same steps one at a time.
- Registry administration (`battinfo registry bootstrap`).
- Large-scale reference validation.

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

A shorter acceptance gate runs the acceptance tests, a smoke test of the installed package and a wheel build. It is part of the repository, not of the installed package, so run it from a checkout:

```powershell
uv run python .tools/quality/run_verification.py
```

CI runs the same checks across Python 3.11/3.12 on Linux and Windows via the
[CI](.github/workflows/ci.yml) workflow, alongside
[Security](.github/workflows/security.yml) (pip-audit + CodeQL) and
[Docs](.github/workflows/docs.yml) builds.

## Citation

If you use BattINFO in your research, please cite it. The concept DOI
[10.5281/zenodo.6304782](https://doi.org/10.5281/zenodo.6304782) always resolves to the latest archived release;
each release also gets its own version DOI on Zenodo.

```bibtex
@software{battinfo,
  title        = {BattINFO: The semantic data layer for battery technology},
  author       = {Clark, Simon and Friis, Jesper and L{\o}nstad Bleken, Francesca and Flores, Eibar and Stier, Simon and Battaglia, Corsin},
  year         = {2026},
  publisher    = {Zenodo},
  doi          = {10.5281/zenodo.6304782},
  url          = {https://github.com/BIG-MAP/BattINFO}
}
```

> **Maintainers:** publishing a GitHub Release archives it on Zenodo as a new
> version under this concept DOI. Zenodo takes the metadata, including the
> author list, from `CITATION.cff`.

## License

Distributed under the **Apache License 2.0**. See [`LICENSE`](LICENSE).

## Acknowledgements

Built on the [EMMO](https://github.com/emmo-repo) ontology suite — in particular
[domain-battery](https://github.com/emmo-repo/domain-battery) and
domain-electrochemistry — and aligned with the
[Battery Pass](https://thebatterypass.eu/) data content guidance.
