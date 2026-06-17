// Lightweight, in-browser STRUCTURAL validator for BattINFO cell-type records.
//
// This is intentionally NOT the canonical validator. The authoritative,
// multi-layer validation (JSON Schema draft 2020-12, Pydantic, JSON-LD
// URDNA2015, semantic rules, referential integrity) lives in the Python
// package under src/battinfo/validate/. This client-side check enforces a few
// high-signal invariants so the website's "Validate" tool gives immediate
// feedback without a backend. Wire it to the real validator API later.

export type Severity = "error" | "warning";

export interface Issue {
  severity: Severity;
  path: string;
  message: string;
}

const IRI_PATTERN = /^https:\/\/w3id\.org\/battinfo\/[a-z-]+\/[a-z0-9-]+$/i;

function isQuantity(v: unknown): v is { value?: unknown; value_text?: unknown; unit?: unknown } {
  return typeof v === "object" && v !== null && ("value" in v || "value_text" in v);
}

export function validateCellType(raw: string): { ok: boolean; issues: Issue[]; parsed?: unknown } {
  const issues: Issue[] = [];

  let doc: unknown;
  try {
    doc = JSON.parse(raw);
  } catch (e) {
    return {
      ok: false,
      issues: [{ severity: "error", path: "(root)", message: `Invalid JSON: ${(e as Error).message}` }],
    };
  }

  if (typeof doc !== "object" || doc === null || Array.isArray(doc)) {
    return { ok: false, issues: [{ severity: "error", path: "(root)", message: "Record must be a JSON object." }] };
  }

  const rec = doc as Record<string, unknown>;

  // --- Top-level shape ---
  if (!("product" in rec)) {
    issues.push({ severity: "error", path: "product", message: "Missing required `product` object." });
  }
  if (!("specs" in rec)) {
    issues.push({ severity: "warning", path: "specs", message: "No `specs` block — record carries no measured properties." });
  }
  if (!("schema_version" in rec)) {
    issues.push({ severity: "warning", path: "schema_version", message: "No `schema_version` — recommended for forward compatibility." });
  }

  // --- product ---
  const product = rec.product;
  if (product && typeof product === "object" && !Array.isArray(product)) {
    const p = product as Record<string, unknown>;
    for (const field of ["name", "manufacturer", "chemistry"]) {
      if (!(field in p)) {
        issues.push({ severity: "warning", path: `product.${field}`, message: `Recommended field \`${field}\` is missing.` });
      }
    }
    if ("id" in p && typeof p.id === "string" && !IRI_PATTERN.test(p.id)) {
      issues.push({
        severity: "error",
        path: "product.id",
        message: "`id` is not a canonical w3id.org/battinfo/{type}/{uid} IRI.",
      });
    }
    if (p.manufacturer && typeof p.manufacturer === "string") {
      issues.push({
        severity: "warning",
        path: "product.manufacturer",
        message: "`manufacturer` should be an Organization object ({ type, name }), not a bare string.",
      });
    }
  }

  // --- specs: every entry must be a quantity with a unit ---
  const specs = rec.specs;
  if (specs && typeof specs === "object" && !Array.isArray(specs)) {
    for (const [key, value] of Object.entries(specs as Record<string, unknown>)) {
      if (!isQuantity(value)) {
        issues.push({ severity: "error", path: `specs.${key}`, message: "Spec must be a quantity object with `value`/`value_text`." });
        continue;
      }
      const q = value as Record<string, unknown>;
      if (!("unit" in q)) {
        issues.push({ severity: "error", path: `specs.${key}.unit`, message: "Quantity is missing a `unit` (units must never be implicit)." });
      }
      if ("value" in q && typeof q.value !== "number") {
        issues.push({ severity: "warning", path: `specs.${key}.value`, message: "`value` should be numeric; use `value_text` for ranges like \">1000\"." });
      }
    }
  }

  const ok = !issues.some((i) => i.severity === "error");
  return { ok, issues, parsed: doc };
}
