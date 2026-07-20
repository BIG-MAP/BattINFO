// Live serialization for the Create page. A small in-browser draft of any of the
// core canonical objects becomes its three working forms: the Python authoring
// call, the canonical record JSON, and the published JSON-LD. Pure, no network.
//
// The JSON-LD carries a self-contained inline @context assembled from the terms
// the document actually uses (the hosted records context is cell-property
// focused and does not define the composition/material terms), so every
// document expands with no loose ends.

import { recordsContext } from "./records-context.generated";
import { validateRecord, type Issue } from "./validate";

export interface DraftProperty {
  key: string;
  value: string;
  unit: string;
}

export type Values = Record<string, string>;

// --- JSON-LD @context assembly -----------------------------------------------
const PREFIXES: Record<string, string> = {
  battery: "https://w3id.org/emmo/domain/battery#",
  electrochemistry: "https://w3id.org/emmo/domain/electrochemistry#",
  emmo: "https://w3id.org/emmo#",
  chemical: "https://w3id.org/emmo/domain/chemical-substance#",
  battinfo: "https://w3id.org/battinfo/",
  schema: "https://schema.org/",
  dcterms: "http://purl.org/dc/terms/",
  skos: "http://www.w3.org/2004/02/skos/core#",
  xsd: "http://www.w3.org/2001/XMLSchema#",
};

// Composition/material/relation terms not in the base records context, taken
// verbatim from the EMMO domain contexts the transform emits.
const SUPPLEMENT: Record<string, unknown> = {
  hasPositiveElectrode: { "@id": "electrochemistry:electrochemistry_8e9cf965_9f92_46e8_b678_b50410ce3616", "@type": "@id" },
  hasNegativeElectrode: { "@id": "electrochemistry:electrochemistry_5d299271_3f68_494f_ab96_3db9acdd3138", "@type": "@id" },
  hasElectrolyte: { "@id": "electrochemistry:electrochemistry_3bd08946_4e81_455d_9fca_dc7a5ead9315", "@type": "@id" },
  hasSeparator: { "@id": "electrochemistry:electrochemistry_9317be62_e602_4343_a72d_02c87201b9f6", "@type": "@id" },
  hasActiveMaterial: { "@id": "electrochemistry:electrochemistry_860aa941_5ff9_4452_8a16_7856fad07bee", "@type": "@id" },
  hasCurrentCollector: { "@id": "electrochemistry:electrochemistry_cc8c2c5d_cf3d_444d_a7e8_44ec4c06a88e", "@type": "@id" },
  hasSolute: { "@id": "electrochemistry:electrochemistry_8784ef24_320b_4a3d_b200_654aec6c271c", "@type": "@id" },
  hasSolvent: { "@id": "electrochemistry:electrochemistry_808e94df_e002_4e64_a6db_182ed75078c6", "@type": "@id" },
  hasConstituent: { "@id": "emmo:EMMO_dba27ca1_33c9_4443_a912_1519ce4c39ec", "@type": "@id" },
  Electrode: "electrochemistry:electrochemistry_0f007072_a8dd_4798_b865_1bf9363be627",
  ActiveMaterial: "electrochemistry:electrochemistry_79d1b273_58cd_4be6_a250_434817f7c261",
  Binder: "electrochemistry:electrochemistry_68eb5e35_5bd8_47b1_9b7f_f67224fa291e",
  ConductiveAdditive: "electrochemistry:electrochemistry_82fef384_8eec_4765_b707_5397054df594",
  CurrentCollector: "electrochemistry:electrochemistry_212af058_3bbb_419f_a9c6_90ba9ebb3706",
  Separator: "electrochemistry:electrochemistry_331e6cca_f260_4bf8_af55_35304fe1bbe0",
  ElectrolyteSolution: "electrochemistry:electrochemistry_fa22874b_76a9_4043_8b8f_6086c88746de",
  Solute: "chemical:substance_3899a9c9_9b34_443e_8ce6_0257589bb38a",
  Solvent: "chemical:substance_0f2f65a7_5cc4_4c86_a4d0_676771c646f1",
  LithiumIronPhosphateElectrode: "electrochemistry:electrochemistry_1d0f15cb_d6b5_4c27_89ca_fe78adc1ce5b",
  GraphiteElectrode: "electrochemistry:electrochemistry_c831d963_629a_41ab_850f_97fb6841b739",
  LithiumNickelManganeseCobaltOxideElectrode: "electrochemistry:electrochemistry_b3eb8c65_5644_45e3_9e17_0be6277c7962",
  SiliconGraphiteElectrode: "electrochemistry:electrochemistry_e8c39ecc_29d1_4172_996e_d5b05dc88015",
  SiliconBasedElectrode: "electrochemistry:electrochemistry_79e12290_d1e5_4c41_916c_18f1e4d7fb51",
  HardCarbonElectrode: "electrochemistry:electrochemistry_6235cc7c_2eee_432a_93af_47d7e05db007",
  LithiumElectrode: "electrochemistry:electrochemistry_55775b50_b9d9_4d68_8cb5_38fcd7b9b54d",
  LithiumCobaltOxideElectrode: "electrochemistry:electrochemistry_fd7caf39_0a43_4fbf_958e_a62067aa9007",
  LithiumManganeseIronPhosphateElectrode: "electrochemistry:electrochemistry_9109b3f6_112b_456d_ae45_b82c271c656b",
  LithiumTitanateElectrode: "electrochemistry:electrochemistry_6d0fe07e_a629_479c_ab24_2846f209bb0b",
  LithiumIronPhosphate: "chemical:substance_aa8e9cc4_5f66_4307_b1c8_26fac7653a90",
  Graphite: "chemical:substance_d53259a7_0d9c_48b9_a6c1_4418169df303",
  LithiumNickelManganeseCobaltOxide: "chemical:substance_3ac62305_acd6_4312_9e31_4f824bd2530d",
  LithiumHexafluorophosphate: "chemical:substance_0deb4fe8_b0c0_4e3f_8848_64435e5c0771",
  EthyleneCarbonate: "chemical:substance_57339d90_0553_4a96_8da9_ff6c3684e226",
  specific_capacity: "electrochemistry:electrochemistry_884650fd_6cc6_4ec6_8264_c18fbe6b90ee",
  loading: "electrochemistry:electrochemistry_c955c089_6ee1_41a2_95fc_d534c5cfd3d5",
  thickness: "emmo:EMMO_43003c86_9d15_433b_9789_ee2940920656",
};

