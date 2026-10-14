# BattINFO Quickstart

BattINFO turns battery metadata into machine-readable Linked Data. In five minutes you will create a semantically typed battery cell record, validate it, and see the EMMO-aligned JSON-LD that BattINFO produces automatically.

## Which surface do I use?

| You want to… | Use | Entry point |
|---|---|---|
| Describe cells/tests/datasets interactively and publish them (the common case) | **Authoring workspace** | `ws = battinfo.workspace(".")` then `ws.quickstart()` |
| Create a single cell-spec record in code and save or publish it | **Models + functions** | `CellSpec(...)` + `battinfo.publish(...)` (this page) |
| Register materials, electrodes, and other components | **`battinfo.api` functions** | `create_material_spec(...)` + `save_material_spec(...)` — see the [how-to guides](docs/pages/howto.md) |

If in doubt, start with `battinfo.workspace(".")` for cells, tests, datasets,
and equipment. The workspace does **not** cover materials or component specs —
those are authored through `battinfo.api`. The full per-record-type coverage
map is in [Workspace authoring](docs/workspace-authoring.md#what-each-surface-can-author-today);
the guided tour is on the same page.

---

## Prerequisites

- Python 3.11–3.14
- A terminal

Install BattINFO from GitHub into a virtual environment. 0.8.0 will be its first working release on PyPI.

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install "battinfo @ git+https://github.com/BIG-MAP/BattINFO.git"
```

> Converting raw cycler files (`ws.convert()`) needs the BDF converter, distributed as `batterydf`. The `processing` extra brings it, along with the plotting libraries:
>
> ```bash
> pip install "battinfo[processing] @ git+https://github.com/BIG-MAP/BattINFO.git"
> ```
>
> The extra requires `batterydf[nda,excel,mat]>=0.2.0rc2,<0.3`, so pip installs the batterydf 0.2.0 release candidate until 0.2.0 itself is published.

---

## 1. Create your first cell-spec record

A **cell spec** is a product specification — the datasheet-level description of a battery model. Create one in three lines:

```python
from battinfo import CellSpec, publish

cell_spec = CellSpec(
    manufacturer="Panasonic",
    model="NCR18650B",
    format="cylindrical",
    chemistry="li-ion",
    size_code="R18650",
    nominal_capacity={"value": 3.4, "unit": "Ah"},
    nominal_voltage={"value": 3.6, "unit": "V"},
    mass={"value": 48.0, "unit": "g"},
)

result = publish(cell_spec, destination="local", root=".battinfo/quickstart")
print(result.canonical_iri)
# https://w3id.org/battinfo/spec/jv2y-hq4t-cjrv-1w16
```

BattINFO mints a stable, opaque IRI for the record and writes it to disk. The IRI comes from the manufacturer, model, format, chemistry and size code, so you get the same one as above.

That IRI is **permanent, but not yet resolvable on the web** — opening
`https://w3id.org/battinfo/spec/...` in a browser returns 404 for a record
published locally. A local publish mints the identity; it becomes
dereferenceable once you publish the record to the registry (Tutorial 6 below).

The `root=".battinfo/quickstart"` above is a dot-directory, so a plain `ls`
hides it — use `ls -a`. The record you just created lives here:

```text
.battinfo/quickstart/
├── index.json
└── examples/cell-spec/cell-spec-jv2y-hq4t-cjrv-1w16.json   # the canonical record (read in step 2)
```

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
# ['BatteryCellSpecification', 'schema:ProductModel', 'schema:CreativeWork']

print(jsonld["schema:name"])     # Panasonic NCR18650B
print(jsonld["schema:size"])     # R18650

cell = jsonld["isDescriptionFor"]
print(cell["@type"])
# ['BatteryCell', 'CylindricalBattery', 'LithiumIonBattery']
print([prop["@type"][0] for prop in cell["hasProperty"]])
# ['NominalCapacity', 'NominalVoltage', 'Mass']
```

A cell spec is an *information entity*, a datasheet as data, not the physical cell it describes. So its `@type` is `BatteryCellSpecification` (an EMMO information object) stacked with `schema:ProductModel` and `schema:CreativeWork`. Its `isDescriptionFor` link points at a node for the cell the spec describes, and that node carries the EMMO types of the physical cell (`BatteryCell`, `CylindricalBattery`, `LithiumIonBattery`) and one `hasProperty` node per quantity: the class (`NominalCapacity`), its `hasNumericalPart` with the number in `hasNumberValue`, and the unit IRI in `hasMeasurementUnit`. See [Tutorial 4](docs/guides/04-semantic-layer.ipynb) for how the spec, the cell and their EMMO types relate.

`publish_record` builds this JSON-LD with the same spec node that a Zenodo deposit carries, and `battinfo.record_to_jsonld` builds that node in memory. It is not yet what the registry serves at the spec's IRI: that is the record body expanded with the records context, as the [known limitations](docs/scope.md#known-limitations-in-080) explain. When you publish cells, tests and datasets with the workspace, the publication package links them to this spec (see [Tutorial 3](docs/guides/03-linked-records.ipynb)).

---

## 4. Validate a record

Validate the record you just created. Run this in the folder you ran step 1 in, with the virtual environment active, in any shell; `--source-root` tells the validator where linked records live:

<!-- The doc-snippet runner runs shell blocks from the repository root, where this
     record does not exist. tests/test_first_contact_files.py runs step 1 and then
     this command, as written, in an empty folder. -->
<!-- doc-snippet: skip -->
```bash
battinfo validate .battinfo/quickstart/examples/cell-spec/cell-spec-jv2y-hq4t-cjrv-1w16.json --source-root .battinfo/quickstart/examples --format json
```

On a core install the output is:

```json
{
  "ok": true,
  "mode": "record",
  "policy": "default",
  "profile": null,
  "source_root": ".battinfo/quickstart/examples",
  "issue_count": 1,
  "error_count": 0,
  "warning_count": 1,
  "errors": [],
  "issues": [
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

The record is valid (`ok: true`, `error_count: 0`). The one warning says that the optional SHACL check was skipped because `pyshacl` is not installed. With `pyshacl` installed (`pip install pyshacl`, or the `dev` extra) the check runs, and `issue_count` and `warning_count` are 0. On Windows, `source_root` shows the path with backslashes.

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
