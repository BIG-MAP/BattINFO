# Read data from the registry

The workspace is for describing and publishing. `battinfo.registry.Registry` goes the other way: it finds what a registry holds and loads the measurement files for analysis. Use it when you want to build a data pipeline on published datasets.

A registry is an index. It stores records and the links between them, and each dataset record points at its files with a URL, a size and a checksum. The files themselves live wherever the publisher put them.

Listing and looking up records needs only the core install. Loading files and building the catalog return pandas objects:

```bash
pip install "battinfo[tabular] @ git+https://github.com/BIG-MAP/BattINFO.git"
```

## Start from the catalog

The catalog is one table with a row per dataset, already joined with the test that produced it, the cell it was measured on and that cell's spec. Filter it before you download anything.

<!-- doc-snippet: skip -->
```python
from battinfo.registry import Registry

reg = Registry()            # the public registry; pass a URL for another one
catalog = reg.catalog()

cycling = catalog[(catalog.test_kind == "cycling") & (catalog.format == "coin")]
print(cycling[["title", "chemistry", "positive_electrode_basis", "nominal_capacity_ah"]])
```

Building the catalog reads every dataset record once, which takes a few minutes on a large registry. The result is cached and reused until the registry reports a change. Pass `refresh=True` to rebuild it regardless.

The columns are:

| Columns | What they hold |
|---|---|
| `dataset_id`, `title`, `license`, `doi` | The dataset record |
| `file_url`, `file_name`, `media_type`, `sha256`, `size_bytes` | Its measurement file. `sha256` is filled only when the record states a SHA-256 checksum |
| `test_id`, `test_kind` | The test that produced it (`cycling`, `capacity_check`, `gitt`, ...) |
| `cell_id`, `cell_name`, `cell_spec_id` | The physical cell and its spec |
| `manufacturer`, `model`, `format`, `chemistry`, `positive_electrode_basis`, `negative_electrode_basis` | Cell description |
| `nominal_capacity_ah`, `nominal_capacity_source` | Stated capacity in Ah, and the property it was read from: `nominal_capacity`, `rated_capacity`, `typical_capacity` or `minimum_capacity`, the first one the cell (or else its spec) states, in that order |
| `checksum_algorithm`, `checksum_value` | The checksum the record states for the file (`sha256`, `md5`, ...), which `download()` and `read()` verify |

A cell with no stated capacity has an empty `nominal_capacity_ah`. Nothing is estimated from the data.

## Load one dataset

<!-- doc-snippet: skip -->
```python
df = reg.read(cycling.iloc[0].dataset_id)
print(df.columns.tolist())
# ['test_time_second', 'voltage_volt', 'current_ampere', 'cycle_count', 'step_index', ...]
```

`read` downloads the file, checks it against the checksum in the record, keeps a local copy and returns a DataFrame. The second call for the same dataset reads the local copy, after checking it again.

The check uses whichever algorithm the record states, as long as Python's `hashlib` provides it. That covers SHA-256 and MD5, which is what Zenodo records give. A download that does not match raises `OSError`, and a local copy that no longer matches is fetched again. Some records state no checksum, or one in an algorithm `hashlib` does not provide: such a file is used unchecked, and a `UserWarning` names it the first time.

Files come from many publishers and do not all spell their columns the same way. By default `read` renames columns to machine-readable BDF names, so `Voltage / V` becomes `voltage_volt` and a file that logs time in milliseconds comes back with `test_time_second`. Columns it does not recognise are left as they are, and it never invents one: a file with no step column still has none. Pass `bdf_names=False` to get the file exactly as published.

To fetch a file without loading it:

<!-- doc-snippet: skip -->
```python
path = reg.download(dataset_id)             # into the cache
path = reg.download(dataset_id, dest="data/raw")
```

## Check what the columns mean

Renaming makes the names agree. It does not make every file mean the same thing by them, so check these before you compute features across sources:

- `current_ampere` is negative while the cell discharges and positive while it charges.
- `cycle_count` starts at 0 in some files and at 1 in others, depending on the cycler and the converter that wrote them. Take the first cycle from the data (`df.cycle_count.min()`) rather than assuming it is 1.
- Which capacity columns a file has depends on its source, and some published files do not follow the BDF definitions. Files from one publisher reset `cumulative_capacity_ah` at every step, so it holds a per-step capacity rather than a running total. Files from another reset `charging_capacity_ah` and `discharging_capacity_ah` every cycle. `step_capacity_ah`, a name from an earlier BDF version, does not always reset at a step boundary.

When in doubt, compute capacity from current and time yourself. Per-cycle discharge capacity by coulomb counting:

<!-- doc-snippet: skip -->
```python
dt_h = df.test_time_second.diff().fillna(0) / 3600
discharge_ah = (-df.current_ampere).clip(lower=0) * dt_h
per_cycle_discharge_ah = discharge_ah.groupby(df.cycle_count).sum()
```

## Process many datasets

