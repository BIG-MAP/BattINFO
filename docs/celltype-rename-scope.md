# Scope: rename/merge `CellType` → `CellSpecification`

## TL;DR

`CellType` and `CellSpecification` are **two coexisting full Pydantic models**
([bundle.py:979](../src/battinfo/bundle.py) and [:1150](../src/battinfo/bundle.py))
that represent the same entity (a `BatteryCellSpecification`). So this is a **model
merge + identifier rename**, not a mechanical find-replace. It touches code, schemas,
on-disk record keys, IRI tokens, docs, tests, and — depending on how far we go — the
live registry and the other three repos. The earlier decision (2026-06-13) deliberately
kept `cell_type` identifiers internal; this reverses that, so the scope decision is
*how deep* the rename goes.

## Footprint (BattINFO repo, occurrences)

| Surface | `CellType` (class) | `cell_type` (snake) | `cell-type` (kebab) |
|---|---|---|---|
| `src/` | 140 across 14 files | 686 across 23 files | 319 across ~40 files |
| `tests/` | — | ~538 across 33 files (combined) | — |

Plus non-code surfaces: `schema/cell-type.yaml`, `assets/schemas/cell-type.schema.json`
(+ packaged copy), `assets/shapes/cell-type.shapes.ttl`, `data/library/cell-type/`,
`examples/cell-type/`, `IDENTIFIER_POLICY.md` §16, and ~10 docs.

## The rename has five distinct layers (each a separate decision)

1. **Python model & API (in-repo).** Merge `CellType` into `CellSpecification`:
   - reconcile fields — `CellType.nominal_properties` vs `CellSpecification.properties`;
     `CellType.cell_specification_id` (back-ref) becomes self; both have manufacturer/
     model/format/chemistry/size_code/product_type/source but `CellType` adds
     `country_of_origin`/`year`, `CellSpecification` adds `specification_comment`;
   - the `CellType.__init__` that absorbs ~40 spec kwargs into `nominal_properties`
     (per CLAUDE.md) must move onto the merged class;
   - rename API methods: `ws.cell_type()`, `Workspace.cell_type()`, `derive_cell_type`,
     `build_publication_package` params, etc.;
   - `CellInstance.cell_type` / `cell_type_id` → `cell_specification` / `cell_specification_id`;
   - `BattinfoBundle.cell_type` and `ZenodoCellRecord.cell_type` → `cell_specification`
     (the bundle already carries a separate `cell_specification` — these merge).
   - `bundle_generated.py` (LinkML-generated) — regenerate from the schema after the
     YAML rename; note this is a large generated diff.

2. **On-disk record keys.** Records use `{"product": …}` / `type_id` (in cell-instance
   records) / the `cell-type` record subdirectory. Renaming these breaks existing
   record files and every `from_record`/`to_record` and `_read_record_sets` mapping.
   *Decision:* rename the record wrapper key (`product` → ?) and `type_id` →
   `cell_specification_id`, or keep on-disk keys stable and only rename in code.

3. **JSON-LD / IRI namespace.** The graph type is already `BatteryCellSpecification`
   (done). IRIs already migrated to `spec/` (per the spec/ IRI migration). BUT
   `from_jsonld` still matches the legacy `/cell-type/` path
   ([bundle.py:2447](../src/battinfo/bundle.py)) and the `cell-type` token appears in
   `jsonld.py`, context, and `IDENTIFIER_POLICY.md` §16. *Decision:* finish purging
   `cell-type` from the IRI/JSON-LD layer (low risk — IRIs already `spec/`).

4. **Schemas, shapes, data, library, examples.** `schema/cell-type.yaml` →
   `cell-specification.yaml` (+ `LinkMLGen` class name), the two `cell-type.schema.json`
   copies, `cell-type.shapes.ttl`, `data/library/cell-type/`, `examples/cell-type/`.
   Renaming files changes the validation `profile`/`resource_type` token
   `"cell-type"` used across `validate/*` and `lint_identifier_policy.py`.

