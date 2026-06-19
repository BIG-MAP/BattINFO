# Releasing BattINFO

BattINFO publishes the `battinfo` package to [PyPI](https://pypi.org/project/battinfo/)
using **OIDC Trusted Publishing** — there are no API tokens to manage. The
[`release.yml`](.github/workflows/release.yml) workflow builds, validates, and
publishes automatically when a version tag is pushed.

The package, CLI, and OWL ontology share **one version line**, continued from the
historical ontology releases (`v0.6.0` → `v0.7.0` → …).

## One-time setup (per maintainer org)

On both [PyPI](https://pypi.org/manage/account/publishing/) and
[TestPyPI](https://test.pypi.org/manage/account/publishing/), add a *pending
trusted publisher*:

| Field        | Value           |
|--------------|-----------------|
| Owner        | `BIG-MAP`       |
| Repository   | `BattINFO`      |
| Workflow     | `release.yml`   |
| Environment  | `pypi` (PyPI) / `testpypi` (TestPyPI) |

Then create matching [GitHub environments](../../settings/environments) named
`pypi` and `testpypi` (optionally with required reviewers as a publish gate).

## Cutting a release

1. **Bump the version.** Edit `__version__` in
   [`src/battinfo/__init__.py`](src/battinfo/__init__.py) — this is the single
   source of truth (`pyproject.toml` reads it dynamically). Keep
   `owl:versionInfo`/`owl:versionIRI` in [`battinfo.ttl`](battinfo.ttl) and the
   version in [`CITATION.cff`](CITATION.cff) in sync.
2. **Update the changelog.** Move `[Unreleased]` entries under a new dated
   `[X.Y.Z]` heading in [`CHANGELOG.md`](CHANGELOG.md).
3. **Verify locally:**
   ```bash
   uv sync --all-extras
   uv run pytest -q tests
   uv build
   uv run python -m twine check dist/*
   ```
4. **(Recommended) Dry-run to TestPyPI** via the Actions tab →
   *Release* → *Run workflow* → `target: testpypi`. Then verify install:
   ```bash
   pip install --index-url https://test.pypi.org/simple/ \
               --extra-index-url https://pypi.org/simple/ battinfo
   ```
5. **Tag and push** — this triggers the real publish:
   ```bash
   git tag -a v0.7.0 -m "BattINFO 0.7.0"
   git push origin v0.7.0
   ```
   The workflow guards that the tag matches the built version, publishes to
   PyPI, and drafts a GitHub Release.
6. **Finalize:** review and publish the drafted GitHub Release. If archiving to
   Zenodo, deposit and then backfill the DOI + `date-released` in
   `CITATION.cff` and the DOI badge/citation in `README.md`.

## Notes

- **Never delete published tags or PyPI releases** — they are referenced by
  downstream consumers and DOI archives.
- PyPI rejects re-uploading an existing version. To fix a bad release, publish a
  new patch version.
