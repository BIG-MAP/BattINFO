# BattINFO Quickstart

BattINFO turns battery metadata into machine-readable Linked Data. In five minutes you will create a semantically typed battery cell record, validate it, and see the EMMO-aligned JSON-LD that BattINFO produces automatically.

## Which surface do I use?

| You want to… | Use | Entry point |
|---|---|---|
| Describe cells/tests/datasets interactively and publish them (the common case) | **Authoring workspace** | `ws = battinfo.workspace(".")` then `ws.quickstart()` |
| Create a single record in code and save/publish it | **Models + functions** | `CellSpec(...)` + `battinfo.publish(...)` (this page) |
| Build or script the full object graph programmatically (ingest pipelines, batch tooling) | **Object-graph engine** | `battinfo.Workspace` — the lower-level engine the authoring workspace wraps |

If in doubt, start with `battinfo.workspace(".")` — it wraps everything else. See
[Workspace authoring](docs/workspace-authoring.md) for the guided tour.

---

## Prerequisites

- Python 3.11+
- A terminal

```bash
pip install battinfo
```

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
# ["BatteryCell", "CylindricalBattery", "LithiumIonBattery", "schema:ProductModel"]

print(jsonld["schema:name"])     # Panasonic NCR18650B
print(jsonld["schema:size"])     # R18650
```

BattINFO automatically stacks EMMO types based on the cell's format and chemistry. A cylindrical Li-ion cell is simultaneously `BatteryCell`, `CylindricalBattery`, and `LithiumIonBattery` — no manual annotation needed.

The resolver JSON-LD is the lightweight document served at the cell's IRI. The full EMMO-aligned publication package — with `hasProperty` nodes for each quantitative specification — is produced by `workspace.build_publication_package()` (see [Guide 3](docs/guides/03-linked-records.ipynb)).

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
  "error_count": 0,
  "warning_count": 0
}
```

---

## You're done

In four steps you have:
- Created a battery cell-spec record with a permanent IRI
- Produced valid, EMMO-aligned JSON-LD
- Seen automatic semantic type stacking

---

## Next steps

The guide notebooks in `docs/guides/` continue the walkthrough interactively. Open them from the repo root with the `.venv` kernel selected.

| Notebook | What you'll learn |
|---|---|
| [01 — Concepts](docs/guides/01-concepts.ipynb) | The data model, record types, and how IRIs work |
| [02 — First cell spec](docs/guides/02-first-cell-type.ipynb) | Full cell-spec authoring: specs, provenance, CLI and Python paths |
| [03 — Linked records](docs/guides/03-linked-records.ipynb) | Cell instance → test → dataset provenance chain |
| [04 — Semantic layer](docs/guides/04-semantic-layer.ipynb) | JSON-LD, EMMO alignment, validation, and RDF queries |
| [05 — Descriptors](docs/guides/05-descriptors.ipynb) | Deep cell descriptors: electrodes, electrolyte, separator |
| [06 — Publish your data](docs/guides/06-publish-your-data.ipynb) | End to end: raw cycler CSV → validated records → DOI + registry |
