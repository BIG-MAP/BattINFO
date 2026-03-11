# BattINFO Notebooks

This folder now contains the four notebooks that are intended to onboard new
users to the current stable BattINFO workflow.

Notebook status:

- preview scope for alpha testing
- useful for onboarding and examples
- not part of the frozen core alpha contract

## Notebook Index

1. `01_cr2032_publication_quickstart.ipynb`
   - The shortest useful BattINFO walkthrough.
   - Build a `CellType -> CellInstance -> Test -> Dataset` chain in Python.
   - Publish `battinfo.publish.jsonld` and reload it with `load_publication(...)`.

2. `02_detailed_cell_specification_walkthrough.ipynb`
   - Use the richer `A123__ANR26650M1-B` library example.
   - Inspect positive/negative electrodes, coating components, electrolyte, and separator metadata.
   - Show how a rich `CellSpecification` can be reduced into a lighter public `CellType`.

3. `03_rich_python_api_construction.ipynb`
   - Build a rich `CellSpecification` directly in Python.
   - Create the public `CellType`, `CellInstance`, `Test`, and `Dataset` objects in code.
   - Publish and reload the resulting `battinfo.publish.jsonld` artifact.

4. `04_rich_dict_first_construction.ipynb`
   - Build the same kind of rich engineering example with plain Python dictionaries.
   - Derive the public `CellType` from that dict-first specification record.
   - Publish and reload the resulting `battinfo.publish.jsonld` artifact.

## Why The Set Was Reduced

Earlier notebooks were useful during refactors and API exploration, but they
mixed onboarding with maintenance and transitional workflows. The current set
keeps one notebook focused on the core publication path, one on richer
specification content, one on building that richer example directly in Python,
and one on a dict-first style that delays BattINFO object construction until
the boundary where it is needed.

## Usage Notes

- Use the repository `.venv` kernel in VS Code.
- The publication review notebook now assumes `battinfo` is importable directly from that environment.
- Open notebooks from repository root or with that `.venv` selected as the active kernel.
