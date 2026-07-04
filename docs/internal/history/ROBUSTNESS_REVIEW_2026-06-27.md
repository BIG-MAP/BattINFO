<!-- Generated 2026-06-27 by a multi-agent adversarial robustness review (36 agents, 7 dimensions, 48 findings, 27 critical/high verified with runnable repros). Read-only review: every item is a PROPOSAL — no src/ or tests/ code was modified. -->

# BattINFO Hardening & Test-Debt Report

## 1. Executive Summary

BattINFO's authoring -> validate -> save gate is genuinely solid: JSON schemas are strict (`additionalProperties:false`, regex IRIs, conditional `allOf`), `save()` raises on invalid records via `validate_record_report`, `semantic.py` is a well-curated unit/plausibility/non-finite validator, and the test suite (986 tests) is fully offline, deterministic, and has real adversarial importer coverage. The Zenodo/R2 upload paths (retry+backoff, post-upload checksum verification) are exemplary and serve as the template the rest of the egress code should follow.

The robustness collapses at the **two egress boundaries the whole stack depends on: `ws.submit()` -> the registry, and durable record writes to disk.** Four cross-cutting root causes recur:

1. **Swallow-and-continue is the house error idiom on every high-stakes seam.** `except RuntimeError: print; return []` in `_do_submit`; `except Exception: continue/pass` in `_load_all`, `_read_record_sets`, `_bundle_data_files`, `convert_raw_to_bdf`, `process_contribution`. The package's reflex on any anomaly is to keep going quietly — the exact inverse of the fail-closed mission bar.
2. **No durable-write discipline.** Every write is truncate-in-place (`_jsonio.write_json`) or rmtree-then-rewrite (`workspace_state._write_workspace`), with no temp+os.replace, no fsync, no lock. One Ctrl-C / disk-full / cloud-sync race produces a corrupt record — which then feeds the swallow-and-continue paths.
3. **Validation is a save-time gate, not an invariant.** `ws.submit()` re-reads on-disk records verbatim and hardcodes `validation:{ok:True}` without re-checking; BDF/gold-standard validation is print-only.
4. **The registry is modelled as trusted, not hostile.** No retry, no 5xx/timeout classification, `status='ok'` on any 2xx without reading the body; a 200-with-non-JSON-body or a read-`TimeoutError` isn't even a `RuntimeError`, so it escapes per-record handling and aborts the batch.

**The single most important thing to fix:** make `ws.submit()` fail closed and observable. Today, against a cold-starting/erroring registry — the dominant production failure mode for the Render-hosted registry — it silently drops records, returns a shorter (or empty) list with no exception, prints a success-shaped message, and (via the CLI) **exits 0**. A CI/cron/notebook caller cannot distinguish "published everything", "published nothing", and "published 3 of 5 then crashed". Every downstream repo's data enters the registry through this one operation. Fix this path (structured failure result + raise/non-zero exit + transient-error retry/classification) and ship the fault-injection harness that locks it.

---

## 2. Correctness Bugs (wrong output / data corruption)

### C-1. Distinct `cell_spec`/`test_spec` IRIs collide and silently overwrite each other on save
Flagged by: Authoring->record->submit (AC-01), Test-suite (TS-06). Verdict: **confirmed**, repro run.

`src/battinfo/_workspace.py:1744-1763, 1909-1932, 1963-1982` | **critical** |
- Repro (run): `Workspace.cell_spec()` x2 with identical identity (cap 2.5 vs 3.5 Ah) -> both finalize to `.../spec/mq8v-2v64-5shr-edr0` (COLLISION=True). Full `ws.save()` -> statuses `created` then `updated` to the **same** path; `examples/cell-spec/` holds exactly 1 file containing only 3.5 Ah; the 2.5 Ah spec is gone. Cascade: both authored cells end up with `cell_spec_id` of the surviving (wrong) spec. `test_spec` x2 (kind=cycling, cycles 100 vs 500) -> identical ids, COLLISION=True.
- Root cause: `_disambiguate_entity_ids` is called for `finalized_cells` (1751), `finalized_tests` (1760), `finalized_datasets` (1763) but **never** for `finalized_cell_specs`/`finalized_test_specs`; spec seeds derive from identity fields only, never content.
- Proposed fix: call `_disambiguate_entity_ids(finalized_cell_specs,'cell-spec')` and `_disambiguate_entity_ids(finalized_test_specs,'test-spec')` in `_finalize()` **before** cells/tests finalize (so re-minted spec ids propagate via `cell_spec_map`/`test_spec_map`). Better: fold a content hash (canonical record minus id) into the spec seed so distinct content can never collide.
- Proposed test: `tests/test_workspace.py::test_finalize_disambiguates_colliding_cell_specs` — author two same-identity, different-spec cell_specs; assert the two finalized ids differ **and** after `ws.save()` two distinct files exist on disk; analogous `test_finalize_disambiguates_colliding_test_specs`. (Use `format='cylindrical'`, not literal `'18650'`, which is enum-rejected.)
- **Scope extension (understated):** `publication.py`/`contribution.package_batch` mint IRIs through a **second** path (`_entity_iri` at `contribution.py:623-640`) that never calls `_disambiguate_entity_ids` at all — so the same data-loss bug exists unguarded on the reference-publication surface. Add a parallel test through `build_zenodo_package`/`package_batch`.

### C-2. Order-dependent disambiguation makes the same logical entity get a different IRI across re-runs
Flagged by: Authoring->record->submit (AC-02). Verdict: **confirmed**, repro run.

`src/battinfo/_workspace.py:146-172, 1945-1956` | **high** |
- Repro (run): two `CellInstance`s, identical identity, distinct measured mass [10,20]. Order [10,20] -> `{10:.../cell/dnqz, 20:.../cell/5gg0}`; order [20,10] -> `{20:.../cell/dnqz, 10:.../cell/5gg0}`. Same physical cell (mass=20) gets a different IRI across runs; IRIs swap.
- Root cause: `_disambiguate_entity_ids` re-mints colliding entities with `_entity_iri(type, f'{current}::{ordinal}')` where `ordinal` is iteration order, not content. On re-save (upsert) the mass=20 cell's new content lands on the mass=10 cell's prior IRI file — wrong record clobbered, prior IRI orphaned.
- Proposed fix: seed the collision re-mint from a hash of the entity's distinguishing/canonical content (the finalized objects retain `.measured`), not `f'{id}::{ordinal}'`.
- Proposed test: `tests/test_workspace.py::test_disambiguation_is_order_independent` — finalize the same two content-distinct, identity-colliding cells in both orders; assert each cell's IRI (keyed by content) is identical across orderings.

### C-3. `_num` coerces NaN/Inf into quantity values; validated records serialize to invalid JSON
Flagged by: Interop (IO-01). Verdict: **confirmed**, repro run.

