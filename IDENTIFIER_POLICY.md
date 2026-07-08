# BattINFO Identifier Policy (v1.0)

## 1. Purpose

This document defines the rules for minting, representing, resolving, and managing persistent identifiers in the BattINFO ecosystem.

Identifiers issued under `https://w3id.org/battinfo/` are:

- Globally unique
- Opaque (non-semantic)
- Persistent
- Never reused
- Never reassigned

Identifiers must remain stable for the lifetime of the registry.

## 2. Normative Language

The keywords `MUST`, `MUST NOT`, `SHOULD`, and `MAY` are to be interpreted as requirement levels.

## 3. Canonical Identifier Format

### 3.1 Structure

Canonical entity IRIs use the pattern:

```text
https://w3id.org/battinfo/{entity-type}/{uid}
```

Example:

```text
https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8
```

Where:

- `{entity-type}` is a registered BattINFO entity class (for example `cell`, `test`, `dataset`)
- `{uid}` is a 16-character Base32 token formatted as 4-4-4-4 (with dashes)

### 3.2 Canonical vs Accepted Forms

- Canonical UID textual form is dashed lowercase (`xxxx-xxxx-xxxx-xxxx`).
- Canonical IRI form uses the dashed lowercase UID.
- Undashed form (`xxxxxxxxxxxxxxxx`) MAY be accepted as input for validation and lookup, but MUST NOT be published as canonical IRI form.

### 3.3 UID Alphabet and Length

Each UID:

- Is 16 characters long, excluding dashes
- Uses Crockford Base32 alphabet:

```text
0123456789ABCDEFGHJKMNPQRSTVWXYZ
```

- Is stored and rendered in lowercase
- Is formatted with dashes in 4-4-4-4 grouping for readability

Example:

```text
3m6k-9t2p-7x4h-9nq8
```

Equivalent undashed token:

```text
3m6k9t2p7x4h9nq8
```

### 3.4 Validation Patterns

Dashed UID regex:

```text
^[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}$
```

Undashed UID regex (accepted input only):

```text
^[0-9a-hjkmnp-tv-z]{16}$
```

Canonical IRI regex:

```text
^https://w3id\.org/battinfo/[a-z][a-z0-9-]*/[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}$
```

## 4. Opaqueness Requirement

UIDs:

- MUST NOT encode semantics
- MUST NOT include manufacturer names
- MUST NOT include model names
- MUST NOT include dates
- MUST NOT include chemistry
- MUST NOT include version information

All metadata belongs in RDF properties, not in identifiers.

## 5. Minting Rules

### 5.1 Authority

UID minting is centrally governed by the BattINFO registry authority.

### 5.2 Generation

- UIDs MUST be generated from a cryptographically strong random source where available.
- For offline or spreadsheet workflows, candidate UIDs MUST be checked against the registry before assignment.

### 5.3 Atomic Issuance Workflow

Minting MUST be implemented as an atomic process:

- Generate candidate UID
- Normalize candidate to lowercase dashed form
- Check non-existence in registry
- Reserve UID
- Bind UID to exactly one entity record
- Commit issuance event to an append-only log

A failure before commit MUST release the reservation and retry with a new candidate.

### 5.4 Collision Handling

If a collision is detected:

- Discard candidate UID
- Generate a new UID
- Record collision event in issuance logs
- Never alter existing identifiers

### 5.5 Distributed Data Generation

Distributed data creation is allowed, but canonical UID issuance remains centrally controlled through one of these mechanisms:

- Online minting API
- Pre-allocated signed UID pools issued by registry authority

All minted UIDs MUST be reconciled against the central registry.

## 6. Entity-Type Registry Governance

The set of `{entity-type}` tokens is registry-managed.

- Entity-type values MUST use lowercase ASCII and hyphen-safe tokens.
- New entity types MUST be approved through documented BattINFO governance.
- Once created, an entity-type token MUST NOT be repurposed.

Recommended initial scope:

- `cell`
- `test`
- `dataset`
- `material`
- `model`

## 7. Resolver and Dereferencing Policy

BattINFO IRIs identify resources and MUST resolve via HTTP.

- Resolver implementation SHOULD use 303 redirects for non-information resources.
- `Accept: text/html` SHOULD resolve to a human-readable HTML page.
- `Accept: application/ld+json` SHOULD resolve to JSON-LD.
- `Accept: text/turtle` MAY resolve to Turtle.

Resolver behavior MUST preserve canonical IRI identity and SHOULD redirect non-canonical UID forms to canonical dashed lowercase IRIs.

## 8. Short Human Identifier (ShortID)

To support usability in spreadsheets, figures, and filenames:

- A ShortID MAY be derived from the canonical UID.
- Default ShortID is the first 6 characters of the undashed UID.
- If collisions occur, ShortID length MUST be extended to the minimal unique prefix.

Example:

Canonical UID:

```text
3m6k-9t2p-7x4h-9nq8
```

