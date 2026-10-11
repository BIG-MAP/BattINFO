# Parameter Set (Examples)

Parameter claims from one source, in two flavours, both minted under the shared `spec/` namespace.

A claim batch is one source (a paper, a lab fit) making parameter claims about one target: a curated material kind, a material spec, or a cell spec. Claims collate under the target across sources, and the spread between sources is data. Its uid derives from (target, scope, name), so re-importing a source is idempotent. Example: `Chen 2020 - graphite`.

A parameter file is one BPX file on one record: every value grouped by part (cell, each electrode's material and build, separator, electrolyte, state), the `User-defined` block as the annex, and the file itself under `distributions`. Its uid derives from the digest of the file's RFC 8785 canonical form, stored as `parameters_sha256`. The five `BPX ...` records are the FaradayInstitution/BPX examples (MIT licence, (c) 2022 University of Oxford), each marked `virtual_cell` because no real cell record stands behind it, with its source pinned to a commit of that repository.