`src/battinfo/interop/protocols.py:54-61` | **critical** |
- Repro (run): `_num('NaN')->nan`, `_num('inf')->inf`. Built a 4-node RO-Crate with `MassLoading hasNumericalValue='NaN'` (unit token `MilliGramPerSquareCentiMetre`); `import_discovery_eln(crate, validate=True)` SUCCEEDED, no exception, no NaN warning; `records[1]/electrode_spec/coating/property/loading/value == nan`; `json.dumps(record, allow_nan=False)` raised "Out of range float values are not JSON compliant". `create_component_spec('electrode', validate=True, ...)` also accepted the NaN.
- Root cause: `_num` has no `math.isfinite()` guard (shared by `discovery._find_property`, `converter._quantity_value`, all protocol importers). The semantic non-finite guard at `validate/semantic.py:423-433` only checks **flat** `specs.{name}` value keys — it does not recurse into nested `coating.property.loading` quantity dicts, so the component-spec path bypasses it. Sibling readers `solid_state_db._number` and `bpx._scalar` already guard with `math.isfinite` — `_num` is the outlier.
- Proposed fix: add `return result if math.isfinite(result) else None` in `protocols._num` (closes discovery/converter/protocols at once). Defense-in-depth: extend the `semantic.py:425` check to recurse into nested `property` quantity dicts so `create_component_spec`/`create_material_spec` fail closed regardless of importer.
- Proposed test: `tests/test_protocol_importers.py::test_num_rejects_non_finite` (`_num('NaN') is None`, `_num('Infinity') is None`); `tests/test_discovery_interop.py::test_discovery_eln_nan_loading_dropped` — assert the NaN-loading crate omits the quantity or raises, and every produced record passes `json.dumps(rec, allow_nan=False)`; `tests/test_api.py::test_create_component_spec_rejects_nan_quantity`.

### C-4. Stale/garbage plot artifacts re-used via skip-if-exists, then published with a real checksum
Flagged by: Processing (PR-03). Verdict: **confirmed**, repro run.

`src/battinfo/processing.py:249-252, 310-313` and `src/battinfo/ws.py:3087, 3106-3118, 6056-6061` | **critical** |
- Repro (run): pre-seed garbage `out/data.png` (27 bytes) and invalid `out/data.plot.json` (`'{"data": [trunca'`); `generate_dataset_plots` returns BOTH paths unchanged (no regeneration). Full `ws.process()` then `path.stat().st_size` + `hashlib.sha256(path.read_bytes())` over the stubs and appends them as dataset distributions whose checksum matches the garbage; the suffix-based promoter (`ws.py:6056-6061`) makes the garbage `.plot.json` a `role=plot_data` entry; `ws.upload()` pushes it to R2. All steps print success.
- Root cause: `_make_static_plot`/`_make_interactive_plot` return `out_path` immediately if it exists, with no completeness/integrity check; `ws.process()` also skips a whole dataset if any distribution name already ends in `.plot.json`.
- Proposed fix: drop or guard skip-if-exists in the plot writers (validate before reuse: `json.loads` the `.plot.json`, check PNG magic bytes / nonzero size); write to `.tmp` then `os.replace`; in `ws.process()` refuse to append a distribution unless the file passes a content sanity check.
- Proposed test: `tests/test_processing_io.py::test_process_does_not_publish_stale_plot` — seed invalid `.plot.json` + garbage png, run `generate_dataset_plots`/`ws.process`, assert the plot.json is valid JSON and the png is a real image (or the distribution is refused) — never trusted as-is.

### C-5. `generate_dataset_plots` produces a "successful" blank/garbage preview from degenerate data
Flagged by: Processing (PR-06). Verdict: not independently re-run by adversary; PR dimension repro confirmed.

`src/battinfo/processing.py:109-132, 253-284, 314-339` | **medium** |
- Repro (run, PR dimension): single-row, all-NaN-voltage, and header-only (zero-row) CSVs all returned `(plot.json, png)` paths as success; only a zero-byte file returned `(None,None)`. The writers check only that `voltage_col`/`time_col` exist, never that there is finite plottable data.
- Proposed fix: before writing, require `df[voltage_col].notna().sum() >= 2`; if not, return `None` and have `ws.process` warn ("no plottable data") rather than publishing a blank preview.
- Proposed test: `tests/test_processing_io.py::test_generate_plots_rejects_degenerate_data` — all-NaN and header-only inputs return `(None,None)`; single-point input handled explicitly, not a silent blank chart.

### C-6. Registry submission sends raw JSON (no EMMO IRIs) and hardcodes `validation:{ok:True}` without running validation
Flagged by: Data-model (DM-01). Verdict: **partial**, repro run. Severity corrected **critical -> high**.

`src/battinfo/ws.py:5918-5958, 6010-6037, 6090-6127` | **high** |
- Repro (run): wrote an invalid cell_spec (unit `'bananas'`, missing required `name`/`chemistry`/`cell_format`, malformed IRI) directly to `examples/cell-spec/` (bypassing `save()`); monkeypatched `submit_publication_package` to capture the POST; `ws.submit(only='cell-spec')` printed `"ACME X1 [published]"` + `"Published - records are live on the platform"`; captured payload carried `validation={'ok':True,...}`, the raw invalid record (`unit 'bananas'` intact), and **no `@context`/EMMO IRIs**.
- Why high not critical: the happy path is guarded — `save()` defaults `validation_policy='strict'` (`ws.py:1927`) and raises on invalid records. Exposure is hand-edited/external/save-bypassed records plus the submit-without-save fallback (see R-9). Note the asymmetry: `workspace_state.build_submission_package` (315-317) DOES run `check()` and raises — BattINFO has **two** submission builders with opposite validation guarantees.
- Proposed fix: in `submit()`, run `validate_record_report(raw, policy='publisher')` per record before building its payload; raise/skip-with-error on `not ok`; populate the payload's `validation` block from the real report instead of a literal. Optionally attach `record_to_jsonld` so published data carries EMMO IRIs.
- Proposed test: `tests/test_authoring_ws.py::test_submit_validates_and_reports_real_validation` — build a record that fails validation, capture the payload via monkeypatched POST, assert `submit()` raises/skips and that no captured payload has `validation.ok=True` for an invalid record; positive variant asserts the captured `validation` block equals the real `validate_record` result.

### C-7. Registry "failed"/"rejected" body on an HTTP-2xx reported as success by the publish path
Flagged by: API (API-03), Data-model (FV-01/AC-04 related). Verdict: **confirmed** (API-03), repro run.

`src/battinfo/api.py:1462-1470, 1518-1524` and `src/battinfo/publish.py:168` | **high** |
- Repro (run): patched `urlopen` -> HTTP 200 body `{'status':'rejected',...}`; `submit_publication_package` returned OUTER `status='ok'`; `publish_curated_cell_spec` returned `PublishResult.status='ok'` while body said `rejected`.
- Root cause: `submit_publication_package` returns `{'status':'ok',...}` for any 2xx without inspecting `response_payload['status']`; `publish.py:168` sets `PublishResult.status = submission_result['status']` (always `'ok'`). `ws.submit()` itself (`ws.py:2947-2956`) DOES read the body status — proving the registry returns body-level `failed`/`rejected` on a 200 — so the asymmetry (ws.submit handles it, publish path does not) is the defect.
- Note (FV-01, corrected critical->medium): the `ws.submit()` summary already prints "Some records did not publish (failed/rejected)" and suppresses the "live" message for a failed body — so it does **not** mislabel as live, but it still returns the failed record inside `results` with no structured/raised signal. Fold into the FV-02 structured-result fix (R-1).
- Proposed fix: in `submit_publication_package`, map a body-level status of `failed`/`rejected`/`error` to a non-ok outer status (or raise); propagate the **body** status (not a blanket `'ok'`) through `publish.py:168` and `publish_curated_cell_spec`.
- Proposed test: `tests/test_api_submit.py::test_submit_publication_package_honours_body_status` — a 200 with body `status='rejected'` must NOT yield outer `status='ok'`; `publish()` must reflect the rejection.

---

## 3. Robustness & Failure-Visibility Gaps

### R-1. `ws.submit()` loses records to errors and reports misleading success — no exception, no failure list, CLI exits 0
Flagged by: Failure-visibility (FV-02), API (API-02), Authoring (AC-03), Test-suite (TS-01), Data-model (DM-05). Verdict: **confirmed**, multiple repros run. **Top threat.**

