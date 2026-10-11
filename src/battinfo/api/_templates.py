"""template_* draft builders (starter documents for save workflows and hand-edited drafts).

Split from the former monolithic ``battinfo/api.py`` (beta-hardening 4.2);
import the public surface from ``battinfo.api``, not from this module.
"""
from __future__ import annotations

from typing import Any, Literal

from battinfo.api._records import (
    _library_record_from_input,
    _record_from_cell_instance,
    _record_from_cell_spec,
    _record_from_dataset,
    _record_from_test,
    _record_from_test_protocol,
)
from battinfo.api._shared import (
    TEMPLATE_CELL_ID,
    TEMPLATE_CELL_SPEC_ID,
    TestKind,
    _without_minted_identity,
)
from battinfo.bundle import (
    BatteryTestType,
    Cell,
    CellSpec,
    Dataset,
    Test,
    TestSpec,
)

# NOTE: the former ``CellSpecificationInput`` DTO has been retired — the ``CellSpec`` model
# (battinfo.bundle) now absorbs the flat authoring input shape directly (model_name/specs/notes, a
# dict manufacturer, flat provenance kwargs, a transient uid), so one model is both the source of
# truth and the thing callers construct. ``_record_from_cell_spec`` mints the IRI + applies save-time
# provenance defaults. (The former ``CellDatasheetInput`` was likewise retired earlier.)
#
# The canonical-record templates write no placeholder IRI. Without uid= a template
# carries no id, short_id or derived identifier, and a reference the caller did not
# give is left out rather than filled with an all-zero IRI; saving the filled-in
# record mints its IRI (see _records._with_minted_id).


def template_cell_spec(
    *,
    manufacturer: str = "ExampleManufacturer",
    model_name: str = "MODEL-001",
    chemistry: str = "unknown",
    format: Literal["cylindrical", "prismatic", "pouch", "coin", "other", "unknown"] = "unknown",
    iec_code: str | None = None,
    country_of_origin: str | None = None,
    year: int | None = None,
    uid: str | None = None,
    source_file: str = "template-cell-spec.json",
) -> dict[str, Any]:
    """Build a starter canonical cell-spec document for save workflows.

    The document has no ``id`` unless *uid* is given; saving it mints the IRI
    from the filled-in manufacturer, model, format and chemistry.
    """
    draft = CellSpec(
        uid=uid,
        model_name=model_name,
        manufacturer=manufacturer,
        chemistry=chemistry,
        format=format,
        iec_code=iec_code,
        country_of_origin=country_of_origin,
        year=year,
        source_file=source_file,
        specs={},
        notes=["Template-generated record. Fill in specs/provenance before saving."],
    )
    record = _record_from_cell_spec(draft)
    return record if uid is not None else _without_minted_identity(record)


def template_cell_spec_draft(
    *,
    manufacturer: str = "ExampleManufacturer",
    model_name: str = "MODEL-001",
    chemistry: str = "unknown",
    format: Literal["cylindrical", "prismatic", "pouch", "coin", "other", "unknown"] = "unknown",
    size_code: str | None = None,
    iec_code: str | None = None,
    country_of_origin: str | None = None,
    year: int | None = None,
    positive_electrode_basis: str | None = None,
    negative_electrode_basis: str | None = None,
    datasheet_revision: str | None = None,
) -> dict[str, Any]:
    """Build a starter authoring draft for a hand-edited cell-spec JSON file."""
    specs = _draft_specs_for_format(format)
    draft: dict[str, Any] = {
        "manufacturer": manufacturer,
        "model": model_name,
        "format": format,
        "chemistry": chemistry,
        "properties": specs,
        "comment": (
            "Template-generated cell-spec authoring draft. "
            "Edit values and remove entries that don't apply. "
            "Run 'battinfo properties list' to see all available properties and their valid units."
        ),
    }
    if size_code is not None:
        draft["size_code"] = size_code
    if iec_code is not None:
        draft["iec_code"] = iec_code
    if country_of_origin is not None:
        draft["country_of_origin"] = country_of_origin
    if year is not None:
        draft["year"] = year
    if positive_electrode_basis is not None:
        draft["positive_electrode_basis"] = positive_electrode_basis
    if negative_electrode_basis is not None:
        draft["negative_electrode_basis"] = negative_electrode_basis
    if datasheet_revision is not None:
        draft["datasheet_revision"] = datasheet_revision
    return draft


