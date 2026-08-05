# Ontology additions needed (domain-battery)

Working queue of EMMO terms the BattINFO model references but that are **not yet
published** upstream. Each is wired in code with a graceful fallback (allowlisted as a
local term, emitted as a bare `@type`, or stubbed via a pending-flag), so nothing is
blocked — but publishing them makes the JSON-LD fully ontology-resolvable. After
publishing, flip the noted code stubs.

Policy (2026-07-07): battinfo never mints domain semantics. Missing terms are added to
EMMO domain-battery / domain-electrochemistry / domain-chemical-substance upstream (we
control them), not here.

Currently pinned: domain-battery 0.20.1, domain-electrochemistry 0.36.0,
domain-chemical-substance 0.15.0, EMMO 1.0.2.

## 1. Property-nature qualifier (coin-cell initiative)

| Term | Kind | Placement | Purpose |
|---|---|---|---|
| **`RatedProperty`** | Class | `rdfs:subClassOf ConventionalProperty` (sibling of `NominalProperty`) | Type "rated" declared values, esp. normalized rated capacities `[AreicCapacity, RatedProperty]` / `[DischargingSpecificCapacity, RatedProperty]`. Distinct from `NominalProperty` (typical/reference). |

Deliberately **not** added in the 0.20.1 / 0.36.0 cycle. The stub therefore stays as it
is: `transform/json_to_jsonld.py` → `PENDING_CO_TYPE_AVAILABLE["RatedProperty"] = False`,
and the curated map keeps `co_type_pending: "RatedProperty"` on
`rated_areal_discharge_capacity` / `rated_specific_discharge_capacity`. They emit
`ConventionalProperty` meanwhile. Flip the flag to `True` when the class lands.

Suggested elucidation: *"A conventional property whose value is a declared rating
established under a specified rating procedure or standard (e.g. IEC 61960), as distinct
from a NominalProperty (an approximate/representative reference value)."*

## 2. Property classes — currently `battinfo:` fallbacks (optional)

These engineering quantities have no clean EMMO term, so they emit under the `battinfo:`
namespace (not lost, just not domain-battery-resolvable). Publish if you want them
first-class:

| Candidate term | Property key | Quantity |
|---|---|---|
| **`FillingRatio`** | `filling_ratio` | case electrolyte/jelly-roll fill ratio (dimensionless) |
| **`ElectrolyteDoseCoefficient`** | `dose_coefficient` | electrolyte dosing (g/Ah) |
| **`WeldWidth`** | `weld_width` | tab/terminal weld width |
| **`TapeWidth`** | `tape_width` | tab insulating-tape width |

A different shape of gap, same section: **a `CapacityFade` quantity class.**
`capacity_fade` is a `%`- or `1/cycle`-valued datasheet slot, and the only
upstream term for the concept — `electrochemistry:CapacityFade`
(`electrochemistry_e3d3d21c_cb9a_498c_bdb0_63c964f0d3c6`) — is an
`ElectrochemicalDegradationPhenomenon`, i.e. it sits on the EMMO *Process*
branch, not under `CategorizedPhysicalQuantity`. The slot points at it anyway
(minting `battinfo:capacityFade` would fork one concept across two IRIs), and
`src/battinfo/data/shapes/cell-spec.shapes.ttl` gives that phenomenon a numeric
part and a unit. What is wanted upstream is a quantity class under
`ElectrochemicalPerformanceQuantity` — the fade *rate*, related to the phenomenon
rather than identical to it. `ChargeRetention`/`CapacityRetention`
(`electrochemistry_49efb72a_…`) is not a substitute: it is defined for
open-circuit stand, not cycling.

To wire after publishing: add a curated entry to
`assets/mappings/domain-battery/property_map.curated.json` (and the `src/battinfo/data`
mirror) with the new `class_iri` — the descriptor then emits the real `@type` instead of
the `battinfo:` fallback.

## 3. Optional — loading-side qualifier

`single_side_loading` / `double_side_loading` both currently type as `MassLoading`
(distinct keys, distinction kept in key/label). If you want to type-distinguish them, add
**`SingleSide`** / **`DoubleSide`** property-nature qualifiers (parallel to
`RatedProperty`) and dual-type `[MassLoading, DoubleSide]`. Not required.

## 4. Continuous-current rated properties (red-team W3.3, 2026-07-07)