`src/battinfo/ws.py:6147-6173` (handler), `2800/2845/2874/2901/2944` (extend), `2946-2957` (summary) | **critical** |
- Repro (run): saved 2 cell-specs; monkeypatched `submit_publication_package` to succeed for #1 and raise `RuntimeError('...HTTP 422...')` for #2. `ws.submit()` printed `"Energizer E91 [published]"`, `"ERROR: Duracell MN2400 - ...HTTP 422"`, `"Submitted 1 record(s)"`, `"Published - records are live"`; returned `len=1` list, **no exception, exit code 0**, no failure indicator. With ALL records failing, returns `[]` — indistinguishable from the empty-workspace no-op which also returns `[]`.
- Root cause: `_do_submit` catches any non-409 `RuntimeError`, prints, and `return []`; `submit()` aggregates only non-empty results; the summary only flags failure when a **returned** record's body status is `failed`/`rejected` — an errored record has no result entry, so it's invisible. `publish()` returns `self.submit(...)` directly.
- **CLI exit-code (understated):** the typer `submit` command surfaces the return value without raising, so a CI/cron pipeline keying off exit code sees success on total submission failure.
- Proposed fix: have `_do_submit` return a structured failure entry (`{'status':'failed','error':str(exc),'title':title}`) so failures land in `results`; have `submit()` collect `(id,status,error)`, print `"Attempted N, succeeded M, failed K"`, and **raise** (or return a structured `{submitted, failed}` distinguishing 'all failed' from 'no records') when any record failed, unless `allow_partial=True`; default `publish()`/CLI to raise -> non-zero exit.
- Proposed test: `tests/test_ws_submit.py::test_submit_reports_per_record_failures` — patch one record to raise; assert the return value exposes the failed record (failed list non-empty / count) rather than silently shrinking the success list; variant asserting `battinfo submit` CLI exits non-zero on total failure.

### R-2. One corrupt/0-byte record aborts the entire submit batch (unguarded `json.loads`)
Flagged by: Failure-visibility (FV-03), Authoring (PR-04/AC). Verdict: **confirmed**, repro run.

`src/battinfo/ws.py:2781, 2805, 2851, 2878, 2905` | **high** |
- Repro (run): workspace with `a_good1.json` (valid), `m_bad.json` (0-byte), `z_good2.json` (valid); patched `_do_submit` to record titles. `submit()` submitted `a_good1` (live), then raised `JSONDecodeError` on the 0-byte file; `z_good2` never attempted. Bare stack trace, no per-file report, partial registry submit with no rollback.
- Root cause: the five per-type submit loops do `json.loads(src.read_text(...))` with NO try/except, unlike the guarded `_load_all` (2737-2740) and `_read_record_sets` (711-714). `submit()` POSTs immediately inside each loop with no up-front validation pass.
- Proposed fix: pre-validate ALL session record files up front (one pass that `json.loads` + schema-checks every file) and fail closed **before any `_do_submit` network call**; share the validated set between `_load_all` and the submit loops. Minimally, wrap each per-record load in `try/except (json.JSONDecodeError, OSError)`, collect into a failures list, print per-file, and continue.
- Proposed test: `tests/test_submit_integrity.py::test_submit_fails_closed_on_corrupt_record` — place a corrupt record among valid ones, mock `_do_submit`, assert `submit()` raises **before any network submission** (`call_count==0`) rather than partially submitting.

### R-3. `submit_publication_package` raises uncaught `JSONDecodeError` on a 2xx with non-JSON body
Flagged by: Failure-visibility (FV-04). Verdict: **confirmed**, repro run.

`src/battinfo/api.py:1462-1464` | **high** |
- Repro (run): patched `urlopen` -> 200 with body `b'<html>502 Bad Gateway</html>'`. `submit_publication_package` raised `JSONDecodeError` (not `RuntimeError`); it then propagated through `_do_submit`'s `except RuntimeError` and aborted the batch. Control runs: valid JSON and empty bodies work fine.
- Root cause: the success-path `json.loads(response_text)` is unguarded; only the HTTPError branch (1473-1476) wraps it. A reverse proxy / CDN / Render cold-start returning an HTML page with a 200 is a common production case.
- Proposed fix: wrap success-path `json.loads` in `try/except json.JSONDecodeError` and raise `RuntimeError(f'Registry returned non-JSON response (HTTP {code}): {response_text[:200]}')`.
- Proposed test: `tests/test_api_submit.py::test_submit_publication_package_non_json_2xx_raises_runtimeerror` — patch `urlopen` to a 200 HTML body; assert `RuntimeError`, not `JSONDecodeError`.

### R-4. Socket read-timeout escapes as raw `TimeoutError`, aborting the batch
Flagged by: Failure-visibility (FV-05), Authoring (AC-05). Verdict: **confirmed**, repro run.

`src/battinfo/api.py:1461-1479` | **high** |
- Repro (run): `socket.timeout is TimeoutError: True`; `issubclass(TimeoutError, URLError): False`; `issubclass(TimeoutError, OSError): True`. Patched `urlopen` -> `TimeoutError('timed out')`; `submit_publication_package` raised raw `TimeoutError` (not wrapped); in a 2-record batch, record 1 was POSTed (live) and record 2's timeout aborted the batch uncaught.
- Root cause: only `HTTPError` and `URLError` are caught. A read-timeout (cold-start) raises bare `socket.timeout`/`TimeoutError`, which is neither — so it escapes both `submit_publication_package` and `_do_submit`'s `except RuntimeError`. (Connect-timeouts are wrapped in `URLError` and already caught — the gap is specifically the read-timeout.)
- Proposed fix: broaden to `except (HTTPError, URLError, TimeoutError, OSError) as exc` and wrap as `RuntimeError(f'Registry submission failed (network/timeout): {exc}') from exc`. `OSError` is the safe superset.
- Proposed test: `tests/test_api_submit.py::test_submit_publication_package_timeout_raises_runtimeerror` — patch `urlopen` to raise `socket.timeout`; assert `RuntimeError`; plus a ws-level test that `submit()` reports the record failed rather than aborting.

### R-5. `_jsonio.write_json` is non-atomic (truncate-then-write) — interrupted write destroys the prior good record
Flagged by: Failure-visibility (FV-08), Processing (PR-02). Verdict: **confirmed**, genuine OS-level repro run.

`src/battinfo/_jsonio.py:29-32` | **high** |
- Repro (run): wrote a 54-byte valid record; a subprocess opened the path in `'w'` mode (truncate) and was killed before flush -> file left at **0 bytes**, invalid JSON; `read_record_json` then raised `JSONDecodeError`. `git grep` for `os.replace|NamedTemporaryFile|os.rename|atomic|fsync` across `src/battinfo` -> ZERO atomic-write guards.
- Root cause: `path.write_text(...)` opens with `mode='w'` (truncate-in-place); a crash/SIGINT/ENOSPC after open before flush leaves the file truncated with prior content gone. This is the persistence primitive behind every `save()` (69 call sites across 8 files). The resulting corrupt file then triggers R-2 (batch abort) and FV-07/TS-2 (silent drop).
- **Understated — strictly worse pattern:** `workspace_state._write_workspace` (537-545) `shutil.rmtree`s the **entire** `records/cell-spec`, `cell-instance`, `test`, `dataset` directories **before** rewriting — a Ctrl-C between rmtree and write destroys ALL records in that group, not one file. Severity should reflect group-level blast radius.
- Proposed fix: write to a `NamedTemporaryFile` in `path.parent`, `flush`+`os.fsync`, then `os.replace(tmp, path)` (atomic on POSIX and Windows). Apply to `_jsonio.write_json`, the in-place writes at `ws.py:3124` (process) and `3296` (upload), and especially `workspace_state._write_workspace` (write new dirs to a temp staging dir, then swap — never rmtree-before-write).
- Proposed test: `tests/test_jsonio.py::test_write_json_is_atomic_on_failure` — **must interrupt DURING the OS write** (partial write + raise), not mid-serialization (patching `json.dumps` to raise leaves the original intact even with the bug present, so that phrasing passes trivially). Assert pre-existing content is intact and no stray temp remains. Companion: `tests/test_workspace_state.py::test_write_workspace_atomic_on_interrupt` — kill between rmtree and rewrite, assert recoverability.

