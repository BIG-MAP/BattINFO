// JSON Schema -> what a form needs to know. Pure: no React, no state.
//
// The schemas are the single source of truth. Nothing in this file lists a
// field, a unit or a vocabulary term; everything is read from the schema at
// runtime. That is the whole point: add a field upstream and the form grows it.

import { schemaFiles } from "@/lib/schemas.generated";

export type Schema = Record<string, any>;

// A schema plus the file it came from. The file matters because $refs are
// relative to it, so a bare schema object is not enough to follow one.
export interface Located {
  schema: Schema;
  file: string;
}

const BY_PATH = new Map(schemaFiles.map((f) => [f.path, f.schema]));

// Paths are spelled the way lib/validate.ts reports them -- "cell_spec.id",
// "notes.0" -- so a row can look itself up in the validator's own findings.
export function join(path: string, key: string | number): string {
  return path ? `${path}.${key}` : String(key);
}

export function schemaFor(file: string): Located {
  const schema = BY_PATH.get(file);
  if (!schema) throw new Error(`no such schema file: ${file}`);
  return { schema, file };
}

// "modules/components/a.json" + "../common/b.json" -> "modules/common/b.json"
function relativeTo(file: string, ref: string): string {
  const out: string[] = file.split("/").slice(0, -1);
  for (const part of ref.split("/")) {
    if (part === "" || part === ".") continue;
    if (part === "..") out.pop();
    else out.push(part);
  }
  return out.join("/");
}

function pointerInto(schema: Schema, pointer: string): Schema {
  let here = schema;
  for (const raw of pointer.split("/")) {
    if (raw === "") continue;
    const key = raw.replace(/~1/g, "/").replace(/~0/g, "~");
    here = here?.[key];
    if (here === undefined) throw new Error(`no such pointer: ${pointer}`);
  }
  return here;
}

// Follow $ref until we reach a real schema. Refs come in three shapes:
// "#/$defs/X" (same file), "other.json" (whole file), "other.json#/$defs/X".
export function deref(loc: Located): Located {
  let { schema, file } = loc;
  for (let hops = 0; schema?.$ref && hops < 16; hops++) {
    const [target, pointer] = String(schema.$ref).split("#");
    if (target) file = relativeTo(file, target);
    const root = BY_PATH.get(file);
    if (!root) throw new Error(`no such schema file: ${file}`);
    schema = pointer ? pointerInto(root, pointer) : root;
  }
  return { schema, file };
}

// Follow $ref, and then a union of shapes, to the schema that actually
// describes the value.
//
// A union is only a union when the schema has no shape of its own: several
// schemas carry `type`, `properties` AND an `anyOf`, where the anyOf states a
// cross-field constraint (ajv's job) rather than a choice of shape, so reading
// it as one would throw the object away.
//
// Both the control and the field list go through here, and that is the point.
// They used to disagree: controlFor followed the union and said "object",
// fieldsOf read `properties` off the union node and found none, so eight fields
// across the record types -- `cell_spec.brand` among them -- drew a section
// with nothing inside it.
/** Two schemas describing the same value. Shape, not identity: a definition
 *  referenced twice and the same definition written out twice should both
 *  count as a match. */
function sameShape(a?: Schema, b?: Schema): boolean {
  return a !== undefined && b !== undefined && JSON.stringify(a) === JSON.stringify(b);
}

