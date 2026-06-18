from __future__ import annotations

import copy
import json
import warnings
from functools import lru_cache
from importlib import resources
from typing import Any
from urllib.request import Request, urlopen

from rdflib import Dataset

try:
    from pyld import jsonld as pyld_jsonld
except ImportError:  # pragma: no cover - exercised only when the dependency is missing at runtime.
    pyld_jsonld = None

from battinfo.validate.core import (
    DEFAULT_POLICY,
    ValidationIssue,
    ValidationPolicy,
    ValidationReport,
    ValidationResult,
    get_validation_policy,
)

# Canonical URL for the EMMO domain-battery JSON-LD context.  A bundled copy lives at
# src/battinfo/data/context/domain-battery.context.json and is served as a local
# fallback so that JSON-LD processing works without network access.  Run
# .tools/quality/refresh_emmo_context.py to update the bundled copy.
_EMMO_BATTERY_CONTEXT_URL = "https://w3id.org/emmo/domain/battery/context"

_EXPLICIT_ALLOWED_TYPE_TERMS = {
    "BatteryCell",
    "BatteryTest",
    "BatteryModule",
    "BatteryPack",
    "BatterySystem",
    "CoinCell",
    "ConventionalProperty",
    "CylindricalBattery",
    "GraphiteElectrode",
    "HardCarbonElectrode",
    "LithiumCobaltOxideElectrode",
    "LithiumIonBattery",
    "LithiumIonCobaltOxideBattery",
    "LithiumIonGraphiteBattery",
    "LithiumIonIronPhosphateBattery",
    "LithiumIonNickelCobaltAluminiumOxideBattery",
    "LithiumIonNickelManganeseCobaltOxideBattery",
    "LithiumIronPhosphateElectrode",
    "LithiumManganeseDioxideBattery",
    "LithiumMetalBattery",
    "PouchCell",
    "PrismaticBattery",
    "RatedEnergy",
    "RealData",
    "SiliconGraphiteElectrode",
    "SodiumIonBattery",
    "MaximumChargingTemperature",
    "MinimumChargingTemperature",
    "MaximumDischargingTemperature",
    "MinimumDischargingTemperature",
    "MaximumStorageTemperature",
    "MinimumStorageTemperature",
    # New in domain-electrochemistry 0.34.0 / domain-battery 0.18.8
    "ACInternalResistance",
    "CalendarLife",
    "DCInternalResistance",
    "InitialCoulombicEfficiency",
    "NominalEnergy",
    "SelfDischargeRate",
    "StateOfHealth",
    # Electrochemical process step types (test protocol step nodes)
    "ConstantCurrentCharging",
    "ConstantCurrentConstantVoltageCharging",
    "ConstantCurrentConstantVoltageCycling",
    "ConstantCurrentDischarging",
    "ConstantVoltageCharging",
    "ConstantVoltageDischarging",
    "ElectrochemicalTestingProcedure",
    "Resting",
    # New in domain-battery 0.19.0
    "BatterySpecification",
    "BatteryCellSpecification",
    "BatteryModuleSpecification",
    "BatteryPackSpecification",
    "BatterySystemSpecification",
    # BatteryTest semantic model
    "BatteryTestResult",
    "BatteryCycler",
    "Galvanostat",
    "MeasuringInstrument",
    "Potentiostat",
    # Material-spec property + property-nature + measurement-parameter terms (Phase 1.5)
    "SpecificCapacity",
    "SpecificSurfaceArea",
    "MolarMass",
    "Voltage",
    "MeasuredProperty",
    "NominalProperty",
    "CRate",
    "ElectricCurrent",
    "LowerVoltageLimit",
    "UpperVoltageLimit",
    # Electrode composition, electrolyte, separator (descriptor pipeline)
    "ActiveMassLoading",
    "ActiveMaterial",
    "AmountConcentration",
    "AqueousElectrolyte",
    "AreicCapacity",
    "Binder",
    "CalenderedCoatingThickness",
    "CalenderedDensity",
    "CelsiusTemperature",
    "ConductiveAdditive",
    "D50ParticleSize",
    "Density",
    "Diameter",
    "DischargingSpecificCapacity",
    "DynamicViscosity",
    "ElectrolyticConductivity",
    "Mass",
    "MassLoading",
    "NPRatio",
    "TheoreticalCapacity",
    "Tortuosity",
    "Volume",
    "CurrentCollector",
    "CurrentCollectorTab",
    "Electrode",
    "ElectrodeCoating",
    # Housing / hardware (E1). Seal is a pending domain-battery term.
    "CoinCase",
    "CylindricalCase",
    "PouchCase",
    "PrismaticCase",
    "CellLid",
    "CellCan",
    "Terminal",
    "Seal",
    "Spring",
    "Spacer",
    "ElectrodeStack",
    "JellyRoll",
    "ElectrolyteAdditive",
    "ElectrolyteSolution",
    "ExpandedMesh",
    "ElectrospunMesh",
    "Foil",
    "IonicLiquidElectrolyte",
    "LiquidElectrolyte",
    "MassFraction",
    "OrganicElectrolyte",
    "PerforatedFoil",
    "PolymerElectrolyte",
    "Porosity",
    "PorousSeparator",
    "Separator",
    "SeparatorPorosity",
    "SeparatorThickness",
    "SolidElectrolyte",
    "Solute",
    "Solvent",
    "Thickness",
    "VolumeFraction",
    "WovenMesh",
}


