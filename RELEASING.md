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

1. On a branch `release/X.Y.Z`, move the `[Unreleased]` entries in `CHANGELOG.md` under `## [X.Y.Z] - <date>` and leave an empty `[Unreleased]` above. Step 2 fills in the date.
2. Set the version with `python scripts/set_version.py X.Y.Z --date <release day>`. The script writes every stamp: `__version__` in `src/battinfo/__init__.py` (the build reads it from there), `owl:versionIRI` and `owl:versionInfo` in `battinfo.ttl`, `version` and `date-released` in `CITATION.cff`, the table in `SECURITY.md`, the tag in the `Changelog` URL in `pyproject.toml` and the date of the release's heading in `CHANGELOG.md`. It then reruns the two generators whose output embeds the version, `scripts/gen_reference_records.py` and `scripts/gen_web_examples.py`. The other stamps always take the base version X.Y.Z, so setting a release candidate or a rehearsal build (`X.Y.Zrc1`, `X.Y.Z.dev1`) on a branch already at X.Y.Z changes only `__version__` and the generated files. `python scripts/set_version.py --check` changes nothing and fails when a stamp disagrees with `__version__`, or when `CHANGELOG.md` has no heading for X.Y.Z or dates it differently from `CITATION.cff`. The test suite runs the same check, and `tests/installed_smoke.py` compares the installed version with `__version__`, so it needs no pin.
   Until the first PyPI release (0.8.0), the install lines point at GitHub: `README.md` (which also drops the PyPI badge), `QUICKSTART.md`, `docs/pages/getting-started.rst`, `docs/howto/read-registry-data.md` and `installSnippet` in `web/lib/examples.ts`, with `pypiLive: false` in `web/lib/site.ts`. The 0.8.0 release commit restores `pip install battinfo` and the badge in the files outside `web/`. The website's two lines (`pypiLive` and `installSnippet`) switch back in a separate pull request, merged only once `pip install battinfo==0.8.0` works, so battinfo.org never shows the PyPI install line before it does.
