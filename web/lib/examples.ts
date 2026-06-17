// PLACEHOLDER fixtures for the Examples page.
//
// These mirror examples/cell-type/A123__ANR26650M1-B.json but are inlined so
// the website stays self-contained during active development. Replace with a
// build-time sync from `examples/**` once the sync script exists (see README).

export const cellTypeInput = {
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
// (abbreviated); the canonical transform lives in the Python package.
export const cellTypeJsonLd = {
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

export const quickstartPython = `from battinfo import CellType, publish

result = publish(
    CellType(
        manufacturer="A123",
        model="ANR26650M1-B",
        format="cylindrical",
        chemistry="Li-ion",
        nominal_properties={"nominal_capacity": {"value": 2.5, "unit": "Ah"}},
    ),
    destination="local",
)
print(result.canonical_iri)
# https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5`;

export const installSnippet = `python -m venv .venv
.venv/bin/pip install battinfo`;
