// Client-side JSON-LD workbench logic — the pure, testable core behind the
// "JSON-LD document" mode of /validate.
//
// It does three things, each reported as its own issue list:
//   a. well-formedness  — parses, resolves a @context, expands; keys that
//      expand to nothing are surfaced (never dropped silently).
//   b. structural       — the real canonical JSON Schemas (via lib/validate).
//   c. semantic sanity  — cheap identity/quantity/reference checks.
//
// Everything here is self-contained: the offline document loader resolves our
// hosted @context from the vendored copy and refuses every other URL, so the
// site makes no network calls. The `jsonld` library is passed in by the caller
// (dynamically imported in the browser) so this module stays free of it and can
// be unit-checked under tsx.

import type { Issue } from "./validate";
import { recordsContext, RECORDS_CONTEXT_URL } from "./records-context.generated";

export type Layer = "well-formedness" | "structural" | "semantic";

export interface LayeredIssue extends Issue {
  layer: Layer;
}

// Minimal surface of the jsonld library we use, so callers can pass either the
// real module or a stub without pulling its types into the bundle everywhere.
export interface JsonLdLib {
  expand(input: unknown, options?: Record<string, unknown>): Promise<unknown[]>;
  frame(input: unknown, frame: unknown, options?: Record<string, unknown>): Promise<Record<string, unknown>>;
}

const JSONLD_KEYWORDS = new Set([
  "@context", "@id", "@type", "@value", "@language", "@index", "@list", "@set",
  "@reverse", "@graph", "@base", "@vocab", "@version", "@container", "@direction",
  "@nest", "@none", "@prefix", "@included", "@json", "@protected", "@import",
]);

// The canonical identifier shape our schemas enforce:
//   https://w3id.org/battinfo/<segment>/<uid>   uid = 4×4 Crockford-ish groups.
const UID = "[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}";
const BATTINFO_IRI = new RegExp(`^https://w3id\\.org/battinfo/[a-z-]+/${UID}$`);
const BATTINFO_PREFIX = "https://w3id.org/battinfo/";

/** URLs we can resolve offline from the vendored context. */
export const KNOWN_CONTEXT_URLS = new Set([
  RECORDS_CONTEXT_URL,
  "https://w3id.org/battinfo/context/records.context.json",
]);

/**
 * A jsonld document loader that resolves our hosted records @context from the
 * vendored copy and refuses everything else. No network, ever.
 */
export function offlineDocumentLoader() {
  return async (url: string) => {
    if (KNOWN_CONTEXT_URLS.has(url)) {
      return { contextUrl: undefined, document: recordsContext, documentUrl: url };
    }
    throw new Error(
      `remote @context <${url}> is not bundled — this tool runs offline. ` +
        `Inline the @context, or reference ${RECORDS_CONTEXT_URL}.`,
    );
  };
}

export interface ParseResult {
  doc?: Record<string, unknown>;
  error?: string;
}

export function parseJson(raw: string): ParseResult {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch (e) {
    return { error: `Invalid JSON: ${(e as Error).message}` };
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return { error: "A JSON-LD document must be a JSON object." };
  }
  return { doc: value as Record<string, unknown> };
}

/** True when the document carries any JSON-LD keyword at the top level. */
export function looksLikeJsonLd(doc: Record<string, unknown>): boolean {
  return "@context" in doc || "@graph" in doc || "@type" in doc || "@id" in doc;
}

// --- context term resolution (for the undefined-term warnings) ----------------

interface TermIndex {
  terms: Set<string>;
  prefixes: Set<string>;
  hasVocab: boolean;
}

/** Merge a document's @context (inline object, array, or our known URL). */
function collectContext(context: unknown, into: Record<string, unknown>): void {
  if (Array.isArray(context)) {
    for (const part of context) collectContext(part, into);
    return;
  }
  if (typeof context === "string") {
    if (KNOWN_CONTEXT_URLS.has(context)) {
      collectContext((recordsContext as Record<string, unknown>)["@context"], into);
    }
    return; // unknown remote context — its terms are simply unknown offline
  }
  if (context && typeof context === "object") {
    Object.assign(into, context as Record<string, unknown>);
  }
}

export function effectiveContext(doc: Record<string, unknown>): Record<string, unknown> {
  const merged: Record<string, unknown> = {};
  collectContext(doc["@context"], merged);
  return merged;
}

function indexContext(ctx: Record<string, unknown>): TermIndex {
  const terms = new Set<string>();
  const prefixes = new Set<string>();
  let hasVocab = false;
  for (const [key, value] of Object.entries(ctx)) {
    if (key === "@vocab") {
      hasVocab = true;
      continue;
    }
    if (key.startsWith("@")) continue;
    terms.add(key);
    // A term whose value is a bare namespace string acts as a prefix.
    if (typeof value === "string" && (value.endsWith("#") || value.endsWith("/") || value.endsWith(":"))) {
      prefixes.add(key);
    }
  }
  return { terms, prefixes, hasVocab };
}

