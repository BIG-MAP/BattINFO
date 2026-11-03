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

`ws.preview_jsonld()` assembles the same JSON-LD graph a Zenodo deposit would carry, runs the publication checks on it and prints the result. Pass the same title and creators you will give the deposit. Without a title, the preview and the deposit both take the automatic one built from the first saved cell spec; without creators, both credit the workspace contributors (`ws.contributor()`), or failing those the creator set with `battinfo config set creator`. With no creators at all, `ws.zenodo()` refuses the deposit before it sends anything, and the preview lists that as an error. The same goes for a record the deposit graph cannot convert, or a distribution entry that is not an object with a `content_url`: the preview lists each as an error, and `ws.zenodo()` refuses the deposit rather than leave them out. To check in code rather than by reading the printout, validate the written file:

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

A clean run prints `Gold-standard: PASS (no validation issues)`. Errors make `ws.zenodo()` refuse the deposit; warnings do not. The preview also compares each test, cell and dataset node with the record it came from and warns, as `publication.record_field_not_emitted`, about a field the record fills and the node does not carry; the count is printed next to the node count. `battinfo.validate.record_fidelity_report(graph, record_sets)` runs that comparison on its own. The checks that matter for a collection:

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

The single-record emitter (`battinfo.record_to_jsonld(record, "dataset")`) writes the same two membership edges and the same series type as the deposit graph.

The registry is a different matter for now. It records each member's `series_id` in its index, so a registry query by collection lists the members and the collection's page shows them. The RDF it serves at a dataset's IRI does not carry `dcat:inSeries`, `schema:isPartOf` or the `dcat:DatasetSeries` type yet. It will once the registry serves battinfo's own JSON-LD for each record. Until then, read membership from the deposit graph or from `record_to_jsonld`, not from the registry's RDF.

## Rules that keep the links stable

**The name is part of the IRI seed.** A collection has no cell or test, so its IRI is seeded from its `access_url` and `name` alone. Rename it, or change its access URL, and it gets a new IRI; every member's `series_id` then points at a record that no longer exists. Pick an access URL that will not change (the deposit DOI, or a project landing page) and settle the name before the first publication. The description, keywords and licence can change freely. To retitle a collection that is already published, pass the IRI it was published under as `Dataset(id=...)`; [Name your records](name-your-records.md) covers titles, handles and pinned identities.

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

`ws.zenodo()` leaves a draft unless you pass `publish=True`. To send the records to the registry instead, use `ws.submit(submit_all=True)`. The `submit_all` flag matters here: `ws.submit()` normally sends only the records this session wrote with `ws.save()` or `ws.add("equipment")`, and datasets written with `save_dataset` are not among them.

The registry route refuses any record that still points at a file on your computer: a `file:///` or plain path in an access URL, a distribution's content URL, a download URL or `provenance.source_url`, or an absolute path in a `source_file` or an artifact `locator`. The registry would publish that path as the download link, and nobody else can follow it. `ws.submit()` lists each such record and field and sends nothing. The members in this example already point at Zenodo, so they pass. For datasets made from local files, run `ws.zenodo()` first: it uploads the files and points each record at its deposited copy, a draft's as well as a published one's, and `ws.submit()` then sends https URLs. A draft's URLs work once it is published. `ws.submit()` records the deposit's DOI as `provenance.citation_doi` only on the records the deposit holds, and only once it is published on zenodo.org; it checks a draft with Zenodo first, when `ZENODO_API_TOKEN` is set, in case you published it on the website. A sandbox deposit (`sandbox=True`) is a dry run: it leaves the records pointing at their local files, and `ws.submit()` still refuses them. Only for a local test registry, `ws.submit(allow_local_files=True)` lifts the check.

`.battinfo/zenodo.json` names the Zenodo record the workspace continues on zenodo.org, and `.battinfo/zenodo-sandbox.json` the one on the sandbox, so a sandbox record and a production one never mix, and nothing needs deleting between a dry run and the real deposit. `.battinfo/deposit-files.json` keeps the local file behind each deposited copy. A record that points at its copy therefore keeps its data in the next deposit, whether that is a new version, a retry after a failed run or a new record, and when its local file is gone, a new version keeps the copy it takes over from the one before. A draft of a new version leaves a record on the published copy until the draft is published, since that URL works meanwhile. A data file that changed since it was added is deposited as it is now, and the deposit graph and the record state its new sha256. A dataset that points at a Zenodo copy the workspace cannot account for, such as a file in a draft that was never published, or a copy that the record a new deposit starts from does not hold, stops `ws.zenodo()` before anything is created, and the message names the dataset. Run the `ws.add("test", ..., data=...)` call that added its file again, then `ws.save()`, to point it at the local file.

