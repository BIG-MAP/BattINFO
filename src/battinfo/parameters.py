"""Parameter vocabulary, model-tier completeness, and claim collation.

Parameters live as *claims* inside ``parameter-set`` records: one record = one
source (paper, BPX file, lab fit). A claim batch makes claims about one target
(a material kind, a material spec, or a cell spec); a parameter file (one BPX
file) groups its claims by part (cell, materials, electrodes, separator,
electrolyte, state). Many records may claim values for the same parameter of
the same material — the spread across sources is data, not a conflict. This
module is the shared contract on top of those records:

- the curated parameter vocabulary (``data/vocab/parameters.json``): canonical
  snake_case keys, physical scopes, canonical units, BPX fields
  (:func:`bpx_field`);
- the model-tier completeness contract (``bote``/``spm``/``spme``/``p2d``):
  which parameters a scope needs before that model tier can honestly run,
  computed by :func:`completeness` and shipped as JSON so downstream surfaces
  (registry, web) apply identical rules;
- collation: :func:`collate_claims` folds any number of parameter-set records
  into ``{parameter: [claim, ...]}`` with per-claim source context attached.

Unknown parameter keys are tolerated everywhere (tolerant-import policy); they
simply never count toward tier completeness.
"""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any, Iterable, Mapping

PARAMETER_SCOPES: tuple[str, ...] = (
    "material", "electrode", "separator", "electrolyte", "cell", "state",
)

# The parts of a parameter file (one BPX file), in canonical order. A part
# holds the claims one BPX block makes; an electrode block splits into its
# material (intrinsic) part and its electrode (build) part.
PARAMETER_FILE_PARTS: tuple[str, ...] = (
    "cell",
    "negative_material",
    "negative_electrode",
    "positive_material",
    "positive_electrode",
    "separator",
    "electrolyte",
    "state",
)
MATERIAL_PARTS: tuple[str, ...] = ("negative_material", "positive_material")

# Transport parameters a physics model needs strictly positive. A scalar claim
# of zero or less for one of them is a placeholder (a BPX file that keeps the
# real model in User-defined, for example), not a value anyone obtained: the
# BPX importer gives it no provenance class, and record validation warns. A
# table may reach zero (a conductivity at zero concentration), so only
# scalars count.
_POSITIVE_TRANSPORT_PARAMETERS = frozenset({
    "ionic_conductivity",
    "electrolyte_diffusivity",
    "transference_number",
    "solid_diffusivity",
    "electronic_conductivity",
    "transport_efficiency",
})


def _nonpositive_transport_value(claim: Any) -> float | None:
    """The value of a scalar transport claim that is zero or negative, else ``None``."""
    if not isinstance(claim, Mapping):
        return None
    if (resolve_parameter(claim.get("parameter")) or claim.get("parameter")) not in _POSITIVE_TRANSPORT_PARAMETERS:
        return None
    quantity = claim.get("quantity")
    value = quantity.get("value") if isinstance(quantity, Mapping) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value > 0:
        return None
    return value


def _load_parameters_file() -> dict[str, Any]:
    packaged_path = resources.files("battinfo").joinpath("data", "vocab", "parameters.json")
    if packaged_path.is_file():
        with packaged_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    repo_root = Path(__file__).resolve().parents[2]
    asset_path = repo_root.joinpath("src", "battinfo", "data", "vocab", "parameters.json")
    if asset_path.is_file():
        with asset_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    return {"version": "0", "parameters": {}, "tiers": {}}


@lru_cache(maxsize=1)
def _parameters_data() -> dict[str, Any]:
    return _load_parameters_file()


@lru_cache(maxsize=1)
def _parameter_alias_index() -> dict[str, str]:
    """Map every lowercased key/label to its canonical parameter key.

    BPX field names are deliberately NOT in this index: BPX reuses names across
    blocks with different meanings ('Conductivity [S.m-1]' is electronic in an
    electrode block, ionic in the electrolyte block), so BPX resolution must be
    block-scoped — see :func:`resolve_bpx_field`.
    """
    index: dict[str, str] = {}
    for key, entry in _parameters_data().get("parameters", {}).items():
        index[key.lower()] = key
        label = entry.get("label")
        if isinstance(label, str) and label.strip():
            index.setdefault(label.strip().lower(), key)
    return index