// Units are emitted as full EMMO IRIs (hasMeasurementUnit is @type:@id), so they
// need no @context term — and unit tokens with a slash cannot be context terms.
const EMMO = "https://w3id.org/emmo#";
const ECHEM = "https://w3id.org/emmo/domain/electrochemistry#";
const UNIT_IRI: Record<string, string> = {
  Ah: EMMO + "AmpereHour", mAh: EMMO + "MilliAmpereHour",
  V: EMMO + "Volt", mV: EMMO + "MilliVolt",
  g: EMMO + "Gram", kg: EMMO + "Kilogram", mg: EMMO + "MilliGram",
  mm: EMMO + "MilliMetre", cm: EMMO + "CentiMetre", um: EMMO + "MicroMetre",
  "Ω": EMMO + "Ohm", "mΩ": EMMO + "MilliOhm", "%": EMMO + "Percent",
  "Wh/kg": EMMO + "WattHourPerKilogram", "Wh/L": EMMO + "WattHourPerLitre",
  "mg/cm2": EMMO + "MilliGramPerSquareCentiMetre",
  "g/cm3": EMMO + "GramPerCubicCentiMetre",
  "mAh/g": ECHEM + "MilliAmpereHourPerGram",
  "mAh/cm2": ECHEM + "MilliAmpereHourPerSquareCentiMetre",
};

function unitIri(token: string): string {
  return UNIT_IRI[token] ?? token;
}

const TERM_SOURCE: Record<string, unknown> = {
  ...(recordsContext["@context"] as Record<string, unknown>),
  ...SUPPLEMENT,
};