ShortID:

```text
3m6k9t
```

ShortIDs:

- Are convenience labels only
- Are not canonical identifiers
- May change length as the registry grows
- MUST NOT replace the canonical IRI

## 9. Input Normalization Rules

When manually entered by users, UID input MAY include ambiguous Crockford characters.

- `o` MAY be normalized to `0`
- `i` MAY be normalized to `1`
- `l` MAY be normalized to `1`

After normalization, the result MUST pass UID validation rules before lookup or issuance.

## 10. Immutability and Lifecycle

Once assigned:

- A UID MUST never change
- A UID MUST never be reused
- Entities MAY be deprecated but not reassigned

If an entity is superseded:

- Mark old entity with `owl:deprecated true`
- Link replacement using `dcterms:isReplacedBy` (or registry-approved equivalent)
- Keep original resource dereferenceable
- Do not modify or recycle original identifier

## 11. Versioning

Version information MUST NOT be encoded in the UID.

If versioning is required:

- Use metadata properties
- Use separate versioned resources
- Maintain a stable base entity identifier

## 12. Governance Scope

This policy applies to:

- Cells
- Tests
- Datasets
- Materials
- Models
- Any future BattINFO-registered entity types

## 13. Security and Audit Requirements

- Issuance events MUST be logged in append-only form with timestamp, issuer, entity-type, UID, and status.
- Access to minting authority MUST be authenticated and auditable.
- Bulk imports MUST run duplicate detection before commit.
- Registry backups SHOULD support disaster recovery without identifier reassignment.

## 14. Vocabulary and Alias Policy (ratified 2026-07-08)

BattINFO **never mints or aliases domain IRIs.** Scientific and battery
semantics — quantities, battery classes, measurement concepts — are
identified exclusively by their EMMO IRIs (domain-battery /
domain-electrochemistry). Terms missing from EMMO are added upstream (the
working queue is `docs/internal/ontology-additions-needed.md`); while a term
is missing, the value is preserved in the JSON record and omitted from RDF
with a `semantic.property_unmapped` warning — never bridged with a
BattINFO-minted IRI.

In particular, a "thin human-friendly IRI layer" over EMMO (e.g. a readable
`battinfo:PowerDensity` aliasing an opaque EMMO IRI) is **rejected as
policy**, not deferred: two IRIs per concept fragment graphs for every
consumer that does not run an OWL reasoner, and the accidental instances of
exactly this pattern measurably caused silent data loss (red-team review,
2026-07). The human-friendly layer is **labels and contexts, not
identifiers**:

- authoring: snake_case JSON keys mapped by the records JSON-LD context;
- reading: `skos:prefLabel` annotations emitted alongside every EMMO term in
  exports, plus the generated property & unit reference;
- querying: a generated labels-companion file for SPARQL users.

`battinfo.ttl` is an **application ontology** in the strict sense: (a) the
import/pin manifest for the EMMO modules a release speaks, (b) the small
record-layer residue of genuinely non-domain terms (after re-homing to
DCTERMS/PROV/DCAT/schema.org where standard terms exist), and (c) optionally
the profile constraints (SHACL shapes). Nothing else. The same ruling applies
to sub-namespaces granted under `w3id.org/battinfo/` (e.g. `/twin`): quantity
terms resolve to EMMO or go upstream; only structural terms may be minted
locally, hand-defined.

Reserved namespace segments (never usable as entity types): `id`, `ontology`,
`vocab`, `doc`, `context`, `resolver`, `twin`, `w3id`.

## 15. Design Principles

The BattINFO identifier system is designed to be:

- Infrastructure-grade
- Web-native
- Scalable to hundreds of millions of entities
- Compatible with distributed data generation
- Independent of any single software platform

## 16. Rationale

The 16-character Base32 UID:

- Provides 80 bits of entropy
- Offers extremely low collision probability at BattINFO scale
- Is shorter and cleaner than UUID
- Is readable when grouped as 4-4-4-4
- Avoids semantic fragility
- Aligns with modern infrastructure practice

## 16. Cell-Type Identifier Usability Decision (v1.0)

BattINFO `cell-type` identifiers MUST remain opaque and policy-compliant:

- `https://w3id.org/battinfo/cell/{uid}`

Human-readable model/manufacturer semantics MUST NOT be encoded in the canonical identifier.

To make instantiation practical:

- Users SHOULD resolve `cell-type` IDs via metadata queries (`manufacturer`, `model_name`, `chemistry`, `format`, properties).
- User interfaces SHOULD display metadata labels plus canonical IRI (and optional `short_id`).
- APIs and tooling SHOULD support lookup-first workflows that return a single canonical `cell-type` IRI before instance creation.

Rationale:

- Semantic IDs are brittle under naming changes, aliases, vendor rebranding, and typo correction.
- Opaque IDs preserve long-term persistence and avoid migration risk.
- Metadata-based lookup provides usability without undermining identifier governance.
