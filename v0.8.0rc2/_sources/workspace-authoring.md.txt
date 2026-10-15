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

# 5. Register the physical cells you tested, by the serials printed on
#    them or labels only your lab uses: a cell's IRI comes from its spec
#    and serial, so a bare "S1" mints the IRI of every other lab's "S1".
ws.add("cell", spec=spec, serial_numbers=["MYLAB-50E-001", "MYLAB-50E-002", "MYLAB-50E-003"])

# 6. Attach a test + data to a cell (explicit)
ws.add("test", type="cycling", cell="MYLAB-50E-001", data="bdf/MYLAB-50E-001.bdf.csv")

# 7. Publish (add zenodo=True for a citable DOI)
ws.save()
ws.publish(note="My cycling campaign, 2026")

ws.status()                          # see it live
```

Every verb is a method on the returned `AuthoringWorkspace` (also importable as
`battinfo.AuthoringWorkspace`): `login`, `whoami`, `credentials_status`, `has_credential`,
`project`, `convert`, `search`, `add`, `load`, `save`, `publish`, `submit`, `status`,
`zenodo`. Each has a docstring with examples —
`help(ws.add)` is the fastest reference.

## Credentials

`ws.login(api_key=...)` saves your registry key in `.battinfo/credentials` in the workspace folder, with the workspace and publisher ids the registry returns. When the registry cannot be asked, `login()` keeps the ids the workspace already has and saves the defaults for any it lacks; an id found only in the environment is used but not saved. `ws.setup()` writes the same file from a template that lists the registry, R2 and Zenodo settings, with the default ids filled in. A name set on more than one line takes the last value. The file is git-ignored, and both calls make it readable by you only (mode 0600 on Linux and macOS).

Each name is looked up in this order, and the first value found is used:

1. an argument passed to the call, such as `ws.zenodo(token=...)` or `ws.submit(api_key=...)`;
2. a value `ws.login()` set on this workspace in this session;
3. an environment variable of the same name;
4. this workspace's `.battinfo/credentials`;
5. the default, for the few names that have one.

The file belongs to its workspace. Opening a workspace reads it into the workspace object, and the workspace reads it again when it changes, so an edit takes effect without reopening the workspace. Nothing is copied into the environment, so two workspaces open in one Python session each use their own credentials, and `os.environ.get("ZENODO_API_TOKEN")` does not tell you what a workspace will use. Ask the workspace:

```python
ws.credentials_status()                    # {"ZENODO_API_TOKEN": {"set": True, "source": "credentials_file"}, ...}
ws.has_credential("ZENODO_SANDBOX_TOKEN")  # True or False
ws.whoami()                                # your registry identity, and where each credential came from
```

None of the three shows a secret. The status gives each name's source (`login`, `environment`, `credentials_file` or `default`, and `argument` for a registry URL passed to `battinfo.workspace()`) and never its value.

The registry URL is looked up the same way, each time it is used. `battinfo.workspace(".")` takes `BATTINFO_REGISTRY_URL` from the environment, then from `.battinfo/credentials`, then uses the production registry, which is also what `battinfo.registry.Registry()` defaults to. `ws.login()` and `ws.whoami()` print the registry they ask and where its URL came from. `registry_url="..."` picks a registry. `registry_url=None` turns registry lookups off, and `ws.login()`, `ws.submit()` and `ws.status()` on such a workspace then need `BATTINFO_REGISTRY_URL` or a `registry_url=` of their own; they never fall back to the production registry.

## Which surface do I use?

| You want to… | Use | Entry point |
|---|---|---|
| Describe cells/tests/datasets interactively and publish them (the common case) | **Authoring workspace** | `ws = battinfo.workspace(".")` — this page |
| Create a single record in code and save or publish it | **Models + functions** | `CellSpec(...)` + `battinfo.publish(...)` for a cell spec; the other models with their `save_*` function. See the [Python API](pages/api-reference.rst) |
| Register materials and component specs (electrodes, electrolytes, …) | **`battinfo.api` functions** | `create_*` / `save_*` — see the [how-to guides](pages/howto.md) |
| Build or script the full object graph programmatically (ingest pipelines, batch tooling) | **Object-graph engine** | `battinfo._workspace.Workspace` |

## What each surface can author today

Verified against the current release — where a cell says "no", that is a
roadmap item, not an omission in your usage:

| Record type | Workspace (`ws.*`) | Python (`battinfo` / `battinfo.api`) | CLI (`battinfo …`) |
|---|---|---|---|
| Cell spec | yes — `template` + `load`, `search` + reuse, `spec=` on `add("cell")` | yes — `CellSpec` + `save_cell_spec` / `publish` | yes — `template` / `save cell-spec` / `validate` |
| Cell (physical instance) | yes — `add("cell", names=[...])` | yes — `save_cell_instance` | yes — `create` / `save cell-instance` |
| Test spec (protocol) | yes — `template("test-spec")` + `load` once `type` is filled in, or a `TestSpec` passed as `spec=` on `add("test")` | yes — `TestSpec` + `save_test_spec` | yes — `template` / `save test-spec` |
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
- **The record models** (`CellSpec`, `Cell`, `Test`, `TestSpec`, `Dataset`) are the authoring input, and every save validates their records against the JSON Schema, which is the save-time contract. Every field carries a description (`help(battinfo.CellSpec)`), and misspelled arguments get a did-you-mean.
- **`battinfo.publish(...)`** takes one `CellSpec` and saves its canonical
  record without a workspace, or saves and submits it to a registry. A `Cell`,
  `TestSpec`, `Test` or `Dataset` is saved with `save_cell_instance`,
  `save_test_spec`, `save_test` or `save_dataset` instead.
