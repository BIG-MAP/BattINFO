"""Guard: every JSON-schema property of every record type is reachable through a model.

Four bugs of one family were found one at a time, each by a human authoring real
data rather than by a test:

* ``Test.conditions`` — the schema defined it, the ``Test`` model had no such
  field, so conditions could not be authored at all (fixed in #329).
* ``reference_electrode`` on cell-spec — the schema defined it, the model dropped
  it on save (fixed in #334).
* ``TestSpec.conditions`` — typed ``dict[str, Quantity]``, so the textual
  conditions the schema permits are inexpressible (open; listed below as M4).
* ``positive_electrode.electrode_spec_id`` — the schema defined it, the JSON-LD
  emitter read it and the registry vendored it, but the inline ``Electrode``
  holder is ``extra="forbid"`` and had no such field, so the seam the electrode
  docs recommend could not be authored at all (readiness finding E1).

E1 escaped this module for a structural reason worth naming: the sweep walked the
record body and its top-level siblings and stopped there, so a component holder
was checked as one property (``positive_electrode`` reaches the model) and never
opened. :func:`test_every_nested_component_property_is_reachable` opens it.

The schema is the save-time contract and the models are the authoring surface, so
a property that exists in one and not the other is data a user cannot express, or
data they express and silently lose. This module sweeps all of it: for every
registered entity kind, every property the JSON schema declares (record body,
top-level siblings, and the closed object schemas nested under either) must be
either

* **reachable** — the model/builder accepts it under its own name or a declared
  authoring alias, and
* **retained** — for scalar-shaped properties, a supplied value survives to the
  built record at the location the schema declares, or
* **derived** — the builder always emits it (``id``, ``short_id``,
  ``provenance``), so authoring it is neither possible nor needed, or
* **listed in :data:`KNOWN_GAPS`** with a reason.

Adding a property to a schema without modeling it therefore fails here, and
:func:`test_known_gaps_are_still_gaps` fails when a listed gap is closed but not
removed from the list, so the list cannot quietly become a graveyard.
"""

from __future__ import annotations

import functools
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.api import (  # noqa: E402
    create_channel,
    create_component_instance,
    create_component_spec,
    create_electrode,
    create_electrode_spec,
    create_equipment,
    create_equipment_spec,
    create_material,
    create_material_spec,
)
from battinfo.bundle import Cell, CellSpec, Dataset, Test, TestSpec  # noqa: E402
from battinfo.entities import COMPONENT_FAMILIES, ENTITY_KINDS  # noqa: E402

SCHEMA_DIR = ROOT / "src" / "battinfo" / "data" / "schemas"

UID = "aaaa-bbbb-cccc-dddd"
SPEC_IRI = f"https://w3id.org/battinfo/spec/{UID}"
CELL_IRI = f"https://w3id.org/battinfo/cell/{UID}"


