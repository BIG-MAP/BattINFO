# Runbook: coordinated `cell_type`/`cell-type` → `cell_spec`/`cell-spec` migration

Status prerequisite: **Phases 1–2 are already done** in BattINFO (the two models are
merged into one `CellSpecification`; the class symbol is renamed; suite green). This
runbook covers the remaining **lockstep token rename** across the on-disk format, the
index/query API, the four repos, and the live registry DB — plus removing the transient
`CellType` alias and `nominal_properties` bridge at the end.

Why lockstep: `cell_type`/`cell_types`/`cell_type_id`/`nominal_properties` and the
`cell-type` kebab tokens are used as the *same strings* on both sides (Python identifiers
**and** on-disk/index/query/registry contract). Renaming one side only leaves a broken
half-state. Renaming **both sides together** makes a near-blanket sweep correct.

---

## 1. Target token map (old → new)

| Surface | Old | New |
|---|---|---|
| Python class | `CellType` (alias) | `CellSpecification` (already canonical) |
| Python ident / var / param | `cell_type` | `cell_spec` |
| Collections / index keys | `cell_types`, `cell_type_count` | `cell_specs`, `cell_spec_count` |
| Field / FK / query kwarg | `cell_type_id`, `cell_type_iri` | `cell_spec_id`, `cell_spec_iri` |
| Property field | `nominal_properties` | `properties` (field already `properties`; remove the bridge) |
| API methods | `query_cell_types`, `load_cell_type`, `publish_cell_type`, `cell_type_to_schema` | `query_cell_specs`, `load_cell_spec`, `publish_cell_spec`, `cell_spec_to_schema` |
| Input/bundle types | `CellTypeInput`, `CellTypeBundle`, `BatteryCellType` | `CellSpecificationInput`, `CellSpecificationBundle`, (drop `BatteryCellType`) |
| Record wrapper key | `"product"` | `"cell_spec"` |
| Record specs key | `"specs"` | `"properties"` |
| Cell-instance FK key | `"type_id"` | `"cell_spec_id"` |
| `kind` discriminator | `"CellType"` | `"CellSpecification"` |
| Compact identifier | `cell-type:{uid}` | `cell-spec:{uid}` |
| Validation profile | `"cell-type"` | `"cell-spec"` |
| Filenames | `cell-type.json`, `cell-type.schema.json`, `cell-type.shapes.ttl`, `cell-type.jsonld`, `cell-type.index.json` | `cell-spec.*` equivalents |
| Directories | `examples/cell-type/`, `data/library/cell-type/`, `.battinfo/library/cell-type/` | `…/cell-spec/` |
| LinkML schema | `schema/cell-type.yaml`, class `CellType` | `schema/cell-spec.yaml`, class `CellSpecification` |

**MUST NOT change** (leave exactly as-is):
- The canonical IRI **path** `https://w3id.org/battinfo/spec/{uid}` — already migrated to
  `spec/`; this rename does NOT touch it.
- The RDF type `BatteryCellSpecification` and all EMMO/`battery:`/`electrochemistry:`
  IRIs (none contain `cell_type`).
- `bundle_generated.py` — **regenerate** from the renamed LinkML schema; never hand-edit.
- Published **Zenodo DOIs / records** — immutable (see §6).

---

## 2. Constraints & risks

- **Immutable published records.** Zenodo deposits carry the old keys (`product`,
  `type_id`, `cell-type:` identifiers) forever. They cannot be edited in place. Two
  options: (a) accept-both reader during a deprecation window, or (b) publish new
  versions. Decision: this is a **hard break**, so the reader does **not** keep
  permanent dual support — but a one-release **import shim** that accepts old keys is
  needed so the registry can re-ingest/migrate existing records once.
- **Live registry DB.** Stored records/columns/indexes use the old tokens; needs a DB
  migration (re-key or re-ingest from re-generated records).
- **Four repos move together.** A registry that speaks `cell_spec` while
  battinfo-records still emits `cell_type` breaks ingestion.
- **Generated artifacts.** `bundle_generated.py`, `records.context.json`, and
  `battinfo.schema.json` are regenerated — review the (large) diffs.

---

## 3. Sequence (one coordinated change)

### Step 0 — freeze & branch
- Announce a publishing freeze (no new registry writes during the window).
- Branch all four repos: `rename/cell-spec`.
- Snapshot the registry DB.

### Step 1 — BattINFO: LinkML schema + regenerate
1. `git mv schema/cell-type.yaml schema/cell-spec.yaml`; rename the LinkML class
   `CellType`→`CellSpecification` and slots (`type_id`→`cell_spec_id`, etc.); update
   `schema/battinfo.yaml` imports.