function collectTerms(node: unknown, out: Set<string>): void {
  if (Array.isArray(node)) {
    for (const item of node) collectTerms(item, out);
    return;
  }
  if (!node || typeof node !== "object") return;
  for (const [key, value] of Object.entries(node)) {
    if (!key.startsWith("@")) out.add(key);
    if (key === "@type") for (const t of Array.isArray(value) ? value : [value]) if (typeof t === "string") out.add(t);
    if (key === "hasMeasurementUnit" && typeof value === "string") out.add(value);
    collectTerms(value, out);
  }
}

/** A minimal inline @context that defines exactly the terms this body uses. */
function assembleContext(body: Record<string, unknown>): Record<string, unknown> {
  const used = new Set<string>();
  collectTerms(body, used);
  const context: Record<string, unknown> = { ...PREFIXES };
  for (const term of used) {
    if (term in TERM_SOURCE) context[term] = TERM_SOURCE[term];
  }
  return context;
}

// --- shared helpers ----------------------------------------------------------
function num(value: string): number | string {
  const n = Number(value);
  return value.trim() !== "" && Number.isFinite(n) ? n : value;
}

function activeProps(props: DraftProperty[]): DraftProperty[] {
  return props.filter((p) => p.key && p.value.trim() !== "");
}

function propBlock(props: DraftProperty[]): Record<string, unknown> {
  return Object.fromEntries(activeProps(props).map((p) => [p.key, { value: num(p.value), unit: p.unit }]));
}

function pyKwargs(pairs: [string, string][]): string[] {
  return pairs.filter(([, v]) => v).map(([k, v]) => `    ${k}=${JSON.stringify(v)},`);
}

function pyProps(props: DraftProperty[]): string[] {
  const list = activeProps(props);
  if (!list.length) return [];
  const lines = ["    properties={"];
  for (const p of list) lines.push(`        "${p.key}": {"value": ${JSON.stringify(num(p.value))}, "unit": ${JSON.stringify(p.unit)}},`);
  lines.push("    },");
  return lines;
}

function jsonldProps(props: DraftProperty[]): Record<string, unknown>[] {
  // snake_case property term resolves to the same IRI as its PascalCase class;
  // the unit is a full EMMO IRI so it needs no context term.
  return activeProps(props).map((p) => ({
    "@type": p.key,
    hasNumericalPart: { hasNumberValue: num(p.value) },
    hasMeasurementUnit: unitIri(p.unit),
  }));
}

function withContext(body: Record<string, unknown>): Record<string, unknown> {
  return { "@context": assembleContext(body), ...body };
}

// --- vocab maps --------------------------------------------------------------
const FORMAT_CLASS: Record<string, string> = {
  coin: "CoinCell", cylindrical: "CylindricalBattery", pouch: "PouchCell", prismatic: "PrismaticBattery",
};
const CHEMISTRY_CLASS: Record<string, string> = {
  "Li-ion": "LithiumIonBattery", "Li-metal": "LithiumMetalBattery", "Na-ion": "SodiumIonBattery", Alkaline: "AlkalineCell",
};
// Basis label -> EMMO electrode class, mirroring the battinfo transform's
// entity_type_map (keys matched case-insensitively, separators normalized).
const BASIS_ELECTRODE: Record<string, string> = {
  lfp: "LithiumIronPhosphateElectrode",
  nmc: "LithiumNickelManganeseCobaltOxideElectrode",
  nmc811: "LithiumNickelManganeseCobaltOxideElectrode",
  lco: "LithiumCobaltOxideElectrode",
  lmfp: "LithiumManganeseIronPhosphateElectrode",
  graphite: "GraphiteElectrode",
  "silicon-graphite": "SiliconGraphiteElectrode",
  silicon: "SiliconBasedElectrode",
  si: "SiliconBasedElectrode",
  "hard-carbon": "HardCarbonElectrode",
  lithium: "LithiumElectrode",
  "lithium-metal": "LithiumElectrode",
  "li-metal": "LithiumElectrode",
  lto: "LithiumTitanateElectrode",
};
const SUBSTANCE: Record<string, string> = {
  LFP: "LithiumIronPhosphate",
  NMC: "LithiumNickelManganeseCobaltOxide",
  graphite: "Graphite",
  Graphite: "Graphite",
  LiPF6: "LithiumHexafluorophosphate",
  EC: "EthyleneCarbonate",
};
const MATERIAL_ROLE: Record<string, string> = {
  active_material: "ActiveMaterial", binder: "Binder", conductive_additive: "ConductiveAdditive",
};