# ── Known gaps ────────────────────────────────────────────────────────────────
# (entity_type, schema property) -> why it is not reachable through the model.
# Every entry is a deliberate decision or a tracked defect, never "we did not get
# to it". Close one and delete the line; the companion test enforces that.
KNOWN_GAPS: dict[tuple[str, str], str] = {
    # Record envelope. ws.license() / ws.project() / ws.contributor() stamp these
    # onto every record the workspace saves, so they belong to the publishing
    # session rather than to any one record model.
    **{
        (entity_type, prop): (
            "record envelope stamped by the workspace at save time "
            "(ws.license / ws.project / ws.contributor), not authored on the model"
        )
        for entity_type in ("cell-spec", "cell", "test-protocol", "test", "dataset",
                            "material-spec", "material", "electrode-spec", "electrode")
        for prop in ("license", "funding", "contributor")
        # dataset carries its license on the dataset body, which IS modeled
        if not (entity_type == "dataset" and prop == "license")
    },

    # Open defect, tracked as readiness finding M4.
    ("test-protocol", "conditions"): (
        "M4: TestSpec.conditions is typed dict[str, Quantity], so the textual "
        "conditions the schema permits ('room temperature') cannot be expressed. "
        "Same bug family as Test.conditions (#329); fix by widening the value type"
    ),

    # EU Battery Regulation fields on the cell-spec. The schema carries them so a
    # digital product passport can round-trip through a record; nothing authors
    # them through CellSpec yet (see the audit note on the model).
    ("cell-spec", "hazardous_substances"): "EU Battery Regulation Annex XIII field; no authoring path yet",
    ("cell-spec", "critical_raw_materials"): "EU Battery Regulation Annex XIII field; no authoring path yet",
    ("cell-spec", "extinguishing_agent"): "EU Battery Regulation Annex VI field; no authoring path yet",
    ("cell-spec", "battery_category"): "EU Battery Regulation category (LMT/EV/…); no authoring path yet",
    ("cell", "battery_status"): "EU Battery Regulation battery status; no authoring path yet",
    ("cell", "dpp_status"): "digital product passport status; no authoring path yet",
    ("cell", "service_start_date"): "EU Battery Regulation in-service date; no authoring path yet",
    ("cell", "supersedes"): "digital product passport lineage link; no authoring path yet",

    # schema.org descriptive fields the schema permits on a product record.
    ("cell-spec", "brand"): "schema:brand object; datasheets use manufacturer + model instead",
    ("cell-spec", "category"): "schema:category; the emitter derives a category from battery_category/chemistry",
    ("cell-spec", "url"): "schema:url for the product page; datasheet_url/provenance.source_url carry this today",
    ("cell-spec", "additional_type"): "schema:additionalType; the emitter derives the EMMO type from format + chemistry",
    ("cell-spec", "manufacturing_place"): "schema:manufacturingPlace; country_of_origin carries this today",
    ("cell-spec", "editorial"): "internal curation metadata; deliberately not part of the published model",
    ("dataset", "about"): "schema:about link to the entity studied; main_entity is the modeled equivalent",

    # Instance links whose modeled form is a list of IRIs, not the record's
    # {id, role} link objects.
    ("cell", "datasets"): "modeled as Cell.dataset_ids (list of IRIs); the record's {id, role} link shape is built at save",
    ("material", "datasets"): "MaterialInput has no dataset link field; save_material takes dataset_ids separately",

    # Free-text notes on the two material inputs.
    ("material-spec", "comment"): "MaterialSpecInput exposes description=; comment is the record-level notes slot",
    ("material", "comment"): "MaterialInput has no comment field; notes= lands at the record top level",

    # Electrode link/collection shapes whose modeled form differs from the record's.
    ("electrode", "datasets"): "ElectrodeInput has no dataset link field; dataset_ids= builds the {id, role} link shape",

    # Faceted query metadata, written by the indexer rather than the author.
    ("test-protocol", "facets"): "derived query facets written by the record indexer, not authored",
}


# ── Builders: one callable per entity kind, returning a canonical record ───────

def _model_builder(model: type, base: dict[str, Any]) -> Callable[..., dict]:
    def build(**kwargs: Any) -> dict:
        return model(**{**base, **kwargs}).to_record()

    return build


def _api_builder(create: Callable[..., dict], base: dict[str, Any]) -> Callable[..., dict]:
    def build(**kwargs: Any) -> dict:
        # validate=False: this sweep feeds deliberately synthetic values, and the
        # question is whether the property reaches the record, not whether the
        # sample passes the save gate.
        return create(validate=False, **{**base, **kwargs})

    return build


def _builders() -> dict[str, Callable[..., dict]]:
    builders: dict[str, Callable[..., dict]] = {
        "cell-spec": _model_builder(CellSpec, {"id": SPEC_IRI, "name": "probe"}),
        "cell": _model_builder(Cell, {"id": CELL_IRI, "name": "probe", "cell_spec_id": SPEC_IRI}),
        "test-protocol": _model_builder(TestSpec, {"id": SPEC_IRI, "name": "probe"}),
        "test": _model_builder(Test, {
            "id": f"https://w3id.org/battinfo/test/{UID}", "name": "probe",
            "cell_id": CELL_IRI, "kind": "cycling",
        }),
        "dataset": _model_builder(Dataset, {
            "id": f"https://w3id.org/battinfo/dataset/{UID}", "name": "probe",
            "access_url": "https://example.org/dataset",
        }),
        "material-spec": _api_builder(create_material_spec, {"uid": UID, "name": "probe"}),
        "material": _api_builder(create_material, {
            "uid": UID, "name": "probe", "material_spec_id": SPEC_IRI,
        }),
        "electrode-spec": _api_builder(create_electrode_spec, {"uid": UID, "name": "probe"}),
        "electrode": _api_builder(create_electrode, {
            "uid": UID, "name": "probe", "electrode_spec_id": SPEC_IRI,
        }),
        "equipment-spec": _api_builder(create_equipment_spec, {"uid": UID, "name": "probe"}),
        "equipment": _api_builder(create_equipment, {
            "uid": UID, "equipment_spec_id": SPEC_IRI, "serial_number": "S1",
        }),
        "channel": _api_builder(create_channel, {
            "uid": UID, "equipment_id": f"https://w3id.org/battinfo/equipment/{UID}", "index": 1,
        }),
    }
    for family in COMPONENT_FAMILIES:
        hyphen = family.replace("_", "-")
        builders[f"{hyphen}-spec"] = _api_builder(
            functools.partial(create_component_spec, family), {"uid": UID, "name": "probe"}
        )
        builders[hyphen] = _api_builder(
            functools.partial(create_component_instance, family), {"uid": UID, "spec_id": SPEC_IRI}
        )
    return builders


