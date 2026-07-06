# Canonical Coin-Cell Description (Phase 0 design)

## 1. Purpose & scope

Define **one canonical way to describe a coin cell** in the BattINFO package that:

1. losslessly represents scraped lab sources such as `Discovery-benchmark.xlsx`
   (absolute masses, diameters, absolute capacity, N/P ratio, suppliers, hardware),
2. round-trips legacy **BattINFO Converter** coin-cell JSON-LD, and
3. is the single foundation both JSON-LD export views (`domain-battery` and
   `converter-compatible`) are projected from — the prerequisite for the
   long-term goal of BattINFO Converter calling `import battinfo` for conversion.

This document is the **arrangement + property-placement contract**. It does not
restate the normative record shape ([cell-descriptor-standard.md](cell-descriptor-standard.md))
or the interop seam ([converter-compatibility.md](converter-compatibility.md)); it
sits between them.

## 2. Locked decisions

- **D1 — Quantities: store both, no derivation.** A holder may carry an absolute
  quantity (Discovery: mg, mAh, mm) **and** a normalized one (converter: mg/cm²,
  mAh/cm², mAh/g) side by side. BattINFO does **not** compute one from the other;
  it persists what each source provides. N/P ratio and capacity relationships stay
  implicit unless a source states them.
- **D2 — Predicate: `hasProperty` + optional measured/conventional co-type.**
  Every quantity is attached with `hasProperty`. The property node is typed with
  its EMMO class, and **dual-typed** with `MeasuredProperty` or
  `ConventionalProperty` *when the source makes the distinction clear* — e.g.
  `@type: [Mass, MeasuredProperty]` (weighed), `@type: [Volume, ConventionalProperty]`
  (nominal/spec). **When unsure, emit the EMMO class alone and omit the co-type.**
  The `converter-compatible` view swaps `hasProperty → hasMeasuredProperty` and
  drops the co-type for byte-level converter fidelity.

## 3. Canonical holder tree

```
BatteryCell (CoinCell)
├─ hasPositiveElectrode / hasNegativeElectrode → Electrode
│    ├─ hasCurrentCollector → [CurrentCollector, <material>, <form>]
│    ├─ hasCoating → ElectrodeCoating
│    │    ├─ hasActiveMaterial → [<MaterialClass>, ActiveMaterial]
│    │    ├─ hasBinder → [Binder, <MaterialClass>]
│    │    └─ hasConductiveAdditive → [ConductiveAdditive, <MaterialClass>]
│    └─ (electrode-level properties)
├─ hasElectrolyte → <FamilyClass>
│    ├─ hasSolvent → Solvent → hasConstituent[…]
│    └─ hasSolute  → Solute  → hasConstituent[…]
│         └─ hasAdditive → Additive → hasConstituent[…]   (converter view)
├─ hasSeparator → [Separator, <material>]
├─ hasCase → [<sizeCode>, <material>] → (CellLid, CellCan with hasCoating)
└─ hasConstituent / hasComponent → Spring, Spacer
```

The BattINFO bundle mirrors this with `CellSpec` → `positive_electrode`
/`negative_electrode` (`Electrode`→`Coating`/`CurrentCollector`), `electrolyte`
(`Electrolyte`→`SolventMixture`/`Salt`/`additive[]`), `separator`, and a `housing`
model (`Case`/`Cap`/`Terminal`/`Seal`/`HardwarePart`; coin case/spring/spacer are
`Case` + `HardwarePart` parts). Each holder owns a free `property` dict whose keys are
routed through the curated property map.

> **Note (2026-06):** the legacy `coin_hardware` dict has been **retired** in favour of
> the format-neutral `housing` model (see
> [engineering-cell-description.md](engineering-cell-description.md)). A `coin_hardware`
> input is still accepted and auto-migrated into `housing` on load for back-compat.

## 4. Property-placement table (the contract)

Predicate is `hasProperty` everywhere (D2); the **Co-type** column is the default
classification when the source is clear, else omit. **Both** = appears in both
Discovery and converter sources. ✅ = round-trips today via `converter-compatible`;
⚠️ = not yet emitted by the `domain-battery` descriptor (Phase 2); ★ = needs a new
curated term (Phase 1).