function electrodeNode(basis: string): Record<string, unknown> | null {
  const label = basis.trim();
  if (!label || label.toLowerCase() === "unknown") return null;
  const key = label.toLowerCase().replace(/[\s_,/]+/g, "-");
  if (BASIS_ELECTRODE[key]) return { "@type": BASIS_ELECTRODE[key] };
  // Unrecognised basis: a labeled generic electrode, matching the transform.
  return { "@type": "Electrode", "skos:prefLabel": label };
}

// --- field + object definitions ----------------------------------------------
export interface FieldDef {
  key: string;
  label: string;
  kind: "text" | "select" | "date";
  options?: string[];
  placeholder?: string;
  section?: string;
  help?: string;
}

export interface PropDef {
  key: string;
  label: string;
  units: string[];
}

export interface SectionDef {
  key: string;
  title: string;
  blurb: string;
}

// A builder can emit one record or several (a cell emits its spec + instance).
export type Emitted = Record<string, unknown> | Record<string, unknown>[];

export interface ObjectDef {
  key: string;
  label: string;
  blurb: string;
  fields: FieldDef[];
  sections?: SectionDef[];
  properties?: PropDef[];
  defaults: Values;
  defaultProperties?: DraftProperty[];
  toRecord: (v: Values, props: DraftProperty[]) => Emitted;
  toPython: (v: Values, props: DraftProperty[]) => string;
  toJsonLd: (v: Values, props: DraftProperty[]) => Emitted;
}

const CELL_PROPS: PropDef[] = [
  { key: "nominal_capacity", label: "Nominal capacity", units: ["Ah", "mAh"] },
  { key: "nominal_voltage", label: "Nominal voltage", units: ["V", "mV"] },
  { key: "mass", label: "Mass", units: ["g", "kg"] },
  { key: "energy_density", label: "Energy density", units: ["Wh/kg", "Wh/L"] },
  { key: "internal_resistance", label: "Internal resistance", units: ["mΩ", "Ω"] },
  { key: "diameter", label: "Diameter", units: ["mm", "cm"] },
  { key: "height", label: "Height", units: ["mm", "cm"] },
];
const ELECTRODE_PROPS: PropDef[] = [
  { key: "loading", label: "Areal mass loading", units: ["mg/cm2"] },
  { key: "thickness", label: "Coating thickness", units: ["um"] },
];
const MATERIAL_PROPS: PropDef[] = [{ key: "specific_capacity", label: "Specific capacity", units: ["mAh/g"] }];

