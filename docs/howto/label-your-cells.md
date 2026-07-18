# Label your cells — names, serials, and QR codes

## Names vs. serial numbers

- **`names=[...]`** — *your* identity for a cell: the marker-pen label, the
  batch ID, "B7-01". This is the primary identifier for lab-built cells,
  which have no serial number.
- **`serial_numbers=[...]`** — the *manufacturer's* identity, printed on the
  wrapper of a commercial cell. Only use it for that; do not invent serials
  for cells you built.

Use either, or both in parallel (same length, matched by position):

```python
import battinfo

ws = battinfo.workspace(".")
spec = battinfo.CellSpec(manufacturer="My Lab", model="COIN-NMC811-A",
                         format="coin", chemistry="Li-ion")

# lab-built coin cells: names only
cells = ws.add("cell", spec=spec, names=["B7-01", "B7-02", "B7-03"])

# commercial cells: manufacturer serials, plus your own shelf label
bought = ws.add("cell", spec=spec, names=["shelf-A-04"],
                serial_numbers=["INR-9F3K72"])

ws.save()   # mints one permanent IRI per cell
```

## What goes on the label

After `ws.save()` each cell object carries its permanent IRI; the last path
segment is the cell's UID and its first six characters (dashes dropped) are
the `short_id` — the thing to write on the cell when a full IRI will not fit:

```python
for cell in cells:
    uid = cell.id.rsplit("/", 1)[-1]          # e.g. gm6p-mrc6-p6cc-0m18
    short_id = uid.replace("-", "")[:6]       # e.g. gm6pmr
    print(f"{cell.name}: {short_id}   {cell.id}")
```

The UID alphabet deliberately omits `i`, `l`, `o`, and `u`, so a handwritten
short ID survives being read back from a photo
([Identifiers](../identifiers.md)). The short ID also does real work later:
name your data files after it and `ws.add("test", datasets="glob")` matches
files to cells automatically.

## QR codes

A QR code holding the cell IRI turns any phone camera into a record lookup.
[segno](https://pypi.org/project/segno/) is a one-file QR library — it is not
a BattINFO dependency, so install it separately (`pip install segno`):

<!-- doc-snippet: skip -->
```python
import segno

for cell in cells:
    qr = segno.make(cell.id, error="m")            # the IRI is the payload
    qr.save(f"{cell.name}-qr.png", scale=6)        # or .svg for vector labels
```

Print the PNG/SVG next to the name and short ID. Scanning resolves the IRI
through `w3id.org`: machine clients get the record as JSON-LD; a browser
lands on the cell's registry page (behind the sign-in gate while the platform
is in soft launch — see [Identifiers](../identifiers.md)).

> **Printable label sheets:** the Battery Genome platform
> ([battery-genome.org](https://www.battery-genome.org)) generates printable
> QR sheets for registered cells, so you do not have to lay out labels
> yourself.
