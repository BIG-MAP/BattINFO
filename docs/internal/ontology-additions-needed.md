# Ontology additions needed (domain-battery)

Working queue of EMMO terms the BattINFO model references but that are **not yet
published** upstream. Each is wired in code with a graceful fallback (allowlisted as a
local term, emitted as a bare `@type`, or stubbed via a pending-flag), so nothing is
blocked — but publishing them makes the JSON-LD fully ontology-resolvable. After
publishing, flip the noted code stubs.

Policy (2026-07-07): battinfo never mints domain semantics. Missing terms are added to
EMMO domain-battery / domain-electrochemistry / domain-chemical-substance upstream (we
control them), not here.

Currently pinned: domain-battery 0.21.0, domain-electrochemistry 0.39.0,
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

## 2. Property classes — currently typed by value basis only (optional)

These engineering quantities have no clean EMMO term. Their quantity nodes carry only the value-basis class (for example `ConventionalProperty`) with the key as `skos:prefLabel`: kept in the graph, but not typed as a specific quantity. Before 2026-10-11 they were given generated `battinfo:` class names. Publish if you want them first-class:

| Candidate term | Property key | Quantity |
|---|---|---|
| **`FillingRatio`** | `filling_ratio` | case electrolyte/jelly-roll fill ratio (dimensionless) |
| **`ElectrolyteDoseCoefficient`** | `dose_coefficient` | electrolyte dosing (g/Ah) |
| **`WeldWidth`** | `weld_width` | tab/terminal weld width |
| **`TapeWidth`** | `tape_width` | tab insulating-tape width |

To wire after publishing: add a curated entry to
`assets/mappings/domain-battery/property_map.curated.json` (and the `src/battinfo/data`
mirror) with the new `class_iri` — the descriptor then emits the real `@type` instead of
the value-basis class alone.

## 3. Optional — loading-side qualifier

`single_side_loading` / `double_side_loading` both currently type as `MassLoading`
(distinct keys, distinction kept in key/label). If you want to type-distinguish them, add
**`SingleSide`** / **`DoubleSide`** property-nature qualifiers (parallel to
`RatedProperty`) and dual-type `[MassLoading, DoubleSide]`. Not required.

## 4. Continuous-current rated properties (red-team W3.3, 2026-07-07)

Resolved without a new class (owner ruling 2026-10-13). `nominal_continuous_charging_current` and `nominal_continuous_discharging_current` are curated as `ChargingCurrent` (`electrochemistry_79551e01_…`) and `DischargingCurrent` (`electrochemistry_e4d666ee_…`), the published classes of a current applied during charging or discharging. A standard continuous current is not a maximum, so neither key shares the `MaximumContinuous*Current` classes of the maximum keys, and the v1 records context was corrected to match before 0.8.0. A `NominalContinuousChargingCurrent` class is not needed unless upstream wants to tell a datasheet's standard current from any charging current.

The other SpecSet keys that once waited here are mapped, except `cycle_life_c_rate` and `round_trip_energy_efficiency_50pct` (see `tests/test_validation_plausibility.py` `KNOWN_UNMAPPED`, which may only shrink).

## 5. Statistical dispersion of a sample (gap E7, 2026-08-17)

A quantity may now state the spread of the sample it summarises — `standard_deviation` and `sample_count` alongside `value` and `unit` — because a batch average without its spread is the number labs actually have and could not publish. There is no EMMO class for either.

| Candidate term | Kind | Placement | Purpose |
|---|---|---|---|
| **`StandardDeviation`** | Class | property-nature qualifier or a `Quantity` subclass | The sample standard deviation of a set of measured values, in the unit of the value it qualifies. |
| **`SampleCount`** | Class | dimensionless quantity | How many members the summary was computed over. `CountingUnit` exists for the unit; the quantity does not. |
| **`hasSampleStatistic`** | Object property | on a `Property` | Attach the above to the property they qualify, the way `hasMeasurementParameter` attaches a condition. |

