# Build a cell from components

Describe a coin cell the way you built it: materials → electrodes →
electrolyte/separator/housing → cell spec → physical cells — every layer a
saved record, every link an IRI. This whole page is one continuous script;
run it top to bottom.

**Ingredients:** a library folder (here `my-library`) and the material specs
from [Register materials](register-materials.md). All the `create_*`/`save_*`
functions live in `battinfo.api`.

## 1. Register the parts and harvest their IRIs

Every `save_*` call returns a dict whose `"id"` is the record's permanent IRI —
capture it, it is how the next layer refers to this one:

```python
from battinfo.api import create_material_spec, save_material_spec

LAB = "my-library"

def material(name, **kw):
    return save_material_spec(create_material_spec(name=name, **kw),
                              source_root=LAB, mode="upsert")["id"]

NMC811_IRI   = material("NMC811", material_class="active_material",
                        electrode_polarity="positive", formula="LiNi0.8Mn0.1Co0.1O2")
GRAPHITE_IRI = material("Graphite", material_class="active_material",
                        electrode_polarity="negative", formula="C")
PVDF_IRI     = material("PVDF", material_class="binder", formula="(C2H2F2)n")
CB_IRI       = material("Carbon black", material_class="conductive_additive", formula="C")
LIPF6_IRI    = material("LiPF6", material_class="electrolyte_salt", formula="LiPF6")
EC_IRI       = material("EC", material_class="electrolyte_solvent", formula="C3H4O3")
EMC_IRI      = material("EMC", material_class="electrolyte_solvent", formula="C4H8O3")
```

(electrode-recipe)=
## 2. The electrodes — a 96/2/2 coating, by IRI

```python
from battinfo.api import create_component_spec, save_component_spec

cathode = create_component_spec(
    "electrode", name="NMC811 cathode 96/2/2", polarity="positive",
    body={
        "coating": {
            "component": {
                "active_material": [{"name": "NMC811", "material_spec_id": NMC811_IRI,
                                     "property": {"mass_fraction": {"value": 0.96, "unit": "1"}}}],
                "binder":   [{"name": "PVDF", "material_spec_id": PVDF_IRI,
                              "property": {"mass_fraction": {"value": 0.02, "unit": "1"}}}],
                "additive": [{"name": "Carbon black", "material_spec_id": CB_IRI,
                              "property": {"mass_fraction": {"value": 0.02, "unit": "1"}}}],
            },
            "property": {"loading":   {"value": 21, "unit": "mg/cm2"},
                         "thickness": {"value": 75, "unit": "um"}},
        },
        "current_collector": {"name": "Aluminium foil",
                              "property": {"thickness": {"value": 15, "unit": "um"}}},
    })
CATHODE_IRI = save_component_spec("electrode", cathode, source_root=LAB, mode="upsert")["id"]

anode = create_component_spec(
    "electrode", name="Graphite anode", polarity="negative",
    body={
        "coating": {
            "component": {
                "active_material": [{"name": "Graphite", "material_spec_id": GRAPHITE_IRI,
                                     "property": {"mass_fraction": {"value": 0.96, "unit": "1"}}}],
                "binder": [{"name": "PVDF", "material_spec_id": PVDF_IRI}],
            },
            "property": {"loading": {"value": 12, "unit": "mg/cm2"}},
        },
        "current_collector": {"name": "Copper foil",
                              "property": {"thickness": {"value": 10, "unit": "um"}}},
    })
ANODE_IRI = save_component_spec("electrode", anode, source_root=LAB, mode="upsert")["id"]
```

