"""Public battinfo API facade.

The former 5,400-line monolithic ``battinfo/api.py`` is now a package; this
module re-exports its ENTIRE pre-split surface — the public names in
``__all__`` plus the underscore helpers that other battinfo modules, tools,
and tests import — so ``from battinfo.api import X`` and ``battinfo.api.X``
keep working for every name that worked before the split.

Layout (private submodules; import from ``battinfo.api``, not from them):

- ``_shared``     — constants, IRI regexes, cross-cutting validation/ID helpers
- ``_templates``  — ``template_*`` draft builders
- ``_staging``    — staging validate/promote + curated submission builders
- ``_registry``   — registry HTTP client (``submit_publication_package``,
  ``RegistryError`` family)
- ``_records``    — ``save_*``/``query_*`` record-store operations
- ``_resolver``   — ``publish_record``/``publish_batch`` + resolver JSON-LD/HTML
  artifact building
- ``_components`` — materials/component families + generated per-family wrappers
- ``_equipment``  — equipment/channel families (IDENTIFIER_POLICY 6.1)
- ``_index``      — ``build_index``/``index_stats``

Truly shared helpers live one level up in ``battinfo._util`` and
``battinfo._emmo_instruments``.
"""
from __future__ import annotations

import difflib
import functools
import html
import json
import math
import re
import secrets
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

