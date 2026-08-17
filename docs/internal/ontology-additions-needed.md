# Ontology additions needed (domain-battery)

Working queue of EMMO terms the BattINFO model references but that are **not yet
published** upstream. Each is wired in code with a graceful fallback (allowlisted as a
local term, emitted as a bare `@type`, or stubbed via a pending-flag), so nothing is
blocked — but publishing them makes the JSON-LD fully ontology-resolvable. After
publishing, flip the noted code stubs.

Policy (2026-07-07): battinfo never mints domain semantics. Missing terms are added to
EMMO domain-battery / domain-electrochemistry / domain-chemical-substance upstream (we
control them), not here.

Currently pinned: domain-battery 0.20.2, domain-electrochemistry 0.37.2,
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

## 5. Statistical dispersion of a sample (gap E7, 2026-08-17)

A quantity may now state the spread of the sample it summarises — `standard_deviation` and `sample_count` alongside `value` and `unit` — because a batch average without its spread is the number labs actually have and could not publish. There is no EMMO class for either.

| Candidate term | Kind | Placement | Purpose |
|---|---|---|---|
| **`StandardDeviation`** | Class | property-nature qualifier or a `Quantity` subclass | The sample standard deviation of a set of measured values, in the unit of the value it qualifies. |
| **`SampleCount`** | Class | dimensionless quantity | How many members the summary was computed over. `CountingUnit` exists for the unit; the quantity does not. |
| **`hasSampleStatistic`** | Object property | on a `Property` | Attach the above to the property they qualify, the way `hasMeasurementParameter` attaches a condition. |

Searched and absent from the 0.20.2 / 0.37.2 / 1.0.2 closure: `StandardDeviation`, `StandardUncertainty`, `Variance`, `ArithmeticMean`, `Median`, `SampleCount`, `SampleSize`, `StatisticalQuantity`, `hasStandardDeviation`. The `Mean*` classes present (`MeanFreePath`, `MeanPoreSize`, …) are physics quantities, not statistics.

`MetrologicalUncertainty` (`EMMO_847724b7_…`) and `hasMetrologicalUncertainty` (`EMMO_662c64e7_…`) **are** in the closure and were deliberately not used. Per VIM, measurement uncertainty characterises the dispersion of values attributable to one measurand; a sample standard deviation over eight electrode discs characterises a population of distinct physical objects. Reusing the class would be a category claim of the same kind as the `CapacityFade` mapping fixed in 0.37.1, so the emitter says what it has instead: `schema:valueReference` → a named `schema:PropertyValue`.

To wire after publishing: `_SAMPLE_STATISTIC_TERMS` and `_apply_sample_statistics` in `transform/json_to_jsonld.py` are the only emission site (both quantity-node builders route through it); add the class to `validate/jsonld.py` `_EXPLICIT_ALLOWED_TYPE_TERMS`, and append the terms to `records.context.v1.json` via `scripts/gen_context.py`. Records already published with the `schema:` qualifier keep expanding as they do, so the flip is additive rather than a v2.

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

**Electrode roles (decision, maintainer ruling).** *Do not use polarity in a half cell —
use reference, working and counter electrode instead of positive or negative electrode.*
`cell_spec` therefore carries a second electrode holder family, `working_electrode` /
`counter_electrode` (with `working_electrode_spec_id` / `counter_electrode_spec_id`
mirroring the polarity siblings), selected by `cell_configuration`. They emit
`hasWorkingElectrode` / `hasCounterElectrode` typed `WorkingElectrode`
(`electrochemistry_fb988878_…`) and `CounterElectrode` (`electrochemistry_871bc4a4_…`).

The three role classes are non-disjoint upstream, which is what lets a half cell's counter
electrode also be its reference — the `HalfCellDevice` axiom. So under `half_cell` the
counter electrode is typed `[CounterElectrode, ReferenceElectrode]`
(`electrochemistry_7729c34e_…`) on one node, never as a second `hasReferenceElectrode`
relation to a second electrode. Under `three_electrode_cell` there IS a third electrode,
so the record's separate `reference_electrode` field carries the reference and the counter
electrode is typed `CounterElectrode` alone.

Composition typing is deliberately role-independent: one shared builder emits the holder
body (coating, current collector, tab, design properties, the `electrode_spec_id` seam) for
both families, because what an electrode is made of does not depend on the role it is given.
Cell typing is likewise unchanged — the device classes still come from `cell_configuration`.
What the roles do change is the basis fallback: once a non-full cell states its electrodes by
role, `positive_electrode_basis` / `negative_electrode_basis` no longer emit a polarity-named
electrode node beside them (they keep contributing to the cell `@type` stack). An electrode
the author actually wrote into a polarity holder is never suppressed this way; the save gate
warns about the mismatch instead. `electrode_spec.polarity` is untouched — that is the
design's intended full-cell side, derived from the kind, and roles are a cell-level
assignment.

### domain-electrochemistry 0.37.1 / 0.37.2

Six quantity classes landed and drained seven `battinfo:` placeholders. All are wired in
`property_map.curated.json` and the LinkML `slot_uri`s; the descriptor now emits the
upstream `@type` instead of the fallback term.

