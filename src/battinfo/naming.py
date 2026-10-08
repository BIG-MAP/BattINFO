"""Record handles and titles.

A record has three names, and each has one job:

1. The IRI is its identity. It is opaque and never changes.
2. The handle is a short slug, unique within one registry workspace and shown
   as ``<workspace>/<handle>``, for example
   ``flores-ocv/graphite-aq-1-063b77-cell``.
3. The title (the record's ``name``) is readable wording for people, for
   example ``Graphite AQ-1 cell 063b77``.

Handles and titles are display text. Correcting one never moves the IRI, and
code should read a record's structured fields rather than parse its handle.

This module builds both from structured parts, so a corpus gets consistent
names without anyone typing them by hand::

    from battinfo.naming import handle_for, title_for

    handle_for("cell", group="flores-ocv", subject="graphite",
               variant="Gr-AQ-1", sample="063b77")
    # 'flores-ocv/graphite-aq-1-063b77-cell'
    title_for("cell", subject="graphite", variant="Gr-AQ-1", sample="063b77")
    # 'Graphite AQ-1 cell 063b77'

A handle reads ``<group>/<subject>[-<variant>][-<sample>][-<method>]-<kind>``.
The group is the handle of the collection the record belongs to; a
collection's own handle is the bare group. The subject is the material kind
from :func:`battinfo.materials.material_kinds`, the variant is the source's
design or batch label with the material prefix dropped (``Gr-AQ-1`` becomes
``aq-1``), the sample is the source's sample id, the method is the test method,
and the kind word from :data:`KIND_WORDS` always comes last.

All functions here are pure: they read the shipped material-kind vocabulary and
nothing else, and they never mint or change an IRI.
"""

from __future__ import annotations

import re
import unicodedata
from types import MappingProxyType
from typing import Mapping

from battinfo.entities import ENTITY_KINDS

__all__ = [
    "COLLECTION",
    "HANDLE_MAX_LENGTH",
    "HANDLE_PATTERN",
    "KIND_WORDS",
    "handle_for",
    "is_valid_handle",
    "kind_word",
    "title_for",
]

#: Longest handle the record schemas accept.
HANDLE_MAX_LENGTH = 120

#: The handle grammar: lowercase ASCII segments joined by ``/``, each segment
#: letters and digits separated by single hyphens. The record schemas carry the
#: same pattern (``$defs/Handle``).
HANDLE_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*(?:/[a-z0-9]+(?:-[a-z0-9]+)*)*$"
_HANDLE_RE = re.compile(HANDLE_PATTERN)

#: The kind word that ends a handle, one per entity kind (keys are the
#: ``entity_type`` values of :data:`battinfo.entities.ENTITY_KINDS`). Titles use
#: the same words with spaces for hyphens (``material-lot`` -> ``material lot``).
KIND_WORDS: Mapping[str, str] = MappingProxyType({
    "cell-spec": "cell-spec",
    "cell": "cell",
    "test-protocol": "test-spec",
    "test": "test",
    "dataset": "dataset",
    "material-spec": "material-spec",
    "material": "material-lot",
    "electrode-spec": "electrode-spec",
    "electrode": "electrode",
    "separator-spec": "separator-spec",
    "separator": "separator",
    "current-collector-spec": "current-collector-spec",
    "current-collector": "current-collector",
    "electrolyte-spec": "electrolyte-spec",
    "electrolyte": "electrolyte",
    "housing-spec": "housing-spec",
    "housing": "housing",
    "equipment-spec": "equipment-spec",
    "equipment": "equipment",
    "channel": "channel",
    "parameter-set": "parameter-set",
    "organization": "organization",
})

#: The kind name for a dataset collection (a ``dataset`` record whose
#: ``additional_type`` is ``DatasetSeries``). A collection's handle is the bare
#: group and carries no kind word.
COLLECTION = "collection"
_COLLECTION_ALIASES = frozenset({"collection", "dataset-series", "series"})

# Titles for subjects whose vocabulary label is too long for a title line.
_SUBJECT_LABEL_OVERRIDES: Mapping[str, str] = MappingProxyType({
    "silicon_graphite": "Silicon-graphite",
})