BUILDERS = _builders()

# Schema property -> the authoring keyword that reaches it. Only where the model
# deliberately names a field differently from the record key.
ALIASES: dict[tuple[str, str], str] = {
    ("cell-spec", "cell_format"): "format",
}


# ── Sampling a schema-valid value ─────────────────────────────────────────────

_SCHEMA_CACHE: dict[str, dict] = {}

# Values for properties whose schema constraint a generic sampler cannot satisfy.
SAMPLE_OVERRIDES: dict[tuple[str, str], Any] = {
    ("material-spec", "kind"): "graphite",  # closed vocabulary lives in code, not in the schema
    # Same: the electrode kind names an ACTIVE material from that same vocabulary.
    ("electrode-spec", "kind"): "graphite",
    ("electrode-spec", "active_material_spec_id"): SPEC_IRI,
}

_PATTERN_SAMPLES = {"short_id": "abcdef", "in_language": "en"}
_NAMESPACE_RE = re.compile(r"battinfo/\(\?:([a-z-]+)|battinfo/([a-z-]+)/")


def _load_schema(relative: str) -> dict:
    if relative not in _SCHEMA_CACHE:
        _SCHEMA_CACHE[relative] = json.loads((SCHEMA_DIR / relative).read_text(encoding="utf-8"))
    return _SCHEMA_CACHE[relative]


def _deref(node: Any, root: dict, base: str) -> tuple[dict, dict, str]:
    """Follow ``$ref`` chains, including refs into sibling schema files."""
    for _ in range(20):
        if not (isinstance(node, dict) and "$ref" in node):
            break
        file_part, _, fragment = node["$ref"].partition("#")
        if file_part:
            relative = str((Path(base).parent / file_part).as_posix()) if base else file_part
            try:
                root = _load_schema(relative)
            except FileNotFoundError:
                return {}, root, base
            base = relative
        cursor: Any = root
        for part in fragment.lstrip("/").split("/") if fragment else []:
            cursor = cursor.get(part, {}) if isinstance(cursor, dict) else {}
        node = cursor
    return (node if isinstance(node, dict) else {}), root, base


def sample_value(schema: dict, root: dict, name: str = "", base: str = "", depth: int = 0) -> Any:
    """A value that satisfies *schema*, good enough to prove a property is reachable."""
    schema, root, base = _deref(schema, root, base)
    if depth > 5:
        return "probe"
    for combinator in ("anyOf", "oneOf"):
        if schema.get(combinator):
            return sample_value(schema[combinator][0], root, name, base, depth + 1)
    if schema.get("enum"):
        return schema["enum"][0]
    if "const" in schema:
        return schema["const"]

    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((entry for entry in kind if entry != "null"), "string")

    if kind == "array":
        return [sample_value(schema.get("items", {"type": "string"}), root, name, base, depth + 1)]
    if kind == "object":
        value: dict[str, Any] = {}
        properties = schema.get("properties", {})
        for required in schema.get("required", []):
            if required in properties:
                value[required] = sample_value(properties[required], root, required, base, depth + 1)
        if not value and properties:
            first = next(iter(properties))
            value[first] = sample_value(properties[first], root, first, base, depth + 1)
        return value or {"name": "probe"}
    if kind == "boolean":
        return True
    if kind == "integer":
        low, high = schema.get("minimum", 1), schema.get("maximum", 3000)
        return 1990 if low <= 1990 <= high else int(low)
    if kind == "number":
        return float(schema.get("minimum", 0)) + 1.5

    fmt = schema.get("format")
    if fmt == "uri":
        return "https://example.org/probe"
    if fmt == "date":
        return "2024-01-01"
    if fmt == "date-time":
        return "2024-01-01T00:00:00Z"
    if schema.get("pattern"):
        if name in _PATTERN_SAMPLES:
            return _PATTERN_SAMPLES[name]
        match = _NAMESPACE_RE.search(schema["pattern"])
        if match:
            return f"https://w3id.org/battinfo/{match.group(1) or match.group(2)}/{UID}"
        return None  # unsamplable pattern; treated as a sweep gap, not a parity gap
    return "probe"


