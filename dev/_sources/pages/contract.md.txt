# The infrastructure contract

This page is for the person deciding whether to *build on* BattINFO: what the
guarantees are, where they are enforced, and what breaks loudly instead of
silently. Everything here is backed by tests or CI gates in this repo or the
registry.

## Records are versioned

Every canonical record carries `schema_version` (currently `0.2.0`, a single
module-level constant). The registry's publish gate validates against pinned,
vendored copies of the same schemas and **flags unknown versions** rather than
guessing. Changes to record shape are CHANGELOG entries, never silent.

Three versions exist in the wild, and consumers should accept all three:

| `schema_version` | What it means |
|---|---|
| `0.1.0` | The original record shape (most of the example corpus still carries it) |
| `1.0.0` | An interim stamp used briefly before the numbering was consolidated |
| `0.2.0` | The current shape: snake_case keys throughout, `properties` (ex `specs`), organizations use `same_as` |

The differences are additive/renaming only — no field changed meaning. New
records always stamp the current version; old records validate against the
same schemas (the keys they use are all still accepted).

## Records are attributable

Every emitted record's provenance block carries `battinfo_version` — the
library build that wrote it. A malformed record found in a corpus two years
from now is forensically traceable to its producer. Explicitly set values are
preserved, so re-serialising another build's record never falsifies origin.

## Identifiers are deterministic

Records saved without an explicit `uid` mint their IRI from the record's
natural identity key (for a cell spec: manufacturer :: model :: format ::
chemistry :: size code), using the same seeds in every authoring path.
Consequences you can rely on:

- re-running an identical ingest is a **no-op**, never a duplicate corpus;
- the workspace and `save_*` paths mint **identical IRIs** for identical
  identities (tested);
- records with no distinguishing identity still mint randomly — two anonymous
  but physically distinct cells never silently merge.

Governance of the IRI space itself is written down in the
[identifier policy](https://github.com/BIG-MAP/BattINFO/blob/main/IDENTIFIER_POLICY.md).

## One schema contract, three consumers

The canonical JSON Schemas in `src/battinfo/data/schemas/` are enforced in
three places, each with a CI gate against drift:

| Consumer | Mechanism | Drift gate |
|---|---|---|
| `battinfo validate` / `save_*` | jsonschema at save/publish | the test suite |
| Registry publish gate | vendored schemas, fails closed on unknown record types | `schema-drift` CI job pinned to a BattINFO commit |
| [battinfo.org/validate](https://battinfo.org/validate) | vendored schemas compiled with Ajv | web CI: sync check + 103-record agreement corpus |

The same record gets the same structural verdict in all three.

## Bulk operations are safe to automate

- `bulk_save_session` ingests ~400 records/s; a 10k-record ingest takes under
  half a minute and is re-runnable without duplicates.
- `ws.submit()` journals every outcome and resumes interrupted batches,
  re-sending only what is missing; transient registry failures retry with
  exponential backoff.
- Submission content conflicts return a **structured 409** naming the existing
  record, not a bare string.

## Deprecations are announced

Public API removals go through one release of `DeprecationWarning` naming the
replacement — never straight to `ImportError`. The policy lives in
[CONTRIBUTING](https://github.com/BIG-MAP/BattINFO/blob/main/CONTRIBUTING.md);
expiring shims are swept at each release.
