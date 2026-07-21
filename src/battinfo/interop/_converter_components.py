"""Extract standalone component specs from a converter CoinCell node.

The BattInfoConverter output carries a full component tree
(``hasPositiveElectrode`` → ``hasCoating`` → ``hasActiveMaterial`` …) that the
base converter importer reduces to two electrode-basis strings. This module
walks that tree and mints deduplicated ``material_spec`` / ``electrode_spec`` /
``electrolyte_spec`` / ``separator_spec`` records using the canonical builders,
so the composition and its quantities survive as linked component specs.

It is context-free by design: it keys on the canonical EMMO term strings the
converter emits, never on a resolved ``@context`` (the property that makes this
robust across converter versions — see the interop recovery scorecard).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from battinfo.api import UID_ALPHABET, _normalized_dashed_uid
from battinfo.api._components import create_component_spec, create_material_spec

# EMMO / QUDT unit token (any prefix) → canonical BattINFO unit text.
_UNIT = {
    "Percent": "%", "PERCENT": "%",
    "MicroMetre": "um", "MicroM": "um",
    "MilliMetre": "mm", "MilliM": "mm",
    "GramPerCubicCentiMetre": "g/cm3",
    "MilliGramPerSquareCentiMetre": "mg/cm2", "MilliGM-PER-CentiM2": "mg/cm2",
    "MilliAmpereHourPerSquareCentiMetre": "mAh/cm2",
    "MilliAmpereHourPerGram": "mAh/g", "MilliA-HR-PER-GM": "mAh/g",
}

# EMMO substance @type → (display name, chemistry_family or None).
_MATERIAL = {
    "LithiumNickelManganeseCobaltOxide": ("NMC", "lithium nickel manganese cobalt oxide"),
    "LithiumIronPhosphate": ("LFP", "lithium iron phosphate"),
    "LithiumCobaltOxide": ("LCO", "lithium cobalt oxide"),
    "LithiumManganeseIronPhosphate": ("LMFP", "lithium manganese iron phosphate"),
    "Graphite": ("Graphite", "graphite"),
    "HardCarbon": ("Hard carbon", None),
    "Silicon": ("Silicon", None),
    "PolyvinylideneFluoride": ("PVDF", None),
    "CarboxymethylCellulose": ("CMC", None),
    "StyreneButadiene": ("SBR", None),
    "CarbonBlack": ("Carbon black", None),
}
_SALT = {
    "LithiumHexafluorophosphate": "LiPF6",
    "LithiumBisfluorosulfonylimide": "LiFSI",
    "LithiumBistrifluoromethanesulfonylimide": "LiTFSI",
}
_SOLVENT = {
    "EthyleneCarbonate": "EC", "DimethylCarbonate": "DMC", "EthylMethylCarbonate": "EMC",
    "PropyleneCarbonate": "PC", "FluoroethyleneCarbonate": "FEC", "VinyleneCarbonate": "VC",
    "DiethylCarbonate": "DEC",
}
_COLLECTOR = {"Aluminium": "Aluminium foil", "Copper": "Copper foil"}

# EMMO property @type → canonical quantity key, per component slot.
_ACTIVE_PROPS = {"MassFraction": "mass_fraction"}
_COATING_PROPS = {
    "MassLoading": "loading",
    "CalenderedCoatingThickness": "thickness",
    "Thickness": "thickness",
    "Porosity": "porosity",
    "CalenderedDensity": "density",
    "Density": "density",
}
_SEPARATOR_PROPS = {"Thickness": "thickness", "Porosity": "porosity"}


@dataclass
class ComponentExtraction:
    material_specs: list[dict[str, Any]] = field(default_factory=list)
    electrode_specs: list[dict[str, Any]] = field(default_factory=list)
    electrolyte_specs: list[dict[str, Any]] = field(default_factory=list)
    separator_specs: list[dict[str, Any]] = field(default_factory=list)
    positive_electrode_spec_id: str | None = None
    negative_electrode_spec_id: str | None = None
    electrolyte_spec_id: str | None = None
    warnings: list[str] = field(default_factory=list)

    def specs(self) -> list[dict[str, Any]]:
        return [*self.material_specs, *self.electrode_specs, *self.electrolyte_specs, *self.separator_specs]


def _uid(*parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).digest()
    return _normalized_dashed_uid("".join(UID_ALPHABET[b % 32] for b in digest[:16]))


def _types(node: Any) -> list[str]:
    if not isinstance(node, Mapping):
        return []
    t = node.get("@type", [])
    if isinstance(t, str):
        return [t]
    return [x for x in t if isinstance(x, str)] if isinstance(t, Sequence) else []


def _local(token: str | None) -> str | None:
    if not isinstance(token, str):
        return None
    if ":" in token and not token.startswith("http"):
        return token.split(":", 1)[1]
    if "#" in token or "/" in token:
        return token.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
    return token


def _num(value: Any) -> float | int | None:
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            f = float(value)
            return int(f) if f.is_integer() else f
        except ValueError:
            return None
    return None


def _prop(node: Mapping[str, Any], emmo_type: str) -> dict[str, Any] | None:
    """Find a hasProperty/hasMeasuredProperty entry by EMMO type → {value, unit?}."""
    for key in ("hasMeasuredProperty", "hasProperty", "hasConventionalProperty"):
        raw = node.get(key)
        if raw is None:
            continue
        for prop in raw if isinstance(raw, list) else [raw]:
            if not isinstance(prop, Mapping) or emmo_type not in _types(prop):
                continue
            part = prop.get("hasNumericalPart")
            value = None
            if isinstance(part, Mapping):
                value = _num(part.get("hasNumberValue", part.get("hasNumericalValue")))
            if value is None:
                continue
            unit = _UNIT.get(_local(prop.get("hasMeasurementUnit")) or "")
            q: dict[str, Any] = {"value": value}
            if unit:
                q["unit"] = unit
            return q
    return None


def _children(node: Mapping[str, Any], relation: str) -> list[Mapping[str, Any]]:
    raw = node.get(relation)
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else [raw]
    return [x for x in items if isinstance(x, Mapping)]


def _substance_type(node: Mapping[str, Any], roles: set[str]) -> str | None:
    return next((t for t in _types(node) if t not in roles), None)


class _Extractor:
    def __init__(self, seed: str, validate: bool) -> None:
        self.seed = seed
        self.validate = validate
        self._materials: dict[str, dict[str, Any]] = {}
        self.out = ComponentExtraction()

    def _material(self, node: Mapping[str, Any], material_class: str, roles: set[str]) -> tuple[str, str] | None:
        emmo = _substance_type(node, roles)
        if emmo is None:
            return None
        name, family = _MATERIAL.get(emmo, (emmo, None))
        if name not in self._materials:
            rec = create_material_spec(
                validate=self.validate,
                uid=_uid(self.seed, "material", name, material_class),
                name=name,
                material_class=material_class,
                chemistry_family=family,
                emmo_type=emmo,
                source_type="datasheet",
            )
            self._materials[name] = rec
            self.out.material_specs.append(rec)
        return name, self._materials[name]["material_spec"]["id"]

    def electrode(self, electrode: Mapping[str, Any], polarity: str) -> str | None:
        coatings = _children(electrode, "hasCoating")
        coating_node = coatings[0] if coatings else {}
        actives = _children(coating_node, "hasActiveMaterial") or _children(electrode, "hasActiveMaterial")
        if not actives:
            return None
        active_node = actives[0]
        mat = self._material(active_node, "active_material", {"ActiveMaterial"})
        if mat is None:
            return None
        active_name, active_id = mat
        active: dict[str, Any] = {"name": active_name, "material_spec_id": active_id}
        mf = _prop(active_node, "MassFraction")
        if mf is not None:
            active["property"] = {"mass_fraction": mf}
        component: dict[str, Any] = {"active_material": [active]}

        binder_node = (_children(coating_node, "hasBinder") or _children(electrode, "hasBinder"))
        if binder_node:
            b = self._material(binder_node[0], "binder", {"Binder"})
            if b:
                component["binder"] = [{"name": b[0], "material_spec_id": b[1]}]
        add_node = (_children(coating_node, "hasConductiveAdditive") or _children(electrode, "hasConductiveAdditive"))
        if add_node:
            a = self._material(add_node[0], "conductive_additive", {"ConductiveAdditive"})
            if a:
                component["additive"] = [{"name": a[0], "material_spec_id": a[1]}]

        coating: dict[str, Any] = {"component": component}
        props: dict[str, Any] = {}
        loading = _prop(active_node, "MassLoading")
        if loading is not None:
            props["loading"] = loading
        for emmo, key in _COATING_PROPS.items():
            if key in props or key == "loading":
                continue
            q = _prop(coating_node, emmo)
            if q is not None:
                props[key] = q
        if props:
            coating["property"] = props

        body: dict[str, Any] = {"coating": coating}
        collectors = _children(electrode, "hasCurrentCollector")
        if collectors:
            cc_type = _substance_type(collectors[0], {"CurrentCollector"})
            body["current_collector"] = {"name": _COLLECTOR.get(cc_type or "", "current collector")}

        rec = create_component_spec(
            "electrode", validate=self.validate,
            uid=_uid(self.seed, "electrode", polarity),
            name=f"{active_name} {polarity} electrode",
            polarity=polarity, body=body, source_type="datasheet",
        )
        self.out.electrode_specs.append(rec)
        return rec["electrode_spec"]["id"]

    def electrolyte(self, node: Mapping[str, Any]) -> str | None:
        body: dict[str, Any] = {"family": "organic"}
        salts = [_substance_type(c, {"Solute", "Constituent"}) for grp in _children(node, "hasSolute") for c in _children(grp, "hasConstituent")]
        salt_name = next((_SALT[s] for s in salts if s in _SALT), None)
        if salt_name:
            body["salt"] = {"name": salt_name}
        solvents = [_substance_type(c, {"Solvent", "Constituent"}) for grp in _children(node, "hasSolvent") for c in _children(grp, "hasConstituent")]
        comps = [{"name": _SOLVENT[s]} for s in solvents if s in _SOLVENT]
        if comps:
            body["solvent_mixture"] = {"component": comps}
        rec = create_component_spec(
            "electrolyte", validate=self.validate,
            uid=_uid(self.seed, "electrolyte"),
            name="Electrolyte", body=body, source_type="datasheet",
        )
        self.out.electrolyte_specs.append(rec)
        return rec["electrolyte_spec"]["id"]

    def separator(self, node: Mapping[str, Any]) -> None:
        props: dict[str, Any] = {}
        for emmo, key in _SEPARATOR_PROPS.items():
            q = _prop(node, emmo)
            if q is not None:
                props[key] = q
        body: dict[str, Any] = {}
        if props:
            body["property"] = props
        rec = create_component_spec(
            "separator", validate=self.validate,
            uid=_uid(self.seed, "separator"),
            name="Separator", body=body, source_type="datasheet",
        )
        self.out.separator_specs.append(rec)


def extract_component_specs(
    coin_cell: Mapping[str, Any], *, seed: str, validate: bool = True
) -> ComponentExtraction:
    """Walk a converter CoinCell node into deduplicated canonical component specs."""
    ex = _Extractor(seed, validate)
    for relation, polarity, setter in (
        ("hasPositiveElectrode", "positive", "positive_electrode_spec_id"),
        ("hasNegativeElectrode", "negative", "negative_electrode_spec_id"),
    ):
        nodes = _children(coin_cell, relation)
        if not nodes:
            continue
        try:
            spec_id = ex.electrode(nodes[0], polarity)
            if spec_id:
                setattr(ex.out, setter, spec_id)
        except Exception as exc:  # noqa: BLE001 - a lossy component is a warning, not a crash
            ex.out.warnings.append(f"{polarity} electrode not extracted: {type(exc).__name__}: {exc}")

    ely = _children(coin_cell, "hasElectrolyte")
    if ely:
        try:
            ex.out.electrolyte_spec_id = ex.electrolyte(ely[0])
        except Exception as exc:  # noqa: BLE001
            ex.out.warnings.append(f"electrolyte not extracted: {type(exc).__name__}: {exc}")

    sep = _children(coin_cell, "hasSeparator")
    if sep:
        try:
            ex.separator(sep[0])
        except Exception as exc:  # noqa: BLE001
            ex.out.warnings.append(f"separator not extracted: {type(exc).__name__}: {exc}")

    return ex.out
