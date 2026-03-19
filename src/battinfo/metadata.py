from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

try:  # pragma: no cover - optional dependency
    import pandas as pd  # type: ignore
except Exception:  # pragma: no cover
    pd = None  # type: ignore


class TableColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    titles: list[str] = Field(default_factory=list)
    description: str | None = None
    datatype: str | None = None
    unit_text: str | None = Field(default=None, validation_alias=AliasChoices("unit_text", "unit", "unitText"))
    same_as: str | None = Field(default=None, validation_alias=AliasChoices("same_as", "sameAs", "property_id", "propertyUrl", "iri"))
    required: bool | None = None

    def to_mapping(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"name": self.name}
        if self.titles:
            payload["titles"] = list(self.titles)
        if self.description is not None:
            payload["description"] = self.description
        if self.datatype is not None:
            payload["datatype"] = self.datatype
        if self.unit_text is not None:
            payload["unit_text"] = self.unit_text
        if self.same_as is not None:
            payload["sameAs"] = self.same_as
        if self.required is not None:
            payload["required"] = self.required
        return payload


class TableSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    name: str | None = None
    description: str | None = None
    columns: list[TableColumn] = Field(default_factory=list, validation_alias=AliasChoices("columns", "column"))
    primary_key: str | list[str] | None = Field(default=None, validation_alias=AliasChoices("primary_key", "primaryKey"))

    def to_mapping(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "columns": [column.to_mapping() for column in self.columns],
        }
        if self.id is not None:
            payload["id"] = self.id
        if self.name is not None:
            payload["name"] = self.name
        if self.description is not None:
            payload["description"] = self.description
        if self.primary_key is not None:
            payload["primaryKey"] = list(self.primary_key) if isinstance(self.primary_key, list) else self.primary_key
        return payload


def _mapping_from_model(value: Any) -> Any:
    if isinstance(value, TableColumn):
        return value.to_mapping()
    if isinstance(value, TableSchema):
        return value.to_mapping()
    return value


def _table_schema_mapping(value: str | Mapping[str, Any] | TableSchema) -> str | dict[str, Any]:
    resolved = _mapping_from_model(value)
    if isinstance(resolved, str):
        return resolved
    if isinstance(resolved, Mapping):
        return dict(resolved)
    raise TypeError("table_schema must be a string IRI, mapping, or battinfo.TableSchema.")


def organization(
    name: str,
    *,
    url: str | None = None,
    ror: str | None = None,
    same_as: str | None = None,
) -> dict[str, Any]:
    node: dict[str, Any] = {"type": "Organization", "name": name}
    if url is not None:
        node["url"] = url
    resolved_same_as = same_as
    if resolved_same_as is None and ror is not None:
        resolved_same_as = ror if ror.startswith("http") else f"https://ror.org/{ror}"
    if resolved_same_as is not None:
        node["sameAs"] = resolved_same_as
    return node