export function resolve(loc: Located): Located {
  let here = deref(loc);
  for (let hops = 0; hops < 8; hops++) {
    const { schema, file } = here;
    if (!schema || schema.type !== undefined || schema.properties) return here;
    const union = schema.anyOf ?? schema.oneOf;
    if (!Array.isArray(union)) return here;
    // Branches are often bare $refs, so deref before judging them. Taking the
    // first real branch covers [X, null] and [string, string[]]; where the
    // choice is genuine (Brand or Organization) it picks the first, which is
    // valid -- offering the choice is a later refinement.
    const branches = union.map((b: Schema) => deref({ schema: b, file }));
    // "One X, or a list of X" (salt, solvent, an organization's same_as) is a
    // list: a list holds one as well as many, so taking the single branch
    // would drop every list. The item and the single branch are compared by
    // shape rather than by object identity -- the two often $ref one
    // definition, but just as often each is written out inline, and identity
    // misses every inline pair.
    const list = branches.find((b) => {
      if (b.schema?.type !== "array") return false;
      const item = deref({ schema: b.schema.items ?? {}, file: b.file }).schema;
      return branches.some((other) => other !== b && sameShape(other.schema, item));
    });
    // "A name, or an object holding that name" (an organization reference) is
    // the object: it says all the name does, and its IRIs besides.
    const named = branches.some((b) => b.schema?.type === "string")
      ? branches.find((b) => b.schema?.type === "object" && b.schema.required?.includes("name"))
      : undefined;
    const branch = list ?? named ?? branches.find((b) => b.schema !== undefined && b.schema.type !== "null");
    if (!branch) return here;
    here = branch;
  }
  return here;
}

// What kind of input a value needs. "const" is a value the schema fixes, so the
// form sets it rather than asking. "opaque" is a value the author does not own.
// "unsupported" is a shape this file cannot read; the tree falls back to a plain
// text box for it, and scripts/check-create.ts fails the build if any reachable
// field ever reaches it.
export type Control =
  | { kind: "text"; format?: string }
  | { kind: "number"; integer: boolean }
  | { kind: "boolean" }
  | { kind: "select"; options: string[] }
  | { kind: "const"; value: unknown }
  | { kind: "object" }
  | { kind: "map"; values: Located; keyPattern?: string }
  | { kind: "array"; items: Located }
  | { kind: "opaque" }
  | { kind: "unsupported" };

// Three ways a schema says "an object whose keys the author chooses":
//
//   patternProperties        keys match a pattern, values share one schema
//   additionalProperties: {} any key, values share one schema
//   additionalProperties:true any key, and any value at all
//
// The first two are named maps -- "diameter", "mass", a protocol condition --
// and get a typed control per entry. The third constrains nothing, so no
// control could be right: a text box would turn `{"reviewed": true}` into
// `{"reviewed": "true"}` on a round trip. Those fields say as much themselves
// ("never authored by hand", "ignored by the publish pipeline"), so the form
// carries them through untouched instead of inventing an editor for them.
function mapOrObject(schema: Schema, file: string): Control {
  if (Object.keys(schema.properties ?? {}).length === 0) {
    const [keyPattern, values] = (Object.entries(schema.patternProperties ?? {})[0] ?? []) as [
      string | undefined,
      Schema | undefined,
    ];
    if (values) return { kind: "map", values: resolve({ schema: values, file }), keyPattern };
    const extra = schema.additionalProperties;
    if (extra && typeof extra === "object") return { kind: "map", values: resolve({ schema: extra, file }) };
    if (extra === true) return { kind: "opaque" };
  }
  return { kind: "object" };
}

export function controlFor(loc: Located): Control {
  const { schema, file } = resolve(loc);
  if (!schema) return { kind: "unsupported" };
  if (schema.const !== undefined) return { kind: "const", value: schema.const };
  if (Array.isArray(schema.enum)) return { kind: "select", options: schema.enum.map(String) };

  // A schema that constrains nothing -- `{}`, or nothing but prose -- permits
  // any value, so a plain box is the one control that cannot contradict it.
  // Dataset's per-file `conditions` is the only one: what is typed there stays
  // a string, which that schema allows.
  if (Object.keys(schema).every((key) => key === "description" || key === "title")) {
    return { kind: "text" };
  }

  // `type: ["number", "null"]` is a nullable value, not a shape of its own: the
  // null branch says "may be absent", which removing the row already says. The
  // first real member wins, as it does for a union of branches above. Without
  // this, ten fields -- every one of test-protocol's safety limits among them --
  // fall through to an untyped box that stores "4.2" as a string the schema
  // then rejects.
  const type = Array.isArray(schema.type)
    ? schema.type.find((member: unknown) => member !== "null")
    : schema.type;

  switch (type) {
    case "string":
      return { kind: "text", format: typeof schema.format === "string" ? schema.format : undefined };
    case "number":
      return { kind: "number", integer: false };
    case "integer":
      return { kind: "number", integer: true };
    case "boolean":
      return { kind: "boolean" };
    case "object":
      return mapOrObject(schema, file);
    case "array":
      return { kind: "array", items: resolve({ schema: schema.items ?? {}, file }) };
    default:
      return schema.properties || schema.patternProperties ? mapOrObject(schema, file) : { kind: "unsupported" };
  }
}

