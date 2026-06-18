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

Requires **Python 3.10+**. This project uses [uv](https://docs.astral.sh/uv/)
for environment and dependency management. `uv sync` manages a `.venv` at the
repo root from the committed `uv.lock` — do not use system Python or `pip`
directly.

```powershell
# Create/sync the environment from the lockfile
uv sync --all-extras
```

Run tools via `uv run <cmd>`; no manual venv activation is needed.

## Quality gate

Every pull request must pass the same checks CI runs across Python 3.10/3.11 on
Linux and Windows ([Refactor Checks](.github/workflows/refactor_checks.yml)).
Run them locally before pushing:

```powershell
# Lint
uv run ruff check src tests

# Type check
uv run mypy

# Tests + coverage gate
uv run pytest -q tests --cov=battinfo --cov-report=term-missing

# Identifier-policy compliance
uv run python .tools/quality/lint_identifier_policy.py

# Alpha verification gate (pytest + installed-smoke + wheel build)
uv run python .tools/quality/run_alpha_verification.py
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

## Reporting security issues

Please **do not** open public issues for security vulnerabilities. See
[`SECURITY.md`](SECURITY.md) for responsible-disclosure instructions.
