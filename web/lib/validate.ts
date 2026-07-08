// In-browser validation against the REAL canonical JSON Schemas.
//
// The schemas are the same files `battinfo validate` and the registry's
// publish gate use (vendored by scripts/sync-schemas.mjs, drift-checked in
// CI), compiled with Ajv in 2020-12 mode. What this tool says is therefore
// what the library and the registry will say — for the structural layer.
// The Python package additionally runs semantic rules, SHACL, and
// referential-integrity checks that need the full record corpus; those
// layers are out of scope in the browser and are labelled as such in the UI.
//
// Record-type detection mirrors battinfo.entities.ENTITY_KINDS (record_key →
// schema file); tests/test_web_snippets.py asserts this map matches the
// registry, so a new record type cannot ship without the web tool learning it.

import Ajv2020 from "ajv/dist/2020";
import type { ErrorObject, ValidateFunction } from "ajv";
import addFormats from "ajv-formats";
import { schemaFiles } from "./schemas.generated";

export type Severity = "error" | "warning";

export interface Issue {
  severity: Severity;
  path: string;
  message: string;
}

export interface ValidationResult {
  ok: boolean;
  recordType: string | null;
  issues: Issue[];
  parsed?: unknown;
}

// record_key (top-level JSON key) -> schema file. KEEP IN SYNC with
// battinfo.entities.ENTITY_KINDS + the organization record; a Python test
// fails when they diverge.
export const DISCRIMINATORS: Record<string, string> = {
  cell_spec: "cell-spec.schema.json",
  cell_instance: "cell-instance.schema.json",
  test_spec: "test-protocol.schema.json",
  test: "test.schema.json",
  dataset: "dataset.schema.json",
  material_spec: "material-spec.schema.json",
  material: "material.schema.json",
  electrode_spec: "electrode-spec.schema.json",
  electrode: "electrode.schema.json",
  separator_spec: "separator-spec.schema.json",
  separator: "separator.schema.json",
  current_collector_spec: "current-collector-spec.schema.json",
  current_collector: "current-collector.schema.json",
  electrolyte_spec: "electrolyte-spec.schema.json",
  electrolyte: "electrolyte.schema.json",
  housing_spec: "housing-spec.schema.json",
  housing: "housing.schema.json",
  equipment_spec: "equipment-spec.schema.json",
  equipment: "equipment.schema.json",
  channel: "channel.schema.json",
  organization: "organization.schema.json",
};

let ajvInstance: Ajv2020 | null = null;
const compiled = new Map<string, ValidateFunction>();

function ajv(): Ajv2020 {
  if (ajvInstance) return ajvInstance;
  const instance = new Ajv2020({
    allErrors: true,
    strict: false, // the canonical schemas are the contract; don't re-lint them
  });
  addFormats(instance);
  for (const { schema } of schemaFiles) {
    if (typeof schema.$id === "string") instance.addSchema(schema);
  }
  ajvInstance = instance;
  return instance;
}

function validatorFor(schemaFile: string): ValidateFunction {
  const cached = compiled.get(schemaFile);
  if (cached) return cached;
  const id = `https://w3id.org/battinfo/schema/${schemaFile}`;
  const fn = ajv().getSchema(id);
  if (!fn) throw new Error(`Schema not vendored: ${schemaFile} (run npm run sync:schemas)`);
  compiled.set(schemaFile, fn);
  return fn;
}

function dotted(instancePath: string): string {
  const path = instancePath
    .split("/")
    .filter(Boolean)
    .map((part) => part.replace(/~1/g, "/").replace(/~0/g, "~"))
    .join(".");
  return path || "(root)";
}

