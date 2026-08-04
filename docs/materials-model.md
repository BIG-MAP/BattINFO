# Materials: kind, spec, instance

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

Each kind carries a canonical `key` (the ergonomic handle), a `label`, a `family`
(`active_anode`, `active_cathode`, `binder`, `conductive_additive`,
`electrolyte_solvent`, `electrolyte_salt`, `separator_material`,
`current_collector_material`, `other`), an optional `formula`, tolerant-import
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

One placement is worth flagging: NMP is a **processing** solvent (slurry casting),
not an electrolyte solvent, and the family list has no `processing_solvent` value, so
it sits under `other` with a `family_note` saying why. Add the family when a second
processing solvent arrives rather than stretching `electrolyte_solvent` to cover it.

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

> The full composition-linkage ladder (rewiring the cell-spec electrode/electrolyte
> models onto material references end-to-end) lands in a follow-up PR; the bridge in
> [`battinfo.materials`](material-spec.md#bridge-embedded--standalone) already lifts
> embedded materials to standalone specs for dedup today.

See the [material-spec / material field reference](material-spec.md) for the exact
fields each record carries.