def _bpx_mapping(entry: Mapping[str, Any], block: str) -> dict[str, str] | None:
    """One vocabulary entry's BPX mapping for ``block``: ``{"field", "unit", "section"?}``.

    The vocabulary states a mapping as the field name (read in the key's
    canonical unit) or as an object naming the field, the BPX unit when it
    differs, and for the State block the section that holds the field.
    """
    bpx = entry.get("bpx")
    if not isinstance(bpx, Mapping):
        return None
    raw = bpx.get(block)
    if isinstance(raw, str) and raw.strip():
        return {"field": raw.strip(), "unit": str(entry.get("unit", "1"))}
    if isinstance(raw, Mapping) and isinstance(raw.get("field"), str) and raw["field"].strip():
        mapping = {"field": raw["field"].strip(), "unit": str(raw.get("unit") or entry.get("unit", "1"))}
        if isinstance(raw.get("section"), str) and raw["section"].strip():
            mapping["section"] = raw["section"].strip()
        return mapping
    return None


@lru_cache(maxsize=1)
def _bpx_field_index() -> dict[tuple[str, str], str]:
    """Map (block, lowercased BPX field name) -> canonical parameter key."""
    index: dict[tuple[str, str], str] = {}
    for key, entry in _parameters_data().get("parameters", {}).items():
        bpx = entry.get("bpx")
        if not isinstance(bpx, Mapping):
            continue
        for block in bpx:
            mapping = _bpx_mapping(entry, block)
            if mapping is not None:
                index[(block, mapping["field"].lower())] = key
    return index


def parameters_vocabulary() -> dict[str, Any]:
    """Return the curated parameter vocabulary + tier contracts, as a deep copy.

    Shape: ``{"version", "parameters": {"<key>": {"label", "scopes", "unit",
    "kind", "bpx"?, ...}}, "tiers": {"<tier>": {"description", "requires":
    {"<scope>": [keys]}}}}``. This is the machine-readable contract downstream
    surfaces vendor so every consumer applies identical completeness rules.
    """
    return copy.deepcopy(_parameters_data())


def parameter_keys() -> list[str]:
    """Sorted list of canonical parameter keys."""
    return sorted(_parameters_data().get("parameters", {}))


def parameter_entry(key: Any) -> dict[str, Any] | None:
    """Return the vocabulary entry for a parameter key/label (with its canonical key), or ``None``."""
    canonical = resolve_parameter(key)
    if canonical is None:
        return None
    entry = dict(_parameters_data()["parameters"][canonical])
    entry["key"] = canonical
    return entry


def resolve_parameter(value: Any) -> str | None:
    """Resolve a parameter key or label to its canonical key, or ``None``.

    Case-insensitive. Returns ``None`` for unknown values; callers decide
    whether that is an error (authoring UX) or fine (tolerant import).
    """
    if not isinstance(value, str) or not value.strip():
        return None
    return _parameter_alias_index().get(value.strip().lower())


def resolve_bpx_field(block: str, field_name: Any) -> str | None:
    """Resolve a BPX field name to its canonical parameter key, scoped by block.

    ``block`` is one of ``"cell"``, ``"electrode"``, ``"separator"``,
    ``"electrolyte"``, ``"state"`` (BPX 'Negative electrode'/'Positive
    electrode' both resolve through ``"electrode"``; a State field is named
    without its section). Block-scoped because BPX reuses field names across
    blocks with different physical meanings.
    """
    if not isinstance(field_name, str) or not field_name.strip():
        return None
    return _bpx_field_index().get((block, field_name.strip().lower()))


def bpx_field(key: Any, block: str) -> dict[str, str] | None:
    """Where a parameter lives in a BPX block: ``{"field", "unit", "section"?}``, or ``None``.

    ``unit`` is the unit BPX states the field in (the key's canonical unit
    unless the vocabulary names another); ``section`` is set for the State
    fields ("Initial conditions", "Thermal environment").
    """
    canonical = resolve_parameter(key)
    if canonical is None:
        return None
    return _bpx_mapping(_parameters_data()["parameters"][canonical], block)


