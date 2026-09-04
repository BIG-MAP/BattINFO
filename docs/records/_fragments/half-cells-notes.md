**Why role, not polarity.** In the working-electrode voltage convention (vs Li/Li+ for a lithium counter) a graphite working electrode *charges* toward 1 V — the polarity labels of a full cell would mislead, so a half cell has no sides to name. The role-based holders are the ruling, not a convenience.

**What is usually stated.** The working electrode as a reference to its [electrode spec](electrodes.md) — the design under test; the counter described inline on its holder, because a lithium foil the lab treats as interchangeable earns a description, not an individually tracked record.

**Emission.** The described device types as `HalfCellDevice`; the working electrode emits under `hasWorkingElectrode`; in a two-electrode half cell the counter node types as both `CounterElectrode` and `ReferenceElectrode`.
