# BattINFO Identifier Policy (v1.1)

Version 1.1, 2026-10-26, takes in the IRI ruling of 22 October 2026 (issue #476). One w3id name holds the standard at its root and everything else in branches (1, 7). New records carry a publisher prefix (3.1, 5.6, 6.4). Shared things and prefix holders' vocabularies have rules of their own (6.5, 6.6), and versions have addresses (11). The amendment that version 1.0 carried as 5.6 is written into 5.1 to 5.6, and the second section 16 is numbered 17. No IRI minted under version 1.0 changes.

## 1. Purpose

This document defines the rules for minting, representing, resolving, and managing persistent identifiers in the BattINFO ecosystem.

Identifiers issued under `https://w3id.org/battinfo/`, called BattINFO IDs, are:

- Globally unique
- Opaque (non-semantic)
- Persistent
- Never reused
- Never reassigned

Identifiers must remain stable for the lifetime of the registry.

`https://w3id.org/battinfo` is the only w3id name BattINFO uses. Every address under it sits in one branch:

- The root holds the standard: the BattINFO ontology with its formats and version paths, the JSON-LD contexts under `context/`, the JSON Schemas under `schema/`, and the 57 terms of the records vocabulary.
- Under `def/{prefix}/` a prefix holder (6.4) defines its own terms (6.6).
- Records are `id/{prefix}/{segment}/{uid}` (3.1).
- A shared thing, such as a product model or a maker, is `id/{uid}`, and only the registry mints one (6.5).

Records of the old form, `{segment}/{uid}`, also sit at the root. Every record minted before 0.8.0 has that form and keeps resolving there. Section 7.1 lists every case an address can fall into.

The BattINFO ontology's IRI is `https://w3id.org/battinfo#`, as `battinfo.ttl` declares. Its document is served at the root, `https://w3id.org/battinfo/`, and `https://w3id.org/battinfo` redirects there. The records vocabulary has an ontology IRI of its own, `https://w3id.org/battinfo/vocab/records`.

## 2. Normative Language

The keywords `MUST`, `MUST NOT`, `SHOULD`, and `MAY` are to be interpreted as requirement levels.

## 3. Canonical Identifier Format

### 3.1 Structure

A record IRI has one of two forms. The prefixed form is

```text
https://w3id.org/battinfo/id/{prefix}/{segment}/{uid}
```

and the old form is

```text
https://w3id.org/battinfo/{segment}/{uid}
```

Examples (the first uid is illustrative; the second IRI is the flagship cell-spec record):

```text
https://w3id.org/battinfo/id/1001/cell/b6yn-0sxe-t2qk-9mjv
https://w3id.org/battinfo/spec/pge5-wer6-2q82-v9k0
```

Where:

- `{prefix}` is a publisher prefix, a number of four or more digits that does not start with 0 (6.4)
- `{segment}` is a registered record segment (for example `spec`, `cell`, `test`, `dataset`; see 6.1 for how the segment encodes the spec/instance duality), never a reserved segment
- `{uid}` is a 16-character Base32 token formatted as 4-4-4-4 (with dashes)

From 0.8.0 new records mint in the prefixed form. Every record minted before has the old form and keeps it, and a workspace or folder created before the switch goes on minting the old form (5.6). A record has one canonical IRI. Under prefix 1001 the old form and the prefixed form of one segment and uid name the same record, and the form the registry holds is the canonical one (5.3). Under any other prefix the same uid names a different record.

A shared thing has neither prefix nor segment: `https://w3id.org/battinfo/id/{uid}` (6.5).

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

Record IRI regex, either form:

```text
^https://w3id\.org/battinfo/(?:id/[1-9][0-9]{3,}/)?[a-z][a-z0-9-]*/[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}$
```

The segment must also not be one of the reserved segments of 6.1, which the expression does not check.

Shared-thing IRI regex:

```text
^https://w3id\.org/battinfo/id/[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}$
```

`battinfo.namespace` builds and reads both forms, and the IRI patterns of the v1 JSON Schemas are generated from it by `scripts/sync_schema_iri_patterns.py`. Each such pattern names the segments of the record type it accepts. A field that refers to an organization, a cell spec or a material accepts a shared thing as well (11.1).

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

BattINFO mints a record's uid on the machine that writes the record, offline and without asking the registry. Every authoring path mints through one primitive, `battinfo.entities.stable_uid(seed)`: the seed is put in Unicode NFC and hashed with SHA-256, and the first 16 bytes of the digest, read as one big-endian integer, are written as 16 characters of the alphabet in 3.3, dashed 4-4-4-4. The paths that mint this way are the workspace (`battinfo.workspace()`) and the engine behind it, the `create_*` and `save_*` functions, a save of a record without an id, the publication package (`battinfo.publish`, `build_publication_package`) and the folder-based batch path (`battinfo batch init`, `battinfo batch add`, `battinfo batch package`). Section 5.4 names the exceptions. The registry does not issue uids for these records: it takes the IRI a record carries (5.3). A uid never depends on the base a record mints under, so one identity gives one uid in either form of 3.1; section 5.6 says which base a record takes.

### 5.2 Identity seeds

A seed is built from what identifies the record, its natural key, by the seed builders in `battinfo.entities`, so one identity gives one uid on every path that sees that identity (5.4 names the paths that see less of it), and saving a record again updates it instead of adding a copy. A cell spec is seeded from its manufacturer, model, format, chemistry and size code; a cell from its spec's IRI, its serial number and batch, and its name when it has no serial number; a test from its cell's IRI, its kind, its protocol (the protocol's IRI when it has one, else its name) and its run (the location of its first data file, else a start time the caller gives, else a name the caller gives, never a title BattINFO generates). Free-text fields go through one normaliser, `entities.seed_text`, which applies Unicode NFC, strips the text and turns each run of whitespace into one space. Cell specs, cells and tests keep the case of the text, and a cell spec's chemistry enters as its key in the chemistry vocabulary as it stood in 0.8.0 (5.5); material and electrode specs lower-case their fields. Locators get NFC alone, and hashes and content seeds enter as they are. Some seeds take a name: a cell without a serial number is seeded from its name, a test protocol from its name and version, and a dataset from its title, which `ws.add("test")` builds from the test's name, so renaming a test moves the IRIs of its datasets (pin them with `dataset_iris=`). A test's own title enters only when the caller gave it to a test with no data file and no start time, and a title BattINFO generates (`C01 cycling`) never does.

A seed that names another record, as a cell names its spec or a test its cell and protocol, takes that record's IRI in the old form, whichever form the record has (`entities.seed_iri`). A cell of a spec in the `/id/1001/` form therefore gets the uid it would get from the same spec in the old form, and adopting either form of the spec never moves the cell.

On every path that mints through `battinfo.entities`:

- A record keeps an IRI it already has. One pinned by its author, imported, or given by an earlier save, in the same session or an earlier one that saved to the same folder, is never minted again. A record saved by an earlier session is recognised by its content: a save of it would write the saved record again.
- When records minted in one save get one IRI from their identity fields, each of them is minted again from its content, except the one recognised as the record already saved under that IRI. Two records that already had one IRI are refused.
- A record that carries none of its identity fields is never merged with another: a save without an id refuses it, and a builder that accepts it gives it a random uid.
- `tests/test_golden_iris.py` holds the IRI each path minted for each case when the 0.8.0 seeds were settled, and fails on any move it does not list.

### 5.3 The registry

The Battery Genome registry holds prefix 1001 (6.4). It takes the BattINFO IRI a submission carries as the record's canonical IRI. A submission that carries none, such as a record written by another tool, gets one from the registry's fallback minter, `mint_canonical_id` in battinfo-registry's `publishing/identifiers.py`. It derives an opaque uid of the form in section 3 from the record type, the publisher and the submission's source-local id, so the same publisher submitting the same record again gets the same IRI, under `/id/1001/` and the segment of the record type (6.1).

The registry accepts record IRIs in the old form and under 1001. It refuses a submission whose IRI carries any other prefix.

Under 1001 the old form and the prefixed form of one segment and uid are one record, for lookup and for ownership. The first publisher to register an IRI owns it in both forms. The registry refuses a submission from another publisher that carries an IRI already registered, in either form (conflict `canonical_identity`), and never reassigns or re-mints that IRI; the submitter gives the record an identity of its own or pins another IRI. Lab labels such as `C01` are not scoped to their publisher before 0.9, so two labs can mint one IRI for two cells, and this rule decides which keeps it.

BattINFO looks a record up before it submits or deposits it and adopts the form the registry already holds (5.6), so a record published in the old form is not sent again under `/id/1001/`.

### 5.4 Minting outside the identity contract

The uids below are as permanent as any other once published, but no other path reproduces them, so the same thing authored another way gets another IRI.

- Random uids. `create_component_spec` and `create_component_instance`, with their per-family wrappers for separators, current collectors, electrolytes and housings, and `create_equipment_spec` and `create_equipment` give a record without `uid=` or `id=` a random uid, a new one on every call. On the batch path, a cell without a serial number gets a random uid, recorded in its `battinfo.yaml`, where `battinfo batch package` reads it. Pass a uid derived from the record's natural key, or keep the file that records it. These builders get natural-key seeds in 0.9.
- The interop importers. The BattInfoConverter importer (`battinfo.interop.converter`, which hashes its own seeds with SHA-1, and its component helper `_converter_components._uid`), the solid-state database importer (`solid_state_db._uid_from_seed`), the Discovery importer (`discovery._uid`) and the Battery Data Commons bridge (`battery_data_commons._uid`) seed from their source's own keys. Importing the same source again gives the same IRIs, but their seeds are not those of `battinfo.entities`, so a cell imported from two sources, or imported and also authored in the workspace, gets two IRIs. They are unstable until 0.9, which moves every minting path onto `battinfo.entities`; 5.5 keeps the IRIs they minted findable then.
- Paths that see less of a record. They mint through `battinfo.entities`, but from fewer of the record's identity fields, so the same record gets another IRI there than in the workspace. `save_test()` and a save of a test without an id never see a data file, so a test with data files is seeded there from its start time or name instead of its first file; they also know a cell's labels only from a `Cell` object, so a title such as `C01 cycling` given there counts as the caller's name. A save of a dataset without an id leaves its cell and test out of its seed, because its `about` list does not say which are its own, so only a dataset with neither, such as a collection, gets the IRI `save_dataset` gives it. The publication package and `battinfo batch package` seed a dataset from its folder and title, not its file, and the publication package takes the dataset folder as the run of a test with data; `battinfo batch package` takes a raw file's path in the cell folder as the run, which matches the workspace only when the workspace's data file has the same path in the workspace folder. `battinfo batch init --batch-id` seeds a cell from its serial number and its batch, and `ws.add("cell")` takes no batch, so the two agree only for a cell without a batch id. Pin the IRI on the path that differs (`iri=`, `dataset_iris=`, `id=` or `--iris`).

### 5.5 Changing a seed

Seed rules are a public contract from 0.8.0, the first release on PyPI: a seed change moves IRIs that users have already saved or published.

- A seed change after 0.8.0, such as scoping lab labels to their publisher, or 0.9's move of every minting path onto `battinfo.entities`, MUST keep the IRIs minted under the old seed findable through a legacy-seed lookup. The code keeps the old seed, so that the record an old IRI names can still be found from its fields, as `_LEGACY_PARAMETER_FILE_SEED` (`api/_parameters.py`) does for parameter files minted before 2026-10-11, and as `entities.keep_legacy_uid` and `Workspace._hold_saved_iris` do for cell specs and tests saved before 0.8.0, whose saves reuse the IRI already on disk. That includes a record that collided with a sibling then and was minted from its content, and a record saved on its own then that a sibling with the same old seed joins later: the record whose save would write the saved one again keeps its IRI.
- The chemistry part of a cell-spec seed reads the chemistry vocabulary as it stood in 0.8.0, frozen in `entities.CHEMISTRY_SEED_KEYS`, never the vendored vocabulary, which grows when the ontology mappings are vendored again. Adding a key or an alias to that table, or pointing an alias at another key, is a seed change.
- A 0.8.x patch release MUST keep every IRI already on disk or published. A fix may change what a new record mints, never the IRI of a record that exists.
- A change of base is not a seed change. Minting under `/id/1001/` instead of the root moves no uid (5.6), and the two forms of one record are one record (5.3).
- Every move is listed in the changelog, and in `MOVED` in `tests/test_golden_iris.py` with its reason.

### 5.6 The base a record mints under (IRI ruling of 22 October 2026)

From 0.8.0 a new record mints under `https://w3id.org/battinfo/id/1001/`, the base of Battery Genome's prefix (6.4), with the uid that 5.1 and 5.2 give it. Where the base comes from depends on where the record is written:

- A workspace, batch folder or contribution folder records its base when it is created, and every record minted in it takes that base. One that records none mints the old form for good, as every folder created before 0.8.0 does.
- The paths without such a folder, such as the `save_*` and `create_*` functions, the publication package and the importers, take an explicit base, by default `/id/1001/`. A record already saved where they write keeps its IRI, in either form. A `uid=` pin mints under the base too, so a published record is pinned by its IRI (`id=`, `iri=`).
- A record that exists keeps its IRI. A save into a folder that holds a record in the old form adopts that form.
- Before a record is submitted to the registry or deposited, each IRI minted under `/id/1001/` is looked up in the registry (5.3), and one the registry holds in the old form is adopted in every record that names it. One the registry holds, in either form, as superseded or withdrawn is not adopted, and the submission or deposit stops with `RetiredIrisError`: the record described has the identity of a retired record. A registry that cannot be asked stops the submission or deposit unless the caller passes `allow_unchecked_iris=True`, which does not lift the stop for a retired record.

`tests/test_golden_iris.py` checks every path under both bases.

## 6. Entity-Type Registry Governance

The set of record segments, `{segment}` in 3.1, is registry-managed.

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

Superseded segments (`material-spec/`, `electrode-spec/`, `separator-spec/`, `electrolyte-spec/`, `current-collector-spec/`, `housing-spec/`, and the older `cell-type/`, `cell_type/`, `test-protocol/`, `test_protocol/` forms) are never minted under again, and every IRI ever minted under one resolves forever. A superseded segment resolves for every record of a type that minted under it. Cell specs minted under `cell/` before they moved to `spec/` keep resolving there the same way.

Reserved segments (never usable as entity namespaces): `id`, `def`, `ontology`, `vocab`, `doc`, `context`, `resolver`, `schema`, `shapes`, `profile`, `ns`, `twin`, `w3id`, `raw`, `inferred`, `turtle`, `latest`, `source`, `versions`.

The list, with the reason each segment is held, is kept as data in `src/battinfo/data/namespace/reserved-segments.json`, and code that builds or serves BattINFO IRIs reads it from there. `id` is the branch for records and shared things (6.4, 6.5), and `def` the branch for prefix holders' definitions (6.6). `raw`, `inferred`, `turtle`, `latest` and `source` are claimed by the ontology rules in the upstream w3id.org `.htaccess`, so requests to those paths never reach the record resolver. So are `def/{prefix}`, its releases and its terms, which those rules send to the vocabularies on GitHub Pages (6.6).

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

### 6.4 Publisher prefixes (ruled 2026-10-22, revised 2026-10-26)

A publisher prefix is a number of four or more digits, held by one prefix holder, such as a registry. The holder answers for every record address under `https://w3id.org/battinfo/id/{prefix}/` and defines its own terms under `https://w3id.org/battinfo/def/{prefix}/` (6.6). A prefix is a number, never a name, so a holder that changes its name keeps its addresses.

A prefix says who answers for an address, not who did the work. The people who made or contributed a record are credited in the record itself, in its `contributor` entries, with their ORCID iDs.

- The register is `src/battinfo/data/namespace/prefixes.json`. It lists each prefix with its holder, whether records are minted under it and the date it was allocated.
- The maintainers of the battinfo entry on w3id.org give out prefixes, in sequence from 1000. A holder asks for one by pull request to this repository. A number is never reused or passed to another holder.
- 1000 is BattINFO's own and holds definitions only: no record is minted under `id/1000/`. 1001 is the Battery Genome registry, and 1002 is Battery Data Commons.
- The prefix of an IRI never changes once the IRI is minted.
- If a holder closes, its prefix is pointed at an archived copy of what it published, so its IRIs keep resolving.

The registry answers for every address under 1001, and a 1001 address resolves once the registry holds its record. In the registry's API a publisher is an account with its own keys. A lab with such an account publishes under 1001 and owns the IRIs it registers (5.3), but the prefix stays the registry's.

A holder may serve its records itself. The register then says where they live: for that prefix it holds an address pattern for a record's RDF and one for its page, each filled in with the record's uid. The registry forwards a request for such a record there and keeps no copy.

### 6.5 Shared things (ruled 2026-10-22)

A shared thing is something many records point to, such as a product model, a maker or a material. Its IRI is `https://w3id.org/battinfo/id/{uid}`, with no prefix and no segment.

- Only the registry mints a shared thing, and only after curation. BattINFO never mints one offline.
- A record points to a thing from one of its reference fields, such as a cell's `cell_spec_id` or a manufacturer's `id` (11.1). A record's own `id` is never a thing's IRI.
- A datasheet record keeps its own IRI. The registry links its `#described` node to the thing with `owl:sameAs`.
- When two things turn out to be one, they are merged. The thing that goes keeps its IRI as a tombstone, marked `owl:deprecated true`, with `dcterms:isReplacedBy` naming the one that stays (10).

How things are curated is not part of this policy; it is the subject of issue #486.

### 6.6 Prefix holders' vocabularies (ruled 2026-10-26)

A prefix holder defines its terms in one vocabulary, an OWL ontology whose IRI is `https://w3id.org/battinfo/def/{prefix}`. BattINFO's own definitions are under 1000.

- A prefix whose holder has no terms to release yet gets an empty release 0.1.0, so that `def/{prefix}` answers before the first terms are released.
- Each release is a file, `def/{prefix}/{X.Y.Z}/vocab.ttl`, in the BattINFO repository. It is added by pull request, checked in CI and served from the repository's GitHub Pages. Section 11 says how releases and terms are versioned.
- A term is `https://w3id.org/battinfo/def/{prefix}/{term}`, and a vocabulary defines terms only under its own prefix.
- Each vocabulary states its own licence, which applies to it in place of the licence of the BattINFO repository.
- Section 14 applies: a prefix holder uses EMMO and BattINFO terms directly and never mints an equivalent of one.

A prefix holder's terms do not go into v1 records. Every v1 record schema rejects a key it does not list.

## 7. Resolver and Dereferencing Policy

BattINFO IRIs identify resources and MUST resolve via HTTP.

- Resolver implementation SHOULD use 303 redirects for non-information resources.
- `Accept: text/html` SHOULD resolve to a human-readable HTML page.
- `Accept: application/ld+json` SHOULD resolve to JSON-LD.
- `Accept: text/turtle` MAY resolve to Turtle.

Resolver behavior MUST preserve canonical IRI identity and SHOULD redirect non-canonical UID forms to canonical dashed lowercase IRIs.

### 7.1 Address layout (ruled 2026-10-22)

Every address under `https://w3id.org/battinfo/` fits exactly one of these cases:

- The ontology: the root, its formats and source files (`inferred`, `turtle`, `latest`, `source`, `raw/…`), and each release, a pre-release such as `0.8.0-beta` included, at `{version}`, `{version}/inferred` and `{version}/turtle`, with the version IRI the release declares, `{version}/battinfo`.
- A file of the standard under a reserved segment (6.1): the contexts under `context/`, the schemas under `schema/`, and `vocab/records`, the records vocabulary's own ontology IRI.
- A term of the records vocabulary at the root: one of its 57 terms, or a term it declares deprecated; and `ns`, the vocabulary's former address, which answers with the vocabulary document.
- A prefix holder's vocabulary (6.6): `def/{prefix}`, a release `def/{prefix}/{X.Y.Z}`, or a term `def/{prefix}/{term}`.
- A record: `id/{prefix}/{segment}/{uid}` under a prefix that holds records (6.4), or `{segment}/{uid}` for a record that has that IRI in the old form.
- A record under a superseded segment, when the record is of a type that minted under it (6.1).
- A version of a record, the record's IRI followed by `/v{n}` (11). These addresses are reserved and not yet served.
- A shared thing, `id/{uid}` (6.5).

Some of these addresses serve whatever is newest and others name one release. `latest` and `source` serve the ontology's source as it develops, and `def/{prefix}` and its terms serve the vocabulary's newest release, so what they return can change. An ontology release at `{version}`, with its `inferred` and `turtle` forms, and a vocabulary release at `def/{prefix}/{X.Y.Z}` do not change.

A record or thing that was superseded or merged keeps answering at its IRI, with its tombstone (10). Under 1001, the other form of a record's IRI resolves to that record (5.3).

Anything else is answered with 404: a word that is not a listed term, a segment that is not a record segment, a prefix nobody holds, a record address under 1000, or a uid that no record has. This rule takes effect only after two checks show that nothing legitimate breaks: a replay of every known IRI against it, and a period in which the resolver runs it in shadow mode beside its earlier rules.

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

The old IRI then resolves to a tombstone, a short description that makes these two statements and points to the replacement, as 6.3 describes for parameter sets. A shared thing merged into another becomes a tombstone the same way (6.5). An edit to a record is not a supersession: it makes a new version under the same IRI (11).

## 11. Versioning

Version information MUST NOT be encoded in the UID. Identifiers stay version-free.

If versioning is required:

- Use metadata properties
- Use separate versioned resources
- Maintain a stable base entity identifier

A record's IRI names the record and answers with its newest version. An edit to the record makes a new version under the same IRI. Each version has an address of its own, the record's IRI in whichever form it has, followed by `/v{n}`, n being the version's number; for example `https://w3id.org/battinfo/id/1001/cell/b6yn-0sxe-t2qk-9mjv/v3`. Version addresses are reserved; the registry does not serve them yet. A version address names that one version and never changes meaning. A change to a record's identity is not a new version. It gives the record a new IRI, and the old one becomes a tombstone (10).

A prefix holder's vocabulary (6.6) is versioned by release. Release X.Y.Z is `https://w3id.org/battinfo/def/{prefix}/{X.Y.Z}`, which it states as its `owl:versionIRI`, and it may name an earlier release with `owl:priorVersion`. A release never changes once published; a mistake is fixed in a new release. Terms are never versioned, reused or removed. When a meaning changes, a new term takes it and the old term is marked `owl:deprecated true`, with `dcterms:isReplacedBy` naming the new term where there is one.

### 11.1 Served-Artifact Immutability

The shared documents served under `https://w3id.org/battinfo/`, the records JSON-LD context and the JSON Schemas, are versioned resources and are **immutable once published**:

- `https://w3id.org/battinfo/context/records/v1.json`
- `https://w3id.org/battinfo/schema/*`

Both are frozen from the `v0.8.0` tag of BattINFO, its first release on PyPI. Consumers may cache them indefinitely and rely on their meaning staying the same for the lifetime of the URL. The first version of this section, of 30 July 2026, already declared them frozen, yet both changed in place until the release; the [erratum](#erratum-changes-made-in-place-before-080) below lists every such change.

The `v1` records context is append-only from the tag. It defines 707 terms at the tag, and `tests/fixtures/context/records-v1-0.8.0.json` records each of them with its full definition. From the tag:

- A term that `v1` defines in a release MUST NOT change any part of its definition (its IRI, `@type`, `@container` or anything else) and MUST NOT be removed, and `v1` MUST NOT gain a JSON-LD keyword such as `@vocab`, which would change how every document expands. For the terms of 0.8.0, `scripts/gen_context.py` refuses to write such a change and `tests/test_context_v1_freeze.py` fails on one. For the terms of later releases, the same test compares `v1` with the copy at each release tag the commit contains; CI fetches the tags for it. `PRE_RELEASE_CORRECTIONS`, the table in that script that corrected terms before the tag, is closed and no longer applied.
- A release MAY add terms. A release whose records use a new term ships only after the registry serves the context that defines it.
- A term found to be wrong stays as it is. Where an emitter chooses the term, as for a class in `@type`, it can switch to a new, correct term; records published with the old one keep their old meaning. A record key whose expansion is wrong waits for a `v2` context at a new URL (`context/records/v2.json`).

The 0.8.0 schemas are frozen from the same tag. Each schema served under `https://w3id.org/battinfo/schema/` at the tag keeps its content at that URL. From the tag:

- An edit that cannot change whether any document validates, to a `description`, `title`, `$comment` or `examples`, MAY be made in place.
- Any other change, whether it tightens a rule, widens one or adds an optional property, MUST be published as a new schema at a new, versioned URL (`schema/.../v2/...`), while the old URL keeps serving the old content.
- A schema for a new record type MAY be added at its own URL at any time.

`tests/test_schema_freeze.py` compares each schema with its copy at every release tag from `v0.8.0` on that the commit contains, setting those four annotations aside. CI fetches the tags for both tests.

So a 0.8.1 or later release can add terms to `v1`, add schemas and reword descriptions, but it cannot correct a `v1` term or change what a 0.8.0 schema accepts at its URL. How versioned schema URLs are laid out, and what a record's `schema_version` then says about the schemas it was written against, are to be defined in 0.9. Existing versioned URLs remain served and unchanged, so records that reference them keep resolving to the exact document they were written against.

#### Erratum: changes made in place before 0.8.0

When this section was first written, on 30 July 2026, it named "the 373 terms defined by the `v1` records context" as frozen. The registry had then served the complete `v1` context at its URL since 22 July (a smaller context before that) and the schemas since early July. It went on re-syncing both from BattINFO until 12 October 2026, and the release itself corrects more. This erratum lists every change made after 30 July 2026, up to the `v0.8.0` tag, to the definition of an existing term or to what an existing schema accepts. It leaves out new terms (`v1` grows from 373 to 707), new schema files, and edits to descriptions, titles, comments and annotations, such as the withdrawn Battery Pass profile and the IEC wording of `size_code`. It was compiled by comparing the context at each commit that changed it, and the schemas at each registry re-sync, with the copies 0.8.0 ships.

A record published before a change keeps the expansion it was rendered with until the registry renders it again with the 0.8.0 copies.

##### The v1 records context

Each row gives what the term expanded to on 30 July 2026, or when it was first served if that was later, and what it expands to from 0.8.0. Names in plain text are the labels of EMMO classes and relations and stand for their IRIs; the snapshot file has every definition in full.

| Term | Before | From 0.8.0 | Changed by |
|---|---|---|---|
| `typical_capacity` | NominalCapacity | TypicalCapacity | PR #331 (4 August) |
| `operating_temperature_min` | `battinfo:operatingTemperatureMin` | MinimumOperatingTemperature | PR #331 |
| `operating_temperature_max` | `battinfo:operatingTemperatureMax` | MaximumOperatingTemperature | PR #331 |
| `Wh`, `WattHour` | `emmo:WattHour` | `emmo:Watthour` | PR #331 |
| `kWh`, `KiloWattHour` | `emmo:KiloWattHour` | `emmo:KiloWatthour` | PR #331 |
| `power_capability` | `battinfo:powerCapability` | MaximumPower | PR #415 (7 October) |
| `maximum_power` | `battinfo:maximumPower` | MaximumPower | PR #415 |
| `power_energy_ratio` | `battinfo:powerEnergyRatio` | PowerToEnergyRatio | PR #415 |
| `round_trip_energy_efficiency` | `battinfo:roundTripEnergyEfficiency` | RoundTripEnergyEfficiency | PR #415 |
| `capacity_fade` | CapacityFade, the degradation phenomenon | CapacityFadeRate | PR #415 |
| `capacity_threshold_exhaustion` | `battinfo:capacityThresholdExhaustion` | EndOfLifeCapacityThreshold | PR #415 |
| `charging_time` | `battinfo:chargingTime` | ChargingTime | PR #415 |
| `degC` | `emmo:EMMO_36a9bf69_…`, EMMO's class for the programming language C | `emmo:DegreeCelsius` | PR #443 (13 October) |
| `TemperatureCoefficientOfTheOpenCircuitVoltage` | `electrochemistry_3b938708_…`, the IRI of CoatingThickness | `electrochemistry_3bb5ae23_…`, the temperature coefficient | PR #443 |
| `%` | `emmo:Percent`, outside the pinned EMMO closure | PercentUnit (domain-electrochemistry) | PR #465 (14 October) |
| `nominal_continuous_charging_current` | MaximumContinuousChargingCurrent | ChargingCurrent | PR #465 |
| `nominal_continuous_discharging_current` | MaximumContinuousDischargingCurrent | DischargingCurrent | PR #465 |
| `rated_energy`, `certified_usable_energy` | NominalEnergy | RatedEnergy | PR #465 |
| `typical_energy` | NominalEnergy | StoredEnergy | PR #465 |
| `WattPerLitre` | QUDT `unit:W-PER-L`, which does not resolve | `emmo:WattPerLitre` | PR #465 |
| `hasTestObject`, `cell_id` | `battery_da3b3f28_…`, a domain-battery relation with no definition | hasTestObject of domain-electrochemistry | PR #465 |
| `hasTestEquipment` | `battery_df4ff8f1_…`, a domain-battery relation with no definition | hasTestEquipment of domain-electrochemistry | PR #465 |
| `ambient_temperature` | `battinfo:ambientTemperature`, a placeholder | AmbientCelsiusTemperature | PR #465 |
| `id` | `schema:productID` | `schema:identifier` | PR #465 |
| `hasNumberValue`, `hasNumericalValue` | EMMO's hasNumberValue, with no datatype | the same IRI, typed `xsd:double` | PR #465 |
| `active_material_spec_id` | the ActiveMaterial class | hasActiveMaterial | PR #465 |

`PrismaticBattery` also changed in PR #331, to a hyphenated IRI the battery ontology had deprecated, and PR #415 restored it, so it ends as it was on 30 July. The registry served the PR #331 changes from 11 August 2026 and the PR #415 changes from 7 October, and from 11 October it served `TemperatureCoefficientOfTheOpenCircuitVoltage` with the CoatingThickness IRI. The PR #443 and PR #465 corrections reach the hosted copy with the 0.8.0 re-sync. Among the terms 0.8.0 adds are twelve unit terms from PR #460, `MilliAmpereHourPerGram`, `AmpereHourPerKilogram`, `MilliAmpereHourPerSquareCentiMetre`, `SiemensPerCentiMetre`, `KiloPascal`, `MegaPascal`, `WattPerWattHour`, `KiloWatt`, `MilliWatt`, `SquareMilliMetre`, `CubicMilliMetre` and `Day`. `%/month` and `year` have no unit in the pinned EMMO closure, so `v1` has no term for them and records keep them as text (`schema:unitText`); a term for them would be an addition.

##### The JSON Schemas

These changes can make a record that validated before fail now:

- Quantity values are numbers only (14 October, PR #460). `value` in `modules/common/quantity.schema.json` and in the `Quantity` of `battinfo.base.schema.json` took a number or a non-empty string, and now takes a number only; text goes in `value_text`. 19 of the 22 record kinds use this module, and so do the `conditions` maps of quantities. A scan of the published corpus on 13 October 2026 (all 1,695 records in battinfo-records and a sample of 295 registry records) found none with text in `value`. When battinfo reads an older record (`ws.import_()`, `ws.load()`, an upsert through `save_record`), it turns a numeric string into a number and moves other text to `value_text`, with a warning.
- Date strings have a fixed form (8 September, PR #388). In cell, current-collector, electrode, electrolyte, housing, material and separator records, `manufactured_at`, `expires_at`, `received_date` and `opened_date` took a Unix time or any string. A string must now read `YYYY`, `YYYY-MM` or `YYYY-MM-DD`.
- Test conditions are quantities (8 September, PR #388). An entry of a test record's `conditions` map could hold anything and must now be a quantity.
- A cell spec's `housing` and `construction` are checked (8 September, PR #388). `housing` took any object and now follows `modules/components/housing.schema.json`, which allows `cap`, `case`, `comment`, `parts`, `property`, `seals` and `terminals` only. In `construction`, `electrode_length` and `jellyroll_volume` took any object and must now be quantities.
- An electrode's `tab` is checked (8 September, PR #388). In `electrode-spec.schema.json` and `modules/components/electrode.schema.json` it took any object; it now allows `material`, `manufacturer`, `supplier`, `product_id`, `comment` and the dimensions under `property` only.
- The provenance block of electrode-spec and electrode records lost `comment`, `curated_by`, `file_hash` and `workflow_version` (8 September, PR #388), which it had accepted from 14 August.
- `modules/components/specification.schema.json` requires `name` and `cell_format` instead of `format`, `positive_electrode_basis` and `negative_electrode_basis`, and its `id` must be a `spec/` IRI, no longer a `cell/` one (8 September, PR #388). `cell-spec.schema.json` uses only its `separator`, so cell-spec records are not affected; a document validated against the module as a whole may be.
- Parameter sets lost `members` and `set_id` (11 October, PRs #421 and #436), which were served from 4 October. A parameter set is now either a claim batch (`claims` and exactly one target, as in August) or one parameter file (`parts`, `parameters_sha256` and exactly one cell link).

These changes only accept more, so a record that validated before still does:

- `battinfo_version`, in the provenance block and in the envelope of `battinfo.base.schema.json`, takes PEP 440 versions (`0.8.0rc1`, `0.8.0.dev1`, `0.8.0.post1`, `0.8.0+local`) as well as `X.Y.Z` with a hyphenated suffix, in all 25 schemas that carry the pattern (PR #456).
- `material_spec_id` in the material-component, current-collector and electrolyte modules, and `electrode_spec_id` in the electrode module, take the superseded `material-spec/` and `electrode-spec/` IRIs as well as `spec/` (14 October, PR #460).
- A quantity that gives only `value_text` needs no unit (8 September), and an inline electrode may consist of its `electrode_spec_id` alone (14 August).
- A cell spec's `reference_electrode` takes an inline electrode as well as a string, and a parameter set no longer needs `claims` (4 October).
- A parameter set's `id` and `supersedes` take a `dataset/` IRI as well as a `spec/` one (12 October, PR #436). New parameter sets mint under `dataset/`, and a `spec/` IRI remains valid for a record minted before (section 6.3).
- Enumerations gained values: the housing part type `vent` (31 July), the material classes `thickener` and `dispersant` (8 September), the test and test-protocol kinds `pitt` and `cyclic_voltammetry`, and the termination quantity `soc` (4 October).
- Record IRIs take both shapes that the IRI ruling of 22 October allows (issues #476 and #478). Every pattern that reads a record IRI, in 32 schema files, accepts `https://w3id.org/battinfo/id/{prefix}/{segment}/{uid}`, with a prefix of four or more digits, as well as `https://w3id.org/battinfo/{segment}/{uid}`, because records of other publishers appear as parents. The patterns are now built by `battinfo.namespace` (`scripts/sync_schema_iri_patterns.py`).
- A field that references a maker, a product model or a material also accepts a shared thing, `https://w3id.org/battinfo/id/{uid}` (issue #478): the `id` of an organization given as a manufacturer, supplier, brand or parent organization, a cell's or a parameter set's `cell_spec_id`, and `material_spec_id`, `active_material_spec_id` and `base_material_id`. A record's own `id` does not. These fields refer to `OrganizationRefIri`, `CellSpecRefIri` and `MaterialSpecRefIri`, split from the definition of a record's own `id` where one served both.
- An electrolyte's `salt` and a person's `affiliation` each take one object or a list of them (25 October, PR #471).
- The `manufacturer` and `supplier` of an inline component (electrode, coating, tab, current collector, electrolyte, salt, material, mixture, separator) take an organization object (`modules/common/organization-ref.schema.json`) as well as a name, and an `Organization` takes `same_as`, an external IRI such as a ROR ID (PR #471).
- An inline electrode (`modules/components/electrode.schema.json`) may consist of its `material` alone, such as a lithium-metal counter electrode (PR #471).
- Optional properties were added to most schemas, `license` and `handle` among them. A record written before uses none of them. The 0.8.0 changelog describes each.

The first version of this section allowed additive, backward-compatible changes within a version, so the changes in this last list did not break it; they are listed so that the record is complete.

##### The records vocabulary

The records vocabulary, `assets/vocab/battinfo-records.ttl`, which the registry serves for each of its terms, changed in two ways before the tag (issue #481):

- It declares its own ontology IRI, `https://w3id.org/battinfo/vocab/records`. It declared `https://w3id.org/battinfo/`, the root, where the BattINFO ontology's document is served (the ontology's own IRI is `https://w3id.org/battinfo#`, section 1), so two documents claimed one address. Its 57 term IRIs are unchanged; each term's `rdfs:isDefinedBy` names the new IRI.
- The 39 terms that earlier served copies declared and later dropped are declared again, as `owl:deprecated`, so that records and deposits that use them still find a definition. Nine name the EMMO term that replaced them with `dcterms:isReplacedBy`, `ambientTemperature` (AmbientCelsiusTemperature) among them.

## 12. Governance Scope

This policy applies to:

- Cells
- Tests
- Datasets
- Materials
- Models
- Any future BattINFO-registered entity types

## 13. Security and Audit Requirements

These apply to the registry. BattINFO mints uids on the machine that writes a record (5.1), with no issuing authority to log or guard; what the registry audits is what it accepts.

- The records the registry accepts, and the IRIs its fallback minter issues (5.3), MUST be logged in append-only form with timestamp, publisher, entity type, IRI and status.
- Access to the registry's submission endpoints and its fallback minter MUST be authenticated and auditable.
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

`battinfo.ttl` is an **application ontology** in the strict sense: (a) the import/pin manifest for the EMMO modules a release speaks, (b) the small record-layer residue of genuinely non-domain terms (after re-homing to DCTERMS/PROV/DCAT/schema.org where standard terms exist), and (c) optionally the profile constraints (SHACL shapes). Nothing else. The same ruling applies to every branch under `w3id.org/battinfo/`, prefix holders' vocabularies under `def/{prefix}/` (6.6) and `/twin` among them: quantity terms resolve to EMMO or go upstream; only structural terms may be minted locally, hand-defined.

So no branch holds an alias layer over EMMO or BattINFO (ruled 2026-10-26). A prefix holder uses an existing EMMO or BattINFO term directly and never mints an equivalent of it. A `def/` term whose label matches the label of an EMMO or BattINFO term states how it differs, with `skos:closeMatch`, `skos:broadMatch` or `skos:narrowMatch`. A `def/` term is never linked to an EMMO or BattINFO term with `owl:equivalentClass` or `skos:exactMatch`.

Reserved namespace segments (never usable as entity types): `id`, `def`, `ontology`, `vocab`, `doc`, `context`, `resolver`, `schema`, `shapes`, `profile`, `ns`, `twin`, `w3id`, `raw`, `inferred`, `turtle`, `latest`, `source`, `versions`.

## 15. Design Principles

The BattINFO identifier system is designed to be:

- Infrastructure-grade
- Web-native
- Scalable to hundreds of millions of entities
- Compatible with distributed data generation
- Independent of any single software platform

## 16. Rationale

The 16-character Base32 UID:

- Holds 80 bits. A uid hashed from a seed (5.1) is 80 bits of a SHA-256 digest, so two different seeds share a uid about as rarely as two random 80-bit values do
- Offers extremely low collision probability at BattINFO scale
- Is shorter and cleaner than UUID
- Is readable when grouped as 4-4-4-4
- Avoids semantic fragility
- Aligns with modern infrastructure practice

## 17. Cell-Spec Identifier Usability Decision (v1.0)

BattINFO cell-spec identifiers MUST remain opaque and policy-compliant:

- `https://w3id.org/battinfo/id/{prefix}/spec/{uid}`, or `https://w3id.org/battinfo/spec/{uid}` in the old form (a cell spec is a reusable description; per §6.1 every spec mints under the shared `spec/` segment, e.g. the flagship `https://w3id.org/battinfo/spec/pge5-wer6-2q82-v9k0`)

Human-readable model/manufacturer semantics MUST NOT be encoded in the canonical identifier.

To make instantiation practical:

- Users SHOULD resolve cell-spec IDs via metadata queries (`manufacturer`, `model_name`, `chemistry`, `format`, properties).
- User interfaces SHOULD display metadata labels plus canonical IRI (and optional `short_id`).
- APIs and tooling SHOULD support lookup-first workflows that return a single canonical cell-spec IRI before instance creation.

Rationale:

- Semantic IDs are brittle under naming changes, aliases, vendor rebranding, and typo correction.
- Opaque IDs preserve long-term persistence and avoid migration risk.
- Metadata-based lookup provides usability without undermining identifier governance.