def _draft_specs_for_format(
    cell_format: str,
) -> dict[str, Any]:
    """Return example specs pre-filled with realistic placeholders for the given cell format."""
    def qty(value: float, unit: str) -> dict[str, Any]:
        return {"value": value, "unit": unit}

    specs: dict[str, Any] = {
        "nominal_capacity": qty(0.0, "Ah"),
        "nominal_voltage": qty(0.0, "V"),
        "mass": qty(0.0, "g"),
        "internal_resistance": qty(0.0, "mohm"),
        "maximum_continuous_discharging_current": qty(0.0, "A"),
        "cycle_life": qty(0, "count"),
    }

    if cell_format == "cylindrical":
        specs["diameter"] = qty(0.0, "mm")
        specs["height"] = qty(0.0, "mm")
    elif cell_format in ("prismatic", "pouch"):
        specs["width"] = qty(0.0, "mm")
        specs["height"] = qty(0.0, "mm")
        specs["thickness"] = qty(0.0, "mm")
    elif cell_format == "coin":
        specs["diameter"] = qty(0.0, "mm")
        specs["thickness"] = qty(0.0, "mm")

    return specs


def template_cell_instance(
    *,
    cell_spec_id: str | None = None,
    source_type: Literal["measurement", "lab", "bms", "other"] = "measurement",
    uid: str | None = None,
) -> dict[str, Any]:
    """Build a starter canonical cell-instance document for save workflows.

    The document carries no ``id`` unless *uid* is given, and no ``cell_spec_id``
    unless *cell_spec_id* is: fill those in, and saving mints the IRI from the
    cell's spec, serial number, batch and name, so records made from the template
    never share a placeholder IRI. A cell with none of serial number, batch and
    name has nothing to mint from, and its save is refused.
    """
    draft = Cell(
        uid=uid,
        cell_spec_id=cell_spec_id or TEMPLATE_CELL_SPEC_ID,  # build scaffold, removed below
        source_type=source_type,
        notes=["Template-generated record. Set cell_spec_id/serial_number/datasets before saving; "
               "saving mints the IRI."],
    )
    record = _record_from_cell_instance(draft)
    if cell_spec_id is None:
        record["cell_instance"].pop("cell_spec_id", None)
    return record if uid is not None else _without_minted_identity(record)


def template_dataset(
    *,
    title: str = "Example Dataset",
    source_type: Literal["catalog", "measurement", "lab", "simulation", "external", "manual", "other"] = "other",
    uid: str | None = None,
    related_cell_ids: list[str] | None = None,
    related_test_ids: list[str] | None = None,
    access_url: str = "https://example.org/replace-with-your-dataset-url",
) -> dict[str, Any]:
    """Build a starter canonical dataset document for save workflows.

    ``access_url`` is a visible example placeholder (like the template's title) — replace
    it with the landing page or download URL where the data actually lives. The document
    has no ``id`` unless *uid* is given, and lists only the cells and tests passed in;
    saving it mints the IRI."""
    draft = Dataset(
        uid=uid,
        title=title,
        source_type=source_type,
        related_cell_ids=related_cell_ids or [],
        related_test_ids=related_test_ids or [],
        access_url=access_url,
        notes=["Template-generated record. Fill in URL/license/distribution details before saving."],
    )
    record = _record_from_dataset(draft)
    return record if uid is not None else _without_minted_identity(record)


