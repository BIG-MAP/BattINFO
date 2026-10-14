# Identifiers & PURLs

Every BattINFO record has one canonical identifier — an IRI of the form:

```text
https://w3id.org/battinfo/<namespace>/<uid>
└──────┬──────┘ └──┬───┘ └───┬────┘ └─┬─┘
   PURL host     project   record     16-char UID
                           namespace  (Crockford Base32)
```

Example: `https://w3id.org/battinfo/spec/pge5-wer6-2q82-v9k0`

## The three promises

- **Opaque** — the IRI carries no embedded meaning: no manufacturer names, no
  dates, no chemistry codes. Anything meaningful would eventually be wrong
  (products get renamed, records get corrected), and identifiers must outlive
  every such change.
- **Stable** — once minted, an IRI never changes and is never reused. It is
  safe to cite in a paper, store in a database, or print on a label.
- **Deterministic where it matters** — BattINFO mints an IRI on your machine, when the record is saved, from the record's identity, so re-saving the same records is an update, never a duplicate (`tests/test_idempotent_minting.py` guards this). The registry mints one only for a submission that carries none. Free text in an identity (a manufacturer, model, name, serial number or batch) is normalised first: surrounding and repeated whitespace, a no-break space and a decomposed accent do not change an IRI, but case does. A cell spec's chemistry counts by its vocabulary key, so `Li-ion` and `li-ion` give one cell spec. A material spec lifted out of a cell spec is minted from its manufacturer, product, grade and kind, as `ws.add("material_spec", ...)` mints it, so the same material lifts to the same spec IRI across cells, and one material from two suppliers to two. A test names one run: it is minted from its cell, its kind, its protocol (the protocol's IRI whenever it has one) and the location of its first data file, or a start time you pass for a test without data (`ws.add("test", ..., started_at=...)`), or else the name you give it. A title BattINFO generates (`C01 cycling`) never enters, so renaming a test with data or a start time keeps its IRI, and a second run of one kind on one cell, with its own data, start time or name, gets its own. A record keeps an IRI it already has: one pinned (`iris=`, `iri=`, an `id` in a draft), imported with `ws.import_()` or given by an earlier `ws.save()`, in this session or an earlier one in the same folder, is never minted again. (A record saved by an earlier session is recognised by its content, so pin one you edit in the same save in which a colliding record joins.) When another record's identity fields mint the same IRI, that newcomer is minted from its content instead, and two records that already had one IRI are refused. A few paths mint outside this until 0.9: the component and equipment builders (`create_component_spec`, `create_equipment` and the like) give a record without `uid=` or `id=` a random IRI, `battinfo batch init` gives a cell without a serial number a random IRI recorded in its `battinfo.yaml`, and the interop importers mint from their own seeds. The [known limitations](scope.md#identifiers) list them, with what to do on each.

## The UID

The 16-character UID uses the **Crockford Base32 alphabet**
(`0-9 a-h j k m n p-t v-z`) — no `i`, `l`, `o`, or `u`, so a UID survives
being read aloud, handwritten on a cell wrapper, or retyped from a photo. It
is displayed in four dash-separated groups (`pge5-wer6-2q82-v9k0`); the first
six characters form the `short_id` used in filenames and for matching data
files to cells (`ws.add("test", datasets="glob")`).

## Namespaces

| Namespace | Record type(s) |
|---|---|
| `/spec/` | Every reusable *description* — cell, test, material, and component specs |
| `/cell/` | Physical cells (instances) |
| `/test/` | Test executions |
| `/dataset/` | Datasets and parameter sets (both are data from one source) |
| `/material/`, `/electrode/`, `/separator/`, ... | Material and component instances |
| `/equipment/`, `/channel/` | Physical equipment units and their channels |

The full map is code, not convention: `battinfo.entities.iri_namespace_map()`.

A namespace can hold more than one record type: `/spec/` holds every kind of description, and `/dataset/` holds dataset records and parameter sets. Tooling never infers a record's type from the segment; the type lives in the record.

More segment rules keep old links alive and new ones honest:

- **Legacy segments are permanent aliases.** Superseded namespaces
  (`/material-spec/`, `/electrode-spec/`, the older `/cell-type/` forms, ...)
  keep resolving forever — anything ever minted stays dereferenceable.
- **Parameter sets minted under `/spec/` before 2026-10-11 keep their IRIs.** Each resolves as a superseded record that points at its replacement, a new `/dataset/` record with a uid of its own. A uid is never reused under another namespace.
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

> **Status:** the resolver and content negotiation are live for published
> records — a request with `Accept: application/ld+json` (or `text/turtle`)
> returns the machine-readable record with no login. In a *browser*, the
> human landing page sits behind the platform's sign-in gate during the soft
> launch, so a scanned label may show a sign-in prompt while a harvester gets
> data from the same IRI. Records that were never published to the registry
> return `404 Record not found`.

## Enforcement

The policy is linted, not aspirational:

- `.tools/quality/lint_identifier_policy.py` checks every canonical record's
  IRIs, UID shapes, and `short_id`s in CI.
- Records carry `id` (the IRI), `short_id`, and `identifier`
  (`<entity-type>:<uid>`) — all derived, never hand-authored. Draft inputs
  omit them; saving canonizes them.

## Handles and titles are not identifiers

A record may also carry a `handle`, a short readable slug such as `flores-ocv/graphite-aq-1-063b77-cell` that is unique within one registry workspace, and a `name`, its title. Both are display text: they can be corrected without touching the IRI, and nothing should be derived from them. [Name your records](howto/name-your-records.md) shows how to build them and how to pin an IRI when a title changes.
