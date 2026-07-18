# Find what already exists

Three surfaces, three scopes. Know which one you are asking before you trust
an answer:

| You are asking about… | Use | Scope |
|---|---|---|
| Records in **this workspace session** | `ws.list(verbose=True)` | What you have added/saved locally with the workspace |
| Records in a **library folder on disk** | `battinfo.api.query_*` / `battinfo query` (CLI) | Exactly the directory you point it at |
| Records **published to the registry** | `ws.search(...)` | The live Battery Genome registry (battery-genome.org) |

## Your workspace session: `ws.list`

```python
import battinfo

ws = battinfo.workspace(".")
spec = battinfo.CellSpec(manufacturer="My Lab", model="COIN-NMC811-A",
                         format="coin", chemistry="Li-ion")
ws.add("cell", spec=spec, names=["B7-01", "B7-02"])
ws.save()

listing = ws.list(verbose=True)   # prints every record, grouped by type, with IRIs
```

Records tagged `[this session]` are the ones `ws.submit()` would send.
Equipment and channel records are registered separately
(`ws.add("equipment", ...)`) and do not currently appear in `ws.list` output.

## A library folder: `query_*`

Every `query_*` function takes the directory to search. **Pass it explicitly**
— with no argument they read the example records packaged inside the BattINFO
wheel, which look plausible but are not yours:

```python
from battinfo.api import query_cell_specs, query_material_specs

# the records ws.save() wrote for this workspace:
mine = query_cell_specs(cell_specs_dir=".battinfo/records/cell-spec")
print([r["model_name"] for r in mine])       # ['COIN-NMC811-A']

# a library you built with save_* functions (source_root="my-library"):
mats = query_material_specs(directory="my-library/material-spec")
```

One asymmetry to know about: `query_cell_specs` calls its directory argument
`cell_specs_dir`; the other `query_*` functions call it `directory`.

The CLI equivalent (`battinfo query cell-spec`, `battinfo query test-spec`, …)
currently reads only the packaged example records — it has no directory
option, so use the Python `query_*` functions for your own library.

<!-- doc-snippet: skip -->
```python
# Filters match the record fields:
query_cell_specs(chemistry="Li-ion", cell_format="coin",
                 cell_specs_dir="my-library/cell-spec")
query_material_specs(material_class="binder", directory="my-library/material-spec")
```

## The registry: `ws.search`

`ws.search` asks the live registry — the shared index of *published* records:

<!-- doc-snippet: skip -->
```python
spec = ws.search("samsung inr21700 50e")[0]        # fuzzy: tolerates typos
cells = ws.search(type="cell", serial="tpejqj")     # instances by serial / short ID
tests = ws.search(type="test-spec", query="capacity")
```

Reading the registry needs no account or API key. What the results mean:

- **A hit** is a published record; `ws.load(hit)` references it in your session
  (reusing its IRI) instead of authoring a duplicate.
- **No hits** means nothing published matches — your own unpublished records
  will *not* appear here; they are only visible to `ws.list` and `query_*`.
- **Offline** (or registry unreachable): search falls back to a local clone of
  the records repository if you have one configured, otherwise it returns an
  empty list after printing a "Registry unreachable" notice. An empty result
  while offline is not evidence that a record does not exist.

`ws.status()` (what have I published?) talks to the registry too, and needs
`ws.login(api_key=...)` first — see the
[troubleshooting page](../pages/troubleshooting.md) if it asks for a
workspace id.
