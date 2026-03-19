from __future__ import annotations

from typing import Any, Sequence

from battinfo.bundle import (
    BillOfMaterials,
    CellConstruction,
    CellSpecification,
    Coating,
    CurrentCollector,
    Electrode,
    Electrolyte,
    MaterialComponent,
    PropertySet,
    ProvenanceInfo,
    Salt,
    Separator,
    SolventMixture,
)


def properties(**items: Any) -> PropertySet:
    """Build a typed property bag without writing raw dict literals."""
    return PropertySet(**items)


def construction(
    *,
    assembly_type: str | None = None,
    layering: str | None = None,
    layer_count: int | None = None,
    comment: str | None = None,
) -> CellConstruction:
    return CellConstruction(
        assembly_type=assembly_type,
        layering=layering,
        layer_count=layer_count,
        comment=comment,
    )


def source(
    *,
    type: str | None = None,
    name: str | None = None,
    file: str | None = None,
    url: str | None = None,
    citation: str | None = None,
    retrieved_at: int | str | None = None,
    workflow_version: str | None = None,
    file_hash: str | None = None,
    curated_by: str | None = None,
    comment: str | None = None,
) -> ProvenanceInfo:
    return ProvenanceInfo(
        type=type,
        name=name,
        file=file,
        url=url,
        citation=citation,
        retrieved_at=retrieved_at,
        workflow_version=workflow_version,
        file_hash=file_hash,
        curated_by=curated_by,
        comment=comment,
    )


def material(
    name: str,
    *,
    property: PropertySet | None = None,
    comment: str | None = None,
    **named_properties: Any,
) -> MaterialComponent:
    property_set = property or properties(**named_properties)
    return MaterialComponent(
        name=name,
        property=property_set,
        comment=comment,
    )


def _component_list(
    value: str | MaterialComponent | Sequence[str | MaterialComponent] | None,
) -> list[MaterialComponent]:
    if value is None:
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        items = value
    else:
        items = [value]
    out: list[MaterialComponent] = []
    for item in items:
        if isinstance(item, MaterialComponent):
            out.append(item)
        else:
            out.append(material(str(item)))
    return out


def bom(
    *,
    active_material: str | MaterialComponent | Sequence[str | MaterialComponent] | None = None,
    binder: str | MaterialComponent | Sequence[str | MaterialComponent] | None = None,
    additive: str | MaterialComponent | Sequence[str | MaterialComponent] | None = None,
) -> BillOfMaterials:
    return BillOfMaterials(
        active_material=_component_list(active_material),
        binder=_component_list(binder),
        additive=_component_list(additive),
    )


def electrode(
    *,
    bom: BillOfMaterials,
    loading: dict[str, Any] | None = None,
    calendered_density: dict[str, Any] | None = None,
    current_collector: str | None = None,
    current_collector_thickness: dict[str, Any] | None = None,
    coating_properties: PropertySet | None = None,
    properties: PropertySet | None = None,
    coating_comment: str | None = None,
    comment: str | None = None,
) -> Electrode:
    resolved_coating_properties = coating_properties or PropertySet()
    if loading is not None:
        resolved_coating_properties.loading = loading
    if calendered_density is not None:
        resolved_coating_properties.calendered_density = calendered_density

    collector = None
    if current_collector is not None or current_collector_thickness is not None:
        collector_properties = PropertySet()
        if current_collector_thickness is not None:
            collector_properties.thickness = current_collector_thickness
        collector = CurrentCollector(
            name=current_collector,
            property=collector_properties,
        )

    return Electrode(
        coating=Coating(
            component=bom,
            property=resolved_coating_properties,
            comment=coating_comment,
        ),
        current_collector=collector,
        property=properties or PropertySet(),
        comment=comment,
    )


def electrolyte_recipe(
    *,
    family: str,
    solvents: str | MaterialComponent | Sequence[str | MaterialComponent] | None = None,
    salt: str | Salt | None = None,
    salt_concentration: dict[str, Any] | None = None,
    additives: str | MaterialComponent | Sequence[str | MaterialComponent] | None = None,
    properties: PropertySet | None = None,
    solvent_comment: str | None = None,
    comment: str | None = None,
) -> Electrolyte:
    if isinstance(salt, Salt):
        salt_obj = salt
    elif isinstance(salt, str):
        salt_properties = PropertySet()
        if salt_concentration is not None:
            salt_properties.concentration = salt_concentration
        salt_obj = Salt(name=salt, property=salt_properties)
    else:
        salt_obj = None

    solvent_components = _component_list(solvents)
    solvent_mixture = None
    if solvent_components:
        solvent_mixture = SolventMixture(component=solvent_components, comment=solvent_comment)

    return Electrolyte(
        family=family,
        solvent_mixture=solvent_mixture,
        salt=salt_obj,
        additive=_component_list(additives),
        property=properties or PropertySet(),
        comment=comment,
    )


def separator_spec(
    *,
    material: str,
    thickness: dict[str, Any] | None = None,
    properties: PropertySet | None = None,
    comment: str | None = None,
) -> Separator:
    resolved_properties = properties or PropertySet()
    if thickness is not None:
        resolved_properties.thickness = thickness
    return Separator(material=material, property=resolved_properties, comment=comment)


def cell_description(
    *,
    id: str,
    manufacturer: str,
    model: str,
    format: str,
    chemistry: str,
    positive_electrode_basis: str | None = None,
    negative_electrode_basis: str | None = None,
    size_code: str | None = None,
    construction: CellConstruction | None = None,
    properties: PropertySet | None = None,
    positive_electrode: Electrode | None = None,
    negative_electrode: Electrode | None = None,
    electrolyte: Electrolyte | None = None,
    separator: Separator | None = None,
    source: ProvenanceInfo | None = None,
    specification_comment: str | list[str] | None = None,
    comment: str | list[str] | None = None,
) -> CellSpecification:
    specification_comments = (
        [specification_comment]
        if isinstance(specification_comment, str)
        else list(specification_comment or [])
    )
    comments = [comment] if isinstance(comment, str) else list(comment or [])
    return CellSpecification(
        id=id,
        manufacturer=manufacturer,
        model=model,
        format=format,
        chemistry=chemistry,
        positive_electrode_basis=positive_electrode_basis,
        negative_electrode_basis=negative_electrode_basis,
        size_code=size_code,
        construction=construction or CellConstruction(),
        properties=properties or PropertySet(),
        positive_electrode=positive_electrode,
        negative_electrode=negative_electrode,
        electrolyte=electrolyte,
        separator=separator,
        source=source or ProvenanceInfo(),
        specification_comment=specification_comments,
        comment=comments,
    )


__all__ = [
    "bom",
    "cell_description",
    "construction",
    "electrode",
    "electrolyte_recipe",
    "material",
    "properties",
    "separator_spec",
    "source",
]
