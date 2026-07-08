// Browser/CLI agreement check (CI): the web validator must accept every
// canonical record in the repo's examples/** corpus — the same corpus the
// Python test suite validates — and must reject known-broken records with
// the right verdicts. If Ajv and the Python jsonschema stack ever disagree,
// or the vendored schemas drift, this fails the web build.
//
//   Run: npm run check:agreement   (tsx; repo-side only, never bundled)

import { readdirSync, readFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { validateRecord } from "../lib/validate";

const repoRoot = resolve(__dirname, "..", "..");
const EXAMPLES = resolve(repoRoot, "examples");

// Directories holding CANONICAL records (drafts and profile documents are
// validated differently and are out of scope here).
const RECORD_DIRS = [
  "cell-spec",
  "cell-instance",
  "test-protocol",
  "test",
  "dataset",
  "material-spec",
  "material",
  "electrode-spec",
  "electrode",
  "separator-spec",
  "separator",
  "current-collector-spec",
  "current-collector",
  "electrolyte-spec",
  "electrolyte",
  "housing-spec",
  "housing",
  "equipment-spec",
  "equipment",
  "channel",
  "organization",
];

function* jsonFiles(dir: string): Generator<string> {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) yield* jsonFiles(full);
    else if (entry.name.endsWith(".json")) yield full;
  }
}

let checked = 0;
const failures: string[] = [];

for (const dir of RECORD_DIRS) {
  const root = join(EXAMPLES, dir);
  let files: string[] = [];
  try {
    files = [...jsonFiles(root)];
  } catch {
    continue; // example dir absent — nothing to check
  }
  for (const file of files) {
    checked += 1;
    const result = validateRecord(readFileSync(file, "utf-8"));
    if (!result.ok) {
      const detail = result.issues
        .slice(0, 3)
        .map((i) => `${i.path}: ${i.message}`)
        .join("; ");
      failures.push(`${relative(repoRoot, file)} — ${detail}`);
    }
  }
}

// Known-broken records: the validator must reject each with a verdict a
// human can act on. Mirrors the classic newcomer mistakes.
const BROKEN: { label: string; record: string; expectPath: RegExp }[] = [
  {
    label: "missing schema_version",
    record: JSON.stringify({
      cell_spec: { id: "https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5", name: "X", model: "X", manufacturer: { type: "Organization", name: "A" }, cell_format: "coin", chemistry: "Li-ion" },
      provenance: { source_type: "datasheet" },
    }),
    expectPath: /schema_version/,
  },
  {
    label: "unknown property (typo)",
    record: JSON.stringify({
      schema_version: "0.2.0",
      cell_spec: { id: "https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq8", name: "X", model: "X", manufacture: "Acme", manufacturer: { type: "Organization", name: "A" }, cell_format: "coin", chemistry: "Li-ion" },
      provenance: { source_type: "datasheet" },
    }),
    expectPath: /manufacture/,
  },
  {
    label: "non-IRI id",
    record: JSON.stringify({
      schema_version: "0.2.0",
      cell_spec: { id: "my-cell-1", name: "X", model: "X", manufacturer: { type: "Organization", name: "A" }, cell_format: "coin", chemistry: "Li-ion" },
      provenance: { source_type: "datasheet" },
    }),
    expectPath: /id/,
  },
  {
    label: "bare-number quantity",
    record: JSON.stringify({
      schema_version: "0.2.0",
      cell_spec: { id: "https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5", name: "X", model: "X", manufacturer: { type: "Organization", name: "A" }, cell_format: "coin", chemistry: "Li-ion" },
      properties: { nominal_capacity: 3.4 },
      provenance: { source_type: "datasheet" },
    }),
    expectPath: /nominal_capacity/,
  },
  {
    label: "unknown record type",
    record: JSON.stringify({ schema_version: "0.2.0", future_thing: { id: "x" } }),
    expectPath: /root/,
  },
];

for (const { label, record, expectPath } of BROKEN) {
  const result = validateRecord(record);
  if (result.ok) {
    failures.push(`broken fixture "${label}" was ACCEPTED — validator too lax`);
  } else if (!result.issues.some((i) => expectPath.test(i.path) || expectPath.test(i.message))) {
    failures.push(
      `broken fixture "${label}" rejected, but no issue mentions ${expectPath} — got: ` +
        result.issues.map((i) => i.path).join(", "),
    );
  }
}

if (failures.length > 0) {
  console.error(`Agreement check FAILED (${failures.length} problem(s), ${checked} records checked):`);
  for (const failure of failures) console.error(`  ${failure}`);
  process.exit(1);
}
console.log(`Agreement check passed: ${checked} canonical records valid, ${BROKEN.length} broken fixtures correctly rejected.`);
