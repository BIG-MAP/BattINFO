# Beta hardening plan — usable by humans, buildable into infrastructure

Source: 2026-07-05 post-consolidation review (baseline: 1175 passed / 3 skipped, ruff clean).
Out of scope, deferred by design: library/canonical record-shape unification and the four
JSON-LD builders (see `library-canonical-unification.md`); MaterialInput/MaterialSpecInput;
web/ dependabot; the version bump is held until Phase 3 completes.

Phase order is a dependency chain, not a priority list: records must be trustworthy before
we advertise the authoring paths (P0 → P1/P2), and the external contract must be enforced
before downstream systems build on it (P3), after which internal structure can move safely
behind facades (P4). P1 is independent of P0 and can run in parallel.

---

## Phase 0 — Record correctness (the emitted bytes are right) — ✅ DONE (PR #236, merged 2026-07-05)

**Goal:** every record written today is one we won't have to migrate later.
**Size:** ~2 days. **Blocks:** P2, P3. **All items ship with regression tests.**

Outcome notes: digit strings <9 chars rejected as ambiguous (0.2); `SCHEMA_VERSION = "0.2.0"`
supersedes both 0.1.0 and the accidental 1.0.0 (0.6); `source_type` turned out to be
schema-REQUIRED, so its category defaults stay as documented defaults — only `manual.json`
and the example.org URLs were fabrication and are gone; the Zenodo flow stamps the patchable
`ZENODO_RECORD_ID` placeholder URL, the BDC importer falls back to a catalog URN (0.7).

- **0.1 ORCID regression** — `_canonical_agent` (bundle.py:532): pass through `orcid` (and
  `identifier`); treat presence of `orcid`/`given_name`/`family_name` as a Person signal
  instead of defaulting to Organization. Applies to dataset `creators`/`funders`/`publisher`.
  Test: creator dict with orcid survives `to_record()` byte-identical to the pre-consolidation
  builder output (fixture from commit 1f4794d).
- **0.2 Timestamp funnel** — `_to_unix_time` (api.py:391) + every `_to_unix_time(x) or _now_unix()`
  site (api.py:2393-2396, 2452, 1520, 4099, 4154, 4453, 4519):
  - accept `datetime`/`date` (anchor naive to UTC); reject `bool`; never raise (NaN/inf/`"²"` → None);
  - call sites distinguish absent (→ default now) from present-but-unparseable (→ `ValueError`
    naming the field and accepted formats), matching what `Test.started_at` already does;
  - `is None` checks, not `or`, so epoch-0 survives;
  - **decision needed:** 8-digit strings (`"20240101"`) currently parse as unix second
    20,240,101 — proposal: reject digit strings shorter than 9 chars as ambiguous.
  - Extend `tests/test_to_unix_time.py` with datetime/date/0/NaN/bool/8-digit cases.
- **0.3 Conversion symmetry** — convert `expires_at` alongside `manufactured_at`
  (api.py:2359-2363); convert ISO `retrieved_at` in the cell-spec/instance/test builders the
  way the test-spec builder already does (api.py:2337 vs 2452).
- **0.4 Dataset `about` round-trip** — `to_record` (bundle.py:2773) emits primary
  `cell_instance_id`/`test_id` FIRST; `from_record` (bundle.py:2638) reads the full `about`
  list into `related_cell_ids`/`related_test_ids`. Test: to_record→from_record→to_record is a
  fixed point with primary + related refs preserved.
- **0.5 Citation collision** — Dataset `__init__` (bundle.py:2474): route flat `citation` into
  provenance even when `source=` is present (merge, or raise on true conflict); never let the
  `citations` alias capture it.
- **0.6 schema_version** — one module-level `SCHEMA_VERSION` constant used by BundleJsonModel
  and all six api.py sites that still say "0.1.0" (api.py:1252, 2217, 3993, 4021, 4451, 4517).
  **Decision needed:** the value (dataset records silently jumped 0.1.0→1.0.0 in the
  consolidation; pick one and CHANGELOG it explicitly).
- **0.7 Stop fabricating data** — drop `source_file="manual.json"` and make `source_type`
  defaults explicit-or-absent (api.py:2333-2336); replace the `example.org` access_url /
  content_url fallbacks (bundle.py:2756, 2792) with a publish-time error telling the user
  which field to set. (Schema requires access_url — an actionable error beats fake data.)

**Acceptance:** suite green; new tests for each item; a full old-vs-new record byte-diff
(cell spec, instance, test, test-spec, dataset) shows only the intended, CHANGELOG-documented
differences.

---

## Phase 1 — Repair the human funnel (runs parallel to P0) — ✅ DONE (PR #237, merged 2026-07-05)

**Goal:** a newcomer who follows the advertised path succeeds on the first try.
**Size:** ~2–3 days. **Coordinate with the in-flight docs/web WIP before touching docs/.**

