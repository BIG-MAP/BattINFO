# Editorial Cell-Spec Workflow

This document describes the BattINFO tooling contract for the shared cell-spec editorial workflow centered on `battinfo-records`.

Use it together with:

- `battinfo-records/docs/editorial-cell-type-workflow.md` in the sibling `battinfo-records` repo (renames to `editorial-cell-spec-workflow.md` when that repo completes its cell-spec migration)
- `battinfo-records/docs/record-lifecycle.md` in the sibling `battinfo-records` repo

## Scope

BattINFO is not the shared editorial source for curated cell-spec content.
BattINFO is the implementation layer that must make that editorial source workable.

For the shared reusable cell-spec corpus:

- `battinfo-records` is the editable source
- BattINFO validates, promotes, and packages records
- `battinfo-registry` publishes them

## Tooling Responsibilities

BattINFO must support these editorial operations reliably:

1. Validate a staging draft before promotion
2. Infer or require an appropriate curated record id
3. Promote a staging draft into curated `record.json`
4. Preserve the existing curated BattINFO identifier when re-promoting the same curated record
5. Build a registry submission package from curated `record.json`
6. Submit that package to the registry without editorial information loss

## Source Of Truth Boundary

BattINFO should assume:

- staging source: `battinfo-records/records/_staging/cell-spec/*.json`
- curated source: `battinfo-records/records/cell-spec/<record-id>/record.json`

BattINFO should not require curators to edit:

- `.battinfo/library-rdf/...`
- `src/battinfo/data/...` generated copies
- registry artifacts
- object storage objects

Generated or packaged outputs remain derived state.

## Expected Editorial Commands

### Validate one staging draft

```powershell
battinfo editorial validate-staging-cell-spec --input <draft.json> --validation-policy strict --format json
```

Expected output contract:

- validation status
- resolved `record_id` when inferable
- `record_id_basis`
- `record_id_hint`
- `requires_record_id`
- normalized canonical record preview
- structured issues

### Promote one staging draft

```powershell
battinfo editorial promote-staging-cell-spec `
  --input <draft.json> `
  --curated-root <records/cell-spec> `
  --record-id <record-id> `
  --validation-policy strict
```

Expected behavior:

- validate before writing
- write only to `records/cell-spec/<record-id>/record.json`
- preserve existing curated `cell_spec.id` and `short_id` if the target already exists

### Publish one curated record

```powershell
battinfo editorial publish-curated-cell-spec `
  --input <record.json> `
  --workspace-id <workspace-id> `
  --publisher-id <publisher-id> `
  --source-version <source-version> `
  --registry-url <registry-url> `
  --api-key <api-key> `
  --validation-policy strict
```

Expected behavior:

- validate curated `record.json`
- infer `source_local_id` from the curated record directory when possible
- generate a registry submission package that preserves the editorial record path in workspace metadata

## Identifier Rules

BattINFO should help with id derivation, but not hide ambiguity.

Expected precedence:

1. year
2. revision
3. evidence date
4. explicit manual record id

If none of those is available and the identity is ambiguous, BattINFO should stop and require an explicit record id.

## Validation Expectations

For editorial workflows, BattINFO should reject:

- malformed staging payloads
- canonical records that fail schema or record validation
- silent loss of provenance fields
- promotion that would overwrite an accepted curated id with a fresh random BattINFO id

BattINFO should surface:

- clear issue lists
- explicit record-id hints
- dry-run previews for promotion

## Re-Promotion Contract

Re-promotion is part of normal editorial maintenance.

If `records/cell-spec/<record-id>/record.json` already exists and still represents the same curated entity, BattINFO must preserve:

- `cell_spec.id`
- derived `short_id`
- canonical BattINFO identity continuity used downstream by the registry and Battery Genome

This is the key safeguard that keeps the editorial source editable after publication.

## Publication Contract

For curated cell-spec publication, BattINFO should treat `record.json` as the publication source.

The generated submission package should contain:

- the canonical curated record in `semantic_payload.battinfo_records.cell_spec`
- editorial workspace metadata pointing back to the curated record path
- workspace, publisher, and source-version metadata for the registry workflow

BattINFO should not treat registry output as a place to be edited later.

## Maintainer Checklist

When changing BattINFO editorial workflows, confirm:

- staging validation still accepts the intended authoring shapes
- ambiguous drafts still require explicit ids
- re-promotion preserves existing curated identifiers
- curated submission generation still works from `record.json`
- registry publication still preserves BattINFO semantic identity when present
- CLI and wrapper docs still match actual command behavior

## Done Condition

BattINFO is doing its job for editorial cell-spec workflows when:

- curators can review and edit records in `battinfo-records`
- promotion is deterministic and reviewable
- re-promotion is identifier-stable
- publication packages are built directly from curated records
- downstream publication remains a repeatable derived step

