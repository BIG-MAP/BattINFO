// Unit checks for the JSON-LD workbench core (lib/jsonld-workbench).
//
// No test framework is vendored for web/; like check-agreement.ts this is a
// plain tsx script that asserts and exits non-zero on failure.
//
//   Run: npm run check:workbench
//
// It exercises the three fixtures called out in the PR: one canonical example,
// one deliberately broken document, and one hand-written legacy-style document
// (same terms, different nesting, hosted @context by URL).

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import jsonld from "jsonld";
import {
  runJsonLdLayers,
  offlineDocumentLoader,
  parseJson,
  checkSemantics,
  checkWellFormedness,
  effectiveContext,
  extractSummary,
  type JsonLdLib,
} from "../lib/jsonld-workbench";
import { RECORDS_CONTEXT_URL } from "../lib/records-context.generated";

const lib = jsonld as unknown as JsonLdLib;
const webRoot = resolve(__dirname, "..");
const failures: string[] = [];

function check(name: string, fn: () => Promise<void> | void): Promise<void> {
  return Promise.resolve()
    .then(fn)
    .then(() => console.log(`  ok  ${name}`))
    .catch((e) => {
      failures.push(`${name}: ${(e as Error).message}`);
      console.error(`FAIL  ${name}`);
    });
}

async function main() {
  // 1. Offline loader resolves our context and refuses everything else.
  await check("offline loader resolves the hosted context URL", async () => {
    const loader = offlineDocumentLoader();
    const res = await loader(RECORDS_CONTEXT_URL);
    assert.ok(res.document && typeof res.document === "object");
  });
  await check("offline loader refuses unknown URLs (no network)", async () => {
    const loader = offlineDocumentLoader();
    await assert.rejects(() => loader("https://example.com/whatever.json"));
  });

  // 2. Canonical example: clean across every layer.
  await check("canonical example expands, frames, and is semantically clean", async () => {
    const raw = readFileSync(resolve(webRoot, "public/jsonld/cell-spec.jsonld"), "utf-8");
    const out = await runJsonLdLayers(raw, lib);
    assert.ok(out.framed, "expected a framed canonical view");
    assert.equal(out.expandError, null);
    const wfErrors = out.wellFormedness.filter((i) => i.severity === "error");
    assert.equal(wfErrors.length, 0, `unexpected well-formedness errors: ${JSON.stringify(wfErrors)}`);
    const semErrors = out.semantic.filter((i) => i.severity === "error");
    assert.equal(semErrors.length, 0, `unexpected semantic errors: ${JSON.stringify(semErrors)}`);
  });

  // 3. Broken document: no @context, garbage type.
  await check("broken document (no @context) is flagged by the well-formedness layer", async () => {
    const raw = JSON.stringify({ "@type": "NotARealType", name: "x" });
    const out = await runJsonLdLayers(raw, lib);
    const wf = out.wellFormedness.filter((i) => i.severity === "error");
    assert.ok(
      wf.some((i) => /no @context/i.test(i.message)),
      `expected a 'no @context' error, got ${JSON.stringify(out.wellFormedness)}`,
    );
  });

  // 4. Hand-written legacy doc: same terms, different nesting, @context by URL.
  //    It must still expand offline and produce a canonical view.
  await check("hand-written doc referencing the hosted context expands offline", async () => {
    const raw = JSON.stringify({
      "@context": RECORDS_CONTEXT_URL,
      "@type": "BatteryCellSpecification",
      "@id": "https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5",
      name: "Legacy cell",
      // A quantity nested a different way than the canonical emitter does:
      hasProperty: [
        { "@type": "NominalCapacity", hasNumericalPart: { hasNumberValue: 2.5 }, hasMeasurementUnit: "Ah" },
      ],
    });
    const out = await runJsonLdLayers(raw, lib);
    assert.equal(out.expandError, null, `expand failed: ${out.expandError}`);
    assert.ok(out.framed, "expected a framed canonical view for the legacy doc");
    assert.ok(out.expanded && out.expanded.length > 0, "expected a non-empty expanded graph");
  });

  // 5. Undefined-term warning: an unknown key is surfaced, never dropped.
  await check("undefined terms are surfaced as warnings", async () => {
    const raw = JSON.stringify({
      "@context": RECORDS_CONTEXT_URL,
      "@type": "BatteryCellSpecification",
      not_a_real_term: 5,
    });
    const parse = parseJson(raw);
    assert.ok(parse.doc);
    const wf = checkWellFormedness(parse.doc, [{}], null);
    assert.ok(
      wf.some((i) => i.severity === "warning" && /not_a_real_term/.test(i.message)),
      `expected an undefined-term warning, got ${JSON.stringify(wf)}`,
    );
  });

  // 6. Semantic: bad @id and a unit-less quantity are caught.
  await check("semantic layer flags a non-canonical @id and a missing unit", () => {
    const framed = {
      "@id": "https://w3id.org/battinfo/spec/not-a-real-uid",
      hasProperty: [{ "@type": "Mass", hasNumericalPart: { hasNumberValue: 76 } }],
    };
    const issues = checkSemantics(framed);
    assert.ok(issues.some((i) => i.severity === "error" && /@id/.test(i.path)), "expected an @id error");
    assert.ok(
      issues.some((i) => i.severity === "warning" && /unit/.test(i.message)),
      "expected a missing-unit warning",
    );
  });

  // 7. effectiveContext merges the hosted URL to the vendored terms.
  await check("effectiveContext resolves the hosted URL to vendored terms", () => {
    const ctx = effectiveContext({ "@context": RECORDS_CONTEXT_URL });
    assert.ok("hasProperty" in ctx, "expected vendored terms after resolving the hosted URL");
  });

  // 8. Datasheet extraction pulls identity, properties, and components.
  await check("extractSummary builds a datasheet from the canonical example", async () => {
    const raw = readFileSync(resolve(webRoot, "public/jsonld/cell-spec.jsonld"), "utf-8");
    const out = await runJsonLdLayers(raw, lib);
    assert.ok(out.framed);
    const s = extractSummary(out.framed);
    assert.equal(s.title, "A123 ANR26650M1-B");
    assert.equal(s.manufacturer, "A123");
    assert.ok(s.properties.length >= 10, `expected several properties, got ${s.properties.length}`);
    const cap = s.properties.find((p) => p.label === "NominalCapacity");
    assert.ok(cap && cap.value === "2.5" && cap.unit, `expected a NominalCapacity with value+unit, got ${JSON.stringify(cap)}`);
    assert.ok(s.types.includes("CylindricalBattery"), "expected the EMMO type stack in the summary");
  });

  await Promise.resolve();
  if (failures.length > 0) {
    console.error(`\nWorkbench checks FAILED (${failures.length}):`);
    for (const f of failures) console.error(`  ${f}`);
    process.exit(1);
  }
  console.log(`\nWorkbench checks passed.`);
}

void main();
