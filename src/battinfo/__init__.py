"""BattINFO — the semantic data layer for battery technology.

The curated public surface is the ~34 names in ``__all__``: the record models,
the workspace, publish/save/query/validate, and the JSON-LD transform.
Everything else lives in its home module (``battinfo.api``,
``battinfo.interop``, ``battinfo.metadata``, …) and remains importable from
the top level for one release with a ``DeprecationWarning`` pointing there.
"""

from battinfo._publish import PublishResult, publish
from battinfo._workspace import q, quantity
from battinfo.api import (
    bulk_save_session,
    query_cell_instances,
    query_cell_specs,
    query_datasets,
    query_test_specs,
    query_tests,
    save_batch,
    save_cell_instance,
    save_cell_spec,
    save_dataset,
    save_record,
    save_test,
    save_test_spec,
)
from battinfo.bundle import BattinfoBundle, Cell, CellSpec, Dataset, ProvenanceInfo, Test, TestSpec
from battinfo.bundle_generated import SpecValue
from battinfo.jsonld import record_to_jsonld
from battinfo.publication import build_publication_package, load_publication_package
from battinfo.publication import publish as publish_publication_package
from battinfo.validate import validate_record, validate_record_report
from battinfo.ws import AuthoringWorkspace, workspace

__version__ = "0.7.0"

__all__ = [
    "__version__",
    "AuthoringWorkspace",
    "BattinfoBundle",
    "Cell",
    "CellSpec",
    "Dataset",
    "ProvenanceInfo",
    "PublishResult",
    "SpecValue",
    "Test",
    "TestSpec",
    "build_publication_package",
    "bulk_save_session",
    "load_publication_package",
    "publish",
    "publish_publication_package",
    "q",
    "quantity",
    "query_cell_instances",
    "query_cell_specs",
    "query_datasets",
    "query_test_specs",
    "query_tests",
    "record_to_jsonld",
    "save_batch",
    "save_cell_instance",
    "save_cell_spec",
    "save_dataset",
    "save_record",
    "save_test",
    "save_test_spec",
    "validate_record",
    "validate_record_report",
    "workspace",
]

