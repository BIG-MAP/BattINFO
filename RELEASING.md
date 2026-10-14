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

Create GitHub environments named `pypi` and `testpypi` in the repository settings. `release.yml` uploads to PyPI only from a pushed `v` tag, and these settings, which a repository admin makes and no pull request can carry, hold the same line on GitHub's side:

- On `pypi`, one required reviewer, the PyPI approver named in the release's tracking issue, who may approve their own run. Every upload waits for that approval.
- On `pypi`, deployment branches and tags limited to the tag rule `v*.*.*`, so no branch can deploy to it, whatever a workflow file says.
- On `pypi`, "Allow administrators to bypass configured protection rules" switched off.
- A tag ruleset for `refs/tags/v*` that lets only maintainers create, update or delete release tags.

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

   The tag runs `release.yml` again: the CI gate; the install gate (`install-smoke.yml`, which installs the built wheel in empty environments on Python 3.11 and 3.14, on Linux and Windows, core-only and with `[processing]`); the build and a check that the tag matches the built version; the hosted check; then, after the `pypi` approval, the upload to PyPI and a draft GitHub Release with the files attached. A manual run of `release.yml` can only target TestPyPI.

   The hosted check (`scripts/check_hosted_files.py`) compares the files w3id serves (the v1 records context, every JSON Schema at its `$id` and the record vocabulary) with the tag's copies. For a final tag a difference stops the upload: deploy the registry with the tag's copies, then use "Re-run failed jobs" on the same run. If the upload itself stops part-way, "Re-run failed jobs" finishes it, since files PyPI already has are skipped. After the release, a daily workflow (`hosted-files.yml`) checks that the hosted context still holds every term of the last release with the same value.

   A pre-release tag such as `vX.Y.Zrc1` goes the same way, except that the hosted check only reports, and the draft release is marked as a pre-release. Leave that draft unpublished, since Zenodo archives pre-releases too. The docs workflow publishes the documentation of each tag in its own folder; only a final tag also updates `stable/` and the version switcher.

8. Review the draft release and publish it. Zenodo then archives it under the concept DOI and takes the metadata, authors included, from `CITATION.cff`. The README badge and citation use the concept DOI and need no change.

Never delete a published tag or a PyPI release, because downstream users and the Zenodo archive refer to them. A bad release is fixed by publishing a patch release.

## Zenodo sandbox run

Before a release, run `scripts/zenodo_sandbox_check.py` by hand against the release candidate, installed in a clean environment, with a token made on [sandbox.zenodo.org](https://sandbox.zenodo.org/account/settings/applications/) (scopes `deposit:write` and `deposit:actions`):

```bash
ZENODO_SANDBOX_TOKEN=<token> python scripts/zenodo_sandbox_check.py
```

It builds a small workspace in a new folder and deposits it to the sandbox the ways a user does: three data files that share a name or differ only in case, a draft then its publish, a run that stops part-way and is finished by a retry, a new version (first with a local data file deleted), a draft then `ws.submit()`, and sandbox then production: the sandbox runs leave the records and the zenodo.org state alone, and a deposit to zenodo.org would start a record of its own. That last check stops every request to zenodo.org before it is sent, so the script reaches the sandbox only. It never uses `ZENODO_API_TOKEN` and will not run in CI or under pytest. It stops at the first step that fails and lists the sandbox records it made.