function termIsDefined(key: string, index: TermIndex): boolean {
  if (key.startsWith("@")) return JSONLD_KEYWORDS.has(key);
  if (index.hasVocab) return true; // @vocab maps any bare term
  if (index.terms.has(key)) return true;
  if (/^https?:\/\//.test(key)) return true; // already an absolute IRI
  if (key.includes(":")) {
    const prefix = key.slice(0, key.indexOf(":"));
    return index.prefixes.has(prefix);
  }
  return false;
}

/**
 * Layer (a) — well-formedness. Reports @context resolution, expansion outcome,
 * and every key that the context does not define (these vanish on expansion, so
 * we surface them rather than let them disappear).
 */
export function checkWellFormedness(
  doc: Record<string, unknown>,
  expanded: unknown[] | null,
  expandError: string | null,
): LayeredIssue[] {
  const issues: LayeredIssue[] = [];
  const hasContext = "@context" in doc || "@graph" in doc;
  if (!hasContext) {
    issues.push({
      layer: "well-formedness",
      severity: "error",
      path: "@context",
      message:
        "No @context. A JSON-LD document needs one to give its terms meaning — " +
        "inline it, or reference our hosted context.",
    });
  }

  if (expandError) {
    issues.push({
      layer: "well-formedness",
      severity: "error",
      path: "(root)",
      message: `Could not expand this document: ${expandError}`,
    });
  } else if (expanded && expanded.length === 0) {
    issues.push({
      layer: "well-formedness",
      severity: "warning",
      path: "(root)",
      message: "Expansion produced an empty graph — no terms resolved to IRIs. Is the @context right?",
    });
  }

  const index = indexContext(effectiveContext(doc));
  const undefined_: { path: string; term: string }[] = [];
  const seen = new Set<string>();
  walkTerms(doc, "", index, undefined_, seen);
  for (const { path, term } of undefined_) {
    issues.push({
      layer: "well-formedness",
      severity: "warning",
      path,
      message: `Term \`${term}\` is not defined by the @context — it expands to nothing and is dropped from the linked data.`,
    });
  }
  return issues;
}

function walkTerms(
  node: unknown,
  path: string,
  index: TermIndex,
  out: { path: string; term: string }[],
  seen: Set<string>,
): void {
  if (Array.isArray(node)) {
    node.forEach((item, i) => walkTerms(item, `${path}[${i}]`, index, out, seen));
    return;
  }
  if (!node || typeof node !== "object") return;
  const obj = node as Record<string, unknown>;
  // Honour a scoped @context nested in this node.
  let scoped = index;
  if ("@context" in obj) {
    const merged: Record<string, unknown> = {};
    for (const t of index.terms) merged[t] = true;
    collectContext(obj["@context"], merged);
    scoped = indexContext(merged);
  }
  for (const [key, value] of Object.entries(obj)) {
    if (key === "@context") continue;
    if (!termIsDefined(key, scoped) && !seen.has(key)) {
      seen.add(key);
      out.push({ path: path ? `${path}.${key}` : key, term: key });
    }
    walkTerms(value, path ? `${path}.${key}` : key, scoped, out, seen);
  }
}

// --- layer (c): semantic sanity ----------------------------------------------

/**
 * Cheap, browser-side semantic checks on the canonical (framed) view:
 *   - @id values that claim a battinfo IRI must match the canonical shape;
 *   - quantity nodes (under hasProperty) must carry a value and a unit;
 *   - *_id references that look like our IRIs must match the canonical shape.
 * This is a pre-check — the library runs the full semantic/SHACL layer.
 */
export function checkSemantics(framed: Record<string, unknown>): LayeredIssue[] {
  const issues: LayeredIssue[] = [];
  walkSemantics(framed, "(root)", issues);
  return issues;
}

function isQuantityContainer(key: string): boolean {
  // Compact term or its EMMO IRI for emmo:hasProperty.
  return key === "hasProperty" || key.endsWith("EMMO_e1097637_70d2_4895_973f_2396f04fa204");
}

function hasNumericValue(node: Record<string, unknown>): boolean {
  if ("schema:value" in node || "value" in node) return true;
  const part = node["hasNumericalPart"] as Record<string, unknown> | undefined;
  if (part && typeof part === "object") {
    return "hasNumberValue" in part || "hasNumericalValue" in part;
  }
  return false;
}

function hasUnit(node: Record<string, unknown>): boolean {
  return (
    "hasMeasurementUnit" in node ||
    "unit" in node ||
    Object.keys(node).some((k) => k.endsWith("EMMO_bed1d005_b04e_4a90_94cf_02bc678a8569"))
  );
}

function walkSemantics(node: unknown, path: string, out: LayeredIssue[]): void {
  if (Array.isArray(node)) {
    node.forEach((item, i) => walkSemantics(item, `${path}[${i}]`, out));
    return;
  }
  if (!node || typeof node !== "object") return;
  const obj = node as Record<string, unknown>;

  // @id identity check.
  const id = obj["@id"] ?? obj["id"];
  if (typeof id === "string" && id.startsWith(BATTINFO_PREFIX) && !BATTINFO_IRI.test(id)) {
    out.push({
      layer: "semantic",
      severity: "error",
      path: `${path}.@id`,
      message: `\`${id}\` claims a battinfo identifier but is not a canonical https://w3id.org/battinfo/<type>/<uid> IRI.`,
    });
  }

  // *_id references (cell_spec_id, test_spec_id, …).
  for (const [key, value] of Object.entries(obj)) {
    if (key.endsWith("_id") && typeof value === "string" && value.startsWith(BATTINFO_PREFIX) && !BATTINFO_IRI.test(value)) {
      out.push({
        layer: "semantic",
        severity: "error",
        path: `${path}.${key}`,
        message: `Reference \`${key}\` is not a canonical battinfo IRI: ${value}.`,
      });
    }
  }

  // Quantity checks: inspect each entry under a hasProperty container.
  for (const [key, value] of Object.entries(obj)) {
    if (isQuantityContainer(key)) {
      const quantities = Array.isArray(value) ? value : [value];
      quantities.forEach((q, i) => {
        if (!q || typeof q !== "object") return;
        const qNode = q as Record<string, unknown>;
        const label = labelOf(qNode) ?? `#${i}`;
        const qPath = `${path}.${key}[${i}]`;
        if (!hasNumericValue(qNode)) {
          out.push({
            layer: "semantic",
            severity: "warning",
            path: qPath,
            message: `Quantity \`${label}\` carries no value.`,
          });
        }
        if (!hasUnit(qNode)) {
          out.push({
            layer: "semantic",
            severity: "warning",
            path: qPath,
            message: `Quantity \`${label}\` carries no unit.`,
          });
        }
      });
    }
  }

  for (const [key, value] of Object.entries(obj)) {
    if (key === "@context") continue;
    walkSemantics(value, `${path}.${key}`, out);
  }
}

function labelOf(node: Record<string, unknown>): string | null {
  const pref = node["skos:prefLabel"];
  if (typeof pref === "string") return pref;
  const t = node["@type"];
  if (typeof t === "string") return t;
  if (Array.isArray(t) && typeof t[0] === "string") return t[0];
  return null;
}

// --- expand + frame orchestration --------------------------------------------

/** A frame that re-nests any graph into our canonical record view. */
export function canonicalFrame(doc: Record<string, unknown>): Record<string, unknown> {
  const inline = effectiveContext(doc);
  const base = (recordsContext as Record<string, unknown>)["@context"] as Record<string, unknown>;
  return {
    "@context": { ...base, ...inline },
    "@embed": "@once",
  };
}

export interface WorkbenchOutput {
  parsed: Record<string, unknown> | null;
  expanded: unknown[] | null;
  framed: Record<string, unknown> | null;
  expandError: string | null;
  wellFormedness: LayeredIssue[];
  semantic: LayeredIssue[];
}

/**
 * Run the JSON-LD layers (a and c). Structural layer (b) is the Ajv path in
 * lib/validate and is invoked separately by the UI so it can offer the manual
 * record-type override.
 */
export async function runJsonLdLayers(raw: string, jsonld: JsonLdLib): Promise<WorkbenchOutput> {
  const parse = parseJson(raw);
  if (parse.error || !parse.doc) {
    return {
      parsed: null,
      expanded: null,
      framed: null,
      expandError: null,
      wellFormedness: [
        { layer: "well-formedness", severity: "error", path: "(root)", message: parse.error ?? "Could not parse document." },
      ],
      semantic: [],
    };
  }
  const doc = parse.doc;
  const documentLoader = offlineDocumentLoader();

  let expanded: unknown[] | null = null;
  let expandError: string | null = null;
  try {
    expanded = await jsonld.expand(doc, { documentLoader });
  } catch (e) {
    expandError = (e as Error).message;
  }

  let framed: Record<string, unknown> | null = null;
  if (expanded && expanded.length > 0) {
    try {
      framed = await jsonld.frame(expanded, canonicalFrame(doc), { documentLoader });
    } catch {
      framed = null;
    }
  }

  const wellFormedness = checkWellFormedness(doc, expanded, expandError);
  const semantic = framed ? checkSemantics(framed) : checkSemantics(doc);
  return { parsed: doc, expanded, framed, expandError, wellFormedness, semantic };
}