Outcome notes: `cycle_life` resolved by standardizing docs on `kind="cycling"` (no enum
addition); all five guide notebooks execute under nbmake in CI. The pre-Phase-1 docs/web
WIP is parked on `wip/docs-web` and needs reconciliation against these changes before it lands.

- **1.1 Guide notebooks** — update all five (`CellType`→`CellSpec`,
  `workspace.cell_type`→`.cell_spec`, `query_cell_types`→`query_cell_specs`,
  `TestProtocol`→`TestSpec`), re-execute, commit executed outputs.
- **1.2 CI guard** — `pytest --nbmake docs/guides/` job so the funnel can't rot again.
- **1.3 Broken snippets** — python-api.md:262 (`setpoints` kwarg; `kind="cycle_life"`),
  getting-started.rst:98 (positional CLI arg), instance-test-dataset-workflow.md:112
  (`--type-id`). **Decision needed:** add `cycle_life` to `BatteryTestType` (it's taught in
  three doc locations) or standardize docs on `calendar_ageing`/`cycling`.
- **1.4 Link/metadata sweep** — six dead links in docs/index.md (targets moved to
  docs/internal/); README test count (938→current); rebuild docs/_build (stale HTML still
  teaches `CellSpecificationInput`).
- **1.5 Doc-snippet harness** — extract fenced python/CLI blocks from QUICKSTART.md,
  python-api.md, getting-started.rst and execute the safe ones in CI.

**Acceptance:** every code cell and fenced snippet in the newcomer path executes in CI.

---

## Phase 2 — Authoring experience (the non-coder succeeds unassisted) — ✅ DONE (branch feat/phase2-authoring-ux, 2026-07-06)

**Goal:** errors teach; nothing accepted is silently dropped; one obvious surface.
**Size:** ~1 week. **Depends on:** P0 (error behavior changes build on the new call-site rules).

Outcome notes: all five acceptance scenarios produce actionable messages. 2.1 extended the
record schemas with the full optional provenance set — **battinfo-registry's vendored
schemas need a re-sync** before records carrying source_name/file_hash/curated_by pass its
gate (fold into 3.1). source_type turned out to be schema-required, so accepted-then-dropped
was fixed by emitting everywhere (one shared serializer/reader pair). 2.4 renamed
workspace_state.WorkspaceManifest → WorkspaceStateManifest.

- **2.1 No silent drops** — raise (or warn + preserve) on: non-mapping `specs=`
  (bundle.py:1246); `source_name`/`file_hash` accepted then omitted from records (either emit
  them — schema work — or reject at construction); positional `cell`/`cell_spec` object passed
  together with a conflicting id kwarg (bundle.py:2242, 1717).
- **2.2 Field descriptions** — `Field(description=...)` on the ~90 fields of the five
  authoring models in bundle.py; the text already exists in adjacent comments and LinkML
  descriptions. Unlocks `help()`, IDE hover, and `.model_json_schema()`.
- **2.3 Aggregated, translated validation errors** — collect ALL schema errors per
  save/publish instead of first-only; map canonical paths back to authoring vocabulary
  (`cell_spec.cell_format`→`format=`, `cell_spec.manufacturer.name`→`manufacturer=`); for
  quantity-shape errors reuse the `battinfo properties show` example text; add
  did-you-mean suggestions for extra-field typos (difflib over field names).
- **2.4 Bless one surface** — export `AuthoringWorkspace` by name, give `workspace()` its own
  doc page mirroring `ws.quickstart()`, add a "which surface do I use?" table to
  QUICKSTART/README, document `Workspace` as the object-graph engine, and fix the wrong module
  path in the AuthoringWorkspace docstring (ws.py:924). Rename one of the two
  `WorkspaceManifest` classes (local_workspace.py:150 vs workspace_state.py:155).
- **2.5 Interop sharp edges** — `import_discovery_eln` handles real `.eln` ZIPs
  (discovery.py:420); a shared `_load_json_source(path)` so every importer error carries the
  file path; per-field warnings in aurora `protocols.py:102-135` when a present numeric fails
  to parse; warn on zero-record batch imports from non-empty files.

**Acceptance:** the five UX failure scenarios from the review (manufacture= typo, bare-number
quantity, cycle_life kind, specs list, dataset with no URL) each produce a single actionable
message naming the fix.

---

## Phase 3 — Infrastructure contract (downstream can depend on it)

**Goal:** the registry seam is versioned, enforced, and fast enough for bulk ingest.
**Size:** ~1–1.5 weeks. **Cross-repo:** battinfo-registry. **Gates the held version bump.**

- **3.1 Schema contract** — emit `SCHEMA_VERSION` (from 0.6) in every record; registry gate
  fails CLOSED on unknown discriminators and flags unknown schema_versions
  (registry `schema_gate.py:139`); add `sync_battinfo_schemas.py --check` and a registry CI
  job diffing vendored schemas against a pinned BattINFO ref. Longer term: publish the schemas
  as a versioned artifact both repos consume.
- **3.2 Provenance stamping** — write `battinfo.__version__` into every record's provenance
  block so malformed records are forensically attributable.
