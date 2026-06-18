"""Bridge between inline cell-spec component holders and standalone component-specs.

A cell-spec may inline its components (``positive_electrode``, ``negative_electrode``,
``electrolyte``, ``separator``, ``housing``) or reference standalone component-specs by
IRI (``*_spec_id``). These helpers lift the inline holders into standalone
``electrode-spec``/``electrolyte-spec``/``separator-spec``/``housing-spec`` records so a
component can be authored once and referenced from many cells (dedup) — the symmetric
counterpart of :func:`battinfo.materials.extract_material_specs`.
"""

from __future__ import annotations

from typing import Any, Mapping

from battinfo._workspace import _stable_uid

# (cell-spec holder key, component family, human label)
_HOLDER_FAMILIES = (
    ("positive_electrode", "electrode", "positive electrode"),
    ("negative_electrode", "electrode", "negative electrode"),
    ("electrolyte", "electrolyte", "electrolyte"),
    ("separator", "separator", "separator"),
    ("housing", "housing", "housing"),
)


def component_spec_from_holder(
    family: str, holder: Mapping[str, Any], *, name: str, uid_seed: str | None = None
) -> dict[str, Any]:
    """Lift an inline component holder to a standalone component-spec record.

    The IRI is minted deterministically from *uid_seed* (or the name), so the same
    holder lifts to the same spec IRI across cells — enabling dedup.
    """
    from battinfo.api import create_component_spec

    body = {k: v for k, v in holder.items() if k != "name"}
    return create_component_spec(
        family, name=name, body=body,
        uid=_stable_uid(uid_seed or f"{family}-spec:{name.strip().lower()}"),
        validate=False,
    )


def extract_component_specs(cell_spec_record: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Extract standalone component-spec records from a cell-spec's inline holders.

    Returns one component-spec per inline holder present
    (positive/negative electrode, electrolyte, separator, housing).
    """
    cell = cell_spec_record.get("cell_spec", {})
    base = cell.get("name") or cell.get("model") or "cell" if isinstance(cell, Mapping) else "cell"
    out: list[dict[str, Any]] = []
    for holder_key, family, label in _HOLDER_FAMILIES:
        holder = cell_spec_record.get(holder_key)
        if isinstance(holder, Mapping) and holder:
            name = holder.get("name") or f"{base} {label}"
            out.append(
                component_spec_from_holder(
                    family, holder, name=name, uid_seed=f"{family}-spec:{base}:{label}"
                )
            )
    return out