The `body=` shapes mirror the canonical examples in
[`examples/electrode-spec/`](https://github.com/BIG-MAP/BattINFO/tree/main/examples/electrode-spec)
— when in doubt, open one and copy its structure.

## 3. Electrolyte, separator, housing

```python
electrolyte = create_component_spec(
    "electrolyte", name="1M LiPF6 EC:EMC 3:7",
    body={
        "family": "organic",
        "salt": {"name": "LiPF6", "material_spec_id": LIPF6_IRI,
                 "property": {"concentration": {"value": 1.0, "unit": "mol/L"}}},
        "solvent_mixture": {"component": [
            {"name": "EC", "material_spec_id": EC_IRI,
             "property": {"volume_fraction": {"value": 0.3, "unit": "1"}}},
            {"name": "EMC", "material_spec_id": EMC_IRI,
             "property": {"volume_fraction": {"value": 0.7, "unit": "1"}}},
        ]},
    })
ELECTROLYTE_IRI = save_component_spec("electrolyte", electrolyte,
                                      source_root=LAB, mode="upsert")["id"]

separator = create_component_spec(
    "separator", name="Celgard 2325",
    body={"material": "polypropylene", "structure": "trilayer",
          "property": {"thickness": {"value": 25, "unit": "um"},
                       "porosity":  {"value": 0.39, "unit": "1"}}})
SEPARATOR_IRI = save_component_spec("separator", separator,
                                    source_root=LAB, mode="upsert")["id"]

housing = create_component_spec(
    "housing", name="CR2032 coin housing",
    body={"cell_format": "coin",
          "case": {"size_code": "2032", "material": "Stainless steel",
                   "property": {"diameter": {"value": 20, "unit": "mm"},
                                "height":   {"value": 3.2, "unit": "mm"}}}})
HOUSING_IRI = save_component_spec("housing", housing,
                                  source_root=LAB, mode="upsert")["id"]
```

> The first argument names the component family — note it goes before `name=`:
> the electrolyte's `"organic"`/`"aqueous"` classification is the `family` key
> *inside* `body=`, not a keyword argument.

## 4. The cell spec — all five references

```python
import battinfo
from battinfo.api import save_cell_spec

cell = battinfo.CellSpec(
    manufacturer="My Lab", model="COIN-NMC811-A", format="coin", chemistry="Li-ion",
    positive_electrode_spec_id=CATHODE_IRI,
    negative_electrode_spec_id=ANODE_IRI,
    electrolyte_spec_id=ELECTROLYTE_IRI,
    separator_spec_id=SEPARATOR_IRI,
    housing_spec_id=HOUSING_IRI,
    nominal_capacity={"value": 0.004, "unit": "Ah"},
    nominal_voltage={"value": 3.7, "unit": "V"},
)
CELL_IRI = save_cell_spec(cell, source_root=LAB, mode="upsert")["id"]
```

This is shipped, working behavior — the five `*_spec_id` reference fields are
part of the `CellSpec` model today, and the packaged
[example fleet](../cell-fleet.md) uses exactly this pattern. A cell may
reference components, inline them, or both (inline holders remain optional —
see [Components](../component-specs.md)).

## 5. The physical cells

```python
from battinfo.api import save_cell_instance

for name in ("B7-01", "B7-02", "B7-03"):
    save_cell_instance({"cell_spec_id": CELL_IRI, "name": name},
                       source_root=LAB, mode="upsert")
```

(For interactive batches — including printing labels — the workspace's
`ws.add("cell", spec=..., names=[...])` does the same thing; see
[Label your cells](label-your-cells.md).)

(validate-the-set)=
## 6. Validate the whole set

Save does **not** currently reject a reference to a spec that does not exist —
a typo in an IRI lands on disk silently. `validate_record_report` catches it,
so finish every build session by sweeping the library:

```python
import json
from pathlib import Path
from battinfo import validate_record_report

bad = 0
for path in sorted(Path(LAB).rglob("*.json")):
    report = validate_record_report(json.loads(path.read_text(encoding="utf-8")),
                                    source_root=LAB)
    if not report.ok:
        bad += 1
        print(f"INVALID {path.name}")
        for issue in report.issues:
            print("  -", issue.message)
print(f"{bad} invalid record(s)")   # 0 invalid record(s)
assert bad == 0
```

A dangling reference reports as `reference.missing` with the offending IRI —
fix the reference (or register the missing part) and re-run. Saves also
check references by default, so a typo normally fails at `save_*` time
before it ever lands on disk; this sweep is the belt-and-braces check over
a finished set.

## What you have now

A three-level graph on disk — cell → components → materials — where every node
is a schema-valid record with a permanent IRI, and shared parts (that binder,
that electrolyte) are registered once and referenced everywhere. The
[cell fleet page](../cell-fleet.md) shows the same pattern across the packaged
example fleet, and [Find existing records](find-existing-records.md) shows how
to query what you have built.
