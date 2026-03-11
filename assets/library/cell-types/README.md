# BattINFO Cell-Type Library

This directory is for canonical reusable commercial cell-type records stored as
BattINFO battery descriptors.

Each file should:

- describe one reusable cell type
- use the battery descriptor schema
- carry the canonical reusable type IRI in `specification.id`
- retain provenance back to the source datasheet

These JSON files are the source of truth for the reusable cell-type library.

Generated RDF artifacts belong in:

- `assets/library-rdf/cell-types/`
- `ontology/library/cell-types.jsonld`
