from __future__ import annotations

from typing import Any, Sequence

from battinfo.bundle import (
    BillOfMaterials,
    Case,
    CellConstruction,
    CellSpec,
    Coating,
    CurrentCollector,
    CurrentCollectorTab,
    Electrode,
    Electrolyte,
    HardwarePart,
    Housing,
    MaterialComponent,
    PropertySet,
    ProvenanceInfo,
    Salt,
    Seal,
    Separator,
    SolventMixture,
    Terminal,
)


def properties(**items: Any) -> PropertySet:
    """Build a typed property bag without writing raw dict literals."""
    return PropertySet(**items)


def construction(
    *,
    assembly_type: str | None = None,
    layering: str | None = None,
    layer_count: int | None = None,
    cathode_sheet_count: int | None = None,
    anode_sheet_count: int | None = None,
    separator_sheet_count: int | None = None,
    winding_turns: float | None = None,
    electrode_length: dict[str, Any] | None = None,
    jellyroll_volume: dict[str, Any] | None = None,
    assembly_sequence: list[str] | None = None,
    comment: str | None = None,
) -> CellConstruction:
    """Describe the physical assembly of a battery cell.

    Args:
        assembly_type: How layers are arranged, e.g. ``"wound"`` or ``"stacked"``.
        layering: Stacking pattern: ``"single_layer"``, ``"multilayer"``, ``"not_applicable"``, or ``"unknown"`` (the schema enum); put finer detail (jelly-roll, z-fold, ...) in ``comment``.
        layer_count: Number of electrode layers or winding turns.
        cathode_sheet_count: Number of cathode sheets in the stack.
        anode_sheet_count: Number of anode sheets in the stack.
        separator_sheet_count: Number of separator sheets/layers.
        winding_turns: Number of jelly-roll winding turns.
        electrode_length: Wound-electrode strip length quantity dict (e.g. mm).
        jellyroll_volume: Jelly-roll volume quantity dict (e.g. cm3).
        assembly_sequence: Ordered list of assembly steps.
        comment: Free-text note about the construction.
    """
    return CellConstruction(
        assembly_type=assembly_type,
        layering=layering,
        layer_count=layer_count,
        cathode_sheet_count=cathode_sheet_count,
        anode_sheet_count=anode_sheet_count,
        separator_sheet_count=separator_sheet_count,
        winding_turns=winding_turns,
        electrode_length=electrode_length,
        jellyroll_volume=jellyroll_volume,
        assembly_sequence=assembly_sequence,
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
    molecular_formula: str | None = None,
    comment: str | None = None,
    **named_properties: Any,
) -> MaterialComponent:
    """Build a named material component with optional quantitative properties.

    The ``property`` keyword accepts a :class:`PropertySet` built with
    :func:`properties`.  Alternatively pass quantity dicts directly as keyword
    arguments (e.g. ``mass_fraction={"value": 90, "unit": "%"}``).

    Material-level quantities (active material ``mass``, ``loading``, ``d50_particle_size``)
    attach here, which is their canonical EMMO holder — e.g.
    ``material("NMC811", mass_fraction={...}, loading={...}, mass={...})``.

    Args:
        name: Material name, e.g. ``"LFP"``, ``"Graphite"``, ``"PVDF"``.
        property: Pre-built property set.  Mutually exclusive with ``**named_properties``.
        molecular_formula: Chemical formula string, e.g. ``"LiNi0.6Mn0.2Co0.2O2"``.
        comment: Free-text note about the material.
        **named_properties: Quantity dicts passed directly to :func:`properties`.
    """
    property_set = property or properties(**named_properties)
    return MaterialComponent(
        name=name,
        property=property_set,
        molecular_formula=molecular_formula,
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
    diameter: dict[str, Any] | None = None,
    mass: dict[str, Any] | None = None,
    theoretical_capacity: dict[str, Any] | None = None,
    rated_areal_discharge_capacity: dict[str, Any] | None = None,
    rated_specific_discharge_capacity: dict[str, Any] | None = None,
    tab: CurrentCollectorTab | None = None,
    coating_comment: str | None = None,
    comment: str | None = None,
) -> Electrode:
    """Build a complete electrode description from a bill-of-materials.

    Electrode-level quantities (``diameter``, ``mass``, ``theoretical_capacity``,
    ``rated_areal_discharge_capacity``, ``rated_specific_discharge_capacity``) attach to
    the electrode as a whole. Material-level quantities — including active-material
    ``loading`` — should be attached to the active material via :func:`material`, which is
    their canonical EMMO holder; the ``loading`` kwarg here remains for backward
    compatibility and places it on the coating.

    Args:
        bom: Coating composition built with :func:`bom`.
        loading: (legacy) coating active-mass loading quantity dict, e.g.
            ``{"value": 12.5, "unit": "mg/cm2"}``. Prefer ``material(loading=...)``.
        calendered_density: Post-calendering coating density quantity dict.
        current_collector: Current-collector material name, e.g. ``"Aluminium foil"``.
        current_collector_thickness: Thickness quantity dict for the current collector.
        coating_properties: Additional coating-level properties (thickness, porosity, etc.).
        properties: Additional electrode-level properties.
        diameter: Electrode diameter quantity dict, e.g. ``{"value": 14, "unit": "mm"}``.
        mass: Electrode (disc, with current collector) mass quantity dict.
        theoretical_capacity: Absolute theoretical capacity quantity dict (e.g. mAh).
        rated_areal_discharge_capacity: Areal rated discharge capacity (e.g. mAh/cm2).
        rated_specific_discharge_capacity: Specific rated discharge capacity (e.g. mAh/g).
        tab: Current-collector tab built with :func:`tab`.
        coating_comment: Free-text note about the coating.
        comment: Free-text note about the electrode as a whole.
    """
    resolved_coating_properties = coating_properties or PropertySet()
    if loading is not None:
        resolved_coating_properties.loading = loading
    if calendered_density is not None:
        resolved_coating_properties.calendered_density = calendered_density

    resolved_properties = properties or PropertySet()
    for prop_name, prop_value in (
        ("diameter", diameter),
        ("mass", mass),
        ("theoretical_capacity", theoretical_capacity),
        ("rated_areal_discharge_capacity", rated_areal_discharge_capacity),
        ("rated_specific_discharge_capacity", rated_specific_discharge_capacity),
    ):
        if prop_value is not None:
            setattr(resolved_properties, prop_name, prop_value)

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
        tab=tab,
        property=resolved_properties,
        comment=comment,
    )