Searched and absent from the 0.20.2 / 0.37.2 / 1.0.2 closure, and again from the 0.21.0 / 0.39.0 / 1.0.2 one (2026-10-12): `StandardDeviation`, `StandardUncertainty`, `Variance`, `ArithmeticMean`, `Median`, `SampleCount`, `SampleSize`, `StatisticalQuantity`, `hasStandardDeviation`. The `Mean*` classes present (`MeanFreePath`, `MeanPoreSize`, …) are physics quantities, not statistics.

`MetrologicalUncertainty` (`EMMO_847724b7_…`) and `hasMetrologicalUncertainty` (`EMMO_662c64e7_…`) **are** in the closure and were deliberately not used. Per VIM, measurement uncertainty characterises the dispersion of values attributable to one measurand; a sample standard deviation over eight electrode discs characterises a population of distinct physical objects. Reusing the class would be a category claim of the same kind as the `CapacityFade` mapping fixed in 0.37.1, so the emitter says what it has instead: `schema:valueReference` → a named `schema:PropertyValue`.

To wire after publishing: `_SAMPLE_STATISTIC_TERMS` and `_apply_sample_statistics` in `transform/json_to_jsonld.py` are the only emission site (both quantity-node builders route through it); add the class to `validate/jsonld.py` `_EXPLICIT_ALLOWED_TYPE_TERMS`, and append the terms to `records.context.v1.json` via `scripts/gen_context.py`. Records already published with the `schema:` qualifier keep expanding as they do, so the flip is additive rather than a v2.

## 6. ns#-retirement placeholders (2026-08-21)

Retiring the served `ns#` catch-all namespace put every canonical record-body key into the records context. The keys below had no EMMO term anywhere in the closure and now expand to `battinfo:` slash placeholders; each is an upstream ask, and the placeholder is retired (context term repointed at the next context version) once the class lands.

| Placeholder | Wanted upstream | Notes |
|---|---|---|
| `battinfo:ambientTemperature` | test-condition quantity, domain-electrochemistry or domain-battery | The transform deliberately types generic conditions as `ConventionalProperty`; a dedicated `AmbientTemperature` quantity would let both the emitter and the flat record layer ground it. The 2026-09-20 parameter sweep considered typing it `ThermodynamicTemperature` via the property map but reverted: the published flat context already expands the key to this placeholder, and the context is append-only — the repoint waits for the class or the next context version, per this section's policy. |
| `battinfo:voltageReference` | ~~relation~~ resolved in emission (2026-09-07) | The JSON-LD side no longer needs an upstream ask: the `voltage_reference` conditions key is intercepted and emitted as EMMO's own `hasMetrologicalReference` with class-typed reference-electrode nodes (see section 7). The placeholder remains only for the flat record key. |
| `battinfo:stepMode` / `battinfo:stepDirection` | control-mode / direction quantities or a sanctioned literal pattern | Process classes (`ConstantCurrentCharging`, …) exist for typed emission; the flat step layer states mode/direction as literals and needs a predicate. |
| `battinfo:lotId` | batch/lot identifier property, domain-battery | Sibling of `battinfo:batchId` (already a placeholder via `ci_batch_id`). |
| `battinfo:chemistryFamily` / `battinfo:materialClass` | material classification relations, domain-battery or chemical-substance | Coarse family ("nmc") and class ("powder") of a material spec. |
| `battinfo:MaterialSpec` / `battinfo:Material` / `battinfo:ElectrodeSpec` / `battinfo:TestSpec` | specification/instance classes parallel to `BatteryCellSpecification` | `MaterialSpecification`, `ElectrodeSpecification` and a test-specification class would ground the served record `@type`s that currently have no EMMO home. |
| `battinfo:EquipmentSpec` / `battinfo:Equipment` / `battinfo:Channel` / `battinfo:ParameterSet` | equipment/channel/parameter-set classes, domain-battery | `hasTestEquipment` exists; the equipment classes themselves (and a measurement-channel class) do not. Parameter sets may re-home to a modelling vocabulary instead. |

Not upstream asks (administrative, stays a placeholder or re-homes to a standard vocabulary if one appears): `battinfo:fundingProgramme`.

## 7. Measurement-provenance cycle (2026-09-07)

