# BattINFO Notebooks

This folder contains practical notebooks for exploring and debugging the refactor.

## Notebook Index

1. `00_setup_and_navigation.ipynb`
   - Environment/path setup and navigation.

2. `01_identifier_policy_checks.ipynb`
   - Inspect identifier policy rules and run ID lint checks.

3. `02_validation_profiles.ipynb`
   - Validate base and Battery Pass profile documents.

4. `03_mapping_json_to_jsonld.ipynb`
   - Run direct + CLI mapping and compare with golden outputs.

5. `04_cells_clean_quality.ipynb`
   - Inspect canonical `cells-clean` data quality and validation state.

6. `05_resolver_artifacts.ipynb`
   - Build and inspect resolver artifacts and `w3id` template logic.

7. `06_minting_and_instance_workflow.ipynb`
   - Create new cell-type and cell-instance records via scripts.

8. `07_query_library_features.ipynb`
   - Query cell types, instances, and datasets via both Python API and CLI with parity checks.

9. `08_create_and_link_instance.ipynb`
   - Instantiate and link resources via both Python API and CLI.

10. `09_publish_pipeline_workflow.ipynb`
   - Run an end-to-end publish pipeline via both Python API and CLI with debug-friendly logs.

## Usage Notes

- Open notebooks from repository root if possible.
- If opened from inside `notebooks/`, setup cells handle path normalization.
- Notebooks are designed to be executable without installing the package globally.