# ── Off-surface names: importable for one release with a pointer to their home ──
_LAZY_EXPORTS: dict[str, str] = {
    "BatchImportResult": "battinfo.interop",
    "BattdatImportResult": "battinfo.interop",
    "BatteryTestType": "battinfo.bundle",
    "BdcImportPackage": "battinfo.interop",
    "BdcRecordImport": "battinfo.interop",
    "BillOfMaterials": "battinfo.bundle",
    "BpxExportResult": "battinfo.interop",
    "BpxImportResult": "battinfo.interop",
    "Case": "battinfo.bundle",
    "CellConstruction": "battinfo.bundle",
    "CellProductType": "battinfo.bundle",
    "ChecksumInfo": "battinfo.bundle",
    "Coating": "battinfo.bundle",
    "Conformance": "battinfo.bundle",
    "ConverterImportPackage": "battinfo.interop",
    "ConverterImportResult": "battinfo.interop",
    "CurrentCollector": "battinfo.bundle",
    "CurrentCollectorTab": "battinfo.bundle",
    "DEVIATION_CATEGORIES": "battinfo.bundle",
    "Deviation": "battinfo.bundle",
    "DiscoveryCell": "battinfo.interop",
    "DiscoveryImportPackage": "battinfo.interop",
    "Electrode": "battinfo.bundle",
    "Electrolyte": "battinfo.bundle",
    "HardwarePart": "battinfo.bundle",
    "Housing": "battinfo.bundle",
    "LocalWorkspace": "battinfo.local_workspace",
    "MaterialComponent": "battinfo.bundle",
    "MaterialInput": "battinfo.api",
    "MaterialSpecInput": "battinfo.api",
    "PropertySet": "battinfo.bundle",
    "ProtocolInfo": "battinfo.bundle",
    "Salt": "battinfo.bundle",
    "Seal": "battinfo.bundle",
    "Separator": "battinfo.bundle",
    "SolidStateImportResult": "battinfo.interop",
    "SolventMixture": "battinfo.bundle",
    "SpecSet": "battinfo.bundle_generated",
    "TableColumn": "battinfo.metadata",
    "TableSchema": "battinfo.metadata",
    "Terminal": "battinfo.bundle",
    "TestConformance": "battinfo.bundle",
    "ValidationIssue": "battinfo.validate",
    "ValidationPolicy": "battinfo.validate",
    "ValidationReport": "battinfo.validate",
    "ValidationResult": "battinfo.validate",
    "ZenodoCellRecord": "battinfo.bundle",
    "ZenodoClient": "battinfo.zenodo",
    "ZenodoDatasetEntry": "battinfo.bundle",
    "ZenodoError": "battinfo.zenodo",
    "batch_import_bdc": "battinfo.interop",
    "batch_import_converter_directory": "battinfo.interop",
    "batch_import_solid_state_db": "battinfo.interop",
    "bom": "battinfo.authoring",
    "build_cell_spec_library_rdf": "battinfo.api",
    "build_curated_cell_spec_submission": "battinfo.api",
    "build_index": "battinfo.api",
    "build_ingest_workspace": "battinfo.ingest",
    "build_zenodo_package": "battinfo.publication",
    "bundle_to_schema": "battinfo.bundle_adapter",
    "case": "battinfo.authoring",
    "cell_description": "battinfo.authoring",
    "cell_spec_to_schema": "battinfo.bundle_adapter",
    "checksum": "battinfo.metadata",
    "component_spec_from_holder": "battinfo.components",
    "construction": "battinfo.authoring",
    "create_cell_instance": "battinfo.api",
    "create_component_instance": "battinfo.api",
    "create_component_spec": "battinfo.api",
    "create_material": "battinfo.api",
    "create_material_spec": "battinfo.api",
    "csvw_table": "battinfo.metadata",
    "csvw_table_group": "battinfo.metadata",
    "data_catalog": "battinfo.metadata",
    "derive_cell_spec": "battinfo.publication",
    "distribution": "battinfo.metadata",
    "electrode": "battinfo.authoring",
    "electrolyte_recipe": "battinfo.authoring",
    "enrich_tabular_dataset": "battinfo.metadata",
    "extract_component_specs": "battinfo.components",
    "extract_material_specs": "battinfo.materials",
    "file_distribution": "battinfo.metadata",
    "from_battdat": "battinfo.interop",
    "from_bpx": "battinfo.interop",
    "from_solid_state_db_row": "battinfo.interop",
    "hardware_part": "battinfo.authoring",
    "housing": "battinfo.authoring",
    "import_aurora_unicycler": "battinfo.interop",
    "import_bdc_record": "battinfo.interop",
    "import_bmgen_jsonld": "battinfo.interop",
    "import_converter_jsonld": "battinfo.interop",
    "import_converter_jsonld_record": "battinfo.interop",
    "import_converter_package": "battinfo.interop",
    "import_dataset_record": "battinfo.interop",
    "import_discovery_eln": "battinfo.interop",
    "import_discovery_xlsx": "battinfo.interop",
    "import_pybamm_experiment": "battinfo.interop",
    "index_stats": "battinfo.api",
    "infer_variable_measured": "battinfo.metadata",
    "inspect_ingest_root": "battinfo.ingest",
    "iter_solid_state_records": "battinfo.interop",
    "link_component_to_spec": "battinfo.materials",
    "load_cell_specification": "battinfo.bundle",
    "load_publication": "battinfo.publication",
    "material": "battinfo.authoring",
    "material_spec_from_component": "battinfo.materials",
    "measured_variable": "battinfo.metadata",
    "organization": "battinfo.metadata",
    "patch_zenodo_urls": "battinfo.zenodo",
    "person": "battinfo.metadata",
    "promote_staging_cell_spec": "battinfo.api",
    "promote_staging_cell_specs": "battinfo.api",
    "properties": "battinfo.authoring",
    "publish_batch": "battinfo.api",
    "publish_cr2032_dataset_metadata": "battinfo.publication",
    "publish_curated_cell_spec": "battinfo.api",
    "publish_dataset_metadata": "battinfo.publication",
    "publish_ingest_workspace": "battinfo.ingest",
    "publish_record": "battinfo.api",
    "query": "battinfo.api",
    "query_component_instances": "battinfo.api",
    "query_component_specs": "battinfo.api",
    "query_library_cell_specs": "battinfo.api",
    "query_material_specs": "battinfo.api",
    "query_materials": "battinfo.api",
    "recover_notebook_runtime": "battinfo.runtime",
    "resolve_cell_spec_id": "battinfo.api",
    "run_demo_pipeline": "battinfo.demo",
    "save_bpx": "battinfo.interop",
    "save_component_instance": "battinfo.api",
    "save_component_spec": "battinfo.api",
    "save_library_cell_spec": "battinfo.api",
    "save_material": "battinfo.api",
    "save_material_spec": "battinfo.api",
    "save_publication_html": "battinfo.publication",
    "seal": "battinfo.authoring",
    "separator_spec": "battinfo.authoring",
    "setup_demo_environment": "battinfo.demo",
    "source": "battinfo.authoring",
    "specs_to_specset": "battinfo.bundle_adapter",
    "specset_to_specs": "battinfo.bundle_adapter",
    "submit_publication_package": "battinfo.api",
    "tab": "battinfo.authoring",
    "template_cell_instance": "battinfo.api",
    "template_cell_spec": "battinfo.api",
    "template_cell_spec_draft": "battinfo.api",
    "template_component_instance": "battinfo.api",
    "template_component_spec": "battinfo.api",
    "template_dataset": "battinfo.api",
    "template_library_cell_spec": "battinfo.api",
    "template_material": "battinfo.api",
    "template_material_spec": "battinfo.api",
    "template_test": "battinfo.api",
    "template_test_spec": "battinfo.api",
    "template_test_spec_draft": "battinfo.api",
    "terminal": "battinfo.authoring",
    "to_bdc_record": "battinfo.interop",
    "to_bpx": "battinfo.interop",
    "upload_zenodo_package": "battinfo.zenodo",
    "validate_jsonld": "battinfo.ws",
    "validate_shacl": "battinfo.validate",
    "validate_shacl_report": "battinfo.validate",
    "validate_staging_cell_spec": "battinfo.api",
    "validate_staging_cell_specs": "battinfo.api",
    "write_ingest_manifest": "battinfo.ingest",
}