def _load_mapping_json(*parts: str) -> dict[str, Any]:
    path = resources.files("battinfo")
    for part in ("data", "mappings", "domain-battery", *parts):
        path = path.joinpath(part)  # single-arg joinpath: multi-arg is Python 3.11+
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _is_absolute_or_compact_iri(value: str) -> bool:
    return "://" in value or ":" in value


def _collect_bare_terms(value: Any, out: set[str]) -> None:
    if isinstance(value, str):
        if value and not _is_absolute_or_compact_iri(value):
            out.add(value)
        return
    if isinstance(value, list):
        for item in value:
            _collect_bare_terms(item, out)
        return
    if isinstance(value, dict):
        for item in value.values():
            _collect_bare_terms(item, out)


@lru_cache(maxsize=1)
def _allowed_type_terms() -> set[str]:
    allowed = set(_EXPLICIT_ALLOWED_TYPE_TERMS)

    entity_map = _load_mapping_json("entity_type_map.json")
    _collect_bare_terms(entity_map.get("mappings", {}), allowed)

    for filename in ("property_map.candidates.json", "property_map.curated.json"):
        property_map = _load_mapping_json(filename)
        for item in property_map.get("mappings", []):
            for key in ("class_pref_label", "class_label"):
                value = item.get(key)
                if isinstance(value, str) and value:
                    allowed.add(value)

    material_map = _load_mapping_json("material_map.json")
    for item in material_map.get("mappings", []):
        emmo_class = item.get("emmo_class")
        if isinstance(emmo_class, str) and emmo_class:
            allowed.add(emmo_class)

    return allowed


def _walk_relative_type_errors(node: Any, path: str, errors: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            next_path = f"{path}.{key}" if path else key
            if key == "@context":
                continue
            if key == "@type":
                values = [value] if isinstance(value, str) else value if isinstance(value, list) else []
                for idx, item in enumerate(values):
                    if not isinstance(item, str):
                        continue
                    if item.startswith("@"):
                        continue
                    if _is_absolute_or_compact_iri(item):
                        continue
                    if item not in _allowed_type_terms():
                        item_path = next_path if isinstance(value, str) else f"{next_path}[{idx}]"
                        errors.append(f"{item_path}: relative @type reference '{item}' is not in the allowed term set")
            else:
                _walk_relative_type_errors(value, next_path, errors)
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            next_path = f"{path}[{idx}]" if path else f"[{idx}]"
            _walk_relative_type_errors(item, next_path, errors)


def _parse_materialization_issues(data: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    # rdflib 7.x emits DeprecationWarning for internal APIs (Dataset.default_context,
    # Dataset.contexts, ConjunctiveGraph) used by its own JSON-LD parser and nquads
    # serializer.  These are rdflib-internal calls, not our code; suppress them so
    # they don't surface as false parse errors when callers run with -W error.
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=DeprecationWarning, module="rdflib")
            dataset = Dataset()
            dataset.parse(data=json.dumps(data), format="json-ld")
    except Exception as exc:  # noqa: BLE001
        issues.append(
            ValidationIssue(
                code="jsonld.parse_error",
                severity="error",
                path="",
                message=f"JSON-LD could not be parsed into an RDF dataset: {exc}",
                validator="jsonld",
                resource_type="jsonld",
            )
        )
        return issues

    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=DeprecationWarning, module="rdflib")
            dataset.serialize(format="nquads")
    except Exception as exc:  # noqa: BLE001
        issues.append(
            ValidationIssue(
                code="jsonld.dataset_materialization_error",
                severity="error",
                path="",
                message=f"JSON-LD parsed, but the RDF dataset could not be materialized to N-Quads: {exc}",
                validator="jsonld",
                resource_type="jsonld",
            )
        )
    return issues