Found while moving quantity conditions onto their `isOutputOf` measurement node and
building the voltage-reference couples table (`transform/json_to_jsonld.py`).

| Term | Kind | Placement | Purpose |
|---|---|---|---|
| **`SodiumElectrode`** | Class | domain-electrochemistry, sibling of `LithiumElectrode`/`ZincElectrode` | A plain sodium-metal electrode. The closure has only `SodiumBasedElectrode` (any electrode containing sodium), which the couples table maps `Na/Na+` to meanwhile — too broad for a reference-electrode couple. Repoint `_VOLTAGE_REFERENCE_COUPLES["na/na+"]` when it lands. |
| **`MeasurementParameter`** (or similar) | Class | chameo or domain-electrochemistry | A generic class for qualitative measurement parameters (`atmosphere: argon`). Such conditions currently type via the dynamic `battinfo:` fallback + `ConventionalProperty` and carry `hasStringValue`. |
| **`PotentiostaticIntermittentTitrationTechnique`** | Class | chameo or domain-electrochemistry, sibling of `GalvanostaticIntermittentTitrationTechnique` | PITT — the potentiostatic twin of GITT (the closure has GITT but not PITT). Until published, `pitt` protocols emit an untyped plan node; add to `TEST_METHOD_CLASS` when it lands. |
| measurement → procedure relation | Object property | chameo | Ties a measurement process to the procedure it followed. Until it exists, the emitter links protocols with `dcterms:conformsTo` (the in-house test→protocol predicate) — the one non-EMMO seam in the measurement subtree. |

## 8. Coating sidedness (electrode review, 2026-09-08)

| Term | Kind | Placement | Purpose |
|---|---|---|---|
| **`DoubleSideCoated`** / **`SingleSideCoated`** (or a `hasCoatedSides` datum) | Class or datum property | domain-electrochemistry, on `ElectrodeCoating` | Whether the current collector is coated on both sides or one — a first-class design fact of every real electrode. The closure has only `OneSidedHeating` / `TwoSidedHeating` (heating processes). Until published, the record key `coating.double_sided` (boolean) emits as a named `schema:PropertyValue` on the coating node (`_descriptor_electrode_coating_to_jsonld`). |

## 9. Cell housing assembly (housing review, 2026-09-09)

The housing record describes the enclosure assembly; the closure has the parts
(`Case`, `CellLid`, `Terminal`, `Gasket`, `Spring`, …) but no class for the
assembly itself, and `hasCase`'s published axioms relate the CELL to its case.

| Term | Kind | Placement | Purpose |
|---|---|---|---|
| **`CellHousing`** | Class | domain-electrochemistry, sibling of `Case` under `ElectrochemicalComponent` | The assembly of components that enclose and mechanically support a cell: case, lid, terminals, seals, and internal hardware (a purchasable coin-cell kit is the canonical instance). Meanwhile the housing individual types `ElectrochemicalComponent` and lists every part under `hasConstituent` (`_component_holder_node`). |
| **`hasHousing`** | Object property | domain-electrochemistry, cell → `CellHousing` | Relates a cell to its enclosure assembly. Meanwhile a cell's housing parts merge onto the cell node (`hasCase` for the case, per the published `CoinCell ⊑ hasCase some CoinCase` pattern). |
| **`hasLid`** | Object property | domain-electrochemistry | `CellLid` "closes the case" but no relation states it; lids currently ride `hasConstituent`. |

## 10. Parameter-vocabulary sweep (2026-09-20)

Audit of every `battinfo:` fallback the parameter-claims corpus emitted. Nineteen keys
turned out to have usable published classes and were wired into
`property_map.curated.json` (both copies) on 2026-09-20 — density, porosity, ocp,
particle_radius, reaction_rate_constant, specific_capacity, stoichiometry_min/max,
surface_area_per_volume, max_concentration, ionic_conductivity, electronic_conductivity,
transference_number, electrolyte_diffusivity, conductivity_activation_energy,
series_resistance, areal_mass, and (per the depth rule below)
diffusivity_activation_energy + reaction_rate_activation_energy to the generic
`ActivationEnergy` — no ontology work needed for those.
(`ambient_temperature` also has a usable class, `ThermodynamicTemperature`, but stays a
placeholder: the published flat context pins the key, see section 6.) What remains is
governed by the depth rule.

