# Releasing BattINFO

The [`release.yml`](.github/workflows/release.yml) workflow publishes the `battinfo` package to [PyPI](https://pypi.org/project/battinfo/) with trusted publishing (OIDC), so no API token is stored anywhere. The package, the CLI and the OWL ontology (`battinfo.ttl`) share one version line, continued from the ontology releases (v0.2.0, v0.6.0, ...). 0.8.0 is the first version on PyPI.

## One-time setup

On [PyPI](https://pypi.org/manage/account/publishing/) and [TestPyPI](https://test.pypi.org/manage/account/publishing/), add a trusted publisher. Until the project exists on an index it is a pending publisher, created from the account's publishing page:

| Field | PyPI | TestPyPI |
|---|---|---|
| Project name | `battinfo` | `battinfo` |
| Owner | `BIG-MAP` | `BIG-MAP` |
| Repository | `BattINFO` | `BattINFO` |
| Workflow | `release.yml` | `release.yml` |
| Environment | `pypi` | `testpypi` |

Create GitHub environments named `pypi` and `testpypi` in the repository settings. Required reviewers on `pypi` make every upload wait for an approval.

Keep the Zenodo integration switched on for the repository. Its webhook archives each published GitHub Release as a new version under the concept DOI [10.5281/zenodo.6304782](https://doi.org/10.5281/zenodo.6304782).

## Cutting a release

1. On a branch `release/X.Y.Z`, set the version: `__version__` in `src/battinfo/__init__.py` (the build reads it from there), `owl:versionIRI` and `owl:versionInfo` in `battinfo.ttl`, `version` and `date-released` in `CITATION.cff`, the table in `SECURITY.md` and the pin in `tests/installed_smoke.py`. Then regenerate the files that embed it, at least `scripts/gen_reference_records.py` and `scripts/gen_web_examples.py`; AGENTS.md lists every generator.
   Until the first PyPI release (0.8.0), the install lines point at GitHub: `README.md` (which also drops the PyPI badge), `QUICKSTART.md`, `docs/pages/getting-started.rst`, `docs/howto/read-registry-data.md` and `installSnippet` in `web/lib/examples.ts`, with `pypiLive: false` in `web/lib/site.ts`. The 0.8.0 release commit restores `pip install battinfo` and the badge in the files outside `web/`. The website's two lines (`pypiLive` and `installSnippet`) switch back in a separate pull request, merged only once `pip install battinfo==0.8.0` works, so battinfo.org never shows the PyPI install line before it does.
2. In `CHANGELOG.md`, move the `[Unreleased]` entries under `## [X.Y.Z] - <date>` and leave an empty `[Unreleased]` above.
3. Remove what has warned for a full release (`_DEPRECATED_ALIASES` and `_LAZY_EXPORTS` in `src/battinfo/__init__.py`, policy in CONTRIBUTING.md). Deprecations added in this release keep their shims for one more.
4. Run the checks listed in AGENTS.md, then build and check the distribution:

   ```bash
   uv build
   uvx twine check dist/*
   ```

5. Push the branch and rehearse on TestPyPI. The workflow runs CI as its gate, builds the distribution and uploads it:

   ```bash
   gh workflow run release.yml --ref release/X.Y.Z -f target=testpypi
   ```

   Install the rehearsal into a clean environment, with dependencies from PyPI, and run `tests/installed_smoke.py` from a checkout against it:

   ```bash
   pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ "battinfo==X.Y.Z"
   ```

   An index never takes the same version twice, so each version can be rehearsed once.

6. Open the pull request and merge it into `main`.
7. If the tag day differs from the date in `CITATION.cff` and the changelog heading, correct both on `main` first. Then tag `main` and push the tag:

   ```bash
   git switch main
   git pull
   git tag -a vX.Y.Z -m "BattINFO X.Y.Z"
   git push origin vX.Y.Z
   ```

   The tag runs `release.yml` again: the CI gate, the build, a check that the tag matches the built version, the upload to PyPI and a draft GitHub Release with the files attached. The docs workflow publishes the documentation for the tag.

8. Review the draft release and publish it. Zenodo then archives it under the concept DOI and takes the metadata, authors included, from `CITATION.cff`. The README badge and citation use the concept DOI and need no change.

Never delete a published tag or a PyPI release, because downstream users and the Zenodo archive refer to them. A bad release is fixed by publishing a patch release.
