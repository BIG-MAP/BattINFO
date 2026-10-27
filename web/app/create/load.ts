// Turning somebody else's JSON into a draft. Pure: no React, no state, so the
// CI guard can run exactly the code the page runs rather than a copy of it.

import { controlFor, fieldsOf, join, type Located } from "./schema";
import { DERIVED_IDENTITY, type RecordType } from "./types";
import { SCHEMA_VERSION } from "@/lib/schema-version";

type Obj = Record<string, unknown>;

export interface Loaded {
  record: Obj;
  removed: string[];
}

// An uploaded file is someone else's JSON. Anything the schema does not know is
// dropped rather than carried into a record that would then fail validation for
// a reason the form cannot show -- the tree only draws fields the schema names,
// so an unknown key would be invisible and still in the output.
export function sanitize(value: unknown, loc: Located, path = "", removed: string[] = []): unknown {
  const control = controlFor(loc);
  // The schema allows any shape here, so every key under it is "known" and
  // none of it is ours to rewrite. Walking in would drop the lot as unknown --
  // which is exactly how a test protocol's conditions and setpoints used to
  // disappear on upload.
  if (control.kind === "opaque") return value;
  // A name where an object holding that name is edited (an organization
  // reference given as a plain name) is that object.
  if (control.kind === "object" && typeof value === "string" && fieldsOf(loc).some((f) => f.key === "name")) {
    return { name: value };
  }
  if (value === null || typeof value !== "object") return value;

  if (control.kind === "array") {
    // A lone object where a list is expected is the "one X" form of "one X or a
    // list of X"; keep it as a one-item list rather than dropping it.
    const items = Array.isArray(value) ? value : [value];
    return items.map((item, index) => sanitize(item, control.items, join(path, index), removed));
  }

  if (control.kind === "map") {
    const allowed = new RegExp(control.keyPattern ?? ".");
    const out: Obj = {};
    for (const [key, item] of Object.entries(value as Obj)) {
      if (!allowed.test(key)) removed.push(join(path, key));
      else out[key] = sanitize(item, control.values, join(path, key), removed);
    }
    return out;
  }

  if (control.kind !== "object") return value;

  const known = new Map(fieldsOf(loc).map((field) => [field.key, field.loc]));
  const out: Obj = {};
  for (const [key, item] of Object.entries(value as Obj)) {
    const child = known.get(key);
    if (!child) removed.push(join(path, key));
    else out[key] = sanitize(item, child, join(path, key), removed);
  }
  return out;
}

// Everything the form settles about a draft rather than asking: the record is
// put in the shape the tree reads, the library's schema_version goes in, and
// the identity it derives on save comes out. One definition, applied wherever
// a draft enters -- a blank one, a template, an uploaded file, or a record
// carried in a link.
//
// Sanitising here and not only on upload is what makes that true. Several
// schemas say "one X or a list of X", the tree renders whichever shape the
// union resolved to, and a lone value where it expects a list is a crash
// rather than a mis-render. sanitize is what reconciles the two. The template
// path used to skip it, and seven of the nine templates broke the page the
// moment they were picked.
//
// schema_version overrides whatever a loaded record arrived with, because the
// draft is being edited against these schemas and claiming an older version it
// no longer matches would be a lie.
export function asDraft(record: Obj, type: RecordType): Obj {
  const clean = sanitize(record, type.root) as Obj;
  const body = { ...((clean[type.key] ?? {}) as Obj) };
  for (const key of DERIVED_IDENTITY) delete body[key];
  return { ...clean, schema_version: SCHEMA_VERSION, [type.key]: body };
}

// A template is a starting point, never a history. The curated records carry a
// provenance block naming the source file, DOI and retrieval time they were
// built from; kept, it would have a new record claim a past it never had. Only
// the kind of source stays: a record started from a template is still entered
// the way the template was. (Their minted IRI goes too, but every draft loses
// that -- see asDraft.) scripts/sync-templates.mjs points here for the rule.
export function asTemplate(record: Obj, type: RecordType): Obj {
  const { provenance, ...rest } = record;
  const sourceType = (provenance as Obj | undefined)?.source_type;
  return asDraft(sourceType === undefined ? rest : { ...rest, provenance: { source_type: sourceType } }, type);
}

/** A parsed record, checked for the two things it must not be, then put
 *  through the one intake every record goes through. */
function take(parsed: unknown, type: RecordType): Loaded {
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("A BattINFO JSON must be a JSON object.");
  }
  // The published form, not the authored one. Sanitising it would strip
  // @context and @graph as unknown keys and hand back an empty record, so say
  // what it is instead -- the same distinction /validate draws.
  if ("@context" in parsed || "@graph" in parsed) {
    throw new Error(
      "This is a JSON-LD document — the published form, generated from a canonical record. " +
        "Open the canonical record it was generated from.",
    );
  }
  const removed: string[] = [];
  return { record: sanitize(parsed, type.root, "", removed) as Obj, removed };
}

export async function read(file: File, type: RecordType): Promise<Loaded> {
  return take(JSON.parse(await file.text()), type);
}

// A record handed over in the link itself, so another tool can open a filled
// form: /create/<type>#record=<base64url of gzipped JSON>.
//
// The fragment is the carrier on purpose. A browser never sends it to a
// server, so a record arriving this way is as private as one typed in, and
// the page keeps its promise that nothing leaves it. Gzip keeps even a
// detailed cell spec near 2 kB, where the raw JSON would be five.
//
// What arrives is a stranger's JSON and is treated as one: the same intake as
// an upload, so a link cannot introduce a field the schemas do not define,
// and the identifier is dropped exactly as it is for a file.
const RECORD_FRAGMENT = "record";

function fromBase64url(text: string): Uint8Array {
  const padded = text.replace(/-/g, "+").replace(/_/g, "/");
  const binary = atob(padded + "=".repeat((4 - (padded.length % 4)) % 4));
  return Uint8Array.from(binary, (c) => c.charCodeAt(0));
}

export async function readFragment(fragment: string, type: RecordType): Promise<Loaded | null> {
  const encoded = new URLSearchParams(fragment.replace(/^#/, "")).get(RECORD_FRAGMENT);
  if (!encoded) return null;
  let text: string;
  try {
    const bytes = fromBase64url(encoded);
    const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip"));
    text = await new Response(stream).text();
  } catch {
    throw new Error("That link does not carry a readable record (expected gzipped JSON in base64url).");
  }
  return take(JSON.parse(text), type);
}