### The depth rule (RATIFIED 2026-09-20)

Where a parameter quantity's class lives is decided by composition depth, not by who
asked for it:

- **Domain ontology (domain-battery / domain-electrochemistry): base quantities plus at
  most ONE qualifying facet**, and only when the compound is measurable as such, used
  across multiple model families, and axiomatized (subclass + restriction), not just
  labeled. Polarity, species, phase, and model tier are facts of the *graph* (the
  claim's target, the BPX block, `model_context`), never baked into new class names —
  "Guest" is the right abstraction because species is a fact about the target material,
  not about the quantity.
- **Application ontologies (BPX; eventually BattMo) own pre-coordinated parameter
  classes** — the 1-1 mapping targets a standard's parameter list needs — each defined
  by a bridge axiom over domain terms so reasoners can still aggregate under domain
  concepts (see 10c).
- **The existing deep compounds in domain-battery
  (`GuestDiffusivityIn{Negative,Positive}ElectrodeActiveMaterial`,
  `ActivationEnergyOf…`, `{Negative,Postive}ElectrodeActivationEnergyOfReaction`,
  `…EntropicChangeCoefficient` pairs, BattMo lineage) are FROZEN: don't grow the
  pattern, don't delete yet (published IRIs).** Reparent them under the 10a generics
  with proper axioms when those land; they are the migration seed for a BattMo
  application ontology, not a pattern to extend. Fix the `Postive` typo alongside (see
  defects).

Two consequences applied immediately (2026-09-20): `diffusivity_activation_energy` and
`reaction_rate_activation_energy` are wired to the published generic `ActivationEnergy`
— the of-what rides the key, label, and claim structure, per the geometry→`Area`
precedent — and the former asks for `ActivationEnergyOfGuestDiffusivityInActiveMaterial`
and `ActivationEnergyOfReaction` are WITHDRAWN (two facets deep; the second only ever
had one job, 1-1 mapping, which is application-ontology work).

### 10a. One-facet generics (domain-battery / domain-electrochemistry)

Parameter claims are polarity-agnostic by design: a claim targets the material kind
(graphite as such) and the BPX block supplies polarity downstream. Two asks survived the
depth rule; add each as the axiomatized parent of its existing polarity pair and repoint
the curated map at it. The second turned out to be published already (see its row).

| Wanted term | Existing polarity pair | Parameter key |
|---|---|---|
| ~~`GuestDiffusivity`~~ | `GuestDiffusivityIn{Negative,Positive}ElectrodeActiveMaterial` | `solid_diffusivity`. Published in domain-electrochemistry 0.39.0 as the defined class `Diffusivity and isPropertyFor some ActiveMaterial`, with the polarity pair deprecated in its favour, and wired since 2026-10-12 (it was the generic `Diffusivity` from 2026-10-11). |
| ~~`EntropicChangeCoefficient`~~ | `{Negative,Positive}ElectrodeEntropicChangeCoefficient` | `entropic_coefficient` — dU/dT. Published in domain-electrochemistry 0.39.0 as `TemperatureCoefficientOfTheOpenCircuitPotential` (altLabel `EntropicChangeCoefficient`), the electrode-level quantity that replaces the deprecated pair, and wired since 2026-10-12. From 2026-10-11 the key pointed at `TemperatureCoefficientOfTheOpenCircuitVoltage`, the cell-level quantity, and the curated entry paired that label with the `CoatingThickness` IRI. |

### 10b. Battery-general quantities missing entirely (domain-battery)

| Wanted term | Parameter key | Notes |
|---|---|---|
| **`FirstCycleCoulombicEfficiency`** | `first_cycle_efficiency` | `CoulombicEfficiency` exists; the first-cycle (formation) form — the number every anode paper reports — does not. Check before asking: `FirstCycleCoulombicEfficiency` is an altLabel of `InitialCoulombicEfficiency` (`electrochemistry_469b9516_…`, already mapped for `initial_coulombic_efficiency`), in 0.37.2 as in 0.39.0, so the key may only need curating. |
| **`TheoreticalSpecificCapacity`** | `theoretical_specific_capacity` | `TheoreticalCapacity` exists but is a capacity, not a specific capacity; the gravimetric form anchors every BotE estimate. |

### 10c. BPX application ontology (meaning fixed by the BPX standard, not physics)

| Wanted term | Parameter key | Notes |
|---|---|---|
| ~~`TransportEfficiency`~~ | `transport_efficiency` | Published in domain-electrochemistry 0.39.0 (altLabel `InverseMacMullinNumber`): the ratio of an effective transport coefficient in a porous medium to its bulk value, with the Bruggeman form (porosity to the Bruggeman coefficient) in a comment and `BruggemanCoefficient` kept as the exponent. It landed in the domain ontology, defined without reference to BPX, rather than in the BPX application ontology this row proposed. Wired since 2026-10-12. |
| *(optional)* **`InitialConcentration`** | `initial_concentration` | An initial condition of the simulation (BPX ≥ 1.0 State family: initial temperature, initial SOC, initial concentrations), not a property of any material. Model-state quantities belong with the model standard. Interim since 2026-10-11: wired to the published `InitialChargeCarrierConcentrationInElectrolyte`, since the key is always the electrolyte's salt concentration (the parameter vocabulary scopes it to electrolyte and state). |
| **`OCPHysteresisDecayConstant`** | `ocp_hysteresis_decay_constant` | BPX 1.x's 'OCP hysteresis decay constant': the dimensionless rate at which the hysteresis state of a single-state OCP hysteresis model moves between the delithiation and lithiation branches. A parameter of that model as BPX defines it, so the BPX application ontology is its home. Until it exists, the key is typed by its value basis only. |
| *(optional)* BPX-normalized `ReactionRateConstant` subclass | `reaction_rate_constant` | BPX's rate constant carries mol·m⁻²·s⁻¹ — a normalization convention of the standard. The generic `ReactionRateConstant` elucidation is dimensionally uncommitted, so the interim curated mapping to it (wired 2026-09-20) is defensible; a BPX-scoped subclass would make the convention explicit. |

**Bridge-axiom pattern (ratified with the depth rule).** Every BPX-app-ontology
parameter class is defined over domain terms, never free-floating — e.g.
`bpx:DiffusivityActivationEnergy ⊑ ActivationEnergy ⊓ isAbout some GuestDiffusivity`,
`bpx:TransportEfficiency ⊑ Ratio` with the ε^p definition in the elucidation and
`BruggemanCoefficient` referenced as the exponent. That gives each simulator its 1-1
mapping targets, keeps reasoner-level aggregation under domain concepts, and pins each
convention to the standard whose version it belongs to. Net layering: a claim types as
what the quantity *is* (domain class), the record says what it's *of* and under which
model, and the application ontology says which slot of the standard it fills.

To wire after any of these publish: curated entry in
`assets/mappings/domain-battery/property_map.curated.json` + the `src/battinfo/data`
mirror, then `scripts/gen_context.py` and `scripts/gen_reference_records.py`; the
value-basis-only typing retires automatically.

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

The versioned records context (`records.context.v1.json`) was frozen before this pass and
kept the old terms until it was corrected in place before 0.8.0 (`PRE_RELEASE_CORRECTIONS`
in `scripts/gen_context.py`); `tests/test_context_v1_agreement.py` now fails if v1 and the
curated map drift apart again.

`CapacityLoss` and `ChargeRecovery` also landed but have no save-gate key, so they are
allowlisted only. Wiring them is a future save-gate addition (`capacity_loss`,
`capacity_retention`, `charge_recovery`), not part of this pass.

Still unmapped, with no upstream class: `cycle_life_c_rate` and `round_trip_energy_efficiency_50pct` (measurement qualifiers upstream does not name). The two `nominal_continuous_*_current` keys from section 4 were curated as `ChargingCurrent` and `DischargingCurrent` on 2026-10-13.

### domain-electrochemistry 0.38.0 / 0.39.0 (domain-battery 0.21.0)

Adopted 2026-10-12. Every EMMO IRI in the curated maps, the static label tables, both records contexts, the generated labels file and the JSON-LD of the packaged examples was checked against the new import closure: each exists, and none is deprecated except `LithiumNickelManganeseOxideElectrode`, which was already deprecated in 0.37.2 (see the defects list).

| Key | Was | Now |
|---|---|---|
| `ocp` | `OpenCircuitVoltage` (`electrochemistry_9c657fdc_…`) | `OpenCircuitPotential` (`electrochemistry_e272f229_…`) |
| `entropic_coefficient` | the label `TemperatureCoefficientOfTheOpenCircuitVoltage` on the `CoatingThickness` IRI (`electrochemistry_3b938708_…`) | `TemperatureCoefficientOfTheOpenCircuitPotential` (`electrochemistry_9b44a651_…`) |
| `solid_diffusivity` | `Diffusivity` (`electrochemistry_37b24a94_…`) | `GuestDiffusivity` (`electrochemistry_fed4582e_…`) |
| `electrode_pair_count` | `NumberOfEntities` (`EMMO_41efdf5d_…`) | `NumberOfElectrodePairs` (`electrochemistry_f7a81b04_…`), a subclass of the former |
| `transport_efficiency` | value basis only | `TransportEfficiency` (`electrochemistry_3605456a_…`) |

0.39.0 makes `OpenCircuitVoltage` strictly the cell-level quantity, the voltage between the terminals at zero current (IEV 482-03-32), and adds `OpenCircuitPotential` for a single electrode against a reference. The `ocp` key is a half-cell potential of an electrode material (material scope in the parameter vocabulary, BPX `OCP [V]` per electrode), so it moves. No key BattINFO emits holds a cell-level open-circuit voltage today, so nothing emits `OpenCircuitVoltage` any more; the term stays in the v1 context with its cell-level IRI. OCP curves and expressions are `schema:PropertyValue` nodes with no EMMO class, as before; the new branch classes (`AnodicBranchOpenCircuitPotential`, `CathodicBranchOpenCircuitPotential`) are not used for them.

The 28 polarity-qualified anchor quantities deprecated in 0.38.0 and the six corrected prefLabel spellings (`InitialThermodynamicTemperature`, `MinimumTemperature`, `MinimumConcentration`, `CarbonDioxideElectrode`, `LithiumNickelManganeseCobaltOxideLithiumManganeseOxideElectrode`, `PositiveElectrodeActivationEnergyOfReaction`) are used nowhere in BattINFO. `initial_temperature` stays on the generic `ThermodynamicTemperature`: the misspelling was one of the two reasons for that, the depth rule is the other, so the choice is open for the maintainer.

The SI-accepted units 0.38.0 brings into the closure (it imports EMMO's `siacceptedunits` module) are the EMMO IRIs `unit_map.curated.json` already used: `AmpereHour`, `MilliAmpereHour`, `Watthour`, `KiloWatthour`, `MegaWattHour`, `MilliLitre`, `MolePerLitre`, `WattHourPerKilogram` and `WattHourPerLitre` were referenced before but declared in no module of the 0.37.2 closure, and are declared now. No unit IRI changed.

`records.context.v1.json` gains the five new class terms. Two of its terms were wrong and were corrected in place (owner ruling 2026-10-13, `PRE_RELEASE_CORRECTIONS` in `scripts/gen_context.py`): `TemperatureCoefficientOfTheOpenCircuitVoltage` expanded to the `CoatingThickness` IRI, a mistake made when `entropic_coefficient` was wired on 2026-10-11, and now expands to `electrochemistry_3bb5ae23_…`; `degC` expanded to `EMMO_36a9bf69_…`, EMMO's class for the programming language C, and now expands to `emmo:DegreeCelsius`, the IRI EMMO 1.0.2 declares for the unit in `disciplines/units/siunits`.

Every unit IRI BattINFO writes is now checked against the measurement-unit classes of the closure. Four are not units there and are allowed by name in `tests/test_mapping_governance.py`: `MilliAmpereHour` and `emmo:Percent` (both in the defects list), and `WeightPercent` and `VolumePercent`, which `unit_map.curated.json` gives the symbols `%` and `vol%` but which domain-electrochemistry declares as `PercentQuantity` classes, quantities rather than units. Whether those two symbols should move to UnitOne with rescaling, or wait for `emmo:Percent` to enter the closure, is open.

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

Rechecked against the 0.21.0 / 0.39.0 / 0.15.0 / 1.0.2 closure on 2026-10-12: every item below is still open except the `Postive` typo, which moved to the resolved list. Three were added in that pass and the next (`LithiumNickelManganeseOxideElectrode`, `MilliAmpereHour` and `Percent`).

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
- **`LithiumNickelManganeseOxideElectrode` is deprecated with no replacement.** `electrochemistry_41ddf723_…` carries `owl:deprecated true` in 0.37.2 and 0.39.0 with no `dcterms:isReplacedBy` and no dated comment, while 0.37.2 un-deprecated its seven chemistry siblings as defined classes. battinfo emits it as the electrode node of `positive_electrode_basis: lnmo` (`entity_type_map.json`). Ask upstream to un-deprecate it like the siblings (it already has the `hasActiveMaterial some LithiumNickelManganeseOxide` restriction) or to name a replacement.
- **`MilliAmpereHour` has no named superclass.** In EMMO 1.0.2 `disciplines/units/siacceptedunits`, `emmo:MilliAmpereHour` is defined by two restrictions only, while `AmpereHour` and `MilliAmpereHourPerGram` subclass their unit classes, so without a reasoner it does not classify as a `MeasurementUnit`. battinfo writes it for `mAh`, and the unit check allows it by name. Ask EMMO to give it the parents `AmpereHour` has (`ElectricChargeUnit`, `SIAcceptedDerivedUnit`).
- **`Percent` is outside the import closure.** The records contexts map `%` to `emmo:Percent`, which EMMO 1.0.2 declares in `disciplines/units/specialunits`, a module the pinned chain does not import (domain-electrochemistry 0.38.0 added `siacceptedunits` for the hour and litre units, not this one). The curated unit map gives `%` the electrochemistry `WeightPercent` IRI for emitted quantities, so the context term (`CONTEXT_UNIT_SYMBOLS` in `jsonld.py`, frozen in v1) is the only place `emmo:Percent` appears.
- **`NominalBatteryProperty` contradicts its own parent (red-team review, 2026-09-15).**
  `battery_fb9baf9b_680e_493e_a755_da9bb1fc9fae` is elucidated "a battery property
  defined by the manufacturer and determined under some specified conditions" - a
  quantified datasheet rating - but subclasses `emmo:NominalProperty`
  (`EMMO_909415d1_…`), VIM's nominal property: one that "has no magnitude" (colour,
  blood type). The class as published means "a quantified property that cannot be
  quantified". It should be reparented (ConventionalProperty is the natural home:
  "a quantitative property attributed by agreement"). battinfo maps its `Nominal`
  value basis to `ConventionalProperty` and does not emit either class of this pair.
