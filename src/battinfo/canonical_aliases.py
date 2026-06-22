from __future__ import annotations

import copy
from typing import Any, Mapping

_CELL_TYPE_PRODUCT_TO_SNAKE = {
    "cellFormat": "cell_format",
    "positiveElectrodeBasis": "positive_electrode_basis",
    "negativeElectrodeBasis": "negative_electrode_basis",
    "sizeCode": "size_code",
    "iecCode": "iec_code",
    "countryOfOrigin": "country_of_origin",
    "datasheetRevision": "datasheet_revision",
    "productType": "product_type",
    "additionalType": "additional_type",
    "manufacturingPlace": "manufacturing_place",
    "batteryCategory": "battery_category",
    "referenceElectrode": "reference_electrode",
}

_DATASET_TO_SNAKE = {
    "sameAs": "same_as",
    "additionalType": "additional_type",
    "creator": "creators",
    "funder": "funders",
    "citation": "citations",
    "measurementTechnique": "measurement_techniques",
    "measurementMethod": "measurement_methods",
    "variableMeasured": "variable_measured",
    "isAccessibleForFree": "is_accessible_for_free",
    "conditionsOfAccess": "conditions_of_access",
    "inLanguage": "in_language",
    "url": "access_url",
    "dateCreated": "created_at",
    "dateModified": "modified_at",
    "datePublished": "published_at",
    "temporalCoverage": "temporal_coverage",
    "spatialCoverage": "spatial_coverage",
    "isBasedOn": "is_based_on",
    "includedInDataCatalog": "included_in_data_catalog",
    "mainEntity": "main_entity",
    "distribution": "distributions",
}

_AGENT_TO_SNAKE = {"sameAs": "same_as"}
_DATA_CATALOG_TO_SNAKE = {"sameAs": "same_as"}
_VARIABLE_TO_SNAKE = {"sameAs": "same_as"}
_DISTRIBUTION_TO_SNAKE = {
    "contentUrl": "content_url",
    "encodingFormat": "encoding_format",
    "contentSize": "content_size",
    "accessLevel": "access_level",
}
_TABLE_SCHEMA_TO_SNAKE = {"primaryKey": "primary_key"}
_CSVW_TABLE_TO_SNAKE = {"tableSchema": "table_schema"}
_TABLE_GROUP_TO_SNAKE = {"table": "tables"}


def record_to_snake_aliases(record: Mapping[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(dict(record))
    if isinstance(normalized.get("cell_spec"), Mapping):
        normalized["cell_spec"] = _map_keys(dict(normalized["cell_spec"]), _CELL_TYPE_PRODUCT_TO_SNAKE)
    if isinstance(normalized.get("dataset"), Mapping):
        normalized["dataset"] = _dataset_to_snake(dict(normalized["dataset"]))
    return normalized


def _map_keys(payload: dict[str, Any], mapping: Mapping[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in payload.items():
        target = mapping.get(key, key)
        # If a record carries BOTH a legacy camelCase alias and its already-migrated
        # snake_case key, they collide on the same output key. Deterministically keep
        # the canonical (snake_case) value rather than letting dict iteration order
        # decide which one wins (silent, order-dependent data loss).
        if target in out and key in mapping:
            continue  # `key` is an alias; the canonical value is already present
        out[target] = value
    return out


def _dataset_to_snake(dataset: dict[str, Any]) -> dict[str, Any]:
    normalized = _map_keys(dataset, _DATASET_TO_SNAKE)
    if isinstance(normalized.get("creators"), list):
        normalized["creators"] = [_agent_to_snake(item) for item in normalized["creators"] if isinstance(item, Mapping)]
    if isinstance(normalized.get("publisher"), Mapping):
        normalized["publisher"] = _agent_to_snake(normalized["publisher"])
    if isinstance(normalized.get("funders"), list):
        normalized["funders"] = [_agent_to_snake(item) for item in normalized["funders"] if isinstance(item, Mapping)]
    if isinstance(normalized.get("included_in_data_catalog"), Mapping):
        normalized["included_in_data_catalog"] = _data_catalog_to_snake(normalized["included_in_data_catalog"])
    if isinstance(normalized.get("citations"), list):
        normalized["citations"] = [copy.deepcopy(dict(item)) for item in normalized["citations"] if isinstance(item, Mapping)]
    if isinstance(normalized.get("variable_measured"), list):
        normalized["variable_measured"] = [
            _variable_to_snake(item) for item in normalized["variable_measured"] if isinstance(item, Mapping)
        ]
    if isinstance(normalized.get("distributions"), list):
        normalized["distributions"] = [
            _distribution_to_snake(item) for item in normalized["distributions"] if isinstance(item, Mapping)
        ]
    if isinstance(normalized.get("main_entity"), list):
        normalized["main_entity"] = [
            _main_entity_to_snake(item) for item in normalized["main_entity"] if isinstance(item, Mapping)
        ]
    return normalized


def _agent_to_snake(value: Mapping[str, Any]) -> dict[str, Any]:
    return _map_keys(dict(value), _AGENT_TO_SNAKE)


def _data_catalog_to_snake(value: Mapping[str, Any]) -> dict[str, Any]:
    return _map_keys(dict(value), _DATA_CATALOG_TO_SNAKE)


def _variable_to_snake(value: Mapping[str, Any]) -> dict[str, Any]:
    return _map_keys(dict(value), _VARIABLE_TO_SNAKE)


def _distribution_to_snake(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _map_keys(dict(value), _DISTRIBUTION_TO_SNAKE)
    checksum = normalized.get("checksum")
    if isinstance(checksum, Mapping):
        normalized["checksum"] = copy.deepcopy(dict(checksum))
    return normalized


def _table_schema_to_snake(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _map_keys(dict(value), _TABLE_SCHEMA_TO_SNAKE)
    columns = normalized.get("columns")
    if isinstance(columns, list):
        normalized["columns"] = [_table_column_to_snake(item) for item in columns if isinstance(item, Mapping)]
    return normalized


def _table_column_to_snake(value: Mapping[str, Any]) -> dict[str, Any]:
    return _map_keys(dict(value), _VARIABLE_TO_SNAKE)


def _csvw_table_to_snake(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _map_keys(dict(value), _CSVW_TABLE_TO_SNAKE)
    table_schema = normalized.get("table_schema")
    if isinstance(table_schema, Mapping):
        normalized["table_schema"] = _table_schema_to_snake(table_schema)
    return normalized


def _main_entity_to_snake(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _map_keys(dict(value), _TABLE_GROUP_TO_SNAKE)
    if normalized.get("type") == "Table":
        return _csvw_table_to_snake(normalized)
    tables = normalized.get("tables")
    if isinstance(tables, list):
        normalized["tables"] = [_csvw_table_to_snake(item) for item in tables if isinstance(item, Mapping)]
    return normalized


__all__ = ["record_to_snake_aliases"]