def _is_scalar(schema: dict, root: dict, base: str) -> bool:
    schema, _, _ = _deref(schema, root, base)
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((entry for entry in kind if entry != "null"), None)
    return kind in {"string", "integer", "number", "boolean"} or bool(schema.get("enum"))


# ── The sweep ─────────────────────────────────────────────────────────────────

def _unknown_property_error(exc: Exception, prop: str) -> bool:
    """True when *exc* says the property is not modeled (vs. a wrong sample shape).

    A wrong sample is this test's fault and must not be reported as a parity gap,
    so only rejections naming the property itself count.
    """
    if isinstance(exc, ValidationError):
        return any(
            error["type"] in {"extra_forbidden", "unexpected_keyword_argument"}
            and tuple(error["loc"]) == (prop,)
            for error in exc.errors()
        )
    if isinstance(exc, TypeError):
        message = str(exc)
        return "Unknown field(s)" in message or "unexpected keyword argument" in message
    return False


def _unknown_nested_error(exc: Exception, path: tuple[str, ...]) -> bool:
    """True when *exc* rejects the nested key at *path* as not modeled.

    Pydantic reports the full location of a rejected key inside a nested model
    (``('positive_electrode', 'electrode_spec_id')``), so match on the tail: the
    holder may sit under a list index or an alias that shifts the head.
    """
    if not isinstance(exc, ValidationError):
        return False
    return any(
        error["type"] in {"extra_forbidden", "unexpected_keyword_argument"}
        and tuple(str(part) for part in error["loc"])[-len(path):] == path
        for error in exc.errors()
    )


def _schema_properties(kind: Any) -> list[tuple[str, str, dict]]:
    """``(location, property, subschema)`` for the record body and its siblings."""
    root = _load_schema(kind.schema_file)
    body = root["properties"][kind.record_key].get("properties", {})
    siblings = {
        name: subschema
        for name, subschema in root["properties"].items()
        if name not in {"schema_version", kind.record_key}
    }
    return (
        [("body", name, subschema) for name, subschema in body.items()]
        + [("top", name, subschema) for name, subschema in siblings.items()]
    )


def _sweep() -> tuple[list[str], list[str], int]:
    """(unreachable, dropped-on-save, properties actually exercised)."""
    unreachable: list[str] = []
    dropped: list[str] = []
    exercised = 0

    for kind in ENTITY_KINDS:
        entity_type = kind.entity_type
        build = BUILDERS[entity_type]
        root = _load_schema(kind.schema_file)
        baseline = build()

        for location, prop, subschema in _schema_properties(kind):
            if (entity_type, prop) in KNOWN_GAPS:
                continue
            target = baseline.get(kind.record_key, {}) if location == "body" else baseline
            if prop in target:
                continue  # derived: the builder always emits it

            if (entity_type, prop) in SAMPLE_OVERRIDES:
                value = SAMPLE_OVERRIDES[(entity_type, prop)]
            else:
                value = sample_value(subschema, root, prop, kind.schema_file)
            if value is None:
                continue

            keyword = ALIASES.get((entity_type, prop), prop)
            try:
                record = build(**{keyword: value})
            except Exception as exc:  # noqa: BLE001 - classified below
                if _unknown_property_error(exc, keyword):
                    try:  # component families take arbitrary body fields
                        record = build(body={prop: value})
                    except Exception:  # noqa: BLE001
                        unreachable.append(f"{entity_type}.{prop} ({location}): {str(exc).splitlines()[0]}")
                        continue
                else:
                    continue  # sample shape mismatch: the field exists, this test guessed badly
            exercised += 1

            if not _is_scalar(subschema, root, kind.schema_file):
                continue
            written = record.get(kind.record_key, {}) if location == "body" else record
            if prop not in written:
                dropped.append(f"{entity_type}.{prop} ({location}) accepted a value but to_record() omitted it")

    return unreachable, dropped, exercised


# ── The nested sweep ──────────────────────────────────────────────────────────
# The sweep above treats a component holder as one property. This one opens it:
# for every closed object schema (``additionalProperties: false`` with declared
# properties) reachable from a record type, each of its own properties must be
# authorable through the model that holds it, and scalars must survive to the
# record. That is where E1 lived, and where the same seam on the current
# collector was found with it.

