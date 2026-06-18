// Example fixtures for the website.
//
// SINGLE SOURCE OF TRUTH: the authored-input record comes from examples/** in
// the repo, surfaced via the generated module below (run `npm run sync:examples`
// to regenerate). The full example content must come from examples/** — only
// short, curated teasers (the hero / install / Python snippets, and the
// illustrative JSON-LD that the Python transform can't yet emit as a file) live
// inline here. See docs/CONTENT-MODEL.md §4.

export { cellSpecInput, cellSpecCanonical } from "./examples.generated";

// Sample for the client-demo Validate/Convert tools. These tools' simplified
// in-browser logic (lib/validate.ts, lib/convert.ts) still expects the
// pre-migration `product`/`specs` shape, so their sample must match that shape
// or the demos break. FOLLOW-UP: migrate validate.ts + convert.ts to the
// canonical `cell_spec`/`properties` shape, then point them at cellSpecInput
// and delete this. See docs/CONTENT-MODEL.md §4.
export const toolDemoInput = {
  schema_version: "0.1.0",
  product: {
    name: "A123 ANR26650M1-B",
    model: "ANR26650M1-B",
    manufacturer: { type: "Organization", name: "A123" },
    category: "battery cell",
    cell_format: "cylindrical",
    chemistry: "Li-ion",
    positive_electrode_basis: "LFP",
    size_code: "R26650",
  },
  specs: {
    nominal_capacity: { value: 2.5, unit: "Ah" },
    nominal_voltage: { value: 3.3, unit: "V" },
    mass: { value: 76.0, unit: "g" },
    diameter: { value: 26.0, unit: "mm" },
    height: { value: 65.0, unit: "mm" },
  },
};

// Representative of the JSON-LD that BattINFO emits — EMMO domain-battery
// aligned, with @type stacking and the canonical quantity pattern. Illustrative
// (abbreviated); the canonical transform lives in the Python package. This stays
// a curated teaser until the Python transform can emit canonical JSON-LD into
// examples/** (then it joins the sync).
export const cellSpecJsonLd = {
  "@context": "https://w3id.org/battinfo/context/domain-battery.jsonld",
  "@id": "https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5",
  "@type": [
    "BatteryCell",
    "CylindricalBattery",
    "LithiumIonBattery",
    "LithiumIronPhosphateBattery",
  ],
  "skos:prefLabel": "A123 ANR26650M1-B",
  manufacturer: { "@type": "Organization", name: "A123" },
  hasProperty: [
    {
      "@type": ["NominalCapacity", "ConventionalProperty"],
      hasNumericalPart: { "@type": "Real", hasNumericalValue: 2.5 },
      hasMeasurementUnit: "https://w3id.org/emmo#AmpereHour",
    },
    {
      "@type": ["NominalVoltage", "ConventionalProperty"],
      hasNumericalPart: { "@type": "Real", hasNumericalValue: 3.3 },
      hasMeasurementUnit: "https://w3id.org/emmo#Volt",
    },
  ],
};

// A deliberately friendly, single-record snippet for the hero — plain authored
// JSON, NOT JSON-LD. The point of the homepage is "this is easy"; the Linked
// Data machinery is shown later (Examples page) once people are interested.
export const heroSnippet = `{
  "name": "A123 ANR26650M1-B",
  "manufacturer": "A123",
  "chemistry": "Li-ion",
  "format": "cylindrical",
  "nominal_capacity": { "value": 2.5, "unit": "Ah" },
  "nominal_voltage":  { "value": 3.3, "unit": "V" }
}`;

export const quickstartPython = `from battinfo import CellSpecification, publish

result = publish(
    CellSpecification(
        manufacturer="A123",
        model="ANR26650M1-B",
        cell_format="cylindrical",
        chemistry="Li-ion",
        nominal_capacity={"value": 2.5, "unit": "Ah"},
    ),
    destination="local",
)
print(result.canonical_iri)
# https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5`;

export const installSnippet = `python -m venv .venv
.venv/bin/pip install battinfo`;
