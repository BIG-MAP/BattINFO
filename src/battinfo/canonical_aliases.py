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
_CELL_TYPE_PRODUCT_TO_LEGACY = {value: key for key, value in _CELL_TYPE_PRODUCT_TO_SNAKE.items()}

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
_DATASET_TO_LEGACY = {value: key for key, value in _DATASET_TO_SNAKE.items()}

_AGENT_TO_SNAKE = {"sameAs": "same_as"}
_AGENT_TO_LEGACY = {value: key for key, value in _AGENT_TO_SNAKE.items()}
_DATA_CATALOG_TO_SNAKE = {"sameAs": "same_as"}
_DATA_CATALOG_TO_LEGACY = {value: key for key, value in _DATA_CATALOG_TO_SNAKE.items()}
_VARIABLE_TO_SNAKE = {"sameAs": "same_as"}
_VARIABLE_TO_LEGACY = {value: key for key, value in _VARIABLE_TO_SNAKE.items()}
_DISTRIBUTION_TO_SNAKE = {
    "contentUrl": "content_url",
    "encodingFormat": "encoding_format",
    "contentSize": "content_size",
    "accessLevel": "access_level",
}
_DISTRIBUTION_TO_LEGACY = {value: key for key, value in _DISTRIBUTION_TO_SNAKE.items()}
_TABLE_SCHEMA_TO_SNAKE = {"primaryKey": "primary_key"}
_TABLE_SCHEMA_TO_LEGACY = {value: key for key, value in _TABLE_SCHEMA_TO_SNAKE.items()}
_CSVW_TABLE_TO_SNAKE = {"tableSchema": "table_schema"}
_CSVW_TABLE_TO_LEGACY = {value: key for key, value in _CSVW_TABLE_TO_SNAKE.items()}
_TABLE_GROUP_TO_SNAKE = {"table": "tables"}
_TABLE_GROUP_TO_LEGACY = {value: key for key, value in _TABLE_GROUP_TO_SNAKE.items()}