# Nested location -> why it is not reachable, same contract as KNOWN_GAPS.
KNOWN_NESTED_GAPS: dict[tuple[str, str], str] = {}

# How deep to open holders. 3 reaches cell-spec.positive_electrode.coating
# .component (holder -> sub-holder -> material component), which is the deepest
# closed object the component schemas define.
_MAX_NESTED_DEPTH = 3


def _closed_object(subschema: dict, root: dict, base: str) -> tuple[dict, dict, str] | None:
    """(schema, root, base) when *subschema* is a closed object with properties."""
    schema, root, base = _deref(subschema, root, base)
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((entry for entry in kind if entry != "null"), None)
    if kind != "object" or schema.get("additionalProperties") is not False:
        return None
    if not isinstance(schema.get("properties"), dict) or not schema["properties"]:
        return None
    return schema, root, base


def _nested_sweep() -> tuple[list[str], list[str], int]:
    """(unreachable, dropped-on-save, nested properties actually exercised)."""
    unreachable: list[str] = []
    dropped: list[str] = []
    exercised = 0

    for kind in ENTITY_KINDS:
        entity_type = kind.entity_type
        build = BUILDERS[entity_type]
        root = _load_schema(kind.schema_file)
        baseline = build()

        def walk(
            subschema: dict, sub_root: dict, base: str,
            path: tuple[str, ...], record_path: tuple[str, ...], depth: int,
            *, _entity_type: str = entity_type, _build: Any = build,
        ) -> None:
            nonlocal exercised
            opened = _closed_object(subschema, sub_root, base)
            if opened is None or depth > _MAX_NESTED_DEPTH:
                return
            obj_schema, obj_root, obj_base = opened
            # A schema-valid payload satisfies the holder's own required keys, so
            # a model that normalizes on a required field (an agent needs a name)
            # is not misread as dropping the property under test.
            required = {
                name: sample_value(obj_schema["properties"][name], obj_root, name, obj_base)
                for name in obj_schema.get("required", [])
                if name in obj_schema["properties"]
            }
            for name, nested_schema in obj_schema["properties"].items():
                if (_entity_type, ".".join(path + (name,))) in KNOWN_NESTED_GAPS:
                    continue
                value = sample_value(nested_schema, obj_root, name, obj_base)
                if value is None:
                    continue
                payload: Any = {**required, name: value}
                for segment in reversed(path[1:]):
                    payload = {segment: payload}
                exercised += 1
                try:
                    record = _build(**{path[0]: payload})
                except Exception as exc:  # noqa: BLE001 - classified here
                    if _unknown_nested_error(exc, path[1:] + (name,)):
                        unreachable.append(f"{_entity_type}.{'.'.join(path + (name,))}")
                    continue  # anything else is a sample-shape mismatch, not a gap

                if _is_scalar(nested_schema, obj_root, obj_base):
                    cursor: Any = record
                    for segment in record_path + path:
                        cursor = cursor.get(segment) if isinstance(cursor, dict) else None
                        if cursor is None:
                            break
                    if not isinstance(cursor, dict) or name not in cursor:
                        dropped.append(f"{_entity_type}.{'.'.join(path + (name,))}")
                walk(nested_schema, obj_root, obj_base, path + (name,), record_path, depth + 1)

        for location, prop, subschema in _schema_properties(kind):
            target = baseline.get(kind.record_key, {}) if location == "body" else baseline
            if prop in target:
                continue  # derived: the builder writes the whole block itself
            record_path = () if location == "top" else (kind.record_key,)
            walk(subschema, root, kind.schema_file, (prop,), record_path, 0)

    return unreachable, dropped, exercised


def test_every_nested_component_property_is_reachable() -> None:
    """E1's family: a closed holder must model every property its schema declares."""
    unreachable, _, _ = _nested_sweep()
    assert not unreachable, (
        "properties of nested component schemas with no authoring path. Add the "
        "field to the holder model, or add it to KNOWN_NESTED_GAPS with a "
        "reason:\n  " + "\n  ".join(sorted(unreachable))
    )


def test_no_nested_property_is_dropped_between_the_model_and_the_record() -> None:
    """A nested value the model accepts must reach the record."""
    _, dropped, _ = _nested_sweep()
    assert not dropped, (
        "nested values accepted by the model but missing from the built record:\n  "
        + "\n  ".join(sorted(dropped))
    )


