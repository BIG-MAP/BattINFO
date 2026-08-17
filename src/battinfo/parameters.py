"""Parameter vocabulary, model-tier completeness, and claim collation.

Parameters live as *claims* inside ``parameter-set`` records: one record = one
source (paper, BPX file, lab fit) making claims about one target (a material
kind, a material spec, or a cell spec). Many records may claim values for the
same parameter of the same material — the spread across sources is data, not a
conflict. This module is the shared contract on top of those records:

- the curated parameter vocabulary (``data/vocab/parameters.json``): canonical
  snake_case keys, physical scopes, canonical units, BPX source fields;
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

PARAMETER_SCOPES: tuple[str, ...] = ("material", "electrode", "separator", "electrolyte", "cell")


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


@lru_cache(maxsize=1)
def _bpx_field_index() -> dict[tuple[str, str], str]:
    """Map (block, lowercased BPX field name) -> canonical parameter key."""
    index: dict[tuple[str, str], str] = {}
    for key, entry in _parameters_data().get("parameters", {}).items():
        bpx = entry.get("bpx")
        if not isinstance(bpx, Mapping):
            continue
        for block, field_name in bpx.items():
            if isinstance(field_name, str) and field_name.strip():
                index[(block, field_name.strip().lower())] = key
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

    ``block`` is one of ``"electrode"``, ``"separator"``, ``"electrolyte"``
    (BPX 'Negative electrode'/'Positive electrode' both resolve through
    ``"electrode"``). Block-scoped because BPX reuses field names across blocks
    with different physical meanings.
    """
    if not isinstance(field_name, str) or not field_name.strip():
        return None
    return _bpx_field_index().get((block, field_name.strip().lower()))


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


def collate_claims(records: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Fold parameter-set records into ``{parameter: [claim, ...]}``.

    Each returned claim is a copy of the stored claim dict with the source
    context attached under ``"source"``: the parameter-set id/name, its target
    (material_kind / material_spec_id / cell_spec_id), scope, and the
    record-level citation (claim-level ``citation``/``citation_doi`` override
    it when present). Unknown parameter keys are kept verbatim — collation is
    for reading what sources say, and tolerant import means unknown keys may
    carry real values.

    The spread across sources per parameter is the point: callers decide how
    to select (curated slate, newest, conditions filter) — this function never
    picks a winner.
    """
    collated: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        body = record.get("parameter_set")
        if not isinstance(body, Mapping):
            continue
        provenance_raw = record.get("provenance")
        provenance: Mapping[str, Any] = provenance_raw if isinstance(provenance_raw, Mapping) else {}
        source: dict[str, Any] = {
            "parameter_set_id": body.get("id"),
            "name": body.get("name"),
            "scope": body.get("scope"),
        }
        for target_field in ("material_kind", "material_spec_id", "cell_spec_id"):
            if body.get(target_field):
                source[target_field] = body[target_field]
        for citation_field in ("citation", "citation_doi"):
            if provenance.get(citation_field):
                source[citation_field] = provenance[citation_field]
        if body.get("electrode_polarity"):
            source["electrode_polarity"] = body["electrode_polarity"]
        claims = body.get("claims")
        if not isinstance(claims, list):
            continue
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
