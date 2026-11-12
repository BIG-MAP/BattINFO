// Which fields get which vocabulary.
//
// A unit or an electrode basis is a plain string as far as JSON Schema is
// concerned, but the package keeps curated terms for both in
// assets/mappings/domain-battery/ -- the same tables the JSON-LD transform
// reads. Those files sit outside web/, so scripts/sync-vocab.mjs embeds them.
// The condition and setpoint keys further down are kept by hand, and a test
// holds them to the package.
//
// These are suggestions, never restrictions: the schema does allow other
// values, and a datalist offers without forbidding.

import { PROPERTY_KEYS } from "@/lib/vocab.generated";

export { NEGATIVE_BASES, POSITIVE_BASES, UNIT_SYMBOLS } from "@/lib/vocab.generated";

export const UNIT_LIST = "vocab-units";
export const POSITIVE_LIST = "vocab-positive-bases";
export const NEGATIVE_LIST = "vocab-negative-bases";

// The one place a field name is bound to a vocabulary. The schemas offer no
// structural marker for "this holds a unit", so the binding has to be written
// down; keeping it to one visible table is the most honest form available.
export const SUGGESTS: Record<string, string> = {
  unit: UNIT_LIST,
  unit_code: UNIT_LIST,
  positive_electrode_basis: POSITIVE_LIST,
  negative_electrode_basis: NEGATIVE_LIST,
};

// A map's entry names are the author's, so its add menu offers the names the
// package knows for that map: property keys for a property bag, and for
// conditions and setpoints the keys the JSON-LD transform gives an EMMO class
// (any other name is published as a bare label). Those keys live in Python
// tables, so they are listed here and tests/test_web_snippets.py holds each
// list to its table. Other spellings the tables tolerate are left out.

/** A test step's setpoints: the setpoints in data/vocab/test-method/quantities.json. */
export const SETPOINT_KEYS = ["c_rate", "current", "current_density", "power", "resistance", "voltage"];

/** A test protocol's conditions: the keys of jsonld.TEST_CONDITION_CLASS. */
export const PROTOCOL_CONDITION_KEYS = [
  "ambient_temperature",
  "applied_pressure",
  "c_rate",
  "charging_current",
  "charging_cutoff_voltage",
  "current",
  "discharging_current",
  "discharging_cutoff_voltage",
  "duration",
  "initial_state_of_charge",
  "lower_voltage_limit",
  "number_of_iterations",
  "state_of_charge",
  "temperature",
  "upper_voltage_limit",
  "voltage",
];

/** Any other conditions -- a test's, or those a value was stated or measured
 *  under: the keys of json_to_jsonld._MEASUREMENT_PARAMETER_TERMS, and
 *  voltage_reference, which both emitters read as the electrode couple. */
export const CONDITION_KEYS = [
  "ambient_temperature",
  "applied_pressure",
  "c_rate",
  "charging_c_rate",
  "current",
  "current_density",
  "discharging_c_rate",
  "initial_state_of_charge",
  "lower_voltage_limit",
  "state_of_charge",
  "temperature",
  "upper_voltage_limit",
  "voltage",
  "voltage_reference",
];

/** The names offered for a new entry in the map held by the field `key`,
 *  defined in the schema file `file`. */
export function entryNames(key: string, file: string): string[] {
  if (key === "property") return PROPERTY_KEYS;
  if (key === "setpoints") return SETPOINT_KEYS;
  if (key === "conditions") return file === "test-protocol.schema.json" ? PROTOCOL_CONDITION_KEYS : CONDITION_KEYS;
  return [];
}
