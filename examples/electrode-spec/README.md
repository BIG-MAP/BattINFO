# Electrode Specs (Examples)

Designed electrodes — the *spec* half of the `electrode-spec` + `electrode` pair. Each
names its active material's `kind`, references the powder's `material-spec` by IRI where it
is known, and describes a coating (active + binder + conductive additive, with weight
fractions) on a current collector, plus design values (loading, thicknesses, areal
capacity). Most are grounded in the DIGIBAT Discovery-Benchmark coin cells (NMC811 cathode,
graphite anode; Canrud).

The Si-Gr pair (`grade: AQ` and `grade: NMP`) is a synthetic illustration of the identity
rule: same recipe and loading, two processing routes, two IRIs — for an electrode the route
is a design decision, so it is part of the spec identity.
