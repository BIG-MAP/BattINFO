from __future__ import annotations

import copy
import json
import warnings
from collections import ChainMap
from collections.abc import Mapping
from functools import lru_cache
from importlib import resources
from typing import Any, NamedTuple
from urllib.request import Request, urlopen

from battinfo.validate.core import (
    DEFAULT_POLICY,
    ValidationIssue,
    ValidationPolicy,
    ValidationReport,
    ValidationResult,
    get_validation_policy,
)


@lru_cache(maxsize=1)
def _pyld_module() -> Any:
    """Return the ``pyld.jsonld`` module, or ``None`` if pyld is not installed.

    Imported lazily (pyld drags in ``requests``, ~0.4 s) so that
    ``import battinfo`` stays fast; the cost is paid on first validation."""
    try:
        from pyld import jsonld as pyld_jsonld  # noqa: PLC0415
    except ImportError:  # pragma: no cover - exercised only when the dependency is missing at runtime.
        return None
    return pyld_jsonld


# Canonical URL for the EMMO domain-battery JSON-LD context.  A bundled copy lives at
# src/battinfo/data/context/domain-battery.context.json and is served as a local
# fallback so that JSON-LD processing works without network access.  Run
# .tools/quality/refresh_emmo_context.py to update the bundled copy.
_EMMO_BATTERY_CONTEXT_URL = "https://w3id.org/emmo/domain/battery/context"
_BATTINFO_RECORDS_CONTEXT_URL = "https://w3id.org/battinfo/context/records/v1.json"

# Remote JSON-LD context URLs whose documents are bundled with the package, so
# that validation, URDNA2015 normalization, and RDF materialization run fully
# offline (no live network at publish/validate time). Refresh the bundled copies
# via .tools/quality/refresh_emmo_context.py.
_LOCAL_CONTEXT_FILES = {
    _EMMO_BATTERY_CONTEXT_URL: "domain-battery.context.json",
    # The hosted records context is the COMPLETE, versioned superset (generated
    # by scripts/gen_context.py), so a document that references the URL resolves
    # every record @type/property offline.
    _BATTINFO_RECORDS_CONTEXT_URL: "records.context.v1.json",
}


def _load_mapping_json(*parts: str) -> dict[str, Any]:
    path = resources.files("battinfo")
    for part in ("data", "mappings", "domain-battery", *parts):
        path = path.joinpath(part)  # single-arg joinpath: multi-arg is Python 3.11+
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _is_absolute_or_compact_iri(value: str) -> bool:
    return "://" in value or ":" in value


def _context_class_terms(context: dict[str, Any]) -> set[str]:
    """The terms of a JSON-LD context that name a class.

    A context entry does not say whether its IRI is a class or a property, so
    this goes by the naming convention the vocabularies share, the same one
    scripts/gen_battinfo_vocab.py applies: class terms are UpperCamelCase
    (``Case``, ``CoinCell``, ``Dataset``), while properties, record keys and
    prefixes start lower-case. A class term binds a plain IRI, or a definition
    holding nothing but an ``@id``.
    """
    terms: set[str] = set()
    for term, value in context.items():
        if not term[:1].isupper():
            continue
        if isinstance(value, dict):
            if set(value) != {"@id"}:
                continue
            value = value["@id"]
        if isinstance(value, str) and value:
            terms.add(term)
    return terms


def _expand_compact_iri(value: str, context: Mapping[str, Any]) -> str:
    """``value`` with its prefix expanded by ``context`` (``emmo:Volt`` -> full IRI)."""
    prefix, sep, local = value.partition(":")
    base = context.get(prefix) if sep and not local.startswith("//") else None
    if isinstance(base, str) and base.endswith(("#", "/")):
        return base + local
    return value


