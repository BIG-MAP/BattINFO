# Name your records: titles and handles

A record carries three names, and each has one job:

- The **IRI** (`https://w3id.org/battinfo/cell/7k2m-...`) is its identity. It is opaque and never changes.
- The **handle** (`flores-ocv/graphite-aq-1-063b77-cell`) is a short slug, unique within one registry workspace. The registry shows it as `<workspace>/<handle>` and can resolve it.
- The **title** is the record's `name` (`Graphite AQ-1 cell 063b77`), written for people.

Handles and titles are display text. You can correct either one later without moving the IRI, as long as you pin the identity (see below). Code that needs to know what a record is should read its structured fields, never parse its handle.

## Build them from structured parts

Nobody should type handles by hand. `battinfo.naming` builds both names from the same parts, so a corpus of a thousand records gets consistent ones:

```python
from battinfo.naming import handle_for, title_for

parts = {"subject": "graphite", "variant": "Gr-AQ-1", "sample": "063b77"}

print(handle_for("cell", group="flores-ocv", **parts))   # flores-ocv/graphite-aq-1-063b77-cell
print(title_for("cell", **parts))                        # Graphite AQ-1 cell 063b77
print(handle_for("test", group="flores-ocv", method="gitt", **parts))
# flores-ocv/graphite-aq-1-063b77-gitt-test
print(title_for("test", method="gitt", **parts))         # Graphite AQ-1 cell 063b77 GITT test
print(handle_for("collection", group="flores-ocv"))      # flores-ocv
```

The parts are:

| Part | What it is | Example |
|---|---|---|
| `group` | The handle of the collection the record belongs to. A collection's own handle is the bare group. | `flores-ocv` |
| `subject` | The material kind, as a key or alias from `battinfo.materials.material_kinds()`. | `graphite`, `silicon_graphite`, `lnmo` |
| `variant` | The source's own design or batch label. A leading prefix that names the subject's material is dropped. | `Gr-AQ-1` becomes `aq-1` in the handle and `AQ-1` in the title |
| `sample` | The source's sample id, for a physical item and its results. | `063b77` |
| `method` | The test method, for tests and datasets. | `gitt`, `p-ocv-hold` |

A handle reads `<group>/<subject>-<variant>-<sample>-<method>-<kind>`, leaving out the parts a record does not have. The kind word always comes last and depends only on the record type: `material-spec`, `material-lot`, `electrode-spec`, `electrode`, `cell-spec`, `cell`, `test-spec`, `test`, `dataset`, and so on for the component, equipment and parameter-set types. The full table is `battinfo.naming.KIND_WORDS`. A collection carries no kind word.

A research record's title leads with its source, as author and year: `title_for("material-spec", source="Flores 2026", subject="graphite")` gives `Flores 2026 graphite material spec`. A registry holds many graphite material specs, and the source is what tells them apart in a list or a search result. After a source, a subject that is a common word loses its capital (graphite, silicon-graphite) and an abbreviation keeps it (LNMO, NMC532). Products name their manufacturer instead (below), and a collection's label carries its source itself (`Flores 2026 half-cell OCP collection`).

Titles use the same parts in plain English. Subjects get a short label (Graphite, Silicon-graphite, LNMO, NMC532), the variant is upper case, and the sample is kept as written. A method written in lower case is upper-cased (`gitt` becomes `GITT`); one the source already capitalises keeps its spelling (`p-OCV hold`). Tests and datasets name the item they are about first: `Graphite AQ-1 cell 063b77 GITT dataset`. A collection's title is its own label plus the word "collection", via `title_for("collection", label="Flores et al. 2026 half-cell OCV")`.

Both functions lowercase and transliterate their input to ASCII and collapse anything that is not a letter or digit into a single hyphen. A part that has nothing left after that raises `ValueError`, and so does a handle longer than 120 characters.

## Products and manufacturers

A commercial product is known by its maker and its model, so it is named by them instead of by a collection. Pass `manufacturer=` and `model=` for any spec type a manufacturer or supplier makes (cell, material, electrode, separator, current collector, electrolyte, housing and equipment specs; the set is `battinfo.naming.PRODUCT_KINDS`):

```python
from battinfo.naming import handle_for, organization_handle, title_for

print(handle_for("cell-spec", manufacturer="Samsung SDI", model="INR18650-35E"))
# samsung-sdi/inr18650-35e-cell-spec
print(title_for("cell-spec", manufacturer="Samsung SDI", model="Samsung SDI INR18650-35E"))
# Samsung SDI INR18650-35E

eve = {"name": "EVE", "handle": "eve-energy"}  # the manufacturer reference a record carries
print(handle_for("cell-spec", manufacturer=eve, model="LF280K"))  # eve-energy/lf280k-cell-spec
print(organization_handle("Haldor Topsøe A/S"))                    # haldor-topsoe-a-s
```

