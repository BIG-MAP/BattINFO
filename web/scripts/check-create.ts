// The Create page derives its form from the schemas, which is only a guarantee
// while the derivation actually works. This runs the page's own modules -- not a
// copy of them -- over every record type the site knows and fails on anything
// the form would silently render as nothing, crash on, or quietly rewrite.
//
//   Run / CI:   npm run check:create
//
// Companion to check-agreement, which asks the same corpus a different
// question: that one says the validator agrees with the library, this one
// says the form can show what the library wrote.

import { readdirSync, readFileSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { dirname, resolve as resolvePath } from "node:path";
import { fileURLToPath } from "node:url";
import { blankFor, controlFor, fieldsOf, isDeprecated, join, type Located } from "../app/create/schema";
import { MAX_LINKED_BYTES, asDraft, asTemplate, findingsFor, readFragment, sanitize } from "../app/create/load";
import { SCHEMA_VERSION } from "../lib/schema-version";
import {
  DERIVED_IDENTITY,
  RECORD_TYPES,
  familyOf,
  notAuthored,
  slugOf,
  typeForSlug,
} from "../app/create/types";
import { TEMPLATES } from "../lib/templates.generated";
import { detectRecordType, validateRecordAs } from "../lib/validate";

type Obj = Record<string, unknown>;

const failures: string[] = [];
const fail = (message: string) => failures.push(message);

// Every place a value's shape and the control drawn for it disagree. An array
// control calls .map on what it is given, so an object there is a blank page;
// a text control stringifies a list into "a,b" and loses it on the next edit.
function unrenderable(value: unknown, loc: Located, path = "", depth = 0): string[] {
  if (depth > 10 || value === null || value === undefined) return [];
  const control = controlFor(loc, value);
  const at = path || "(root)";
  if (control.kind === "array") {
    if (!Array.isArray(value)) return [`${at} holds ${typeof value}, but its control is a list`];
    return value.flatMap((item, i) => unrenderable(item, control.items, `${path}[${i}]`, depth + 1));
  }
  if (Array.isArray(value)) return [`${at} holds a list, but its control is ${control.kind}`];
  if (typeof value !== "object") return [];
  if (control.kind === "map") {
    return Object.entries(value as Obj).flatMap(([key, item]) =>
      unrenderable(item, control.values, join(path, key), depth + 1),
    );
  }
  if (control.kind !== "object") return [];
  const known = new Map(fieldsOf(loc, value).map((field) => [field.key, field.loc]));
  return Object.entries(value as Obj).flatMap(([key, item]) => {
    const child = known.get(key);
    return child ? unrenderable(item, child, join(path, key), depth + 1) : [];
  });
}

// Every field the form could ever draw for this type, following refs once per
// distinct target so a self-referential schema terminates.
function walk(loc: Located, path: string, seen: Set<string>, visit: (path: string, loc: Located) => void) {
  const key = `${loc.file}|${JSON.stringify(loc.schema).length}|${path.split(".").at(-1)}`;
  if (seen.has(key)) return;
  seen.add(key);
  visit(path, loc);
  const control = controlFor(loc);
  if (control.kind === "array") return walk(control.items, `${path}[]`, seen, visit);
  if (control.kind === "map") return walk(control.values, `${path}.*`, seen, visit);
  if (control.kind !== "object") return;
  for (const field of fieldsOf(loc)) walk(field.loc, path ? `${path}.${field.key}` : field.key, seen, visit);
}

// 1. Every record type resolves, and the URL it lives at round-trips.
for (const type of RECORD_TYPES) {
  if (typeForSlug(slugOf(type))?.key !== type.key) fail(`${type.key}: slug ${slugOf(type)} does not resolve back`);
  if (!type.root.schema) fail(`${type.key}: no schema behind ${type.root.file}`);
}

// 2. Every field the form can reach renders as some control. "unsupported" is
//    an honest dead end in the code and an invisible field on the page: a
//    record could carry a value nobody can see or edit.
for (const type of RECORD_TYPES) {
  walk(type.root, "", new Set(), (path, loc) => {
    if (controlFor(loc).kind === "unsupported") fail(`${type.key}: no control for ${path || "(root)"}`);
  });
}

// 3. And every container can actually hold something. Having *a* control is not
//    enough: an object whose field list comes back empty draws a section that
//    opens onto nothing, and on upload every key under it is dropped as
//    unknown. This is the shape that lost a test protocol's conditions and
//    setpoints, and the eight union-typed fields (cell_spec.brand among them)
//    where the control said "object" and the field list disagreed.
for (const type of RECORD_TYPES) {
  walk(type.root, "", new Set(), (path, loc) => {
    if (controlFor(loc).kind === "object" && fieldsOf(loc).length === 0) {
      fail(`${type.key}: ${path || "(root)"} is a section with no fields in it`);
    }
  });
}

// 4. A blank draft is buildable for every type. blankFor recurses through
//    required fields, so a required cycle would hang the page instead.
for (const type of RECORD_TYPES) {
  try {
    if (typeof blankFor(type.root) !== "object") fail(`${type.key}: blankFor did not build an object`);
  } catch (error) {
    fail(`${type.key}: blankFor threw — ${(error as Error).message}`);
  }
}

// 5. The form never offers an identifier. Since BIG-MAP/BattINFO#435 the
//    package rejects a placeholder and mints from the record's natural key, so
//    a row that let someone type one would be a row that produces a rejected
//    record. The schemas do define these fields, so only `notAuthored` keeps
//    them off the page -- this is what fails if that list is ever trimmed.
for (const type of RECORD_TYPES) {
  const hidden = notAuthored(type);
  for (const key of DERIVED_IDENTITY) {
    const body = fieldsOf(type.root).find((field) => field.key === type.key);
    const present = body?.loc && fieldsOf(body.loc).some((field) => field.key === key);
    if (present && !hidden.includes(`${type.key}.${key}`)) {
      fail(`${type.key}: ${key} is a schema field the form would let someone author`);
    }
  }
  if (!hidden.includes("schema_version")) fail(`${type.key}: schema_version is not stamped`);
}

// 6. Every template is a record the form can actually open: it validates, it
//    belongs to a type the form offers, and loading it drops nothing.
for (const template of TEMPLATES) {
  const record = template.record as Obj;
  const key = detectRecordType(record);
  const type = RECORD_TYPES.find((candidate) => candidate.key === key);
  if (!type) {
    fail(`template ${template.slug}: no record type the form offers`);
    continue;
  }
  const result = validateRecordAs(JSON.stringify(record), type.key);
  if (!result.ok) fail(`template ${template.slug}: invalid — ${result.issues[0]?.message}`);

  const removed: string[] = [];
  const loaded = sanitize(record, type.root, "", removed);
  if (removed.length) fail(`template ${template.slug}: loading it would drop ${removed.join(", ")}`);
  const reloaded = validateRecordAs(JSON.stringify(loaded), type.key);
  if (!reloaded.ok) fail(`template ${template.slug}: invalid once loaded — ${reloaded.issues[0]?.message}`);

  // 7. And picking it hands over a starting point, not a published record:
  //    of the provenance, only the kind of source survives, and the
  //    template's own IRI stays behind so saving mints the new record's.
  const started = asTemplate(structuredClone(record), type) as Obj;
  const kept = Object.keys((started.provenance ?? {}) as Obj).filter((key) => key !== "source_type");
  if (kept.length) fail(`template ${template.slug}: keeps the source record's provenance (${kept.join(", ")})`);
  const startedBody = (started[type.key] ?? {}) as Obj;
  for (const key of ["id", "short_id"]) {
    if (key in startedBody) fail(`template ${template.slug}: hands over the template's ${key}`);
  }
}

// 8. Whatever way a draft enters, it gets the current schema_version (not
//    whatever an older file carried). A record opened from a file keeps its
//    identity, so saving it again updates that record instead of minting
//    another; the all-zero placeholder, which the package refuses, does not.
//    A template drops its IRI but not an identifier of the author's own, such
//    as a dataset's DOI.
for (const type of RECORD_TYPES) {
  const body = fieldsOf(type.root).find((field) => field.key === type.key);
  const defined = DERIVED_IDENTITY.filter((key) => body?.loc && fieldsOf(body.loc).some((f) => f.key === key));
  const identity: Obj = {
    id: "https://w3id.org/battinfo/id/1001/spec/aaaa-bbbb-cccc-dddd",
    short_id: "aaaabb",
    identifier: "x:aaaa-bbbb-cccc-dddd",
  };

  const draft = asDraft({ schema_version: "0.0.1", [type.key]: { ...identity } }, type) as Obj;
  const opened = (draft[type.key] ?? {}) as Obj;
  for (const key of defined) {
    if (opened[key] !== identity[key]) fail(`${type.key}: an opened record lost its ${key}`);
  }
  if (draft.schema_version !== SCHEMA_VERSION) {
    fail(`${type.key}: asDraft left schema_version at ${String(draft.schema_version)}`);
  }

  const placeholder = asDraft(
    {
      [type.key]: {
        id: "https://w3id.org/battinfo/id/1001/spec/0000-0000-0000-0000",
        short_id: "000000",
        identifier: "x:0000-0000-0000-0000",
      },
    },
    type,
  ) as Obj;
  for (const key of DERIVED_IDENTITY) {
    if (key in ((placeholder[type.key] ?? {}) as Obj)) fail(`${type.key}: asDraft kept the placeholder ${key}`);
  }

  // The form excuses a missing id, never a wrong one.
  const wrong = asDraft({ [type.key]: { id: "not-an-iri" } }, type) as Obj;
  const reported = findingsFor(validateRecordAs(JSON.stringify(wrong), type.key).issues, type);
  if (!reported.some((issue) => issue.path === `${type.key}.id`)) fail(`${type.key}: a malformed id goes unreported`);

  if (defined.includes("identifier")) {
    const own = asTemplate({ [type.key]: { ...identity, identifier: "doi:10.5281/zenodo.1234567" } }, type) as Obj;
    if (((own[type.key] ?? {}) as Obj).identifier !== "doi:10.5281/zenodo.1234567") {
      fail(`${type.key}: a template dropped an identifier that was not derived from its IRI`);
    }
  }
}

// 9. Whatever a draft holds is a shape the tree can draw. The schemas say "one
//    X or a list of X" in several places and the tree renders whichever shape
//    the union resolved to, so a lone value where it expects a list is a blank
//    page, not a mis-rendered row. Checking only that nothing was *dropped*
//    missed this: seven of the nine templates loaded without losing a field
//    and still crashed on pick, because the template path reached the tree
//    without going through sanitize.
for (const template of TEMPLATES) {
  const record = template.record as Obj;
  const type = RECORD_TYPES.find((candidate) => candidate.key === detectRecordType(record));
  if (!type) continue;
  for (const [how, draft] of [
    ["picked as a template", asTemplate(structuredClone(record), type)],
    ["uploaded as a file", asDraft(sanitize(structuredClone(record), type.root) as Obj, type)],
  ] as const) {
    for (const where of unrenderable(draft, type.root)) {
      fail(`template ${template.slug} ${how}: ${where}`);
    }
  }
}

// 10. A field that is "one X or a list of X" (an electrolyte's solvent) keeps a
//    list, and keeps a lone X as a one-item list. Reading only the single
//    branch dropped every list on load.
{
  const cellSpec = RECORD_TYPES.find((type) => type.key === "cell_spec")!;
  const solvents = (solvent: unknown) => {
    const removed: string[] = [];
    const out = sanitize({ electrolyte: { family: "organic", solvent } }, cellSpec.root, "", removed) as Obj;
    return { removed, kept: ((out.electrolyte ?? {}) as Obj).solvent };
  };
  const list = solvents([{ name: "EC" }, { name: "EMC" }]);
  if (list.removed.length) fail(`a solvent list loses ${list.removed.join(", ")} on load`);
  const single = solvents({ name: "EC" });
  if (JSON.stringify(single.kept) !== JSON.stringify([{ name: "EC" }])) {
    fail(`a single solvent loads as ${JSON.stringify(single.kept)}, not a one-item list`);
  }
}

// 11. A manufacturer is "a name, or an organization holding that name": the
//     form edits the organization, so its IRIs survive and a plain name loads
//     as that organization.
{
  const cellSpec = RECORD_TYPES.find((type) => type.key === "cell_spec")!;
  const maker = (manufacturer: unknown) => {
    const out = sanitize({ separator: { material: "PP", manufacturer } }, cellSpec.root, "", []) as Obj;
    return ((out.separator ?? {}) as Obj).manufacturer;
  };
  const org = { name: "Celgard", same_as: "http://www.wikidata.org/entity/Q122199856" };
  if (JSON.stringify(maker(org)) !== JSON.stringify(org)) fail(`an organization manufacturer loads as ${JSON.stringify(maker(org))}`);
  if (JSON.stringify(maker("Celgard")) !== JSON.stringify({ name: "Celgard" })) {
    fail(`a manufacturer name loads as ${JSON.stringify(maker("Celgard"))}, not an organization`);
  }

  // A brand is a Brand or an Organization, and only the second has `same_as`.
  // The form reads whichever one the record holds, by its `type` or by the
  // keys it has, so neither loses anything on open; a new brand is a Brand.
  const brand = (value: unknown) => {
    const removed: string[] = [];
    const out = sanitize({ cell_spec: { brand: value } }, cellSpec.root, "", removed) as Obj;
    return { removed, kept: ((out.cell_spec ?? {}) as Obj).brand };
  };
  const wikidata = "http://www.wikidata.org/entity/Q1"; // illustrative
  for (const value of [
    { type: "Organization", name: "Duracell", same_as: wikidata },
    { name: "Duracell", same_as: wikidata },
    { type: "Brand", name: "Duracell", url: "https://www.duracell.com" },
  ]) {
    const { removed, kept } = brand(value);
    if (removed.length || JSON.stringify(kept) !== JSON.stringify(value)) {
      fail(`brand ${JSON.stringify(value)} loads as ${JSON.stringify(kept)}, dropping ${removed.join(", ") || "nothing"}`);
    }
  }
  const body = fieldsOf(cellSpec.root).find((field) => field.key === "cell_spec");
  const brandField = body && fieldsOf(body.loc).find((field) => field.key === "brand");
  if (!brandField || (blankFor(brandField.loc) as Obj).type !== "Brand") fail("a new brand no longer starts as a Brand");
}

// 12. And the whole corpus opens, not just the nine templates. Every canonical
//     record the repo ships is loaded the way an upload would be: it must lose
//     nothing, come out as a shape the tree can draw, and still validate with only what
//     the form excuses (findingsFor) set aside. The same corpus check-agreement
//     runs, asked a different question -- that one says the validator agrees
//     with the library, this one says the form can show what the library
//     wrote.
{
  const repoRoot = resolvePath(dirname(fileURLToPath(import.meta.url)), "..", "..");
  const files: string[] = [];
  (function walk(dir: string) {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const at = resolvePath(dir, entry.name);
      if (entry.isDirectory()) walk(at);
      else if (entry.name.endsWith(".json")) files.push(at);
    }
  })(resolvePath(repoRoot, "examples"));

  let opened = 0;
  for (const file of files) {
    let record: Obj;
    try {
      record = JSON.parse(readFileSync(file, "utf-8")) as Obj;
    } catch {
      continue; // not a record; check-agreement owns malformed JSON
    }
    const type = RECORD_TYPES.find((candidate) => candidate.key === detectRecordType(record));
    if (!type) continue;
    opened++;
    const name = file.slice(repoRoot.length + 1).split("\\").join("/");
    // Opening it drops nothing: every key the package wrote is one the form
    // has a place for.
    const removed: string[] = [];
    sanitize(structuredClone(record), type.root, "", removed);
    if (removed.length) fail(`${name}: opening it would drop ${removed.join(", ")}`);
    const draft = asDraft(record, type) as Obj;
    for (const where of unrenderable(draft, type.root)) fail(`${name}: ${where}`);
    const report = validateRecordAs(JSON.stringify(draft), type.key);
    const real = findingsFor(report.issues, type);
    if (real.length) fail(`${name}: invalid once loaded — ${real[0].path} ${real[0].message}`);
  }
  if (opened < 100) fail(`only ${opened} corpus records were opened; the walk found too few`);
  console.log(`  corpus: ${opened} records open as drafts the tree can draw.`);
}