3. Remove what has warned for a full release (`_DEPRECATED_ALIASES` and `_LAZY_EXPORTS` in `src/battinfo/__init__.py`, policy in CONTRIBUTING.md). Deprecations added in this release keep their shims for one more.
4. Run the checks listed in AGENTS.md, then build and check the distribution:

   ```bash
   uv build
   uvx twine check dist/*
   python scripts/check_distribution.py dist
   ```

   `check_distribution.py` checks that the wheel and the sdist carry the licence expression, project URLs, keywords and classifiers of `pyproject.toml`, which an index keeps as uploaded, and that the sdist has no `tests/` folder. CI and the release build run it too.

   For 0.8.0, `python scripts/gen_context.py --check` must also report `0 added since the 0.8.0 snapshot`, so that the snapshot holds every v1 term the release ships ([The frozen v1 records context](#the-frozen-v1-records-context)). CI enforces this for the `release/0.8.0` branch and the `v0.8.0` tags, release candidates included: there `tests/test_context_v1_freeze.py` fails while v1 has a term the snapshot lacks.

5. Push the branch and rehearse on TestPyPI. The workflow runs the CI suite and the install gate, builds the distribution and uploads it. On a manual run the hosted check only reports, since a rehearsal usually runs before the registry has the new copies:

   ```bash
   gh workflow run release.yml --ref release/X.Y.Z -f target=testpypi
   ```

   In a clean environment, install the battinfo wheel from TestPyPI with its dependencies from PyPI, then run `tests/installed_smoke.py` from a checkout against it:

   ```bash
   VERSION=0.8.0rc1  # the exact version on the branch
   pip download --no-deps --only-binary :all: --index-url https://test.pypi.org/simple/ "battinfo==$VERSION" -d "rehearsal-$VERSION"
   pip install "rehearsal-$VERSION"/battinfo-*.whl
   ```

   Only the battinfo wheel comes from TestPyPI. An install with `--extra-index-url` would also let a package on TestPyPI stand in for a PyPI dependency of the same name. Pin the exact version, such as `0.8.0rc1` or `0.8.0.dev1`: TestPyPI already holds a 0.8.0, built from an older commit, and it sorts above every 0.8.0 pre-release. An index never takes the same version twice, so each version can be rehearsed once.

6. Open the pull request and merge it into `main`.
7. If the tag day differs from the date in `CITATION.cff` and the changelog heading, correct both on `main` first (`python scripts/set_version.py X.Y.Z --date <tag day>`). Check where the ontology IRIs lead, as [The ontology at its w3id IRIs](#the-ontology-at-its-w3id-iris) describes. Then tag `main` and push the tag:

   ```bash
   git switch main
   git pull
   git tag -a vX.Y.Z -m "BattINFO X.Y.Z"
   git push origin vX.Y.Z
   ```

   The tag runs `release.yml` again: the CI gate; the install gate (`install-smoke.yml`, which installs the built wheel in empty environments on Python 3.11 and 3.14, on Linux and Windows, core-only and with `[processing]`); the build and a check that the tag matches the built version; the hosted check; then, after the `pypi` approval, the upload to PyPI and a draft GitHub Release with the files attached. A manual run of `release.yml` can only target TestPyPI.

   The hosted check (`scripts/check_hosted_files.py`) compares the files w3id serves (the v1 records context, every JSON Schema at its `$id` and the record vocabulary) with the tag's copies. For a final tag a difference stops the upload: deploy the registry with the tag's copies, then use "Re-run failed jobs" on the same run. When w3id or the registry does not answer, the check stops asking after eight minutes and lists the files it could not fetch; for a final tag that also stops the upload, and "Re-run failed jobs" tries again once the registry is back. If the upload itself stops part-way, "Re-run failed jobs" finishes it, since files PyPI already has are skipped. After the release, a daily workflow (`hosted-files.yml`) checks that the hosted context still holds every term of the last release with the same value.

   A pre-release tag such as `vX.Y.Zrc1` goes the same way, except that the hosted check only reports, and the draft release is marked as a pre-release. Leave that draft unpublished, since Zenodo archives pre-releases too. The docs workflow publishes the documentation of each tag in its own folder; only a final tag also updates `stable/` and the version switcher, and publishes the ontology.

   Push a pre-release tag only when PyPI already holds a final release of `battinfo`, such as the 0.0.1 placeholder that reserves the name, and when the README, the known limitations and the identity, context and schema rules are final and the registry is deployed with the release's copies. While PyPI holds no final release, a plain `pip install battinfo` installs the newest pre-release, and no upload can be edited afterwards. Until then, rehearse with the TestPyPI run of step 5.

8. Review the draft release and publish it. Zenodo then archives it under the concept DOI and takes the metadata, authors included, from `CITATION.cff`. The README badge and citation use the concept DOI and need no change.
9. Once the docs workflow has deployed the tag, check that the ontology IRIs serve the release's `battinfo.ttl` (next section), and that the next run of `hosted-files.yml` is green.

Never delete a published tag or a PyPI release, because downstream users and the Zenodo archive refer to them. A bad release is fixed by publishing a patch release.

## The frozen v1 records context

`src/battinfo/data/context/records.context.v1.json` is the bundled copy of `https://w3id.org/battinfo/context/records/v1.json`, and it is append-only from the v0.8.0 tag: a term it defines keeps its definition, and a new meaning needs a new term or a v2 context. `tests/fixtures/context/records-v1-0.8.0.json` holds every v1 term as 0.8.0 ships it. `tests/test_context_v1_freeze.py` fails when v1 changes or drops one of those terms, and `scripts/gen_context.py` refuses to write such a v1, whether the change comes from a hand edit or a source table. Added terms pass, except a JSON-LD keyword such as `@vocab` or `@language`, which changes how every document expands. `PRE_RELEASE_CORRECTIONS` in `gen_context.py` is closed: the build no longer applies it, v1 carries each of its entries, and it stays as the record the erratum below draws on.

The snapshot is taken last, in the freeze pull request, once every change to v1 for 0.8.0 is on `main`, the pre-release corrections included. Until then `gen_context.py --check` fails on any correction the snapshot does not hold yet, and the command that retakes it is:

```bash
python scripts/gen_context.py --write-snapshot
python scripts/gen_context.py --check
```

The first command writes v1 and the snapshot from the same build; commit both. The second should then report `0 added since the 0.8.0 snapshot`. A term added to v1 after the snapshot, by a soak fix for instance, passes the guard but is not frozen, so if the count is not 0, run the first command again before the tag; CI on the release branch and tags fails until you do. A correction ruled before the tag is made by editing v1, adding an entry to `PRE_RELEASE_CORRECTIONS` for the record, and running the same two commands. `--write-snapshot` refuses once the checkout has the `v0.8.0` tag, and from then on the guard blocks every correction of a frozen term. Later releases add terms without retaking this snapshot.

The snapshot sits in the same tree as v1, so a pull request could change both. Against each release tag from `v0.8.0` on that the checked-out commit contains, `tests/test_context_v1_freeze.py` therefore also checks that v1 keeps every term the tag's v1 defines, which covers terms added after 0.8.0, and that the snapshot equals the tagged copy. `tests/test_schema_freeze.py` checks each schema a tag holds in `src/battinfo/data/schemas/` in the same way: it may differ only in `description`, `title`, `$comment` or `examples`. The CI test job fetches the full history with the tags, so both checks run on every pull request; a shallow clone or an sdist has no tags, and there they skip. A tag that only a later line contains, such as `v0.9.0` seen from a `release/0.8.x` branch, is left out.

Section 11.1 of `IDENTIFIER_POLICY.md` says how many terms 0.8.0 freezes, and its erratum lists every term changed in place before the tag. After a retake, bring both up to date: the number of terms is the count `--write-snapshot` prints less one, since `@version` is not a term, and each term it reports as changed belongs in the erratum's table. `tests/test_identifier_policy_erratum.py` fails when an entry of `PRE_RELEASE_CORRECTIONS` is missing from that table, or when a changelog entry mentions the erratum without linking to it.

## The ontology at its w3id IRIs

`battinfo.ttl` is served from GitHub Pages. For a final tag `vX.Y.Z` the docs workflow (`.github/workflows/docs-deploy.sh`) copies it to `battinfo/versions/X.Y.Z/` on the `gh-pages` branch, and to the root of the site when the tag is the newest final release, each time with a short `battinfo.html` for browsers. A pre-release tag publishes no ontology. A tag whose `battinfo.ttl` declares another version deploys its documentation but not the ontology, and the deploy job fails.

Beside each copy goes `battinfo-inferred.ttl`: [ROBOT](https://robot.obolibrary.org/) merges the import closure and adds what the HermiT reasoner infers, and the file declares the versionIRI `https://w3id.org/battinfo/X.Y.Z/inferred`. The docs workflow installs a pinned ROBOT for tags. ROBOT reads `.github/workflows/docs-deploy-catalog.xml`, which sends the EMMO version IRI to the release's own `emmo.ttl`, since the squashed EMMO that w3id serves there makes HermiT find the closure incoherent. When the EMMO core version in the header of `battinfo.ttl` changes, change it in the catalog too; a test compares them. The file is optional: when ROBOT cannot be installed, finds the closure incoherent or runs past 20 minutes (`REASONER_TIMEOUT`), the ontology is published without it, the job shows a warning, and a root `battinfo-inferred.ttl` of an older version is removed, so `/inferred` never answers for another version than the root.

The deploys of `main` and of a final tag also keep the root's ontology at its versionIRI: before a release replaces it, a root `battinfo.ttl` whose `battinfo/versions/V/` folder does not exist is copied there with its `battinfo-inferred.ttl`. This keeps the 2024 file, `https://w3id.org/battinfo/0.8.0-beta/battinfo`, resolving. They also remove the root `versions/` folder, which held copies of that file under the numbers of older releases.

| IRI | Where it leads |
|---|---|
| `https://w3id.org/battinfo` | `battinfo.ttl` at the root of the site (`battinfo.html` for a browser) |
| `https://w3id.org/battinfo/X.Y.Z` | `battinfo/versions/X.Y.Z/battinfo.ttl` (`battinfo.html` for a browser) |
| `https://w3id.org/battinfo/X.Y.Z/battinfo`, the `owl:versionIRI` | the registry, which answers with a 303 to `https://w3id.org/battinfo/X.Y.Z` |
| `https://w3id.org/battinfo/latest` | `battinfo.ttl` on `main` |
| `https://w3id.org/battinfo/inferred` | `battinfo-inferred.ttl` at the root of the site |
| `https://w3id.org/battinfo/X.Y.Z/inferred` | `battinfo/versions/X.Y.Z/battinfo-inferred.ttl` |
| `https://w3id.org/battinfo/0.8.0-beta/battinfo`, the 2024 file's `owl:versionIRI` | the registry, which answers with a 303 to `https://w3id.org/battinfo/0.8.0-beta`, that is `battinfo/versions/0.8.0-beta/battinfo.ttl` |

The rules live in `battinfo/.htaccess` in [perma-id/w3id.org](https://github.com/perma-id/w3id.org); the versionIRI matches none of the ontology rules there and reaches the registry. `/latest` and its alias `/source` read the `master` branch until a perma-id pull request moves them to `main`, and the `raw/` rules in the same file read `master` still, so keep `master` when old branches are cleaned up.

Before the tag, on the frozen `main` and after the registry deploy, check where each IRI leads:

```bash
python scripts/check_hosted_files.py --ontology-routes
```

It takes the version and the versionIRI from the checkout's `battinfo.ttl` and follows every redirect. It passes when each IRI lands where the table says, even where the file is not there yet: before the tag, `/X.Y.Z`, the versionIRI and `/X.Y.Z/inferred` land on a 404 in `battinfo/versions/X.Y.Z/`, and the root and `/inferred` still serve the last release. Once the perma-id pull request has moved it, `/latest` already serves the frozen `main`. Until then `/latest` lands on `master`, and the check reports it as `pending` without failing: that pull request is reviewed outside this repository and does not block the tag. Any other landing place for `/latest` fails the check. So does a registry that does not yet forward the 0.8.0-beta versionIRI (battery-genome/battinfo-registry#102).

After the tag's docs deploy, from a checkout of the tag:

```bash
python scripts/check_hosted_files.py --ontology-routes --served
python scripts/check_hosted_files.py --ontology --tag vX.Y.Z
```

The first wants the root, `/latest`, `/X.Y.Z` and the versionIRI to serve the tag's `battinfo.ttl`, apart from a `/latest` that is still pending on `master`, and the inferred and 0.8.0-beta IRIs to serve files that declare their versionIRIs. The second is what `hosted-files.yml` runs every day against the newest final tag: the root declares the release's versionIRI and imports, `/X.Y.Z` and the versionIRI serve its `battinfo.ttl`, and the inferred and 0.8.0-beta IRIs are checked as in the first. A release published without `battinfo-inferred.ttl` passes both: a 404 where the inferred file belongs is reported as `routed`, but a file that declares another versionIRI fails. Neither runs in `release.yml`, because the versionIRI resolves only after the tag's own docs deploy.

## Zenodo sandbox run

Before a release, run `scripts/zenodo_sandbox_check.py` by hand against the release candidate, installed in a clean environment, with a token made on [sandbox.zenodo.org](https://sandbox.zenodo.org/account/settings/applications/) (scopes `deposit:write` and `deposit:actions`):

```bash
ZENODO_SANDBOX_TOKEN=<token> python scripts/zenodo_sandbox_check.py
```

It builds a small workspace in a new folder and deposits it to the sandbox the ways a user does: three data files that share a name or differ only in case, a draft then its publish, a run that stops part-way and is finished by a retry, a new version after one data file changed and another was deleted locally (it keeps the copy the version before holds), a draft then `ws.submit()`, and sandbox then production: the sandbox runs leave the records and the zenodo.org state alone, and a deposit to zenodo.org would start a record of its own. That last check stops every request to zenodo.org before it is sent, so the script reaches the sandbox only. It never uses `ZENODO_API_TOKEN` and will not run in CI or under pytest. It stops at the first step that fails and lists the sandbox records it made.