| Holder | Property key | EMMO class | Default co-type | Source | Status |
|---|---|---|---|---|---|
| Cell | `nominal_capacity` | NominalCapacity | Conventional | Discovery (derived) | ✅ |
| Cell | `nominal_voltage` | NominalVoltage | Conventional | Discovery | ✅ |
| Cell | `n_p_ratio` | `NPRatio` (under RatioQuantity) | Conventional | Discovery | curated wiring (Phase 1) |
| Electrode | `diameter` | Diameter | Conventional | both | ✅ ⚠️ |
| Electrode ★ | `mass` | Mass | Measured | Discovery (disc w/ foil) | ★ ⚠️ |
| Electrode ★ | `theoretical_capacity` | TheoreticalCapacity (mAh) | Conventional | Discovery (abs mAh) | ★ ⚠️ |
| Electrode ★ | `rated_areal_discharge_capacity` | **AreicCapacity** (mAh/cm²) — see §4.1 | Conventional | converter | ★ ⚠️ |
| Electrode ★ | `rated_specific_discharge_capacity` | **DischargingSpecificCapacity** (mAh/g) — see §4.1 | Conventional | converter | ★ ⚠️ |
| Coating | `calendered_density` / thickness | CalenderedDensity / CalenderedCoatingThickness | Measured | converter | ✅ |
| Coating | `porosity` | Porosity | Measured | converter | ✅ |
| Coating | `tortuosity` | Tortuosity | Conventional | converter | ✅ ⚠️ |
| Coating ★ | `mass` | Mass | Measured | Discovery (no-foil) | ★ ⚠️ |
| ActiveMaterial | `mass_fraction` | MassFraction | Conventional | both | ✅ |
| ActiveMaterial | `loading` | MassLoading / ActiveMassLoading | Measured | both | ✅ — see §5.1 |
| ActiveMaterial | `d50_particle_size` | D50ParticleSize | Measured | converter | ✅ ⚠️ |
| ActiveMaterial | `molecular_formula` | molecularFormula (string) | — | converter | ✅ (field) |
| ActiveMaterial ★ | `mass` | Mass | Measured | Discovery (active mass) | ★ ⚠️ |
| Binder / Additive | `mass_fraction` | MassFraction | Conventional | both | ✅ |
| CurrentCollector | `thickness` | Thickness | Conventional | converter | ✅ |
| CurrentCollector | `diameter` / `mass` | Diameter / Mass | Conventional / Measured | Discovery | ★ ⚠️ |
| Electrolyte | `conductivity` `viscosity` `density` `temperature` | ElectrolyticConductivity / DynamicViscosity / Density / CelsiusTemperature | Measured | converter | ✅ |
| Electrolyte | `fill_volume` | Volume | Conventional | both | ✅ |
| Solvent constituent | `volume_fraction` | VolumeFraction | Conventional | both | ✅ |
| Solute / additive constituent | `concentration` | AmountConcentration | Conventional | both | ✅ |
| Separator | `thickness` `porosity` `tortuosity` `diameter` | Thickness / Porosity / Tortuosity / Diameter | mixed | both | ✅ |
| Case | size/material | `<sizeCode>` / `<material>` as @type | — | both | ✅ |
| Spring / Spacer | `diameter` `thickness` | Diameter / Thickness | Conventional | both | ✅ |

EMMO classes in parentheses with `?` require IRI verification against
domain-battery 0.18.7 in Phase 1 before use.

### 4.1 Capacity & normalized-quantity typing (rated / areal / specific)

The BattINFO Converter types **every** electrode capacity as `RatedCapacity`,
distinguished only by unit (mAh, mAh/cm², mAh/g). This is **dimensionally
incorrect**: `RatedCapacity` is a `Capacity` (dimension of charge, mAh). A value
in mAh/cm² is charge-per-area and a value in mAh/g is charge-per-mass — different
quantity kinds. We keep this overload **only in the `converter-compatible` view**,
for byte-for-byte legacy round-trip. The **canonical view uses the correct EMMO
class** (verified present in domain-battery 0.18.7):

| Quantity (unit) | Canonical `@type` | `converter-compatible` `@type` |
|---|---|---|
| absolute capacity (mAh) | `Capacity` / `RatedCapacity` / `NominalCapacity` / `TheoreticalCapacity` | `RatedCapacity` |
| areal capacity (mAh/cm²) | `AreicCapacity` | `RatedCapacity` |
| specific capacity (mAh/g) | `SpecificCapacity` / `DischargingSpecificCapacity` | `RatedCapacity` |

This works because the bundle already stores `rated_areal_discharge_capacity` and
`rated_specific_discharge_capacity` as **distinct keys** — the canonical exporter
types them by key, the converter view collapses both to `RatedCapacity`+unit.

**On "rated" vs "nominal" (verified gap):** domain-battery 0.18.7 has **no
`RatedProperty` class** (the available `…Property` qualifiers are
`ConventionalProperty`, `NominalProperty`, `MeasuredProperty`, `ModelledProperty`,
`CharacterisationProperty`, `ControlProperty`, …). So:
- For **absolute** capacities the rated/nominal/theoretical distinction *is*
  expressible via the dedicated classes `RatedCapacity` / `NominalCapacity` /
  `TheoreticalCapacity`.