// 13. isDeprecated reads the schemas' own convention instead of holding a
//     list, so the thing that can rot is the convention. Every property whose
//     description mentions deprecation must be one the predicate catches,
//     otherwise a spelling the project has moved off quietly returns to the
//     "add" list beside the current one -- which is how `legalName` came to
//     sit next to `legal_name` with nothing to tell them apart.
{
  let deprecated = 0;
  for (const type of RECORD_TYPES) {
    walk(type.root, type.key, new Set(), (path, loc) => {
      if (controlFor(loc).kind !== "object") return;
      for (const field of fieldsOf(loc)) {
        if (!/deprecat/i.test(field.help ?? "")) continue;
        if (isDeprecated(field)) deprecated++;
        else fail(`${path}.${field.key}: reads as deprecated but isDeprecated misses it`);
      }
    });
  }
  if (deprecated === 0) fail("no deprecated property was found at all; the convention moved");
}

// 14. The Create page offers the record types in three groups, and works out
//     which group a type belongs to from the schemas: a specification by its
//     name, an instance by requiring the IRI of the record it realizes,
//     everything else by requiring neither. Nothing is listed, so nothing can
//     be forgotten -- but a schema that stopped requiring such a reference
//     would move a type to another heading silently. Each group must keep at
//     least one type, and the instances must be the records that name
//     something: these are the ones whose grouping is a judgement the schemas
//     make, not a spelling.
{
  const held = new Map<string, string[]>();
  for (const type of RECORD_TYPES) {
    const family = familyOf(type);
    held.set(family, [...(held.get(family) ?? []), type.key]);
  }
  for (const family of ["spec", "instance", "other"]) {
    if (!held.get(family)?.length) fail(`the Create page's "${family}" group came out empty`);
  }
  const counted = [...held.values()].reduce((total, keys) => total + keys.length, 0);
  if (counted !== RECORD_TYPES.length) {
    fail(`grouping covered ${counted} of ${RECORD_TYPES.length} record types`);
  }
  // A cell realizes a spec; a dataset realizes nothing. If either moves, the
  // rule behind the headings has changed and the copy under them is wrong.
  if (familyOf(typeForSlug("cell-instance")!) !== "instance") fail("a cell instance is no longer an instance");
  if (familyOf(typeForSlug("dataset")!) !== "other") fail("a dataset is now grouped as an instance");
  if (familyOf(typeForSlug("cell-spec")!) !== "spec") fail("a cell spec is no longer a specification");
  console.log(
    `  groups: ${["spec", "instance", "other"].map((f) => `${held.get(f)!.length} ${f}`).join(", ")}.`,
  );
}