<!-- doc-snippet: skip -->
```python
from pathlib import Path

out = Path("features")
out.mkdir(exist_ok=True)

for row in cycling.itertuples():
    try:
        df = reg.read(row.dataset_id)
    except ValueError as err:  # a data file read() does not load, such as .xlsx
        print(f"skipped {row.dataset_id}: {err}")
        continue
    per_cycle = df.groupby("cycle_count").agg(
        v_min=("voltage_volt", "min"),
        v_max=("voltage_volt", "max"),
        duration_s=("test_time_second", lambda t: t.max() - t.min()),
    )
    per_cycle.to_parquet(out / f"{row.dataset_id.rsplit('/', 1)[1]}.parquet")
```

`read()` loads `.parquet` and `.csv` files and raises `ValueError` for anything else, such as the spreadsheets (`.xlsx`) a few publishers share, so the loop skips those and says which instead of stopping at the first one.

Keep the `dataset_id` with anything you derive. It is the persistent identifier to cite, and it is how you get back to the cell and test descriptions later.

## Look at individual records

<!-- doc-snippet: skip -->
```python
tests = reg.list("test", kind="cycling")          # summaries, all pages
entry = reg.get(tests[0])                         # the registry's entry for the test
reg.links(entry)                                  # e.g. {'cell': ['https://w3id.org/battinfo/cell/...']}
reg.files("https://w3id.org/battinfo/dataset/xt2a-nsda-njps-9n50")
```

`list` accepts any record type (`dataset`, `test`, `cell`, `cell_spec`, `test_spec`, ...). `get` takes an IRI, or a summary returned by `list`.

`links` groups the IRIs a record points at by the type of the record they name, as the registry indexed them. Which keys appear depends on the record: a test has `cell`, plus `test_spec` only when it names its test spec; a dataset has `cell` and `test`; a cell has `cell_spec`, `test` and `dataset`. A type the record has no link to is left out rather than given an empty list, so read it with `reg.links(entry).get("test_spec", [])`.

## Get the record out of an entry

The entry that `get` returns is the registry's view of a record: its IRI, title and status, the links and files the registry indexed, and the record as it was published. The entry itself is not a BattINFO record, so `Dataset.from_record` and the other `from_record` methods cannot take it. The record sits inside it, under the entry's `resource_type`:

<!-- doc-snippet: skip -->
```python
entry = reg.get("https://w3id.org/battinfo/dataset/xt2a-nsda-njps-9n50")
record = entry["semantic_payload"]["battinfo_records"][entry["resource_type"]]
```

The same line works for every record type. A cell's entry keeps its record under `"cell"` (the body inside is `cell_instance`) and a copy of the cell's spec under `"cell_spec"`.

## Make a new version of a published dataset

To change a published dataset, for example to link it to a different test, rebuild it from its record, change what needs changing, save it and submit it. The registry keeps it as a new version of the same IRI.

The curve preview the registry shows for a dataset does not come along by itself. Its two files, a Plotly figure (`.plot.json`, role `plot_data`) and an image (`.png`, role `plot_static`), are listed in the entry's `distributions` but not in the record, so a version made from the record alone is published without them, and nothing warns you. Copy them across before you save:

<!-- doc-snippet: skip -->
```python
import battinfo

files = list(record["dataset"].get("distributions", []))
names = {f.get("name") for f in files}
for f in entry["distributions"]:
    if f.get("role") in ("plot_data", "plot_static") and f["title"] not in names:
        files.append({"name": f["title"], "content_url": f["access_url"], "encoding_format": f.get("media_type")})

dataset = battinfo.Dataset.from_record(record)
dataset.test_id = new_test_iri            # the change this version makes
dataset.distributions = files
battinfo.save_dataset(dataset, source_root="lab/.battinfo/records", validation_policy="strict")
```

`ws.submit()` recognises the copied files by their names and lists them as `plot_data` and `plot_static` again, with the image as the preview. The record keeps only the measurement files, as the published one does.

`save_dataset` checks that the cell and test the dataset is about are known in the workspace. A cell the workspace has looked up in the registry counts, for example one given by IRI to `ws.add("test", cell=...)` when you make the new test. A cell or test that exists only in the registry and was never looked up does not, so for a version that keeps its published links, pass `resolve_references=False`.

Once `ws.save()` or `ws.add("equipment")` has written records in a session, `ws.submit()` sends only those, even with `submit_all=True`, and a dataset written by `save_dataset` is not one of them. Submit the dataset from a new workspace object:

<!-- doc-snippet: skip -->
```python
ws = battinfo.workspace("lab")
ws.login(api_key="...")
ws.submit(only="dataset", submit_all=True)
```

## Where things are kept

Downloads and the catalog go to the user cache directory (`~/.cache/battinfo`, or `%LOCALAPPDATA%\battinfo` on Windows). Set `BATTINFO_CACHE_DIR`, or pass `cache_dir=` to `Registry`, to put them somewhere else. `BATTINFO_REGISTRY_URL` changes the default registry.

The public registry can take half a minute to answer the first request after it has been idle. Later requests are fast.
