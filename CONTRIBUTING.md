# Contributing to BattINFO

Thanks for your interest in improving BattINFO. This guide covers how to set up
your environment, the quality gate your change must pass, and how to propose
changes.

By participating in this project you agree to abide by our
[Code of Conduct](CODE_OF_CONDUCT.md).

## Ways to contribute

- **Report a bug** or **request a feature** via the
  [issue templates](https://github.com/BIG-MAP/BattINFO/issues/new/choose).
- **Improve documentation, examples, or guide notebooks.**
- **Submit code or mapping changes** via a pull request (please open an issue to
  discuss substantial changes first).

## Development setup

Requires **Python 3.11+**. This project uses [uv](https://docs.astral.sh/uv/)
for environment and dependency management. `uv sync` manages a `.venv` at the
repo root from the committed `uv.lock` — do not use system Python or `pip`
directly.

```powershell
# Create/sync the environment from the lockfile
uv sync --all-extras
```

Run tools via `uv run <cmd>`; no manual venv activation is needed.

## Quality gate

Every pull request must pass the same checks CI runs across Python 3.11/3.12 on
Linux and Windows ([CI](.github/workflows/ci.yml)). Run them locally before
pushing:

```powershell
# Lint
uv run ruff check src tests

# Type check
uv run mypy

# Tests + coverage gate
uv run pytest -q tests --cov=battinfo --cov-report=term-missing

# Identifier-policy compliance
uv run python .tools/quality/lint_identifier_policy.py

# Verification gate (pytest + installed-smoke + wheel build)
uv run python .tools/quality/run_verification.py
```

## Project conventions

- **Domain-battery is the normative ontology**; BattINFO is operational. Do not
  modify upstream ontology source files.
- **Do not hardcode ontology IRIs** as bare strings in business logic — define
  them as named constants or look them up via the term registry.
- **The canonical contract is JSON Schema**; Pydantic models are generated for
  the CLI and Python API. Keep the application (`bundle.py`) and generated
  (`bundle_generated.py`) layers in sync — `tests/test_schema_sync.py` enforces
  this.
- **Type hints and docstrings** on all public functions and classes.
- All published entities carry a `https://w3id.org/battinfo/{type}/{uid}` IRI,
  governed by [`IDENTIFIER_POLICY.md`](IDENTIFIER_POLICY.md).

## Pull request checklist

- [ ] The quality gate above passes locally.
- [ ] New behaviour is covered by tests.
- [ ] User-facing changes are noted in [`CHANGELOG.md`](CHANGELOG.md) under `[Unreleased]`.
- [ ] Docs/examples updated if the change affects them.

## Authorship

We distinguish **authors** (credited in the citation metadata —
[`CITATION.cff`](CITATION.cff), `pyproject.toml`, and any Zenodo deposit) from
**contributors** (credited in [`CONTRIBUTORS.md`](CONTRIBUTORS.md) and the GitHub
contributor graph). Both are valued; the distinction is only about who appears in
the formal, citable author list.

Someone is listed as an **author** when they meet **both** criteria, adapted from
[ICMJE](https://www.icmje.org/) / [CRediT](https://credit.niso.org/):

1. **Substantial intellectual contribution** — they shaped *what BattINFO is*
   (architecture, the data model or ontology mappings, major features), not an
   isolated patch.
2. **Sustained responsibility** — ongoing, design-level involvement and
   accountability for the project, not a one-off contribution.

Everyone else who contributes code, mappings, examples, documentation, review,
or bug reports is a **contributor**. Useful gut-checks for the author bar:

- *Would BattINFO be materially different without them?*
- *Is their involvement sustained and design-level, rather than a single change?*
- *Would they share responsibility for the correctness of a release?*

Notes:

- A single merged pull request, however valuable, is a contribution — not
  authorship.
- Securing funding or providing supervision is **not**, by itself, authorship
  (it is a CRediT *Funding acquisition* / *Supervision* role, acknowledged
  accordingly) — though such people often also do qualifying technical or design
  work and earn authorship that way.
- Contributors graduate to authors when they cross from one-off into sustained,
  design-level work, by agreement of the existing authors.
- The author list is reviewed at each significant release. Contributions to
  individual published *records* are credited separately, by ORCID, in the
  record metadata itself.

## Releasing

Maintainers: see [`RELEASING.md`](RELEASING.md) for the tag-driven PyPI release
procedure.

## Reporting security issues

Please **do not** open public issues for security vulnerabilities. See
[`SECURITY.md`](SECURITY.md) for responsible-disclosure instructions.
