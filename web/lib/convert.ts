// Illustrative, in-browser transform from authored BattINFO JSON to EMMO
// `domain-battery` JSON-LD.
//
// This is intentionally NOT the canonical transform. The deterministic,
// mapping-table-driven engine lives in the Python package
// (`battinfo.transform.to_jsonld`). This client-side version reproduces the
// shape and the high-signal mappings so the Convert page can show "JSON →
// Linked Data" instantly, with no backend. The Convert page wires a
// "Convert canonically" button to the real engine (see
// docs/web-validator-converter-plan.md, phase P2).

export interface ConvertResult {
  domainBattery: unknown;
  converterCompatible: unknown;
  notes: string[]; // lossy / illustrative caveats, never silently dropped
  error?: string;
}

// Curated subset of the unit → EMMO/QUDT IRI table (assets/mappings/...).
const UNIT_IRI: Record<string, string> = {
  Ah: "https://w3id.org/emmo#AmpereHour",
  mAh: "https://w3id.org/emmo#MilliAmpereHour",
  V: "https://w3id.org/emmo#Volt",
  g: "https://w3id.org/emmo#Gram",
  kg: "https://w3id.org/emmo#Kilogram",
  mm: "https://w3id.org/emmo#Millimetre",
  cm: "https://w3id.org/emmo#Centimetre",
  Wh: "https://w3id.org/emmo#WattHour",
  "Wh/kg": "https://w3id.org/emmo#WattHourPerKilogram",
};

// Curated subset of the property → EMMO type table.
const PROPERTY_TYPE: Record<string, string> = {
  nominal_capacity: "NominalCapacity",
  nominal_voltage: "NominalVoltage",
  mass: "Mass",
  diameter: "Diameter",
  height: "Height",
  width: "Width",
  thickness: "Thickness",
  energy_density: "GravimetricEnergyDensity",
};

// Cell format → EMMO battery-geometry type.
const FORMAT_TYPE: Record<string, string> = {
  cylindrical: "CylindricalBattery",
  prismatic: "PrismaticBattery",
  pouch: "PouchBattery",
  coin: "CoinCellBattery",
};

// Positive-electrode chemistry basis → EMMO cell-chemistry type.
const CHEMISTRY_BASIS_TYPE: Record<string, string> = {
  LFP: "LithiumIronPhosphateBattery",
  NMC: "LithiumNickelManganeseCobaltOxideBattery",
  NCA: "LithiumNickelCobaltAluminiumOxideBattery",
  LCO: "LithiumCobaltOxideBattery",
  LTO: "LithiumTitanateBattery",
};

function titleCaseLabel(p: Record<string, unknown>): string {
  return (
    (p.name as string) ||
    (p.model as string) ||
    "Unnamed cell type"
  );
}

function buildTypeStack(product: Record<string, unknown>, notes: string[]): string[] {
  const stack = ["BatteryCell"];
  const fmt = product.cell_format as string | undefined;
  if (fmt) {
    if (FORMAT_TYPE[fmt]) stack.push(FORMAT_TYPE[fmt]);
    else notes.push(`cell_format "${fmt}" has no illustrative @type mapping here.`);
  }
  if (product.chemistry === "Li-ion") stack.push("LithiumIonBattery");
  const basis = product.positive_electrode_basis as string | undefined;
  if (basis) {
    if (CHEMISTRY_BASIS_TYPE[basis]) stack.push(CHEMISTRY_BASIS_TYPE[basis]);
    else notes.push(`positive_electrode_basis "${basis}" has no illustrative @type mapping here.`);
  }
  return stack;
}

function buildProperties(
  specs: Record<string, unknown>,
  notes: string[],
  measured: boolean,
): unknown[] {
  const out: unknown[] = [];
  for (const [key, value] of Object.entries(specs)) {
    if (typeof value !== "object" || value === null) {
      notes.push(`spec "${key}" is not a quantity object; skipped.`);
      continue;
    }
    const q = value as Record<string, unknown>;
    const propType = PROPERTY_TYPE[key];
    if (!propType) notes.push(`property "${key}" has no illustrative EMMO type mapping here.`);
    const unit = q.unit as string | undefined;
    if (unit && !UNIT_IRI[unit]) notes.push(`unit "${unit}" has no illustrative IRI mapping here.`);

    out.push({
      "@type": [propType ?? key, measured ? "MeasuredProperty" : "ConventionalProperty"],
      hasNumericalPart: { "@type": "Real", hasNumericalValue: q.value ?? q.value_text },
      hasMeasurementUnit: unit ? UNIT_IRI[unit] ?? unit : undefined,
    });
  }
  return out;
}

export function convertCellType(raw: string, target: "domain-battery" | "converter-compatible" = "domain-battery"): ConvertResult {
  let doc: unknown;
  try {
    doc = JSON.parse(raw);
  } catch (e) {
    return { domainBattery: null, converterCompatible: null, notes: [], error: `Invalid JSON: ${(e as Error).message}` };
  }
  if (typeof doc !== "object" || doc === null || Array.isArray(doc)) {
    return { domainBattery: null, converterCompatible: null, notes: [], error: "Record must be a JSON object." };
  }

  const rec = doc as Record<string, unknown>;
  const product = (rec.product ?? {}) as Record<string, unknown>;
  const specs = (rec.specs ?? {}) as Record<string, unknown>;
  const notes: string[] = [];

  const typeStack = buildTypeStack(product, notes);
  const label = titleCaseLabel(product);
  const manufacturer = product.manufacturer;
  const iri = "https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5";

  const domainBattery = {
    "@context": "https://w3id.org/battinfo/context/domain-battery.jsonld",
    "@id": (product.id as string) || iri,
    "@type": typeStack,
    "skos:prefLabel": label,
    ...(manufacturer
      ? {
          manufacturer:
            typeof manufacturer === "string"
              ? { "@type": "Organization", name: manufacturer }
              : manufacturer,
        }
      : {}),
    hasProperty: buildProperties(specs, notes, false),
  };

  // converter-compatible view: legacy RatedCapacity overload + hasMeasuredProperty.
  const converterCompatible = {
    "@context": "https://w3id.org/battinfo/context/converter.jsonld",
    "@id": (product.id as string) || iri,
    "@type": typeStack,
    "schema:name": label,
    hasMeasuredProperty: buildProperties(specs, [], true),
  };

  notes.unshift(
    "Illustrative transform. The canonical, deterministic mappings live in the battinfo Python package.",
  );

  return {
    domainBattery,
    converterCompatible,
    notes,
  };
}