2. Regenerate: `make gen-context`, `make gen-schema`, and `gen-pydantic --meta full`
   (review `bundle_generated.py`). Sync packaged copies (`assets/` ↔
   `src/battinfo/data/`).

### Step 2 — BattINFO: in-repo token sweep (now safe — both sides rename)
Apply, in order, with **word-boundary** regex over `src/battinfo/**` (excluding
`bundle_generated.py`) **and** `tests/**`, **excluding** `… as Gen*` generated-symbol
imports and EMMO IRIs:
1. `nominal_properties` → `properties`, then **remove** the transient bridge property
   and the legacy-kwarg absorption in `bundle.py`.
2. `cell_type_id`→`cell_spec_id`, `cell_type_iri`→`cell_spec_iri`,
   `cell_type_count`→`cell_spec_count`, `cell_types`→`cell_specs`, `cell_type`→`cell_spec`
   (longest-first to avoid partial overlaps).
3. Kebab/string tokens: `"cell-type"`→`"cell-spec"`, `cell-type:`→`cell-spec:`,
   `/cell-type/`→`/cell-spec/`, and the record keys `"product"`→`"cell_spec"`,
   `"specs"`→`"properties"`, `"type_id"`→`"cell_spec_id"`, `kind "CellType"`→
   `"CellSpecification"`.
4. `git mv` the directories/filenames (`examples/cell-type/`→`examples/cell-spec/`, the
   two `cell-type.schema.json`, `cell-type.shapes.ttl`, library dirs, etc.) and update
   `default_filename`, `EXAMPLES_ROOT` constants, and any path globs.
5. Update `IDENTIFIER_POLICY.md` §16, `from_jsonld` legacy `/cell-type/` matcher (drop),
   and the bundled example/library record files to the new keys.
6. **Migration shim (one release):** in `from_record`/`from_library_record`/index
   readers, accept the **old** keys (`product`/`specs`/`type_id`/`cell-type:`) as
   fallbacks so existing records still load during re-ingest. Mark `# DEPRECATED: remove
   after registry migration`.
7. Remove the transient `CellType = CellSpecification` alias and its `__init__` export;
   rename `CellTypeInput`/`CellTypeBundle`/`BatteryCellType`.
8. Regenerate the LR03 preview; run the full suite + the gold-standard/SHACL validators.

### Step 3 — battinfo-records
- Rename emitters/readers, the `cell-type` profile, record-builder keys, and example
  data to the new tokens. Bump the BattINFO dependency to the renamed version.

### Step 4 — battinfo-registry + DB
- Rename API routes/params/serializers/index fields.
- **DB migration:** either (a) a re-key migration (rename columns/JSON keys
  `cell_type*`→`cell_spec*`, `product`→`cell_spec`, `type_id`→`cell_spec_id`,
  `cell-type:`→`cell-spec:`), or (b) re-ingest every record through the renamed
  battinfo-records pipeline (preferred — uses the migration shim from Step 2.6 to read
  old, writes new). Keep the snapshot for rollback.
- Resolver: ensure `spec/{uid}` still resolves (unchanged); add 301s for any legacy
  `cell-type` profile URLs that existed.

### Step 5 — battery-genome
- Update any `cell_type`/`cell-type` consumers and manifests. (User-facing display is
  already "cell spec" per the 2026-06-13 nomenclature decision.)

### Step 6 — cutover
- Deploy registry + records + battery-genome together; lift the freeze.
- After all live records are confirmed migrated, **remove the Step 2.6 old-key shim**
  (final hard break) in a follow-up release.

---

## 4. Published Zenodo records (immutable)
- They keep old keys forever. The Step 2.6 import shim lets the registry ingest them
  once into the new schema. No edit to the immutable deposit is required; if a
  re-publish is desired, mint a **new version** with the new keys and
  `dcterms:isVersionOf` the old.

## 5. Verification checklist
- `grep -rn '\bcell_type\b\|cell-type\|\btype_id\b\|nominal_properties' src tests` → only
  intended residue (none, or documented shim lines).
- Full suite green in all four repos; gold-standard SHACL + publication validators pass.
- A pre-migration record resolves post-migration (via shim) and re-serializes with new
  keys; round-trip (`from_jsonld`/`from_record`) lossless.
- Registry resolves a sample `spec/{uid}` IRI to JSON-LD with the new keys.
- LR03 preview regenerated and validates.

## 6. Rollback
- Revert the four branches; restore the registry DB snapshot. Because the cutover is a
  single coordinated deploy, rollback is a single coordinated revert. The Step 2.6 shim
  means a half-migrated DB can still be read by the old code during rollback.

## 7. What stays transient until the very end
- `CellType` alias and `nominal_properties` bridge (BattINFO) — removed in Step 2.7.
- The old-key import shim (Step 2.6) — removed in Step 6 after the DB is fully migrated.