def tier_keys() -> list[str]:
    """Model tiers in ascending-fidelity order, as declared in the vocabulary."""
    return list(_parameters_data().get("tiers", {}))


def tier_requirements(tier: str) -> dict[str, list[str]]:
    """Return ``{scope: [required parameter keys]}`` for a model tier.

    Raises ``ValueError`` for an unknown tier, listing the valid ones.
    """
    tiers = _parameters_data().get("tiers", {})
    if tier not in tiers:
        raise ValueError(f"unknown model tier {tier!r}; valid tiers: {', '.join(tiers)}")
    requires = tiers[tier].get("requires", {})
    return {scope: list(keys) for scope, keys in requires.items()}


def _claimed_keys(claims: Iterable[Any]) -> set[str]:
    """Canonical parameter keys present in *claims* (claim dicts or bare key strings)."""
    keys: set[str] = set()
    for claim in claims:
        raw = claim.get("parameter") if isinstance(claim, Mapping) else claim
        canonical = resolve_parameter(raw)
        if canonical is not None:
            keys.add(canonical)
    return keys


def completeness(claims: Iterable[Any], *, scope: str = "material") -> dict[str, dict[str, Any]]:
    """Which model tiers this scope's claims satisfy, and what is missing.

    ``claims`` is an iterable of claim dicts (``{"parameter": ...}``) or bare
    parameter-key strings. Returns ``{tier: {"satisfied": bool, "missing":
    [keys]}}`` for every tier that states requirements for *scope*; tiers with
    no requirements for the scope are omitted. Unknown parameter keys never
    count toward completeness.

    This is per-scope completeness ("can this material support SPM?"). Whether
    a whole cell can run a tier is :func:`cell_completeness`.
    """
    if scope not in PARAMETER_SCOPES:
        raise ValueError(f"unknown scope {scope!r}; valid scopes: {', '.join(PARAMETER_SCOPES)}")
    have = _claimed_keys(claims)
    result: dict[str, dict[str, Any]] = {}
    for tier, entry in _parameters_data().get("tiers", {}).items():
        required = entry.get("requires", {}).get(scope)
        if not required:
            continue
        missing = [key for key in required if key not in have]
        result[tier] = {"satisfied": not missing, "missing": missing}
    return result


def cell_completeness(claims_by_scope: Mapping[str, Iterable[Any]]) -> dict[str, dict[str, Any]]:
    """Whole-cell tier completeness across scopes.

    ``claims_by_scope`` maps scope names to claim iterables. Electrode-scope
    (and material-scope) requirements apply per electrode, so pass e.g.
    ``{"material_negative": [...], "material_positive": [...],
    "electrode_negative": [...], "electrode_positive": [...],
    "separator": [...], "electrolyte": [...]}`` — a plain ``"material"`` /
    ``"electrode"`` key is also accepted and treated as covering both sides.

    Returns ``{tier: {"satisfied": bool, "missing": {scope_key: [keys]}}}``
    for every declared tier.
    """
    have: dict[str, set[str]] = {}
    for scope_key, claims in claims_by_scope.items():
        have[scope_key] = _claimed_keys(claims)

    def _have_for(scope: str, side: str) -> set[str]:
        return have.get(f"{scope}_{side}", have.get(scope, set()))

    result: dict[str, dict[str, Any]] = {}
    for tier, entry in _parameters_data().get("tiers", {}).items():
        missing: dict[str, list[str]] = {}
        for scope, required in entry.get("requires", {}).items():
            if scope in ("material", "electrode"):
                for side in ("negative", "positive"):
                    got = _have_for(scope, side)
                    absent = [key for key in required if key not in got]
                    if absent:
                        missing[f"{scope}_{side}"] = absent
            else:
                got = have.get(scope, set())
                absent = [key for key in required if key not in got]
                if absent:
                    missing[scope] = absent
        result[tier] = {"satisfied": not missing, "missing": missing}
    return result