import battinfo.api._components as _components_mod
from battinfo._emmo_instruments import (
    _INSTRUMENT_EMMO_MAP,
    _instrument_emmo_type,
    _instrument_node,
)
from battinfo._jsonio import read_record_json as _load_json
from battinfo._jsonio import write_json as _write_json
from battinfo._record_index import active_record_cache, bulk_save_session
from battinfo._util import (
    _DOI_LITERAL_RE,
    _DOI_URL_RE,
    _as_path,
    _citation_doi_from_url,
    _citation_url_value,
    _now_iso,
    _now_unix,
)
from battinfo.api._components import (
    _COMPONENT_WRAPPER_NAMES,
    MaterialInput,
    MaterialSpecInput,
    _org_value,
    _query_component,
    _record_from_component_instance,
    _record_from_component_spec,
    _record_from_material,
    _record_from_material_spec,
    _save_component,
    create_component_instance,
    create_component_spec,
    create_material,
    create_material_spec,
    query_component_instances,
    query_component_specs,
    query_material_specs,
    query_materials,
    save_component_instance,
    save_component_spec,
    save_material,
    save_material_spec,
    template_component_instance,
    template_component_spec,
    template_material,
    template_material_spec,
)
from battinfo.api._equipment import (
    _record_from_channel,
    _record_from_equipment,
    _record_from_equipment_spec,
    create_channel,
    create_equipment,
    create_equipment_spec,
)
from battinfo.api._index import (
    build_index,
    index_stats,
)
from battinfo.api._records import (
    _COMPONENT_SPEC_REF_NAMESPACES,
    _LIBRARY_SPEC_OPTIONAL_FIELDS,
    _assert_id_matches_uid,
    _candidate_types_for_namespace,
    _cell_spec_record_to_library_format,
    _find_library_descriptor_path_by_id,
    _find_record_path_by_id,
    _identity_minted_uid,
    _iter_entity_files,
    _library_cell_spec_filename,
    _library_record_from_input,
    _library_token,
    _matches_facets,
    _mint_cell_spec_record,
    _record_content_differs,
    _record_from_cell_instance,
    _record_from_cell_spec,
    _record_from_dataset,
    _record_from_test,
    _record_from_test_protocol,
    _resolve_references_for_save,
    _save_entity_path,
    _seed_part,
    _sync_library_packaged_copy,
    _validate_cell_specification,
    _validate_duplicate_policy,
    _validate_save_mode,
    build_cell_spec_library_rdf,
    create_cell_instance,
    query,
    query_cell_instances,
    query_cell_specs,
    query_datasets,
    query_library_cell_specs,
    query_test_specs,
    query_tests,
    resolve_cell_spec_id,
    save_batch,
    save_cell_instance,
    save_cell_spec,
    save_dataset,
    save_library_cell_spec,
    save_record,
    save_test,
    save_test_spec,
)
from battinfo.api._registry import (
    _REGISTRY_ERROR_BODY_LIMIT,
    _REGISTRY_REJECTED_BODY_STATUS,
    _REGISTRY_RETRYABLE_STATUS,
    _SECRET_TOKEN_RE,
    RegistryClientError,
    RegistryError,
    RegistryTransientError,
    _scrub_secret,
    publish_curated_cell_spec,
    submit_publication_package,
)
from battinfo.api._resolver import (
    _PYBAMM_STEP_EMMO_PATTERNS,
    _pybamm_step_emmo_type,
    _pybamm_step_to_jsonld,
    _resolver_html,
    _resolver_jsonld,
    _schema_agent_value,
    _schema_citation_value,
    _schema_data_catalog_value,
    _schema_distribution_value,
    _schema_identifier_value,
    _schema_main_entity_value,
    _schema_table_column_value,
    _schema_table_schema_value,
    _schema_variable_measured_value,
    publish_batch,
    publish_record,
)
from battinfo.api._shared import (
    _UID_TAIL,
    CELL_IRI_RE,
    CELL_SPEC_IRI_RE,
    DATASET_IRI_RE,
    DEFAULT_CELL_INSTANCES_DIR,
    DEFAULT_CELL_TYPES_DIR,
    DEFAULT_DATASETS_DIR,
    DEFAULT_INDEX_SOURCE_ROOT,
    DEFAULT_LIBRARY_AGGREGATE_JSONLD,
    DEFAULT_LIBRARY_CELL_TYPES_DIR,
    DEFAULT_LIBRARY_MANIFEST_JSON,
    DEFAULT_LIBRARY_RDF_CELL_TYPES_DIR,
    DEFAULT_MATERIAL_SPECS_DIR,
    DEFAULT_MATERIALS_DIR,
    DEFAULT_PACKAGED_LIBRARY_CELL_TYPES_DIR,
    DEFAULT_PUBLISH_SOURCES,
    DEFAULT_REGISTRATION_SOURCE_ROOT,
    DEFAULT_TEST_PROTOCOLS_DIR,
    DEFAULT_TESTS_DIR,
    DUPLICATE_POLICIES,
    DUPLICATE_POLICY_ERROR,
    DUPLICATE_POLICY_RETURN_EXISTING,
    EXAMPLES_ROOT,
    MATERIAL_IRI_RE,
    MATERIAL_SPEC_IRI_RE,
    PACKAGE_ROOT,
    REGISTER_MODE_CREATE_ONLY,
    REGISTER_MODE_UPSERT,
    REGISTER_MODES,
    SCHEMAS_ROOT,
    SPEC_IRI_RE,
    TEMPLATE_CELL_ID,
    TEMPLATE_CELL_SPEC_ID,
    TEMPLATE_UID,
    TEST_IRI_RE,
    TEST_PROTOCOL_IRI_RE,
    UID_ALPHABET,
    UID_DASHED_RE,
    UID_UNDASHED_RE,
    PathLike,
    TestKind,
    _comment_list,
    _component_iri_re,
    _editorial_date_token,
    _editorial_record_id,
    _entity_id,
    _entity_schema_rel_path,
    _in_range,
    _iri_tail,
    _iter_json_files,
    _logical_entity_type_from_doc,
    _normalized_dashed_uid,
    _paginate,
    _quantity_numeric_value,
    _relative_or_absolute,
    _resolved_retrieved_at,
    _resolved_time,
    _short_id_from_iri,
    _spec_numeric_value,
    _str_contains,
    _str_eq,
    _str_fuzzy_match,
    _to_unix_time,
    _validate_canonical_record,
    _validate_publication_artifact,
    _validate_schema,
)
from battinfo.api._staging import (
    _curated_cell_spec_source,
    _curated_cell_spec_submission_resource,
    _curated_cell_spec_title,
    _dataset_record_id,
    _existing_curated_cell_spec_id,
    _staging_cell_spec_identity,
    _staging_cell_spec_input,
    _staging_dataset_identity,
    _staging_dataset_input,
    build_curated_cell_spec_submission,
    build_submission_envelope,
    promote_staging_cell_spec,
    promote_staging_cell_specs,
    promote_staging_dataset,
    promote_staging_datasets,
    validate_staging_cell_spec,
    validate_staging_cell_specs,
    validate_staging_dataset,
    validate_staging_datasets,
)
from battinfo.api._templates import (
    _draft_specs_for_format,
    template_cell_instance,
    template_cell_spec,
    template_cell_spec_draft,
    template_dataset,
    template_library_cell_spec,
    template_test,
    template_test_spec,
    template_test_spec_draft,
)
from battinfo.bundle import (
    SCHEMA_VERSION,
    BatteryTestType,
    Cell,
    CellSpec,
    Dataset,
    Test,
    TestSpec,
    stamp_provenance,
)
from battinfo.canonical_aliases import record_to_snake_aliases
from battinfo.entities import (
    COMPONENT_FAMILIES,
    ENTITY_KINDS,
    entity_id_from_doc,
    entity_types_for_namespace,
    iter_entity_files,
    kind_for_doc,
    save_entity_path,
)
from battinfo.transform.json_to_jsonld import _descriptor_quantity_node as _jsonld_quantity_node
from battinfo.validate.core import DEFAULT_POLICY, ValidationPolicy
from battinfo.validate.friendly import format_report_errors
from battinfo.validate.publication import validate_publication_report
from battinfo.validate.pydantic import validate_json
from battinfo.validate.record import validate_record, validate_record_report
from battinfo.validate.references import validate_references_report
from battinfo.validate.schema import validate_schema_data
from battinfo.workflows.map import run_mapping

