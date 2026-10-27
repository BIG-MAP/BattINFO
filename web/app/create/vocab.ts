// Which fields get which vocabulary.
//
// A unit or an electrode basis is a plain string as far as JSON Schema is
// concerned, but the package keeps curated terms for both in
// assets/mappings/domain-battery/ -- the same tables the JSON-LD transform
// reads. Those files sit outside web/, so scripts/sync-vocab.mjs embeds them;
// nothing here is hand-copied.
//
// These are suggestions, never restrictions: the schema does allow other
// values, and a datalist offers without forbidding.

export { MATERIAL_SYMBOLS, PROPERTY_KEYS, UNIT_SYMBOLS } from "@/lib/vocab.generated";

export const UNIT_LIST = "vocab-units";
export const MATERIAL_LIST = "vocab-materials";
export const PROPERTY_LIST = "vocab-properties";

// The one place a field name is bound to a vocabulary. The schemas offer no
// structural marker for "this holds a unit", so the binding has to be written
// down; keeping it to one visible table is the most honest form available.
export const SUGGESTS: Record<string, string> = {
  unit: UNIT_LIST,
  unit_code: UNIT_LIST,
  positive_electrode_basis: MATERIAL_LIST,
  negative_electrode_basis: MATERIAL_LIST,
};