def person(
    name: str,
    *,
    email: str | None = None,
    url: str | None = None,
    orcid: str | None = None,
    same_as: str | None = None,
    given_name: str | None = None,
    family_name: str | None = None,
    affiliation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    node: dict[str, Any] = {"type": "Person", "name": name}
    if email is not None:
        node["email"] = email
    if url is not None:
        node["url"] = url
    resolved_same_as = same_as
    if resolved_same_as is None and orcid is not None:
        resolved_same_as = orcid if orcid.startswith("http") else f"https://orcid.org/{orcid}"
    if resolved_same_as is not None:
        node["sameAs"] = resolved_same_as
    if given_name is not None:
        node["given_name"] = given_name
    if family_name is not None:
        node["family_name"] = family_name
    if affiliation is not None:
        node["affiliation"] = dict(affiliation)
    return node


def data_catalog(
    name: str,
    *,
    id: str | None = None,
    url: str | None = None,
    same_as: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    node: dict[str, Any] = {"type": "DataCatalog", "name": name}
    if id is not None:
        node["id"] = id
    if url is not None:
        node["url"] = url
    if same_as is not None:
        node["sameAs"] = same_as
    if description is not None:
        node["description"] = description
    return node


def measured_variable(
    name: str,
    *,
    property_id: str | None = None,
    same_as: str | None = None,
    unit_text: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    node: dict[str, Any] = {"name": name}
    resolved_same_as = same_as or property_id
    if resolved_same_as is not None:
        node["sameAs"] = resolved_same_as
    if unit_text is not None:
        node["unit_text"] = unit_text
    if description is not None:
        node["description"] = description
    return node


def checksum(algorithm: str, value: str) -> dict[str, str]:
    return {"algorithm": algorithm, "value": value}


def distribution(
    content_url: str,
    *,
    encoding_format: str,
    name: str | None = None,
    description: str | None = None,
    content_size: str | None = None,
    access_level: str | None = None,
    checksum_value: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    node: dict[str, Any] = {
        "type": "DataDownload",
        "contentUrl": content_url,
        "encodingFormat": encoding_format,
    }
    if name is not None:
        node["name"] = name
    if description is not None:
        node["description"] = description
    if content_size is not None:
        node["contentSize"] = content_size
    if access_level is not None:
        node["accessLevel"] = access_level
    if checksum_value is not None:
        node["checksum"] = dict(checksum_value)
    return node


def file_distribution(
    path: str | Path,
    *,
    encoding_format: str | None = None,
    description: str | None = None,
    content_size: str | None = None,
    access_level: str | None = None,
    checksum_value: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    file_path = Path(path)
    return distribution(
        file_path.resolve().as_uri(),
        encoding_format=encoding_format or "application/octet-stream",
        name=file_path.name,
        description=description,
        content_size=content_size,
        access_level=access_level,
        checksum_value=checksum_value,
    )


def csvw_table(
    url: str,
    *,
    table_schema: str | Mapping[str, Any] | TableSchema,
    id: str | None = None,
    name: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    node: dict[str, Any] = {
        "type": "Table",
        "url": url,
        "tableSchema": _table_schema_mapping(table_schema),
    }
    if id is not None:
        node["id"] = id
    if name is not None:
        node["name"] = name
    if description is not None:
        node["description"] = description
    return node


def csvw_table_group(
    *tables: Mapping[str, Any],
    id: str | None = None,
    url: str | None = None,
    name: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    node: dict[str, Any] = {"type": "TableGroup", "table": [dict(table) for table in tables]}
    if id is not None:
        node["id"] = id
    if url is not None:
        node["url"] = url
    if name is not None:
        node["name"] = name
    if description is not None:
        node["description"] = description
    return node


def _split_label_and_unit(label: str) -> tuple[str, str | None]:
    text = label.strip()
    if " / " in text:
        left, right = text.split("/", 1)
        return left.strip(), right.strip() or None
    if text.endswith("]") and "[" in text:
        left, right = text.rsplit("[", 1)
        return left.strip(), right[:-1].strip() or None
    return text, None


def _coerce_column_sequence(data: Any, columns: Sequence[Any] | None) -> Sequence[Any]:
    if columns is not None:
        return columns
    if data is None:
        return []
    if hasattr(data, "columns"):
        return list(getattr(data, "columns"))
    return []


def _coerce_column_metadata(data: Any, column_metadata: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if column_metadata is not None:
        return column_metadata
    attrs = getattr(data, "attrs", {}) if data is not None else {}
    if isinstance(attrs, Mapping):
        for key in ("battinfo:columns", "bdf:columns"):
            value = attrs.get(key)
            if isinstance(value, Mapping):
                return value
    return {}


def _coerce_table_schema_columns(table_schema: TableSchema | Mapping[str, Any] | None) -> Sequence[Any]:
    if table_schema is None:
        return []
    resolved = _mapping_from_model(table_schema)
    if not isinstance(resolved, Mapping):
        return []
    columns = resolved.get("columns") or resolved.get("column")
    if not isinstance(columns, list):
        return []
    out: list[str] = []
    for item in columns:
        candidate = _mapping_from_model(item)
        if not isinstance(candidate, Mapping):
            continue
        titles = candidate.get("titles")
        if isinstance(titles, list):
            label = next((str(value).strip() for value in titles if isinstance(value, str) and str(value).strip()), None)
            if label:
                out.append(label)
                continue
        if isinstance(titles, str) and titles.strip():
            out.append(titles.strip())
            continue
        name = candidate.get("name")
        if isinstance(name, str) and name.strip():
            out.append(name.strip())
    return out


def _coerce_table_schema_metadata(table_schema: TableSchema | Mapping[str, Any] | None) -> Mapping[str, Any]:
    if table_schema is None:
        return {}
    resolved = _mapping_from_model(table_schema)
    if not isinstance(resolved, Mapping):
        return {}
    columns = resolved.get("columns") or resolved.get("column")
    if not isinstance(columns, list):
        return {}
    metadata: dict[str, dict[str, Any]] = {}
    for item in columns:
        candidate = _mapping_from_model(item)
        if not isinstance(candidate, Mapping):
            continue
        label = None
        titles = candidate.get("titles")
        if isinstance(titles, list):
            label = next((str(value).strip() for value in titles if isinstance(value, str) and str(value).strip()), None)
        elif isinstance(titles, str) and titles.strip():
            label = titles.strip()
        if label is None:
            name = candidate.get("name")
            if isinstance(name, str) and name.strip():
                label = name.strip()
        if label is None:
            continue
        info: dict[str, Any] = {}
        if isinstance(candidate.get("description"), str):
            info["description"] = candidate["description"]
        if isinstance(candidate.get("unit_text"), str):
            info["unit"] = candidate["unit_text"]
        if isinstance(candidate.get("sameAs"), str):
            info["iri"] = candidate["sameAs"]
        elif isinstance(candidate.get("property_id"), str):
            info["iri"] = candidate["property_id"]
        name = candidate.get("name")
        if isinstance(name, str) and name.strip():
            info["name"] = name.strip()
        if info:
            metadata[label] = info
    return metadata


def infer_variable_measured(
    data: Any = None,
    *,
    columns: Sequence[Any] | None = None,
    column_metadata: Mapping[str, Any] | None = None,
    table_schema: TableSchema | Mapping[str, Any] | None = None,
    numeric_only: bool = False,
) -> list[dict[str, Any]]:
    resolved_columns = _coerce_column_sequence(data, columns)
    if not resolved_columns and table_schema is not None:
        resolved_columns = _coerce_table_schema_columns(table_schema)
    resolved_metadata = _coerce_column_metadata(data, column_metadata)
    if not resolved_metadata and table_schema is not None:
        resolved_metadata = _coerce_table_schema_metadata(table_schema)
    out: list[dict[str, Any]] = []

    for column in resolved_columns:
        column_label = str(column)
        if numeric_only and pd is not None and hasattr(data, "__getitem__"):
            try:
                if not pd.api.types.is_numeric_dtype(data[column]):  # type: ignore[index]
                    continue
            except Exception:  # noqa: BLE001
                pass
        info = resolved_metadata.get(column_label)
        if isinstance(info, Mapping):
            name = str(info.get("name") or _split_label_and_unit(column_label)[0]).strip()
            unit_text = info.get("unit")
            if not isinstance(unit_text, str):
                _, unit_text = _split_label_and_unit(column_label)
            property_id = info.get("sameAs") or info.get("property_id") or info.get("iri")
            description = info.get("description")
        else:
            name, unit_text = _split_label_and_unit(column_label)
            property_id = None
            description = None
        if not name:
            continue
        variable = measured_variable(
            name,
            property_id=str(property_id) if isinstance(property_id, str) else None,
            unit_text=unit_text if isinstance(unit_text, str) else None,
            description=description if isinstance(description, str) else None,
        )
        out.append(variable)

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None, str | None]] = set()
    for item in out:
        key = (
            item["name"],
            item.get("sameAs") if isinstance(item.get("sameAs"), str) else None,
            item.get("unit_text") if isinstance(item.get("unit_text"), str) else None,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _merge_variable_measured(
    existing: Sequence[Mapping[str, Any]],
    inferred: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str | None, str | None]] = set()
    for item in [*existing, *inferred]:
        key = (
            str(item.get("name", "")),
            str(item.get("sameAs")) if isinstance(item.get("sameAs"), str) else None,
            str(item.get("unit_text")) if isinstance(item.get("unit_text"), str) else None,
        )
        if not key[0] or key in seen:
            continue
        seen.add(key)
        out.append(dict(item))
    return out


def _merge_main_entity(
    existing: Sequence[Mapping[str, Any]],
    inferred: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    if inferred is None:
        return [dict(item) for item in existing]
    out: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()
    for item in [*existing, inferred]:
        table_schema = item.get("tableSchema")
        if isinstance(table_schema, Mapping):
            table_schema_key = (
                str(table_schema.get("id"))
                if isinstance(table_schema.get("id"), str)
                else json.dumps(table_schema, sort_keys=True, ensure_ascii=False)
            )
        elif isinstance(table_schema, str):
            table_schema_key = table_schema
        else:
            table_schema_key = None
        key = (
            str(item.get("type")) if isinstance(item.get("type"), str) else None,
            str(item.get("url")) if isinstance(item.get("url"), str) else None,
            table_schema_key,
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(item))
    return out


def _infer_csvw_url(dataset: Any) -> str | None:
    for item in getattr(dataset, "distributions", []):
        if not isinstance(item, Mapping):
            continue
        content_url = item.get("contentUrl")
        encoding_format = item.get("encodingFormat")
        if not isinstance(content_url, str):
            continue
        if isinstance(encoding_format, str) and any(token in encoding_format.lower() for token in ("csv", "tsv", "tabular", "parquet")):
            return content_url
    download_url = getattr(dataset, "download_url", None)
    if isinstance(download_url, str):
        return download_url
    return None


def enrich_tabular_dataset(
    dataset: Any,
    *,
    data: Any = None,
    columns: Sequence[Any] | None = None,
    column_metadata: Mapping[str, Any] | None = None,
    csvw_url: str | None = None,
    table_schema: str | Mapping[str, Any] | TableSchema | None = None,
    table_id: str | None = None,
    table_name: str | None = None,
    table_description: str | None = None,
    merge_variables: bool = True,
    replace_main_entity: bool = False,
):
    from battinfo.bundle import Dataset as BattinfoDataset

    if not isinstance(dataset, BattinfoDataset):
        raise TypeError("dataset must be a battinfo.Dataset instance")

    inferred_variables = infer_variable_measured(
        data,
        columns=columns,
        column_metadata=column_metadata,
        table_schema=table_schema if isinstance(table_schema, (TableSchema, Mapping)) else None,
    )
    if merge_variables:
        variable_measured = _merge_variable_measured(dataset.variable_measured, inferred_variables)
    else:
        variable_measured = [dict(item) for item in inferred_variables] or [dict(item) for item in dataset.variable_measured]

    main_entity = [dict(item) for item in dataset.main_entity]
    inferred_table = None
    resolved_csvw_url = csvw_url or _infer_csvw_url(dataset)
    if table_schema is not None and resolved_csvw_url is not None:
        inferred_table = csvw_table(
            resolved_csvw_url,
            table_schema=table_schema,
            id=table_id,
            name=table_name,
            description=table_description,
        )
    if replace_main_entity:
        main_entity = [inferred_table] if inferred_table is not None else []
    else:
        main_entity = _merge_main_entity(main_entity, inferred_table)

    return dataset.model_copy(
        update={
            "variable_measured": variable_measured,
            "main_entity": main_entity,
            "test": dataset.test,
            "cell": dataset.cell,
        },
        deep=True,
    )


__all__ = [
    "TableColumn",
    "TableSchema",
    "checksum",
    "csvw_table",
    "csvw_table_group",
    "data_catalog",
    "distribution",
    "enrich_tabular_dataset",
    "file_distribution",
    "infer_variable_measured",
    "measured_variable",
    "organization",
    "person",
]
