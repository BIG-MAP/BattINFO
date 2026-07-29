// Emitter term-drift guard (CI): every JSON-LD @type token the Create-page
// emitter (lib/create-model.ts) can produce must resolve in the hosted records
// context. The context is the same document the package ships
// (src/battinfo/data/context/records.context.v1.json), vendored into
// lib/records-context.generated.ts. Without this check the hand-rolled web
// emitter can silently name a term the context does not define — e.g. emitting
// a property under a class that denotes a different canonical key — and produce
// JSON-LD that expands to the wrong IRI or none at all.
//
//   Run: npm run check:create-model   (tsx; repo-side only, never bundled)

import {
  OBJECT_TYPES,
  SCHEMA_VERSION,
  FORMAT_CLASS,
  CHEMISTRY_CLASS,
  BASIS_ELECTRODE,
  SUBSTANCE,
  MATERIAL_ROLE,
} from "../lib/create-model";
import { recordsContext } from "../lib/records-context.generated";
import { cellSpecCanonical } from "../lib/examples.generated";

const context = (recordsContext as { "@context": Record<string, unknown> })["@context"];
const defined = new Set(Object.keys(context));

// A token is either a bare context term (e.g. "nominal_capacity",
// "MaximumContinuousChargingCurrent") or a CURIE (e.g. "schema:CreativeWork",
// "battinfo:DischargeCapacity"). A CURIE resolves iff its prefix is defined.
function resolves(token: string): boolean {
  if (token.includes(":")) return defined.has(token.split(":", 1)[0]);
  return defined.has(token);
}

// Collect every @type token the emitter's configurable tables can emit: the
// property term map (term ?? key for each PropDef) and the class maps.
const tokens: { where: string; token: string }[] = [];

for (const obj of OBJECT_TYPES) {
  for (const prop of obj.properties ?? []) {
    tokens.push({ where: `${obj.key}.properties[${prop.key}]`, token: prop.term ?? prop.key });
  }
}
const classMaps: [string, Record<string, string>][] = [
  ["FORMAT_CLASS", FORMAT_CLASS],
  ["CHEMISTRY_CLASS", CHEMISTRY_CLASS],
  ["BASIS_ELECTRODE", BASIS_ELECTRODE],
  ["SUBSTANCE", SUBSTANCE],
  ["MATERIAL_ROLE", MATERIAL_ROLE],
];
for (const [name, map] of classMaps) {
  for (const [key, value] of Object.entries(map)) {
    tokens.push({ where: `${name}[${key}]`, token: value });
  }
}

const failures = tokens
  .filter((t) => !resolves(t.token))
  .map((t) => `${t.where} -> "${t.token}" is not a term in records.context.v1.json`);

// schema_version: the emitter's single stamp must equal the synced example
// corpus (examples.generated.ts, synced from examples/** = the package SSoT),
// and every record the builders emit must carry that stamp — no stray literal.
const corpusVersion = (cellSpecCanonical as { schema_version: string }).schema_version;
if (SCHEMA_VERSION !== corpusVersion) {
  failures.push(`SCHEMA_VERSION "${SCHEMA_VERSION}" != example corpus schema_version "${corpusVersion}" (cellSpecCanonical)`);
}
for (const obj of OBJECT_TYPES) {
  const emitted = obj.toRecord(obj.defaults, obj.defaultProperties ?? []);
  const records = Array.isArray(emitted) ? emitted : [emitted];
  for (const record of records) {
    const stamped = (record as { schema_version?: unknown }).schema_version;
    if (stamped !== undefined && stamped !== SCHEMA_VERSION) {
      failures.push(`${obj.key}.toRecord emits schema_version ${JSON.stringify(stamped)}, expected "${SCHEMA_VERSION}"`);
    }
  }
}

if (failures.length > 0) {
  console.error(`Emitter drift check FAILED (${failures.length} problem(s), ${tokens.length} @type tokens checked):`);
  for (const f of failures) console.error(`  ${f}`);
  process.exit(1);
}
console.log(`Emitter drift check passed: ${tokens.length} @type tokens resolve in the records context; schema_version "${SCHEMA_VERSION}" matches the example corpus and every emitted record.`);
