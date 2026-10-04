# Read data from the registry

The workspace is for describing and publishing. `battinfo.registry.Registry` goes the other way: it finds what a registry holds and loads the measurement files for analysis. Use it when you want to build a data pipeline on published datasets.

A registry is an index. It stores records and the links between them, and each dataset record points at its files with a URL, a size and a checksum. The files themselves live wherever the publisher put them.

Listing and looking up records needs only the core install. Loading files and building the catalog return pandas objects:

```bash
pip install "battinfo[tabular]"
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
| `file_url`, `file_name`, `media_type`, `sha256`, `size_bytes` | Its measurement file |
| `test_id`, `test_kind` | The test that produced it (`cycling`, `capacity_check`, `gitt`, ...) |
| `cell_id`, `cell_name`, `cell_spec_id` | The physical cell and its spec |
| `manufacturer`, `model`, `format`, `chemistry`, `positive_electrode_basis`, `negative_electrode_basis` | Cell description |
| `nominal_capacity_ah`, `nominal_capacity_source` | Stated capacity in Ah, and whether it is the nominal, rated, typical or minimum figure |

A cell with no stated capacity has an empty `nominal_capacity_ah`. Nothing is estimated from the data.

## Load one dataset

<!-- doc-snippet: skip -->
```python
df = reg.read(cycling.iloc[0].dataset_id)
print(df.columns.tolist())
# ['test_time_second', 'voltage_volt', 'current_ampere', 'cycle_count', 'step_index', ...]
```

`read` downloads the file, checks it against the checksum in the record, keeps a local copy and returns a DataFrame. The second call for the same dataset reads the local copy.

Files come from many publishers and do not all spell their columns the same way. By default `read` renames columns to machine-readable BDF names, so `Voltage / V` becomes `voltage_volt` and a file that logs time in milliseconds comes back with `test_time_second`. Columns it does not recognise are left as they are, and it never invents one: a file with no step column still has none. Pass `bdf_names=False` to get the file exactly as published.

To fetch a file without loading it:

<!-- doc-snippet: skip -->
```python
path = reg.download(dataset_id)             # into the cache
path = reg.download(dataset_id, dest="data/raw")
```

## Process many datasets

<!-- doc-snippet: skip -->
```python
from pathlib import Path

out = Path("features")
out.mkdir(exist_ok=True)

for row in cycling.itertuples():
    df = reg.read(row.dataset_id)
    per_cycle = df.groupby("cycle_count").agg(
        v_min=("voltage_volt", "min"),
        v_max=("voltage_volt", "max"),
        duration_s=("test_time_second", lambda t: t.max() - t.min()),
    )
    per_cycle.to_parquet(out / f"{row.dataset_id.rsplit('/', 1)[1]}.parquet")
```

Keep the `dataset_id` with anything you derive. It is the persistent identifier to cite, and it is how you get back to the cell and test descriptions later.

## Look at individual records

<!-- doc-snippet: skip -->
```python
tests = reg.list("test", kind="cycling")          # summaries, all pages
record = reg.get(tests[0])                        # the full record
reg.links(record)                                 # {'cell': [...], 'test_spec': [...]}
reg.files("https://w3id.org/battinfo/dataset/xt2a-nsda-njps-9n50")
```

`list` accepts any record type (`dataset`, `test`, `cell`, `cell_spec`, `test_spec`, ...). `get` takes an IRI, or a summary returned by `list`.

## Where things are kept

Downloads and the catalog go to the user cache directory (`~/.cache/battinfo`, or `%LOCALAPPDATA%\battinfo` on Windows). Set `BATTINFO_CACHE_DIR`, or pass `cache_dir=` to `Registry`, to put them somewhere else. `BATTINFO_REGISTRY_URL` changes the default registry.

The public registry can take half a minute to answer the first request after it has been idle. Later requests are fast.