- **3.3 Idempotent minting** — route `save_*` no-uid minting through the ws-style
  content/identity-seeded `_stable_uid` (_workspace.py:118) instead of `secrets.choice`
  (api.py:420); re-running an identical ingest becomes a no-op (`status: exists`/`updated,
  content_changed: False`), not a duplicate corpus. Document the minting policy in save_*
  docstrings. **Decision needed:** identity fields per record type (cell spec:
  manufacturer+model+datasheet_revision is the natural key).
- **3.4 Bulk save session** — a context that loads the id→path map once (kills the O(n²)
  scan in `_find_record_path_by_id`, api.py:2265) and defers index rebuild/validation to
  end-of-batch (_workspace.py:1658). Target ≥1,000 records/s on the 400-record benchmark that
  currently runs at 15–20/s.
- **3.5 Bulk submit** — pooled HTTP session + exponential backoff + resumable outcome journal
  for `ws.submit()` (ws.py:6461); registry bulk endpoint when its side is ready.
- **3.6 Deprecation policy** — write it down (CONTRIBUTING + RELEASING); since the version
  bump is still held, add cheap `*Input` shim classes that raise a `DeprecationWarning` and
  forward to the models for one release, so downstream pinners get a migration message instead
  of ImportError. Remove the `battinfo.publish` function/module shadowing and replace the
  `_looks_like_legacy_publication_call` kwargs-sniffing (publish.py:184) with an explicit path.
- **3.7 De-globalize** — replace `os.environ["BATTINFO_WORKSPACE_ID"]` mutation (ws.py:1080)
  with instance state.

**Acceptance:** registry CI fails on schema drift; 10k-record ingest completes in minutes and
is re-runnable without duplicates; ship the held release (0.8) at the end of this phase.

---

## Phase 4 — Structure & footprint (keep it maintainable at scale)

**Goal:** a curated public surface and module boundaries that survive the post-beta
JSON-LD unification. **Size:** ~1–2 weeks, mechanical, safely after the release.

- **4.1 Curate the namespace** — ~30-name top level (models, `workspace`, `publish`,
  `PublishResult`, `query_*`, `save_record`, `validate_record`, `q`/`quantity`,
  `record_to_jsonld`); everything else behind subpackages via PEP 562 lazy re-export with
  `DeprecationWarning`. Deprecation list: `Cell`/`BatteryCell`/`BatteryCellSpecification`/
  `TestProtocol` aliases, the 40 generated component wrappers (keep generic forms canonical),
  demo helpers (`publish_cr2032_dataset_metadata`, `run_demo_pipeline` → `battinfo.demo`).
- **4.2 Split api.py** (5,164 lines) along measured seams behind a `battinfo.api` facade:
  templates (142-382), staging (628-1281 — export or delete the un-exported dataset staging
  twins), registry client (1282-1482), queries+store (1546-3232), resolver JSON-LD (3233-3980),
  materials/components (3988-4700), index (4705-end). Extract shared `_util.py` for the
  copy-pasted `_as_path`/`_sha256`/`_now_iso`/citation helpers (10 modules) and ESPECIALLY the
  EMMO instrument mapping duplicated in api.py:3564 and publication.py:186.
- **4.3 Workspace unification** — `AuthoringWorkspace` delegates payload building to
  `api.build_curated_cell_spec_submission` (ws.py:6130-6281 currently parallel-builds them).
- **4.4 Dependency footprint** — pandas/pyarrow/openpyxl → `[tabular]` extra, rocrate →
  `[publish]` extra, lazy-import inside api.py; target <0.5 s cold import (measured 2.94 s).
- **4.5 Type-safety debt** — remove mypy `ignore_errors` for `battinfo.api` submodules and
  `validate.schema` as the split lands; CLI `test-protocol`→`test-spec` naming with hidden alias.

---

## Decision points for the maintainer (asked once, up front)

1. ~~`SCHEMA_VERSION` value~~ — DECIDED: `"0.2.0"` (0.6, PR #236).
2. ~~Digit-string timestamp policy~~ — DECIDED: reject <9-digit strings as ambiguous (0.2, PR #236).
3. ~~`cycle_life`~~ — DECIDED: standardize docs on `cycling`; no enum addition (1.3, PR #237).
4. Natural identity keys per record type for deterministic minting (3.3). — OPEN
5. ~~P1 vs docs/web WIP sequencing~~ — RESOLVED: P1 landed first; WIP parked on `wip/docs-web`
   for reconciliation when docs work resumes.

## Sequencing summary

```
P0 record correctness  ──┐          (2 days)
P1 human funnel  ────────┼──► P2 authoring UX (1 wk) ──► P3 contract (1–1.5 wk) ──► release 0.8 ──► P4 structure (1–2 wk)
   (2–3 days, parallel) ─┘
```

Total: ~4–6 focused weeks to both goals; the "usable by humans" bar is substantially met
after P2, "buildable into infrastructure" after P3.
