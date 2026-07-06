# Bulk-ingest thousands of records

One `save_*` call per record re-scans the record store every time. For batches,
open a `bulk_save_session`: the id→path map is loaded once, every save keeps it
current, and re-running the same ingest is a no-op (identical identities mint
identical IRIs).

```python
import battinfo

spec = battinfo.api.save_cell_spec(
    {"manufacturer": "Acme", "model": "BULK-1", "chemistry": "Li-ion", "format": "cylindrical"},
    source_root="examples-bulk",
)

with battinfo.bulk_save_session("examples-bulk"):
    for i in range(50):
        battinfo.save_cell_instance(
            {"cell_spec_id": spec["id"], "serial_number": f"CELL-{i:04d}"},
            source_root="examples-bulk",
        )
print("50 instances saved")
```

Measured on the 400-record benchmark: 18 → 385 records/s; a 10k-record ingest
completes in about half a minute. Re-run the loop above with `mode="upsert"`
and every save reports `content_changed: False` — no duplicates, ever.

For folders of ready-made record files, `battinfo save batch --source-dir ...`
wraps the same session automatically.
