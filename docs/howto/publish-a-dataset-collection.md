# Publish a dataset collection

A collection groups the datasets of one study or one deposit under a single record, so a reader can find all of them from one place and cite them together. In BattINFO a collection is an ordinary dataset record with `additional_type=["DatasetSeries"]` (a DCAT 3 dataset series). Each member dataset points at it with `series_id`. There is no separate record type.

This page builds a collection of three half-cell measurements, checks the deposit graph, and explains the rules that keep the links stable after publication.

## When to use one

Use a collection when several datasets belong together and someone will want them as a set: the 95 files of one Zenodo deposit, every cell of a cycling campaign, the repeats of one protocol. Each member still describes one data artifact with its own cell, test and files. The collection adds the grouping and nothing else.

Skip it for a single dataset, or for datasets that only share a cell or a test. Those links already live in each dataset's `about` list.

## 1. Describe the cells and tests

The cells and tests are authored with the workspace as usual. This example has three coin half cells and one test on each:

```python
from pathlib import Path

import battinfo
from battinfo.metadata import checksum, distribution

ws = battinfo.workspace("ocv-study", registry_url=None)
ws.license("cc-by-4.0")

spec = battinfo.CellSpec(
    manufacturer="Example Lab", model="R2032 graphite half cell",
    format="coin", chemistry="li-ion",
)
cells = ws.add("cell", spec=spec, serial_numbers=["C01", "C02", "C03"])
tests = [ws.add("test", type="cycling", cell=cell)[0] for cell in cells]
ws.save()
```

## 2. Save the collection first

The data files in this example are already archived (here on Zenodo), so the datasets describe them by URL. Datasets like that are written with the `Dataset` model and `save_dataset`, into the same records folder the workspace uses.

The collection has a name, a description, the series marker and an access URL. It has no cell, no test and no files:

```python
records = Path("ocv-study") / ".battinfo" / "records"
deposit = "https://doi.org/10.5281/zenodo.1234567"

collection = battinfo.Dataset(
    name="Graphite half-cell pOCV collection",
    description="Pseudo-OCV curves of three graphite coin half cells, one dataset per cell.",
    additional_type=["DatasetSeries"],
    access_url=deposit,
    license="cc-by-4.0",
    source={"type": "measurement"},
)
saved = battinfo.save_dataset(
    collection, source_root=records, mode="upsert",
    validation_policy="strict", build_jsonld=False, build_html=False,
)
collection_iri = saved["id"]
print(collection_iri)
```

Its IRI is minted from the access URL and the name. Saving the same collection again returns the same IRI, which is what makes the members' links reproducible.

## 3. Save the members

Each member is a normal dataset: it names its cell and test (they end up in its `about` list), lists its files, and carries `series_id`. Zenodo shows an md5 checksum for every file, so it is copied in here:

```python
md5 = {
    "C01": "3b5d5c3712955042212316173ccf37be",
    "C02": "2cd6ee2c70b0bde53fbe6cac3c8b8bb1",
    "C03": "e29311f6f1bf1af907f9ef9f44b8328b",
}
for cell, test in zip(cells, tests):
    member = battinfo.Dataset(
        name=f"Graphite half-cell pOCV, cell {cell.serial_number}",
        cell=cell,
        test=test,
        series_id=collection_iri,
        access_url=deposit,
        license="cc-by-4.0",
        distributions=[
            distribution(
                f"https://zenodo.org/records/1234567/files/{cell.serial_number}.bdf.parquet",
                encoding_format="application/vnd.apache.parquet",
                checksum_value=checksum("md5", md5[cell.serial_number]),
            )
        ],
        source={"type": "measurement"},
    )
    battinfo.save_dataset(
        member, source_root=records, mode="upsert",
        validation_policy="strict", build_jsonld=False, build_html=False,
    )
```

The tests do not need to list their datasets in `dataset_ids`. The deposit graph reads each dataset's own `about` list and fills in the reverse link (`prov:generated`) on the test.

## 4. Check the deposit graph

`ws.preview_jsonld()` assembles the same JSON-LD graph a Zenodo deposit would carry, runs the publication checks on it and prints the result. Pass the same title and creators you will give the deposit. To check in code rather than by reading the printout, validate the written file:

```python
import json

from battinfo.validate import validate_publication_report

preview = ws.preview_jsonld(
    title="Graphite half-cell pOCV",
    creators=[{"name": "Doe, Jane", "orcid": "0000-0002-1825-0097"}],
)
graph = json.loads(preview.read_text(encoding="utf-8"))
report = validate_publication_report(graph, policy="publisher")
for issue in report.issues:
    print(issue.severity, issue.code, issue.message)
assert not report.issues
```

A clean run prints `Gold-standard: PASS (no validation issues)`. The checks that matter for a collection:

- every member needs a non-empty `schema:about` and at least one distribution; the collection is exempt from both;
- a member's `dcat:inSeries` must point at a node typed `dcat:DatasetSeries` when that node is in the graph (`publication.series_target_not_series` otherwise);
- a member whose collection is not in the graph gets a warning, `publication.series_not_in_package`. That is expected when the collection was published earlier, and a mistake when you forgot to save it.

Single records can be checked with `battinfo.validate_record_report(record, policy="strict")`. The strict policy lets a collection go without a cell link, and only a collection.

## What it looks like in JSON-LD

In the deposit graph the collection is typed as a series and carries no files:

```json
{
  "@type": ["dcat:Dataset", "schema:Dataset", "dcat:DatasetSeries"],
  "@id": "https://w3id.org/battinfo/dataset/3qnk-am9a-nnfp-jjde",
  "schema:name": "Graphite half-cell pOCV collection",
  "dcterms:isPartOf": {"@id": "https://zenodo.org/records/RECORD_ID"}
}
```

Each member points at it twice, once in DCAT (`dcat:inSeries`) and once for dataset search engines (`schema:isPartOf`), and says what it is about. `dcterms:isPartOf` is the Zenodo record the whole deposit lives in:

```json
{
  "@type": ["dcat:Dataset", "schema:Dataset"],
  "@id": "https://w3id.org/battinfo/dataset/dce8-qhqb-z438-wsx8",
  "schema:name": "Graphite half-cell pOCV, cell C01",
  "schema:about": [
    {"@id": "https://w3id.org/battinfo/cell/2r4c-8tav-e52s-q1hp"},
    {"@id": "https://w3id.org/battinfo/test/5xpt-0m0e-nrp5-q323"}
  ],
  "dcat:inSeries": {"@id": "https://w3id.org/battinfo/dataset/3qnk-am9a-nnfp-jjde"},
  "schema:isPartOf": {"@id": "https://w3id.org/battinfo/dataset/3qnk-am9a-nnfp-jjde"},
  "dcterms:isPartOf": {"@id": "https://zenodo.org/records/RECORD_ID"}
}
```

The single-record emitter (`battinfo.record_to_jsonld(record, "dataset")`) and the registry's resolver use the same two membership edges and the same series type.

## Rules that keep the links stable

**The name is frozen once published.** A collection has no cell or test, so its IRI is seeded from its `access_url` and `name` alone. Rename it, or change its access URL, and it gets a new IRI; every member's `series_id` then points at a record that no longer exists. Pick an access URL that will not change (the deposit DOI, or a project landing page) and settle the name before the first publication. The description, keywords and licence can change freely.

**Publish the collection before its members.** Members carry the link, so the collection has to exist with its final IRI before they cite it. In a single Zenodo deposit this happens on its own, since everything goes up together. If the members go out later or separately, publish the collection first.

**A collection has no distributions and no `about`.** The files and the cell and test links belong to the members. Leave both out of the collection; the publication checks exempt it from them.

## Publishing

Once the preview is clean, publish as usual. The deposit carries the collection and all its members in one `battinfo.json`:

<!-- doc-snippet: skip -->
```python
result = ws.zenodo(
    title="Graphite half-cell pOCV",
    creators=[{"name": "Doe, Jane", "orcid": "0000-0002-1825-0097"}],
)
```

`ws.zenodo()` leaves a draft unless you pass `publish=True`. To send the records to the registry instead, use `ws.submit(submit_all=True)`. The `submit_all` flag matters here: `ws.submit()` normally sends only what the last `ws.save()` wrote, and datasets written with `save_dataset` are not part of that.

## Limits today

`ws.add("test", data=...)` creates a dataset for each local data file, but it has no way to set `series_id`. Collections of local files therefore need the member datasets written with `Dataset` and `save_dataset` as above, with `file://` URLs in their distributions. `ws.zenodo()` uploads those files with the deposit and points each distribution at its copy there, which `ws.preview_jsonld()` already shows.