def template_test(
    *,
    cell_id: str | None = None,
    name: str = "Example Test",
    kind: TestKind = BatteryTestType.OTHER,
    source_type: Literal["measurement", "lab", "simulation", "manual", "other"] = "measurement",
    uid: str | None = None,
    dataset_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build a starter canonical test document for save workflows.

    The document has no ``id`` unless *uid* is given and no ``cell_id`` unless
    *cell_id* is; saving the filled-in record mints the IRI.
    """
    draft = Test(
        uid=uid,
        cell_id=cell_id or TEMPLATE_CELL_ID,  # build scaffold, removed below
        name=name,
        kind=kind,
        source_type=source_type,
        dataset_ids=dataset_ids or [],
        notes=["Template-generated record. Set the concrete cell, protocol, and datasets before saving."],
    )
    record = _record_from_test(draft)
    if cell_id is None:
        record["test"].pop("cell_id", None)
    return record if uid is not None else _without_minted_identity(record)


def template_test_spec(
    *,
    name: str = "Example Test Protocol",
    kind: TestKind = BatteryTestType.OTHER,
    source_type: Literal["manual", "lab", "simulation", "other"] = "manual",
    uid: str | None = None,
) -> dict[str, Any]:
    """Build a starter canonical test-protocol document for save workflows.

    The document has no ``id`` unless *uid* is given; saving it mints the IRI.
    """
    draft = TestSpec(
        uid=uid,
        name=name,
        kind=kind,
        source_type=source_type,
        experiment=["Discharge at C/10 until 2.5 V"],
        notes=["Template-generated record. Replace the example experiment / conditions before saving."],
    )
    record = _record_from_test_protocol(draft)
    return record if uid is not None else _without_minted_identity(record)


def template_test_spec_draft(
    *,
    name: str = "Example Test Protocol",
    kind: TestKind = BatteryTestType.OTHER,
    version: str | None = None,
    protocol_url: str | None = None,
) -> dict[str, Any]:
    """Build a starter authoring draft for a hand-edited test-protocol JSON file."""
    draft: dict[str, Any] = {
        "name": name,
        "kind": str(kind),
        "experiment": ["Charge at 1 C until 4.2 V", "Hold at 4.2 V until C/50", "Discharge at 1 C until 2.5 V"],
        "cycles": 1,
        "conditions": {"temperature": {"value": 25, "unit": "degC"}},
        "record": {},
        "safety": {},
        "artifacts": [],
        "comment": "Template-generated test-protocol authoring draft. Replace the example experiment with the real PyBaMM-style steps before loading into Workspace.",
    }
    if version is not None:
        draft["version"] = version
    if protocol_url is not None:
        draft["protocol_url"] = protocol_url
    return draft


def template_library_cell_spec(
    *,
    manufacturer: str = "ExampleManufacturer",
    model: str = "MODEL-001",
    chemistry: str = "unknown",
    format: Literal["cylindrical", "prismatic", "pouch", "coin", "other", "unknown"] = "unknown",
    positive_electrode_basis: str = "unknown",
    negative_electrode_basis: str = "unknown",
    uid: str | None = None,
    source_file: str = "template-library-cell-spec.json",
    source_type: str = "datasheet",
) -> dict[str, Any]:
    """Build a starter detailed cell specification (library record).

    Detailed specs are normally authored via ``cell_description()``; this is the flat
    template for the library record (fill in the electrode/electrolyte/separator structure).
    The record has no ``specification.id`` unless *uid* is given; ``save_library_cell_spec``
    mints it from the filled-in manufacturer, model, format and chemistry.
    """
    record = _library_record_from_input(
        {
            "uid": uid,
            "manufacturer": manufacturer,
            "model": model,
            "chemistry": chemistry,
            "format": format,
            "positive_electrode_basis": positive_electrode_basis,
            "negative_electrode_basis": negative_electrode_basis,
            "source_file": source_file,
            "source_type": source_type,
            "specification_comment": ["Template-generated specification. Fill in trusted specification values."],
            "comment": ["Template-generated reusable library cell spec."],
        }
    )
    return record if uid is not None else _without_minted_identity(record, "specification")
