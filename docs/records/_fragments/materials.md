Materials in BattINFO follow a **three-level model** — the spec + instance pattern
every record family uses, with one universal level above it. It mirrors how cells
work (chemistry/format vocabulary above `cell-spec` above `cell`).

| Level | What it is | Form | Example |
| --- | --- | --- | --- |
| 1. **kind** | the *generic* material | curated vocabulary (not a record) | `graphite`, `nmc811`, `lfp` |
| 2. **spec** | a *manufactured/synthesized product* | `material-spec` record | Targray NMC811, grade X |
| 3. **instance** | an *actual lot/batch* | `material` record | lot `LOT-2026-04` |

## Level 1 — MaterialKind (a curated vocabulary)

Generic graphite is universal reference data: the genome's cross-dataset promise
("all graphite half-cell OCVs") requires every publisher to converge on **one**
identifier for graphite. So kinds are a **shipped, versioned, curated vocabulary**
governed by PR — like the property vocabulary — **not** a user-authored record
type. If level 1 were records, the corpus would grow fifty graphites.

Each kind carries a canonical `key` (the ergonomic handle), a `label`, its
`roles` — the use-site slots this substance is *known* to fill, as a list
because roles are system-relative (FEC is both co-solvent and additive, CMC
both binder and thickener). The list is informative, never normative: the
role a material actually plays in a given cell is stated at the use site
(coating role slots, electrolyte constituent slots, the component spec that
references it), and a use outside the listed roles is never an error. Then
an optional `formula`, tolerant-import
`aliases` ("NMC 811", "LiNi0.8Mn0.1Co0.1O2", "Si/Gr"), and — the anchor — its
`chemsub`: the material's **chemical-substance domain-ontology class IRI** (the EMMO
ecosystem's `domain-chemical-substance`). The battinfo `key` is just the handle;
`chemsub` is the semantic identity. Kinds missing from the ontology omit `chemsub`
and go on the ontology-additions backlog (a labeled `ChemicalSubstance` fallback
carries the node until the class is upstreamed). A kind may also carry curated,
citable `reference_properties` (e.g. graphite 372 mAh/g) — the generic anchors the
genome compares datasheet- and measurement-reported values against.

### External identity anchors

`chemsub` is the EMMO identity. Materials science also runs on Wikidata, PubChem,
the Materials Project, InChIKeys and CAS numbers, so a kind may additionally carry
`wikidata_qid`, `pubchem_cid`, `mp_id`, `inchikey` and `cas_rn`. The three that have
a stable dereferenceable form are emitted as `skos:exactMatch` links, which is how a
consumer joins a BattINFO material to those systems with no lookup table:

| Field | Emitted as |
| --- | --- |
| `wikidata_qid` | `http://www.wikidata.org/entity/<QID>` |
| `pubchem_cid` | `https://pubchem.ncbi.nlm.nih.gov/compound/<CID>` |
| `mp_id` | `https://next-gen.materialsproject.org/materials/<mp-id>` |
| `inchikey`, `cas_rn` | carried as literals only — neither has a canonical, freely-dereferenceable IRI |

Two rules govern the anchors. **An absent anchor means unverified, never guessed**:
a kind carries an identifier only once someone has checked it, so an empty field is
information, not an oversight. And **`mp_id` denotes a representative ordered
structure**, so solid-solution families (the NMC ratios, NCA, LMFP) legitimately
carry none — that absence is correct, not a gap to fill. No InChIKeys are populated
yet; molecular-species curation is a later pass.

```python
import battinfo
from battinfo.materials import material_kind, material_kind_keys, resolve_material_kind

battinfo.material_kinds()                 # the whole vocabulary
material_kind_keys()                      # the valid kind keys
resolve_material_kind("NMC 811")          # -> "nmc811" (aliases resolve)
material_kind("graphite")                 # the full entry (chemsub, emmo, refs)
```

The vocabulary covers 38 kinds: the common actives (graphite, hard carbon, LTO,
silicon and Si/Gr, lithium and zinc metal; LFP, LMFP, LCO, LMO, LNMO, the four NMC
ratios, NCA, MnO2), binders, conductive additives, the salts (LiPF6, LiTFSI, LiFSI,
KOH), carbonate solvents and additives, separator and current-collector materials,
plus alumina and NMP. Every one anchors to a `domain-chemical-substance` class.
Adding a kind is a PR against `src/battinfo/data/vocab/material_kinds.json`; the
tests check that each new `emmo` class resolves in the bundled context and names the
same substance as its `chemsub` anchor.

