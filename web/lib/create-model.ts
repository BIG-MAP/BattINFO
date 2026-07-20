// Live serialization for the Create page: turn a small in-browser cell draft
// into the three forms a BattINFO user works with — the Python authoring call,
// the canonical record JSON, and the published JSON-LD. Pure functions, no
// network; the JSON-LD references our hosted @context (resolved offline by the
// viewer) so it stays compact and readable.

export interface DraftProperty {
  key: string;
  value: string;
  unit: string;
}

export interface CellDraft {
  name: string;
  manufacturer: string;
  model: string;
  format: string;
  chemistry: string;
  positiveBasis: string;
  negativeBasis: string;
  properties: DraftProperty[];
}

export const FORMATS = ["coin", "cylindrical", "pouch", "prismatic"] as const;
export const CHEMISTRIES = ["Li-ion", "Li-metal", "Na-ion", "Alkaline"] as const;

// The properties offered in the builder, each with its allowed units. Keeping
// this a fixed catalog means everything maps cleanly to a canonical type + unit.
export const PROPERTY_CATALOG: { key: string; label: string; units: string[] }[] = [
  { key: "nominal_capacity", label: "Nominal capacity", units: ["Ah", "mAh"] },
  { key: "nominal_voltage", label: "Nominal voltage", units: ["V", "mV"] },
  { key: "mass", label: "Mass", units: ["g", "kg"] },
  { key: "energy_density", label: "Energy density", units: ["Wh/kg", "Wh/L"] },
  { key: "internal_resistance", label: "Internal resistance", units: ["mΩ", "Ω"] },
  { key: "diameter", label: "Diameter", units: ["mm", "cm"] },
  { key: "height", label: "Height", units: ["mm", "cm"] },
];

// Physical-cell EMMO classes stacked under isDescriptionFor in the JSON-LD.
const FORMAT_CLASS: Record<string, string> = {
  coin: "CoinCell",
  cylindrical: "CylindricalBattery",
  pouch: "PouchCell",
  prismatic: "PrismaticBattery",
};
const CHEMISTRY_CLASS: Record<string, string> = {
  "Li-ion": "LithiumIonBattery",
  "Li-metal": "LithiumMetalBattery",
  "Na-ion": "SodiumIonBattery",
  Alkaline: "AlkalineCell",
};

export const RECORDS_CONTEXT_URL = "https://w3id.org/battinfo/context/records/v1.json";

function num(value: string): number | string {
  const n = Number(value);
  return value.trim() !== "" && Number.isFinite(n) ? n : value;
}

function validProperties(draft: CellDraft): DraftProperty[] {
  return draft.properties.filter((p) => p.key && p.value.trim() !== "");
}

function displayName(draft: CellDraft): string {
  return draft.name.trim() || [draft.manufacturer, draft.model].filter(Boolean).join(" ").trim();
}

/** The canonical record — the object `spec.to_record()` produces. */
export function toRecord(draft: CellDraft): Record<string, unknown> {
  const cell: Record<string, unknown> = {};
  const name = displayName(draft);
  if (name) cell.name = name;
  if (draft.model) cell.model = draft.model;
  if (draft.manufacturer) cell.manufacturer = { type: "Organization", name: draft.manufacturer };
  if (draft.format) cell.cell_format = draft.format;
  if (draft.chemistry) cell.chemistry = draft.chemistry;
  if (draft.positiveBasis) cell.positive_electrode_basis = draft.positiveBasis;
  if (draft.negativeBasis) cell.negative_electrode_basis = draft.negativeBasis;

  const record: Record<string, unknown> = { schema_version: "0.1.0", cell_spec: cell };
  const props = validProperties(draft);
  if (props.length) {
    record.properties = Object.fromEntries(
      props.map((p) => [p.key, { value: num(p.value), unit: p.unit }]),
    );
  }
  return record;
}

/** The Python authoring call that produces the same record. */
export function toPython(draft: CellDraft): string {
  const lines: string[] = ["from battinfo import CellSpec", "", "spec = CellSpec("];
  const arg = (key: string, value: string) => {
    if (value) lines.push(`    ${key}=${JSON.stringify(value)},`);
  };
  arg("name", displayName(draft));
  arg("manufacturer", draft.manufacturer);
  arg("model", draft.model);
  arg("format", draft.format);
  arg("chemistry", draft.chemistry);
  arg("positive_electrode_basis", draft.positiveBasis);
  arg("negative_electrode_basis", draft.negativeBasis);
  const props = validProperties(draft);
  if (props.length) {
    lines.push("    properties={");
    for (const p of props) {
      lines.push(`        "${p.key}": {"value": ${JSON.stringify(num(p.value))}, "unit": ${JSON.stringify(p.unit)}},`);
    }
    lines.push("    },");
  }
  lines.push(")", "record = spec.to_record()");
  return lines.join("\n");
}

/** The published JSON-LD (compact form, resolved by our hosted @context). */
export function toJsonLd(draft: CellDraft): Record<string, unknown> {
  const doc: Record<string, unknown> = {
    "@context": RECORDS_CONTEXT_URL,
    "@type": ["BatteryCellSpecification", "schema:CreativeWork"],
  };
  const name = displayName(draft);
  if (name) doc.name = name;
  if (draft.model) doc.model = draft.model;
  if (draft.manufacturer) doc.manufacturer = { "@type": "schema:Organization", name: draft.manufacturer };

  const physical = ["BatteryCell"];
  if (FORMAT_CLASS[draft.format]) physical.push(FORMAT_CLASS[draft.format]);
  if (CHEMISTRY_CLASS[draft.chemistry]) physical.push(CHEMISTRY_CLASS[draft.chemistry]);
  doc.isDescriptionFor = { "@type": physical };

  // Each property is a quantity node typed by its property term. We use the
  // snake_case term (nominal_capacity, …) rather than the PascalCase class name:
  // both resolve to the same EMMO IRI, but only the snake term is defined by the
  // hosted records @context, so the compact document expands with no loose ends.
  const props = validProperties(draft);
  if (props.length) {
    doc.hasProperty = props.map((p) => ({
      "@type": p.key,
      hasNumericalPart: { hasNumberValue: num(p.value) },
      hasMeasurementUnit: p.unit,
    }));
  }
  return doc;
}
