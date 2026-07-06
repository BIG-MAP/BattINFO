# Workspace authoring

`battinfo.workspace(".")` is the blessed authoring surface — the one entry point that
covers the common case end-to-end: describe the cells you tested, attach tests and data,
and publish, without touching the lower layers.

```python
import battinfo

ws = battinfo.workspace(".")
ws.quickstart()   # prints the copy-pasteable version of everything below
```

## The end-to-end flow

```python
import battinfo
ws = battinfo.workspace(".")

# 1. One-time: log in (get a key at the registry settings page)
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
| Create a single record in code and save/publish it | **Models + functions** | `CellSpec(...)` + `battinfo.publish(...)` — see the [Python API](python-api.md) |
| Build or script the full object graph programmatically (ingest pipelines, batch tooling) | **Object-graph engine** | `battinfo.Workspace` |

## The layers underneath

- **`battinfo.Workspace`** (in `battinfo._workspace`) is the object-graph engine: it
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
