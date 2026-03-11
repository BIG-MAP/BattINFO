from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, ClassVar, Mapping, Self

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

PathLike = str | Path

BUNDLE_MANIFEST_FILENAME = "bundle.json"
CELL_SPECIFICATION_FILENAME = "cell-specification.json"
CELL_TYPE_FILENAME = "cell-type.json"
CELL_INSTANCE_FILENAME = "cell-instance.json"
TEST_FILENAME = "test.json"
DATASET_FILENAME = "dataset.json"
OWL_CLASS_IRI = "http://www.w3.org/2002/07/owl#Class"
RDFS_SUBCLASS_OF_IRI = "http://www.w3.org/2000/01/rdf-schema#subClassOf"


def _as_path(path: PathLike) -> Path:
    return path if isinstance(path, Path) else Path(path)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _short_id(entity_id: str) -> str:
    tail = entity_id.rstrip("/").split("/")[-1].replace("-", "")
    return tail[:6]


def _identifier(prefix: str, entity_id: str) -> str:
    tail = entity_id.rstrip("/").split("/")[-1]
    return f"{prefix}:{tail}"


def _id_tail(entity_id: str | None) -> str | None:
    if not entity_id:
        return None
    return entity_id.rstrip("/").split("/")[-1]


def _node_has_type(node: Mapping[str, Any], expected: str) -> bool:
    value = node.get("@type")
    if isinstance(value, str):
        return value == expected
    if isinstance(value, list):
        return expected in value
    return False