def parameter_set_claim_groups(body: Mapping[str, Any]) -> list[tuple[dict[str, Any], list[Any]]]:
    """A parameter-set body's claims as ``[(context, claims), ...]``.

    A claim batch is one group whose context is its target, scope and
    polarity. A parameter file gives one group per part, whose context is the
    part (and phase), the part's material target and the file's cell link, so
    its graphite claims collate with every other source's graphite claims.
    """
    parts = body.get("parts")
    if isinstance(parts, list):
        cell_link = {
            field: body[field]
            for field in ("cell_spec_id", "cell_instance_id", "virtual_cell")
            if body.get(field)
        }
        groups: list[tuple[dict[str, Any], list[Any]]] = []
        for part in parts:
            if not isinstance(part, Mapping) or not isinstance(part.get("claims"), list):
                continue
            context: dict[str, Any] = {"part": part.get("part"), **cell_link}
            for field in ("phase", "material_kind", "material_spec_id"):
                if part.get(field):
                    context[field] = part[field]
            groups.append((context, part["claims"]))
        return groups
    context = {"scope": body.get("scope")}
    for field in ("material_kind", "material_spec_id", "cell_spec_id", "electrode_polarity"):
        if body.get(field):
            context[field] = body[field]
    claims = body.get("claims")
    return [(context, claims)] if isinstance(claims, list) else []


def collate_claims(
    records: Iterable[Mapping[str, Any]],
    *,
    material_kind: str | None = None,
    material_spec_id: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Fold parameter-set records into ``{parameter: [claim, ...]}``.

    Each returned claim is a copy of the stored claim dict with the source
    context attached under ``"source"``: the parameter-set id/name, its target
    (material_kind / material_spec_id / cell_spec_id), scope, and the
    record-level citation (claim-level ``citation``/``citation_doi`` override
    it when present). A parameter file's claims carry their part instead of a
    scope, with the part's material target and the file's cell link
    (:func:`parameter_set_claim_groups`). Unknown parameter keys are kept
    verbatim — collation is for reading what sources say, and tolerant import
    means unknown keys may carry real values.

    ``material_kind`` (a kind key or alias) and ``material_spec_id`` keep
    only the claims about that material: a claim batch with that target, and
    the matching material part of a parameter file. Without them every claim
    of every record comes back, including a BPX file's cell, electrode and
    other-electrode claims. A search by material therefore passes the same
    filter on::

        rows = query_parameter_sets(material_kind="graphite", parameter="particle_radius")
        claims = collate_claims([row["record"] for row in rows], material_kind="graphite")

    The spread across sources per parameter is the point: callers decide how
    to select (curated slate, newest, conditions filter) — this function never
    picks a winner.
    """
    kind_filter: str | None = None
    if material_kind is not None:
        from battinfo.materials import resolve_material_kind  # noqa: PLC0415

        kind_filter = resolve_material_kind(material_kind) or material_kind
    collated: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        body = record.get("parameter_set")
        if not isinstance(body, Mapping):
            continue
        provenance_raw = record.get("provenance")
        provenance: Mapping[str, Any] = provenance_raw if isinstance(provenance_raw, Mapping) else {}
        record_source: dict[str, Any] = {
            "parameter_set_id": body.get("id"),
            "name": body.get("name"),
        }
        for citation_field in ("citation", "citation_doi"):
            if provenance.get(citation_field):
                record_source[citation_field] = provenance[citation_field]
        for context, claims in parameter_set_claim_groups(body):
            if kind_filter is not None and context.get("material_kind") != kind_filter:
                continue
            if material_spec_id is not None and context.get("material_spec_id") != material_spec_id:
                continue
            source = {**record_source, **context}
            for claim in claims:
                if not isinstance(claim, Mapping) or not claim.get("parameter"):
                    continue
                key = resolve_parameter(claim["parameter"]) or str(claim["parameter"])
                entry = dict(claim)
                claim_source = dict(source)
                for citation_field in ("citation", "citation_doi"):
                    if claim.get(citation_field):
                        claim_source[citation_field] = claim[citation_field]
                entry["source"] = claim_source
                collated.setdefault(key, []).append(entry)
    return collated