| Key | Was | Now |
|---|---|---|
| `capacity_fade` | `electrochemistry:CapacityFade` (a phenomenon) | `CapacityFadeRate` (`electrochemistry_5b59a86e_…`) |
| `charging_time` | `battinfo:chargingTime` | `ChargingTime` (`electrochemistry_a3d54f83_…`) |
| `maximum_power` | `battinfo:maximumPower` | `MaximumPower` (`electrochemistry_4e6c4e9d_…`) |
| `power_capability` | `battinfo:powerCapability` | `MaximumPower` — `PowerCapability` is its altLabel |
| `power_energy_ratio` | `battinfo:powerEnergyRatio` | `PowerToEnergyRatio` (`electrochemistry_917660a7_…`) |
| `round_trip_energy_efficiency` | `battinfo:roundTripEnergyEfficiency` | `RoundTripEnergyEfficiency` (`electrochemistry_c413d29a_…`) |
| `capacity_threshold_exhaustion` | `battinfo:capacityThresholdExhaustion` | `EndOfLifeCapacityThreshold` (`electrochemistry_02dc55b3_…`) |

`CapacityFadeRate` is the quantity class this file asked for: `capacity_fade` used to
point at `electrochemistry:CapacityFade`, an `ElectrochemicalDegradationPhenomenon` on
the EMMO *Process* branch, so a unit-bearing datasheet value was typed as a process.

`CapacityLoss` and `ChargeRecovery` also landed but have no save-gate key, so they are
allowlisted only. Wiring them is a future save-gate addition (`capacity_loss`,
`capacity_retention`, `charge_recovery`), not part of this pass.

Still unmapped, with no upstream class: `cycle_life_c_rate`,
`round_trip_energy_efficiency_50pct` (measurement qualifiers upstream does not name) and
the two `nominal_continuous_*_current` keys from section 4.

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

Found while re-verifying every emitted IRI against the 0.20.2 / 0.37.2 / 0.15.0 / 1.0.2
closure. None is caused by this repo; each is worked around locally.

- **`Watthour` / `KiloWatthour` spelling.** EMMO's local names carry a lower-case "h"
  while the prefLabels read `WattHour` / `KiloWattHour`. `unit_map.curated.json` now
  follows the IRI and keeps the prefLabel as the label.
- **`FaradaicEfficiency` / `CoulombicEfficiency` label swap (0.36.0).** IRIs unchanged;
  battinfo only maps `InitialCoulombicEfficiency`, which is unaffected.
- **Two `hasTestEquipment` object properties (new in 0.20.2).**
  `battery:battery_df4ff8f1_2cf2_444a_9498_23f533bd295c` (which battinfo declares and
  emits) and `electrochemistry:electrochemistry_52702560_2034_4369_ab7f_28e8bb32680c`
  now both carry that prefLabel. Neither is deprecated and neither points at the other,
  but the upstream domain-battery context repointed the *label* to the electrochemistry
  one, so a consumer resolving `hasTestEquipment` through that context and a consumer
  reading a battinfo record's own context land on different IRIs. battinfo keeps the
  battery term (still live, and already published in v1); upstream should merge them or
  deprecate one with `dcterms:isReplacedBy`.
- **Duplicate `CapacityLoss`.** `electrochemistry_652b94f1_…` has it as prefLabel while
  `electrochemistry_e3d3d21c_…` (`CapacityFade`) carries it as an altLabel, so the string
  resolves to two classes. battinfo maps neither by key; the label is allowlisted only.
- **Five context terms resolve to IRIs outside the import closure.** The published
  domain-battery 0.20.2 context maps `ChemicalMaterial`, `ElementalMaterial`,
  `ChemicallyDefinedMaterial`, `hasORCID` and `AngularWaveNumber` to
  `https://w3id.org/emmo#EMMO_{8a41ed1b…, a086af15…, a96e2152…, e117f976…, e4791212…}`,
  none of which is defined in EMMO 1.0.2 or in any imported module. Likely left over from
  a pre-1.0 EMMO. battinfo emits none of them, so nothing is broken here — but any
  consumer expanding those terms gets an IRI that does not dereference.

### Resolved upstream

- **`PrismaticBattery` local name used hyphens.** Fixed in domain-battery 0.20.2:
  upstream minted the underscore-named twin `battery_86c9ca80_de6f_417f_afdc_a7e52fa6322d`
  and deprecated the hyphenated original with `dcterms:isReplacedBy`
  ([domain-battery#73](https://github.com/emmo-repo/domain-battery/issues/73)).
  `_STATIC_LABEL_TO_COMPACT`, `_BATTERY_TYPE_IRIS` and `scripts/assemble_context.py`
  now emit the twin; the validator still accepts the hyphenated IRI so records published
  before the flip keep validating, and the frozen v1 context still serves it.
- **Deprecated chemistry classes still in active use.** Resolved in domain-battery 0.20.2
  / domain-electrochemistry 0.37.2
  ([domain-battery#74](https://github.com/emmo-repo/domain-battery/issues/74)). All 15 are
  now first-class defined classes:
  `LithiumIon{CobaltOxide,Graphite,IronPhosphate,ManganeseIronPhosphate,ManganeseOxide,NickelCobaltAluminiumOxide,NickelManganeseCobaltOxide,Titanate}Battery`,
  `Lithium{CobaltOxide,IronPhosphate,ManganeseIronPhosphate,ManganeseOxide,NickelManganeseCobaltOxide,Titanate}Electrode`
  and `SiliconGraphiteElectrode` (defined as `hasActiveMaterial some` chemical-substance
  `SiliconGraphite`). The battinfo mappings that used them needed no change and no code
  caveat existed to remove. Note that the **silicon-oxide** siblings
  (`LithiumIonSilicon{,Oxide,OxideGraphite,Graphite}Battery`, `SiliconOxideElectrode`,
  `SiliconOxideGraphiteElectrode`) are still deprecated — battinfo maps none of them.