5. **Cross-repo + live registry (out of this repo).** `cell_type`/`type_id`/`cell-type`
   and the `cell-type` profile flow to **battinfo-records, battinfo-registry, and
   battery-genome**, and the live registry DB. A code-only rename here will desync them
   unless coordinated. This is the highest-risk layer and cannot be completed inside
   BattINFO alone.

## Recommended phasing (each independently shippable, suite green between)

- **Phase 0 — decide the on-disk & IRI contract.** Whether record keys (`product`,
  `type_id`), the `cell-type` profile token, and remaining `/cell-type/` IRI references
  change, or stay as compatibility shims. This gates everything else.
- **Phase 1 — merge the models (in-repo, no on-disk change).** Make `CellType` a
  deprecated alias of a merged `CellSpecification` (re-export `CellType = CellSpecification`
  with a `DeprecationWarning`), unify fields, keep `from_record`/`to_record` reading the
  existing on-disk keys. Update internal call sites incrementally. Largest code diff;
  back-compat preserved via the alias.
- **Phase 2 — rename the API surface** (`cell_type()` → `cell_specification()` /
  `cell_spec()`), keeping thin deprecated wrappers. Update tests.
- **Phase 3 — purge `cell-type` from JSON-LD/IRI layer & docs/policy** (low risk; IRIs
  already `spec/`).
- **Phase 4 — rename schemas/shapes/data dirs & the `cell-type` profile token**, with a
  migration for existing record files and the validation profile registry.
- **Phase 5 — cross-repo + registry migration** (coordinated, separate effort across
  battinfo-records/registry/battery-genome + a DB/record migration).

## Risks

- **Generated artifacts:** `bundle_generated.py` regeneration produces a large,
  hard-to-review diff (the installed `gen-pydantic` differs from the committed file —
  see the prior consolidation); plan targeted edits or accept a full regen + review.
- **`schema_sync` / freshness tests** enforce enum/field parity; renames must update
  both layers together.
- **Back-compat:** old `battinfo.json` / `battinfo.bundle.json` / record files in the
  wild (and the registry) carry `type_id`/`cell-type`; readers must keep accepting them.
- **Identifier policy:** `IDENTIFIER_POLICY.md` §16 and `lint_identifier_policy.py`
  encode `cell-type`; the lint will fight an inconsistent partial rename.
- **The 2026-06-13 decision** to keep `cell_type` identifiers is being reversed — confirm
  that's intended for *identifiers/record keys*, not just the user-facing term.

## Effort

- Phases 1–3 (in-repo code + JSON-LD + docs, with deprecation aliases): **large** but
  self-contained; ~all 33 test files touched.
- Phase 4 (schemas/data/profile token + record migration): **medium**, needs a data
  migration script.
- Phase 5 (cross-repo + live registry): **large + coordinated**, outside this repo.

## Execution status (2026-06-15)

- **Phase 1 — model merge: DONE, suite green.** `CellType` merged into one
  `CellSpecification` (union of authoring API + datasheet structure; `properties`
  canonical; transient `nominal_properties` bridge + transient `CellType` alias).
  `Workspace.add` dispatch and `_append_unique` reconciled for the collapsed type.
- **Phase 2 — `CellType`→`CellSpecification` symbol rename: DONE, suite green.** All
  application-layer + test references renamed (the LinkML-generated `bundle_generated`
  `CellType` and the `CellType as Gen…` adapter imports were correctly preserved).

### Finding: Phase 3 is NOT cleanly separable from Phase 4

