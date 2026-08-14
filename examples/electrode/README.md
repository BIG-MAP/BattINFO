# Electrode Batches (Examples)

Coated electrode batches — the *instance* half of the `electrode-spec` + `electrode` pair.
Each links to its design via `electrode_spec_id` and carries the batch label, build dates,
amount/count, storage, and as-built actuals in an open `property` map (measured loading and
thickness differ from the design values on the spec, which is why the batch is its own
record). Optional characterization `datasets` link out to the data.
