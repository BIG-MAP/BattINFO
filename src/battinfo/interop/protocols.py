"""Importers from executable cycling-protocol formats into a descriptive TestSpec.

Each importer parses a machine-actionable protocol (aurora-unicycler JSON, a
PyBaMM experiment, or bmgen EMMO JSON-LD) into the canonical structured ``method``
and links the source file back as a Layer-B ``source_protocol`` artifact, so the
descriptive (queryable) and actionable (runnable) layers stay connected.

The descriptive layer is allowed to be lossy: the imported method is a faithful
summary; the linked artifact remains the executable source of truth.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

from battinfo.bundle import Artifact, ProvenanceInfo, TestSpec
from battinfo.testmethod import (
    ExperimentSyntaxError,
    Quantity,
    Step,
    Termination,
    _parse_value,
    _termination_from_value,
    parse_experiment,
    parse_step,
)

__all__ = [
    "import_aurora_unicycler",
    "import_pybamm_experiment",
    "import_bmgen_jsonld",
]


# ── helpers ─────────────────────────────────────────────────────────────────

def _load(source: Any) -> Any:
    """Accept a parsed object, a JSON string, or a path to a JSON file."""
    if isinstance(source, (dict, list)):
        return source
    text = Path(source).read_text(encoding="utf-8") if _looks_like_path(source) else str(source)
    return json.loads(text)


def _looks_like_path(source: Any) -> bool:
    if not isinstance(source, (str, Path)):
        return False
    s = str(source)
    return len(s) < 1024 and not s.lstrip().startswith(("{", "["))


def _num(value: Any) -> float | None:
    """aurora-unicycler JSON stores numbers as strings; coerce leniently.

    A non-finite result (NaN / +-Infinity) is rejected as ``None``: it is never a
    valid measurement and is not JSON-serialisable (RFC 8259), so it must never be
    coerced into a quantity that later survives validation and fails on export.
    """
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _q(value: float, unit: str) -> Quantity:
    return Quantity(value=value, unit=unit)


def _source_artifact(fmt: str, locator: str | None, sha256: str | None,
                     conforms_to: str | None) -> list[Artifact]:
    if not locator:
        return []
    return [Artifact(role="source_protocol", format=fmt, locator=locator,
                     sha256=sha256, conforms_to=conforms_to)]


def _provenance(source_file: str | None) -> ProvenanceInfo:
    # Stamp retrieval time so the imported record is schema-valid standalone
    # (mirrors the save/publish path, which mints retrieved_at when absent).
    return ProvenanceInfo(type="import", file=source_file, retrieved_at=int(time.time()))


# ── aurora-unicycler ──────────────────────────────────────────────────────────

_AURORA_CONFORMS = "https://github.com/EmpaEconversion/aurora-unicycler"


def _aurora_leaf(s: dict) -> Step | None:
    kind = s.get("step")
    if kind == "open_circuit_voltage":
        st = Step(mode="rest", direction="rest")
        if _num(s.get("until_time_s")) is not None:
            st.duration = _q(_num(s["until_time_s"]), "s")
        return st

    if kind == "constant_current":
        rate, cur = _num(s.get("rate_C")), _num(s.get("current_mA"))
        signed = rate if rate is not None else cur
        direction = "discharge" if (signed is not None and signed < 0) else "charge"
        setpoints: dict[str, Quantity] = {}
        if rate is not None:
            setpoints["c_rate"] = _q(abs(rate), "A/Ah")
        elif cur is not None:
            setpoints["current"] = _q(abs(cur) / 1000.0, "A")
        st = Step(mode="cc", direction=direction, setpoints=setpoints)
        terms: list[Termination] = []
        if _num(s.get("until_voltage_V")) is not None:
            terms.append(Termination(quantity="voltage", value=_num(s["until_voltage_V"]), unit="V",
                                     direction="above" if direction == "charge" else "below"))
        if _num(s.get("until_time_s")) is not None:
            st.duration = _q(_num(s["until_time_s"]), "s")
        st.termination = terms
        return st

    if kind == "constant_voltage":
        setpoints = {}
        if _num(s.get("voltage_V")) is not None:
            setpoints["voltage"] = _q(_num(s["voltage_V"]), "V")
        st = Step(mode="cv", direction="hold", setpoints=setpoints)
        terms = []
        if _num(s.get("until_rate_C")) is not None:
            terms.append(Termination(quantity="c_rate", value=abs(_num(s["until_rate_C"])),
                                     unit="A/Ah", direction="below"))
        if _num(s.get("until_current_mA")) is not None:
            terms.append(Termination(quantity="current", value=abs(_num(s["until_current_mA"])) / 1000.0,
                                     unit="A", direction="below"))
        if _num(s.get("until_time_s")) is not None:
            st.duration = _q(_num(s["until_time_s"]), "s")
        st.termination = terms
        return st

    if kind == "impedance_spectroscopy":
        setpoints = {}
        for key, unit in (("start_frequency_Hz", "Hz"), ("end_frequency_Hz", "Hz"),
                          ("amplitude_V", "V"), ("amplitude_mA", "mA")):
            if _num(s.get(key)) is not None:
                setpoints[key.rsplit("_", 1)[0]] = _q(_num(s[key]), unit)
        return Step(mode="eis", direction="hold", setpoints=setpoints)

    if kind == "voltage_scan":
        setpoints = {}
        for key, unit in (("start_voltage_V", "V"), ("end_voltage_V", "V"),
                          ("scan_rate_mV_per_s", "mV/s")):
            if _num(s.get(key)) is not None:
                setpoints[key.rsplit("_", 1)[0] if key.endswith("_V") else key] = _q(_num(s[key]), unit)
        return Step(mode="scan", direction="charge", setpoints=setpoints)

    return None  # tag / loop / unknown handled by the caller


def _fold_aurora_method(method: list[dict]) -> tuple[list[Step], list[str]]:
    """Parse aurora's flat method (with Tag/Loop goto steps) into nested groups."""
    warnings: list[str] = []
    tag_pos: dict[str, int] = {}
    flat: list[dict] = []  # [{"orig": int, "step": Step}]
    for i, s in enumerate(method):
        kind = s.get("step")
        if kind == "tag":
            if s.get("tag"):
                tag_pos[s["tag"]] = i
            continue
        if kind == "loop":
            loop_to = s.get("loop_to", 1)
            count = int(_num(s.get("cycle_count")) or 1)
            start = tag_pos[loop_to] if isinstance(loop_to, str) and loop_to in tag_pos else (
                int(_num(loop_to) or 1) - 1)
            body = [f["step"] for f in flat if f["orig"] >= start]
            flat = [f for f in flat if f["orig"] < start]
            if body:
                flat.append({"orig": i, "step": Step(mode="group", count=count, steps=body)})
            continue
        st = _aurora_leaf(s)
        if st is not None:
            flat.append({"orig": i, "step": st})
        else:
            warnings.append(f"aurora-unicycler: skipped unsupported step '{kind}'.")
    return [f["step"] for f in flat], warnings


