# Fix the five classic validation errors

Every error names its fix. These are the five you will actually meet, with the
message you get and the line that resolves it.

**1. A typo'd field**

```python
import battinfo

try:
    battinfo.CellSpecification(manufacture="Acme", model="X", format="coin", chemistry="Li-ion")
except TypeError as exc:
    print(exc)  # Unknown field(s), with a did-you-mean for manufacturer=
```

**2. A bare-number quantity** — quantities are objects, units are never implicit:

```python
spec = battinfo.CellSpecification(
    manufacturer="Acme", model="X", format="coin", chemistry="Li-ion",
    nominal_capacity={"value": 2.5, "unit": "Ah"},   # not nominal_capacity=2.5
)
print(spec.nominal_capacity)
```

**3. An invalid test kind**

```python
try:
    battinfo.TestSpec(name="t", kind="cycle_life")
except Exception as exc:
    print(str(exc)[:120])  # lists the valid kinds; use "cycling"
```

**4. `specs=` as a list** — it is a mapping of property name to value:

```python
try:
    battinfo.CellSpecification(
        manufacturer="Acme", model="X", format="coin", chemistry="Li-ion",
        specs=[("nominal_voltage", 3.0)],
    )
except TypeError as exc:
    print(exc)
```

**5. A dataset without a URL** — schema requires a resolvable location:

```python
ds = battinfo.Dataset(
    name="No URL yet",
    id="https://w3id.org/battinfo/dataset/1f8r-6v2k-9p4m-3t7x",
    cell_instance_id="https://w3id.org/battinfo/cell/3m6k-9t2p-7x4h-9nq8",
)
try:
    ds.to_record()
except ValueError as exc:
    print(str(exc)[:120])  # set access_url= to the landing page or download URL
```

Check any record in the browser at [battinfo.org/validate](https://battinfo.org/validate) —
it runs the same canonical schemas as `battinfo validate` and the registry.
