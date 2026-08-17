# Parameter Set (Examples)

Claim batches: one source (paper, BPX file, lab fit) making parameter claims about one target (a curated material kind, a material spec, or a cell spec). Claims collate under the target across sources; the spread between sources is data. Mints under the shared `spec/` namespace with a uid derived from (target, scope, name), so re-importing a source is idempotent.
