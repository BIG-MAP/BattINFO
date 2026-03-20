# BattINFO Notebooks

This folder contains the alpha walkthrough notebooks for the supported BattINFO
scope.

Notebook status:

- aligned to the alpha test surface
- intended for onboarding, demos, and tester self-service
- executable against temporary workspace data under `.battinfo/notebooks`
- written against public BattINFO package APIs rather than repo-local helpers

## Terminology

- `Workspace`: the human-first Python authoring helper for linked BattINFO records.
- `Project`: a compatibility wrapper around one `Workspace`.
- `LocalWorkspace`: the disk-first release scaffold behind `battinfo workspace ...`, authored from JSON resource files on disk.

The onboarding notebooks now use `Workspace` directly. When they need a disk-backed
submission workspace or a registry-ready submission package, they call
`Workspace.export_submission_workspace(...)` or
`Workspace.build_submission_package(...)`, which use `LocalWorkspace` internally.

## Notebook Index

1. `01_alpha_simple_commercial_cell_walkthrough.ipynb`
   - The smallest possible BattINFO flow.
   - Generate a draft `cell-type` JSON file, load it into a `Workspace`, and canonize it into a saved BattINFO record.

2. `02_alpha_linked_records_walkthrough.ipynb`
   - The core canonical record workflow.
   - Create one `CellType`, one `Cell`, one `Test`, and one linked `Dataset`, then build publication and submission packages.

3. `03_alpha_detailed_coin_cell_descriptor_walkthrough.ipynb`
   - The richer detailed authoring workflow.
   - Describe a coin cell with electrode, electrolyte, separator, and construction details, derive a canonical `CellType`, and publish a linked dataset with the descriptor attached.

## Usage Notes

- Use the repository `.venv` kernel in VS Code.
- Install with `pip install -e .[dev]` before running the notebooks.
- Open notebooks from repository root or with that `.venv` selected as the active kernel.
- The notebooks write temporary data under `.battinfo/notebooks` and do not modify curated repository examples.
- If VS Code gets stuck on `Restarting Kernel`, shut down the notebook and run:
  `battinfo notebook recover --project-root . --format text`
  This stops repo-local `ipykernel` processes for the current `.venv` and clears `.jupyter-runtime-test` when present.

