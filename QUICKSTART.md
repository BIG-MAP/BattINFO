# BattINFO Quickstart

BattINFO turns battery metadata into machine-readable Linked Data. In five minutes you will create a semantically typed battery cell record, validate it, and see the EMMO-aligned JSON-LD that BattINFO produces automatically.

## Which surface do I use?

| You want to… | Use | Entry point |
|---|---|---|
| Describe cells/tests/datasets interactively and publish them (the common case) | **Authoring workspace** | `ws = battinfo.workspace(".")` then `ws.quickstart()` |
| Create a single record in code and save/publish it | **Models + functions** | `CellSpec(...)` + `battinfo.publish(...)` (this page) |
| Register materials, electrodes, and other components | **`battinfo.api` functions** | `create_material_spec(...)` + `save_material_spec(...)` — see the [how-to guides](docs/pages/howto.md) |

If in doubt, start with `battinfo.workspace(".")` for cells, tests, datasets,
and equipment. The workspace does **not** cover materials or component specs —
those are authored through `battinfo.api`. The full per-record-type coverage
map is in [Workspace authoring](docs/workspace-authoring.md#what-each-surface-can-author-today);
the guided tour is on the same page.

---

## Prerequisites

- Python 3.11+
- A terminal

BattINFO is not on PyPI until the 0.8 release. Until then, install from source
into a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install "git+https://github.com/BIG-MAP/BattINFO.git"
```

<!-- 0.8 release: replace the block above with  pip install battinfo -->

> Converting raw cycler files (`ws.convert()`) needs the BDF converter,
> distributed as `batterydf`. It is not yet on PyPI, so the `battinfo[processing]`
> extra cannot resolve; install the converter and plotting libraries directly:
>
> ```bash
> pip install "git+https://github.com/battery-data-alliance/battery-data-format.git" matplotlib plotly
> ```

---

## 1. Create your first cell-spec record

A **cell spec** is a product specification — the datasheet-level description of a battery model. Create one in three lines:

```python
from battinfo import CellSpec, publish

cell_spec = CellSpec(
    manufacturer="Panasonic",
    model="NCR18650B",
    format="cylindrical",
    chemistry="Li-ion",
    size_code="R18650",
    nominal_capacity={"value": 3.4, "unit": "Ah"},
    nominal_voltage={"value": 3.6, "unit": "V"},
    mass={"value": 48.0, "unit": "g"},
)

result = publish(cell_spec, destination="local", root=".battinfo/quickstart")
print(result.canonical_iri)
# https://w3id.org/battinfo/spec/xxxx-xxxx-xxxx-xxxx
```

BattINFO mints a stable, opaque IRI for the record and writes it to disk.

---

## 2. See what was produced

```python
import json
from pathlib import Path

record = json.loads(
    Path(result.debug_paths["canonical_record_path"]).read_text()
)
print(json.dumps(record, indent=2))
```

The canonical record is plain JSON — human-readable and schema-valid.

---

## 3. See the JSON-LD (semantic layer)

```python
from battinfo.api import publish_record

output = publish_record(
    result.debug_paths["canonical_record_path"],
    target_root=".battinfo/quickstart-jsonld",
)

jsonld = json.loads(
    Path(output["output_dir"], "index.jsonld").read_text()
)
print(jsonld["@type"])
# ['BatteryCellSpecification', 'schema:CreativeWork']

print(jsonld["schema:name"])     # Panasonic NCR18650B
print(jsonld["schema:size"])     # R18650
```

A cell spec is an *information entity* — a datasheet as data — not the physical
cell it describes. So its `@type` is `BatteryCellSpecification` (an EMMO
information object) stacked with `schema:CreativeWork`, and an `isDescriptionFor`
link points from the spec to the cell type it specifies. The EMMO type stacking
that describes the physical cell itself — `BatteryCell`, `CylindricalBattery`,
`LithiumIonBattery`, and friends — lives on the cell node inside the full
publication package, not on this resolver document. See
[Tutorial 4](docs/guides/04-semantic-layer.ipynb) for how the spec, the cell type,
and their EMMO types relate.

The resolver JSON-LD is the lightweight document served at the cell spec's IRI.
The full EMMO-aligned publication package — with `hasProperty` nodes for each
quantitative specification — is produced when you publish (see
[Tutorial 3](docs/guides/03-linked-records.ipynb)).

---

## 4. Validate a record

Canonical cell-spec records are validated with `--source-root`:

```powershell
.venv\Scripts\battinfo validate examples/cell-spec/A123__ANR26650M1-B.json `
    --source-root examples --format json
```

```json
{
  "ok": true,
  "mode": "record",
  "policy": "default",
  "profile": null,
  "source_root": "examples",
  "issue_count": 2,
  "error_count": 0,
  "warning_count": 2,
  "errors": [],
  "issues": [
    {
      "code": "semantic.value_text_only",
      "severity": "warning",
      "path": "properties.cycle_life",
      "message": "'cycle_life' carries only value_text - the JSON-LD export emits numeric quantities, so this property will be OMITTED there.",
      "hint": null,
      "validator": "semantic",
      "resource_type": "cell-spec",
      "profile": null
    },
    {
      "code": "shacl.unavailable",
      "severity": "warning",
      "path": "",
      "message": "pyshacl is not installed; SHACL validation skipped. Install with: pip install pyshacl",
      "hint": null,
      "validator": "shacl",
      "resource_type": null,
      "profile": null
    }
  ]
}
```

The record is valid (`error_count: 0`). The two warnings are expected on a core
install: one flags that `cycle_life` carries only free text so it is omitted from
the numeric JSON-LD export, and the other notes that optional SHACL validation is
skipped because `pyshacl` is not installed (it ships with `battinfo[dev]`).

---

## You're done

In four steps you have:
- Created a battery cell-spec record with a permanent IRI
- Produced valid, EMMO-aligned JSON-LD
- Seen automatic semantic type stacking

---

## Next steps

The tutorial notebooks in `docs/guides/` continue the walkthrough interactively. Each notebook runs from its own folder and writes only to a throwaway `_scratch/` directory next to it.

| Notebook | What you'll learn |
|---|---|
| [1 — Concepts](docs/guides/01-concepts.ipynb) | The record model, IRIs, and the semantic layer |
| [2 — Describing a cell](docs/guides/02-first-cell-type.ipynb) | Author and publish a cell spec, with a taste of material-level depth |
| [3 — Linked records](docs/guides/03-linked-records.ipynb) | Cells, test specs, tests, and datasets with the workspace |
| [4 — Semantic layer](docs/guides/04-semantic-layer.ipynb) | JSON-LD anatomy, EMMO type stacking, RDF and SPARQL |
| [5 — Cell descriptors](docs/guides/05-descriptors.ipynb) | Research-grade composition: materials, BOMs, electrodes, electrolyte |
| [6 — Publish your first dataset](docs/guides/06-publish-your-data.ipynb) | End to end: raw cycler CSV → validated records → DOI + registry |
