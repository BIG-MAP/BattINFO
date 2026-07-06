# Library/canonical cell-spec unification — status and post-beta plan

Status: **deferred to a single post-beta effort** (decided 2026-07-05, during the beta-readiness
sweep). This note records why, and the plan to finish it later.

## Where things stand (already true)

The "one model" goal is met. `CellSpec` (`bundle.py`) is the single source of truth for a
cell specification. It serializes into two envelopes:

- **Canonical** (`cell_spec` key) — `to_record()` / `from_record()`. Schema-validated, IRI-minted,
  provenance-complete. Consumed by the publish path, the registry, the JSON-Schema gate, and SHACL
  input. This is the real record.
- **Library** (`specification` key) — `to_library_record()` / `from_library_record()`. A flatter,
  author-friendly *internal* serialization used only by the local reuse catalog
  (`save_library_cell_spec`, `query_library_cell_specs`, `build_cell_spec_library_rdf`,
  `Workspace.save_descriptions`).

The library shape is **not a rival model** — it is a second serialization of the same model. So the
original "competing models" concern is already resolved.

## Why the collapse is deferred (de-risking findings, 2026-07-05)

1. **The RDF is not shape-agnostic.** `run_mapping(canonical)` drops the `specification_comment`
   (curation notes) from the domain-battery JSON-LD that `run_mapping(specification)` keeps — a quirk
   of Builder A's (`transform/json_to_jsonld.py`) `cell_spec` normalization path. So the
   `specification` envelope must survive internally until Builder A is fixed, and fixing Builder A is
   JSON-LD-builder work (see 3B) that also changes converter/batterypass output.
2. **The whole library CRUD surface keys off `specification`.** `save_library_cell_spec`,
   `query_library_cell_specs`, `_find_library_descriptor_path_by_id`, `Workspace.save_descriptions`,
   and the `library` CLI commands all read `specification.id` / `specification.manufacturer`
   internally. Flipping the stored shape to canonical means reworking all of them + migrating files +
   updating their tests — an invasive change to a working subsystem for a largely-internal benefit.

Because (1) ties the envelope collapse to the JSON-LD builders, the envelope work and the shared
JSON-LD core (3B) are one problem, best done together.

## Beta: no code change (validation win attempted, backed out)

Adding canonical-projection validation on `save_library_cell_spec` was attempted as a small win but
backed out: it revealed that the library authoring path never applies the save-time provenance
defaults (`source_type`, etc.) that `_record_from_cell_spec` applies on the canonical path, so many
library docs' canonical projections fail schema on `provenance.source_type`. Making them valid means
adding provenance-defaulting to the library path — which is part of the deferred collapse, not a
one-liner. Folded into the post-beta plan below. For beta the library subsystem is unchanged and
`CellSpec` remains the documented single source of truth.

## Post-beta plan (one unified effort: envelope collapse + shared JSON-LD core)

The four JSON-LD builders serve four distinct output contracts and should not be merged into one;
the goal is to remove the *duplicated cell-spec→node logic*, then collapse the envelope on top:

1. Extract a shared cell-spec→JSON-LD core (vocab maps, quantity encoding, node assembly) that
   builders A (`transform/json_to_jsonld.py`), B (`jsonld.py`), and D (`api.py::_resolver_jsonld`)
   all call, so they stop drifting. Fold the Zenodo builder (C, `ws.py::_assemble_zenodo_jsonld`)
   onto B's node functions. Keep the four output targets as thin adapters. Guard with golden JSON-LD
   baselines per consumer (SHACL, publish, converter, batterypass, Zenodo).
2. With the shared core mapping canonical directly (and preserving the curation-comment behavior),
   flip the library's *stored* shape to canonical: rework `save_library_cell_spec` /
   `query_library_cell_specs` / `_find_library_descriptor_path_by_id` / `Workspace.save_descriptions`
   / the CLI to key off `cell_spec`; add save-time provenance defaulting to the library path (it
   currently omits `provenance.source_type`, so canonical projections fail schema — see the backed-out
   validation attempt above); migrate the packaged `data/library/cell-spec/*.json`; keep
   `from_library_record` / `from_path` as a read adapter for legacy files. Guard with a
   `build_cell_spec_library_rdf` golden baseline.

Verification tooling already scoped: golden-baseline harnesses for the library RDF output and for
per-consumer JSON-LD exist in the sweep's scratch work and should be lifted into `tests/`.