# ── Retired names: resolve with a DeprecationWarning naming the replacement ──
_DEPRECATED_ALIASES: dict[str, tuple[str, object]] = {
    # Pre-0.8 long-form class names (renamed to the consistent short scheme).
    "CellSpecification": ("CellSpec", CellSpec),
    "CellInstance": ("Cell", Cell),
    # Legacy spelling aliases.
    "BatteryCellSpecification": ("CellSpec", CellSpec),
    "BatteryCell": ("Cell", Cell),
    "TestProtocol": ("TestSpec", TestSpec),
    # Retired *Input DTOs from the model consolidation.
    "CellSpecificationInput": ("CellSpec", CellSpec),
    "CellInstanceInput": ("Cell", Cell),
    "TestInput": ("Test", Test),
    "DatasetInput": ("Dataset", Dataset),
    "TestSpecInput": ("TestSpec", TestSpec),
    "TestProtocolInput": ("TestSpec", TestSpec),
}


def __getattr__(name: str) -> object:
    """PEP 562: retired and off-surface names resolve with a DeprecationWarning."""
    import warnings

    if name in _DEPRECATED_ALIASES:
        replacement, target = _DEPRECATED_ALIASES[name]
        warnings.warn(
            f"battinfo.{name} is retired; use battinfo.{replacement} — same authoring "
            f"field names. This alias will be removed one release after 0.8.",
            DeprecationWarning,
            stacklevel=2,
        )
        return target

    if name == "Workspace":
        warnings.warn(
            "battinfo.Workspace is the internal object-graph engine behind "
            "battinfo.workspace(); author through workspace() or the record "
            "models + publish(). If you really need the engine, import "
            "battinfo._workspace.Workspace. The top-level name will be removed "
            "one release after 0.8.",
            DeprecationWarning,
            stacklevel=2,
        )
        from battinfo._workspace import Workspace

        return Workspace

    if name in _LAZY_EXPORTS:
        module_name = _LAZY_EXPORTS[name]
        warnings.warn(
            f"battinfo.{name} is moving off the curated top level; import it from "
            f"{module_name} instead. Top-level access is kept for one release after 0.8.",
            DeprecationWarning,
            stacklevel=2,
        )
        import importlib

        value = getattr(importlib.import_module(module_name), name)
        globals()[name] = value  # cache: warn once per name
        return value

    # Generated per-family component wrappers (create_electrode_spec, …).
    from battinfo import api as _api

    if name in _api._COMPONENT_WRAPPER_NAMES:
        warnings.warn(
            f"battinfo.{name} is moving off the curated top level; use battinfo.api.{name} "
            f"(or the generic create/save/query component functions in battinfo.api).",
            DeprecationWarning,
            stacklevel=2,
        )
        value = getattr(_api, name)
        globals()[name] = value
        return value

    raise AttributeError(f"module 'battinfo' has no attribute {name!r}")


def __dir__() -> list[str]:
    from battinfo import api as _api

    return sorted(
        set(__all__) | set(_LAZY_EXPORTS) | set(_DEPRECATED_ALIASES)
        | set(_api._COMPONENT_WRAPPER_NAMES) | {"Workspace"}
    )