Renaming `cell_type`→`cell_spec` as a "Python-only, on-disk-stable" step is **not
safely achievable**, because `cell_type` / `cell_types` / `cell_type_id` /
`nominal_properties` are used as **string-literal contract tokens** throughout the
index (`build_index`), the query API (`query_cell_types`, filter keys), workspace-state
serialization, `validate/references`, and authoring-input payloads — exactly the
on-disk/registry/query surface decision A says to keep stable. The Python identifiers
and these stable tokens are the *same strings*, tightly coupled (a method name maps to a
directory name; a field maps to a record key; a query kwarg maps to an index key). A
partial sweep would leave a confusing half-state (Python says `cell_spec`, the
index/query/registry say `cell_type`).

**Recommendation:** fold the `cell_type`→`cell_spec` identifier rename INTO the
coordinated Phase-4/5 migration (records + index + query API + registry DB + the three
downstream repos), done as one lockstep change — not as an in-repo-only Phase 3. The
cleanly-separable in-repo work (the model merge + the `CellSpecification` class symbol)
is complete. The transient `CellType` alias and `nominal_properties` bridge remain until
that coordinated migration removes them.

## Confirmed decisions (2026-06-15)

1. **Depth:** all the way through (Phases 1–5).
2. **Back-compat:** hard-break, no permanent aliases (a *transient* alias is used only
   during the refactor to keep the suite green between phases, removed at the end).
3. **Target term:** `cell_spec` / `CellSpecification`.

## Concrete merge design (Phase 1)

The two models become **one** `CellSpecification` that is the union:

- **Canonical class:** `CellSpecification` absorbs `CellType`'s authoring surface — the
  kwarg-absorbing `__init__`, the `_mapping_property` descriptors + `specs` proxy, the
  `_populate_name` validator, and `id`/`name` being optional — **and keeps its own**
  datasheet structure (`positive_electrode`/`negative_electrode`/`electrolyte`/
  `separator`/`construction`/`coin_hardware`/`specification_comment`).
- **Property field:** unify on `properties` (drop `nominal_properties`); the ~74
  `nominal_properties` sites migrate in Phase 3 (a transient read/write property bridges
  them until then).
- **Extra fields folded in:** `iec_code`, `country_of_origin`, `rechargeable`, `year`,
  `datasheet_revision`, `bibliography` (drop the now-self-referential
  `cell_specification_id`).
- **Two record formats both retained on the class:** `to_record`/`from_record`
  (`product`/`specs`, used by the JSON-LD builder) **and**
  `to_library_record`/`from_library_record` (`specification`/`property`, the datasheet
  library format). Phase 4 decides whether/how these on-disk keys rename — **this is the
  one that touches the live registry** (records carry `product`/`type_id`).
- `kind` discriminator and `default_filename` become the `CellSpecification` values.
- Transient `CellType = CellSpecification` alias added, removed in Phase 5.

### The gating sub-decision (affects the registry contract)

When the on-disk record keys rename in Phase 4 — `product` → ? , `specs` → `properties`,
`type_id` → `cell_spec_id`, the `cell-type` record subdir/profile → `cell-spec` — every
already-published record and the registry DB must migrate in lockstep. **Recommend:**
keep the `product`/`specs`/`type_id` on-disk keys *stable* for now (rename only Python +
API + JSON-LD/docs in Phases 1–3), and schedule the on-disk + registry key rename as a
separate coordinated migration (Phase 4–5), exactly as the `spec/` IRI migration was
done. This avoids a flag-day break of the live registry.

## Decisions needed before executing

1. **Depth:** code-only (Phases 1–3) now, or all the way through on-disk keys + IRI
   token + cross-repo (Phases 4–5)?
2. **Back-compat:** keep `CellType` as a deprecated alias and accept old record keys, or
   hard-break (you noted legacy graphs can be remade — does that extend to record files
   and the registry)?
3. **Target name:** `CellSpecification` everywhere, and what user-facing/API term —
   `cell_specification`, `cell_spec`, or `spec` (the canonical display term is "cell
   spec" per the nomenclature decision)?
4. **Record-key/profile rename:** rename `product`/`type_id`/`cell-type` profile, or
   keep them as stable on-disk tokens while renaming only Python/API?
