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
    """Describe the physical assembly of a battery cell.

    Args:
        assembly_type: How layers are arranged, e.g. ``"wound"`` or ``"stacked"``.
        layering: Stacking pattern, e.g. ``"jelly-roll"`` or ``"z-fold"``.
        layer_count: Number of electrode layers or winding turns.
        comment: Free-text note about the construction.
    """
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
    """Build a provenance record describing where data came from.

    Args:
        type: Source category, e.g. ``"datasheet"``, ``"measurement"``, ``"lab"``.
        name: Human-readable name for the source document or dataset.
        file: Relative path or filename of the source file.
        url: URL where the source can be retrieved.
        citation: DOI URL or bibliographic reference string.
        retrieved_at: Unix timestamp (int) or ISO 8601 string of retrieval time.
        workflow_version: Version of the ingestion pipeline used to process the source.
        file_hash: SHA-256 hex digest of the source file for integrity checking.
        curated_by: Name or identifier of the person who curated the data.
        comment: Free-text note about the provenance.
    """
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
    """Build a named material component with optional quantitative properties.

    The ``property`` keyword accepts a :class:`PropertySet` built with
    :func:`properties`.  Alternatively pass quantity dicts directly as keyword
    arguments (e.g. ``mass_fraction={"value": 90, "unit": "%"}``).

    Args:
        name: Material name, e.g. ``"LFP"``, ``"Graphite"``, ``"PVDF"``.
        property: Pre-built property set.  Mutually exclusive with ``**named_properties``.
        comment: Free-text note about the material.
        **named_properties: Quantity dicts passed directly to :func:`properties`.
    """
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
    """Build a bill-of-materials for an electrode coating.

    Each argument accepts a bare material name string, a :class:`MaterialComponent`
    from :func:`material`, or a list of either.  Multiple active materials (blended
    cathodes) and multiple binders/additives are all supported.

    Args:
        active_material: Primary electrochemically active material(s).
        binder: Binder material(s), e.g. ``"PVDF"``, ``"CMC"``, ``"SBR"``.
        additive: Conductive additive(s), e.g. ``"Carbon black"``, ``"VGCF"``.
    """
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
    """Build a complete electrode description from a bill-of-materials.

    Args:
        bom: Coating composition built with :func:`bom`.
        loading: Active-material areal loading quantity dict, e.g.
            ``{"value": 12.5, "unit": "mg/cm2"}``.
        calendered_density: Post-calendering coating density quantity dict.
        current_collector: Current-collector material name, e.g. ``"Aluminium foil"``.
        current_collector_thickness: Thickness quantity dict for the current collector.
        coating_properties: Additional coating-level properties (thickness, porosity, etc.).
        properties: Electrode-level properties (areal capacity, etc.).
        coating_comment: Free-text note about the coating.
        comment: Free-text note about the electrode as a whole.
    """
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
    """Build an electrolyte description from solvent, salt, and additive components.

    Args:
        family: Electrolyte family: ``"organic"``, ``"aqueous"``, ``"ionic_liquid"``,
            ``"solid"``, ``"gel"``, ``"hybrid"``, or ``"unknown"``.
        solvents: Solvent component(s) — name string(s) or :class:`MaterialComponent`
            objects.  Use :func:`material` to attach volume-fraction properties.
        salt: Salt name string or pre-built :class:`Salt` object.
        salt_concentration: Concentration quantity dict, e.g.
            ``{"value": 1.0, "unit": "mol/L"}``.  Only used when ``salt`` is a string.
        additives: Optional electrolyte additive(s).
        properties: Bulk electrolyte properties (ionic conductivity, viscosity, etc.).
        solvent_comment: Free-text note about the solvent mixture.
        comment: Free-text note about the electrolyte as a whole.
    """
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
    """Build a separator description.

    Args:
        material: Base material name, e.g. ``"polypropylene"``, ``"glass fibre"``.
        thickness: Thickness quantity dict, e.g. ``{"value": 25, "unit": "mm"}``.
        properties: Additional separator properties (porosity, Gurley number, etc.).
            ``thickness`` is merged into this set if both are provided.
        comment: Free-text note about the separator.
    """
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
    coin_hardware: dict[str, Any] | None = None,
    source: ProvenanceInfo | None = None,
    specification_comment: str | list[str] | None = None,
    comment: str | list[str] | None = None,
) -> CellSpecification:
    """Build a complete cell descriptor specification.

    This is the primary authoring entry point for detailed cell descriptions.
    Combine it with :func:`electrode`, :func:`electrolyte_recipe`, and
    :func:`separator_spec` to build a full description ready for
    :meth:`Workspace.describe_cell`.

    Args:
        id: Canonical BattINFO cell-type IRI, e.g.
            ``"https://w3id.org/battinfo/cell/xxxx-xxxx-xxxx-xxxx"``.
        manufacturer: Manufacturer name string.
        model: Model/product code string.
        format: Cell format: ``"coin"``, ``"cylindrical"``, ``"pouch"``,
            ``"prismatic"``, or ``"other"``.
        chemistry: Electrochemistry family, e.g. ``"li-ion"``, ``"li-primary"``.
        positive_electrode_basis: Positive electrode chemistry shortcode,
            e.g. ``"lfp"``, ``"nmc"``, ``"nca"``.
        negative_electrode_basis: Negative electrode chemistry shortcode,
            e.g. ``"graphite"``, ``"lithium"``.
        size_code: IEC or custom size code, e.g. ``"R18650"``, ``"P0035"``.
        construction: Assembly description from :func:`construction`.
        properties: Cell-level quantitative properties (capacity, voltage, etc.).
        positive_electrode: Positive electrode from :func:`electrode`.
        negative_electrode: Negative electrode from :func:`electrode`.
        electrolyte: Electrolyte from :func:`electrolyte_recipe`.
        separator: Separator from :func:`separator_spec`.
        coin_hardware: Dict of coin-cell-specific hardware (case, lid, spring, spacer).
        source: Provenance record from :func:`source`.
        specification_comment: Note(s) about the specification itself.
        comment: General note(s) about the cell.
    """
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
        coin_hardware=coin_hardware or {},
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