The canonical schema accepts `nominal_continuous_charging_current` /
`nominal_continuous_discharging_current` (datasheet staples), but neither has a
resolvable EMMO class — the candidate mappings still point at fabricated
`w3id.org/emmo/domain/battery#nominalContinuous...` IRIs that do not exist in the 0.20.1
closure. Until EMMO gains these terms, the keys validate with a
`semantic.property_unmapped` warning and are omitted from JSON-LD.

- **NominalContinuousChargingCurrent** — proposed electrochemistry class
- **NominalContinuousDischargingCurrent** — proposed electrochemistry class
- Also unmapped SpecSet keys awaiting terms or curation: `capacity_threshold_exhaustion`,
  `charging_time`, `cycle_life_c_rate`, `maximum_power`, `power_capability`,
  `power_energy_ratio`, `round_trip_energy_efficiency(_50pct)`
  (see `tests/test_validation_plausibility.py` `KNOWN_UNMAPPED` — the list may only shrink).

## Landed upstream — stubs flipped

### domain-electrochemistry 0.36.0

| Term | Where it is now wired |
|---|---|
| `Seal` | `_HARDWARE_PART_TYPE["seal"]` |
| `Gasket` | `_HARDWARE_PART_TYPE["gasket"]` |
| `SafetyVent` | `_HARDWARE_PART_TYPE["vent"]`, `["safety vent"]` |
| `CurrentInterruptDevice` | `_HARDWARE_PART_TYPE["cid"]`, `["current interrupt device"]` |
| `InsulatorRing` | `_HARDWARE_PART_TYPE["insulator"]`, `["insulator ring"]` |
| `WaveSpring` | `_HARDWARE_PART_TYPE["wave spring"]` |
| `WoundStack` (altLabels JellyRoll, SwissRoll) | `_descriptor_electrode_assembly_to_jsonld` — emits the **prefLabel**, since altLabels do not resolve through a context |
| `CeramicCoating` | context + validator allowlist only; no coating-layer emitter yet (separator `coating` is still a free-text field) |
| `DryCoatingThickness` | `_DESCRIPTOR_COATING_PROPERTY_TERMS["dry_thickness"]` |
| `MinimumOperatingTemperature` / `MaximumOperatingTemperature` | curated map + `schema/cell-spec.yaml` `slot_uri` for `operating_temperature_min` / `_max` (were `battinfo:` placeholders) |
| `TypicalCapacity` | curated map + `slot_uri` for `typical_capacity` (was sharing `NominalCapacity`) |
| `HalfCellDevice`, `ThreeElectrodeCellDevice` | `entity_type_map.json` `cell_configuration` section |

Also mapped in the same pass, though published earlier: `MaximumPulseChargingCurrent` /
`MaximumPulseDischargingCurrent`, for the `maximum_pulse_*_current` keys — only the
`pulse_*_current` spellings had been curated.

### domain-chemical-substance 0.15.0

The kind vocabulary (`material_kinds.json`) is fully anchored against this release: all
38 kinds carry a `chemsub` class, with `SiliconGraphite`, `HardCarbon`, `LithiumTitanate`,
`LithiumManganeseOxide`, `LithiumBistrifluoromethanesulfonylimide`,
`LithiumBisfluorosulfonylimide` and `NMethyl2Pyrrolidone` newly available, and the four
NMC ratios moved off the generic `LithiumNickelManganeseCobaltOxide` onto their
stoichiometric classes. `tests/test_materials_first_class.py` checks every `emmo` class
resolves in the bundled context and agrees with its `chemsub` anchor.

`LithiumNickelManganeseCobaltOxide111` / `532` / `622` / `811` (altLabels NMC111 …) and
`SiliconGraphite` are wired in `material_map.json`; a named NMC ratio now resolves to its
own class and bare "NMC" keeps the generic one. The pre-existing `LiTFSI`, `LiFSI` and
`NMP` classes were mapped at the same time.

### domain-battery 0.20.1

`BatteryHalfCell` (`rdfs:subClassOf BatteryCell`) is wired through the
`cell_configuration` section.

**Half-cell semantics (decision).** A battery half-cell types as the DEVICE classes
`BatteryHalfCell` + `HalfCellDevice`, never as `ElectrochemicalHalfCell`: upstream
annotates that class with an explicit warning against the conflation (it is one electrode
plus one electrolyte, not an experimental setup).