def test_nested_sweep_actually_exercises_the_corpus() -> None:
    """The sweep that would have caught E1 must keep opening holders."""
    _, _, exercised = _nested_sweep()
    assert exercised >= 800, (
        f"only {exercised} nested properties round-tripped a value; the nested sweep is degrading"
    )


def test_known_nested_gaps_all_carry_a_reason() -> None:
    empty = [key for key, reason in KNOWN_NESTED_GAPS.items() if not reason.strip()]
    assert not empty, f"KNOWN_NESTED_GAPS entries without a reason: {empty}"


@pytest.mark.parametrize("holder", ["positive_electrode", "negative_electrode",
                                    "working_electrode", "counter_electrode"])
def test_electrode_holder_models_both_spec_seams(holder: str) -> None:
    """E1 by name, on every electrode holder, through the blessed authoring path.

    The role holders (working / counter) are the same shape as the polarity ones,
    so the seam that went missing on ``positive_electrode`` is pinned on all four
    rather than left to the sweep alone.
    """
    from battinfo.bundle import Electrode

    inline = CellSpec(id=SPEC_IRI, name="probe", **{holder: Electrode(electrode_spec_id=SPEC_IRI)})
    # Assignment after construction is the shape the readiness report used.
    getattr(inline, holder).electrode_spec_id = SPEC_IRI
    record = inline.to_record()
    assert record[holder]["electrode_spec_id"] == SPEC_IRI
    assert getattr(CellSpec.from_record(record), holder).electrode_spec_id == SPEC_IRI
    assert CellSpec.from_record(record).to_record() == record


def test_every_schema_property_is_reachable_through_a_model() -> None:
    """No schema property may exist that a user cannot author through the model."""
    unreachable, _, _ = _sweep()
    assert not unreachable, (
        "schema properties with no authoring path. Add the field to the model, or "
        "add it to KNOWN_GAPS with a reason:\n  " + "\n  ".join(sorted(unreachable))
    )


def test_no_property_is_dropped_between_the_model_and_the_record() -> None:
    """A value the model accepts must reach the record (the reference_electrode bug)."""
    _, dropped, _ = _sweep()
    assert not dropped, (
        "values accepted by the model but missing from the built record:\n  "
        + "\n  ".join(sorted(dropped))
    )


def test_sweep_actually_exercises_the_corpus() -> None:
    """A sweep that silently stops finding properties would pass while testing nothing."""
    _, _, exercised = _sweep()
    total = sum(len(_schema_properties(kind)) for kind in ENTITY_KINDS)
    assert total >= 350, f"only {total} schema properties discovered; the registry shrank?"
    assert exercised >= 200, f"only {exercised} properties round-tripped a value; the sweep is degrading"


def test_every_entity_kind_has_a_builder() -> None:
    """A new record type must be swept, not silently skipped."""
    missing = [kind.entity_type for kind in ENTITY_KINDS if kind.entity_type not in BUILDERS]
    assert not missing, f"entity kinds with no builder in this sweep: {missing}"


@pytest.mark.parametrize(("entity_type", "prop"), sorted(KNOWN_GAPS))
def test_known_gaps_are_still_gaps(entity_type: str, prop: str) -> None:
    """Delete the entry when the gap closes: an allowlist that never shrinks is a lie."""
    kind = next(k for k in ENTITY_KINDS if k.entity_type == entity_type)
    root = _load_schema(kind.schema_file)
    declared = _schema_properties(kind)
    subschema = next((s for _, name, s in declared if name == prop), None)
    assert subschema is not None, (
        f"{entity_type}.{prop} is in KNOWN_GAPS but the schema no longer declares it; delete the entry"
    )

    build = BUILDERS[entity_type]
    value = SAMPLE_OVERRIDES.get(
        (entity_type, prop), sample_value(subschema, root, prop, kind.schema_file)
    )
    if value is None:
        return
    try:
        build(**{ALIASES.get((entity_type, prop), prop): value})
    except Exception as exc:  # noqa: BLE001
        if _unknown_property_error(exc, ALIASES.get((entity_type, prop), prop)):
            return
    else:
        pytest.fail(
            f"{entity_type}.{prop} is now reachable through the model; remove it from KNOWN_GAPS"
        )


def test_known_gaps_all_carry_a_reason() -> None:
    empty = [key for key, reason in KNOWN_GAPS.items() if not reason.strip()]
    assert not empty, f"KNOWN_GAPS entries without a reason: {empty}"
