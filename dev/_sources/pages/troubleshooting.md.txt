# Troubleshooting

The classic surprises, with what is actually happening and the fix. Everything
here reflects the current release; several of these edges are actively being
smoothed.

## `ws.search(...)` returns nothing

`ws.search` queries the **live registry** — only *published* records exist
there. Your own unsaved/unpublished records will never show up in search;
inspect them with `ws.list(verbose=True)` or the `query_*` functions instead
([Find existing records](../howto/find-existing-records.md)).

If you are offline (or the registry is unreachable), search prints a
"Registry unreachable" notice and falls back to a local clone of the records
repository if configured — otherwise you get an empty list. An empty result
while offline proves nothing about what exists.

## "I don't have an API key"

Reading needs no key: `ws.search`, resolving IRIs, and all local authoring
work without an account. A key (`ws.login(api_key="bk_...")`) is only needed
to **publish** to the registry (battery-genome.org). During the soft launch,
keys are granted by the registry operators — there is no self-service key
page yet; contact the Battery Genome team for publish access. `ws.status()`
also needs a login, because it asks the registry about *your* workspace.

## `ws.template("test-spec")` output won't load

Known sharp edge. The generated test-spec template currently emits shapes the
record model rejects: bare scalars where `{"value": ..., "unit": ...}` maps
are required, a `{"min": ..., "max": ...}` voltage window the model cannot
yet express, and `null` placeholders that are themselves invalid — so
`ws.load()` fails with a stack of pydantic errors even after you fill it in.

Until the template round-trip is fixed, author test specs directly in Python —
this path works today and parses plain-English steps into the structured
method:

```python
import battinfo

battinfo.save_test_spec(battinfo.TestSpec(
    name="Capacity Check - C/10 at 25 C",
    kind="capacity_check",
    experiment=["Charge at C/3 until 4.2 V", "Hold at 4.2 V until C/20",
                "Discharge at C/10 until 2.5 V"],
    conditions={"ambient_temperature": {"value": 25.0, "unit": "degC"}},
), source_root="my-library", mode="upsert")
```

Put voltage limits in the step strings (as above) rather than in a
min/max window. See [Test specs](../test-specs.md) for the full recipe.

## "Which install extra do I need?"

Each missing optional dependency raises an error naming its extra. The map:

| You want | Install |
|---|---|
| Convert raw cycler files (`ws.convert()`) + plotting | `pip install "battinfo[processing]"` |
| Read CSV/Parquet/XLSX tables (`ws.convert_csv`, dataset enrichment) | `pip install "battinfo[tabular]"` |
| RO-Crate validation when publishing | `pip install "battinfo[publish]"` |
| QR codes for cell labels | `pip install segno` (not a BattINFO extra) |

## My record's IRI opens a sign-in page

Content negotiation is doing its job. A `https://w3id.org/battinfo/...` IRI
serves **two representations**: machine clients asking for
`application/ld+json` (or `text/turtle`) get the record data — publicly, no
login; browsers get the human landing page on the Battery Genome platform,
which sits behind a sign-in gate during the soft launch. Verify the machine
path yourself:

```bash
curl -sL -H "Accept: application/ld+json" \
  https://w3id.org/battinfo/spec/27p5-216g-0vyc-98he
```

A `404 Record not found` from the resolver means the record was never
published to the registry (local records resolve only after publishing).

## Converted file is missing columns

`ws.convert_csv(path, hints=...)` renames only the columns you map; columns
it does not recognize pass through with their original names, and the BDF
validation report then lists them under `extras` (with anything required
under `missing`). If a column you care about — a capacity or step column —
shows up in `extras`, it is not mapped to the canonical vocabulary and
downstream tools will not see it.

Fix: print the canonical target names and extend `hints`:

```python
import battinfo

ws = battinfo.workspace(".")
columns = ws.bdf_columns()   # prints all canonical BDF column names
```

<!-- doc-snippet: skip -->
```python
ws.convert_csv("export.csv", hints={
    "Voltage(V)":  "voltage_volt",
    "Current(A)":  "current_ampere",
    "AhDis[Ah]":   "discharging_capacity_ah",   # map, don't lose, capacity
})
```

Treat any non-empty `extras` list on a column you measured as a red flag —
never accept a "successful" conversion without checking it.

## Validation error: date "is not of type 'integer'"

Canonical records store timestamps (`test.started_at`, `test.ended_at`,
`provenance.retrieved_at`, …) as **Unix seconds**. The authoring surfaces
(`battinfo.TestSpec(...)`, `ws.add(...)`, `create_*`) accept ISO dates like
`"2026-01-15"` and convert for you — but if you hand-edit a saved JSON record
and type an ISO string into one of these fields, schema validation rejects it
with `'2026-07-17' is not of type 'integer'`. Fix: edit through the authoring
surface, or enter the Unix timestamp. (Some fields, like a cell instance's
`manufactured_at`, are flexible and take either form — the validator error
tells you which field objected.)

## Dangling references save without complaint

`save_cell_spec` does not currently verify that a referenced
`*_spec_id` exists — a typo lands on disk silently. Run
`validate_record_report` over your library after a build session; it reports
`reference.missing` with the offending IRI. The recipe is in
{ref}`Build a cell from components <validate-the-set>`.

## Still stuck?

Open an issue at
[github.com/BIG-MAP/BattINFO/issues](https://github.com/BIG-MAP/BattINFO/issues)
with the record (or a redacted version) and the full error text — the
validators' machine-readable output is designed to be pasted.
