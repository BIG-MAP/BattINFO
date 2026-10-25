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

    from battinfo.namespace import parse_record_iri, record_iri, same_record

    record_iri("cell", "b6yn-0sxe-t2qk-9mjv")
    # 'https://w3id.org/battinfo/cell/b6yn-0sxe-t2qk-9mjv'
    record_iri("cell", "b6yn-0sxe-t2qk-9mjv", prefix="1001")
    # 'https://w3id.org/battinfo/id/1001/cell/b6yn-0sxe-t2qk-9mjv'
    parse_record_iri("https://w3id.org/battinfo/id/1001/cell/b6yn-0sxe-t2qk-9mjv")
    # RecordIri(prefix='1001', segment='cell', uid='b6yn-0sxe-t2qk-9mjv')
    same_record(
        "https://w3id.org/battinfo/cell/b6yn-0sxe-t2qk-9mjv",
        "https://w3id.org/battinfo/id/1001/cell/b6yn-0sxe-t2qk-9mjv",
    )
    # True

Nothing mints the prefixed form yet. Every builder calls :func:`record_iri`
without a prefix, so minted IRIs keep the old form until minting takes its
base from the workspace, and the recognisers built with
:func:`record_iri_pattern` accept the old form only until the v1 schemas
accept both shapes.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from battinfo.entities import UID_DASHED_RE

__all__ = [
    "BATTERY_GENOME_PREFIX",
    "BATTINFO_PREFIX",
    "BATTINFO_ROOT",
    "CONTEXT_BASE",
    "ID_BASE",
    "PREFIX_PATTERN",
    "RecordIri",
    "SCHEMA_BASE",
    "SEGMENT_PATTERN",
    "UID_PATTERN",
    "VOCABULARY_NAMESPACE",
    "parse_record_iri",
    "parse_thing_iri",
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

# Publisher prefixes (ruling decision 3). These constants stand in for the
# prefix register, a data file in this package that is to replace them; until
# it exists they are the only list.
#: BattINFO itself. It holds definitions only (``def/1000/``), never records.
BATTINFO_PREFIX = "1000"
#: The Battery Genome registry, and the SDK's own prefix.
BATTERY_GENOME_PREFIX = "1001"
# Prefixes that hold definitions only: no record is minted under them.
_DEFINITIONS_ONLY_PREFIXES = frozenset({BATTINFO_PREFIX})
# The prefix an IRI of the old form counts as when two IRIs are compared. The
# old form and the ``/id/1001/`` form of one segment and uid are one record
# (ruling decision 5); under any other prefix the same uid is another record
# (decision 3).
_OLD_FORM_PREFIX = BATTERY_GENOME_PREFIX

#: A uid: the grammar of ``entities.UID_DASHED_RE``, without its anchors.
UID_PATTERN = UID_DASHED_RE.pattern.removeprefix("^").removesuffix("$")
#: A record segment such as ``spec``, ``cell`` or ``current-collector``.
SEGMENT_PATTERN = r"[a-z][a-z0-9-]*"
#: A publisher prefix: a number of four or more digits, never a name.
PREFIX_PATTERN = r"[0-9]{4,}"

# The branch names at the root: id/ holds records of the prefixed form and
# shared things, def/ publishers' definitions, which nothing here mints.
# Neither is ever a record segment, so ``https://w3id.org/battinfo/id/{uid}``
# is a shared thing, not a record.
_BRANCHES = frozenset({"id", "def"})
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
    if not isinstance(segment, str) or not _SEGMENT_RE.fullmatch(segment) or segment in _BRANCHES:
        raise ValueError(
            f"{segment!r} is not a record segment: a segment is a lower-case word such as spec, cell or "
            "current-collector, and never id or def."
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
    if match is None or match["segment"] in _BRANCHES:
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


def record_iri_regex(*segments: str, both_shapes: bool = False) -> str:
    """The anchored regular expression that a record IRI under one of *segments* matches in full.

    Without *both_shapes* it matches the old form only, as every recogniser
    has; with it, the prefixed form under any prefix as well. The expression
    has no capturing groups and uses only syntax that a JSON Schema
    ``pattern`` shares with Python's ``re``.
    """
    if not segments:
        raise ValueError("record_iri_regex needs at least one segment.")
    names = [_checked_segment(segment) for segment in segments]
    alternation = names[0] if len(names) == 1 else "(?:" + "|".join(names) + ")"
    prefix = rf"(?:id/{PREFIX_PATTERN}/)?" if both_shapes else ""
    return rf"^{_ROOT_PATTERN}{prefix}{alternation}/{UID_PATTERN}$"


def record_iri_pattern(*segments: str, both_shapes: bool = False) -> re.Pattern[str]:
    """:func:`record_iri_regex` compiled, for ``fullmatch`` or ``match``."""
    return re.compile(record_iri_regex(*segments, both_shapes=both_shapes))
