# Identifiers & PURLs

Every BattINFO record has one canonical identifier — an IRI of the form:

```text
https://w3id.org/battinfo/<namespace>/<uid>
└──────┬──────┘ └──┬───┘ └───┬────┘ └─┬─┘
   PURL host     project   record     16-char UID
                           namespace  (Crockford Base32)
```

Example: `https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5`

## The three promises

- **Opaque** — the IRI carries no embedded meaning: no manufacturer names, no
  dates, no chemistry codes. Anything meaningful would eventually be wrong
  (products get renamed, records get corrected), and identifiers must outlive
  every such change.
- **Stable** — once minted, an IRI never changes and is never reused. It is
  safe to cite in a paper, store in a database, or print on a label.
- **Deterministic where it matters** — the workspace mints IRIs from each
  record's identity, so re-saving the same records is an update, never a
  duplicate (`tests/test_idempotent_minting.py` guards this). Standalone
  material specs are minted from the material name, so the same material
  lifts to the same spec IRI across cells.

## The UID

The 16-character UID uses the **Crockford Base32 alphabet**
(`0-9 a-h j k m n p-t v-z`) — no `i`, `l`, `o`, or `u`, so a UID survives
being read aloud, handwritten on a cell wrapper, or retyped from a photo. It
is displayed in four dash-separated groups (`7d9k-2m4p-8t3x-6nq5`); the first
six characters form the `short_id` used in filenames and for matching data
files to cells (`ws.add("test", datasets="glob")`).

## Namespaces

| Namespace | Record type(s) |
|---|---|
| `/spec/` | Cell specs **and** test specs — the reusable *descriptions* |
| `/cell/` | Physical cells (instances) |
| `/test/` | Test executions |
| `/dataset/` | Datasets |
| `/material-spec/`, `/material/` | Standalone materials, spec and instance |
| `/electrode-spec/`, `/separator-spec/`, `/electrolyte-spec/`, ... | Component specs (and their instance namespaces) |

The full map is code, not convention: `battinfo.entities.iri_namespace_map()`.

## Why w3id.org (the PURL layer)

`w3id.org` is the W3C Permanent Identifier Community Group's redirect
service: a community-maintained, permanently-hosted layer of indirection.
The `https://w3id.org/battinfo/...` IRIs redirect to wherever the resolver
actually lives today — so records cite an address that outlives any single
server, domain, or hosting decision. Dereferencing a record IRI serves its
resolver artifact (`index.html` for humans, `index.jsonld` / `index.json`
for machines — content-negotiated), produced by `battinfo.api.publish_record`.

## Enforcement

The policy is linted, not aspirational:

- `.tools/quality/lint_identifier_policy.py` checks every canonical record's
  IRIs, UID shapes, and `short_id`s in CI.
- Records carry `id` (the IRI), `short_id`, and `identifier`
  (`<entity-type>:<uid>`) — all derived, never hand-authored. Draft inputs
  omit them; saving canonizes them.
