// What the form needs to know about one record type. Almost nothing here is
// a list: the types come from lib/validate's DISCRIMINATORS (itself pinned to
// battinfo.entities.ENTITY_KINDS by a Python test) and everything else from
// the schemas, except NO_NATURAL_KEY, which the schemas cannot tell and a
// Python test pins the same way.

import { DISCRIMINATORS } from "@/lib/validate";
import { fieldsOf, labelFor, resolve, schemaFor, type Located } from "./schema";

export interface RecordType {
  /** The discriminator key and the schema's own body key. */
  key: string;
  label: string;
  root: Located;
}

function build(key: string, file: string): RecordType {
  return { key, label: labelFor(key), root: schemaFor(file) };
}

export const RECORD_TYPES: RecordType[] = Object.entries(DISCRIMINATORS).map(([key, file]) =>
  build(key, file),
);

// "cell_spec" <-> "cell-spec". The URL wants the dashed form; everything else
// in the record, the schemas and the transform wants the underscored one.
export function slugOf(type: RecordType): string {
  return type.key.replace(/_/g, "-");
}

export function typeForSlug(slug: string): RecordType | undefined {
  return RECORD_TYPES.find((type) => slugOf(type) === slug);
}

// Three kinds of field the author does not own, and what the form does with
// each. None of them is a schema `const`, which is why the tree cannot work
// any of this out for itself.
//
// STAMPED is set by the form: every schema describes schema_version as
// "stamped by the library on save", and every record in examples/** carries
// the same value. The value itself is read from that corpus, never written
// down here -- see lib/schema-version.ts.
//
// DERIVED_IDENTITY is not authored here. docs/identifiers.md: "Records carry
// `id`, `short_id`, and `identifier` -- all derived, never hand-authored. Draft
// inputs omit them; saving canonizes them." Since BIG-MAP/BattINFO#435 the
// package rejects a placeholder outright and mints from the record's natural
// key, so the form offers no identifier rather than inventing one. A record
// opened from a file or a link keeps the one it has (see asDraft).
//
// The third kind -- a schema that constrains nothing about its values -- is
// carried through untouched, and the tree works that one out on its own
// (`controlFor` returns "opaque").
export const STAMPED = ["schema_version"];
export const DERIVED_IDENTITY = ["id", "short_id", "identifier"];

// The record types the package cannot mint an IRI for: nothing in the record
// identifies it, and a random IRI would make every re-run of a save a new
// record, so a save without an id is refused. A new one needs a uid the form
// does not offer, and the page says so. The schemas cannot say which types
// these are, so they are listed, and tests/test_web_snippets.py holds the list
// to what the package does with the records in examples/.
export const NO_NATURAL_KEY = [
  "separator_spec",
  "separator",
  "current_collector_spec",
  "current_collector",
  "electrolyte_spec",
  "electrolyte",
  "housing_spec",
  "housing",
  "equipment_spec",
  "equipment",
];

// Which of three kinds a record is, worked out from the schemas rather than
// listed here.
//
// A specification is a design, and the package names one `<thing>_spec`.
//
// An instance exists because of a record it realizes -- a built electrode, a
// test that ran, a channel of an instrument -- and the schemas say so by
// requiring the IRI that names that record. Its own identity does not count:
// every record requires an `id`, so counting that would make all of them
// instances.
//
// What requires neither stands on its own: a dataset, a parameter set, an
// organization.
export type Family = "spec" | "instance" | "other";

export function familyOf(type: RecordType): Family {
  if (type.key.endsWith("_spec")) return "spec";
  const body = fieldsOf(type.root).find((field) => field.key === type.key);
  const realizes =
    body?.loc !== undefined &&
    fieldsOf(body.loc).some(
      (field) =>
        field.required &&
        !DERIVED_IDENTITY.includes(field.key) &&
        /w3id/.test(String(resolve(field.loc).schema.pattern ?? "")),
    );
  return realizes ? "instance" : "other";
}

/** Dotted paths the form fills in or leaves out, so the tree shows neither. */
export function notAuthored(type: RecordType): string[] {
  return [...STAMPED, ...DERIVED_IDENTITY.map((key) => `${type.key}.${key}`)];
}