- **`LR6` entails zinc-carbon chemistry (red-team review, 2026-09-15).**
  `AlkalineZincManganeseDioxideBattery` is declared `rdfs:subClassOf` both
  `AlkalineCell` and `ZincCarbonBattery`; alkaline and zinc-carbon are distinct
  chemistries, so every `LR6` (AA alkaline) individual is entailed to be a
  zinc-carbon battery. The `ZincCarbonBattery` parent should be removed. battinfo
  still emits `LR6` (the designation typing is correct); the false chemistry
  entailment is upstream's to fix.
- **Five context terms resolve to IRIs outside the import closure.** The published
  domain-battery 0.20.2 context (unchanged in 0.21.0) maps `ChemicalMaterial`, `ElementalMaterial`,
  `ChemicallyDefinedMaterial`, `hasORCID` and `AngularWaveNumber` to
  `https://w3id.org/emmo#EMMO_{8a41ed1b…, a086af15…, a96e2152…, e117f976…, e4791212…}`,
  none of which is defined in EMMO 1.0.2 or in any imported module. Likely left over from
  a pre-1.0 EMMO. battinfo emits none of them, so nothing is broken here — but any
  consumer expanding those terms gets an IRI that does not dereference.

### Resolved upstream

- **`PostiveElectrodeActivationEnergyOfReaction` typo.** Corrected to `PositiveElectrodeActivationEnergyOfReaction` in domain-electrochemistry 0.38.0, with the old spelling kept as a `formerLabel`; the same release deprecated the class in favour of `ActivationEnergy`. battinfo never mapped it.
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