def tab(
    *,
    material: str | None = None,
    manufacturer: str | None = None,
    supplier: str | None = None,
    product_id: str | None = None,
    properties: PropertySet | None = None,
    comment: str | None = None,
    **named_properties: Any,
) -> CurrentCollectorTab:
    """Build an electrode current-collector tab.

    Quantities (``width``/``thickness``/``length``/``weld_width``/``tape_width``) may be
    passed as keyword quantity dicts.
    """
    property_set = properties or PropertySet(**named_properties)
    return CurrentCollectorTab(
        material=material, manufacturer=manufacturer, supplier=supplier,
        product_id=product_id, property=property_set, comment=comment,
    )


def electrolyte_recipe(
    *,
    family: str,
    solvents: str | MaterialComponent | Sequence[str | MaterialComponent] | None = None,
    salt: str | Salt | MaterialComponent | None = None,
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
        salt: The salt, in the SAME form as a solvent entry — a
            :func:`material` component carrying its properties inline, e.g.
            ``salt=material("LiPF6", concentration={"value": 1.0, "unit": "mol/L"})``
            — or a bare name string, or a pre-built :class:`Salt`.
        salt_concentration: Concentration quantity dict; only used when ``salt``
            is a bare string (the ``material(...)`` form carries it inline).
        additives: Optional electrolyte additive(s).
        properties: Bulk electrolyte properties (ionic conductivity, viscosity, etc.).
        solvent_comment: Free-text note about the solvent mixture.
        comment: Free-text note about the electrolyte as a whole.
    """
    if isinstance(salt, Salt):
        salt_obj = salt
    elif isinstance(salt, MaterialComponent):
        # Salts are materials like any other component; accept the same
        # material(...) form as solvents. molecular_formula has no home on a
        # salt record (use cation=/anion= on Salt) — refuse rather than drop.
        if salt.molecular_formula is not None:
            raise ValueError(
                "salt components do not carry molecular_formula — build a "
                "Salt(name=..., cation=..., anion=...) instead."
            )
        salt_obj = Salt(
            name=salt.name,
            material_spec_id=salt.material_spec_id,
            manufacturer=salt.manufacturer,
            supplier=salt.supplier,
            product_id=salt.product_id,
            property=salt.property,
            comment=salt.comment,
        )
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
    diameter: dict[str, Any] | None = None,
    properties: PropertySet | None = None,
    comment: str | None = None,
) -> Separator:
    """Build a separator description.

    Args:
        material: Base material name, e.g. ``"polypropylene"``, ``"glass fibre"``.
        thickness: Thickness quantity dict, e.g. ``{"value": 25, "unit": "mm"}``.
        diameter: Diameter quantity dict, e.g. ``{"value": 19, "unit": "mm"}``.
        properties: Additional separator properties (porosity, Gurley number, etc.).
            ``thickness`` and ``diameter`` are merged into this set if provided.
        comment: Free-text note about the separator.
    """
    resolved_properties = properties or PropertySet()
    if thickness is not None:
        resolved_properties.thickness = thickness
    if diameter is not None:
        resolved_properties.diameter = diameter
    return Separator(material=material, property=resolved_properties, comment=comment)


def case(
    *,
    material: str | None = None,
    size_code: str | None = None,
    coating: str | None = None,
    manufacturer: str | None = None,
    supplier: str | None = None,
    product_id: str | None = None,
    properties: PropertySet | None = None,
    comment: str | None = None,
    **named_properties: Any,
) -> Case:
    """Build a cell case/can. JSON-LD ``@type`` is chosen from the cell format.

    Quantities (e.g. ``wall_thickness``, ``weight``, ``available_volume``,
    ``filling_ratio``) may be passed as keyword quantity dicts.
    """
    property_set = properties or PropertySet(**named_properties)
    return Case(
        material=material, size_code=size_code, coating=coating,
        manufacturer=manufacturer, supplier=supplier, product_id=product_id,
        property=property_set, comment=comment,
    )


def terminal(
    *,
    polarity: str | None = None,
    material: str | None = None,
    manufacturer: str | None = None,
    supplier: str | None = None,
    product_id: str | None = None,
    properties: PropertySet | None = None,
    comment: str | None = None,
    **named_properties: Any,
) -> Terminal:
    """Build a cell terminal (``width``/``thickness``/``weld_width``/``tape_width`` as quantities)."""
    property_set = properties or PropertySet(**named_properties)
    return Terminal(
        polarity=polarity, material=material, manufacturer=manufacturer,
        supplier=supplier, product_id=product_id, property=property_set, comment=comment,
    )


def seal(
    *,
    material: str | None = None,
    properties: PropertySet | None = None,
    comment: str | None = None,
    **named_properties: Any,
) -> Seal:
    """Build a pouch/prismatic seal (thickness quantities)."""
    property_set = properties or PropertySet(**named_properties)
    return Seal(material=material, property=property_set, comment=comment)


def hardware_part(
    type: str,
    *,
    material: str | None = None,
    coating: str | None = None,
    properties: PropertySet | None = None,
    comment: str | None = None,
    **named_properties: Any,
) -> HardwarePart:
    """Build a discrete hardware part (``"cap"``/``"lid"``/``"can"``/``"spring"``/``"spacer"``)."""
    property_set = properties or PropertySet(**named_properties)
    return HardwarePart(type=type, material=material, coating=coating, property=property_set, comment=comment)


def housing(
    *,
    case: Case | None = None,
    cap: HardwarePart | None = None,
    terminals: Terminal | Sequence[Terminal] | None = None,
    seals: Seal | Sequence[Seal] | None = None,
    parts: HardwarePart | Sequence[HardwarePart] | None = None,
    comment: str | None = None,
) -> Housing:
    """Assemble a cell housing from a case, terminals, seals, and discrete parts.

    This is the format-neutral home for mechanical hardware (prismatic/cylindrical/pouch
    case + terminals + seals, or coin case + spring/spacer).
    """
    def _as_list(value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return list(value)
        return [value]

    return Housing(
        case=case,
        cap=cap,
        terminals=_as_list(terminals),
        seals=_as_list(seals),
        parts=_as_list(parts),
        comment=comment,
    )


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
    coin_hardware: dict[str, Any] | None = None,  # DEPRECATED: pass ``housing`` instead (auto-migrated).
    housing: Housing | None = None,
    source: ProvenanceInfo | None = None,
    specification_comment: str | list[str] | None = None,
    comment: str | list[str] | None = None,
) -> CellSpec:
    """Build a complete cell descriptor specification.

    This is the primary authoring entry point for detailed cell descriptions.
    Combine it with :func:`electrode`, :func:`electrolyte_recipe`, and
    :func:`separator_spec` to build a full description ready for
    :meth:`Workspace.describe_cell`.

    Args:
        id: Canonical BattINFO cell-spec IRI, e.g.
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
        coin_hardware: DEPRECATED legacy coin-hardware dict (case/lid/can/spring/spacer);
            auto-migrated into ``housing`` on construction. Prefer passing ``housing``.
        housing: Cell mechanical housing built with :func:`housing` (case/cap/terminals/seals/parts).
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
    return CellSpec(
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
        housing=housing,
        source=source or ProvenanceInfo(),
        specification_comment=specification_comments,
        comment=comments,
    )


__all__ = [
    "bom",
    "case",
    "cell_description",
    "construction",
    "electrode",
    "electrolyte_recipe",
    "hardware_part",
    "housing",
    "material",
    "properties",
    "seal",
    "separator_spec",
    "source",
    "tab",
    "terminal",
]