def _context_unit_terms(context: dict[str, Any]) -> set[str]:
    """The terms of a JSON-LD context bound to a measurement unit.

    A unit is any IRI in the curated or candidate unit map, or bound to one of
    the unit symbols the records context defines
    (:data:`battinfo.jsonld.CONTEXT_UNIT_SYMBOLS`): ``V``, ``Volt``, ``MWh``,
    ``UnitOne`` and the like.
    """
    from battinfo.jsonld import CONTEXT_UNIT_SYMBOLS  # noqa: PLC0415

    # Compact IRIs expand with the context's own prefixes first, then with the
    # bundled v1 prefixes, so a context that binds full IRIs and declares no
    # ``emmo`` prefix (the EMMO domain-battery context) is read the same way.
    records = _local_context_document(_LOCAL_CONTEXT_FILES[_BATTINFO_RECORDS_CONTEXT_URL]).get("@context", {})
    prefixes = ChainMap(context, records)
    unit_iris = {_expand_compact_iri(iri, prefixes) for iri in CONTEXT_UNIT_SYMBOLS.values()}
    for filename in ("unit_map.curated.json", "unit_map.candidates.json"):
        for item in _load_mapping_json(filename).get("mappings", []):
            iri = item.get("unit_iri")
            if isinstance(iri, str) and iri:
                unit_iris.add(_expand_compact_iri(iri, prefixes))
    terms: set[str] = set()
    for term, value in context.items():
        iri = value.get("@id") if isinstance(value, dict) else value
        if isinstance(iri, str) and _expand_compact_iri(iri, prefixes) in unit_iris:
            terms.add(term)
    return terms


# -- The @type check ----------------------------------------------------------
#
# A bare @type token expands through the context in force at its node. A token
# that context does not define expands relative to wherever the document is read
# (file:///.../coin), so each node is judged against its own active context: the
# bundled copy of a known context URL, an inline object, a nested or
# property-scoped context, and @context null, applied in order as a JSON-LD
# processor applies them. A chain of local contexts is keyed by a tuple of their
# canonical forms, so each distinct chain is processed once.

_ContextKey = tuple[str, ...]


def _context_key_part(local: Any) -> str:
    """One local context (a URL, an object, a list or null) in a hashable form."""
    if isinstance(local, str):
        return "url:" + local
    return "json:" + json.dumps(local, sort_keys=True, ensure_ascii=False, default=str)


def _context_from_key_part(part: str) -> Any:
    return part[4:] if part.startswith("url:") else json.loads(part[5:])


def _remote_context(url: str) -> Any:
    """The ``@context`` value of the context document at ``url``.

    Known URLs resolve to their bundled copies; any other URL goes through the
    loader the URDNA2015 step uses. None when the document cannot be loaded or
    holds no context; that step then reports the failure as an error.
    """
    document: Any = _resolve_local_context(url)
    if document is None:
        try:
            document = _pyld_document_loader(url, {}).get("document")
        except Exception:  # noqa: BLE001 - reported by the URDNA2015 step
            return None
        if isinstance(document, str):
            try:
                document = json.loads(document)
            except ValueError:
                return None
    if not isinstance(document, dict) or "@context" not in document:
        return None
    return document["@context"]


def _merge_local_context(
    terms: dict[str, Any], vocab: str | None, local: Any, loading: frozenset[str]
) -> tuple[dict[str, Any], str | None] | None:
    """The term definitions and ``@vocab`` after applying ``local``.

    Returns None when ``local`` holds a context that cannot be loaded or is
    not a context at all. ``terms`` is never changed in place.
    """
    if local is None:
        return {}, None
    if isinstance(local, list):
        for item in local:
            merged = _merge_local_context(terms, vocab, item, loading)
            if merged is None:
                return None
            terms, vocab = merged
        return terms, vocab
    if isinstance(local, str):
        remote = _remote_context(local) if local not in loading else None
        if remote is None:
            return None
        return _merge_local_context(terms, vocab, remote, loading | {local})
    if not isinstance(local, dict):
        return None
    terms = dict(terms)
    for term, value in local.items():
        if term == "@vocab":
            vocab = value if isinstance(value, str) and _is_absolute_or_compact_iri(value) else None
        elif term.startswith("@"):
            continue
        elif value is None or (isinstance(value, dict) and "@id" in value and value["@id"] is None):
            terms.pop(term, None)
        else:
            terms[term] = value
    return terms, vocab


@lru_cache(maxsize=64)
def _active_context(key: _ContextKey) -> tuple[dict[str, Any], str | None] | None:
    """The term definitions and ``@vocab`` after the local contexts ``key``
    names, in order; None when one of them cannot be loaded. The result is
    shared, so callers never change it."""
    if not key:
        return {}, None
    local = _context_from_key_part(key[-1])
    first = local[0] if isinstance(local, list) and local else local
    # @context null starts again from the empty context, whatever came before.
    parent = ({}, None) if first is None else _active_context(key[:-1])
    if parent is None:
        return None
    return _merge_local_context(parent[0], parent[1], local, frozenset())


class _TypeView(NamedTuple):
    """What the @type check needs to know about one active context."""

    defined: frozenset[str]
    classes: frozenset[str]
    vocab: str | None
    type_aliases: frozenset[str]
    scoped: dict[str, Any]