// Requirements a schema states as a choice rather than a list: "one of these
// must be present". A quantity says it this way -- a value, and a unit for it --
// so `required` is empty and a plain reading of the schema shows nothing at all.
// Branches that are not a bare `required` (the exemption a text-only value gets)
// are skipped: they qualify the rule rather than name a field.
export function requiredGroups(loc: Located): string[][] {
  const { schema } = deref(loc);
  const groups: string[][] = [];
  for (const node of [schema, ...(schema?.allOf ?? [])]) {
    const branches = node?.anyOf ?? node?.oneOf;
    if (!Array.isArray(branches)) continue;
    const named = branches
      .filter((b: Schema) => b && Object.keys(b).length === 1 && Array.isArray(b.required))
      .flatMap((b: Schema) => b.required as string[]);
    if (named.length > 1) groups.push(named);
  }
  return groups;
}

export interface Field {
  key: string;
  label: string;
  help?: string;
  required: boolean;
  loc: Located;
}

// A field the schemas keep accepting but tell you not to start using -- a
// pre-snake_case spelling, an alias a rename left behind. Offering it beside
// the current spelling is a trap: `legalName` and `legal_name` sit next to
// each other in the list and nothing says which one is the one to use.
//
// Read from the schema's own words rather than held as a list here: all
// sixteen open their description with "Deprecated". Shown when a record
// already carries one, never offered for a new record -- the same rule an
// opaque value gets.
export function isDeprecated(field: Field): boolean {
  return /^\s*deprecated/i.test(field.help ?? "");
}

// The value a freshly added field starts as. Required children are filled in
// too, so adding an object never leaves a hole the user cannot see -- and a
// value the schema fixes (`const`) is set rather than asked for. Recursion is
// bounded: it follows required fields only, and cell-spec is five deep.
export function blankFor(loc: Located): unknown {
  const control = controlFor(loc);
  switch (control.kind) {
    case "const":
      return control.value;
    case "boolean":
      return false;
    case "array":
      return [];
    case "map":
      return {};
    // Never created by the form -- only carried when a loaded record has one.
    case "opaque":
      return undefined;
    case "object": {
      const out: Record<string, unknown> = {};
      for (const field of fieldsOf(loc)) {
        const child = controlFor(field.loc);
        if (child.kind === "const") out[field.key] = child.value;
        else if (field.required) out[field.key] = blankFor(field.loc);
      }
      return out;
    }
    default:
      return "";
  }
}

// "positive_electrode_basis" -> "Positive electrode basis". Only a title on the
// property itself is used: the title of a shared $ref target describes the
// definition, not this use of it, so four electrode roles all read "Electrode".
// Inline properties carry no title at all, so the key is usually the only label
// there is; if titles land upstream this falls back to them instead.
export function labelFor(key: string, schema?: Schema): string {
  if (schema?.title) return schema.title;
  const words = key.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

// Every property an object node may hold, in schema order, required first
// flagged. The description is read before dereferencing: a $ref carries its
// own meaning at the point of use ("Canonical IRI of this cell spec") which is
// more specific than the shared definition it points at.
export function fieldsOf(loc: Located): Field[] {
  const { schema, file } = resolve(loc);
  const required = new Set<string>(schema?.required ?? []);
  return Object.entries(schema?.properties ?? {}).map(([key, raw]) => {
    const sub = raw as Schema;
    const target = resolve({ schema: sub, file });
    return {
      key,
      label: labelFor(key, sub),
      help: sub.description ?? target.schema?.description,
      required: required.has(key),
      loc: target,
    };
  });
}