### R-6. Corrupt sibling records silently dropped from the submit relationship-graph and the published JSON-LD
Flagged by: Failure-visibility (FV-07), Test-suite (TS-02). Verdict: **confirmed**, repro run.

`src/battinfo/ws.py:2732-2745` (_load_all), `711-714` (_read_record_sets), `3739/3759/3782` (_bundle_data_files) | **high** |
- Repro (run, TS-02): cell-instance whose dataset sibling links back via `dataset.about=[cell_iri]`; `ws._session_paths` set to ONLY the cell-instance (documented "submit a subset" case). Intact: cell-instance `related = ['instanceOf','hasDataset']`. After truncating the dataset sibling: `related = ['instanceOf']` (hasDataset GONE), `warnings = []`, still printed `"Cell ABC [published]"` + `"Published - records are live"`.
- Repro (run, FV-07): truncated cell-spec -> silently absent from `battinfo.json` graph; assembly still passes `validate_jsonld`.
- Root cause: `_load_all` / `_read_record_sets` / `_bundle_data_files` all `except Exception: continue`. `_load_all` deliberately reads EVERY record on disk (`ws.py:2727-2731` comment) so links resolve when a subset is re-submitted — which is exactly what makes a corrupt cross-session file silently drop links on records being submitted now.
- Proposed fix: on `JSONDecodeError`/`OSError`, append the filename to a collected-errors list and surface it (raise when publishing, or at minimum a prominent warning + skipped-file count) instead of silently continuing.
- Proposed test: `tests/test_authoring_ws.py::test_submit_warns_on_corrupt_sibling_record` — corrupt one sibling json, mock submit, assert a warning is surfaced AND the dependent relationship is never silently absent; `tests/test_zenodo.py::test_read_record_sets_surfaces_corrupt_files`.

### R-7. Zenodo deposit can be published with missing data files; no validation gate before `publish_deposit`
Flagged by: Failure-visibility (FV-06). Verdict: **partial**, repro run. Severity corrected **critical -> high**.