The handle is `<manufacturer>/<model>-<kind>`. The title is the manufacturer's name and the model with no kind words: that is what people search for and cite, and the record type is shown beside the title. A model that repeats the manufacturer's name ("Samsung SDI INR18650-35E") is not doubled.

The group is the manufacturer's organization handle when the reference or record carries one, and its slugged name otherwise. Give each organization a handle once (`organization_handle()` builds one, a single bare segment such as `eve-energy`) and every product of that company lands in one group, whichever spelling of its name a datasheet used. Like a collection's, an organization's handle carries no kind word.

## Put them on records

Every record type has an optional `handle` next to its `name`, and every authoring surface that takes `name=` takes `handle=`. The workspace never makes one up for you:

```python
import battinfo
from battinfo.naming import handle_for, title_for

ws = battinfo.workspace("lab", registry_url=None)
gr = {"subject": "graphite", "variant": "Gr-AQ-1"}

ws.add(
    "material_spec", kind="graphite",
    name=title_for("material-spec", subject="graphite"),
    handle=handle_for("material-spec", group="flores-ocv", subject="graphite"),
)
spec = battinfo.CellSpec(
    manufacturer="Flores Lab", model="Gr AQ-1 half cell", format="coin", chemistry="li-ion",
    name=title_for("cell-spec", **gr),
    handle=handle_for("cell-spec", group="flores-ocv", **gr),
)
cells = ws.add(
    "cell", spec=spec,
    names=[title_for("cell", sample="063b77", **gr)],
    handles=[handle_for("cell", group="flores-ocv", sample="063b77", **gr)],
)
ws.add(
    "test", type="gitt", cell=cells[0],
    name=title_for("test", sample="063b77", method="gitt", **gr),
    handle=handle_for("test", group="flores-ocv", sample="063b77", method="gitt", **gr),
)
ws.save()
```

Cells take `handles=[...]` in parallel with `names=` and `serial_numbers=`. The record models (`CellSpec`, `Cell`, `TestSpec`, `Test`, `Dataset`) take `handle=`, and so do the builders in `battinfo.api` (`create_material_spec`, `create_component_spec`, `create_equipment`, `create_organization`, `create_parameter_set` and the rest). Draft files loaded with `ws.load()` may carry a `"handle"` key.

## Rename without moving an IRI

Several record types seed their IRI from their name, so a new title would mint a new record. When you rename something that is already published, pin its identity:

| Record | How to pin |
|---|---|
| Cell | `ws.add("cell", ..., iris=[...])`, one IRI per cell |
| Test, and the datasets made from its data files | `ws.add("test", ..., iri=...)` or `uid=...`, plus `dataset_iris=[...]` in the order of `data=` |
| Test spec drafts | an `"id"` (or `"uid"`) key in the `.test-spec.json` file |
| Material and electrode records | `uid=...` or `id=...` |
| Datasets and collections written with `battinfo.Dataset` | `Dataset(id=...)`; a collection's IRI otherwise comes from its access URL and name |

For example, rebuilding a corpus with the new titles keeps the cell and test IRIs they were published under:

```python
rebuilt = battinfo.workspace("lab-rebuilt", registry_url=None)
cell = rebuilt.add(
    "cell", spec=spec, names=["Graphite AQ-1 cell 063b77"],
    iris=["https://w3id.org/battinfo/cell/7k2m-4q8r-9tvx-3hd5"],
)[0]
test = rebuilt.add(
    "test", type="gitt", cell=cell,
    name="Graphite AQ-1 cell 063b77 GITT test",
    iri="https://w3id.org/battinfo/test/7d9k-2m4p-8t3x-6nq5",
)[0]
rebuilt.save()
print(test.id)  # https://w3id.org/battinfo/test/7d9k-2m4p-8t3x-6nq5
```

A pinned IRI must have the right namespace (`/test/` for a test, `/dataset/` for a dataset, `/spec/` for a spec), and one IRI can name only one record in a session.

## What validation checks

The schema of every record type defines `handle` with the grammar and a 120 character limit, so a handle such as `Flores OCV` or `flores_ocv/cell` fails `battinfo.validate_record_report()` with a `schema.pattern` error.

A handle that follows the grammar but does not end with its record type's kind word, such as `flores-ocv/graphite-cell` on a cell spec, gets a `semantic.handle_kind_word_expected` warning. It stays a warning under every policy, strict included: the handle is still usable, the warning only points at the convention. Collections are not checked, since they carry no kind word.

## In JSON-LD

`battinfo.record_to_jsonld()` emits the handle as one more `schema:identifier`, next to whatever identifiers the record already has:

```json
"schema:identifier": {
  "@type": "schema:PropertyValue",
  "schema:propertyID": "battinfo-handle",
  "schema:value": "flores-ocv/graphite-aq-1-063b77-cell"
}
```

The value is the bare handle. The registry workspace that makes it unique is not part of the record.
