A half cell puts one electrode under test against a counter electrode that
also serves as the potential reference — the standard bench format for
characterizing a single electrode (OCV, GITT, rate behaviour) without the
other electrode's contribution.

There is no separate record type: a half cell is a **cell** with
`cell_configuration: "half_cell"`, and its electrodes are named by **role**,
not by polarity — `working_electrode` / `counter_electrode` holders (or
their `*_spec_id` reference siblings) instead of positive/negative. The
role-based naming is deliberate: a half cell has no sides to name, and in
the working-electrode voltage convention (vs Li/Li+ for a lithium counter)
a graphite working electrode *charges* toward 1 V — polarity labels would
mislead. In a two-electrode half cell the counter also carries the
reference role; a `three_electrode_cell` separates them.

What is usually stated: the working electrode as a reference to its
[electrode spec](electrodes.md) (the design under test), and the counter
described inline on its holder — a lithium foil the lab treats as
interchangeable earns a description, not an individually tracked record.
See [electrodes — half cells name their electrodes by role](electrodes.md#half-cells-name-their-electrodes-by-role-not-by-polarity)
for the ruling, and [cells](cells.md) for everything half cells share with
full cells.