def import_aurora_unicycler(source: Any, *, name: str | None = None, kind: str | None = None,
                            source_locator: str | None = None, source_sha256: str | None = None) -> TestSpec:
    """Import an aurora-unicycler protocol (dict | JSON string | path) into a TestSpec."""
    doc = _load(source)
    method = doc.get("method") or []
    steps, warnings = _fold_aurora_method(method)

    record: dict[str, Any] = {}
    for key in ("time_s", "voltage_V", "current_mA"):
        v = _num((doc.get("record") or {}).get(key))
        if v is not None:
            record[key] = v
    safety: dict[str, Any] = {}
    for key in ("max_voltage_V", "min_voltage_V", "max_current_mA", "min_current_mA",
                "max_capacity_mAh", "delay_s"):
        v = _num((doc.get("safety") or {}).get(key))
        if v is not None:
            safety[key] = v

    sample = doc.get("sample") or {}
    inferred_kind = kind or ("cycling" if any(s.mode == "group" for s in steps) else "other")
    return TestSpec(
        name=name or sample.get("name") or "Imported aurora-unicycler protocol",
        test_kind=inferred_kind,
        description="Imported from an aurora-unicycler protocol.",
        method=steps,
        record=record,
        safety=safety,
        artifacts=_source_artifact("aurora-unicycler-json", source_locator, source_sha256, _AURORA_CONFORMS),
        source=_provenance(source_locator),
        comment=warnings,
    )


# ── PyBaMM experiment ─────────────────────────────────────────────────────────

_PYBAMM_CONFORMS = "https://docs.pybamm.org/en/stable/source/api/experiment/index.html"


# PyBaMM step `type` (class name) substring → (mode, default direction, setpoint key, unit).
_PYBAMM_TYPE = (
    ("rest", ("rest", "rest", None, None)),
    ("ocv", ("rest", "rest", None, None)),
    ("opencircuit", ("rest", "rest", None, None)),
    ("voltage", ("cv", "hold", "voltage", "V")),
    ("power", ("cp", None, "power", "W")),
    ("resistance", ("cr", None, "resistance", "Ohm")),
    ("current", ("cc", None, "current", "A")),
)


