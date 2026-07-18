# Workspace authoring

`battinfo.workspace(".")` is the blessed authoring surface for the lab-log
workflow — describe the cells you tested, attach tests and data, and publish,
without touching the lower layers. It covers cells, tests, datasets, and
equipment; materials and component specs are authored through `battinfo.api`
(see the [coverage table](#what-each-surface-can-author-today) below).

```python
import battinfo

ws = battinfo.workspace(".")
ws.quickstart()   # prints the copy-pasteable version of everything below
```

## The end-to-end flow

```python
import battinfo
ws = battinfo.workspace(".")

# 1. One-time: log in. Publishing goes to the Battery Genome registry
#    (battery-genome.org); during the soft launch API keys are granted by
#    the registry operators — there is no self-service key page yet.
ws.login(api_key="YOUR_KEY")        # or ws.setup() to see options

# 2. Tag this work with the project that funded it (optional, once per
#    workspace). The grant is stamped onto every record you save.
ws.project("101103997")              # e.g. an EU grant agreement number

# 3. Convert raw cycler files (NEWARE/Biologic/Excel/... auto-detected)
ws.convert()                         # -> bdf/*.bdf.csv

# 4. Find your cell in the registry (fuzzy search)
spec = ws.search("samsung inr21700 50e")[0]

# 5. Register the physical cells you tested
ws.add("cell", spec=spec, serial_numbers=["S1", "S2", "S3"])

# 6. Attach a test + data to a cell (explicit)
ws.add("test", type="cycling", cell="S1", data="bdf/S1.bdf.csv")

# 7. Publish (add zenodo=True for a citable DOI)
ws.save()
ws.publish(note="My cycling campaign, 2026")

ws.status()                          # see it live
```

Every verb is a method on the returned `AuthoringWorkspace` (also importable as
`battinfo.AuthoringWorkspace`): `login`, `project`, `convert`, `search`, `add`, `load`,
`save`, `publish`, `submit`, `status`, `zenodo`. Each has a docstring with examples —
`help(ws.add)` is the fastest reference.

## Which surface do I use?

| You want to… | Use | Entry point |
|---|---|---|
| Describe cells/tests/datasets interactively and publish them (the common case) | **Authoring workspace** | `ws = battinfo.workspace(".")` — this page |
| Create a single record in code and save/publish it | **Models + functions** | `CellSpec(...)` + `battinfo.publish(...)` — see the [Python API](pages/api-reference.rst) |
| Register materials and component specs (electrodes, electrolytes, …) | **`battinfo.api` functions** | `create_*` / `save_*` — see the [cookbook](pages/cookbook.md) |
| Build or script the full object graph programmatically (ingest pipelines, batch tooling) | **Object-graph engine** | `battinfo._workspace.Workspace` |

## What each surface can author today

Verified against the current release — where a cell says "no", that is a
roadmap item, not an omission in your usage:

| Record type | Workspace (`ws.*`) | Python (`battinfo` / `battinfo.api`) | CLI (`battinfo …`) |
|---|---|---|---|
| Cell spec | yes — `template` + `load`, `search` + reuse, `spec=` on `add("cell")` | yes — `CellSpec` + `save_cell_spec` / `publish` | yes — `template` / `save cell-spec` / `validate` |
| Cell (physical instance) | yes — `add("cell", names=[...])` | yes — `save_cell_instance` | yes — `create` / `save cell-instance` |
| Test spec (protocol) | partial — `template("test-spec")` exists but its output currently fails `ws.load()` ([troubleshooting](pages/troubleshooting.md)) | yes — `TestSpec` + `save_test_spec` (recommended) | yes — `template` / `save test-spec` |
| Test | yes — `add("test", cell=..., data=..., channel=...)` | yes — `Test` + `save_test` | yes — `save test` |
| Dataset | yes — created by `add("test", data=...)` | yes — `Dataset` + `save_dataset` | yes — `save dataset` |
| Equipment + channels | **yes — best path**: `add("equipment", ...)` ([how-to](howto/register-equipment.md)) | yes — `battinfo.api` equipment/channel functions | no |
| Material spec / lot | no | **yes — the path**: `battinfo.api` `create`/`save_material_spec` ([how-to](howto/register-materials.md)) | partial — `save record --input file.json` |
| Component specs (electrode, electrolyte, separator, current-collector, housing) | no | **yes — the path**: `battinfo.api` per-family `create`/`save` ([how-to](howto/build-a-cell-from-components.md)) | partial — `save record --input file.json` |

Two CLI caveats: `battinfo query` currently reads only the example records
packaged with BattINFO (no directory option — use the Python `query_*`
functions for your own library), and there are no CLI `template`/`query`
commands for materials or components.

## The layers underneath

- **`battinfo._workspace.Workspace`** is the object-graph engine (the top-level
  `battinfo.Workspace` alias is deprecated): it
  holds linked `CellSpec` / `Cell` / `Test` / `Dataset` objects,
  finalizes ids and provenance, and writes the canonical records. The authoring
  workspace delegates to it; script against it directly when you are building
  pipelines rather than working interactively.
- **The record models** (`CellSpec`, `Cell`, `Test`, `TestSpec`,
  `Dataset`) are both the canonical source of truth and the authoring input — every
  field carries a description (`help(battinfo.CellSpec)`), and misspelled
  arguments get a did-you-mean.
- **`battinfo.publish(...)`** takes a single model (or a linked graph of them) and
  writes/publishes the canonical records without a workspace.