@lru_cache(maxsize=64)
def _type_view(key: _ContextKey) -> _TypeView | None:
    active = _active_context(key)
    if active is None:
        return None
    terms, vocab = active
    aliases = frozenset(
        term
        for term, value in terms.items()
        if value == "@type" or (isinstance(value, dict) and value.get("@id") == "@type")
    )
    scoped = {
        term: value["@context"] for term, value in terms.items() if isinstance(value, dict) and "@context" in value
    }
    return _TypeView(
        defined=frozenset(terms),
        classes=frozenset(_context_class_terms(terms) - _context_unit_terms(terms)),
        vocab=vocab,
        type_aliases=aliases,
        scoped=scoped,
    )


_RECORDS_CONTEXT_KEY: _ContextKey = (_context_key_part(_BATTINFO_RECORDS_CONTEXT_URL),)


def _allowed_type_terms() -> frozenset[str]:
    """The bare @type tokens a document whose ``@context`` is the hosted v1 URL
    may use: every class term of the bundled v1 context, less its unit terms.

    A document with another context is judged against that context instead
    (see :func:`type_term_issues`).
    """
    view = _type_view(_RECORDS_CONTEXT_KEY)
    return view.classes if view is not None else frozenset()


def _walk_relative_type_errors(node: Any, path: str, errors: list[str], key: _ContextKey = ()) -> None:
    if isinstance(node, list):
        for idx, item in enumerate(node):
            next_path = f"{path}[{idx}]" if path else f"[{idx}]"
            _walk_relative_type_errors(item, next_path, errors, key)
        return
    if not isinstance(node, dict):
        return
    if "@context" in node:
        key = (*key, _context_key_part(node["@context"]))
    # None: a context in force here could not be loaded, so the check cannot
    # judge this node's types; the URDNA2015 step reports that context.
    view = _type_view(key)
    for name, value in node.items():
        if name == "@context":
            continue
        next_path = f"{path}.{name}" if path else name
        if name == "@type" or (view is not None and name in view.type_aliases):
            if view is not None:
                _check_type_values(value, next_path, view, errors)
            continue
        child_key = key
        if view is not None and name in view.scoped:
            child_key = (*key, _context_key_part(view.scoped[name]))
        _walk_relative_type_errors(value, next_path, errors, child_key)


def _check_type_values(value: Any, path: str, view: _TypeView, errors: list[str]) -> None:
    values = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    for idx, item in enumerate(values):
        if not isinstance(item, str) or item.startswith("@") or _is_absolute_or_compact_iri(item):
            continue
        if item in view.classes:
            continue
        if view.vocab is not None and item not in view.defined:
            continue  # expands through @vocab to an absolute IRI
        item_path = path if isinstance(value, str) else f"{path}[{idx}]"
        errors.append(f"{item_path}: relative @type reference '{item}' is not a class the document's @context defines")


def type_term_issues(data: Any) -> list[ValidationIssue]:
    """A ``jsonld.type_term_unknown`` error for every bare @type in ``data``
    that the context in force at its node does not define as a class.

    Prefixed and absolute IRIs and keywords are not judged. A unit term (``V``,
    ``Volt``) is never a node's type, so it is reported too. Types under a
    context that cannot be loaded are left to the URDNA2015 step, which
    reports the context. ``record_to_jsonld`` raises on any of these, and
    :func:`validate_jsonld_report` reports them as errors under every policy.
    """
    errors: list[str] = []
    _walk_relative_type_errors(data, "", errors)
    issues: list[ValidationIssue] = []
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
    return issues


def _is_bare_relative_id(value: str) -> bool:
    """True if this ``@id`` is a bare token that silently resolves to a machine-local IRI.

    A usable ``@id`` is an absolute IRI carrying a scheme (``http:``, ``urn:``, …), a compact
    CURIE (``prefix:local``), or a blank-node label (``_:b0``). A bare token with none of these —
    e.g. ``c1`` or an unmapped unit symbol — has no scheme and no CURIE colon, so rdflib resolves
    it against the document base (the current working directory on export), silently producing
    ``file:///…/token`` and leaking the authoring machine's filesystem into the record. (Explicit
    ``file:`` IRIs are left alone: the offline DCAT bundle links its sibling data files that way
    by design.)
    """
    if not value or value.startswith(("_:", "@")):
        return False  # blank node / JSON-LD keyword — not a resolvable IRI
    return ":" not in value


