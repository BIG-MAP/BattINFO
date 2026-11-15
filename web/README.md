# battinfo.org — website

The public landing pad and documentation site for **BattINFO**, the semantic
data layer for battery technology. Deployed at <https://battinfo.org>.

This is a self-contained Next.js app living inside the BattINFO monorepo. It is
the only thing in this directory; it does **not** import from or modify the
Python package, ontology, schemas, or any other part of the repo. Content that
needs to stay in sync with the ontology/schemas (term reference, schema browser)
is pulled in at build time via an explicit sync step (see "Content sources"
below) — never by reaching across the repo at runtime.

## Develop

```bash
cd web
npm install
npm run dev          # http://localhost:3000
```

## Build

```bash
npm run build
npm run start
```

## Deploy (Vercel)

Create a **separate Vercel project** for this site and set:

- **Root Directory:** `web`
- **Domain:** `battinfo.org`
- **Ignored Build Step:** skip builds when nothing under `web/` changed, e.g.
  `git diff --quiet HEAD^ HEAD -- .` — so ontology/package commits don't trigger
  a site rebuild.

Keeping the Vercel root scoped to `web/` is what keeps the monorepo split-able
later: the site is a pure subdirectory consumer.

## Content sources

The site is a presentation layer. The sources of truth stay where they live:

| On the site | Source of truth | How it gets here |
|---|---|---|
| Term / IRI reference | `battinfo.ttl`, `assets/ontology/` | build-time sync script (TODO) |
| Schema browser | `assets/schemas/*.json` | build-time sync script (TODO) |
| Examples (flagship record) | `examples/cell-spec/A123__ANR26650M1-B.json` | `npm run sync:examples` → `lib/examples.generated.ts` (committed) |

```bash
npm run sync:examples   # regenerate lib/examples.generated.ts from examples/**
```

`lib/examples.generated.ts` is generated and **committed** (so the Vercel build,
scoped to `web/`, never reaches outside it). CI should re-run the sync and fail
on a dirty diff. The remaining inline fixtures under `lib/` are clearly marked
teasers; see `docs/CONTENT-MODEL.md` §4 for what is and isn't synced yet.
Resolution of `w3id.org/battinfo/` IRIs stays on w3id.org — this site never
serves as the IRI resolver.

## The Create page (`/create`)

`/create/<record-type>` builds a form for any of the record types in
`lib/validate.ts`'s `DISCRIMINATORS` by reading the vendored JSON Schemas at
runtime. It lists no field, option or vocabulary term of its own, so it cannot
drift from the package — which is why it replaces nothing by hand and needs no
sync step beyond the ones already here.

One question at a time, each with the screen to itself:

| | | |
|---|---|---|
| `/create` | which kind of record? | `chooser.tsx` |
| `/create/<type>` | what goes in it — blank, a template, a file? | `start.tsx` |
| `/create/<type>` | *(answered)* the record | `form.tsx` |

The kinds are offered in three groups, because which kind you want is the
first thing to get right. `familyOf` (types.ts) reads the group from the
schemas rather than keeping a list: a **specification** by the package's naming
convention (`<thing>_spec`); an **instance** by requiring the IRI of the record
it came from, its own `id` not counting; everything else by requiring neither.
A record type added to the package therefore lands in a group without this page
being touched, and `check:create` fails if a group empties or if the records
that name something stop naming it.

No form renders behind a question: a blank one reports every required field
as missing before anyone has written a thing. Once the kind is settled it
needs no chrome — the tree's outermost branch is the record's own key.

What it does *not* do is as deliberate as what it does:

- **No identifier.** `id`, `short_id` and `identifier` are derived by the
  library at save time, and since BIG-MAP/BattINFO#435 a placeholder is
  rejected outright. The form shows no row for them. A record opened from a
  file or a link keeps the ones it has, so saving it again updates that
  record; a template leaves its IRI behind. The schemas still require an `id`,
  so this is the one place the page sets the validator aside: a *missing* id
  (or dataset identifier) is excused, a wrong one is not (`findingsFor` in
  `load.ts`). Ten component and equipment types have no natural key, so the
  package cannot mint their IRI and refuses to save a new one without a uid;
  their pages say so (`NO_NATURAL_KEY` in `types.ts`).
- **No JSON-LD.** The transform has no JavaScript equivalent and this site runs
  without a server; `battinfo` emits it from the downloaded record.
- **No free-form editing.** A schema that constrains nothing about its values
  (`editorial`, `facets`) is carried through untouched rather than given an
  editor that would retype `true` as `"true"`.
- **No storage.** A draft lives as long as the page is open. To carry on
  another day, download the record and open it again — the form reads its own
  output. A half-written record quietly outliving the visit that made it was a
  surprise rather than a feature, and keeping it in step with what was on
  screen caused more bugs than it prevented. Closing the tab with work in it
  asks first, as does the way back to the record types; the site's own nav
  links do not, which is the one place work can still be lost.

`npm run check:create` runs the page's own modules over every record type:
every field resolves to a control, every container can hold something,
`blankFor` terminates, templates load without dropping anything and still
validate once loaded, a "one or a list" field keeps its list, an organization
reference keeps its IRIs, an opened record keeps its identity and a template
does not. It is wired into CI next to the other web checks.

### Opening a filled form from a link

Another tool can hand the page a record to open:

```text
/create/<record-type>#record=<base64url of the gzipped canonical JSON>
```

The fragment is the carrier deliberately. A browser never sends it to a
server, so a record arriving this way is as private as one typed in and the
page keeps its promise that nothing leaves it. Gzip keeps a detailed cell spec
near 2 kB where the raw JSON is five.

```js
// writing one
const gz = await new Response(
  new Blob([JSON.stringify(record)]).stream().pipeThrough(new CompressionStream("gzip")),
).arrayBuffer();
let binary = "";
for (const byte of new Uint8Array(gz)) binary += String.fromCharCode(byte);
const encoded = btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const url = `https://battinfo.org/create/cell-spec#record=${encoded}`;
```

What arrives is a stranger's JSON and is treated as one: the same intake as an
upload, so a link cannot introduce a field the schemas do not define, and it
keeps its identity exactly as a file does. A fragment that carries no
readable record, or one that inflates past 5 MB, says so above the start
screen rather than failing quietly, and the fragment is cleared from the
address bar once read. `check:create` pins the format.

It replaced a playground at this same address that hand-listed six object
types and showed each as Python, canonical JSON and JSON-LD. Two pages both
offering to build a record was the confusing part, and the Python it taught
already lives in `/docs`, which is where someone goes looking for it. That
removed `lib/create-model.ts`, its CI guard, and the hand-copied
`SCHEMA_VERSION` those shared — the stamp is now read from the synced example
corpus (`lib/schema-version.ts`), so it cannot drift.

## Status

Early draft scaffold. Landing, docs index, examples, an in-browser structural
validator, and the Create page above are runnable. Create is marked beta in
the UI: the schemas may still change until battinfo 1.0.
