# Ontology additions needed (domain-battery)

Consolidated list of EMMO domain-battery terms the BattINFO model now references but
that are **not yet published** in the ontology. Each is wired in code with a graceful
fallback (allowlisted as a local term, emitted as a bare `@type`, or stubbed via a
pending-flag), so nothing is blocked — but publishing these makes the JSON-LD fully
ontology-resolvable. After publishing, flip the noted code stubs.

## 1. Property-nature qualifier (coin-cell initiative)

| Term | Kind | Placement | Purpose |
|---|---|---|---|
| **`RatedProperty`** | Class | `rdfs:subClassOf ConventionalProperty` (sibling of `NominalProperty`) | Type "rated" declared values, esp. normalized rated capacities `[AreicCapacity, RatedProperty]` / `[DischargingSpecificCapacity, RatedProperty]`. Distinct from `NominalProperty` (typical/reference). |

**Code stub to flip when published:** `transform/json_to_jsonld.py` →
`PENDING_CO_TYPE_AVAILABLE["RatedProperty"] = True`. The curated map already carries
`co_type_pending: "RatedProperty"` on `rated_areal_discharge_capacity` /
`rated_specific_discharge_capacity`. Until then they emit `ConventionalProperty`.

Suggested elucidation: *"A conventional property whose value is a declared rating
established under a specified rating procedure or standard (e.g. IEC 61960), as distinct
from a NominalProperty (an approximate/representative reference value)."*

## 2. Hardware / assembly classes (engineering initiative)

| Term | Kind | Emitted as | Status |
|---|---|---|---|
| **`Seal`** | Class | `@type: Seal` under `hasConstituent` (pouch/prismatic seal) | allowlisted as local term; emitted today |
| **`JellyRoll`** | Class | `@type: JellyRoll` under `hasConstituent` (wound electrode assembly; sibling of the existing `ElectrodeStack`) | allowlisted as local term; emitted today |
| **`CeramicCoating`** | Class | (not yet emitted) a secondary ceramic coating layer on an electrode | reserved; emit once ceramic-coating modeling lands |

**Code:** these are in `validate/jsonld.py` `_EXPLICIT_ALLOWED_TYPE_TERMS` under the
"Housing / hardware" and "Electrode assembly" comments. No flip needed — just publishing
makes them resolve in the context. (`ElectrodeStack`, `Terminal`, `CurrentCollectorTab`,
`PrismaticCase`/`PouchCase`/`CylindricalCase`/`CoinCase`, `CellLid`, `CellCan`, `Spring`,
`Spacer` already exist in domain-battery.)

## 3. Property classes — currently `battinfo:` fallbacks (optional)

These engineering quantities have no clean EMMO term, so they emit under the `battinfo:`
namespace (not lost, just not domain-battery-resolvable). Publish if you want them
first-class:

| Candidate term | Property key | Quantity |
|---|---|---|
| **`FillingRatio`** | `filling_ratio` | case electrolyte/jelly-roll fill ratio (dimensionless) |
| **`ElectrolyteDoseCoefficient`** | `dose_coefficient` | electrolyte dosing (g/Ah) |
| **`WeldWidth`** | `weld_width` | tab/terminal weld width |
| **`TapeWidth`** | `tape_width` | tab insulating-tape width |

To wire after publishing: add a curated entry to
`assets/mappings/domain-battery/property_map.curated.json` (and the `src/battinfo/data`
mirror) with the new `class_iri` — the descriptor then emits the real `@type` instead of
the `battinfo:` fallback.

## 4. Optional — loading-side qualifier

`single_side_loading` / `double_side_loading` both currently type as `MassLoading`
(distinct keys, distinction kept in key/label). If you want to type-distinguish them, add
**`SingleSide`** / **`DoubleSide`** property-nature qualifiers (parallel to
`RatedProperty`) and dual-type `[MassLoading, DoubleSide]`. Not required.

## Already published & in use (no action)

`AreicCapacity`, `SpecificCapacity`, `DischargingSpecificCapacity`, `TheoreticalCapacity`,
`NPRatio`, `Mass`, `Diameter`, `Thickness`, `Width`, `Length`, `Volume`, `Density`,
`Porosity`, `Tortuosity`, `D50ParticleSize`, `MassLoading`, `ActiveMassLoading`,
`CalenderedDensity`, `ElectrodeStack`, `Terminal`, `CurrentCollectorTab`, `*Case`,
`CellLid`, `CellCan`, `Spring`, `Spacer`, and the electrode chemistry classes
(`LithiumManganeseIronPhosphateElectrode`, `LithiumManganeseOxideElectrode`,
`LithiumTitanateElectrode`, …).


## Continuous-current rated properties (red-team W3.3, 2026-07-07)

The canonical schema accepts `nominal_continuous_charging_current` /
`nominal_continuous_discharging_current` (datasheet staples), but neither has
a resolvable EMMO class - the candidate mappings point at fabricated
`w3id.org/emmo/domain/battery#nominalContinuous...` IRIs that do not exist.
Until EMMO gains these terms, the keys validate with a
`semantic.property_unmapped` warning and are omitted from JSON-LD.

- **NominalContinuousChargingCurrent** - proposed electrochemistry class
- **NominalContinuousDischargingCurrent** - proposed electrochemistry class
- Also unmapped SpecSet keys awaiting terms or curation: capacity_fade,
  capacity_threshold_exhaustion, charging_time, cycle_life_c_rate,
  maximum_power, power_capability, power_density, power_energy_ratio,
  round_trip_energy_efficiency(-_50pct), specific_power
  (see tests/test_validation_plausibility.py KNOWN_UNMAPPED - the list may
  only shrink).
