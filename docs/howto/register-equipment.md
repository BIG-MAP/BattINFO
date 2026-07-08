# Register your lab equipment and log which channel ran a test

One `ws.add("equipment", ...)` call saves the equipment-spec (the model), the
physical unit, and one channel record per slot — then any test can name its
channel and the saved test record carries `equipment_id` + `channel_id`.

**1. Register a unit.** Reuse a canonical equipment-spec record (here: the
packaged SkyRC MC3000 example). `ws.add` saves the spec into your workspace if
it is new, and channel count defaults to the spec's `channel_count`:

```python
from pathlib import Path

import battinfo

ws = battinfo.workspace()

spec_path = next(Path("examples/equipment-spec").glob("*.json"))
ws.add("equipment", spec=spec_path,
       serial_number="MC3K-2026-0001", name="Cycler 1", location="Lab B")
```

Re-running the same call is safe: equipment and channel IRIs are minted
deterministically from (spec, serial number) and (unit, index), so the records
converge instead of duplicating.

No canonical spec to reuse? Author one from a template and load it:

```python
ws.template("equipment-spec", name="...", manufacturer="...", model="...")
spec = ws.load("....equipment-spec.json")   # fill in the file first
```

**2. Attach a test to a channel.** Reference the channel by label, by
`"<unit>/CHn"`, or by its IRI — an unknown reference lists the channels it
knows about:

```python
cell_spec = battinfo.CellSpec(manufacturer="Acme", model="X-1",
                              format="cylindrical", chemistry="Li-ion")
ws.add("cell", spec=cell_spec, serial_numbers=["CELL-001"])

ws.add("test", type="cycling", cell="CELL-001", channel="Cycler 1/CH2")
ws.save()
```

The saved test record now contains the channel's `equipment_id` and
`channel_id`, so "which slot of which cycler produced this data" survives into
the published record.