- For **normalized** capacities only `AreicCapacity` / `SpecificCapacity` exist —
  no rated/nominal variant. The closest available co-type is `ConventionalProperty`
  (a rated value *is* a declared/conventional property, per D2), with the
  "rated/discharge" semantics preserved in the property key and `rdfs:label`.
- **Ontology decision (owner-approved path):** add a single class `RatedProperty`
  as a subclass of `ConventionalProperty` (sibling of `NominalProperty`). Then
  normalized rated capacities are dual-typed `[AreicCapacity, RatedProperty]` /
  `[SpecificCapacity, RatedProperty]`. Do **not** pre-compose the rated/nominal ×
  areic/specific/volumetric × charging/discharging cross-product as dedicated
  classes; compose via the nature co-type. `hasRatedProperty` relation NOT added
  (D2 uses plain `hasProperty`+co-type; EMMO's relation-per-nature pattern is
  already incomplete — no `hasNominalProperty`). `RatedProperty` is the **only**
  ontology term that needs adding; `NPRatio`, `AreicCapacity`, `SpecificCapacity`,
  `TheoreticalCapacity`, `Mass`, etc. all already exist in domain-battery 0.18.7.

Phase 1 adds curated map entries `rated_areal_discharge_capacity → AreicCapacity`,
`rated_specific_discharge_capacity → DischargingSpecificCapacity`,
`theoretical_capacity → TheoreticalCapacity` (the converter table in
`json_to_jsonld.py` keeps its `→ RatedCapacity` entries for the compat view).

## 5. Divergence resolutions

Five places where converter and BattINFO descriptor disagreed. With two export
views derived from one bundle, only one needs a model/transform change.

### 5.1 MassLoading placement — **change descriptor to active material**
Converter attaches `MassLoading` to the **active material**; the BattINFO
descriptor reads `loading` from the **coating** (`ActiveMassLoading`). The
importer already lands it on the active material, so the descriptor currently
fails to emit imported loading. **Decision:** canonical home is the **active
material** (`hasActiveMaterial → ActiveMaterial → hasProperty (MassLoading,…)`),
matching the converter and the EMMO semantics (loading *of the active material*).
Phase 2 migrates the descriptor coating-loading logic to the active material.

### 5.2 Electrolyte additive nesting — **keep bundle flat, nest in the view**
Converter nests `hasSolute → hasAdditive → Additive → hasConstituent`; the bundle
stores `electrolyte.additive[]` flat. **Decision:** bundle stays flat; the
`converter-compatible` view nests under solute (already implemented), the
`domain-battery` view emits `hasAdditive` at electrolyte level. No model change.

### 5.3 Case / hardware structure — **two views over the `housing` model**
Converter: `hasCase → hasComponent[CellLid, CellCan]` + cell-level `hasComponent`
for spring/spacer (v3.x) or `hasConstituent` (v1.1.x). **Decision (updated 2026-06):**
the bundle stores a format-neutral `housing` model (coin case/spring/spacer are
`Case` + `HardwarePart` parts; the legacy `coin_hardware` dict is auto-migrated into
it). The importer accepts all shapes; the descriptor emits `hasCase`+`hasConstituent`,
the converter view emits `hasCase→hasComponent`+cell `hasComponent`. See
[engineering-cell-description.md](engineering-cell-description.md).

### 5.4 Measured vs conventional — **resolved by D2** (co-type when clear, else omit).

### 5.5 Absolute vs normalized — **resolved by D1** (store both, no derivation).

## 6. Status & next phases

- **6 converter-compatible fixes landed** (2026-06-16): `converter → import →
  export(converter-compatible)` reproduces `coincell_jsonld_result.json` with
  zero property-node loss. Covers RatedCapacity (areal/specific), Tortuosity,
  MassLoading/CelsiusTemperature units, and `molecular_formula` modeling.
- **Phase 1** — curated vocab: `theoretical_capacity`, electrode/coating/active
  `mass`, `n_p_ratio`, `tortuosity`, `d50_particle_size` with verified
  domain-battery 0.18.7 IRIs (★ rows above).
- **Phase 2** — unify the exporter: descriptor routes each holder's full
  `property` dict through the curated map with the D2 rule, emits electrode-level
  property, moves loading to the active material (§5.1); `converter-compatible`
  becomes a thin predicate-swap view. Clears all ⚠️ rows.
- **Phase 3** — authoring helpers gain `mass=/diameter=/theoretical_capacity=/loading=`;
  holder×property validity via SHACL / `extension_policy.json`.
- **Phase 4** — Discovery scraper on this contract. **Phase 5** — expose the
  unified exporter for BattINFO Converter to `import battinfo`.

A regression test asserting the §6 round-trip is the green/red signal for the
whole effort.