## Chemical-substance classes needed for the substances vocabulary (2026-08-29)

The substance-vocabulary build (`tools/substances/build_vocab.py`, joining the seed against domain-chemical-substance 0.14.2-14-g3347cc2 by PubChem CID) found 39 of 72 structure-identified substances already have chemsub classes. The 33 below do not; each is listed as symbol | PubChem title | CID | InChIKey | CAS so upstream entries can be minted mechanically. The bare ions in particular block ion-typed JSON-LD emission (electrolyte plan E6).

**Ions (10):** BETI- | Bis(pentafluoroethylsulfonyl)imide | 4067273 | SLSPYQCCSCAKIB-UHFFFAOYSA-N | 129318-46-3; BMIM+ | 1-Butyl-3-methylimidazolium | 2734162 | IQQRAVYLUAZUGX-UHFFFAOYSA-N | 80432-08-2; DFOB- | Difluoro(oxalato)borate | 58152809 | CKSNGRFEJKNBMU-UHFFFAOYSA-N | (none); EMIM+ | 1-Ethyl-3-methylimidazolium | 174076 | NJMWOUFKYKNWDW-UHFFFAOYSA-N | 65039-03-4; K+ | 813 | NPYPAHLBTDXSSS-UHFFFAOYSA-N | 24203-36-9; Li+ | 28486 | HBBGRARXTFLTSG-UHFFFAOYSA-N | 17341-24-1; Na+ | 923 | FKNQFGJONOIPTF-UHFFFAOYSA-N | 17341-25-2; OH- | 961 | XLYOFNOQVPJJNP-UHFFFAOYSA-M | 14280-30-9; PYR14+ | 1-Butyl-1-methylpyrrolidinium | 11009533 | PXELHGDYRQLRQO-UHFFFAOYSA-N | 223437-10-3; TFA- | Trifluoroacetate | 84468 | DTQVDTLACAAQTR-UHFFFAOYSA-M | 14477-72-6.