One role is load-bearing: `active_material` gates which kinds an electrode
may name and is where reference anchors such as specific capacity attach.
The rest are browse-and-discovery knowledge. An empty list is honest too:
NMP fills no composition slot at all — it is a processing solvent, which its
`roles_note` says.

## Level 2 — material-spec (first-class record)

A manufactured or lab-synthesized product, equal in standing to `cell-spec`:

- **Identity** — a deterministic, content-derived IRI minted like every other
  engine type, from normalized **(manufacturer, product, grade)**. Re-authoring
  the same product is a no-op, never a duplicate. Lab-synthesized materials use the
  lab as manufacturer and the recipe/batch-family name as product. There is no
  random-id path. **Processing is NOT part of spec identity** (see level 3).
- **Required `kind`** — every spec names its level-1 kind (aliases welcome). This
  is the query backbone; an unknown kind is rejected at save with the valid keys.
- **Manufacturer as org link** — `manufacturer.id` → an `organization` record IRI,
  name fallback tolerated.
- **Properties** — datasheet values via the standard property mechanism, each
  eligible for per-property provenance (value/unit/`co_type`/`conditions`).
- **Attribution** — `contributor` / `license` / `funding` are allowed on the
  schema and stamped by `ws.save`, exactly like every other record.

## Level 3 — material (instance record)

An actual batch/lot/portion realizing a spec:

- **`spec` link** (required), `lot`/batch number, received/opened/expiry dates,
  supplier reference, `amount`, `storage`.
- **`processing`** — the route (`aqueous` | `nmp` | `dry` | `other`), solvent, and
  free-text detail. **Processing lives here, on the build, not on the spec** —
  aqueous vs NMP is not a distinct product.
- **An OPEN property block** for as-received / as-characterized measurements —
  unmapped keys get the standard labeled-fallback + warning, *not* a closed
  vocabulary.
- **Identity** — deterministic from **(spec_id, lot)**.

## Blessed API

```python
ws = battinfo.workspace(".")
ws.license("cc-by-4.0"); ws.contributor(orcid="0000-...")

nmc = ws.add("material_spec", name="Targray NMC811", kind="nmc811",
             manufacturer="Targray", grade="grade X",
             property={"d50_particle_size": {"value": 11, "unit": "um"}})[0]

ws.add("material", spec=nmc, lot="LOT-2026-04",
       processing={"route": "nmp", "solvent": "NMP"}, storage="dry room")

ws.save()   # writes + stamps contributor/license/funding onto both records
```

No `ws._ws` is required for materials.

## Progressive-fidelity linkage into cells

Electrode composition components (and electrolyte solvents/salts, separator
materials) reference a material at whichever level you know:

- a **kind key** — minimum ("the anode is graphite"), resolves to the vocabulary
  IRI / EMMO class;
- a **material-spec IRI** — better ("Targray NMC811 grade X");
- a **material-instance IRI** — best ("this lot"), typically on the cell *build*.

Express at the level you know and upgrade without re-modeling — the adoption funnel
applied to materials. The transform renders whichever level is present as a
properly-typed linked node; the link-integrity gate validates internal IRIs; and
tolerant import maps free-text names through the alias table with warnings.