@lru_cache(maxsize=1)
def _pyld_base_document_loader() -> Any:
    if pyld_jsonld is None:
        return None
    try:
        return pyld_jsonld.requests_document_loader(timeout=10)
    except ModuleNotFoundError:
        return _stdlib_document_loader


def _stdlib_document_loader(url: str, _options: dict[str, Any]) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/ld+json, application/json;q=0.9, */*;q=0.1",
            "User-Agent": "battinfo-jsonld-loader/0.1",
        },
    )
    with urlopen(request, timeout=10) as response:  # noqa: S310 - JSON-LD contexts are fetched from caller-provided URLs.
        charset = response.headers.get_content_charset() or "utf-8"
        document = json.loads(response.read().decode(charset))
        return {
            "contextUrl": None,
            "documentUrl": response.geturl(),
            "document": document,
        }


@lru_cache(maxsize=32)
def _cached_pyld_document(url: str) -> dict[str, Any]:
    loader = _pyld_base_document_loader()
    if loader is None:
        raise RuntimeError("PyLD is not available.")
    return loader(url, {})


@lru_cache(maxsize=1)
def _local_emmo_context() -> dict[str, Any]:
    path = resources.files("battinfo").joinpath("data").joinpath("context").joinpath("domain-battery.context.json")
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _pyld_document_loader(url: str, options: dict[str, Any]) -> dict[str, Any]:
    # Serve the bundled EMMO context from the local file to avoid a live network
    # dependency at validation time.  This makes JSON-LD processing reproducible and
    # allows offline use.  The bundled copy is refreshed via
    # .tools/quality/refresh_emmo_context.py when EMMO releases a new version.
    if url == _EMMO_BATTERY_CONTEXT_URL or url.rstrip("/") == _EMMO_BATTERY_CONTEXT_URL:
        return {"contextUrl": None, "documentUrl": url, "document": _local_emmo_context()}
    return copy.deepcopy(_cached_pyld_document(url))


def _urdna2015_issues(data: dict[str, Any]) -> list[ValidationIssue]:
    if pyld_jsonld is None:
        return [
            ValidationIssue(
                code="jsonld.normalizer_unavailable",
                severity="error",
                path="",
                message="PyLD is not installed, so URDNA2015 normalization could not be run.",
                validator="jsonld",
                resource_type="jsonld",
            )
        ]

    try:
        pyld_jsonld.normalize(
            data,
            {
                "algorithm": "URDNA2015",
                "format": "application/n-quads",
                "documentLoader": _pyld_document_loader,
            },
        )
    except Exception as exc:  # noqa: BLE001
        return [
            ValidationIssue(
                code="jsonld.urdna2015_normalization_error",
                severity="error",
                path="",
                message=f"JSON-LD could not be normalized with URDNA2015: {exc}",
                validator="jsonld",
                resource_type="jsonld",
            )
        ]
    return []


def validate_jsonld_report(
    data: dict[str, Any],
    *,
    policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> ValidationReport:
    resolved_policy = get_validation_policy(policy) if isinstance(policy, str) else policy
    errors: list[str] = []
    _walk_relative_type_errors(data, "", errors)
    issues = []
    for rendered in errors:
        path, _, message = rendered.partition(": ")
        issues.append(
            ValidationIssue(
                code="jsonld.type_term_unknown",
                severity="error",
                path=path if _ else "",
                message=message if _ else rendered,
                validator="@type",
                resource_type="jsonld",
            )
        )
    materialization_issues = _parse_materialization_issues(data)
    issues.extend(materialization_issues)
    if not any(issue.code == "jsonld.parse_error" for issue in materialization_issues):
        issues.extend(_urdna2015_issues(data))
    return ValidationReport(issues=tuple(issues), policy=resolved_policy)


def validate_jsonld(
    data: dict[str, Any],
    *,
    policy: ValidationPolicy | str = DEFAULT_POLICY,
) -> ValidationResult:
    return validate_jsonld_report(data, policy=policy).to_result()