export const OBJECT_TYPES: ObjectDef[] = [
  {
    key: "cell",
    label: "Cell",
    blurb: "A cell design (spec) and a physical unit built to it (instance).",
    sections: [
      {
        key: "spec",
        title: "Cell spec",
        blurb: "The reusable design of a cell: format, chemistry, electrodes, and rated properties. Many physical cells can share one spec.",
      },
      {
        key: "instance",
        title: "Cell instance",
        blurb: "One physical cell built to the spec, with its own serial number and dates. On save it links back to the spec.",
      },
    ],
    fields: [
      { key: "manufacturer", label: "Manufacturer", kind: "text", section: "spec" },
      { key: "model", label: "Model", kind: "text", section: "spec" },
      { key: "format", label: "Format", kind: "select", options: ["coin", "cylindrical", "pouch", "prismatic"], section: "spec" },
      { key: "chemistry", label: "Chemistry", kind: "select", options: ["Li-ion", "Li-metal", "Na-ion", "Alkaline"], section: "spec" },
      { key: "positiveBasis", label: "Positive electrode", kind: "text", placeholder: "e.g. LFP", section: "spec" },
      { key: "negativeBasis", label: "Negative electrode", kind: "text", placeholder: "e.g. graphite", section: "spec" },
      { key: "instanceName", label: "Name / label", kind: "text", placeholder: "e.g. Cell 001", section: "instance" },
      { key: "serial_number", label: "Serial number", kind: "text", placeholder: "e.g. SN-0001", section: "instance" },
      { key: "manufactured_at", label: "Production date", kind: "date", section: "instance" },
      { key: "expires_at", label: "Expiration date", kind: "date", section: "instance" },
    ],
    properties: CELL_PROPS,
    defaults: {
      manufacturer: "A123", model: "ANR26650M1-B", format: "cylindrical", chemistry: "Li-ion",
      positiveBasis: "LFP", negativeBasis: "graphite",
      instanceName: "Cell 001", serial_number: "SN-0001", manufactured_at: "2024-06-01", expires_at: "2034-06-01",
    },
    defaultProperties: [
      { key: "nominal_capacity", value: "2.5", unit: "Ah" },
      { key: "nominal_voltage", value: "3.3", unit: "V" },
    ],
    toRecord: (v, props) => {
      const spec: Record<string, unknown> = {};
      const specName = [v.manufacturer, v.model].filter(Boolean).join(" ").trim();
      if (specName) spec.name = specName;
      if (v.model) spec.model = v.model;
      if (v.manufacturer) spec.manufacturer = { type: "Organization", name: v.manufacturer };
      if (v.format) spec.cell_format = v.format;
      if (v.chemistry) spec.chemistry = v.chemistry;
      if (v.positiveBasis) spec.positive_electrode_basis = v.positiveBasis;
      if (v.negativeBasis) spec.negative_electrode_basis = v.negativeBasis;
      const specRecord: Record<string, unknown> = { schema_version: "0.1.0", cell_spec: spec };
      const p = propBlock(props);
      if (Object.keys(p).length) specRecord.properties = p;

      const instance: Record<string, unknown> = {};
      if (v.instanceName) instance.name = v.instanceName;
      if (v.serial_number) instance.serial_number = v.serial_number;
      if (v.manufactured_at) instance.manufactured_at = v.manufactured_at;
      if (v.expires_at) instance.expires_at = v.expires_at;
      const instanceRecord = { schema_version: "0.1.0", cell_instance: instance };
      return [specRecord, instanceRecord];
    },
    toPython: (v, props) => {
      const specName = [v.manufacturer, v.model].filter(Boolean).join(" ").trim();
      const lines = ["from battinfo import CellSpec, create_cell_instance", "", "spec = CellSpec("];
      lines.push(...pyKwargs([
        ["name", specName], ["manufacturer", v.manufacturer], ["model", v.model],
        ["format", v.format], ["chemistry", v.chemistry],
        ["positive_electrode_basis", v.positiveBasis], ["negative_electrode_basis", v.negativeBasis],
      ]));
      lines.push(...pyProps(props), ")", "spec_record = spec.to_record()", "");
      lines.push("# one physical cell built to the spec");
      lines.push("instance = create_cell_instance(");
      lines.push('    cell_spec_id=spec_record["cell_spec"]["id"],');
      lines.push(...pyKwargs([
        ["name", v.instanceName], ["serial_number", v.serial_number],
        ["manufactured_at", v.manufactured_at], ["expires_at", v.expires_at],
      ]));
      lines.push(")");
      return lines.join("\n");
    },
    toJsonLd: (v, props) => {
      const specName = [v.manufacturer, v.model].filter(Boolean).join(" ").trim();
      const specDoc: Record<string, unknown> = { "@type": ["BatteryCellSpecification", "schema:CreativeWork"] };
      if (specName) specDoc.name = specName;
      if (v.model) specDoc.model = v.model;
      if (v.manufacturer) specDoc.manufacturer = { "@type": "schema:Organization", name: v.manufacturer };
      const physical = ["BatteryCell"];
      if (FORMAT_CLASS[v.format]) physical.push(FORMAT_CLASS[v.format]);
      if (CHEMISTRY_CLASS[v.chemistry]) physical.push(CHEMISTRY_CLASS[v.chemistry]);
      specDoc.isDescriptionFor = { "@type": physical };
      const pos = electrodeNode(v.positiveBasis);
      const neg = electrodeNode(v.negativeBasis);
      if (pos) specDoc.hasPositiveElectrode = pos;
      if (neg) specDoc.hasNegativeElectrode = neg;
      const hp = jsonldProps(props);
      if (hp.length) specDoc.hasProperty = hp;

      const instanceDoc: Record<string, unknown> = { "@type": "BatteryCell" };
      if (v.instanceName) instanceDoc.name = v.instanceName;
      if (v.serial_number) instanceDoc["schema:serialNumber"] = v.serial_number;
      return [withContext(specDoc), withContext(instanceDoc)];
    },
  },
  {
    key: "material_spec",
    label: "Material spec",
    blurb: "A reusable substance: an active material, binder, or additive.",
    fields: [
      { key: "name", label: "Name", kind: "text", placeholder: "e.g. NMC811" },
      { key: "material_class", label: "Material class", kind: "select", options: ["active_material", "binder", "conductive_additive"] },
      { key: "formula", label: "Formula", kind: "text", placeholder: "e.g. LiNi0.8Mn0.1Co0.1O2" },
      { key: "chemistry_family", label: "Chemistry family", kind: "text", placeholder: "e.g. lithium nickel manganese cobalt oxide" },
    ],
    properties: MATERIAL_PROPS,
    defaults: { name: "NMC811", material_class: "active_material", formula: "LiNi0.8Mn0.1Co0.1O2", chemistry_family: "lithium nickel manganese cobalt oxide" },
    defaultProperties: [{ key: "specific_capacity", value: "188", unit: "mAh/g" }],
    toRecord: (v, props) => {
      const body: Record<string, unknown> = {};
      if (v.name) body.name = v.name;
      if (v.material_class) body.material_class = v.material_class;
      if (v.formula) body.formula = v.formula;
      if (v.chemistry_family) body.chemistry_family = v.chemistry_family;
      const p = propBlock(props);
      if (Object.keys(p).length) body.property = p;
      return { schema_version: "0.1.0", material_spec: body };
    },
    toPython: (v, props) => {
      const lines = ["from battinfo import create_material_spec", "", "record = create_material_spec("];
      lines.push(...pyKwargs([["name", v.name], ["material_class", v.material_class], ["formula", v.formula], ["chemistry_family", v.chemistry_family]]));
      const list = activeProps(props);
      if (list.length) {
        lines.push("    property={");
        for (const p of list) lines.push(`        "${p.key}": {"value": ${JSON.stringify(num(p.value))}, "unit": ${JSON.stringify(p.unit)}},`);
        lines.push("    },");
      }
      lines.push(")");
      return lines.join("\n");
    },
    toJsonLd: (v, props) => {
      const types: string[] = [];
      if (SUBSTANCE[v.name]) types.push(SUBSTANCE[v.name]);
      if (MATERIAL_ROLE[v.material_class]) types.push(MATERIAL_ROLE[v.material_class]);
      const doc: Record<string, unknown> = {};
      if (types.length) doc["@type"] = types.length === 1 ? types[0] : types;
      if (v.name) doc.name = v.name;
      const hp = jsonldProps(props);
      if (hp.length) doc.hasProperty = hp;
      return withContext(doc);
    },
  },
  {
    key: "electrode_spec",
    label: "Electrode spec",
    blurb: "A coated electrode: an active material on a current collector.",
    fields: [
      { key: "name", label: "Name", kind: "text", placeholder: "e.g. NMC cathode" },
      { key: "polarity", label: "Polarity", kind: "select", options: ["positive", "negative"] },
      { key: "active", label: "Active material", kind: "text", placeholder: "e.g. NMC" },
      { key: "collector", label: "Current collector", kind: "text", placeholder: "e.g. Aluminium foil" },
    ],
    properties: ELECTRODE_PROPS,
    defaults: { name: "NMC cathode", polarity: "positive", active: "NMC", collector: "Aluminium foil" },
    defaultProperties: [
      { key: "loading", value: "6.6", unit: "mg/cm2" },
      { key: "thickness", value: "16", unit: "um" },
    ],
    toRecord: (v, props) => {
      const coating: Record<string, unknown> = { component: { active_material: [{ name: v.active }] } };
      const p = propBlock(props);
      if (Object.keys(p).length) coating.property = p;
      const body: Record<string, unknown> = { coating };
      if (v.name) body.name = v.name;
      if (v.polarity) body.polarity = v.polarity;
      if (v.collector) body.current_collector = { name: v.collector };
      return { schema_version: "0.1.0", electrode_spec: body };
    },
    toPython: (v, props) => {
      const body = { coating: { component: { active_material: [{ name: v.active }] }, property: propBlock(props) }, current_collector: { name: v.collector } };
      return [
        "from battinfo import create_component_spec",
        "",
        'record = create_component_spec(',
        '    "electrode",',
        ...pyKwargs([["name", v.name], ["polarity", v.polarity]]),
        `    body=${JSON.stringify(body, null, 4).replace(/\n/g, "\n    ")},`,
        ")",
      ].join("\n");
    },
    toJsonLd: (v, props) => {
      const doc: Record<string, unknown> = { "@type": "Electrode" };
      if (v.name) doc.name = v.name;
      const active: Record<string, unknown> = SUBSTANCE[v.active] ? { "@type": SUBSTANCE[v.active], name: v.active } : { "@type": "ActiveMaterial", name: v.active };
      doc.hasActiveMaterial = active;
      if (v.collector) doc.hasCurrentCollector = { "@type": "CurrentCollector", name: v.collector };
      const hp = jsonldProps(props);
      if (hp.length) doc.hasProperty = hp;
      return withContext(doc);
    },
  },
  {
    key: "electrolyte_spec",
    label: "Electrolyte spec",
    blurb: "A salt-in-solvent electrolyte recipe.",
    fields: [
      { key: "name", label: "Name", kind: "text", placeholder: "e.g. 1M LiPF6 EC:DMC" },
      { key: "family", label: "Family", kind: "select", options: ["organic", "aqueous", "ionic liquid", "polymer", "solid"] },
      { key: "salt", label: "Salt", kind: "text", placeholder: "e.g. LiPF6" },
      { key: "solvents", label: "Solvents (comma-separated)", kind: "text", placeholder: "e.g. EC, DMC" },
    ],
    defaults: { name: "1M LiPF6 EC:DMC", family: "organic", salt: "LiPF6", solvents: "EC, DMC" },
    toRecord: (v) => {
      const body: Record<string, unknown> = {};
      if (v.family) body.family = v.family;
      if (v.name) body.name = v.name;
      if (v.salt) body.salt = { name: v.salt };
      const solvents = v.solvents.split(",").map((s) => s.trim()).filter(Boolean);
      if (solvents.length) body.solvent_mixture = { component: solvents.map((name) => ({ name })) };
      return { schema_version: "0.1.0", electrolyte_spec: body };
    },
    toPython: (v) => {
      const solvents = v.solvents.split(",").map((s) => s.trim()).filter(Boolean);
      const body = { family: v.family, salt: { name: v.salt }, solvent_mixture: { component: solvents.map((name) => ({ name })) } };
      return [
        "from battinfo import create_component_spec",
        "",
        'record = create_component_spec(',
        '    "electrolyte",',
        ...pyKwargs([["name", v.name]]),
        `    body=${JSON.stringify(body, null, 4).replace(/\n/g, "\n    ")},`,
        ")",
      ].join("\n");
    },
    toJsonLd: (v) => {
      const doc: Record<string, unknown> = { "@type": "ElectrolyteSolution" };
      if (v.name) doc.name = v.name;
      if (v.salt) doc.hasSolute = SUBSTANCE[v.salt] ? { "@type": SUBSTANCE[v.salt], name: v.salt } : { "@type": "Solute", name: v.salt };
      const solvents = v.solvents.split(",").map((s) => s.trim()).filter(Boolean);
      if (solvents.length) {
        doc.hasSolvent = {
          "@type": "Solvent",
          hasConstituent: solvents.map((name) => (SUBSTANCE[name] ? { "@type": SUBSTANCE[name], name } : { name })),
        };
      }
      return withContext(doc);
    },
  },
  {
    key: "test",
    label: "Test",
    blurb: "A measurement performed on a cell.",
    fields: [
      { key: "name", label: "Name", kind: "text", placeholder: "e.g. Rate capability" },
      { key: "cell_id", label: "Cell IRI", kind: "text", placeholder: "https://w3id.org/battinfo/cell/…" },
      { key: "kind", label: "Kind", kind: "select", options: ["cycling", "eis", "dcir", "quasi_ocv", "capacity_check"] },
      { key: "status", label: "Status", kind: "select", options: ["completed", "planned", "running"] },
    ],
    defaults: { name: "Rate capability", cell_id: "https://w3id.org/battinfo/cell/7d9k-2m4p-8t3x-6nq5", kind: "cycling", status: "completed" },
    toRecord: (v) => {
      const body: Record<string, unknown> = {};
      if (v.name) body.name = v.name;
      if (v.cell_id) body.cell_id = v.cell_id;
      if (v.kind) body.kind = v.kind;
      if (v.status) body.status = v.status;
      return { schema_version: "0.1.0", test: body };
    },
    toPython: (v) => [
      "from battinfo import Test",
      "",
      "record = Test(",
      ...pyKwargs([["name", v.name], ["cell_id", v.cell_id], ["kind", v.kind], ["status", v.status]]),
      ").to_record()",
    ].join("\n"),
    toJsonLd: (v) => {
      const doc: Record<string, unknown> = { "@type": "BatteryTest" };
      if (v.name) doc.name = v.name;
      return withContext(doc);
    },
  },
  {
    key: "dataset",
    label: "Dataset",
    blurb: "The files a test produced, with where to get them.",
    fields: [
      { key: "name", label: "Name", kind: "text", placeholder: "e.g. Cycling data for Cell 001" },
      { key: "access_url", label: "Access URL", kind: "text", placeholder: "https://…" },
      { key: "description", label: "Description", kind: "text" },
    ],
    defaults: { name: "Cycling data for Cell 001", access_url: "https://example.org/data/cell-001.csv", description: "Galvanostatic cycling export." },
    toRecord: (v) => {
      const body: Record<string, unknown> = {};
      if (v.name) body.name = v.name;
      if (v.access_url) body.access_url = v.access_url;
      if (v.description) body.description = v.description;
      return { schema_version: "0.1.0", dataset: body };
    },
    toPython: (v) => [
      "from battinfo import Dataset",
      "",
      "record = Dataset(",
      ...pyKwargs([["title", v.name], ["access_url", v.access_url], ["description", v.description]]),
      ").to_record()",
    ].join("\n"),
    toJsonLd: (v) => {
      const doc: Record<string, unknown> = { "@type": "schema:Dataset" };
      if (v.name) doc["schema:name"] = v.name;
      if (v.access_url) doc["schema:url"] = v.access_url;
      if (v.description) doc["schema:description"] = v.description;
      return withContext(doc);
    },
  },
];

export interface DraftStatus {
  level: "green" | "yellow" | "red";
  issues: Issue[];
}

// Live check of the emitted record(s) against the canonical schemas. Identifiers
// and references are minted on save, so issues about them are set aside here.
export function draftStatus(emitted: Emitted): DraftStatus {
  const records = Array.isArray(emitted) ? emitted : [emitted];
  const issues: Issue[] = [];
  for (const record of records) {
    for (const issue of validateRecord(JSON.stringify(record)).issues) {
      const p = issue.path;
      // Fields added by the library on save, not authored in the playground.
      const saveTime =
        p === "id" || p.endsWith(".id") || p.endsWith("_id") ||
        p === "provenance" || p.endsWith(".provenance") ||
        p === "identifier" || p.endsWith(".identifier") ||
        /\bIRI\b/i.test(issue.message);
      if (!saveTime) issues.push(issue);
    }
  }
  const errors = issues.filter((i) => i.severity === "error").length;
  const warnings = issues.filter((i) => i.severity === "warning").length;
  return { level: errors ? "red" : warnings ? "yellow" : "green", issues };
}