// 15. A link can carry a record. `/create/<type>#record=<base64url of gzipped
//     JSON>` is a format another tool writes, so it is pinned here rather
//     than left to drift: a record encoded the documented way comes back out
//     intact, through the same intake an upload uses, and a link that carries
//     nothing readable, or too much, is refused rather than silently ignored.
async function checkTheLinkFormat(): Promise<void> {
  const type = RECORD_TYPES.find((candidate) => candidate.key === "cell_spec")!;
  const source = TEMPLATES.find((template) => template.slug === "coin-detailed")!.record as Obj;
  const encoded = gzipSync(Buffer.from(JSON.stringify(source))).toString("base64url");

  const loaded = await readFragment(`#record=${encoded}`, type);
  if (!loaded) {
    fail("a link carrying a record read as carrying none");
  } else {
    if (loaded.removed.length) fail(`a linked record lost ${loaded.removed.join(", ")}`);
    // What the page makes of it. A linked record is a record that exists, so
    // it keeps its IRI exactly as an opened file does.
    const draft = asDraft(loaded.record, type) as Obj;
    const sourceId = ((source[type.key] ?? {}) as Obj).id;
    if (!sourceId) fail("the template the link check encodes has no id to keep");
    else if (((draft[type.key] ?? {}) as Obj).id !== sourceId) fail("a record opened from a link lost its id");
    if (!String((draft[type.key] as Obj)?.name ?? "")) fail("a record opened from a link lost its name");
    for (const where of unrenderable(draft, type.root)) {
      fail(`a record opened from a link is unrenderable: ${where}`);
    }
  }

  if ((await readFragment("#other=1", type)) !== null) fail("a fragment with no record returned one");

  // Each bad link is refused with its own reason, which the page shows.
  const refusal = async (fragment: string): Promise<string | null> => {
    try {
      await readFragment(fragment, type);
      return null;
    } catch (error) {
      return (error as Error).message;
    }
  };
  if (!(await refusal("#record=not-gzipped-at-all"))) fail("a link whose record cannot be decoded was accepted");
  const notJson = await refusal(`#record=${gzipSync(Buffer.from("not json")).toString("base64url")}`);
  if (!notJson?.includes("not valid JSON")) fail(`a link holding text that is not JSON gave: ${notJson}`);
  // Six megabytes of spaces gzip to a few kilobytes: the shape of a link
  // that would otherwise inflate until the tab ran out of memory.
  const bomb = gzipSync(Buffer.alloc(MAX_LINKED_BYTES + 1_000_000, 0x20)).toString("base64url");
  const tooBig = await refusal(`#record=${bomb}`);
  if (!tooBig?.includes("larger than")) fail(`a link that inflates past the cap gave: ${tooBig}`);
}

// The only asynchronous check, so the verdict waits for it. tsx compiles this
// file to CJS, where a top-level await is not available.
void checkTheLinkFormat().then(() => {
  if (failures.length) {
    console.error(`check:create — ${failures.length} problem(s):`);
    for (const message of failures) console.error(`  • ${message}`);
    process.exit(1);
  }
  console.log(
    `check:create — ${RECORD_TYPES.length} record types render, ${TEMPLATES.length} templates open clean.`,
  );
});
