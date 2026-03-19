# BattINFO Notebooks

This folder contains the alpha walkthrough notebooks for the supported BattINFO
scope.

Notebook status:

- aligned to the alpha test surface
- intended for onboarding, demos, and tester self-service
- executable against temporary workspace data under `.battinfo/notebooks`
- written against public BattINFO package APIs rather than repo-local helpers

## Notebook Index

1. `01_alpha_simple_commercial_cell_walkthrough.ipynb`
   - Start with the BattINFO hello-world flow for first-time users.
   - Create one `BatteryCellType`, one `BatteryCell`, one test, and one linked dataset with the high-level public API.
   - Publish the dataset to JSON-LD and emit the registry-ready intake bundle.

## Usage Notes

- Use the repository `.venv` kernel in VS Code.
- Install with `pip install -e .[dev]` before running the notebooks.
- Open notebooks from repository root or with that `.venv` selected as the active kernel.
- The notebooks write temporary data under `.battinfo/notebooks` and do not modify curated repository examples.
- If VS Code gets stuck on `Restarting Kernel`, shut down the notebook and run:
  `battinfo notebook recover --project-root . --format text`
  This stops repo-local `ipykernel` processes for the current `.venv` and clears `.jupyter-runtime-test` when present.

