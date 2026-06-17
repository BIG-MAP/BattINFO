# Engineering Cell Description (prismatic / cylindrical / pouch) — proposed schema

## 1. Purpose & scope

The canonical coin-cell model ([coincell-canonical.md](coincell-canonical.md)) describes
*composition* and *nominal/measured performance*. A prismatic/cylindrical cell **design**
(e.g. the `Cell_Design_Tool` LFP 100 Ah prismatic) additionally encodes **as-designed
engineering** facts: housing/can, terminals, tabs, seals, electrode-stack / jelly-roll
geometry, electrolyte dosing, and process-level electrode parameters.

This document proposes the schema additions to support that **durable as-designed**
information. It deliberately **excludes**:

- *design-tool scratch math* (intermediate volumes, slurry mL, wet loading) — recomputed, not stored;
- *behavioural / state-dependent* data (the swelling cascade, ASI impedance decomposition) —
  these are functions of SOC/cycle and belong with **measurement series**, not spec fields
  (see §6).

## 2. Design principle — reuse the holder+property pattern

Phase 2 made the descriptor exporter emit **any** curated property on **any** holder that
exposes a `property` dict (`_descriptor_property_nodes`). So every new engineering part is
modelled as a **holder** — identity fields (`material`/`manufacturer`/`product_id`) + a
`property` dict — and its quantities ride the existing generic emitter for free. New code
is limited to: the pydantic sub-models, the JSON-LD **relations** (`hasTerminal`, …), and
`@type` selection. No new per-property transform logic.

## 3. Proposed schema

### 3.1 Housing (generalises `coin_hardware` to all formats)

New `Housing` model on `CellSpecification` (field `housing`). `coin_hardware` is retained
and **mapped into `housing` on load** for back-compat (see §7 migration).

```python
class Terminal(BaseModel):        # @type: Terminal  (EMMO ✓)
    polarity: str | None          # "positive" | "negative"
    material: str | None
    manufacturer / supplier / product_id: str | None
    property: dict                # width, thickness, weld_width, tape_width, length

class Seal(BaseModel):            # @type: Seal  (EMMO ✗ — to add)
    material: str | None
    property: dict                # single_channel_thickness, top_corner_thickness

class Case(BaseModel):           # @type: {PrismaticCase|PouchCase|CylindricalCase|CoinCase} (EMMO ✓)
    material: str | None          # @type stacks material class (e.g. Aluminium)
    manufacturer / supplier / product_id: str | None
    property: dict                # wall_thickness, weight, available_volume, filling_ratio,
                                  # outer width/height/thickness (incl. terminal)

class Cap(BaseModel):            # @type: CellLid  (EMMO ✓)
    material: str | None
    property: dict                # cap_assembly_weight

class Housing(BaseModel):
    case: Case | None
    cap: Cap | None
    terminals: list[Terminal]
    seals: list[Seal]             # pouch / prismatic
    # coin back-compat:
    spring: dict | None
    spacer: dict | None
```

JSON-LD: `hasCase` (existing), `hasTerminal`, `hasSeal`, `hasCap`/`hasComponent`. Case
`@type` is chosen from `format` (`prismatic → PrismaticCase`, etc.).

### 3.2 Tabs — on the electrode

Tabs belong to the electrode's current collector, so `Electrode` (or `CurrentCollector`)
gains an optional `tab`:

```python
class CurrentCollectorTab(BaseModel):   # @type: CurrentCollectorTab  (EMMO ✓)
    material: str | None
    property: dict   # width, thickness, length, weld_width, tape_width, center_to_edge
```

JSON-LD: `hasCurrentCollectorTab` under the electrode.

### 3.3 Construction / electrode-assembly enrichment

Extend `CellConstruction` with durable stack/winding facts:

```python
class CellConstruction(BaseModel):
    assembly_type / layering / layer_count / comment       # existing
    cathode_sheet_count: int | None                        # new
    anode_sheet_count: int | None
    separator_sheet_count: int | None
    winding_turns: float | None
    electrode_length: dict | None                          # quantity (wound electrode strip)
    jellyroll_volume: dict | None                          # quantity (optional, derived)
```

JSON-LD: emit as an `ElectrodeStack` (EMMO ✓) / `JellyRoll` (EMMO ✗ — to add) node under
`hasElectrodeAssembly`, with sheet counts and `Length`/`Volume` properties. (Today
construction emits flat `schema:PropertyValue` strings — this upgrades the geometric parts
to typed EMMO quantities.)

### 3.4 Electrode process properties (curated keys)

Add curated map entries (most EMMO terms already exist):