// Translate Ajv's error vocabulary into messages that teach, mirroring the
// library's "errors name the fix" policy.
function toIssue(error: ErrorObject): Issue {
  const basePath = dotted(error.instancePath);
  if (error.keyword === "required") {
    const missing = (error.params as { missingProperty: string }).missingProperty;
    const path = basePath === "(root)" ? missing : `${basePath}.${missing}`;
    return { severity: "error", path, message: `Missing required property \`${missing}\`.` };
  }
  if (error.keyword === "additionalProperties") {
    const extra = (error.params as { additionalProperty: string }).additionalProperty;
    const path = basePath === "(root)" ? extra : `${basePath}.${extra}`;
    return {
      severity: "error",
      path,
      message: `Unknown property \`${extra}\` — not part of the record contract (typo?).`,
    };
  }
  if (error.keyword === "pattern" && basePath.endsWith(".id")) {
    return {
      severity: "error",
      path: basePath,
      message: "`id` is not a canonical w3id.org/battinfo/{type}/{uid} IRI.",
    };
  }
  if (error.keyword === "type" && error.message?.includes("object") && /properties\.[a-z_]+$/.test(basePath)) {
    return {
      severity: "error",
      path: basePath,
      message: `${error.message} — quantities are objects like { "value": 2.5, "unit": "Ah" }, never bare numbers.`,
    };
  }
  return { severity: "error", path: basePath, message: error.message ?? error.keyword };
}

/** Detect the record type from its top-level discriminator key. */
export function detectRecordType(record: Record<string, unknown>): string | null {
  for (const key of Object.keys(DISCRIMINATORS)) {
    const value = record[key];
    if (typeof value === "object" && value !== null && !Array.isArray(value)) return key;
  }
  return null;
}

const PYTHON_HINT = /^\s*(from\s+\w|import\s+\w|def\s+\w|\w+\s*=\s*(battinfo\.|CellSpec\(|Cell\(|TestSpec\(|Test\(|Dataset\())/m;

/** Validate a canonical BattINFO record (as JSON text) against the real schemas. */
export function validateRecord(raw: string): ValidationResult {
  let doc: unknown;
  try {
    doc = JSON.parse(raw);
  } catch (e) {
    // Python authoring code is a common honest mistake — point at the record.
    if (PYTHON_HINT.test(raw)) {
      return {
        ok: false,
        recordType: null,
        issues: [{
          severity: "error",
          path: "(root)",
          message:
            "This looks like Python authoring code. The validator checks the JSON record it produces — " +
            "run record = spec.to_record() (or ws.save(), which validates for you) and paste the JSON here.",
        }],
      };
    }
    return {
      ok: false,
      recordType: null,
      issues: [{ severity: "error", path: "(root)", message: `Invalid JSON: ${(e as Error).message}` }],
    };
  }

  // JSON-LD is the *published* form; schemas validate the canonical record.
  if (typeof doc === "object" && doc !== null && !Array.isArray(doc)
      && ("@context" in doc || "@graph" in doc)) {
    return {
      ok: false,
      recordType: null,
      issues: [{
        severity: "error",
        path: "(root)",
        message:
          "This is a JSON-LD document (it carries @context/@graph) — the published form, generated from a canonical record. " +
          "Paste the canonical record JSON to validate it here; for JSON-LD-level checks (RDF parse, term resolution), " +
          "run battinfo.validate_record_report / the publish pipeline locally, which validates both layers.",
      }],
      parsed: doc,
    };
  }

  if (typeof doc !== "object" || doc === null || Array.isArray(doc)) {
    return {
      ok: false,
      recordType: null,
      issues: [{ severity: "error", path: "(root)", message: "A record must be a JSON object." }],
    };
  }

  const record = doc as Record<string, unknown>;
  const recordType = detectRecordType(record);
  if (recordType === null) {
    // Fail closed, exactly like the registry's publish gate: a payload we
    // cannot match to a schema must not be waved through.
    const known = Object.keys(DISCRIMINATORS).join(", ");
    return {
      ok: false,
      recordType: null,
      issues: [
        {
          severity: "error",
          path: "(root)",
          message: `No known record type found. A canonical record carries one of: ${known}.`,
        },
      ],
      parsed: doc,
    };
  }

  const validate = validatorFor(DISCRIMINATORS[recordType]);
  const valid = validate(doc) as boolean;
  const issues = (validate.errors ?? []).map(toIssue);
  return { ok: valid, recordType, issues, parsed: doc };
}