def _pybamm_mode(type_name: str) -> tuple[str, str | None, str | None, str | None] | None:
    low = (type_name or "").lower()
    for needle, info in _PYBAMM_TYPE:
        if needle in low:
            return info
    return None


def _pybamm_config_step(s: Any) -> Step | None:
    """A single PyBaMM to_config() step dict (or string) → a structured Step.

    Prefers the step's preserved PyBaMM string (``description``) so it reuses the
    grammar parser; falls back to interpreting type/value/termination/duration."""
    if isinstance(s, str):
        try:
            return parse_step(s)
        except ExperimentSyntaxError:
            return None
    if not isinstance(s, dict):
        return None
    desc = s.get("description")
    if isinstance(desc, str) and desc.strip():
        try:
            return parse_step(desc)
        except ExperimentSyntaxError:
            pass
    info = _pybamm_mode(s.get("type", ""))
    if info is None:
        return None
    mode, default_dir, sp_key, sp_unit = info
    direction = (s.get("direction") or "").strip().lower() or default_dir
    if direction not in ("charge", "discharge", "hold", "rest", None):
        direction = default_dir
    step = Step(mode=mode, direction=direction)
    value = s.get("value")
    if sp_key is not None and value is not None:
        if isinstance(value, str):
            try:
                kind, qty = _parse_value(value)
                step.setpoints[kind] = qty
            except ExperimentSyntaxError:
                step.setpoints[sp_key] = _q(_num(value) or 0.0, sp_unit)
        else:
            num = _num(value)
            if num is not None:
                step.setpoints[sp_key] = _q(abs(num) if mode != "cv" else num, sp_unit)
    for term in s.get("termination") or []:
        parsed = _pybamm_termination(term, direction)
        if parsed is not None:
            step.termination.append(parsed)
    dur = _num(s.get("duration"))
    if dur is not None:
        step.duration = _q(dur, "s")
    temp = _num(s.get("temperature"))
    if temp is not None:
        step.temperature = _q(temp, "K")
    tags = s.get("tags")
    if isinstance(tags, list):
        step.tags = [str(t) for t in tags]
    return step


def _pybamm_termination(term: Any, direction: str | None) -> Termination | None:
    text = term if isinstance(term, str) else (term.get("value") if isinstance(term, dict) else None)
    if text is None:
        return None
    try:
        kind, qty = _parse_value(str(text))
    except ExperimentSyntaxError:
        return None
    return _termination_from_value(kind, qty, direction)


def _pybamm_items_to_method(items: list) -> list[Step]:
    """The pybamm.Experiment list form: strings (single steps) + lists/tuples
    (cycles, repeated via [(...)] * N → consecutive identical entries)."""
    method: list[Step] = []
    i = 0
    while i < len(items):
        item = items[i]
        if isinstance(item, (list, tuple)):
            run = 1
            while i + run < len(items) and items[i + run] == item:
                run += 1
            inner = parse_experiment([str(s) for s in item])
            method.append(Step(mode="group", count=run, steps=inner))
            i += run
        else:
            method.append(parse_experiment([str(item)])[0])
            i += 1
    return method


def _pybamm_config_to_method(config: dict) -> list[Step]:
    """A pybamm to_config() dict → method. A single cycle flattens; multiple
    cycles become groups, with consecutive identical cycles folded into one
    repeated group (the [(...)] * N case after to_config expands it)."""
    cycles = config.get("cycles") or []
    if len(cycles) == 1:
        return [st for st in (_pybamm_config_step(s) for s in cycles[0]) if st is not None]
    method: list[Step] = []
    i = 0
    while i < len(cycles):
        cyc = cycles[i]
        run = 1
        while i + run < len(cycles) and cycles[i + run] == cyc:
            run += 1
        inner = [st for st in (_pybamm_config_step(s) for s in cyc) if st is not None]
        method.append(Step(mode="group", count=run, steps=inner))
        i += run
    return method


def import_pybamm_experiment(source: Any, *, name: str | None = None, kind: str | None = None,
                             source_locator: str | None = None) -> TestSpec:
    """Import a PyBaMM experiment definition into a TestSpec.

    Accepts either the list passed to ``pybamm.Experiment`` (strings for single
    steps, lists/tuples for cycles, ``[(...)] * N`` style) OR a ``to_config()``
    dict ``{"cycles": [[step_dict, …], …]}`` (or a JSON string / path to one).
    Consecutive identical cycles fold into one repeated group."""
    data = source
    if isinstance(source, (str, Path)) and (_looks_like_path(source)
                                            or (isinstance(source, str) and source.lstrip().startswith("{"))):
        data = _load(source)

    method: list[Step]
    if isinstance(data, dict) and "cycles" in data:
        method = _pybamm_config_to_method(data)
    else:
        if isinstance(data, str):
            data = [data]
        method = _pybamm_items_to_method(list(data))

    inferred_kind = kind or ("cycling" if any(s.mode == "group" for s in method) else "other")
    return TestSpec(
        name=name or "Imported PyBaMM experiment",
        test_kind=inferred_kind,
        description="Imported from a PyBaMM experiment definition.",
        method=method,
        artifacts=_source_artifact("pybamm-experiment", source_locator, None, _PYBAMM_CONFORMS),
        source=_provenance(source_locator),
    )