def _type_values(node: Mapping[str, Any]) -> list[str]:
    value = node.get("@type")
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _graph_nodes(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    graph = payload.get("@graph")
    if isinstance(graph, list):
        return [node for node in graph if isinstance(node, dict)]
    if isinstance(payload, dict):
        return [dict(payload)]
    return []


def _ref_id(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        ref_id = value.get("@id")
        return str(ref_id) if isinstance(ref_id, str) else None
    if isinstance(value, list):
        for item in value:
            ref_id = _ref_id(item)
            if ref_id is not None:
                return ref_id
    return None


def _text_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if isinstance(item, (str, int, float))]
    return []


def _instrument_name(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        name = value.get("schema:name")
        return str(name) if isinstance(name, str) else None
    return None


def _protocol_from_description(value: Any) -> tuple[str | None, str | None]:
    text_items = _text_list(value)
    protocol_name = None
    description_items: list[str] = []
    for item in text_items:
        if item.startswith("Protocol: "):
            protocol_name = item.removeprefix("Protocol: ").strip() or None
        else:
            description_items.append(item)
    if not description_items:
        description = None
    elif len(description_items) == 1:
        description = description_items[0]
    else:
        description = "\n".join(description_items)
    return protocol_name, description


def _ref_ids(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        ref_id = value.get("@id")
        return [str(ref_id)] if isinstance(ref_id, str) else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_ref_ids(item))
        return out
    return []


def _subclass_ref_ids(node: Mapping[str, Any]) -> list[str]:
    return _ref_ids(node.get(RDFS_SUBCLASS_OF_IRI)) + _ref_ids(node.get("rdfs:subClassOf"))


def _unit_from_iri(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if value.endswith("MilliMetre"):
        return "mm"
    if value.endswith("Volt"):
        return "V"
    if value.endswith("AmpereHour"):
        return "Ah"
    if value.endswith("Gram"):
        return "g"
    return value


def _property_key_from_type(value: Any) -> str | None:
    if isinstance(value, str):
        types = [value]
    elif isinstance(value, list):
        types = [item for item in value if isinstance(item, str)]
    else:
        types = []
    for type_name in types:
        if type_name == "Diameter":
            return "diameter"
        if type_name == "Height":
            return "height"
        if type_name == "NominalVoltage":
            return "nominal_voltage"
        if type_name == "NominalCapacity":
            return "nominal_capacity"
        if type_name == "Mass":
            return "mass"
    return None


def _extract_property_item(node: Mapping[str, Any]) -> tuple[str, dict[str, Any]] | None:
    key = _property_key_from_type(node.get("@type"))
    if key is None:
        return None
    numerical = node.get("hasNumericalPart")
    if not isinstance(numerical, Mapping):
        return None
    value = numerical.get("hasNumericalValue")
    unit = _unit_from_iri(node.get("hasMeasurementUnit"))
    if value is None or unit is None:
        return None
    return key, {"value": value, "unit": unit}


class ProvenanceInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str | None = None
    name: str | None = None
    file: str | None = None
    url: str | None = None
    retrieved_at: int | str | None = None
    workflow_version: str | None = None
    file_hash: str | None = None
    curated_by: str | None = None
    comment: str | None = None


class ProtocolInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    url: str | None = None


class ChecksumInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    algorithm: str | None = None
    value: str | None = None


class MaterialComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    property: dict[str, Any] = Field(default_factory=dict)
    comment: str | None = None


class Coating(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component: dict[str, list[MaterialComponent]] = Field(default_factory=dict)
    property: dict[str, Any] = Field(default_factory=dict)
    comment: str | None = None

    @field_validator("component", mode="before")
    @classmethod
    def _coerce_component_groups(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        out: dict[str, list[dict[str, Any] | MaterialComponent]] = {}
        for key, items in value.items():
            if isinstance(items, list):
                out[str(key)] = list(items)
        return out


class CurrentCollector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    property: dict[str, Any] = Field(default_factory=dict)
    comment: str | None = None


class Electrode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    coating: Coating | None = None
    current_collector: CurrentCollector | None = None
    property: dict[str, Any] = Field(default_factory=dict)
    comment: str | None = None


class SolventMixture(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component: list[MaterialComponent] = Field(default_factory=list)
    property: dict[str, Any] = Field(default_factory=dict)
    comment: str | None = None


class Salt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    cation: str | None = None
    anion: str | None = None
    property: dict[str, Any] = Field(default_factory=dict)
    comment: str | None = None


class Separator(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material: str | None = None
    property: dict[str, Any] = Field(default_factory=dict)
    comment: str | None = None


class Electrolyte(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family: str | None = None
    solvent_mixture: SolventMixture | None = None
    salt: Salt | None = None
    additive: list[MaterialComponent] = Field(default_factory=list)
    property: dict[str, Any] = Field(default_factory=dict)
    comment: str | None = None


class BundleJsonModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0.0"
    kind: str

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> Self:
        return cls.model_validate(dict(payload))

    @classmethod
    def from_path(cls, path: PathLike) -> Self:
        return cls.from_json(_read_json(_as_path(path)))

    def to_path(self, path: PathLike) -> Path:
        out_path = _as_path(path)
        _write_json(out_path, self.to_json())
        return out_path


class CellSpecification(BundleJsonModel):
    default_filename: ClassVar[str] = CELL_SPECIFICATION_FILENAME

    kind: str = "CellSpecification"
    id: str
    manufacturer: str
    model: str
    format: str
    chemistry: str
    positive_electrode_basis: str | None = None
    negative_electrode_basis: str | None = None
    size_code: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    positive_electrode: Electrode | None = None
    negative_electrode: Electrode | None = None
    electrolyte: Electrolyte | None = None
    separator: Separator | None = None
    specification_comment: list[str] = Field(default_factory=list)
    source: ProvenanceInfo = Field(default_factory=ProvenanceInfo)
    comment: list[str] = Field(default_factory=list)

    @field_validator("positive_electrode", "negative_electrode", mode="before")
    @classmethod
    def _coerce_electrode(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            return dict(value)
        return value

    @field_validator("electrolyte", mode="before")
    @classmethod
    def _coerce_electrolyte(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            return dict(value)
        return value

    @field_validator("separator", mode="before")
    @classmethod
    def _coerce_separator(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            return dict(value)
        return value

    @classmethod
    def from_path(cls, path: PathLike) -> Self:
        payload = _read_json(_as_path(path))
        if isinstance(payload.get("specification"), Mapping):
            return cls.from_library_record(payload)
        return cls.from_json(payload)

    @classmethod
    def from_library_record(cls, record: Mapping[str, Any]) -> Self:
        specification = record.get("specification", {})
        provenance = record.get("provenance", {})
        if not isinstance(specification, Mapping):
            raise ValueError("cell specification record must contain a 'specification' object.")
        if not isinstance(provenance, Mapping):
            provenance = {}
        specification_comment = specification.get("comment")
        if not isinstance(specification_comment, list):
            specification_comment = []
        comment = record.get("comment")
        if not isinstance(comment, list):
            comment = []
        return cls(
            schema_version=str(record.get("schema_version", "1.0.0")),
            id=str(specification["id"]),
            manufacturer=str(specification["manufacturer"]),
            model=str(specification["model"]),
            format=str(specification["format"]),
            chemistry=str(specification["chemistry"]),
            positive_electrode_basis=specification.get("positive_electrode_basis"),
            negative_electrode_basis=specification.get("negative_electrode_basis"),
            size_code=specification.get("size_code"),
            properties=dict(specification.get("property", {})) if isinstance(specification.get("property"), Mapping) else {},
            positive_electrode=copy.deepcopy(specification.get("positive_electrode")),
            negative_electrode=copy.deepcopy(specification.get("negative_electrode")),
            electrolyte=copy.deepcopy(specification.get("electrolyte")),
            separator=copy.deepcopy(specification.get("separator")),
            specification_comment=[str(item) for item in specification_comment],
            source=ProvenanceInfo(
                type=provenance.get("source_type"),
                name=provenance.get("source_name"),
                file=provenance.get("source_file"),
                url=provenance.get("source_url"),
                retrieved_at=provenance.get("retrieved_at"),
                workflow_version=provenance.get("workflow_version"),
                comment=provenance.get("comment"),
            ),
            comment=[str(item) for item in comment],
        )

    def to_library_record(self) -> dict[str, Any]:
        specification: dict[str, Any] = {
            "id": self.id,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "format": self.format,
            "chemistry": self.chemistry,
        }
        if self.positive_electrode_basis is not None:
            specification["positive_electrode_basis"] = self.positive_electrode_basis
        if self.negative_electrode_basis is not None:
            specification["negative_electrode_basis"] = self.negative_electrode_basis
        if self.size_code is not None:
            specification["size_code"] = self.size_code
        if self.properties:
            specification["property"] = self.properties
        if self.positive_electrode is not None:
            specification["positive_electrode"] = self.positive_electrode.model_dump(mode="json", exclude_none=True)
        if self.negative_electrode is not None:
            specification["negative_electrode"] = self.negative_electrode.model_dump(mode="json", exclude_none=True)
        if self.electrolyte is not None:
            specification["electrolyte"] = self.electrolyte.model_dump(mode="json", exclude_none=True)
        if self.separator is not None:
            specification["separator"] = self.separator.model_dump(mode="json", exclude_none=True)
        if self.specification_comment:
            specification["comment"] = list(self.specification_comment)

        provenance: dict[str, Any] = {}
        if self.source.type is not None:
            provenance["source_type"] = self.source.type
        if self.source.name is not None:
            provenance["source_name"] = self.source.name
        if self.source.file is not None:
            provenance["source_file"] = self.source.file
        if self.source.url is not None:
            provenance["source_url"] = self.source.url
        if self.source.retrieved_at is not None:
            provenance["retrieved_at"] = self.source.retrieved_at
        if self.source.workflow_version is not None:
            provenance["workflow_version"] = self.source.workflow_version
        if self.source.comment is not None:
            provenance["comment"] = self.source.comment

        out = {
            "schema_version": self.schema_version,
            "specification": specification,
            "provenance": provenance,
        }
        if self.comment:
            out["comment"] = list(self.comment)
        return out


class CellType(BundleJsonModel):
    default_filename: ClassVar[str] = CELL_TYPE_FILENAME

    kind: str = "CellType"
    id: str | None = None
    name: str | None = None
    manufacturer: str
    model: str
    format: str
    chemistry: str
    positive_electrode_basis: str | None = None
    negative_electrode_basis: str | None = None
    size_code: str | None = None
    datasheet_revision: str | None = None
    cell_specification_id: str | None = None
    nominal_properties: dict[str, Any] = Field(default_factory=dict)
    source: ProvenanceInfo = Field(default_factory=ProvenanceInfo)
    comment: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _populate_name(self) -> Self:
        if self.name is None:
            self.name = f"{self.manufacturer} {self.model}"
        return self

    @classmethod
    def from_record(cls, record: Mapping[str, Any], *, cell_specification_id: str | None = None) -> Self:
        product = record.get("product")
        if not isinstance(product, Mapping):
            raise ValueError("cell type record must contain a 'product' object.")
        provenance = record.get("provenance", {})
        if not isinstance(provenance, Mapping):
            provenance = {}
        manufacturer = product.get("manufacturer")
        manufacturer_name = manufacturer.get("name") if isinstance(manufacturer, Mapping) else manufacturer
        notes = record.get("notes")
        if not isinstance(notes, list):
            notes = []
        return cls(
            schema_version=str(record.get("schema_version", "1.0.0")),
            id=str(product["id"]),
            name=str(product.get("name") or f"{manufacturer_name} {product.get('model')}"),
            manufacturer=str(manufacturer_name),
            model=str(product["model"]),
            format=str(product.get("cellFormat", "unknown")),
            chemistry=str(product.get("chemistry", "unknown")),
            positive_electrode_basis=product.get("positiveElectrodeBasis"),
            negative_electrode_basis=product.get("negativeElectrodeBasis"),
            size_code=product.get("sizeCode"),
            datasheet_revision=product.get("datasheetRevision"),
            cell_specification_id=cell_specification_id,
            nominal_properties=dict(record.get("specs", {})) if isinstance(record.get("specs"), Mapping) else {},
            source=ProvenanceInfo(
                type=provenance.get("source_type"),
                file=provenance.get("source_file"),
                url=provenance.get("source_url"),
                retrieved_at=provenance.get("retrieved_at"),
                file_hash=provenance.get("file_hash"),
            ),
            comment=[str(item) for item in notes],
        )

    @classmethod
    def from_cell_specification(
        cls,
        specification: CellSpecification,
        *,
        id: str | None = None,
        name: str | None = None,
    ) -> Self:
        return cls(
            id=id or specification.id,
            name=name or f"{specification.manufacturer} {specification.model}",
            manufacturer=specification.manufacturer,
            model=specification.model,
            format=specification.format,
            chemistry=specification.chemistry,
            positive_electrode_basis=specification.positive_electrode_basis,
            negative_electrode_basis=specification.negative_electrode_basis,
            size_code=specification.size_code,
            cell_specification_id=specification.id,
            nominal_properties=dict(specification.properties),
            source=ProvenanceInfo(
                type=specification.source.type,
                file=specification.source.file,
                url=specification.source.url,
                retrieved_at=specification.source.retrieved_at,
            ),
            comment=["Generated from the linked CellSpecification."],
        )

    def to_record(self) -> dict[str, Any]:
        if self.id is None:
            raise ValueError("CellType.id is required before serialization. Use battinfo.publish(...) to finalize IDs.")
        if self.name is None:
            raise ValueError("CellType.name is required before serialization.")
        record: dict[str, Any] = {
            "schema_version": self.schema_version,
            "product": {
                "id": self.id,
                "short_id": _short_id(self.id),
                "identifier": _identifier("cell-type", self.id),
                "name": self.name,
                "model": self.model,
                "manufacturer": {"type": "Organization", "name": self.manufacturer},
                "cellFormat": self.format,
                "chemistry": self.chemistry,
            },
            "specs": self.nominal_properties,
            "provenance": {},
        }
        if self.positive_electrode_basis is not None:
            record["product"]["positiveElectrodeBasis"] = self.positive_electrode_basis
        if self.negative_electrode_basis is not None:
            record["product"]["negativeElectrodeBasis"] = self.negative_electrode_basis
        if self.size_code is not None:
            record["product"]["sizeCode"] = self.size_code
        if self.datasheet_revision is not None:
            record["product"]["datasheetRevision"] = self.datasheet_revision
        if self.source.type is not None:
            record["provenance"]["source_type"] = self.source.type
        if self.source.file is not None:
            record["provenance"]["source_file"] = self.source.file
        if self.source.url is not None:
            record["provenance"]["source_url"] = self.source.url
        if self.source.retrieved_at is not None:
            record["provenance"]["retrieved_at"] = self.source.retrieved_at
        if self.source.file_hash is not None:
            record["provenance"]["file_hash"] = self.source.file_hash
        if self.comment:
            record["notes"] = list(self.comment)
        return record


class CellInstance(BundleJsonModel):
    default_filename: ClassVar[str] = CELL_INSTANCE_FILENAME

    kind: str = "CellInstance"
    id: str | None = None
    name: str | None = None
    cell_type_id: str | None = None
    cell_type: CellType | None = Field(default=None, exclude=True, repr=False)
    serial_number: str | None = None
    batch_id: str | None = None
    manufactured_at: int | str | None = None
    measured: dict[str, Any] = Field(default_factory=dict)
    dataset_ids: list[str] = Field(default_factory=list)
    source: ProvenanceInfo = Field(default_factory=ProvenanceInfo)
    comment: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _populate_links(self) -> Self:
        if self.cell_type_id is None and self.cell_type is not None and self.cell_type.id is not None:
            self.cell_type_id = self.cell_type.id
        if self.name is None:
            self.name = self.serial_number or self.batch_id or _id_tail(self.id)
        return self

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> Self:
        cell_instance = record.get("cell_instance")
        if not isinstance(cell_instance, Mapping):
            raise ValueError("cell instance record must contain a 'cell_instance' object.")
        provenance = record.get("provenance", {})
        if not isinstance(provenance, Mapping):
            provenance = {}
        dataset_ids = provenance.get("dataset_ids")
        if not isinstance(dataset_ids, list):
            dataset_ids = []
        notes = record.get("notes")
        if not isinstance(notes, list):
            notes = []
        return cls(
            schema_version=str(record.get("schema_version", "1.0.0")),
            id=str(cell_instance["id"]),
            name=str(cell_instance.get("serial_number") or cell_instance["id"].rstrip("/").split("/")[-1]),
            cell_type_id=str(cell_instance["type_id"]),
            serial_number=cell_instance.get("serial_number"),
            batch_id=cell_instance.get("batch_id"),
            manufactured_at=cell_instance.get("manufactured_at"),
            measured=dict(record.get("measured", {})) if isinstance(record.get("measured"), Mapping) else {},
            dataset_ids=[str(item) for item in dataset_ids],
            source=ProvenanceInfo(
                type=provenance.get("source_type"),
                url=provenance.get("source_url"),
                retrieved_at=provenance.get("retrieved_at"),
            ),
            comment=[str(item) for item in notes],
        )

    def to_record(self) -> dict[str, Any]:
        if self.id is None:
            raise ValueError("CellInstance.id is required before serialization. Use battinfo.publish(...) to finalize IDs.")
        if self.cell_type_id is None:
            raise ValueError("CellInstance.cell_type_id is required before serialization.")
        record: dict[str, Any] = {
            "schema_version": self.schema_version,
            "cell_instance": {
                "id": self.id,
                "short_id": _short_id(self.id),
                "type_id": self.cell_type_id,
                "serial_number": self.serial_number,
                "batch_id": self.batch_id,
                "manufactured_at": self.manufactured_at,
            },
            "provenance": {},
        }
        if self.measured:
            record["measured"] = self.measured
        if self.dataset_ids:
            record["provenance"]["dataset_ids"] = list(self.dataset_ids)
            record["provenance"]["dataset_id"] = self.dataset_ids[0]
            record["datasets"] = [{"id": dataset_id, "role": "raw"} for dataset_id in self.dataset_ids]
        if self.source.type is not None:
            record["provenance"]["source_type"] = self.source.type
        if self.source.url is not None:
            record["provenance"]["source_url"] = self.source.url
        if self.source.retrieved_at is not None:
            record["provenance"]["retrieved_at"] = self.source.retrieved_at
        record["cell_instance"] = {key: value for key, value in record["cell_instance"].items() if value is not None}
        if self.comment:
            record["notes"] = list(self.comment)
        return record


class Test(BundleJsonModel):
    default_filename: ClassVar[str] = TEST_FILENAME

    kind: str = "Test"
    __test__ = False
    id: str | None = None
    name: str | None = None
    test_kind: str = Field(validation_alias=AliasChoices("test_kind", "kind"))
    cell_instance_id: str | None = None
    cell: CellInstance | None = Field(default=None, exclude=True, repr=False)
    description: str | None = None
    status: str | None = None
    protocol: ProtocolInfo = Field(default_factory=ProtocolInfo)
    instrument: str | None = None
    started_at: int | str | None = None
    ended_at: int | str | None = None
    dataset_ids: list[str] = Field(default_factory=list)
    source: ProvenanceInfo = Field(default_factory=ProvenanceInfo)
    comment: list[str] = Field(default_factory=list)

    @field_validator("protocol", mode="before")
    @classmethod
    def _coerce_protocol(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"name": value}
        return value

    @model_validator(mode="after")
    def _populate_links(self) -> Self:
        if self.cell_instance_id is None and self.cell is not None and self.cell.id is not None:
            self.cell_instance_id = self.cell.id
        if self.name is None:
            base = self.protocol.name or self.test_kind
            cell_name = self.cell.name if self.cell is not None else None
            self.name = f"{cell_name} {base}" if cell_name else base
        return self

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> Self:
        test = record.get("test")
        if not isinstance(test, Mapping):
            raise ValueError("test record must contain a 'test' object.")
        provenance = record.get("provenance", {})
        if not isinstance(provenance, Mapping):
            provenance = {}
        notes = record.get("notes")
        if not isinstance(notes, list):
            notes = []
        dataset_ids = test.get("dataset_ids")
        if not isinstance(dataset_ids, list):
            dataset_ids = []
        return cls(
            schema_version=str(record.get("schema_version", "1.0.0")),
            id=str(test["id"]),
            name=str(test["name"]),
            test_kind=str(test["kind"]),
            cell_instance_id=str(test["cell_id"]),
            description=test.get("description"),
            status=test.get("status"),
            protocol=ProtocolInfo(
                name=test.get("protocol_name"),
                url=test.get("protocol_url"),
            ),
            instrument=test.get("instrument_name"),
            started_at=test.get("started_at"),
            ended_at=test.get("ended_at"),
            dataset_ids=[str(item) for item in dataset_ids],
            source=ProvenanceInfo(
                type=provenance.get("source_type"),
                file=provenance.get("source_file"),
                url=provenance.get("source_url"),
                retrieved_at=provenance.get("retrieved_at"),
                workflow_version=provenance.get("workflow_version"),
            ),
            comment=[str(item) for item in notes],
        )

    def to_record(self) -> dict[str, Any]:
        if self.id is None:
            raise ValueError("Test.id is required before serialization. Use battinfo.publish(...) to finalize IDs.")
        if self.name is None:
            raise ValueError("Test.name is required before serialization.")
        if self.cell_instance_id is None:
            raise ValueError("Test.cell_instance_id is required before serialization.")
        record: dict[str, Any] = {
            "schema_version": self.schema_version,
            "test": {
                "id": self.id,
                "short_id": _short_id(self.id),
                "identifier": _identifier("test", self.id),
                "name": self.name,
                "kind": self.test_kind,
                "cell_id": self.cell_instance_id,
            },
            "provenance": {},
        }
        if self.description is not None:
            record["test"]["description"] = self.description
        if self.status is not None:
            record["test"]["status"] = self.status
        if self.protocol.name is not None:
            record["test"]["protocol_name"] = self.protocol.name
        if self.protocol.url is not None:
            record["test"]["protocol_url"] = self.protocol.url
        if self.instrument is not None:
            record["test"]["instrument_name"] = self.instrument
        if self.started_at is not None:
            record["test"]["started_at"] = self.started_at
        if self.ended_at is not None:
            record["test"]["ended_at"] = self.ended_at
        if self.dataset_ids:
            record["test"]["dataset_ids"] = list(self.dataset_ids)
        if self.source.type is not None:
            record["provenance"]["source_type"] = self.source.type
        if self.source.file is not None:
            record["provenance"]["source_file"] = self.source.file
        if self.source.url is not None:
            record["provenance"]["source_url"] = self.source.url
        if self.source.retrieved_at is not None:
            record["provenance"]["retrieved_at"] = self.source.retrieved_at
        if self.source.workflow_version is not None:
            record["provenance"]["workflow_version"] = self.source.workflow_version
        if self.comment:
            record["notes"] = list(self.comment)
        return record


class Dataset(BundleJsonModel):
    default_filename: ClassVar[str] = DATASET_FILENAME

    kind: str = "Dataset"
    id: str | None = None
    name: str | None = None
    description: str | None = None
    license: str | None = None
    data_format: str | None = None
    dataset_path: str | None = Field(default=None, validation_alias=AliasChoices("dataset_path", "path"))
    access_url: str | None = None
    download_url: str | None = None
    created_at: int | str | None = None
    checksum: ChecksumInfo = Field(default_factory=ChecksumInfo)
    cell_instance_id: str | None = None
    test_id: str | None = None
    test: Test | None = Field(default=None, exclude=True, repr=False)
    cell: CellInstance | None = Field(default=None, exclude=True, repr=False)
    source: ProvenanceInfo = Field(default_factory=ProvenanceInfo)
    comment: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _populate_links(self) -> Self:
        if self.test_id is None and self.test is not None and self.test.id is not None:
            self.test_id = self.test.id
        if self.cell_instance_id is None:
            if self.cell is not None and self.cell.id is not None:
                self.cell_instance_id = self.cell.id
            elif self.test is not None and self.test.cell_instance_id is not None:
                self.cell_instance_id = self.test.cell_instance_id
        if self.name is None:
            self.name = (
                Path(self.dataset_path).name
                if self.dataset_path is not None
                else self.access_url or _id_tail(self.id)
            )
        return self

    @classmethod
    def from_record(cls, record: Mapping[str, Any], *, dataset_path: str | None = None) -> Self:
        dataset = record.get("dataset")
        if not isinstance(dataset, Mapping):
            raise ValueError("dataset record must contain a 'dataset' object.")
        provenance = record.get("provenance", {})
        if not isinstance(provenance, Mapping):
            provenance = {}
        about = dataset.get("about")
        related_cell_id = None
        related_test_id = None
        if isinstance(about, list):
            for item in about:
                if isinstance(item, str) and "/cell/" in item and related_cell_id is None:
                    related_cell_id = item
                if isinstance(item, str) and "/test/" in item and related_test_id is None:
                    related_test_id = item
        distribution = dataset.get("distribution")
        checksum = ChecksumInfo()
        data_format = None
        download_url = None
        if isinstance(distribution, list) and distribution and isinstance(distribution[0], Mapping):
            first = distribution[0]
            data_format = first.get("encodingFormat")
            download_url = first.get("contentUrl")
            checksum_obj = first.get("checksum")
            if isinstance(checksum_obj, Mapping):
                checksum = ChecksumInfo(
                    algorithm=checksum_obj.get("algorithm"),
                    value=checksum_obj.get("value"),
                )
        notes = record.get("notes")
        if not isinstance(notes, list):
            notes = []
        return cls(
            schema_version=str(record.get("schema_version", "1.0.0")),
            id=str(dataset["id"]),
            name=str(dataset.get("name") or dataset.get("title") or dataset["id"]),
            description=dataset.get("description"),
            license=dataset.get("license"),
            data_format=data_format,
            dataset_path=dataset_path,
            access_url=dataset.get("url"),
            download_url=download_url,
            created_at=dataset.get("dateCreated"),
            checksum=checksum,
            cell_instance_id=related_cell_id,
            test_id=related_test_id,
            source=ProvenanceInfo(
                type=provenance.get("source_type"),
                url=provenance.get("source_url"),
                retrieved_at=provenance.get("retrieved_at"),
                curated_by=provenance.get("curated_by"),
            ),
            comment=[str(item) for item in notes],
        )

    def to_record(self) -> dict[str, Any]:
        if self.id is None:
            raise ValueError("Dataset.id is required before serialization. Use battinfo.publish(...) to finalize IDs.")
        if self.name is None:
            raise ValueError("Dataset.name is required before serialization.")
        dataset_obj: dict[str, Any] = {
            "id": self.id,
            "short_id": _short_id(self.id),
            "identifier": _identifier("dataset", self.id),
            "name": self.name,
        }
        if self.description is not None:
            dataset_obj["description"] = self.description
        if self.license is not None:
            dataset_obj["license"] = self.license
        if self.access_url is not None:
            dataset_obj["url"] = self.access_url
        if self.created_at is not None:
            dataset_obj["dateCreated"] = self.created_at
            dataset_obj["dateModified"] = self.created_at
            dataset_obj["datePublished"] = self.created_at
        about: list[str] = []
        if self.cell_instance_id is not None:
            about.append(self.cell_instance_id)
        if self.test_id is not None:
            about.append(self.test_id)
        if about:
            dataset_obj["about"] = about
        if self.download_url is not None or self.data_format is not None or self.checksum.value is not None:
            dist: dict[str, Any] = {}
            if self.download_url is not None:
                dist["contentUrl"] = self.download_url
            elif self.access_url is not None:
                dist["contentUrl"] = self.access_url
            if self.data_format is not None:
                dist["encodingFormat"] = self.data_format
            if self.checksum.value is not None:
                dist["checksum"] = {
                    "algorithm": self.checksum.algorithm,
                    "value": self.checksum.value,
                }
            dataset_obj["distribution"] = [dist]

        record: dict[str, Any] = {
            "schema_version": self.schema_version,
            "dataset": dataset_obj,
            "provenance": {},
        }
        if self.source.type is not None:
            record["provenance"]["source_type"] = self.source.type
        if self.source.url is not None:
            record["provenance"]["source_url"] = self.source.url
        if self.source.retrieved_at is not None:
            record["provenance"]["retrieved_at"] = self.source.retrieved_at
        if self.source.curated_by is not None:
            record["provenance"]["curated_by"] = self.source.curated_by
        if self.comment:
            record["notes"] = list(self.comment)
        return record


class BattinfoBundle(BundleJsonModel):
    default_filename: ClassVar[str] = BUNDLE_MANIFEST_FILENAME

    kind: str = "BattinfoBundle"
    bundle_name: str | None = None
    cell_specification: CellSpecification | None = None
    cell_type: CellType
    cell_instance: CellInstance
    test: Test
    dataset: Dataset
    comment: list[str] = Field(default_factory=list)

    def manifest_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "cell_type_file": CELL_TYPE_FILENAME,
            "cell_instance_file": CELL_INSTANCE_FILENAME,
            "test_file": TEST_FILENAME,
            "dataset_file": DATASET_FILENAME,
        }
        if self.cell_specification is not None:
            payload["cell_specification_file"] = CELL_SPECIFICATION_FILENAME
        if self.bundle_name is not None:
            payload["bundle_name"] = self.bundle_name
        if self.comment:
            payload["comment"] = list(self.comment)
        return payload

    def to_directory(self, directory: PathLike) -> Path:
        root = _as_path(directory)
        root.mkdir(parents=True, exist_ok=True)
        if self.cell_specification is not None:
            self.cell_specification.to_path(root / CELL_SPECIFICATION_FILENAME)
        self.cell_type.to_path(root / CELL_TYPE_FILENAME)
        self.cell_instance.to_path(root / CELL_INSTANCE_FILENAME)
        self.test.to_path(root / TEST_FILENAME)
        self.dataset.to_path(root / DATASET_FILENAME)
        _write_json(root / BUNDLE_MANIFEST_FILENAME, self.manifest_json())
        return root

    @classmethod
    def from_directory(cls, directory: PathLike) -> Self:
        root = _as_path(directory)
        manifest = _read_json(root / BUNDLE_MANIFEST_FILENAME)
        cell_specification_file = manifest.get("cell_specification_file")
        cell_specification = None
        if isinstance(cell_specification_file, str):
            spec_path = root / cell_specification_file
            if spec_path.exists():
                cell_specification = CellSpecification.from_path(spec_path)
        return cls(
            schema_version=str(manifest.get("schema_version", "1.0.0")),
            bundle_name=manifest.get("bundle_name"),
            cell_specification=cell_specification,
            cell_type=CellType.from_path(root / str(manifest.get("cell_type_file", CELL_TYPE_FILENAME))),
            cell_instance=CellInstance.from_path(root / str(manifest.get("cell_instance_file", CELL_INSTANCE_FILENAME))),
            test=Test.from_path(root / str(manifest.get("test_file", TEST_FILENAME))),
            dataset=Dataset.from_path(root / str(manifest.get("dataset_file", DATASET_FILENAME))),
            comment=[str(item) for item in manifest.get("comment", [])] if isinstance(manifest.get("comment"), list) else [],
        )

    @classmethod
    def from_jsonld(cls, source: Mapping[str, Any] | PathLike) -> Self:
        payload = _read_json(_as_path(source)) if isinstance(source, (str, Path)) else dict(source)
        graph = _graph_nodes(payload)
        graph_by_id = {
            str(node["@id"]): node
            for node in graph
            if isinstance(node.get("@id"), str)
        }

        for node in graph:
            # Backward-compatible reader for older bundle-style JSON-LD payloads.
            if _node_has_type(node, "battinfo:MetadataBundle"):
                return cls(
                    bundle_name=node.get("schema:name") if isinstance(node.get("schema:name"), str) else None,
                    cell_specification=CellSpecification.from_json(node["battinfo:cellSpecificationRecord"])
                    if isinstance(node.get("battinfo:cellSpecificationRecord"), Mapping)
                    else None,
                    cell_type=CellType.from_json(node["battinfo:cellTypeRecord"]),
                    cell_instance=CellInstance.from_json(node["battinfo:cellInstanceRecord"]),
                    test=Test.from_json(node["battinfo:testRecord"]),
                    dataset=Dataset.from_json(node["battinfo:datasetRecord"]),
                    comment=_text_list(node.get("schema:description")),
                )

        cell_instance_node = next((node for node in graph if _node_has_type(node, "battinfo:BatteryCellInstance")), None)
        if cell_instance_node is None:
            cell_instance_node = next(
                (node for node in graph if _node_has_type(node, "schema:IndividualProduct")),
                None,
            )
        cell_type_id = None
        if cell_instance_node is not None:
            cell_type_id = next((value for value in _type_values(cell_instance_node) if "/cell-type/" in value), None)
            if cell_type_id is None:
                cell_type_id = _ref_id(cell_instance_node.get("schema:isVariantOf"))
        cell_type_node = graph_by_id.get(cell_type_id) if cell_type_id is not None else None
        if cell_type_node is None:
            cell_type_node = next(
                (
                    node
                    for node in graph
                    if _node_has_type(node, OWL_CLASS_IRI)
                    or _node_has_type(node, "schema:ProductModel")
                    or _node_has_type(node, "BatteryCell")
                ),
                None,
            )
        test_node = next((node for node in graph if _node_has_type(node, "battinfo:BatteryCellTest")), None)
        if test_node is None:
            test_node = next(
                (
                    node
                    for node in graph
                    if _node_has_type(node, "schema:Action")
                    and (_ref_id(node.get("schema:object")) or _ref_id(node.get("schema:about")))
                ),
                None,
            )
        dataset_node = next(
            (
                node
                for node in graph
                if _node_has_type(node, "schema:Dataset")
                and (
                    (
                        node.get("battinfo:aboutCell") is not None
                        and node.get("battinfo:aboutTest") is not None
                    )
                    or (
                        any("/cell/" in ref_id for ref_id in _ref_ids(node.get("schema:about")))
                        and any("/test/" in ref_id for ref_id in _ref_ids(node.get("schema:about")))
                    )
                )
            ),
            None,
        )

        if cell_type_node is None or cell_instance_node is None or test_node is None or dataset_node is None:
            raise ValueError("Could not reconstruct BattinfoBundle from JSON-LD graph.")

        cell_specification_node = next(
            (
                node
                for node in graph
                if _node_has_type(node, "schema:CreativeWork")
                and (
                    node.get("schema:additionalType") == "cell-specification"
                    or _ref_id(node.get("schema:about")) == str(cell_type_node.get("@id"))
                )
            ),
            None,
        )
        if cell_specification_node is None:
            spec_ref_id = _ref_id(cell_type_node.get("schema:isBasedOn"))
            candidate = graph_by_id.get(spec_ref_id) if spec_ref_id is not None else None
            if isinstance(candidate, Mapping) and _node_has_type(candidate, "schema:CreativeWork"):
                cell_specification_node = candidate

        manufacturer_obj = cell_type_node.get("schema:manufacturer")
        if not isinstance(manufacturer_obj, Mapping) and cell_specification_node is not None:
            manufacturer_obj = cell_specification_node.get("schema:manufacturer")
        manufacturer = (
            manufacturer_obj.get("schema:name")
            if isinstance(manufacturer_obj, Mapping)
            else manufacturer_obj
        )
        properties: dict[str, Any] = {}
        property_source = cell_specification_node if cell_specification_node is not None else cell_type_node
        for item in property_source.get("hasProperty", []):
            if isinstance(item, Mapping):
                extracted = _extract_property_item(item)
                if extracted is not None:
                    key, value = extracted
                    properties[key] = value

        source_obj = (
            cell_specification_node.get("schema:isBasedOn")
            if cell_specification_node is not None
            else cell_type_node.get("schema:isBasedOn")
        )
        if not isinstance(source_obj, Mapping):
            source_obj = {}
        subclass_ids = _subclass_ref_ids(cell_type_node)
        format_value = (
            "coin"
            if "CoinCell" in subclass_ids or _node_has_type(cell_instance_node, "CoinCell")
            else "cylindrical"
            if "CylindricalBattery" in subclass_ids or _node_has_type(cell_instance_node, "CylindricalBattery")
            else "pouch"
            if "PouchCell" in subclass_ids or _node_has_type(cell_instance_node, "PouchCell")
            else "prismatic"
            if "PrismaticBattery" in subclass_ids or _node_has_type(cell_instance_node, "PrismaticBattery")
            else str(cell_type_node.get("schema:category") or cell_specification_node.get("schema:category") if isinstance(cell_specification_node, Mapping) else "unknown")
        )
        cell_type = CellType(
            id=str(cell_type_node["@id"]),
            name=str(cell_type_node.get("schema:name") or f"{manufacturer} {cell_type_node.get('schema:model') or 'unknown'}"),
            manufacturer=str(manufacturer or "unknown"),
            model=str(
                cell_type_node.get("schema:model")
                or (cell_specification_node.get("schema:model") if isinstance(cell_specification_node, Mapping) else None)
                or cell_type_node.get("schema:name")
                or "unknown"
            ),
            format=format_value,
            chemistry=str(
                cell_type_node.get("schema:material")
                or (cell_specification_node.get("schema:material") if isinstance(cell_specification_node, Mapping) else None)
                or "unknown"
            ),
            size_code=cell_type_node.get("schema:size") or (cell_specification_node.get("schema:size") if isinstance(cell_specification_node, Mapping) else None),
            cell_specification_id=str(cell_specification_node.get("@id")) if isinstance(cell_specification_node, Mapping) else None,
            nominal_properties=properties,
            source=ProvenanceInfo(
                type=source_obj.get("schema:additionalType"),
                name=source_obj.get("schema:name"),
                file=source_obj.get("schema:identifier"),
                url=source_obj.get("schema:url") or source_obj.get("@id"),
                retrieved_at=source_obj.get("schema:dateModified"),
                workflow_version=source_obj.get("schema:version"),
                comment=source_obj.get("schema:description"),
            ),
            comment=_text_list(cell_type_node.get("schema:description")),
        )
        cell_specification = None
        if isinstance(cell_specification_node, Mapping):
            spec_manufacturer_obj = cell_specification_node.get("schema:manufacturer")
            spec_manufacturer = (
                spec_manufacturer_obj.get("schema:name")
                if isinstance(spec_manufacturer_obj, Mapping)
                else spec_manufacturer_obj
            )
            cell_specification = CellSpecification(
                id=str(cell_specification_node["@id"]),
                manufacturer=str(spec_manufacturer or manufacturer or "unknown"),
                model=str(cell_specification_node.get("schema:model") or cell_type.model),
                format=str(cell_specification_node.get("schema:category") or cell_type.format),
                chemistry=str(cell_specification_node.get("schema:material") or cell_type.chemistry),
                size_code=cell_specification_node.get("schema:size"),
                properties=properties,
                specification_comment=_text_list(cell_specification_node.get("schema:description")),
                source=ProvenanceInfo(
                    type=source_obj.get("schema:additionalType"),
                    name=source_obj.get("schema:name"),
                    file=source_obj.get("schema:identifier"),
                    url=source_obj.get("schema:url") or source_obj.get("@id"),
                    retrieved_at=source_obj.get("schema:dateModified"),
                    workflow_version=source_obj.get("schema:version"),
                    comment=source_obj.get("schema:description"),
                ),
            )
        cell_instance = CellInstance(
            id=str(cell_instance_node["@id"]),
            name=str(cell_instance_node.get("schema:name") or cell_instance_node["@id"]),
            cell_type_id=str(cell_type_id or cell_type.id),
            serial_number=cell_instance_node.get("schema:serialNumber"),
            batch_id=cell_instance_node.get("battinfo:batchId"),
        )
        protocol_name, test_description = _protocol_from_description(test_node.get("schema:description"))
        instrument_name = _instrument_name(test_node.get("schema:instrument"))
        test = Test(
            id=str(test_node["@id"]),
            name=str(test_node.get("schema:name") or test_node["@id"]),
            test_kind=str(test_node.get("battinfo:testKind") or test_node.get("schema:additionalType") or "other"),
            cell_instance_id=str(
                _ref_id(test_node.get("battinfo:aboutCell"))
                or _ref_id(test_node.get("schema:object"))
                or _ref_id(test_node.get("schema:about"))
                or cell_instance.id
            ),
            description=test_description,
            status=test_node.get("schema:creativeWorkStatus") or test_node.get("schema:actionStatus"),
            protocol=ProtocolInfo(
                name=protocol_name,
            ),
            instrument=instrument_name,
            dataset_ids=[
                ref_id
                for ref_id in (
                    [_ref_id(item) for item in test_node.get("battinfo:hasDataset", [])]
                    + _ref_ids(test_node.get("schema:result"))
                )
                if ref_id is not None
            ],
            started_at=test_node.get("schema:startTime"),
        )
        dataset_distribution = dataset_node.get("schema:distribution")
        first_distribution = dataset_distribution[0] if isinstance(dataset_distribution, list) and dataset_distribution else {}
        dataset = Dataset(
            id=str(dataset_node["@id"]),
            name=str(dataset_node.get("schema:name") or dataset_node["@id"]),
            description=dataset_node.get("schema:description"),
            license=dataset_node.get("schema:license"),
            data_format=first_distribution.get("schema:encodingFormat") if isinstance(first_distribution, Mapping) else None,
            access_url=dataset_node.get("schema:url"),
            download_url=first_distribution.get("schema:contentUrl") if isinstance(first_distribution, Mapping) else None,
            cell_instance_id=(
                _ref_id(dataset_node.get("battinfo:aboutCell"))
                or next((ref_id for ref_id in _ref_ids(dataset_node.get("schema:about")) if "/cell/" in ref_id), None)
            ),
            test_id=(
                _ref_id(dataset_node.get("battinfo:aboutTest"))
                or next((ref_id for ref_id in _ref_ids(dataset_node.get("schema:about")) if "/test/" in ref_id), None)
            ),
        )
        return cls(
            bundle_name=dataset.name,
            cell_specification=cell_specification,
            cell_type=cell_type,
            cell_instance=cell_instance,
            test=test,
            dataset=dataset,
        )


def load_cell_specification(path: PathLike) -> CellSpecification:
    return CellSpecification.from_path(path)


__all__ = [
    "BUNDLE_MANIFEST_FILENAME",
    "BattinfoBundle",
    "CELL_INSTANCE_FILENAME",
    "CELL_SPECIFICATION_FILENAME",
    "CELL_TYPE_FILENAME",
    "Coating",
    "CellInstance",
    "CellSpecification",
    "CellType",
    "ChecksumInfo",
    "CurrentCollector",
    "DATASET_FILENAME",
    "Dataset",
    "Electrode",
    "Electrolyte",
    "MaterialComponent",
    "load_cell_specification",
    "ProvenanceInfo",
    "ProtocolInfo",
    "Salt",
    "Separator",
    "SolventMixture",
    "TEST_FILENAME",
    "Test",
]