`src/battinfo/ws.py:3752-3760` (skip), `3304-3524` (zenodo, no validation before publish at 3500) | **high** |
- Repro (run): a dataset whose distribution `content_url` is a non-existent `file://` path is silently skipped by `_bundle_data_files` (no warning, unlike `ws.upload()`'s `"WARNING: file not found"` at 3233); the produced JSON-LD distribution node has empty `downloadURL`. `validate_publication_report` on that graph returns 2 hard errors — but that validator is invoked **only** in the preview method (`3706-3707`), never in `zenodo()`, which goes `_bundle_data_files -> build JSON-LD -> publish_deposit` with zero validation. So `zenodo(publish=True)` can mint a DOI on an incomplete deposit.
- Refuted half: the non-`file://`/R2 case is **guarded** — `_download_url` returns the http(s) URL verbatim, pointing at the live hosted file (correct). The finding's "dangling reference to a live URL of a missing file" mechanism is inaccurate; the real harm is the empty-URL distribution + unrun validator on the moved/deleted `file://` source.
- Proposed fix: (1) run `validate_publication_report` inside `zenodo()` before `publish_deposit` and raise on errors when `publish=True`; (2) make `_bundle_data_files` record/print skipped referenced `file://` distributions (parity with `ws.upload`).
- Proposed test: `tests/test_zenodo.py::test_zenodo_fails_closed_on_missing_distribution_file` — a dataset referencing a non-existent `file://` file causes `zenodo(publish=True)` to warn/raise; the R2/https case must NOT trip it.

### R-8. `convert_raw_to_bdf` swallows a corrupt cached `.bdf.parquet` and aliases it to "no deps"
Flagged by: Processing (PR-01), Failure-visibility (FV-10). Verdict: **partial**, repro run. Severity corrected **high -> medium**.

`src/battinfo/processing.py:195-228` | **medium** |
- Repro (run): seed valid `cell.csv` + 36-byte garbage `cell.bdf.parquet`; `convert_raw_to_bdf(raw)` -> `(None,None)`, corrupt file still present; control with no pre-existing parquet generates a real parquet (raw IS convertible); 3 repeated calls -> `(None,None)` each, file never cleared (permanent poisoning). The sole caller `contribution.py:345-347` collapses `(None,None)` (corruption) and the ImportError branch (no `batterydf`) into the same `None`.
- Why medium: never produces/submits bad data — returns the no-op sentinel and skips BDF/test-type derivation (recoverable by deleting the stale file). A fail-silent/ambiguous-sentinel robustness defect, not an integrity breach.
- Proposed fix: on read failure of an existing output, delete-and-regenerate or raise a typed error (never reuse the cached parquet without an integrity check); write to a `.tmp` sibling + `os.replace`; return a richer result so "corrupt cache" != "no deps". In `contribution.py`, record per-file conversion failures into `warnings`/`errors` instead of `except Exception: pass` (348-349).
- Proposed test: `tests/test_processing_io.py::test_convert_raw_to_bdf_rejects_corrupt_cached_parquet` — seed garbage `.bdf.parquet`, assert it regenerates or raises and does NOT silently return `(None,None)` leaving the corrupt file.

### R-9. `submit()` with empty `_session_paths` silently submits EVERY record on disk
Flagged by: Authoring (AC-06). Verdict: confirmed by dimension (not re-run by adversary).

`src/battinfo/ws.py:2714-2723` | **medium** |
- Repro sketch: populate `examples/cell-spec/` with two files; instantiate `AuthoringWorkspace` fresh (so `_session_paths=set()`); call `ws.submit()` with patched `_do_submit`; observe it submits BOTH files despite no `save()` this session — contradicting the `save()` docstring promise (1932-1933) that prior-session leftovers are ignored. Compounds C-6: bad/leftover drafts submit asserting `validation:{ok:True}`.
- Proposed fix: track whether a `save()` occurred this session; if `submit()` is called with no recorded session, require explicit `submit_all=True` or raise (`"call ws.save() first, or pass submit_all=True"`). Do not default to submitting everything.
- Proposed test: `tests/test_ws_submit.py::test_submit_without_save_does_not_publish_leftovers` — pre-populate `examples/`, fresh workspace, patch `_do_submit`; assert `submit()` raises or submits nothing.

### R-10. UTF-8 BOM / latin-1 record files are routine malformed input handled silently-wrong
Flagged by: Completeness critic (newly surfaced). Verdict: probe reproduced (raises).

`src/battinfo/_jsonio.py:21` and ~63 `read_text(encoding='utf-8')` sites in `ws.py` | **high** |
- Repro (probe, run): a BOM-prefixed record (`b'\xef\xbb\xbf...'`) raises `JSONDecodeError('Unexpected UTF-8 BOM')`; a latin-1 degC sign raises `UnicodeDecodeError`. BOM/latin-1 files are the Windows/Excel norm in exactly this user's instrument/legacy-data tooling.
- Why it matters: this is the realistic **trigger** that fires R-2 (submit-loop abort before record one), R-6 (silent `_load_all` link drop), and the corruption blast radius of R-5 — without any interrupted write. Every agent assumed corruption only comes from crashes; encoding is the common-case source.
- Proposed fix: decide policy and apply uniformly — either read with `encoding='utf-8-sig'` (tolerate BOM) plus an explicit loud error with file context on non-UTF-8, or fail-loud-with-filename on any decode error. Whichever, the submit/`_load_all` paths must not abort the batch or silently drop.
- Proposed test: `tests/test_jsonio.py::test_read_record_rejects_non_utf8_with_file_context` + `tests/test_ws_submit.py::test_submit_handles_bom_record_loudly` — write a BOM record and a latin-1 record; assert the submit loop does NOT abort the batch and the undecodable sibling is surfaced (error/warning), never silently dropped.

---

## 4. API / Design Weaknesses

### A-1. Registry client has no retry and no 5xx/timeout classification
Flagged by: API (API-01). Verdict: **confirmed**, repro run.

`src/battinfo/api.py:1441-1479` | **high** |
- Repro (run): patched `urlopen` to raise `URLError(socket.timeout)` on call 1 and return 200 on call 2; `submit_publication_package` made exactly 1 attempt before raising — a single retry would have published. Driving `_do_submit` over a 2-record batch dropped the cold-start record silently (only the 409-substring path retries).
- Root cause: single `urlopen(timeout=30)`, every `HTTPError` (400/409 and 500/503 alike) collapsed to one `RuntimeError`; no 4xx-vs-5xx distinction, no backoff, no typed error. The registry is a cold-starting Render service whose dominant failure is first-request latency.
- Correction to the finding: the cited "proven `zenodo.upload_files` retry precedent" — `zenodo.upload_files` DOES retry with backoff (the per-file upload loop), but the registry client was simply never hardened to match.
- Proposed fix: add bounded retry-with-backoff for connection/timeout + HTTP 429/500/502/503/504; do NOT retry other 4xx; raise typed errors (`RegistryTransientError` vs `RegistryClientError`) so `_do_submit`/`submit` can classify transient vs client and stop silently dropping batch records.
- Proposed test: `tests/test_api_submit.py::test_submit_publication_package_retries_on_5xx_not_4xx` — a 503-then-200 sequence succeeds with >1 attempt; a 422 raises immediately with exactly one attempt; plus a ws-level test that a transient failure does not silently shrink the batch.

### A-2. `ws.submit(only=...)` does not validate the filter; a typo silently submits zero records
Flagged by: API (API-04). Verdict: confirmed by dimension (alias logic replayed).

`src/battinfo/ws.py:2691-2712` | **medium** |
- Repro sketch: `_ALIASES.get(rt.lower().replace('_','-'), rt.lower())` defaults to the raw value when unknown, so `only='cellspec'` (missing dash) yields `allowed={'cellspec'}`, matching no real subdir -> zero records submitted, no error. `only=123` raises a confusing low-level `'int object is not iterable'`.
- Proposed fix: validate `raw_only` against the known accepted type tokens and raise `ValueError` listing valid values on any unknown token; coerce/raise clearly on non-string elements.
- Proposed test: `tests/test_ws_submit.py::test_submit_rejects_unknown_only_filter` — `ws.submit(only='cellspec')` raises `ValueError` naming valid options; `ws.submit(only=['cell-spec','bogus'])` also raises.

### A-3. 409 retry bumps `source_version` and re-POSTs — duplicate proliferation on time-seeded re-runs
Flagged by: API (API-05), Completeness critic (time-seeding link). Verdict: confirmed by dimension. **Understated -> the trigger is routine.**

`src/battinfo/ws.py:6162-6170` | **medium-high** |
- Mechanism: on any 409 the code bumps `_bump_version` (`...-v2`, `-v3`) and re-submits with no content comparison. **Why routine, not rare:** `_workspace._now_unix` (114) stamps `retrieved_at`/`created_at` on every freshly-authored record (1906,1931,...) and `_cell_spec_submission_payload` uses `_now_iso()` for `generated_at` (5932,5941). Re-running an authoring **script** from scratch (the canonical reproducibility path) re-creates objects in memory -> new timestamps -> byte-different payload -> registry 409 -> version bump. So the 409-bump path is the **expected** outcome of any reproducible re-author, steadily proliferating `...-v2/-v3` duplicates.
- Proposed fix: only bump+retry on 409 when local content is known to differ from the registry's stored version (compare a content hash, or have the 409 body distinguish "duplicate-identical" from "version-conflict-changed"); treat identical-content 409 as a no-op success. Separately, exclude `retrieved_at`/`created_at`/`generated_at` from the IRI-and-version identity, or make them injectable for reproducible runs.
- Proposed test: `tests/test_ws_submit.py::test_409_identical_content_does_not_duplicate` — a 409 signalling identical content must not result in a bumped-version re-POST; `tests/test_workspace.py::test_reauthored_record_bytes_stable` — author the same logical record in two fresh processes and assert the on-disk identity bytes (excluding free-running timestamps) are stable.

### A-4. `Workspace.save()` hardcodes `mode='upsert'`; the create_only overwrite guard is unreachable
Flagged by: Authoring (AC-07). Verdict: confirmed by dimension (warrants_repro=false).

`src/battinfo/ws.py:1936`, `_workspace.py:1554`, `api.py:2800-2813` | **medium** |
- Mechanism: every authoring save overwrites any existing file with the same IRI with no confirmation. Combined with C-1/C-2, a collision or order-shift silently replaces a sibling record with no fail-closed checkpoint.
- Proposed fix: expose `mode` through `AuthoringWorkspace.save()`; add an integrity check before overwrite (same IRI but content implies an accidental collision rather than a genuine update -> warn or require explicit overwrite flag).
- Proposed test: `tests/test_workspace.py::test_save_create_only_blocks_collision` — with the C-1 collision present, save under create_only-equivalent raises rather than silently overwriting.

### A-5. Zenodo publish/metadata calls (irreversible) have a timeout but no retry
Flagged by: API (API-06). Verdict: confirmed by dimension (warrants_repro=false).

`src/battinfo/zenodo.py:67-90, 125-127` | **medium** |
- Mechanism: `ZenodoClient._request` (create/update/publish/delete) has a 60s timeout but no retry; only `upload_files` retries. A transient 5xx/timeout on the irreversible `publish_deposit` leaves the user unsure whether the publish committed; a transient failure mid-flow can orphan a created draft.
- Proposed fix: on a publish timeout, GET the deposit to confirm `state` before reporting failure; add bounded retry on connection/timeout/5xx for idempotent GETs.
- Proposed test: `tests/test_zenodo.py::test_zenodo_publish_confirms_state_on_timeout` — a timeout on publish followed by a GET showing `state='done'` is treated as success, not error.

### A-6. Credentials file written world-readable; registry error body unbounded/unscrubbed
Flagged by: API (API-07, API-08). Verdict: confirmed by dimension (defensive gaps, no observed leak).

`src/battinfo/ws.py:967-985, 1034-1042` and `src/battinfo/api.py:1471-1477` | **low** |
- Mechanism: `_set_credentials` writes `.battinfo/credentials` (API keys, R2 secrets, Zenodo token) with default OS permissions (no `os.chmod(0o600)`). Separately, `submit_publication_package` embeds the entire (uncapped) `HTTPError` response body verbatim into the `RuntimeError` — a registry that echoes the `X-Battinfo-API-Key` header would leak it (no observed leak under a normal registry; the key is header-only, not in URLs — that part is clean).
- Proposed fix: best-effort `os.chmod(path, 0o600)` after writing (no-op on Windows); truncate the registry error body (`body[:400]`, as `zenodo.py` already does) and scrub anything matching the api_key/known secret patterns before embedding.
- Proposed test: `tests/test_ws_login.py::test_credentials_file_is_owner_only` (skip on Windows); `tests/test_api_submit.py::test_registry_error_message_is_bounded_and_scrubbed` — an HTTPError body echoing the key yields a length-bounded message that does not contain the key.

### A-7. Env/config/credentials precedence is unreviewed — a submit can silently target the wrong registry
Flagged by: Completeness critic (newly surfaced). Verdict: not reviewed by any dimension.

`src/battinfo/config.py` + `.battinfo/credentials` + per-call kwargs + env vars | **medium** |
- Mechanism: registry URL / api_key / tokens resolve from four sources with an undocumented precedence; a stale `.battinfo/credentials` disagreeing with an env var silently determines which registry receives a submit.
- Proposed fix: document and enforce a single precedence order (recommend explicit kwarg > env > credentials file > config default); log the resolved registry host at submit time.
- Proposed test: `tests/test_config.py::test_registry_resolution_precedence` — set a conflicting env var, credentials file, and kwarg; assert a single documented winner.

---

## 5. Data-Model / Schema / Semantic-Fidelity Gaps

### D-1. Four schema-allowed spec properties have no unit-compatibility entry and accept any unit
Flagged by: Data-model (DM-04). Verdict: confirmed by dimension (warrants_repro=false).

`src/battinfo/validate/semantic.py:20-90, 434-446` | **medium** |
- Mechanism: `_validate_specs` only checks units when `spec_name in SPEC_UNIT_COMPATIBILITY`. `ac_internal_resistance`, `initial_coulombic_efficiency`, `self_discharge_rate`, `state_of_health` are schema-valid SpecSet keys with no entry, so `properties.state_of_health = {value:95, unit:'furlongs'}` passes strict validation. The bad unit then flows to JSON-LD (D-2).
- Proposed fix: add `SPEC_UNIT_COMPATIBILITY` (and `SPEC_PLAUSIBILITY_BOUNDS` where sensible) entries for the four; better, drive allowed units from the same curated `unit_map` so schema/semantic/JSON-LD agree.
- Proposed test: `tests/test_validation_semantic.py::test_unit_check_covers_all_schema_specs` — assert the set of unit-bearing SpecSet properties is a subset of `SPEC_UNIT_COMPATIBILITY` keys (coverage guard); plus a case asserting a nonsense unit on `state_of_health` raises under strict.

### D-2. Unmapped units leak machine-local `file://` IRIs into exported/SHACL-input RDF
Flagged by: Data-model (DM-02). Verdict: **partial**, repro run. Severity corrected **critical -> low**. Scope corrected.

`src/battinfo/jsonld.py:224` (live path) | **low** |
- Repro (run): `jsonld._UNIT_MAP` is loaded from `unit_map.curated.json` (36 units incl. mAh, Wh/kg) — so `mAh -> EMMO MilliAmpereHour` and `cell_spec_to_jsonld('mAh')` yields ZERO `file://` objects. The finding's "every published quantity corrupts via a 4-entry map" is **refuted** (it conflated the dead `publication.py` `UNIT_IRI_MAP` with the live 36-entry map). Confirmed real but narrow: `_quantity` emits a bare unit string for a genuinely-exotic unit (`psi`, `furlongs`, `mAh/g`); because the context types `hasMeasurementUnit` as `@type:@id`, it expands to `file:///C:/Users/<author>/.../psi` — a filesystem-path leak + non-resolvable RDF — in `ws.export()` output and SHACL-validation input. The gold-standard Zenodo publish graph (`_assemble_zenodo_jsonld`, guarded by `if unit_iri:`) is **not** affected; the cited `publication.py` functions are dead code (no callers, not in `__all__`).
- Proposed fix: in `jsonld._quantity`, when the unit is unmapped emit `schema:unitText` (a literal, like the safe `json_to_jsonld._descriptor_quantity_node` at 420-425) and/or raise.
- Proposed test: `tests/test_build_zenodo_package.py::test_export_unmapped_unit_no_file_iri` — a record quantity in `psi`/`mAh·g⁻¹`; materialize `record_to_jsonld` through rdflib; assert NO triple object is a `file://`/relative IRI and every `hasMeasurementUnit` object is an absolute http(s) IRI or a literal. (Existing tests set zero quantities and are blind to this.)

### D-3. No RDF round-trip assertion anywhere (the deeper gap behind D-2 and DM-01)
Flagged by: Data-model, Completeness critic. Verdict: gap, not a single defect.

- There is no test that materializes `record_to_jsonld` / the publication graph through rdflib/pyLD and asserts every object of an `@id`-typed predicate is an absolute http(s) IRI. `file://`, relative, and bare-string IRIs are entirely unguarded; combined with C-6 (submit payload carries zero EMMO IRIs), published RDF fidelity is untested.
- Proposed test (harness): `tests/test_jsonld_roundtrip.py::test_id_typed_objects_are_absolute_http_iris` — parse export + publication graphs with rdflib; for every `@id`-typed predicate, assert the object is an absolute `http(s)` IRI. Reusable across importers.

### D-4. Gold-standard publication validation is computed but never enforced (preview only)
Flagged by: Data-model (DM-03). Verdict: **partial** (mislocated), repro run. Severity corrected **high -> low**.

`src/battinfo/ws.py:3631-3721` (`preview_jsonld`, not `zenodo()`) | **low** |
- Repro (run): the cited "in `ws.zenodo()`" quote does not exist — `validate_publication_report` appears only at `3706-3709` inside `preview_jsonld` (a documented local-review helper that writes `battinfo.preview.jsonld`, performs no upload). `zenodo()` (3304-3524) never calls it. So as written this finding mislocates the code; the real "publish path doesn't validate" concern is R-7 (no validation before `publish_deposit`), tracked there.
- Residual (low): `preview_jsonld` writes the file before validating and `return out` unconditionally — a minor UX nicety (a preview could surface validation issues more prominently or exit non-zero), not a submission defect.

### D-5. BDC silently drops non-numeric/non-Ah capacity; `batch_import_bdc` never emits warnings
Flagged by: Interop (IO-03). Verdict: confirmed by dimension, probe run.

`src/battinfo/interop/battery_data_commons.py:225-228, 318-330` | **medium** |
- Repro (probe, run): `import_bdc_record({...,'reported_values':{'rated_capacity_Ah':'45'}})` -> `nominal_capacity` not in properties, no signal; `BdcImportPackage.warnings` hardcoded `[]`. A string/0/negative/mAh-under-Ah-key capacity is silently lost.
- Proposed fix: when `rated_capacity_Ah` is present but not a usable positive float, append a warning to a per-record channel; populate `BdcImportPackage.warnings` by collecting per-record warnings instead of `[]`.
- Proposed test: `tests/test_bdc_interop.py::test_bdc_drops_non_numeric_capacity_with_warning` — a string/0/negative capacity yields no `nominal_capacity` AND surfaces a warning; `batch_import_bdc` propagates per-record warnings.

### D-6. Converter import runs no validation; Discovery electrolyte parser mints duplicate solvents
Flagged by: Interop (IO-02 partial, IO-04). Verdict: IO-02 **partial** (high->low, repro run); IO-04 confirmed by dimension.

`src/battinfo/interop/converter.py:242-419`; `src/battinfo/interop/discovery.py:157-175` | **low** |
- IO-02 (low): converter import is the only importer with no validation call, but the genuine fail-closed gate is the `ws.save(validation_policy='strict')` boundary (`_workspace.py:388`), which re-validates; and pydantic `model_dump(mode='json')` converts NaN->null before the record (so no NaN reaches output, `allow_nan=False` already succeeds). Note: the finding's proposed `_validate_canonical_record(record)` fix is itself broken — it raises "Unsupported record type" on the converter's library-record envelope. The real improvement is an optional `validate=` parameter for parity + turning a non-finite numeric into a loud warning rather than a silent null.
- IO-04 (low): `_parse_electrolyte('1M LiPF6 EC:EC=1:1')` -> two `EC` components; the parser splits any `XX:YY` token, so a stray colon code invents phantom solvents with `volume_fraction None`.
- Proposed fix: add an optional `validate=` to `import_converter_jsonld_record` for parity; in discovery, dedupe solvent names (or warn on duplicates) and require recognized solvent tokens.
- Proposed test: `tests/test_converter_interop.py::test_converter_import_validates_output` (optional validate path); `tests/test_discovery_interop.py::test_discovery_electrolyte_dedupes_solvents`.

### D-7. `_group_files_by_cell` silently collapses unmatched filenames into one cell
Flagged by: Completeness critic (newly surfaced). Verdict: not reviewed by any dimension.

`src/battinfo/contribution.py:~980` | **medium** |
- Mechanism: when filename patterns don't match, `_scan_data_files`/`_group_files_by_cell` falls back to `{'1': all-files}` single-cell grouping — silently mis-attributing multiple physical cells to one, a data-model corruption. `push_batch` `shutil.move`s raw files with no rollback.
- Proposed fix: when no cell token is detectable, warn/error rather than collapsing; do not attribute multiple files to a single synthetic cell without an explicit opt-in.
- Proposed test: `tests/test_contribution.py::test_group_files_no_token_does_not_collapse` — filenames with no detectable cell token must not silently collapse into a single `'1'` group.

### D-8. No schema-version back-compat path on workspace/record load
Flagged by: Completeness critic (newly surfaced). Verdict: not reviewed by any dimension.

`workspace_state.py:438` (`WorkspaceStateStore.open`) | **low-medium** |
- Mechanism: `WORKSPACE_STATE_SCHEMA_VERSION`/record `schema_version` are written but `open()` does `model_validate` with no version check — a future/older `schema_version` is silently accepted or hard-fails on an unrelated field.
- Proposed fix: add a version-aware check that raises a clear, actionable error on an unknown major version.
- Proposed test: `tests/test_workspace_state.py::test_open_rejects_incompatible_schema_version` — a manifest with `schema_version='9.9.9'` + a future-only field yields a clear version error, not a silent accept or an unrelated pydantic failure.

---

## 6. Test-Coverage Backlog (prioritized)

**Coverage state:** suite is fully offline (`--disable-socket --allow-hosts=127.0.0.1,::1,localhost`, `--strict-markers`, `--timeout=300`), deterministic, gated at `fail_under=72` while measured is 73.88%. The two largest user surfaces are the least covered: `ws.py` 51% (submit body 2668-2956, process, upload, zenodo all in the missing set), `cli.py` 44%, `contribution.py` 44%, `processing.py` 21% (import-time only). No `hypothesis` dependency; no fault-injection harness.

### P0 — the fault-injection harness (covers FV-01..05, AC-03..05, API-01..03, DM-05, TS-01, R-1..R-4)
`tests/test_ws_submit.py` (new) — one parametrized harness that monkeypatches `battinfo.api.submit_publication_package` to: (a) raise `RuntimeError('503')`, (b) raise `TimeoutError`, (c) return 200 with non-JSON body, (d) return 200 with body `status='failed'`, (e) succeed-then-fail across two records. Assertions: `ws.submit()` either raises or returns a structured result distinguishing succeeded/failed/dropped (never a bare shorter list); the `battinfo submit` CLI exits **non-zero**; "all failed" is distinguishable from "no records".

### P0 — corrupt/encoding input at the submit boundary (R-2, R-6, R-10)
- `tests/test_submit_integrity.py::test_submit_fails_closed_on_corrupt_record` — corrupt record among valid ones; mock `_do_submit`; assert raise before any network call (`call_count==0`).
- `tests/test_ws_submit.py::test_submit_handles_bom_record_loudly` — BOM-prefixed and latin-1 record files; assert the batch does not abort and the undecodable file is surfaced, never silently dropped.
- `tests/test_authoring_ws.py::test_submit_warns_on_corrupt_sibling_record` — truncated sibling; assert warning + the dependent relationship never silently absent.

### P0 — atomic-write regression (R-5)
- `tests/test_jsonio.py::test_write_json_is_atomic_on_failure` — interrupt DURING the OS write (partial write + raise); assert prior content intact, no stray temp.
- `tests/test_workspace_state.py::test_write_workspace_atomic_on_interrupt` — kill between rmtree and rewrite; assert the whole record group is recoverable.

### P0 — spec IRI collision on BOTH minting paths (C-1, C-2, A-4)
- `tests/test_workspace.py::test_finalize_disambiguates_colliding_cell_specs` / `..._test_specs` — two same-identity, different-content specs; assert distinct finalized ids AND two distinct on-disk files.
- `tests/test_workspace.py::test_disambiguation_is_order_independent` — same two content-distinct cells in both orders; assert content-keyed IRIs identical.
- `tests/test_publish.py::test_package_batch_disambiguates_colliding_specs` — same collision through `build_zenodo_package`/`package_batch` (the second, currently-unguarded minting path).

### P1 — non-finite / RFC-8259 / RDF round-trip (C-3, D-2, D-3)
- `tests/test_protocol_importers.py::test_num_rejects_non_finite` + `tests/test_discovery_interop.py::test_discovery_eln_nan_loading_dropped` + `tests/test_api.py::test_create_component_spec_rejects_nan_quantity`.
- **Strict-serialization gate (property-ish):** for every importer's output fixture, assert `json.dumps(record, allow_nan=False)` succeeds — a single shared parametrization across `tests/fixtures/interop/`.
- `tests/test_jsonld_roundtrip.py::test_id_typed_objects_are_absolute_http_iris` — parse export + publication graphs via rdflib; every `@id`-typed predicate object is an absolute http(s) IRI (catches D-2 file:// leak + bare/relative IRIs).

### P1 — processing data-quality (C-4, C-5, R-8)
`tests/test_processing_io.py` — `test_process_does_not_publish_stale_plot`, `test_generate_plots_rejects_degenerate_data`, `test_convert_raw_to_bdf_rejects_corrupt_cached_parquet`.

### P1 — registry contract + validation-at-submit (C-6, C-7, A-1, A-2, A-3)
- `tests/test_api_submit.py` — `test_submit_publication_package_non_json_2xx_raises_runtimeerror`, `test_submit_publication_package_timeout_raises_runtimeerror`, `test_submit_publication_package_honours_body_status`, `test_submit_publication_package_retries_on_5xx_not_4xx`.
- `tests/test_authoring_ws.py::test_submit_validates_and_reports_real_validation`.
- `tests/test_ws_submit.py::test_submit_rejects_unknown_only_filter`, `test_409_identical_content_does_not_duplicate`, `test_submit_without_save_does_not_publish_leftovers`.

### P2 — interop/contribution/config/back-compat (D-1, D-5, D-6, D-7, A-7, D-8)
`tests/test_validation_semantic.py::test_unit_check_covers_all_schema_specs`; `tests/test_bdc_interop.py::test_bdc_drops_non_numeric_capacity_with_warning`; `tests/test_discovery_interop.py::test_discovery_electrolyte_dedupes_solvents`; `tests/test_contribution.py::test_group_files_no_token_does_not_collapse`; `tests/test_config.py::test_registry_resolution_precedence`; `tests/test_workspace_state.py::test_open_rejects_incompatible_schema_version`.

### Property-based / fuzz opportunities
Add `hypothesis` as a dev dependency and target: (1) `_num`/numeric coercion (never yields a non-finite float; rejects garbage cleanly); (2) IRI minting determinism + collision-disambiguation order-independence; (3) JSON-LD round-trip (`record -> jsonld -> rdflib -> assert no file://`); (4) `_bump_version` over `''`, `'x'`, `'x-v2'`, `'x-v9'`.

### Coverage / CI gate
Ratchet `fail_under` from 72 to **74** immediately (current level, no new tests needed). Once the P0 submit/processing tests land, add **module-level floors** for the critical paths via a small CI assertion script: `ws.py` submit path and `processing.py` must meet a per-module floor (a single global gate lets high-coverage small modules mask regression on the riskiest code). Keep `--strict-markers`/`--disable-socket` and add a CI assertion that no test uses `@pytest.mark.enable_socket`.

---

## 7. Recommended Hardening Sequence (cheapest-highest-leverage first)

1. **Make `_jsonio.write_json` atomic (temp + fsync + os.replace)** — one localized change that hardens every record write; immediately removes the corruption precondition behind R-2/R-6/R-10 blast radius. Add the regression test (interrupt DURING write). Then fix `workspace_state._write_workspace` to stage-then-swap instead of rmtree-before-write.
2. **Fix the registry exception contract in `api.py`** — broaden the `except` to `(HTTPError, URLError, TimeoutError, OSError)`, guard the success-path `json.loads`, and honour the body-level status. Cheap, closes R-3/R-4/C-7. Add the three `test_api_submit.py` tests.
3. **Make `ws.submit()` fail closed and observable** — `_do_submit` returns structured failure entries; `submit()` collects `(id,status,error)`, prints `Attempted N / succeeded M / failed K`, and raises (or returns `{submitted,failed}`) on any failure unless `allow_partial=True`; CLI/`publish()` default to non-zero exit. Wrap per-record `json.loads` and add the up-front parse-all-before-submit pass. Ship the P0 fault-injection harness. **This is the single most important fix.**
4. **Extend `_disambiguate_entity_ids` to specs (both minting paths) and fold content into spec seeds** — closes the deepest correctness defect (C-1/C-2) for a foundation whose value proposition is stable IRIs. Expose `mode` through `AuthoringWorkspace.save()`.
5. **Add the `math.isfinite` guard to `protocols._num`** (one line) and recurse the semantic non-finite check into nested quantities — closes C-3 across discovery/converter/protocols.
6. **Validate at submit + gate Zenodo publish** — run `validate_record_report` in `submit()` and populate the real `validation` block (C-6); run `validate_publication_report` before `publish_deposit` and warn on skipped data files (R-7).
7. **Guard plot/BDF reuse and degenerate data** (C-4/C-5/R-8); decide the encoding policy (R-10); then the P2 interop/config/back-compat items.

### Definition of robust (exit bar)
- **Every failure mode has a loud error and a regression test.** No `except Exception: continue/pass` and no `except RuntimeError: print; return []` on the network/IO boundary without a surfaced, machine-readable failure count.
- **`ws.submit()` fails closed:** a cold-start/5xx/timeout/non-JSON/2xx-rejection never reports success; partial submit is structurally distinguishable from full success and from "nothing to submit"; the CLI exits non-zero on any failure.
- **All durable writes are atomic** (temp + fsync + os.replace; never rmtree-before-write); a Ctrl-C / disk-full / cloud-sync race cannot destroy a prior good record.
- **Importers and record loaders fail closed on malformed input** (BOM/latin-1/NaN/truncated) — loud error with file context, never silent drop or silent NaN-into-RDF.
- **Distinct entities never silently overwrite** on either the authoring or publication minting path.
- **Published RDF is round-trip-asserted:** no `file://`/relative/bare-string `@id` objects.
- **Coverage >= 74% global with module-level floors on the submit and processing paths, enforced in CI.**

---

## 8. Appendix — Refuted / Already-Handled / Reframed

**Refuted (investigated, not a defect):**
- **DM-03** (gold-standard validation "in `ws.zenodo()`") — repro run: mislocated; `validate_publication_report` lives only in the `preview_jsonld` local-review helper, which `zenodo()` never calls. The real publish-path gap is tracked as R-7. Residual: low.
- **DM-02** as "every published quantity corrupts via a 4-entry map" — repro run: refuted. Live `_UNIT_MAP` has 36 units (mAh/Wh/kg all mapped, ZERO `file://`); the cited `publication.py` `UNIT_IRI_MAP` functions are dead code (no callers, not in `__all__`); the Zenodo publish graph is guarded. Real residual is the narrow exotic-unit export/SHACL leak (D-2, low).

**Overstated (kept at corrected severity):**
- **FV-01** critical -> **medium**, folded into C-7/R-1: repro showed `ws.submit()` does NOT mislabel a 2xx-rejection as "live" (the status-aware summary at `ws.py:2946-2957` suppresses the live message and prints the failed/rejected warning); residual is the stdout-only/returned-in-results signal.
- **IO-02** high -> **low** (D-6): the `ws.save(strict)` boundary re-validates and pydantic converts NaN->null, so no NaN/structurally-bad data reaches output; the proposed `_validate_canonical_record` fix is itself broken on the converter envelope.
- **TS-03** (processing.py 21% coverage) high -> **low** as a standalone item: the zero-import fact is accurate, but the underlying risk is fully captured by C-4/C-5/R-8; the bare coverage number is a symptom. Tests still added in §6 P1.
- **PR-01/FV-10** high -> **medium** (R-8): confirmed behavior, but it returns a no-op sentinel and skips derivation — never produces/submits bad data.
- **R-7 (FV-06)** critical -> **high**: the non-`file://`/R2 half is guarded; only the moved/deleted `file://` source + unrun-validator half is real.

**Already-handled — lock with a regression test (no current coverage):**
- `ws.upload()` post-upload SHA-256 verify + raise on mismatch (`ws.py:3274-3280`) — **add** `tests/test_ws_upload.py::test_upload_raises_on_checksum_mismatch`.
- `ws.convert()` per-file `try/except` so one bad instrument file doesn't abort the batch (`ws.py:1479-1509`) — **add** `tests/test_ws_convert.py::test_convert_isolates_one_bad_file`.
- `save()` raises `ValueError` on invalid records via `validate_record_report` (`_workspace.py:388-390, 447-449`) — covered indirectly; **add** an explicit `tests/test_workspace.py::test_save_rejects_invalid_record_strict`.
- `semantic.py` non-finite NaN/Inf hard-error on **flat** specs (`423-433`) — covered for flat specs; the gap is **nested** quantities (C-3), tested there.
- `zenodo()` defaults `publish=False` (draft, no DOI) (`ws.py:3499-3508`) — **add** `tests/test_zenodo.py::test_zenodo_defaults_to_draft`.
- `test_schema_sync.py` enforces the two-layer `bundle.py`/`bundle_generated.py` contract — already locked; keep.
- `solid_state_db._number` / `bpx._scalar` `math.isfinite` guards and `bpx.to_json(allow_nan=False)` — already correct; they are the contract `_num` (C-3) should match.
