"""Record IRIs under ``https://w3id.org/battinfo/``: building them and reading them back.

The IRI ruling of 22 October 2026 (BIG-MAP/BattINFO#476) gives a record IRI
one of two shapes:

- the old form, ``https://w3id.org/battinfo/{segment}/{uid}``, which every
  record minted before the switch has and keeps for good;
- the prefixed form, ``https://w3id.org/battinfo/id/{prefix}/{segment}/{uid}``,
  where the prefix is the number of the publisher that minted it, four or
  more digits.

A curated shared thing (a product model, a material, a maker) is
``https://w3id.org/battinfo/id/{uid}``, and only the registry mints one. The
old form and the ``/id/1001/`` form of one segment and uid are one record;
under any other prefix the same uid names another record.

This module is the one place that builds and recognises these shapes::

    from battinfo.namespace import base_prefix, parse_record_iri, record_iri, same_record

    record_iri("cell", "b6yn-0sxe-t2qk-9mjv")
    # 'https://w3id.org/battinfo/cell/b6yn-0sxe-t2qk-9mjv'
    record_iri("cell", "b6yn-0sxe-t2qk-9mjv", prefix="1001")
    # 'https://w3id.org/battinfo/id/1001/cell/b6yn-0sxe-t2qk-9mjv'
    base_prefix("https://w3id.org/battinfo/id/1001/")
    # '1001'
    parse_record_iri("https://w3id.org/battinfo/id/1001/cell/b6yn-0sxe-t2qk-9mjv")
    # RecordIri(prefix='1001', segment='cell', uid='b6yn-0sxe-t2qk-9mjv')
    same_record(
        "https://w3id.org/battinfo/cell/b6yn-0sxe-t2qk-9mjv",
        "https://w3id.org/battinfo/id/1001/cell/b6yn-0sxe-t2qk-9mjv",
    )
    # True

A record mints under the base of its container (ruling decision 5). A
workspace or a batch folder records its base when it is created, and new
ones record :data:`DEFAULT_RECORD_BASE`, ``https://w3id.org/battinfo/id/1001/``;
one with no base recorded was created before the switch and keeps the old
form, :data:`OLD_FORM_BASE`, for good. A path without a container, such as a
``save_*`` or ``create_*`` function, takes a ``base=`` argument that defaults
to :data:`DEFAULT_RECORD_BASE`. :func:`base_prefix` reads a base back as the
prefix :func:`record_iri` takes. A uid never depends on the base: a seed takes
a parent's IRI in the old form (``entities.seed_iri``).

Every recogniser accepts both shapes (``both_shapes=True``), as the v1 JSON
Schemas do, and a field that references a maker, a product model or a
material also accepts a shared thing (``things=True``). The IRI patterns of
the schemas are built here too: ``scripts/sync_schema_iri_patterns.py``
writes them.

The publisher prefixes come from the register in
``data/namespace/prefixes.json`` (:data:`PUBLISHER_PREFIXES`), and the
segments that are never record segments from
``data/namespace/reserved-segments.json``
(``entities.RESERVED_NAMESPACE_SEGMENTS``).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from types import MappingProxyType
from typing import Any, NamedTuple

from battinfo.entities import RESERVED_NAMESPACE_SEGMENTS, UID_DASHED_RE, _namespace_file

__all__ = [
    "BATTERY_GENOME_PREFIX",
    "BATTINFO_PREFIX",
    "BATTINFO_ROOT",
    "CONTEXT_BASE",
    "DEFAULT_RECORD_BASE",
    "ID_BASE",
    "OLD_FORM_BASE",
    "PREFIX_PATTERN",
    "PUBLISHER_PREFIXES",
    "PublisherPrefix",
    "RecordIri",
    "SCHEMA_BASE",
    "SEGMENT_PATTERN",
    "UID_PATTERN",
    "VOCABULARY_NAMESPACE",
    "base_prefix",
    "parse_record_iri",
    "parse_thing_iri",
    "publisher_prefix",
    "record_base",
    "record_iri",
    "record_iri_pattern",
    "record_iri_regex",
    "same_record",
]

#: The root of the battinfo w3id name. The ontology, the record-layer
#: vocabulary terms and every record IRI of the old form sit right under it.
BATTINFO_ROOT = "https://w3id.org/battinfo/"
#: The record-layer vocabulary namespace (``battinfo:`` in the records
#: context). It is the root itself, named apart so that code which means the
#: vocabulary says so; it never changes with the record shapes.
VOCABULARY_NAMESPACE = BATTINFO_ROOT
#: Where the JSON-LD contexts are published (``context/records/v1.json``).
CONTEXT_BASE = BATTINFO_ROOT + "context/"
#: Where the JSON Schemas are published (``schema/cell-spec.schema.json``).
SCHEMA_BASE = BATTINFO_ROOT + "schema/"
#: The branch that holds records of the prefixed form and shared things.
ID_BASE = BATTINFO_ROOT + "id/"

#: A uid: the grammar of ``entities.UID_DASHED_RE``, without its anchors.
UID_PATTERN = UID_DASHED_RE.pattern.removeprefix("^").removesuffix("$")
#: A record segment such as ``spec``, ``cell`` or ``current-collector``.
SEGMENT_PATTERN = r"[a-z][a-z0-9-]*"
#: A publisher prefix: a number of four or more digits, never a name.
PREFIX_PATTERN = r"[1-9][0-9]{3,}"


class PublisherPrefix(NamedTuple):
    """One entry of the publisher prefix register (``data/namespace/prefixes.json``).

    *records* is false for a prefix that holds definitions only, and
    *resolver* is ``None`` when the BattINFO registry dispatches the
    publisher's addresses rather than a resolver of its own. *landing* is
    the host of the publisher's own record pages, or ``None``: a browser that
    opens one of its record IRIs is sent to the record's page only when that
    page is on this host.
    """

    prefix: str
    holder: str
    records: bool
    resolver: str | None
    landing: str | None
    allocated: date


_REGISTER_PREFIX_RE = re.compile(r"[1-9][0-9]{3}")
_FIRST_PREFIX = 1000


def _register_entry(entry: Any) -> PublisherPrefix:
    if not isinstance(entry, Mapping) or set(entry) != set(PublisherPrefix._fields):
        raise ValueError(f"a prefix register entry has the fields {', '.join(PublisherPrefix._fields)}: {entry!r}")
    prefix, holder, records, resolver = entry["prefix"], entry["holder"], entry["records"], entry["resolver"]
    landing = entry["landing"]
    if not isinstance(prefix, str) or not _REGISTER_PREFIX_RE.fullmatch(prefix):
        raise ValueError(f"register prefix {prefix!r} is not a four-digit number")
    if not isinstance(holder, str) or not holder.strip() or not isinstance(records, bool):
        raise ValueError(f"register prefix {prefix} needs a holder and a true or false records")
    if resolver is not None and not (isinstance(resolver, str) and resolver.startswith("https://")):
        raise ValueError(f"register prefix {prefix} has a resolver that is not an https URL: {resolver!r}")
    if landing is not None and not (
        isinstance(landing, str) and landing.startswith("https://") and landing.endswith("/")
    ):
        raise ValueError(
            f"register prefix {prefix} has a landing host that is not an https URL ending in /: {landing!r}"
        )
    allocated = entry["allocated"]
    if not isinstance(allocated, str):
        raise ValueError(f"register prefix {prefix} needs its allocation date as YYYY-MM-DD: {allocated!r}")
    return PublisherPrefix(prefix, holder, records, resolver, landing, date.fromisoformat(allocated))


def _load_prefix_register(document: Any) -> Mapping[str, PublisherPrefix]:
    """The register in *document*, keyed by prefix, checked to be numbered in sequence from 1000."""
    entries = [_register_entry(entry) for entry in document["prefixes"]]
    expected = [str(number) for number in range(_FIRST_PREFIX, _FIRST_PREFIX + len(entries))]
    if [entry.prefix for entry in entries] != expected:
        raise ValueError(
            f"the prefix register must number its entries in sequence from {_FIRST_PREFIX}, "
            f"with no gap or repeat: {[entry.prefix for entry in entries]}"
        )
    return MappingProxyType({entry.prefix: entry for entry in entries})


#: The publisher prefix register (ruling decision 3), keyed by prefix, in the
#: order the numbers were given out.
PUBLISHER_PREFIXES: Mapping[str, PublisherPrefix] = _load_prefix_register(_namespace_file("prefixes.json"))


def publisher_prefix(prefix: str) -> PublisherPrefix | None:
    """The register entry of *prefix*, or ``None`` for a number nobody holds."""
    return PUBLISHER_PREFIXES.get(prefix)


#: BattINFO itself. It holds definitions only (``def/1000/``), never records.
BATTINFO_PREFIX = "1000"
#: The Battery Genome registry, and the SDK's own prefix.
BATTERY_GENOME_PREFIX = "1001"
# A holder's name may change in the register; its number never does.
if BATTINFO_PREFIX not in PUBLISHER_PREFIXES or PUBLISHER_PREFIXES[BATTINFO_PREFIX].records:
    raise ValueError(f"the prefix register must hold {BATTINFO_PREFIX} for definitions only")
if BATTERY_GENOME_PREFIX not in PUBLISHER_PREFIXES or not PUBLISHER_PREFIXES[BATTERY_GENOME_PREFIX].records:
    raise ValueError(f"the prefix register must hold {BATTERY_GENOME_PREFIX} for records")
# Prefixes that hold definitions only: no record is minted under them.
_DEFINITIONS_ONLY_PREFIXES = frozenset(entry.prefix for entry in PUBLISHER_PREFIXES.values() if not entry.records)
# The prefix an IRI of the old form counts as when two IRIs are compared. The
# old form and the ``/id/1001/`` form of one segment and uid are one record
# (ruling decision 5); under any other prefix the same uid is another record
# (decision 3).
_OLD_FORM_PREFIX = BATTERY_GENOME_PREFIX

# The segments that are never record segments, id and def among them: id/
# holds records of the prefixed form and shared things, def/ publishers'
# definitions, which nothing here mints. So
# ``https://w3id.org/battinfo/id/{uid}`` is a shared thing, not a record.
_RESERVED_SEGMENTS = RESERVED_NAMESPACE_SEGMENTS
_ROOT_PATTERN = re.escape(BATTINFO_ROOT)
_SEGMENT_RE = re.compile(SEGMENT_PATTERN)
_UID_RE = re.compile(UID_PATTERN)
_PREFIX_RE = re.compile(PREFIX_PATTERN)
_RECORD_IRI_RE = re.compile(
    rf"{_ROOT_PATTERN}(?:id/(?P<prefix>{PREFIX_PATTERN})/)?(?P<segment>{SEGMENT_PATTERN})/(?P<uid>{UID_PATTERN})"
)
_THING_IRI_RE = re.compile(rf"{re.escape(ID_BASE)}(?P<uid>{UID_PATTERN})")


class RecordIri(NamedTuple):
    """A record IRI taken apart: *prefix* is ``None`` for the old form."""

    prefix: str | None
    segment: str
    uid: str


def _checked_segment(segment: str) -> str:
    if not isinstance(segment, str) or not _SEGMENT_RE.fullmatch(segment) or segment in _RESERVED_SEGMENTS:
        raise ValueError(
            f"{segment!r} is not a record segment: a segment is a lower-case word such as spec, cell or "
            "current-collector, and never a reserved segment such as id, def or context."
        )
    return segment


def _checked_prefix(prefix: str) -> str:
    if not isinstance(prefix, str) or not _PREFIX_RE.fullmatch(prefix):
        raise ValueError(f"{prefix!r} is not a publisher prefix: a prefix is a number of four or more digits.")
    if prefix in _DEFINITIONS_ONLY_PREFIXES:
        raise ValueError(f"Prefix {prefix} holds definitions only; no record is minted under it.")
    return prefix


def record_base(prefix: str | None = None) -> str:
    """The base a record IRI is minted under: the root for the old form, ``.../id/{prefix}/`` with *prefix*.

    Raises ``ValueError`` for a prefix that is not four or more digits or that
    holds definitions only (1000, BattINFO's own).
    """
    return BATTINFO_ROOT if prefix is None else f"{ID_BASE}{_checked_prefix(prefix)}/"


#: The base of the old form, the root. Every record minted before the switch
#: has it, and so does every record that a workspace or batch folder with no
#: base recorded mints, for good.
OLD_FORM_BASE = BATTINFO_ROOT
#: The base new records mint under: Battery Genome's, ``https://w3id.org/battinfo/id/1001/``.
#: New workspaces and batch folders record it when they are created, and the
#: paths without a container take it unless they are given another.
DEFAULT_RECORD_BASE = record_base(BATTERY_GENOME_PREFIX)


def base_prefix(base: str) -> str | None:
    """The prefix :func:`record_iri` takes for *base*: ``None`` for :data:`OLD_FORM_BASE`, else ``{prefix}``.

    *base* is a record base as a container records it and as ``base=``
    arguments take it: ``https://w3id.org/battinfo/`` for the old form or
    ``https://w3id.org/battinfo/id/{prefix}/``. Raises ``ValueError`` for
    anything else, a prefix that holds definitions only (1000) included.
    """
    if base == OLD_FORM_BASE:
        return None
    if isinstance(base, str) and base.startswith(ID_BASE) and base.endswith("/"):
        prefix = base[len(ID_BASE) : -1]
        if _PREFIX_RE.fullmatch(prefix):
            return _checked_prefix(prefix)
    raise ValueError(
        f"{base!r} is not a record base: a base is {OLD_FORM_BASE} for the old form or "
        f"{ID_BASE}{{prefix}}/ with a publisher prefix of four or more digits, such as {DEFAULT_RECORD_BASE}."
    )


def record_iri(segment: str, uid: str, prefix: str | None = None) -> str:
    """The IRI of the record *uid* under *segment*: the old form without *prefix*, else the prefixed form.

    The one builder of record IRIs. Raises ``ValueError`` for a segment, uid or
    prefix that is not well formed, and for a prefix that holds definitions
    only. A uid never depends on the base, so the two forms of one record
    differ in the base alone.
    """
    if not isinstance(uid, str) or not _UID_RE.fullmatch(uid):
        raise ValueError(
            f"{uid!r} is not a record uid: four groups of four characters (digits, and lower-case letters "
            "other than i, l, o and u) joined by dashes, such as pge5-wer6-2q82-v9k0."
        )
    return f"{record_base(prefix)}{_checked_segment(segment)}/{uid}"


def parse_record_iri(value: object) -> RecordIri | None:
    """*value* taken apart as a record IRI of either form, or ``None`` when it is not one.

    The whole string has to be the IRI: no trailing slash, query or fragment.
    Any prefix of four or more digits parses, an allocated one or not, 1000
    included; whether a publisher holds it is the registry's question.
    """
    if not isinstance(value, str):
        return None
    match = _RECORD_IRI_RE.fullmatch(value)
    if match is None or match["segment"] in _RESERVED_SEGMENTS:
        return None
    return RecordIri(match["prefix"], match["segment"], match["uid"])


def parse_thing_iri(value: object) -> str | None:
    """The uid of a shared thing's IRI, ``https://w3id.org/battinfo/id/{uid}``, or ``None`` for anything else."""
    if not isinstance(value, str):
        return None
    match = _THING_IRI_RE.fullmatch(value)
    return match["uid"] if match is not None else None


def same_record(left: object, right: object) -> bool:
    """True when *left* and *right* are IRIs of one record, whichever form each has.

    They are when both parse (:func:`parse_record_iri`) to the same segment
    and uid under the same publisher, an IRI of the old form counting as
    prefix 1001. ``.../cell/{uid}`` and ``.../id/1001/cell/{uid}``
    are one record; ``.../id/1002/cell/{uid}`` is another.
    """
    first, second = parse_record_iri(left), parse_record_iri(right)
    return first is not None and second is not None and _record_key(first) == _record_key(second)


def _record_key(parsed: RecordIri) -> tuple[str, str, str]:
    return parsed.prefix or _OLD_FORM_PREFIX, parsed.segment, parsed.uid


def record_iri_regex(*segments: str, both_shapes: bool = False, things: bool = False) -> str:
    """The anchored regular expression that a record IRI under one of *segments* matches in full.

    Without *both_shapes* it matches the old form only; with it, the prefixed
    form under any prefix as well. With *things* it also matches a shared
    thing, ``https://w3id.org/battinfo/id/{uid}``, which a field that
    references a maker, a product model or a material accepts (ruling
    decision 4). The expression has no capturing groups and uses only syntax
    that a JSON Schema ``pattern`` shares with Python's ``re``.
    """
    if not segments:
        raise ValueError("record_iri_regex needs at least one segment.")
    names = [_checked_segment(segment) for segment in segments]
    alternation = names[0] if len(names) == 1 else "(?:" + "|".join(names) + ")"
    prefix = rf"(?:id/{PREFIX_PATTERN}/)?" if both_shapes else ""
    record = f"{prefix}{alternation}/"
    if things:
        record = f"(?:{record}|id/)"
    return rf"^{_ROOT_PATTERN}{record}{UID_PATTERN}$"


def record_iri_pattern(*segments: str, both_shapes: bool = False, things: bool = False) -> re.Pattern[str]:
    """:func:`record_iri_regex` compiled, for ``fullmatch`` or ``match``."""
    return re.compile(record_iri_regex(*segments, both_shapes=both_shapes, things=things))
