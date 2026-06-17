# JSON-LD builder consolidation

## Status — COMPLETE

All three JSON-LD graph builders are now consolidated onto a single shared,
input-agnostic builder, `AuthoringWorkspace._assemble_zenodo_jsonld` (takes canonical
`record_sets`, emits the gold-standard catalog graph):

| Builder | Entry points | Status |
|---|---|---|
| `ws.py` `_build_zenodo_jsonld` | `AuthoringWorkspace.upload` / `preview_jsonld` | ✅ thin adapter over the shared builder |
| `publication.py` `_zenodo_publication_graph` | `build_zenodo_package` / `contribute` | ✅ adapter (`_record_sets_from_zenodo_record`) over the shared builder |
| `publication.py` `_publication_graph` | `publish()` / `Workspace.publish` (local single-dataset directory) | ✅ adapter over the shared builder (local `file://` base, CSVW/DataCite/HTML preserved) |

The blocker below was resolved by **collapsing CellType into CellSpecification**: they
are the same entity (a `BatteryCellSpecification`), so the single merged spec node is
authoritative and `from_jsonld` always reconstructs a specification from it. The stale
"cell-type-only ⇒ no specification" distinction was removed.

The shared builder was also generalized to support local publication: a
`files_base_url` parameter (default `<record_url>/files`) and a DOI guard (omit
`schema:identifier` when there is no DOI). Member-dataset nodes were enriched with
FAIR/Google-Dataset-Search discoverability fields (license, keywords, version,
measurementTechnique, dates, coverage, …) read from the dataset record — this also
delivers the Tier-2 "member discoverability" goal for the Zenodo paths.

## How the round-trip was made whole

Routing `publish()` through the shared builder required `BattinfoBundle.from_jsonld`
and the builder to handle the gold-standard shape. The changes:

- **CellType ≡ CellSpecification.** `from_jsonld` treats the single
  `BatteryCellSpecification` node as both; `cell_specification` is always recovered.
- **Protocol / instrument round-trip.** Recovered from `schema:measurementTechnique`
  and `hasTestEquipment` (the gold-standard carriers), not the legacy
  `schema:description` / `schema:instrument`.
- **test→dataset link & test kind.** `from_jsonld` falls back to the reconstructed
  test for `dataset.test_id`; the builder emits the test kind as `schema:additionalType`.
- **Rich Dataset metadata** (creators, publisher, funders, citations, variableMeasured,
  CSVW `mainEntity`, …) is merged onto the shared member node from the existing
  `_dataset_jsonld_node` helper, so no shaping logic is duplicated.
- **Distributions** combine the dataset's declared distributions (which may be remote
  URLs, used verbatim) with files discovered in the directory (rewritten to
  `files_base_url`). The shared builder gained a `files_base_url` parameter and a DOI
  guard for this local case.
- **Property-map completeness.** `rated_energy` / `certified_usable_energy` were added
  to the curated property map (→ `NominalEnergy`) so quantities are not dropped.

The shared builder also gained spec-node richness (`countryOfOrigin`, `releaseDate`,
`additionalType`, `schemaVersion`) and member-dataset discoverability fields, benefiting
every path (this is the Tier-2 discoverability goal, delivered).