# ── bmgen EMMO JSON-LD ─────────────────────────────────────────────────────────

_BMGEN_CONFORMS = "https://github.com/digibatt/bmgen"

# EMMO process class (bmgen @type) → (mode, direction)
_BMGEN_STEP = {
    "ConstantCurrentCharging": ("cc", "charge"),
    "ConstantCurrentDischarging": ("cc", "discharge"),
    "ConstantCurrentConstantVoltageCharging": ("cccv", "charge"),
    "ConstantCurrentConstantVoltageDischarging": ("cccv", "discharge"),
    "ConstantPowerCharging": ("cp", "charge"),
    "ConstantPowerDischarging": ("cp", "discharge"),
    "OpenCircuitHold": ("rest", "rest"),
    "VoltageHold": ("cv", "hold"),
}
# EMMO quantity class → (group, setpoint-key, unit)
_BMGEN_SETPOINT = {
    "ChargingCurrent": ("current", "A"),
    "DischargingCurrent": ("current", "A"),
    "ChargingVoltage": ("voltage", "V"),
    "CRate": ("c_rate", "A/Ah"),
}
# EMMO termination class → (quantity, direction)
_BMGEN_TERMINATION = {
    "LowerVoltageLimit": ("voltage", "below"),
    "UpperVoltageLimit": ("voltage", "above"),
    "TerminationQuantity": ("current", "below"),
}


def _bmgen_type(node: dict) -> str:
    t = node.get("@type")
    if isinstance(t, list):
        return next((x for x in t if x not in ("schema:HowToStep",)), t[0] if t else "")
    return t or ""


def _bmgen_value(node: dict) -> float | None:
    part = node.get("hasNumericalPart") or {}
    return _num(part.get("hasNumberValue", part.get("hasNumericalValue")))


def _bmgen_step(node: dict) -> Step | None:
    cls = _bmgen_type(node)
    mode_dir = _BMGEN_STEP.get(cls)
    if mode_dir is None:
        return None
    mode, direction = mode_dir
    step = Step(mode=mode, direction=direction)
    for param in node.get("hasProcessParameter") or []:
        if not isinstance(param, dict):
            continue
        pcls = _bmgen_type(param)
        value = _bmgen_value(param)
        if value is None:
            continue
        if pcls in _BMGEN_SETPOINT:
            key, unit = _BMGEN_SETPOINT[pcls]
            step.setpoints[key] = _q(abs(value), unit)
        elif pcls in _BMGEN_TERMINATION:
            quantity, tdir = _BMGEN_TERMINATION[pcls]
            unit = {"voltage": "V", "current": "A"}[quantity]
            step.termination.append(Termination(quantity=quantity, value=value, unit=unit, direction=tdir))
    return step


def import_bmgen_jsonld(source: Any, *, name: str | None = None, kind: str | None = None,
                        source_locator: str | None = None) -> TestSpec:
    """Import a bmgen EMMO/BattINFO JSON-LD program into a TestSpec."""
    doc = _load(source)
    graph = doc.get("@graph", doc) if isinstance(doc, dict) else doc
    nodes = graph if isinstance(graph, list) else [graph]
    # Steps are the nodes carrying hasProcessParameter (bmgen) or hasTask order.
    steps: list[Step] = []
    warnings: list[str] = []
    for node in nodes:
        if not isinstance(node, dict) or "hasProcessParameter" not in node:
            continue
        st = _bmgen_step(node)
        if st is not None:
            steps.append(st)
        else:
            warnings.append(f"bmgen: skipped unsupported step '{_bmgen_type(node)}'.")

    return TestSpec(
        name=name or "Imported bmgen program",
        test_kind=kind or "other",
        description="Imported from a bmgen EMMO JSON-LD program.",
        method=steps,
        artifacts=_source_artifact("bmgen-jsonld", source_locator, None, _BMGEN_CONFORMS),
        source=_provenance(source_locator),
        comment=warnings,
    )