The electrode half of that ladder is built: an [electrode-spec](electrodes.md)
names its active material's `kind` and may reference the powder's `material-spec`, so
a powder, the electrodes made from it, and the cells built from those electrodes are one
chain. The bridge in
[`battinfo.materials`](#bridge-embedded-standalone) also lifts embedded
materials to standalone specs for dedup. The electrolyte/separator half is still a
follow-up.

See the [material-spec / material field reference](#records) for the exact
fields each record carries.

## Records

### `material-spec`

A reusable material specification. Top-level key `material_spec`.

| Field | Required | Notes |
| --- | --- | --- |
| `id` | ✓ | `https://w3id.org/battinfo/spec/{uid}` — content-derived from (manufacturer, product, grade); re-authoring the same product is a no-op |
| `name` | ✓ | Material grade, e.g. `"LFP"`, `"Graphite"`, `"NMC811"` |
| `kind` | ✓ (at save) | Level-1 [MaterialKind](#level-1-materialkind-a-curated-vocabulary) key from the curated vocabulary (`graphite`, `lfp`, `nmc811`, …). The genome's aggregation axis; resolves to the kind's chemical-substance class IRI. Aliases resolve on input; an unknown kind is rejected at save. See `battinfo.materials.material_kind_keys()` |
| `grade` | | Manufacturer grade / product version; part of spec identity |
| `material_class` | | `active_material`, `binder`, `conductive_additive`, `current_collector`, `separator_material`, `electrolyte_salt`, `electrolyte_solvent`, `electrolyte_additive`, `metal_electrode`, `coating`, `other` |
| `electrode_polarity` | | `positive` / `negative` / `none` (for active materials) |
| `formula` | | Idealized composition, e.g. `LiFePO4`, `C`, `Zn`, `(C2H2F2)n` |
| `chemistry_family` | | Coarse family label, e.g. `olivine`, `layered-oxide`, `spinel` |
| `manufacturer` / `supplier` | | Organization reference — a plain name string **or** an `{type: Organization, name, id}` object whose `id` links to an `organization` record |
| `product_id` | | Manufacturer / supplier grade identifier |
| `composition` | | Structured derivation: `base_material_id`, `coatings[]`, `dopants[]`, `constituents[]` (see below) |
| `property` | | Curated quantity map (snake_case keys → `{value, unit}`), e.g. `specific_capacity`, `true_density`, `particle_size_d50`. Each quantity may carry `co_type` + `conditions` (see below) |

### Properties with conditions

A quantity is rarely meaningful without the conditions it was measured under. Any
quantity (here and in cell/test records) may carry an optional `co_type`
(`Measured` / `Conventional` / `Rated` / `Nominal`) and a `conditions` map — each
condition is itself a quantity (`discharge_c_rate`, `lower_voltage_limit`,
`upper_voltage_limit`, `temperature`, `counter_electrode`, …):

```json
"specific_capacity": {
  "value": 160, "unit": "mAh/g", "co_type": "Measured",
  "conditions": {
    "discharge_c_rate":   {"value": 0.1, "unit": "C"},
    "lower_voltage_limit":{"value": 2.5, "unit": "V"},
    "upper_voltage_limit":{"value": 3.65,"unit": "V"},
    "temperature":        {"value": 25,  "unit": "degC"},
    "counter_electrode":  {"value_text": "Li metal", "unit_text": "n/a"}
  }
}
```

In JSON-LD this emits a typed EMMO property (`[SpecificCapacity, MeasuredProperty]`)
with each condition as a `hasMeasurementParameter`. Plausibility bounds and unit
compatibility are checked for known material keys during semantic validation.

### Properties that summarise a sample

A lab number is often a batch average. When it is, say so: `standard_deviation` (in the same unit as `value`) and `sample_count` sit alongside `value` and `unit` on the same quantity, so the mean and its spread stay one property instead of competing for the same EMMO class.

```json
"loading": {
  "value": 3.6472, "unit": "mg/cm2",
  "standard_deviation": 0.3017, "sample_count": 8,
  "min_value": 3.2844, "max_value": 4.0667
}
```

A zero standard deviation is published, not suppressed: it says every member of the sample carried the same number, which is a finding about how the value was obtained rather than a missing value.

In JSON-LD both ride `schema:valueReference` as named `schema:PropertyValue` qualifiers on the property node — the standard deviation carrying the quantity's unit, the count carrying none:

```json
"schema:valueReference": [
  {"@type": "schema:PropertyValue", "schema:propertyID": "standard_deviation",
   "schema:value": 0.3017, "schema:unitText": "mg/cm2"},
  {"@type": "schema:PropertyValue", "schema:propertyID": "sample_count", "schema:value": 8}
]
```

Not an EMMO class, because there is not one: the pinned closure publishes no `StandardDeviation`, `Variance` or `SampleCount`, and the additions are queued upstream. It does publish `MetrologicalUncertainty`, which is deliberately not used here — the spread of a batch of eight discs is a property of a population of distinct objects, not the uncertainty attributed to a single measurand, and typing it as uncertainty would claim something the number does not support.

### Structured composition

For derived/blended grades, `composition` references other material-specs by IRI:

```json
"composition": {
  "base_material_id": "https://w3id.org/battinfo/spec/<NMC811>",
  "coatings": [{"material_spec_id": "https://w3id.org/battinfo/spec/<Al2O3>",
                "name": "Al2O3", "property": {"thickness": {"value": 5, "unit": "nm"}}}],
  "dopants": [{"element": "Al", "fraction": {"value": 0.01, "unit": "1"}}],
  "constituents": []
}
```

All `*_material_id` references are existence-checked against material-spec records.

### `material`

A physical lot/batch realizing a spec. Top-level key `material`. Its `id`
(`https://w3id.org/battinfo/material/{uid}`) is content-derived from (spec_id, lot).
Links to its spec via `material_spec_id` (required); carries lot facts (`lot_id`,
`supplier`, `received_date`, `opened_date`, `expires_at`, `amount`, `storage`), a
`processing` block, an OPEN measured `property` block for as-received
characterisation (unmapped keys get the standard labeled-fallback + warning, not a
closed vocabulary), and a `datasets[]` array linking the lot to its characterization
data (XRD/SEM/ICP/PSD), each `{id, role}` existence-checked against `dataset` records.

Processing lives HERE, never on the spec: aqueous vs NMP is not a distinct product.

| Field | Required | Notes |
| --- | --- | --- |
| `material_spec_id` | ✓ | Level-2 spec IRI |
| `lot_id` | | Lot / batch number (accepts `lot=` in `ws.add`); part of instance identity |
| `processing` | | `{route: aqueous\|nmp\|dry\|other, solvent, detail}` |
| `amount` | | Quantity on hand/consumed, `{value, unit}` |
| `storage` | | Storage conditions, free text |
| `property` | | OPEN as-received measurement map |

Both `material-spec` and `material` carry record-level `contributor` / `license` /
`funding`, stamped by `ws.save` exactly like every other record type.

## Bridge: embedded ↔ standalone

Cell-specs still embed materials inline (`positive_electrode.coating.component`,
`electrolyte.salt`, …). To dedup a material across many cells, lift the embedded holder
to a standalone spec and reference it by IRI:

```python
from battinfo.materials import (
    extract_material_specs, link_component_to_spec, material_spec_from_component)

specs = extract_material_specs(cell_spec_record)   # one material-spec per unique material
spec  = material_spec_from_component(holder, material_class="active_material")
holder = link_component_to_spec(holder, spec["material_spec"]["id"])  # holder now carries material_spec_id
```

The embedded `material-component` holder gained an optional `material_spec_id` field for
this reference. Rewiring the full cell-spec fleet onto references is Phase 3.

## Worked example (Python API)

```python
from battinfo.api import (
    create_material, create_material_spec, query_material_specs,
    save_material, save_material_spec)

spec = create_material_spec(
    name="LFP",
    material_class="active_material",
    electrode_polarity="positive",
    formula="LiFePO4",
    chemistry_family="olivine",
    manufacturer="Canrud",
    property={"specific_capacity": {"value": 160, "unit": "mAh/g"}},
)
save_material_spec(spec, source_root="examples", mode="upsert")

lot = create_material(
    material_spec_id=spec["material_spec"]["id"],
    lot_id="CANRUD-LFP-2026-03",
    supplier="Canrud",
    property={"mass": {"value": 19.5, "unit": "mg"}},
)
save_material(lot, source_root="examples", mode="upsert")  # resolves the material_spec_id reference

# pass directory= explicitly — the default reads the packaged examples
query_material_specs(material_class="active_material", directory="examples/material-spec")
```

## Examples

Canonical examples live in [`examples/material-spec/`](https://github.com/BIG-MAP/BattINFO/tree/main/examples/material-spec) and
[`examples/material/`](https://github.com/BIG-MAP/BattINFO/tree/main/examples/material) (the single source of truth, mirrored into
the wheel by `scripts/sync_examples.py`). Coverage spans graphite, LFP, NMC811, NMC622,
LCO, LMFP, LNMO, zinc, carbon black, PVDF, and the KOH / LiPF6 / EC / EMC electrolyte
constituents. The Li-ion cathode/anode actives and electrolyte salts/solvents are
grounded in the DIGIBAT Discovery-Benchmark coin-cell corpus; LNMO, zinc, and KOH are
synthetic reference examples.

> Electrolyte *formulations* (e.g. "7M KOH in H₂O", "1M LiPF₆ EC:EMC 3:7") are modelled
> by the [`electrolyte-spec`](components.md) family, which assembles these
> material-spec constituents; coated electrodes are modelled by
> [`electrode-spec`](electrodes.md), which names its active material's kind and may
> reference the powder's material-spec.