| key | EMMO class | status |
|---|---|---|
| `press_density` (alias of `calendered_density`) | `CalenderedDensity` | ✓ exists |
| `foil_thickness` (on current collector) | `Thickness` | ✓ exists |
| `coating_thickness_with_foil` (electrode total) | `Thickness` | ✓ exists |
| `single_side_loading` / `double_side_loading` | `MassLoading` + side qualifier | ⚠ needs a `SingleSide`/`DoubleSide` co-type or distinct terms |
| `ceramic_coating` (secondary layer) | `CeramicCoating` | ✗ to add (model as a 2nd `Coating` on the electrode) |

### 3.5 Electrolyte dosing

```python
# Electrolyte.property gains:
#   dose_coefficient   -> quantity g/Ah   (curated key; EMMO term ✗ to add or map to a generic ratio)
#   fill_volume        -> Volume          (✓ exists)
```

### 3.6 Cell-level — already supported

- Capacity tolerance (±2.275%) → use the existing `min_value`/`max_value` on the
  `nominal_capacity` quantity (no schema change).
- GED/VED → `specific_energy` / `energy_density` (✓). ACIR/DCIR → `ac_internal_resistance`
  / `dc_internal_resistance` (✓). Nominal voltage/energy (✓).

## 4. EMMO term status

- **Already in domain-battery:** `PrismaticCase`, `PouchCase`, `CylindricalCase`, `CellCan`,
  `CellLid`, `Terminal`, `CurrentCollectorTab`, `ElectrodeStack`, `CalenderedDensity`,
  `MassLoading`, `Thickness`, `Volume`, `Length`.
- **You would add (owner-controlled, like `RatedProperty`):** `Seal`, `JellyRoll`,
  `CeramicCoating`; optionally `SafetyVent`/`CurrentInterruptDevice`/`Mandrel` for cylindrical
  safety hardware; and a `SingleSide`/`DoubleSide` loading qualifier. Until added, these emit
  via the same pending-co-type/stub mechanism used for `RatedProperty`.

## 5. What this buys

A prismatic design like the LFP 100 Ah cell becomes:
`PrismaticBattery → hasCase(PrismaticCase: wall_thickness, weight, filling_ratio) +
hasTerminal[+,-] + hasSeal + hasPositiveElectrode(… hasCurrentCollectorTab) +
hasElectrodeAssembly(ElectrodeStack: cathode/anode/separator sheet counts, electrode_length) +
hasElectrolyte(dose_coefficient, fill_volume)` — all validated and queryable.

## 6. Deferred: the behavioural layer (swelling, ASI)

The swelling cascade (thickness after calendering/baking/wetting/@SOC/@cycle) and the ASI
impedance decomposition (electrode/CC/terminal/module/pack) are **state- and cycle-dependent
functions**, not static design facts. Recommendation: model them as **measurement outputs**
(a thickness-vs-SOC / thickness-vs-cycle series, an impedance breakdown table) attached to a
`Test`/`Dataset`, not as `CellSpecification` properties. Tracked as a separate initiative;
out of scope here.

## 7. Implementation plan

- **E0 — electrode-drop fix (prerequisite, also a live bug).** Make the descriptor fall back
  to a generic `Electrode` node (relation inferred from the field name) when the basis is
  unmapped, so composition is never dropped; add missing bases (`lmfp`, `lto`, `lmo`) and
  `nca`'s `node_type`. Required for any LMFP/less-common prismatic.
- **E1 — Housing model.** Add `Housing`/`Case`/`Cap`/`Terminal`/`Seal` sub-models +
  `housing` field; descriptor emission (`hasCase` by format, `hasTerminal`, `hasSeal`);
  `coin_hardware` → `housing` back-compat mapping; converter import/export updated.
- **E2 — Tabs.** Add `CurrentCollectorTab` on the electrode + `hasCurrentCollectorTab`.
- **E3 — Construction enrichment.** Add stack/winding fields + `ElectrodeStack`/`JellyRoll`
  emission under `hasElectrodeAssembly`.
- **E4 — Vocabulary.** Curated entries for `press_density`/`foil_thickness`/`dose_coefficient`/
  loading-side/`ceramic_coating`; add the missing EMMO terms (§4) and wire the stub co-types.
- **E5 — Authoring + validation.** `housing()`, `terminal()`, `tab=`, construction stack
  kwargs; then build a scraper for `Cell_Design_Tool*.xlsx` (analogous to the Discovery
  scraper) as the end-to-end proof, producing one prismatic `CellSpecification` + instances.

## 8. Open decisions

1. **Unify or add-alongside `coin_hardware`?** Recommended: introduce `housing` as the
   format-neutral home and fold `coin_hardware` into it with a back-compat shim (one home,
   one descriptor path), accepting a one-time migration of the live coin records / converter
   maps. Alternative: keep `coin_hardware` and add `housing` only for non-coin (no migration,
   but two structures).
2. **Behavioural layer (swelling/ASI) — in or out?** Recommended out (measurement-series
   concern, §6). Confirm.
3. **Loading single/double-side typing** — distinct curated keys vs a `SingleSide`/`DoubleSide`
   qualifier co-type (parallels the `RatedProperty` decision).