# Longest leading run of label tokens tried as a material prefix ("Si-Gr").
_MAX_PREFIX_TOKENS = 3


def _kind_aliases() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for kind in ENTITY_KINDS:
        aliases[kind.record_key.replace("_", "-")] = kind.entity_type
        aliases[kind.subdir] = kind.entity_type
    for entity_type, word in KIND_WORDS.items():
        aliases[word] = entity_type
    return aliases


_KIND_ALIASES = _kind_aliases()


def _resolve_kind(kind: str) -> str:
    """An entity type from :data:`KIND_WORDS`, or :data:`COLLECTION`."""
    if not isinstance(kind, str):
        raise TypeError(f"kind must be a string, got {type(kind).__name__}.")
    key = re.sub(r"[\s_]+", "-", kind.strip().lower())
    if key in _COLLECTION_ALIASES:
        return COLLECTION
    if key in KIND_WORDS:
        return key
    if key in _KIND_ALIASES:
        return _KIND_ALIASES[key]
    known = ", ".join([*KIND_WORDS, COLLECTION])
    raise ValueError(f"Unknown record kind {kind!r}. Expected one of: {known}.")


def kind_word(kind: str) -> str | None:
    """The word that ends a handle for *kind*, or ``None`` for a collection.

    *kind* is an entity type (``"material"``), a record key
    (``"cell_instance"``), or a kind word (``"material-lot"``, ``"test-spec"``).

    >>> kind_word("material")
    'material-lot'
    >>> kind_word("test_spec")
    'test-spec'
    """
    resolved = _resolve_kind(kind)
    return None if resolved == COLLECTION else KIND_WORDS[resolved]


def is_valid_handle(value: object) -> bool:
    """True when *value* follows the handle grammar and length limit.

    >>> is_valid_handle("flores-ocv/graphite-material-spec")
    True
    >>> is_valid_handle("Flores OCV")
    False
    """
    return (
        isinstance(value, str)
        and len(value) <= HANDLE_MAX_LENGTH
        and _HANDLE_RE.fullmatch(value) is not None
    )


# ── Normalisation ─────────────────────────────────────────────────────────────