A deposit archives data files that `ws.upload()` put in R2 storage only when you ask for it. When the records point at such files, `ws.zenodo()` and `ws.publish(zenodo=True)` stop before anything is sent, and the message names the files. With R2 storage configured, `ws.publish(zenodo=True)` stops the same way before it uploads, since it puts the files in R2 first. Pass `archive_hosted_files=True` to archive them from their local files. The records keep their R2 URLs, and a warning names each file from the private bucket (`ws.upload(public=False)`), since the deposit makes it public.

## Members from local data files

The members above describe files that are already archived. When a member's data file is on your disk, the workspace can write the dataset for you: `ws.add("test", data=...)` makes one dataset per data file, and `series_id=` puts each of them in the collection. Here a fourth cell, C04, was measured later in your own lab:

```python
ws.add("cell", spec=spec, serial_numbers=["C04"])
# Stands in for the converted file you already have.
Path("ocv-study", "C04.bdf.csv").write_text(
    "test_time_second,voltage_volt\n0,0.81\n3600,0.12\n", encoding="utf-8"
)
ws.add("test", type="cycling", cell="C04", data="C04.bdf.csv", series_id=collection_iri)
ws.save()
```

`series_id` takes the collection's IRI and nothing else. A value that is not a `https://w3id.org/battinfo/dataset/...` IRI is refused before any record is created, and so is `series_id` without `data=`. Membership is not part of a record's identity, so adding or dropping `series_id` never moves the IRI of the test or its datasets. The collection itself is still saved with `Dataset` and `save_dataset`, before its members, as in step 2. `ws.zenodo()` uploads the data file with the deposit and points the dataset's distribution at its copy there.

## Deposit options

`ws.zenodo()` fills in the Zenodo form from the workspace, and a few keywords change what it sends. Without them the deposit is the one described above.

<!-- doc-snippet: skip -->
```python
result = ws.zenodo(
    title="Graphite half-cell pOCV",
    description="Pseudo-OCV curves of four graphite coin half cells.\n\nOne dataset per cell.",
    creators=[{"name": "Doe, Jane", "orcid": "0000-0002-1825-0097"}],
    version="2.0.0",
    keywords=["graphite", "pseudo-OCV"],
    auto_keywords=False,
    access_right="embargoed",
    embargo_date="2027-06-30",
    related_identifiers=[{"identifier": "10.1234/example", "relation": "isSupplementTo"}],
    publisher={"name": "Example Lab", "ror": "https://ror.org/01abcde23"},
    bundle="single",
    archive_name="ocv-study__data.zip",
)
```

- `access_right` is `"open"` unless you pass `"embargoed"`, `"restricted"` or `"closed"`. An embargo needs `embargo_date`, the day the files open, which has to be after today, and restricted access needs `access_conditions`.
- `version` goes on the form and into the deposit graph as `schema:version`. Without `publication_date`, Zenodo dates the record the day it is published.
- Zenodo's related identifiers go in `related_identifiers`; the page of a funding project set with `ws.project()` is added after them.
- Zenodo shows the description as HTML, so a description of several paragraphs, separated by blank lines, goes to the form as HTML paragraphs. The deposit graph keeps the text as you wrote it.
- The form's keywords start with `BattINFO`, `battery`, `electrochemistry` and the manufacturer, model, chemistry, format and IEC code of each saved cell spec. With `auto_keywords=False` only `keywords` are sent. A keyword that differs from an earlier one only in case, spaces, hyphens, underscores or slashes is sent once, but synonyms such as `li-ion` and `lithium-ion battery` are both kept.
- `publisher` is the organisation the deposit graph names as its publisher, by name, by ROR (`"ror"`) or by registry organization IRI (`"id"`). Without it the graph takes the first affiliation among the creators and contributors. Zenodo's form does not get it.
- The deposit joins the `battery-knowledge-base` community unless you pass another one as `community`, or `None`.

