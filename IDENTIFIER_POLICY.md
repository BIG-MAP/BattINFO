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

Example (the flagship cell-spec record):

```text
https://w3id.org/battinfo/spec/pge5-wer6-2q82-v9k0
```

Where:

- `{entity-type}` is a registered BattINFO entity class (for example `spec`, `cell`, `test`, `dataset`; see §6.1 for how the segment encodes the spec/instance duality)
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

### 5.1 Where uids are minted

BattINFO mints a record's uid on the machine that writes the record, offline and without asking the registry. Every authoring path mints through one primitive, `battinfo.entities.stable_uid(seed)`: the seed is put in Unicode NFC and hashed with SHA-256, and the first 16 bytes of the digest, read as one big-endian integer, are written as 16 characters of the alphabet in 3.3, dashed 4-4-4-4. The paths that mint this way are the workspace (`battinfo.workspace()`) and the engine behind it, the `create_*` and `save_*` functions, a save of a record without an id, the publication package (`battinfo.publish`, `build_publication_package`) and the folder-based batch path (`battinfo batch init`, `battinfo batch add`, `battinfo batch package`). Section 5.4 names the exceptions. The registry does not issue uids for these records: it takes the IRI a record carries (5.3).

### 5.2 Identity seeds

A seed is built from what identifies the record, its natural key, by the seed builders in `battinfo.entities`, so one identity gives one uid on every path, and saving a record again updates it instead of adding a copy. A cell spec is seeded from its manufacturer, model, format, chemistry and size code; a cell from its spec's IRI, its serial number and batch, and its name when it has no serial number; a test from its cell's IRI, its kind, its protocol (the protocol's IRI when it has one, else its name) and its run (the location of its first data file, else a start time the caller gives, else a name the caller gives, never a title BattINFO generates). Free-text fields go through one normaliser, `entities.seed_text`, which applies Unicode NFC, strips the text and turns each run of whitespace into one space. Cell specs, cells and tests keep the case of the text, and a cell spec's chemistry enters as its key in the chemistry vocabulary; material and electrode specs lower-case their fields. Locators get NFC alone, and hashes and content seeds enter as they are. Display text, such as a test's title, never enters a seed.

On every path that mints through `battinfo.entities`:

- A record keeps an IRI it already has. One pinned by its author, imported, or given by an earlier save is never minted again.
- When records minted in one save get one IRI from their identity fields, each of them is minted again from its content. Two records that already had one IRI are refused.
- A record that carries none of its identity fields is never merged with another: a save without an id refuses it, and a builder that accepts it gives it a random uid.
- `tests/test_golden_iris.py` holds the IRI each path minted for each case when the 0.8.0 seeds were settled, and fails on any move it does not list.

### 5.3 The registry

The registry takes the BattINFO IRI a submission carries as the record's canonical IRI. A submission that carries none, such as a record written by another tool, gets one from the registry's fallback minter, `mint_canonical_id` in battinfo-registry's `publishing/identifiers.py`. It derives an opaque uid of the form in section 3 from the record type, the publisher and the submission's source-local id, so the same publisher submitting the same record again gets the same IRI, under the namespace segment of the record type (6.1).

The first publisher to register an IRI owns it. The registry refuses a submission from another publisher that carries an IRI already registered (conflict `canonical_identity`) and never reassigns or re-mints that IRI; the submitter gives the record an identity of its own or pins another IRI. Lab labels such as `C01` are not scoped to their publisher before 0.9, so two labs can mint one IRI for two cells, and this rule decides which keeps it.

### 5.4 Minting outside the identity contract

The uids below are as permanent as any other once published, but no other path reproduces them, so the same thing authored another way gets another IRI.

- Random uids. `create_component_spec` and `create_component_instance`, with their per-family wrappers for separators, current collectors, electrolytes and housings, and `create_equipment_spec` and `create_equipment` give a record without `uid=` or `id=` a random uid, a new one on every call. On the batch path, a cell without a serial number gets a random uid, recorded in its `battinfo.yaml`, where `battinfo batch package` reads it. Pass a uid derived from the record's natural key, or keep the file that records it. These builders get natural-key seeds in 0.9.
- The interop importers. The BattInfoConverter importer (`battinfo.interop.converter`, which hashes its own seeds with SHA-1, and its component helper `_converter_components._uid`), the solid-state database importer (`solid_state_db._uid_from_seed`), the Discovery importer (`discovery._uid`) and the Battery Data Commons bridge (`battery_data_commons._uid`) seed from their source's own keys. Importing the same source again gives the same IRIs, but their seeds are not those of `battinfo.entities`, so a cell imported from two sources, or imported and also authored in the workspace, gets two IRIs. They are unstable until 0.9, which moves every minting path onto `battinfo.entities`; 5.5 keeps the IRIs they minted findable then.

### 5.5 Changing a seed

Seed rules are a public contract from 0.8.0, the first release on PyPI: a seed change moves IRIs that users have already saved or published.

- A seed change after 0.8.0, such as scoping lab labels to their publisher, or 0.9's move of every minting path onto `battinfo.entities`, MUST keep the IRIs minted under the old seed findable through a legacy-seed lookup. The code keeps the old seed, so that the record an old IRI names can still be found from its fields, as `_LEGACY_PARAMETER_FILE_SEED` (`api/_parameters.py`) does for parameter files minted before 2026-10-11, and as `entities.keep_legacy_uid` and `Workspace._keep_legacy_test_iris` do for cell specs and tests saved before 0.8.0, whose saves reuse the IRI already on disk.
- A 0.8.x patch release MUST keep every IRI already on disk or published. A fix may change what a new record mints, never the IRI of a record that exists.
- Every move is listed in the changelog, and in `MOVED` in `tests/test_golden_iris.py` with its reason.

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
- `equipment`
- `channel`

### 6.1 Namespace scheme (ratified 2026-07-08)

The namespace segment encodes exactly ONE distinction — the spec/instance
duality at the heart of the data model — and nothing else:

- **`spec/` holds every reusable description**: cell specs, test specs,
  material specs, and all component specs (electrode, separator, electrolyte,
  current-collector, housing), present and future. Descriptions are one kind
  of thing; their differences are expressed by `@type`, not by the IRI.
- **Each kind of concrete thing or event gets a short generic noun**: `cell/`, `test/`, `dataset/`, `material/`, `electrode/`, `separator/`, `electrolyte/`, `current-collector/`, `housing/`, `organization/`, `equipment/`, `channel/` (and `twin/` for registered twin instances). Instance identifiers are the ones humans handle physically, so the noun is a deliberate affordance. `dataset/` is the noun for concrete data artifacts and is shared by two record types, dataset records and parameter sets (6.3), which broadens the noun rather than repurposing it.

Rationale: type names have churned three times (cell-type→cell-spec, test-protocol→test-spec, coin_hardware→housing) and the generic `spec/` segment survived every rename untouched; per-type spec segments demonstrably do not. Tooling MUST NOT infer a record's type from its namespace segment. `spec/` is shared by design, and so is `dataset/` (dataset records and parameter sets); the type lives in the record and its `@type`.

Superseded segments (`material-spec/`, `electrode-spec/`, `separator-spec/`,
`electrolyte-spec/`, `current-collector-spec/`, `housing-spec/`, and the
older `cell-type/`, `cell_type/`, `test_protocol/` forms) remain permanent
resolver aliases — anything ever minted resolves forever.

Reserved segments (never usable as entity namespaces): `id`, `ontology`,
`vocab`, `doc`, `context`, `resolver`, `twin`, `w3id`, `raw`, `inferred`,
`turtle`, `latest`, `source`. The last five are claimed by the ontology
block in the upstream w3id.org `.htaccess`, so requests to those paths can
never reach the record resolver.

### 6.2 Equipment and channels (ratified 2026-07-08)

Equipment specs (the model, e.g. "Neware BTS-4000") are descriptions and
mint under `spec/`; physical units mint under `equipment/`. Equipment
category (cycler, glovebox, coater, ...) is data (`equipment_class`,
mapped to EMMO classes upstream), never a namespace segment and never a
battinfo-minted class (SS14).

Channels are flat instance IRIs under `channel/` — containment is never
encoded in the address (channel boards get re-homed between units; the IRI
must survive that), so the parent link `equipment_id` lives in the record
body. Channel UIDs mint deterministically from `(equipment uid, index)`, so
registering the same channel twice is idempotent. Channels are
instance-only: there is no channel-spec kind — per-channel ratings are
properties of the equipment spec.

### 6.3 Parameter sets (2026-08-17, revised 2026-10-11)

A parameter set is one source's parameter claims, in one of two flavours: a claim batch (claims about one target) or a parameter file (one BPX file, see the amendment below). Both are datasets in the sense of 6.1, not descriptions. Nothing is ever an instance of a parameter set: it is one particular piece of data from one source, produced by one calibration or extraction. Both flavours therefore mint under `dataset/` (ruling 2026-10-11), which they share with dataset records, and both emit as `schema:Dataset`; tooling reads the record to tell a parameter set from a dataset record. A parameter set is not a spec+instance pair, and its target link (`material_kind`, `material_spec_id` or `cell_spec_id`, or the cell a file describes) lives in the record body, never in the address. Parameter *keys* ("solid_diffusivity", ...) are vocabulary entries (`data/vocab/parameters.json`), never namespace segments and never battinfo-minted classes (SS14).

A claim batch's uid mints deterministically from its target, scope, electrode polarity and name: `stable_uid("parameter-claims:<target>:<scope>[:<electrode_polarity>]:<name>")`, where the name is normalised as every free-text identity field is (stripped, each run of whitespace one space, Unicode NFC) and lowercased, and the polarity appears only when the batch names one (electrode scope). Re-importing the same source, the same paper, lands on the existing record instead of duplicating it. An author may pin a claim batch's uid or IRI instead of the derived one; a pinned IRI must be a `dataset/` IRI. A parameter file's uid comes from its parameters alone (amendment below).

**Records minted before 2026-10-11.** Parameter sets used to mint under `spec/`: a claim batch from the seed `parameter-set:<target>:<scope>[:<electrode_polarity>]:<name>`, a parameter file from `parameter-set-file:<parameters_sha256>`. They are not moved. Each is republished as a new `dataset/` record, minted from the seeds of this section, whose `supersedes` names the old `spec/` IRI. The registry marks the old record superseded (section 10); its IRI stays dereferenceable and points at its replacement. `supersedes` is open to both flavours and takes a `dataset/` IRI or, for a record minted before 2026-10-11, a `spec/` one. Only the publisher of the old record may supersede it: the registry refuses a `supersedes` from any other publisher.

A legacy `spec/` parameter-set IRI is accepted read-only (ruling 2026-10-12). The published schema keeps validating such a record, so the records already published under it stay valid (section 11.1), and tooling still finds a record by its `spec/` IRI; validators warn that it is legacy and name its replacement, and the publisher policy refuses it, so nothing is published or minted under `spec/` again. A uid is never reused across namespaces (section 10): a `dataset/` record never takes the uid of a `spec/` record, and a record whose uid is that of the record it supersedes, or that supersedes itself, is invalid under every policy.

**Amendment, 2026-10-07, revised 2026-10-11: a parameter file is one record, addressed by its parameters.** A parameter file (a BPX file today) becomes exactly one parameter-set record, holding every value of the file grouped by part. Its uid is `stable_uid("parameter-file:<parameters_sha256>")`, minted under `dataset/`, where `parameters_sha256` is the SHA-256 of the file's canonical JSON; there are no per-part or per-block records and no other seeds. Canonical means RFC 8785, the JSON Canonicalization Scheme: numbers written as ECMAScript writes doubles, object keys sorted by UTF-16 code units, minimal string escaping, no whitespace, UTF-8. Names, the cell the file is linked to and the materials its parts are mapped to do not enter the seed. The IRI therefore names the canonical parameters, not the bytes of one copy. The same parameters in any formatting share an IRI, whether a copy is re-indented, has CRLF line endings, orders its keys differently or spells `1.0` as `1`, and any changed value mints a new IRI; a corrected file is a new record that supersedes the old. A file holding a value JSON cannot express (NaN, an infinity) gets no IRI. The reason is that a solver can be handed the record's IRI, and the parameters behind it must never change. The record stores the fingerprint as `parameters_sha256`, so anyone holding a file can check it against the IRI, and it carries the file itself under `distributions` (exactly one source, each entry with its sha256), so the IRI resolves to a file with exactly those parameters. The registry keeps the first copy of the file it is given; a later copy with the same parameters resolves to that record and its stored bytes. The first publisher to submit a file owns its IRI: a submission of the same parameters by another publisher is refused, and the owner's later versions of the record keep the same source file. The registry checks every file itself, downloading it and recomputing its checksum and fingerprint, and a validator refuses a record whose `id` is not the one its `parameters_sha256` gives, under every policy. Which cell or material a curator maps the file to is description: it can be corrected in a new version of the record without touching the identity. A corrected file has other parameters, so it is a new record with a new IRI that names the old record in `supersedes`; only the publisher of the old record may do that, the registry then marks the old record superseded (section 10), and the old IRI keeps resolving to its file. Two files whose values differ only beyond double precision (`0.1000000000000000001` and `0.1`) hold the same JSON numbers, so they share an IRI.

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

### 11.1 Served-Artifact Immutability

The shared documents served under `https://w3id.org/battinfo/` — the records
JSON-LD context and the JSON Schemas — are versioned resources and are
**immutable once published**:

- `https://w3id.org/battinfo/context/records/v1.json`
- `https://w3id.org/battinfo/schema/*`

Once a version of these artifacts is published, its content MUST NOT change in
place. The 373 terms defined by the `v1` records context, and each published
schema, are frozen: consumers may cache them indefinitely and rely on their
meaning being stable for the lifetime of that URL.

A change that alters, removes, or repurposes any term — anything that could
change how an already-published record expands or validates — MUST be shipped
as a **new version at a new URL** (`context/records/v2.json`,
`schema/.../v2/...`), never by editing `v1` in place. Purely additive,
backward-compatible clarifications MAY be made within a version only when they
cannot change the interpretation of any record already published against it;
when in doubt, mint a new version. Existing versioned URLs remain served and
unchanged so records that reference them keep resolving to the exact document
they were authored against.

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
is missing, the value is preserved in the JSON record and in RDF, where its
quantity node carries only its value-basis class (for example
`ConventionalProperty`) and the record key as `skos:prefLabel`, with a
`semantic.property_unmapped` warning — never bridged with a BattINFO-minted
IRI. (Amended 2026-10-11: such values were previously omitted from RDF in
this text, while the emitter gave them generated `battinfo:` class names.)

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
`vocab`, `doc`, `context`, `resolver`, `twin`, `w3id`, `raw`, `inferred`,
`turtle`, `latest`, `source`.

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

## 16. Cell-Spec Identifier Usability Decision (v1.0)

BattINFO cell-spec identifiers MUST remain opaque and policy-compliant:

- `https://w3id.org/battinfo/spec/{uid}` (a cell spec is a reusable description; per §6.1 every spec mints under the shared `spec/` segment, e.g. the flagship `https://w3id.org/battinfo/spec/pge5-wer6-2q82-v9k0`)

Human-readable model/manufacturer semantics MUST NOT be encoded in the canonical identifier.

To make instantiation practical:

- Users SHOULD resolve cell-spec IDs via metadata queries (`manufacturer`, `model_name`, `chemistry`, `format`, properties).
- User interfaces SHOULD display metadata labels plus canonical IRI (and optional `short_id`).
- APIs and tooling SHOULD support lookup-first workflows that return a single canonical cell-spec IRI before instance creation.

Rationale:

- Semantic IDs are brittle under naming changes, aliases, vendor rebranding, and typo correction.
- Opaque IDs preserve long-term persistence and avoid migration risk.
- Metadata-based lookup provides usability without undermining identifier governance.