# Re-export the dynamically generated per-family component wrappers
# (create_electrode_spec, query_electrode_specs, ...) exactly as the
# monolithic module exposed them.
for _wrapper_name in _COMPONENT_WRAPPER_NAMES:
    globals()[_wrapper_name] = getattr(_components_mod, _wrapper_name)




__all__ = [
    "RegistryError",
    "RegistryClientError",
    "RegistryTransientError",
    "MaterialSpecInput",
    "MaterialInput",
    "create_material_spec",
    "create_material",
    "save_material_spec",
    "save_material",
    "query_material_specs",
    "query_materials",
    "template_material_spec",
    "template_material",
    "create_component_spec",
    "create_component_instance",
    "create_equipment_spec",
    "create_equipment",
    "create_channel",
    "save_component_spec",
    "save_component_instance",
    "query_component_specs",
    "query_component_instances",
    "template_component_spec",
    "template_component_instance",
    "build_cell_spec_library_rdf",
    "build_index",
    "build_curated_cell_spec_submission",
    "create_cell_instance",
    "index_stats",
    "publish_curated_cell_spec",
    "publish_batch",
    "publish_record",
    "promote_staging_cell_spec",
    "promote_staging_cell_specs",
    "promote_staging_dataset",
    "promote_staging_datasets",
    "query",
    "query_cell_instances",
    "query_library_cell_specs",
    "query_cell_specs",
    "query_datasets",
    "query_test_specs",
    "query_tests",
    "save_batch",
    "save_cell_instance",
    "save_cell_spec",
    "save_dataset",
    "save_library_cell_spec",
    "save_test_spec",
    "resolve_cell_spec_id",
    "save_record",
    "save_test",
    "template_library_cell_spec",
    "template_cell_instance",
    "template_cell_spec_draft",
    "template_cell_spec",
    "template_dataset",
    "template_test_spec_draft",
    "template_test_spec",
    "template_test",
    "submit_publication_package",
    "validate_staging_cell_spec",
    "validate_staging_cell_specs",
    "validate_staging_dataset",
    "validate_staging_datasets",
    "save_test_protocol",
    "template_test_protocol",
    "template_test_protocol_draft",
    "query_test_protocols",
]

# Per-family component wrappers (create_electrode_spec, query_electrode_specs, …).
__all__ += _COMPONENT_WRAPPER_NAMES


save_test_protocol = save_test_spec  # backward compat alias
template_test_protocol = template_test_spec  # backward compat alias
template_test_protocol_draft = template_test_spec_draft  # backward compat alias
query_test_protocols = query_test_specs  # backward compat alias