**Solvents (16):** Ac2O acetic anhydride 7918 (108-24-7); BC 2,3-butylene carbonate 10080377 (51261-82-6); DMI 1,3-dimethyl-2-imidazolidinone 6661 (80-73-9); EB ethyl butyrate 7762 (105-54-4); EP ethyl propionate 7749 (105-37-3); FAN fluoroacetonitrile 10420 (503-20-8); FEA 2-fluoroethyl acetate 10016 (462-26-0); FEMC methyl 2,2,2-trifluoroethyl carbonate 17761042 (156783-95-8); GN glutaronitrile 10994 (544-13-8); MAA methyl acetoacetate 7757 (105-45-3); MB methyl butyrate 12180 (623-42-7); MP methyl propionate 11124 (554-12-1); MPyr methyl pyruvate 11748 (600-22-6); SN succinonitrile 8062 (110-61-2); TEP triethyl phosphate 6535 (78-40-0); TMP trimethyl phosphate 10541 (512-56-1).

**Ionic liquids (3):** EMIM-TFSI 11731903 (174899-82-2); BMIM-BF4 2734178 (174501-65-6); PYR14-TFSI 11048104 (223437-11-4).

**Additives/diluents (4):** PS 1,3-propane sultone 14264 (1120-71-4); DTD ethylene sulfate 14075 (1072-53-3); TTE 2776662 (16627-68-2); BTFE 9528 (333-36-8) — the last two are LHCE diluents.

Full identifiers for every entry are in `src/battinfo/data/vocab/substances.json`; the generator re-emits this gap list on every run, so the section can be refreshed after each chemsub release.