def _walk_relative_id_errors(node: Any, path: str, errors: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            next_path = f"{path}.{key}" if path else key
            if key == "@context":
                continue
            if key == "@id":
                if isinstance(value, str) and _is_bare_relative_id(value):
                    errors.append(
                        f"{next_path}: bare @id '{value}' has no scheme or CURIE prefix and "
                        "would export to a cwd-relative file:// IRI"
                    )
                continue
            _walk_relative_id_errors(value, next_path, errors)
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            next_path = f"{path}[{idx}]" if path else f"[{idx}]"
            _walk_relative_id_errors(item, next_path, errors)


def _parse_materialization_issues(data: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    # rdflib 7.x emits DeprecationWarning for internal APIs (Dataset.default_context,
    # Dataset.contexts, ConjunctiveGraph) used by its own JSON-LD parser and nquads
    # serializer.  These are rdflib-internal calls, not our code; suppress them so
    # they don't surface as false parse errors when callers run with -W error.
    from rdflib import Dataset  # noqa: PLC0415 - deferred so `import battinfo` stays fast

    try:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=DeprecationWarning, module="rdflib")
            dataset = Dataset()
            # Inline bundled contexts so rdflib never fetches them over the network.
            dataset.parse(data=json.dumps(_inline_local_contexts(data)), format="json-ld")
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
    pyld_jsonld = _pyld_module()
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


def _normalize_context_url(url: str) -> str:
    # Records sometimes carry a trailing slash or stray '.'; normalize for lookup.
    return url.strip().rstrip("/.")


@lru_cache(maxsize=8)
def _local_context_document(filename: str) -> dict[str, Any]:
    path = resources.files("battinfo").joinpath("data").joinpath("context").joinpath(filename)
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _resolve_local_context(url: str) -> dict[str, Any] | None:
    """Return the bundled context document for a known remote URL, else None."""
    key = _normalize_context_url(url)
    for known_url, filename in _LOCAL_CONTEXT_FILES.items():
        if key == _normalize_context_url(known_url):
            return _local_context_document(filename)
    return None


def _pyld_document_loader(url: str, options: dict[str, Any]) -> dict[str, Any]:
    # Serve bundled contexts from local files so URDNA2015 normalization is
    # reproducible and works offline.  Bundled records never reference contexts
    # outside _LOCAL_CONTEXT_FILES, so the network fallback below is not taken
    # during normal publication/validation.
    local = _resolve_local_context(url)
    if local is not None:
        return {"contextUrl": None, "documentUrl": url, "document": local}
    return copy.deepcopy(_cached_pyld_document(url))


def _inline_context_value(value: Any) -> Any:
    """Replace any known remote @context URL with its bundled context object."""
    if isinstance(value, str):
        local = _resolve_local_context(value)
        if local is not None:
            return local.get("@context", local)
        return value
    if isinstance(value, list):
        return [_inline_context_value(item) for item in value]
    return value


def _inline_local_contexts(node: Any) -> Any:
    """Deep-copy ``node`` with every known remote @context URL replaced by its
    bundled context object.  rdflib's JSON-LD parser resolves contexts through its
    own loader (it does not honour PyLD's documentLoader), so inlining the bundled
    contexts is what lets RDF materialization run without a live network."""
    if isinstance(node, dict):
        return {
            key: (_inline_context_value(value) if key == "@context" else _inline_local_contexts(value))
            for key, value in node.items()
        }
    if isinstance(node, list):
        return [_inline_local_contexts(item) for item in node]
    return node


def _urdna2015_issues(data: dict[str, Any]) -> list[ValidationIssue]:
    pyld_jsonld = _pyld_module()
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
    # An undefined @type is an error under every policy: the RDF it gives
    # carries a machine-local IRI, whatever stage the document is at.
    issues = type_term_issues(data)
    # @id portability is enforced only for publication: mid-pipeline authoring and staging forms
    # legitimately carry local ids and file:// staging links that are rewritten to their final
    # w3id/Zenodo IRIs before a record is published. At publish time (publisher policy) any such
    # value that survived is a real leak — a cwd-relative or file:// IRI in the released RDF.
    id_errors: list[str] = []
    if resolved_policy.name == "publisher":
        _walk_relative_id_errors(data, "", id_errors)
    for rendered in id_errors:
        path, _, message = rendered.partition(": ")
        issues.append(
            ValidationIssue(
                code="jsonld.id_not_portable",
                severity="error",
                path=path if _ else "",
                message=message if _ else rendered,
                validator="@id",
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
