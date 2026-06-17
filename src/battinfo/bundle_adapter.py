"""Adapter between the handcrafted bundle.py application layer and the
LinkML-generated bundle_generated.py schema layer.

Use these functions when you need a generated-schema object that carries full
EMMO IRI annotations (e.g. for JSON-LD export via the linkml_meta fields).
Application code should use bundle.py types directly.

See CLAUDE.md § Bundle Layer Architecture for design rationale.

Public API
----------
specs_to_specset(props)         dict[str, Any] → SpecSet
specset_to_specs(ss)            SpecSet        → dict[str, Any]
cell_spec_to_schema(ct)         CellSpecification       → generated CellSpecification
cell_instance_to_schema(ci)     CellInstance   → generated CellInstance
test_to_schema(t)               Test           → generated Test
test_spec_to_schema(ts)         TestSpec       → generated TestSpec
bundle_to_schema(obj)           any bundle obj → corresponding generated obj

schema_cell_spec_to_record_dict(ct_gen) → record dict accepted by CellSpecification.from_record()
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from battinfo.bundle import CellInstance, CellSpecification, Test, TestSpec
    from battinfo.bundle_generated import (
        CellInstance as GenCellInstance,
    )
    from battinfo.bundle_generated import (
        CellSpecification as GenCellSpecification,
    )
    from battinfo.bundle_generated import (
        SpecSet,
        SpecValue,
    )
    from battinfo.bundle_generated import (
        Test as GenTest,
    )
    from battinfo.bundle_generated import (
        TestSpec as GenTestSpec,
    )


# ── SpecValue / SpecSet helpers ───────────────────────────────────────────────


def _dict_to_spec_value(v: Mapping[str, Any]) -> "SpecValue":
    from battinfo.bundle_generated import SpecValue  # noqa: PLC0415
    return SpecValue(
        sv_value=v.get("value"),
        sv_unit=v.get("unit"),
        sv_min_value=v.get("min_value"),
        sv_max_value=v.get("max_value"),
        sv_typical_value=v.get("typical_value"),
    )


def _spec_value_to_dict(sv: "SpecValue") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if sv.sv_value is not None:
        out["value"] = sv.sv_value
    if sv.sv_unit is not None:
        out["unit"] = sv.sv_unit
    if sv.sv_min_value is not None:
        out["min_value"] = sv.sv_min_value
    if sv.sv_max_value is not None:
        out["max_value"] = sv.sv_max_value
    if sv.sv_typical_value is not None:
        out["typical_value"] = sv.sv_typical_value
    return out


def specs_to_specset(props: dict[str, Any]) -> "SpecSet | None":
    """Convert a properties dict to a SpecSet.

    Keys matching SpecSet field names become typed SpecValue objects.
    Unknown keys are stored as extras (ConfiguredBaseModel uses extra='allow').
    """
    from battinfo.bundle_generated import SpecSet  # noqa: PLC0415
    if not props:
        return None
    kwargs: dict[str, Any] = {}
    for key, v in props.items():
        if isinstance(v, Mapping) and ("value" in v or "unit" in v):
            kwargs[key] = _dict_to_spec_value(v)
        elif v is not None:
            kwargs[key] = v
    return SpecSet(**kwargs) if kwargs else None


def specset_to_specs(specset: "SpecSet | None") -> dict[str, Any]:
    """Convert a SpecSet to a properties dict.

    Only non-None fields are included.  SpecValue fields are converted to
    {"value": ..., "unit": ...} dicts.
    """
    if specset is None:
        return {}
    from battinfo.bundle_generated import SpecValue  # noqa: PLC0415
    out: dict[str, Any] = {}
    for key, raw in specset.model_dump(exclude_none=True).items():
        if key == "linkml_meta":
            continue
        if isinstance(raw, SpecValue):
            out[key] = _spec_value_to_dict(raw)
        elif isinstance(raw, Mapping):
            # model_dump() already serialised SpecValue to a dict with sv_* keys
            sv_value = raw.get("sv_value")
            sv_unit = raw.get("sv_unit")
            sv_min = raw.get("sv_min_value")
            sv_max = raw.get("sv_max_value")
            sv_typ = raw.get("sv_typical_value")
            if sv_value is not None or sv_unit is not None:
                spec: dict[str, Any] = {}
                if sv_value is not None:
                    spec["value"] = sv_value
                if sv_unit is not None:
                    spec["unit"] = sv_unit
                if sv_min is not None:
                    spec["min_value"] = sv_min
                if sv_max is not None:
                    spec["max_value"] = sv_max
                if sv_typ is not None:
                    spec["typical_value"] = sv_typ
                out[key] = spec
    return out


# ── bundle.py → generated ─────────────────────────────────────────────────────


def cell_spec_to_schema(ct: "CellSpecification") -> "GenCellSpecification":
    """Convert a bundle.py CellSpecification to a generated CellSpecification with EMMO IRI annotations."""
    from battinfo.bundle_generated import (  # noqa: PLC0415
        CellSpecification as GenCellSpecification,
    )
    from battinfo.bundle_generated import (
        Organization,
    )
    return GenCellSpecification(
        id=ct.id or "urn:staging:unknown",
        ct_name=ct.name,
        ct_model=ct.model,
        ct_manufacturer=Organization(org_name=ct.manufacturer),
        ct_cell_format=ct.format,
        ct_chemistry=ct.chemistry,
        ct_product_type=ct.product_type.value if ct.product_type is not None else None,
        ct_rechargeable=ct.rechargeable,
        ct_year=ct.year,
        ct_country_of_origin=ct.country_of_origin,
        ct_positive_electrode_basis=ct.positive_electrode_basis,
        ct_negative_electrode_basis=ct.negative_electrode_basis,
        ct_size_code=ct.size_code,
        ct_iec_code=ct.iec_code,
        ct_specs=specs_to_specset(ct.properties),
    )


def cell_instance_to_schema(ci: "CellInstance") -> "GenCellInstance":
    """Convert a bundle.py CellInstance to a generated CellInstance."""
    from battinfo.bundle_generated import CellInstance as GenCellInstance  # noqa: PLC0415
    return GenCellInstance(
        ci_id=ci.id or "urn:staging:unknown",
        ci_type_id=ci.cell_spec_id or "",
        ci_name=ci.name,
        ci_serial_number=ci.serial_number,
        ci_batch_id=ci.batch_id,
        ci_grade=ci.grade,
        ci_manufactured_at=ci.manufactured_at if isinstance(ci.manufactured_at, int) else None,
        ci_expires_at=ci.expires_at if isinstance(ci.expires_at, int) else None,
        ci_dataset_ids=list(ci.dataset_ids) if ci.dataset_ids else None,
        ci_measured=specs_to_specset(ci.measured) if ci.measured else None,
    )


def test_spec_to_schema(ts: "TestSpec") -> "GenTestSpec":
    """Convert a bundle.py TestSpec to a generated TestSpec."""
    from battinfo.bundle_generated import (  # noqa: PLC0415
        ProtocolInfo as GenProtocolInfo,
    )
    from battinfo.bundle_generated import (
        TestSpec as GenTestSpec,
    )
    return GenTestSpec(
        ts_id=ts.id or "urn:staging:unknown",
        ts_name=ts.name or "",
        ts_kind=ts.test_type.value,
        ts_description=ts.description,
        ts_version=ts.version,
        ts_protocol=GenProtocolInfo(
            protocol_name=ts.protocol.name,
            protocol_url=ts.protocol.url,
        ) if (ts.protocol.name or ts.protocol.url) else None,
        ts_steps=ts.experiment or None,
        ts_cycles=None,
    )


def test_to_schema(t: "Test") -> "GenTest":
    """Convert a bundle.py Test to a generated Test."""
    from battinfo.bundle_generated import (  # noqa: PLC0415
        ProtocolInfo as GenProtocolInfo,
    )
    from battinfo.bundle_generated import (
        Test as GenTest,
    )
    return GenTest(
        t_id=t.id or "urn:staging:unknown",
        t_name=t.name or "",
        t_kind=t.test_type.value,
        t_cell_id=t.cell_instance_id or "",
        t_protocol_id=t.protocol_id,
        t_description=t.description,
        t_status=t.status,
        t_protocol=GenProtocolInfo(
            protocol_name=t.protocol.name,
            protocol_url=t.protocol.url,
        ) if (t.protocol.name or t.protocol.url) else None,
        t_instrument=t.instrument,
        t_started_at=t.started_at if isinstance(t.started_at, int) else None,
        t_ended_at=t.ended_at if isinstance(t.ended_at, int) else None,
        t_dataset_ids=list(t.dataset_ids) if t.dataset_ids else None,
    )


def bundle_to_schema(obj: Any) -> Any:
    """Dispatch: convert any bundle.py object to its generated-schema counterpart.

    Raises TypeError for unknown types.
    """
    from battinfo.bundle import (  # noqa: PLC0415
        CellInstance,
        CellSpecification,
        Test,
        TestSpec,
    )
    if isinstance(obj, CellSpecification):
        return cell_spec_to_schema(obj)
    if isinstance(obj, CellInstance):
        return cell_instance_to_schema(obj)
    if isinstance(obj, Test):
        return test_to_schema(obj)
    if isinstance(obj, TestSpec):
        return test_spec_to_schema(obj)
    raise TypeError(f"No schema adapter for {type(obj).__name__}")


# ── generated → record dict ───────────────────────────────────────────────────


def schema_cell_spec_to_record_dict(ct_gen: "GenCellSpecification") -> dict[str, Any]:
    """Convert a generated CellSpecification to the record dict accepted by CellSpecification.from_record().

    Useful when reading JSON-LD output back into the application layer.
    """
    manufacturer_name = (
        ct_gen.ct_manufacturer.org_name
        if ct_gen.ct_manufacturer is not None
        else "unknown"
    )
    product: dict[str, Any] = {
        "id": ct_gen.id,
        "model": ct_gen.ct_model,
        "name": ct_gen.ct_name or f"{manufacturer_name} {ct_gen.ct_model}",
        "manufacturer": {"type": "Organization", "name": manufacturer_name},
        "cell_format": ct_gen.ct_cell_format if ct_gen.ct_cell_format is not None else "unknown",
        "chemistry": ct_gen.ct_chemistry or "unknown",
    }
    if ct_gen.ct_product_type is not None:
        product["product_type"] = str(ct_gen.ct_product_type)
    if ct_gen.ct_rechargeable is not None:
        product["rechargeable"] = ct_gen.ct_rechargeable
    if ct_gen.ct_year is not None:
        product["year"] = ct_gen.ct_year
    if ct_gen.ct_country_of_origin is not None:
        product["country_of_origin"] = ct_gen.ct_country_of_origin
    if ct_gen.ct_positive_electrode_basis is not None:
        product["positive_electrode_basis"] = ct_gen.ct_positive_electrode_basis
    if ct_gen.ct_negative_electrode_basis is not None:
        product["negative_electrode_basis"] = ct_gen.ct_negative_electrode_basis
    if ct_gen.ct_size_code is not None:
        product["size_code"] = ct_gen.ct_size_code
    if ct_gen.ct_iec_code is not None:
        product["iec_code"] = ct_gen.ct_iec_code
    return {
        "schema_version": "1.0.0",
        "cell_spec": product,
        "properties": specset_to_specs(ct_gen.ct_specs),
        "provenance": {},
    }