def _text(value: object, what: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise TypeError(f"{what} must be a string, got {type(value).__name__}.")
    return str(value)


def _ascii(value: str) -> str:
    """ASCII transliteration: accents fold away, letters with no ASCII form drop."""
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")


def _slug(value: object, what: str) -> str:
    """One handle segment: lowercase ASCII words joined by single hyphens."""
    text = _text(value, what)
    slug = re.sub(r"[^a-z0-9]+", "-", _ascii(text).lower()).strip("-")
    if not slug:
        raise ValueError(f"{what} {text!r} has no letters or digits to build a handle from.")
    return slug


def _tokens(value: object, what: str) -> list[str]:
    """The alphanumeric words of *value*, case kept, in ASCII."""
    text = _text(value, what)
    tokens = re.findall(r"[A-Za-z0-9]+", _ascii(text))
    if not tokens:
        raise ValueError(f"{what} {text!r} has no letters or digits.")
    return tokens


def _group_slug(group: object) -> str:
    text = _text(group, "group")
    parts = [part for part in text.split("/") if part.strip()]
    if not parts:
        raise ValueError(f"group {text!r} has no letters or digits to build a handle from.")
    return "/".join(_slug(part, "group") for part in parts)


def _subject_key(subject: object) -> str | None:
    """The canonical material-kind key for *subject*, or ``None`` if it is not one."""
    from battinfo.materials import resolve_material_kind  # noqa: PLC0415

    return resolve_material_kind(_text(subject, "subject"))


def _subject_slug(subject: object) -> str:
    key = _subject_key(subject)
    return key.replace("_", "-") if key is not None else _slug(subject, "subject")


def _subject_label(subject: object) -> str:
    """The short title label for a subject: Graphite, Silicon-graphite, LNMO, NMC532."""
    from battinfo.materials import material_kind  # noqa: PLC0415

    key = _subject_key(subject)
    if key is None:
        label = " ".join(_text(subject, "subject").split())
        if not label:
            raise ValueError("subject is empty.")
        return label
    if key in _SUBJECT_LABEL_OVERRIDES:
        return _SUBJECT_LABEL_OVERRIDES[key]
    entry = material_kind(key) or {}
    label = str(entry.get("label") or key).strip()
    if label.endswith(")") and "(" in label:
        # A trailing parenthetical is either a formula or an abbreviation:
        # "NMC532 (LiNi0.5Mn0.3Co0.2O2)" -> NMC532; "Lithium iron phosphate (LFP)" -> LFP.
        before, _, inside = label[:-1].rpartition("(")
        before, inside = before.strip(), inside.strip()
        if before and " " not in before:
            return before
        if inside and " " not in inside:
            return inside
        return before or label
    return label


def _variant_tokens(variant: object, subject: object | None) -> list[str]:
    """The variant label's words with a leading material prefix dropped.

    The prefix is dropped only when it names the same material kind as the
    subject (``Gr`` for graphite, ``Si-Gr`` for silicon-graphite), so a label
    that merely starts with another material's name (``NMP-2``) keeps it.
    """
    tokens = _tokens(variant, "variant")
    key = _subject_key(subject) if subject is not None else None
    if key is None:
        return tokens
    from battinfo.materials import resolve_material_kind  # noqa: PLC0415

    for count in range(min(len(tokens), _MAX_PREFIX_TOKENS), 0, -1):
        head = tokens[:count]
        spellings = {"-".join(head), " ".join(head), "/".join(head), "".join(head)}
        if any(resolve_material_kind(spelling) == key for spelling in spellings):
            return tokens[count:]
    return tokens


def _kind_title_words(entity_type: str) -> str:
    return KIND_WORDS[entity_type].replace("-", " ")


# ── Handles ───────────────────────────────────────────────────────────────────


def handle_for(
    kind: str,
    *,
    group: str | None = None,
    subject: str | None = None,
    variant: str | None = None,
    sample: str | int | None = None,
    method: str | None = None,
) -> str:
    """Build a record handle from structured parts.

    Args:
        kind: The record type: an entity type (``"material"``), a record key
            (``"cell_instance"``), a kind word (``"material-lot"``), or
            ``"collection"`` for a dataset collection.
        group: The handle of the collection (or other grouping source) the
            record belongs to, e.g. ``"flores-ocv"``. It may itself contain
            ``/``. A collection's handle is the bare group.
        subject: The material kind, as a vocabulary key or alias
            (``"graphite"``, ``"Si-Gr"``). Vocabulary entries become their key
            with ``_`` replaced by ``-``; other text is slugged as given.
        variant: The source's own design or batch label (``"Gr-AQ-1"``). A
            leading prefix naming the subject's material is dropped, so
            ``Gr-AQ-1`` becomes ``aq-1``.
        sample: The source's sample id for a physical item or its results.
        method: The test method for tests and datasets (``"gitt"``,
            ``"p-OCV hold"``).

    Every part is normalised the same way: lowercased, transliterated to ASCII,
    and runs of anything other than letters and digits collapsed to one hyphen.
    The kind word always comes last.

    Raises:
        ValueError: when a part has no letters or digits, the kind is unknown,
            a collection is given anything but a group, or the handle would be
            longer than :data:`HANDLE_MAX_LENGTH`.

    >>> handle_for("collection", group="flores-ocv")
    'flores-ocv'
    >>> handle_for("test", group="flores-ocv", subject="graphite",
    ...            variant="Gr-AQ-1", sample="063b77", method="GITT")
    'flores-ocv/graphite-aq-1-063b77-gitt-test'
    """
    resolved = _resolve_kind(kind)
    group_slug = _group_slug(group) if group is not None else None

    if resolved == COLLECTION:
        extras = [name for name, value in (
            ("subject", subject), ("variant", variant), ("sample", sample), ("method", method),
        ) if value is not None]
        if extras:
            raise ValueError(
                "A collection's handle is its bare group; drop "
                + ", ".join(f"{name}=" for name in extras) + "."
            )
        if group_slug is None:
            raise ValueError("A collection's handle is its group: pass group=...")
        handle = group_slug
    else:
        words: list[str] = []
        if subject is not None:
            words.append(_subject_slug(subject))
        if variant is not None:
            tokens = _variant_tokens(variant, subject)
            if tokens:
                words.append(_slug("-".join(tokens), "variant"))
        if sample is not None:
            words.append(_slug(sample, "sample"))
        if method is not None:
            words.append(_slug(method, "method"))
        words.append(KIND_WORDS[resolved])
        segment = "-".join(words)
        handle = f"{group_slug}/{segment}" if group_slug else segment

    if len(handle) > HANDLE_MAX_LENGTH:
        raise ValueError(
            f"handle {handle!r} is {len(handle)} characters; the limit is {HANDLE_MAX_LENGTH}."
        )
    if not is_valid_handle(handle):  # pragma: no cover - normalisation guarantees it
        raise ValueError(f"handle {handle!r} does not follow the handle grammar.")
    return handle


# ── Titles ────────────────────────────────────────────────────────────────────

_RESULT_KINDS = frozenset({"test", "dataset"})


def title_for(
    kind: str,
    *,
    subject: str | None = None,
    variant: str | None = None,
    sample: str | int | None = None,
    method: str | None = None,
    tested: str | None = "cell",
    label: str | None = None,
) -> str:
    """Build a readable record title (the ``name``) from structured parts.

    The title mirrors the handle in plain English::

        <Subject> [<VARIANT>] <kind words> [<sample>] [<METHOD>]

    Tests and datasets name the item they are about first, then the method,
    then their own kind (``Graphite AQ-1 cell 063b77 GITT test``), and a test
    spec puts its method before its kind (``GITT test spec``).

    Args:
        kind: The record type, as for :func:`handle_for`.
        subject: The material kind. Vocabulary entries use a short label
            (Graphite, Silicon-graphite, Silicon, LNMO, LFP, NMC111, NMC532);
            other text is used as given.
        variant: The source's design or batch label. The material prefix is
            dropped as in :func:`handle_for` and the rest is upper case
            (``Gr-AQ-1`` -> ``AQ-1``).
        sample: The source's sample id, kept as written.
        method: The test method, upper case (``gitt`` -> ``GITT``).
        tested: For tests and datasets, the kind of item tested (default
            ``"cell"``). Pass ``None`` to leave it out. Other kinds ignore it.
        label: A collection's descriptive name; ``" collection"`` is
            appended unless it already ends that way. Only collections take it.

    Raises:
        ValueError: when the kind is unknown, a collection has no label, or a
            non-collection is given a label.

    >>> title_for("electrode", subject="graphite", variant="Gr-AQ-1", sample="063b77")
    'Graphite AQ-1 electrode 063b77'
    >>> title_for("test-spec", method="gitt")
    'GITT test spec'
    """
    resolved = _resolve_kind(kind)

    if resolved == COLLECTION:
        if label is None or not " ".join(_text(label, "label").split()):
            raise ValueError("A collection's title needs label=..., e.g. 'Flores et al. 2026 half-cell OCV'.")
        text = " ".join(_text(label, "label").split())
        return text if text.lower().endswith(" collection") else f"{text} collection"
    if label is not None:
        raise ValueError("label= is only used for collections; build other titles from their parts.")

    words: list[str] = []
    if subject is not None:
        words.append(_subject_label(subject))
    if variant is not None:
        tokens = _variant_tokens(variant, subject)
        if tokens:
            words.append("-".join(tokens).upper())
    sample_text = " ".join(_text(sample, "sample").split()) if sample is not None else ""
    method_text = " ".join(_text(method, "method").split()).upper() if method is not None else ""

    if resolved in _RESULT_KINDS or resolved == "test-protocol":
        if resolved in _RESULT_KINDS and tested and (words or sample_text):
            words.append(_kind_title_words(_resolve_tested(tested)))
        if sample_text:
            words.append(sample_text)
        if method_text:
            words.append(method_text)
        words.append(_kind_title_words(resolved))
    else:
        words.append(_kind_title_words(resolved))
        if sample_text:
            words.append(sample_text)
        if method_text:
            words.append(method_text)

    title = " ".join(word for word in words if word)
    return title[:1].upper() + title[1:]


def _resolve_tested(tested: str) -> str:
    resolved = _resolve_kind(tested)
    if resolved == COLLECTION:
        raise ValueError("tested= names a record kind such as 'cell' or 'electrode', not a collection.")
    return resolved
