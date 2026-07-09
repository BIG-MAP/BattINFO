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
| `/spec/` | Every reusable *description* — cell, test, material, and component specs |
| `/cell/` | Physical cells (instances) |
| `/test/` | Test executions |
| `/dataset/` | Datasets |
| `/material/`, `/electrode/`, `/separator/`, ... | Material and component instances |
| `/equipment/`, `/channel/` | Physical equipment units and their channels |

The full map is code, not convention: `battinfo.entities.iri_namespace_map()`.

Two more segment rules keep old links alive and new ones honest:

- **Legacy segments are permanent aliases.** Superseded namespaces
  (`/material-spec/`, `/electrode-spec/`, the older `/cell-type/` forms, ...)
  keep resolving forever — anything ever minted stays dereferenceable.
- **Reserved segments** (`id`, `ontology`, `vocab`, `doc`, `context`,
  `resolver`, `twin`, `w3id`, `raw`, `inferred`, `turtle`, `latest`,
  `source`) can never become record namespaces — they are claimed by the
  resolver and ontology infrastructure
  (`battinfo.entities.RESERVED_NAMESPACE_SEGMENTS`).

## Why w3id.org (the PURL layer)

`w3id.org` is the W3C Permanent Identifier Community Group's redirect
service: a community-maintained, permanently-hosted layer of indirection.
The `https://w3id.org/battinfo/...` IRIs redirect to wherever the registry
resolver actually lives today — so records cite an address that outlives any
single server, domain, or hosting decision.

Dereferencing follows linked-data convention: a record IRI names the *thing*
(a cell, a test), not a document, so the resolver answers with a **303
redirect** to a representation chosen by content negotiation — JSON-LD (or
Turtle) for machines, a human-readable landing page for browsers.

Records also never disappear. A withdrawn record gets a **tombstone** — the
resource stays dereferenceable, marked `owl:deprecated` and pointing at its
replacement where one exists — never a 404. An IRI that once resolved always
resolves.

> **Status:** during the soft launch the registry sits behind an access gate,
> so record IRIs may resolve to the platform's sign-in page rather than the
> machine-readable artifact. Public reads for published records arrive as the
> gate comes down — until then, treat dereferencing as not yet reliable for
> harvesters.

## Enforcement

The policy is linted, not aspirational:

- `.tools/quality/lint_identifier_policy.py` checks every canonical record's
  IRIs, UID shapes, and `short_id`s in CI.
- Records carry `id` (the IRI), `short_id`, and `identifier`
  (`<entity-type>:<uid>`) — all derived, never hand-authored. Draft inputs
  omit them; saving canonizes them.