`cell_spec.cell_configuration` (`full_cell` | `half_cell` | `three_electrode_cell`,
optional, no default) now carries the statement. The `reference_electrode` heuristic
survives as the fallback for records that never state a configuration, but an explicit
value wins in both directions — `full_cell` suppresses the heuristic, which is what a
three-electrode full cell or a commercial cell under potential monitoring needs.
`three_electrode_cell` types as `ThreeElectrodeCellDevice`; `full_cell` adds no device
class at all. Both spellings (`three-electrode`, `three-electrode-cell`) are keyed in
`entity_type_map.json` so tolerant import and the schema enum land on the same mapping.

### Test-protocol method classes (chameo, via domain-electrochemistry 0.36.0)

`record_to_jsonld` emits test-protocol records as of the vocabulary top-up, and types the
plan node with the published characterisation-method class where the protocol's kind names
one: `GalvanostaticIntermittentTitrationTechnique` (gitt),
`PseudoOpenCircuitVoltageMethod` (quasi_ocv), `ElectrochemicalImpedanceSpectroscopy`
(eis/impedance), `HPPC`, `CyclingTest`, `CRateTest`, `CapacityTest`, `FormationCycling`.
The map is `battinfo.jsonld.TEST_METHOD_CLASS`; the IRIs are read from the bundled
domain-battery context rather than hard-coded, so the emitter, the hosted records context
and the validator allowlist cannot drift apart. Kinds with no published class
(`ici`, `dcir`, `calendar_ageing`, `rpt`, the drive cycles) keep the untyped
`prov:Plan` / `schema:HowTo` node — those are the open candidates if upstream wants them.

This closes readiness finding **M5** (test protocols were the last record type without
JSON-LD emission).

## Already published & in use (no action)

`AreicCapacity`, `SpecificCapacity`, `DischargingSpecificCapacity`, `TheoreticalCapacity`,
`NPRatio`, `Mass`, `Diameter`, `Thickness`, `Width`, `Length`, `Volume`, `Density`,
`Porosity`, `Tortuosity`, `D50ParticleSize`, `MassLoading`, `ActiveMassLoading`,
`CalenderedDensity`, `ElectrodeStack`, `Terminal`, `CurrentCollectorTab`, `*Case`,
`CellLid`, `CellCan`, `Spring`, `Spacer`, `RatedCapacity`, `StateOfHealth`, the storage /
charging / discharging temperature limits, and the electrode chemistry classes
(`LithiumManganeseIronPhosphateElectrode`, `LithiumManganeseOxideElectrode`,
`LithiumTitanateElectrode`, …).

## Upstream defects to report

Found while re-verifying every emitted IRI against the 0.20.1 closure. None is caused by
this repo; each is worked around locally.

- **`PrismaticBattery` local name uses hyphens.** `battery_86c9ca80-de6f-417f-afdc-a7e52fa6322d`,
  where every other domain-battery term uses underscores. Present since at least 0.19.0.
  The battinfo tables now copy it verbatim so the term expands to an IRI that exists; if
  upstream normalizes it, update `_STATIC_LABEL_TO_COMPACT`, `_BATTERY_TYPE_IRIS` and
  `scripts/assemble_context.py` together.
- **`Watthour` / `KiloWatthour` spelling.** EMMO's local names carry a lower-case "h"
  while the prefLabels read `WattHour` / `KiloWattHour`. `unit_map.curated.json` now
  follows the IRI and keeps the prefLabel as the label.
- **Deprecated classes still in active use.** The closure marks these
  `owl:deprecated true` with no stated successor, yet they are the only classes for the
  concepts: `LithiumIon{CobaltOxide,Graphite,IronPhosphate,ManganeseIronPhosphate,ManganeseOxide,NickelCobaltAluminiumOxide,NickelManganeseCobaltOxide,Titanate}Battery`
  and `Lithium{CobaltOxide,IronPhosphate,ManganeseIronPhosphate,ManganeseOxide,NickelManganeseCobaltOxide,Titanate}Electrode`,
  plus `SiliconGraphiteElectrode`. Deprecated since before 0.19.0 / 0.34.0, so this is not
  a regression — but either the deprecations or the battinfo mappings need to move.
- **`FaradaicEfficiency` / `CoulombicEfficiency` label swap (0.36.0).** IRIs unchanged;
  battinfo only maps `InitialCoulombicEfficiency`, which is unaffected.