def record_to_snake_aliases(record: Mapping[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(dict(record))
    if isinstance(normalized.get("cell_spec"), Mapping):
        normalized["cell_spec"] = _map_keys(dict(normalized["cell_spec"]), _CELL_TYPE_PRODUCT_TO_SNAKE)
    if isinstance(normalized.get("dataset"), Mapping):
        normalized["dataset"] = _dataset_to_snake(dict(normalized["dataset"]))
    return normalized


def record_to_legacy_aliases(record: Mapping[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(dict(record))
    if isinstance(normalized.get("cell_spec"), Mapping):
        normalized["cell_spec"] = _map_keys(dict(normalized["cell_spec"]), _CELL_TYPE_PRODUCT_TO_LEGACY)
    if isinstance(normalized.get("dataset"), Mapping):
        normalized["dataset"] = _dataset_to_legacy(dict(normalized["dataset"]))
    return normalized


def _map_keys(payload: dict[str, Any], mapping: Mapping[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in payload.items():
        out[mapping.get(key, key)] = value
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


def _dataset_to_legacy(dataset: dict[str, Any]) -> dict[str, Any]:
    normalized = _map_keys(dataset, _DATASET_TO_LEGACY)
    if isinstance(normalized.get("creator"), list):
        normalized["creator"] = [_agent_to_legacy(item) for item in normalized["creator"] if isinstance(item, Mapping)]
    if isinstance(normalized.get("publisher"), Mapping):
        normalized["publisher"] = _agent_to_legacy(normalized["publisher"])
    if isinstance(normalized.get("funder"), list):
        normalized["funder"] = [_agent_to_legacy(item) for item in normalized["funder"] if isinstance(item, Mapping)]
    if isinstance(normalized.get("includedInDataCatalog"), Mapping):
        normalized["includedInDataCatalog"] = _data_catalog_to_legacy(normalized["includedInDataCatalog"])
    if isinstance(normalized.get("citation"), list):
        normalized["citation"] = [copy.deepcopy(dict(item)) for item in normalized["citation"] if isinstance(item, Mapping)]
    if isinstance(normalized.get("variableMeasured"), list):
        normalized["variableMeasured"] = [
            _variable_to_legacy(item) for item in normalized["variableMeasured"] if isinstance(item, Mapping)
        ]
    if isinstance(normalized.get("distribution"), list):
        normalized["distribution"] = [
            _distribution_to_legacy(item) for item in normalized["distribution"] if isinstance(item, Mapping)
        ]
    if isinstance(normalized.get("mainEntity"), list):
        normalized["mainEntity"] = [
            _main_entity_to_legacy(item) for item in normalized["mainEntity"] if isinstance(item, Mapping)
        ]
    return normalized


def _agent_to_snake(value: Mapping[str, Any]) -> dict[str, Any]:
    return _map_keys(dict(value), _AGENT_TO_SNAKE)


def _agent_to_legacy(value: Mapping[str, Any]) -> dict[str, Any]:
    return _map_keys(dict(value), _AGENT_TO_LEGACY)


def _data_catalog_to_snake(value: Mapping[str, Any]) -> dict[str, Any]:
    return _map_keys(dict(value), _DATA_CATALOG_TO_SNAKE)


def _data_catalog_to_legacy(value: Mapping[str, Any]) -> dict[str, Any]:
    return _map_keys(dict(value), _DATA_CATALOG_TO_LEGACY)


def _variable_to_snake(value: Mapping[str, Any]) -> dict[str, Any]:
    return _map_keys(dict(value), _VARIABLE_TO_SNAKE)


def _variable_to_legacy(value: Mapping[str, Any]) -> dict[str, Any]:
    return _map_keys(dict(value), _VARIABLE_TO_LEGACY)


def _distribution_to_snake(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _map_keys(dict(value), _DISTRIBUTION_TO_SNAKE)
    checksum = normalized.get("checksum")
    if isinstance(checksum, Mapping):
        normalized["checksum"] = copy.deepcopy(dict(checksum))
    return normalized


def _distribution_to_legacy(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _map_keys(dict(value), _DISTRIBUTION_TO_LEGACY)
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


def _table_schema_to_legacy(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _map_keys(dict(value), _TABLE_SCHEMA_TO_LEGACY)
    columns = normalized.get("columns")
    if isinstance(columns, list):
        normalized["columns"] = [_table_column_to_legacy(item) for item in columns if isinstance(item, Mapping)]
    return normalized


def _table_column_to_snake(value: Mapping[str, Any]) -> dict[str, Any]:
    return _map_keys(dict(value), _VARIABLE_TO_SNAKE)


def _table_column_to_legacy(value: Mapping[str, Any]) -> dict[str, Any]:
    return _map_keys(dict(value), _VARIABLE_TO_LEGACY)


def _csvw_table_to_snake(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _map_keys(dict(value), _CSVW_TABLE_TO_SNAKE)
    table_schema = normalized.get("table_schema")
    if isinstance(table_schema, Mapping):
        normalized["table_schema"] = _table_schema_to_snake(table_schema)
    return normalized


def _csvw_table_to_legacy(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _map_keys(dict(value), _CSVW_TABLE_TO_LEGACY)
    table_schema = normalized.get("tableSchema")
    if isinstance(table_schema, Mapping):
        normalized["tableSchema"] = _table_schema_to_legacy(table_schema)
    return normalized


def _main_entity_to_snake(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _map_keys(dict(value), _TABLE_GROUP_TO_SNAKE)
    if normalized.get("type") == "Table":
        return _csvw_table_to_snake(normalized)
    tables = normalized.get("tables")
    if isinstance(tables, list):
        normalized["tables"] = [_csvw_table_to_snake(item) for item in tables if isinstance(item, Mapping)]
    return normalized


def _main_entity_to_legacy(value: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _map_keys(dict(value), _TABLE_GROUP_TO_LEGACY)
    if normalized.get("type") == "Table":
        return _csvw_table_to_legacy(normalized)
    tables = normalized.get("table")
    if isinstance(tables, list):
        normalized["table"] = [_csvw_table_to_legacy(item) for item in tables if isinstance(item, Mapping)]
    return normalized


__all__ = ["record_to_legacy_aliases", "record_to_snake_aliases"]