Zenodo takes at most 100 files in one record by default. A deposit of more than 90 data files is therefore zipped one archive per test kind, which is `bundle="by_kind"`, the default. `bundle="single"` zips every data file into one archive, named by `archive_name` (`data.zip` when not given), however few there are. `bundle="none"` deposits each file as itself, and `ws.zenodo()` warns before it sends anything when the deposit would then hold more than 100 files. A dataset whose file is in an archive links to the archive and names its own file. `ws.publish(zenodo=True)` has no `bundle` option, and without R2 storage it refuses a deposit of more than 90 data files, since the registry cannot yet point a record at a file inside an archive.

The deposit graph names the concept record, the Zenodo record that groups every version, as `dcterms:isVersionOf`, and the version a new version follows as `dcat:previousVersion`. `ws.zenodo()` takes both from Zenodo. `ws.preview_jsonld()` has no deposit to ask, so give them there as `is_version_of` and `previous_version`, with the other options that reach the graph:

```python
preview = ws.preview_jsonld(
    title="Graphite half-cell pOCV",
    creators=[{"name": "Doe, Jane", "orcid": "0000-0002-1825-0097"}],
    version="2.0.0",
    is_version_of="https://zenodo.org/records/1234566",
    previous_version="https://zenodo.org/records/1234567",
    publisher={"name": "Example Lab", "ror": "https://ror.org/01abcde23"},
    bundle="single",
    archive_name="ocv-study__data.zip",
)
catalog = next(node for node in json.loads(preview.read_text(encoding="utf-8"))["@graph"]
               if "dcat:Catalog" in node["@type"])
print(catalog["dcterms:isVersionOf"], catalog["dcat:previousVersion"])
```

`ws.preview_rocrate()` takes `bundle`, `archive_name` and `extra_files` as well.

## What the deposit holds

A deposit made with `ws.zenodo()` holds the files below and no others.

- The data files the dataset records name, with the test and protocol files the records point at, each under its own name. When the deposit is zipped (more than 90 such files under `bundle="by_kind"`, or `bundle="single"`), the zip archives take their place.
- `battinfo.json`, the deposit graph, which describes every record of the deposit. `ws.import_()` rebuilds a workspace from it.
- `ro-crate-metadata.json`, an RO-Crate that lists `battinfo.json` and every other file, the data files and extra files with their size and sha256.
- Any extra files you pass in `extra_files`.

`battinfo.bundle.json` is never part of a workspace deposit. Only `build_zenodo_package()`, which `battinfo batch package` runs, writes that file.

Extra files, such as a README or a list of checksums, document the deposit as a whole. They belong to no dataset and are not distributions. Each goes up as itself, never zipped. The RO-Crate lists it as a `File`, and the catalog of the deposit graph lists it under `schema:hasPart`, after the member datasets, as a `schema:DigitalDocument` with its media type, size and sha256. `dcat:dataset` still names the datasets alone.

```python
Path("ocv-study", "README.md").write_text(
    "# Graphite half-cell pOCV\n\nOne dataset per cell, one file per dataset.\n", encoding="utf-8"
)
preview = ws.preview_jsonld(
    title="Graphite half-cell pOCV",
    creators=[{"name": "Doe, Jane", "orcid": "0000-0002-1825-0097"}],
    extra_files=["README.md"],
)
catalog = next(node for node in json.loads(preview.read_text(encoding="utf-8"))["@graph"]
               if "dcat:Catalog" in node["@type"])
print([part["schema:name"] for part in catalog["schema:hasPart"] if "schema:name" in part])  # ['README.md']
```

A relative path is read from the workspace folder, and each file keeps its own name. To give one another name in the deposit, pass a mapping of path to name instead of a list, such as `{"notes/readme-v2.md": "README.md"}`. Before anything is sent, `ws.zenodo()` refuses a path that is not a file, and a name the deposit already gives a data file, an archive, `battinfo.json`, `ro-crate-metadata.json` or another extra file, whatever its case. Extra files count toward the 100 files Zenodo takes in one record.

`.battinfo/zenodo.json` records the names of the extra files. Each run describes the whole deposit, so pass the same `extra_files` every time. A file that has not changed stays on the draft as it is and a changed one is replaced. One that a run leaves out is removed, and the run warns, naming it. `ws.publish(zenodo=True)` passes no extra files, so it removes them too.
