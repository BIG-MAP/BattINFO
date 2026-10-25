"""Single source of truth for BattINFO record types.

Every BattINFO record is one of a small set of **entity kinds**, and the model
follows a uniform *spec + instance* pattern: a *spec* is the reusable, datasheet
-like type description; an *instance* is a physical realization of that spec
(a batch of material, a built electrode, a tested cell). ``cell-spec``/``cell``
and ``test-spec``/``test`` already follow this; new families extend it.

This module centralizes the per-type metadata (top-level JSON key, schema file,
on-disk subdirectory, IRI namespace, instance->spec link) that used to be
copy-pasted across ``api.py``, ``validate/record.py``, ``validate/references.py``,
``ws.py`` and ``_workspace.py``. Those call sites now derive their dispatch from
:data:`ENTITY_KINDS` so adding a family is a single registry entry.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Optional

UID_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"

#: A uid in its dashed form: four groups of four characters from
#: :data:`UID_ALPHABET`, joined by dashes (``pge5-wer6-2q82-v9k0``). Record
#: files are named after it, so nothing else may name one.
UID_DASHED_RE = re.compile(r"^[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}$")


def is_dashed_uid(value: object) -> bool:
    """True when *value* is a uid in its dashed form, such as ``pge5-wer6-2q82-v9k0``."""
    return isinstance(value, str) and UID_DASHED_RE.fullmatch(value) is not None


def stable_uid(seed: str) -> str:
    """Deterministic dashed 16-char uid derived from an identity seed.

    The single minting primitive shared by the workspace finalizers and the
    ``save_*`` builders: the same identity seed always mints the same uid, so a
    re-run of an identical ingest lands on the existing record instead of
    creating a duplicate corpus. The registry's dedup logic mirrors the same
    volatile-key policy (see ``_workspace._VOLATILE_SEED_KEYS``).

    The seed is put in Unicode NFC first, so a composed and a decomposed
    spelling of one text mint one uid. NFC leaves an ASCII seed as it is, so
    URLs, hashes and every ASCII seed keep their uids. The seed builders
    normalise their free-text fields further (:func:`seed_text`).
    """
    return _uid_from_bytes(unicodedata.normalize("NFC", seed).encode("utf-8"))


def legacy_stable_uid(seed: str) -> str:
    """The uid :func:`stable_uid` gave *seed* before 0.8.0, which had no NFC step.

    Only for finding a record minted under an earlier seed rule (see
    :func:`keep_legacy_uid`); nothing new is minted with it.
    """
    return _uid_from_bytes(seed.encode("utf-8"))


def _uid_from_bytes(data: bytes) -> str:
    value = int.from_bytes(hashlib.sha256(data).digest()[:16], "big")
    chars: list[str] = []
    for _ in range(16):
        value, remainder = divmod(value, 32)
        chars.append(UID_ALPHABET[remainder])
    token = "".join(reversed(chars))
    return "-".join((token[:4], token[4:8], token[8:12], token[12:16]))


def seed_text(value: object) -> str:
    """A free-text identity field as it enters an identity seed.

    The one normaliser every seed builder applies to its free-text identity
    fields (manufacturer, model, name, serial number, batch, labels and size
    code): the text in Unicode NFC, stripped, with each run of whitespace,
    no-break and other non-space whitespace included, as one space. Case is
    kept. ``"C01 "``, ``"C01"`` and ``"C01"`` followed by a no-break space all
    give ``"C01"``. ``None``, and a value that is nothing but whitespace,
    give ``""``, which a seed treats as missing.

    Locators (URLs and paths) are not free text: whitespace is part of a
    location, so they get NFC alone (:func:`dataset_locator_seed`). Hashes and
    content seeds are left as they are.
    """
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    return " ".join(unicodedata.normalize("NFC", text).split())


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _stripped(value: object) -> str:
    """*value* stripped, as the seeds of before 0.8.0 read a field."""
    if value is None:
        return ""
    return (value if isinstance(value, str) else str(value)).strip()


#: The chemistry part of a cell-spec seed, frozen with 0.8.0: each key and alias
#: of the chemistry vocabulary (``entity_type_map.json``) as it stood then,
#: case-folded, to the key it seeds as, an alias resolved. The vocabulary grows
#: when the ontology mappings are vendored again; this table does not follow it,
#: because a new key or alias would change the seed of every cell spec spelled
#: that way and move its IRI, and the IRIs of its cells, tests and datasets.
#: Changing it is a seed change (IDENTIFIER_POLICY 5.5), which needs a lookup
#: under the old table; ``tests/test_seed_normalisation.py`` fails when it changes.
CHEMISTRY_SEED_KEYS: Mapping[str, str] = MappingProxyType(
    {
        "al-air": "al-air",
        "alkaline": "alkaline-zn-mno2",
        "alkaline-zn-mno2": "alkaline-zn-mno2",
        "ca-ion": "ca-ion",
        "fe-air": "fe-air",
        "fe-flow": "fe-flow",
        "k-ion": "k-ion",
        "lead-acid": "lead-acid",
        "leclanche": "leclanche",
        "li-air": "li-air",
        "li-cfx": "li-cfx",
        "li-cuo": "li-cuo",
        "li-fes2": "li-fes2",
        "li-ion": "li-ion",
        "li-metal": "li-metal",
        "li-mno2": "li-mno2",
        "li-primary": "li-metal",
        "li-s": "li-s",
        "li-socl2": "li-socl2",
        "mg-air": "mg-air",
        "mg-ion": "mg-ion",
        "na-air": "na-air",
        "na-ion": "na-ion",
        "ni-cd": "ni-cd",
        "ni-fe": "ni-fe",
        "ni-mh": "ni-mh",
        "ni-zn": "ni-zn",
        "si-air": "si-air",
        "vanadium-flow": "vanadium-flow",
        "zinc-carbon": "zinc-carbon",
        "zinc-chloride": "zinc-chloride",
        "zn-air": "zn-air",
        "zn-br-flow": "zn-br-flow",
        "zn-hgo": "zn-hgo",
        "zn-mno2": "zn-mno2",
        "znmno2": "zn-mno2",
    }
)


def chemistry_seed_key(value: object) -> str:
    """The chemistry part of a cell-spec identity seed: its vocabulary key.

    A value that matches a key or an alias of the chemistry vocabulary after
    case-folding seeds as that key, with the alias resolved: ``Li-ion``,
    ``li-ion`` and ``LI-ION`` give ``li-ion``, and the alias ``li-primary``
    gives ``li-metal``. A narrower couple keeps its own key (``li-mno2`` is
    not seeded as its broader ``li-metal``). Any other value is seeded as
    normalised free text (:func:`seed_text`), its case kept. The vocabulary
    read is the one frozen with 0.8.0 (:data:`CHEMISTRY_SEED_KEYS`), so a key
    added to the vocabulary later does not move an IRI.
    """
    text = seed_text(value)
    return CHEMISTRY_SEED_KEYS.get(text.casefold(), text)


def cell_spec_identity_seed(
    *,
    manufacturer: object,
    model: object,
    format: object,
    chemistry: object,
    size_code: object = None,
) -> str:
    """Identity seed for a cell spec, shared by every minting surface.

    ``manufacturer :: model :: format :: chemistry :: size_code``. The
    manufacturer, model and size code enter as :func:`seed_text`, their case
    kept; the chemistry as its vocabulary key (:func:`chemistry_seed_key`);
    the format, a controlled value, stripped. A missing manufacturer, model,
    format or chemistry seeds as ``unknown-manufacturer`` (and so on).
    """
    return "::".join(
        [
            seed_text(manufacturer) or "unknown-manufacturer",
            seed_text(model) or "unknown-model",
            _stripped(format) or "unknown-format",
            chemistry_seed_key(chemistry) or "unknown-chemistry",
            seed_text(size_code),
        ]
    )


def legacy_cell_spec_identity_seed(
    *,
    manufacturer: object,
    model: object,
    format: object,
    chemistry: object,
    size_code: object = None,
) -> str:
    """The cell-spec identity seed of before 0.8.0, kept to find specs minted under it.

    The same parts as :func:`cell_spec_identity_seed`, each only stripped (the
    size code not even that) and the chemistry as written. Hash it with
    :func:`legacy_stable_uid`; nothing new is minted from it.
    """
    return "::".join(
        [
            _stripped(manufacturer) or "unknown-manufacturer",
            _stripped(model) or "unknown-model",
            _stripped(format) or "unknown-format",
            _stripped(chemistry) or "unknown-chemistry",
            size_code if isinstance(size_code, str) else "",
        ]
    )


def cell_spec_seed_fields(body: Mapping[str, Any]) -> dict[str, Any]:
    """The identity fields of a cell-spec record body, as the seed functions take them.

    Reads a canonical ``cell_spec`` body (``cell_format``, a manufacturer
    organization) and a library ``specification`` body (``format``, a
    manufacturer name) alike.
    """
    manufacturer = body.get("manufacturer")
    if isinstance(manufacturer, Mapping):
        manufacturer = manufacturer.get("name")
    return {
        "manufacturer": manufacturer,
        "model": body.get("model"),
        "format": body.get("cell_format") or body.get("format"),
        "chemistry": body.get("chemistry"),
        "size_code": body.get("size_code"),
    }


def keep_legacy_uid(
    uid: str,
    legacy_uid: str,
    *,
    saved: Callable[[str], Optional[Mapping[str, Any]]],
    same_identity: Callable[[Mapping[str, Any]], bool],
) -> str:
    """The uid a record minted as *uid* takes, keeping an IRI minted under an earlier seed rule.

    *legacy_uid* is the uid the earlier rule gives the same fields. A seed
    change must not move a record that is already saved: when *legacy_uid*
    differs from *uid*, nothing is saved under *uid*, and the record saved
    under *legacy_uid* has the same identity (*same_identity* of its body),
    that record keeps its IRI and *legacy_uid* is returned. Otherwise *uid*.
    *saved* returns the body of the record saved under a uid, or ``None``;
    either form of the record's IRI counts (:func:`saved_record_document`), so
    the IRI to keep is the one that body carries.
    """
    if legacy_uid == uid or saved(uid) is not None:
        return uid
    body = saved(legacy_uid)
    return legacy_uid if body is not None and same_identity(body) else uid


def saved_record_document(entity_type: str, uid: str, roots: Iterable[str | Path]) -> Optional[Mapping[str, Any]]:
    """The *entity_type* record document saved as *uid* under one of *roots*, or ``None``.

    Looks at the file a save writes (:func:`save_entity_path`) in each root
    and returns the whole document (its body and the sections beside it, such
    as a cell spec's ``properties``) only when the body carries an IRI of the
    record *uid* names, in whichever form it was saved: the old form or the
    ``/id/1001/`` form (``namespace.same_record``). That IRI is the one the
    record keeps.
    """
    from battinfo._jsonio import read_record_json  # noqa: PLC0415
    from battinfo.namespace import record_iri, same_record  # noqa: PLC0415

    kind = ENTITY_BY_TYPE[entity_type]
    for root in roots:
        path = save_entity_path(entity_type, uid, Path(root))
        if not path.is_file():
            continue
        try:
            doc = read_record_json(path)
        except (OSError, ValueError):
            continue
        body = doc.get(kind.record_key) if isinstance(doc, Mapping) else None
        if isinstance(body, Mapping) and same_record(body.get("id"), record_iri(kind.iri_namespace, uid)):
            return doc
    return None


def saved_record_body(entity_type: str, uid: str, roots: Iterable[str | Path]) -> Optional[Mapping[str, Any]]:
    """The body of the *entity_type* record saved as *uid* under one of *roots*, or ``None``.

    The object under the kind's record key in :func:`saved_record_document`.
    """
    doc = saved_record_document(entity_type, uid, roots)
    return None if doc is None else doc[ENTITY_BY_TYPE[entity_type].record_key]


def cell_spec_uid(
    fields: Mapping[str, Any],
    *,
    roots: Iterable[str | Path] = (),
    saved: Optional[Callable[[str], Optional[Mapping[str, Any]]]] = None,
) -> str:
    """The uid of a cell spec minted from its natural key (*fields*, see :func:`cell_spec_seed_fields`).

    A cell spec already saved with the IRI the seeds of before 0.8.0 gave the
    same identity keeps that IRI (:func:`keep_legacy_uid`). It is looked for
    under *roots*, the records folders a save writes to, or with *saved*, which
    returns the body of the spec saved under a uid, or ``None``.
    """
    seed = cell_spec_identity_seed(**fields)
    if saved is None:
        folders = tuple(roots)

        def saved(uid: str) -> Optional[Mapping[str, Any]]:
            return saved_record_body("cell-spec", uid, folders)

    return keep_legacy_uid(
        stable_uid(seed),
        legacy_stable_uid(legacy_cell_spec_identity_seed(**fields)),
        saved=saved,
        same_identity=lambda body: cell_spec_identity_seed(**cell_spec_seed_fields(body)) == seed,
    )


#: The uid record templates used as a placeholder ("0000000000000000", dashed).
#: Templates no longer write it; validation rejects a record whose own IRI still
#: carries it, since every record made from an unedited old template would claim it.
PLACEHOLDER_UID = "0000-0000-0000-0000"


def is_placeholder_iri(value: object) -> bool:
    """True for a record IRI whose uid is the all-zero template placeholder."""
    return isinstance(value, str) and value.rstrip("/").rsplit("/", 1)[-1] == PLACEHOLDER_UID


def cell_instance_identity_seed(
    *,
    cell_spec_id: str | None,
    serial_number: str | None = None,
    batch_id: str | None = None,
    name: str | None = None,
) -> Optional[str]:
    """Identity seed for a physical cell instance — shared by every minting surface.

    The instance IRI is deterministic from (spec IRI, serial/batch/name), so the
    same physical cell authored through the workspace (``ws.add('cell', ...)``),
    ``save_cell_instance`` or ``create_cell_instance`` lands on the same IRI
    instead of minting parallel identities per surface.

    The serial number is the cell's identity and the name is display text, so
    the label part of the seed takes the serial first. Renaming a cell that has
    a serial keeps its IRI. A cell without a serial is still seeded from its
    name, then its batch.

    The serial, batch and name enter as :func:`seed_text`, so ``"C01 "`` and
    ``"C01"`` are one cell.

    Returns ``None`` when the instance carries no distinguishing identity at all
    (no name, serial, or batch) — callers must then fall back to their own
    anonymous policy (e.g. a random uid), because two anonymous but physically
    distinct cells must never silently dedup into one.
    """
    serial, batch = seed_text(serial_number), seed_text(batch_id)
    label = next((value for value in (serial, seed_text(name), batch) if value), "")
    if not label:
        return None
    return "::".join(
        [
            (cell_spec_id or "").strip() or "unknown-cell-spec",
            serial,
            batch,
            label,
        ]
    )


def dataset_locator_seed(
    *,
    access_url: str | None = None,
    download_url: str | None = None,
    dataset_path: str | Path | None = None,
    workspace_root: str | Path | None = None,
) -> str:
    """The location part of a dataset's identity seed, the same wherever the workspace sits.

    Shared by every surface that mints a dataset IRI (the workspace finalizer,
    the ``save_dataset`` builder and the publication package). An explicit
    remote ``access_url`` or ``download_url`` (``https://...`` or any other
    non-file URL) is used as it is. A local data file or folder, given as
    ``dataset_path`` or as a ``file:`` URL, is named by its path relative to
    *workspace_root* in POSIX form when it lies inside that folder; a relative
    path is read against *workspace_root*, never against the current
    directory. Outside the workspace, or with no workspace root, it is named
    by its folder and its name (``run1/data.csv``), so two files with one name
    in different folders do not share an IRI. The absolute path never enters
    the seed, so the same workspace built in another folder, by a colleague or
    a CI job, mints the same dataset IRIs.

    The locator is put in Unicode NFC and keeps its whitespace: a URL or a
    path that differs only between composed and decomposed characters names
    one location, one that differs in whitespace names another.

    Returns ``""`` when the dataset names no location at all.
    """
    from battinfo._util import is_local_location, local_path, path_tail  # noqa: PLC0415

    for url in (access_url, download_url):
        if isinstance(url, str) and url.strip() and not is_local_location(url):
            return _nfc(url.strip())
    root = Path(workspace_root).resolve() if workspace_root is not None else None
    for candidate in (dataset_path, access_url, download_url):
        path = local_path(candidate)
        if path is None or not str(path).strip():
            continue
        if root is not None:
            absolute = path if path.is_absolute() else root / path
            try:
                relative = absolute.resolve().relative_to(root)
            except (OSError, ValueError):
                relative = None
            if relative is not None and relative.parts:
                return _nfc(relative.as_posix())
        return _nfc(path_tail(path))
    return ""


def test_identity_seed(
    *,
    cell_id: object,
    kind: object,
    protocol_id: object = None,
    protocol_name: object = None,
    data_locator: object = None,
    started_at: object = None,
    name: object = None,
) -> str:
    """Identity seed for a test, one run on one cell, shared by every minting surface.

    ``cell IRI :: kind :: protocol :: run``:

    - The protocol is the IRI of the test spec the run followed whenever the
      test names one, saved in this workspace or published elsewhere. A test
      without one is seeded with its protocol name (:func:`seed_text`), and
      with nothing when that name only restates the kind (``ws.add("test")``
      names an unnamed protocol after the test type). A name read from a copy
      of a published record never enters, so the IRI does not depend on
      whether a registry lookup worked.
    - The run tells two runs of one kind on one cell apart: the locator of
      the test's first data file (*data_locator*, from
      :func:`dataset_locator_seed`); for a test without a data file, the
      start time the caller gave (*started_at*) in Unix seconds; and for a
      test with neither, the name the caller gave it (*name*, as
      :func:`seed_text`), as a cell without a serial number is seeded from
      its name. A test with none of these has an empty run part.

    A test with a data file or a start time is told apart by those, so its
    name is display text and renaming it keeps its IRI. A title that
    BattINFO generated, such as ``C01 cycling``, depends on how the cell was
    referenced and never decides an IRI: callers pass only a name the caller
    gave (see :func:`given_test_name`). Nothing read from inside a data file
    enters either: a start time measured from a file can first appear after
    a converter upgrade, and one run would get two IRIs. A caller that has
    data files therefore gives their locator, and *started_at* only when
    there is none.
    """
    kind_text = _stripped(kind)
    return "::".join(
        [
            _stripped(cell_id) or "unknown-cell",
            kind_text or "other",
            _test_protocol_seed(protocol_id, protocol_name, kind_text),
            _test_run_seed(data_locator, started_at, name),
        ]
    )


# Its name starts with "test", so pytest would collect it from a test module that imports it.
test_identity_seed.__test__ = False  # type: ignore[attr-defined]


def _test_protocol_seed(protocol_id: object, protocol_name: object, kind: str) -> str:
    """The protocol part of a test seed: its IRI, else its name unless that only restates *kind*."""
    iri = _stripped(protocol_id)
    if iri:
        return iri
    name = seed_text(protocol_name)
    if name.casefold() == seed_text(kind.replace("_", " ")).casefold():
        return ""
    return name


def _test_run_seed(data_locator: object, started_at: object, name: object = None) -> str:
    """The run part of a test seed: the data file's locator, else ``started_at=<Unix seconds>``, else ``name=<name>``."""
    if isinstance(data_locator, str) and data_locator.strip():
        return _nfc(data_locator)
    if started_at is not None:
        from battinfo.api._shared import _to_unix_time  # noqa: PLC0415

        unix = _to_unix_time(started_at)
        text = str(unix) if unix is not None else seed_text(started_at)
        if text:
            return f"started_at={text}"
    label = seed_text(name)
    return f"name={label}" if label else ""


def given_test_name(
    name: object, *, kind: object = None, protocol_name: object = None, cell_labels: Iterable[object] = ()
) -> Optional[str]:
    """*name*, a test's name, when the caller gave it; ``None`` when BattINFO could have generated it.

    BattINFO titles an unnamed test after its cell and its protocol, or its
    kind when it has no protocol name (``C01 cycling``, or ``cycling`` alone
    when the cell has no name). Such a title restates the cell and the
    protocol, and depends on how the cell was referenced, so it never tells a
    run apart (:func:`test_identity_seed`). A name counts as generated when it
    is the protocol name, the kind (with or without underscores) or ``test``,
    alone or after one of *cell_labels* (the cell's name, serial number and
    batch) or ``cell``; case and spacing aside.
    """
    text = seed_text(name)
    if not text:
        return None
    kind_text = seed_text(getattr(kind, "value", kind))
    bases = {seed_text(protocol_name), kind_text, kind_text.replace("_", " "), "test"} - {""}
    labels = ({seed_text(label) for label in cell_labels} | {"cell"}) - {""}
    generated = bases | {f"{label} {base}" for label in labels for base in bases}
    return None if text.casefold() in {item.casefold() for item in generated} else text


def legacy_test_identity_seed(*, cell_id: object, kind: object, protocol_name: object, name: object) -> str:
    """The test identity seed of before 0.8.0, kept to find tests minted under it.

    ``cell IRI :: kind :: protocol name :: name``: the protocol name as
    written (``test`` without one), the cell, kind and name stripped, and
    ``test`` for a missing name. Hash it with :func:`legacy_stable_uid`;
    nothing new is minted from it.
    """
    protocol = protocol_name if isinstance(protocol_name, str) and protocol_name else "test"
    return "::".join(
        [
            _stripped(cell_id) or "unknown-cell",
            _stripped(kind) or "other",
            protocol,
            _stripped(name) or "test",
        ]
    )


def material_spec_identity_seed(
    *,
    manufacturer: str | None,
    product: str | None,
    grade: str | None = None,
    kind: str | None = None,
) -> str:
    """Identity seed for a material spec, shared by every minting surface.

    ``material-spec :: manufacturer :: product :: grade :: kind``: the
    manufacturer, the product (its product id, else its name) and the grade
    enter as :func:`seed_text`, lower-cased, so "Graphite" and "graphite" from
    one manufacturer are one spec; the kind as its canonical vocabulary key.
    Processing is not part of a material spec's identity.
    """
    return "::".join(
        [
            "material-spec",
            seed_text(manufacturer).lower() or "unknown-manufacturer",
            seed_text(product).lower() or "unknown-product",
            seed_text(grade).lower(),
            kind or "",
        ]
    )


def material_identity_seed(*, material_spec_id: str | None, lot: object) -> str:
    """Identity seed for a material lot: ``material :: spec IRI :: lot``, the lot as :func:`seed_text`."""
    return "::".join(["material", (material_spec_id or "").strip(), seed_text(lot)])


def electrode_spec_identity_seed(
    *,
    producer: str | None,
    product: str | None,
    grade: str | None = None,
    kind: str | None = None,
    route: str | None = None,
) -> str:
    """Identity seed for an electrode spec — shared by every minting surface.

    Mirrors the material-spec seed (producer, product, grade, kind) and adds the
    processing *route*. That addition is deliberate, not decoration: for an
    electrode the route is a DESIGN decision — an aqueous-processed electrode is a
    different spec from an NMP-processed one — so leaving it out would collapse
    two genuinely different designs onto one IRI and silently lose one of them.
    (A material lot's processing is the opposite: an instance property, and
    correctly absent from the material-spec seed.)

    Each part enters as :func:`seed_text`, lower-cased.
    """
    return "::".join(
        [
            "electrode-spec",
            seed_text(producer).lower() or "unknown-producer",
            seed_text(product).lower() or "unknown-product",
            seed_text(grade).lower(),
            seed_text(kind).lower(),
            seed_text(route).lower(),
        ]
    )


def electrode_identity_seed(
    *,
    electrode_spec_id: str | None,
    batch: str | None,
    parent_id: str | None = None,
    piece_id: str | None = None,
) -> str:
    """Identity seed for a physical electrode — (spec IRI, batch label), plus
    the genealogy coordinates for a cut piece.

    Mirrors the material-instance seed: re-authoring the same batch of the same
    design lands on the existing record instead of minting a duplicate. A piece
    cut from a parent (a roll, web, or strip) appends the parent IRI and its
    piece label, so disc-07 of one roll and disc-07 of another mint distinct
    IRIs — appended only when present, which keeps every pre-genealogy seed
    (and therefore every existing record IRI) byte-identical. The batch and
    piece labels enter as :func:`seed_text`.
    """
    parts = [
        "electrode",
        (electrode_spec_id or "").strip(),
        seed_text(batch),
    ]
    if parent_id and parent_id.strip():
        parts.append(parent_id.strip())
    piece = seed_text(piece_id)
    if piece:
        parts.append(piece)
    return "::".join(parts)


@dataclass(frozen=True)
class EntityKind:
    """Metadata describing one BattINFO record type.

    Attributes:
        entity_type: Canonical hyphenated identifier, e.g. ``"cell-spec"``,
            ``"material"``. Used as the logical type and the saved-file prefix.
        record_key: Top-level JSON key carrying the record body, e.g.
            ``"cell_spec"``, ``"material"``.
        schema_file: Path (relative to ``data/schemas``) of the JSON Schema.
        subdir: Directory name under a ``source_root`` where records live.
        iri_namespace: Path segment in the canonical IRI
            ``https://w3id.org/battinfo/<iri_namespace>/<uid>``.
        spec_ref_field: For an instance kind, the body field that links to its
            spec (e.g. ``"cell_spec_id"``); ``None`` for spec kinds.
        spec_entity_type: The ``entity_type`` that ``spec_ref_field`` points to.
        legacy_iri_namespaces: Namespaces this kind minted under before it
            moved to ``iri_namespace``. Nothing new mints there, but records
            minted there keep their IRIs, so lookups search them too.
        files_named_by_uid: Every record of this kind has only ever been
            written at :func:`save_entity_path` (its file named by its uid),
            so a lookup by IRI opens that one file rather than every file of
            the kind (:func:`entity_files_for_uid`).
    """

    entity_type: str
    record_key: str
    schema_file: str
    subdir: str
    iri_namespace: str
    spec_ref_field: Optional[str] = None
    spec_entity_type: Optional[str] = None
    legacy_iri_namespaces: tuple[str, ...] = ()
    files_named_by_uid: bool = False


# Registered in a deterministic order. Dispatch keys on ``record_key`` (unique),
# so ordering only affects iteration (e.g. record-set directory order).
ENTITY_KINDS: tuple[EntityKind, ...] = (
    EntityKind("cell-spec", "cell_spec", "cell-spec.schema.json", "cell-spec", "spec"),
    EntityKind(
        "cell",
        "cell_instance",
        "cell-instance.schema.json",
        "cell-instance",
        "cell",
        spec_ref_field="cell_spec_id",
        spec_entity_type="cell-spec",
    ),
    EntityKind("test-protocol", "test_spec", "test-protocol.schema.json", "test-protocol", "spec"),
    EntityKind("test", "test", "test.schema.json", "test", "test"),
    EntityKind("dataset", "dataset", "dataset.schema.json", "dataset", "dataset"),
    EntityKind("material-spec", "material_spec", "material-spec.schema.json", "material-spec", "spec"),
    EntityKind(
        "material",
        "material",
        "material.schema.json",
        "material",
        "material",
        spec_ref_field="material_spec_id",
        spec_entity_type="material-spec",
    ),
    EntityKind("electrode-spec", "electrode_spec", "electrode-spec.schema.json", "electrode-spec", "spec"),
    EntityKind(
        "electrode",
        "electrode",
        "electrode.schema.json",
        "electrode",
        "electrode",
        spec_ref_field="electrode_spec_id",
        spec_entity_type="electrode-spec",
    ),
    EntityKind("separator-spec", "separator_spec", "separator-spec.schema.json", "separator-spec", "spec"),
    EntityKind(
        "separator",
        "separator",
        "separator.schema.json",
        "separator",
        "separator",
        spec_ref_field="separator_spec_id",
        spec_entity_type="separator-spec",
    ),
    EntityKind(
        "current-collector-spec",
        "current_collector_spec",
        "current-collector-spec.schema.json",
        "current-collector-spec",
        "spec",
    ),
    EntityKind(
        "current-collector",
        "current_collector",
        "current-collector.schema.json",
        "current-collector",
        "current-collector",
        spec_ref_field="current_collector_spec_id",
        spec_entity_type="current-collector-spec",
    ),
    EntityKind("electrolyte-spec", "electrolyte_spec", "electrolyte-spec.schema.json", "electrolyte-spec", "spec"),
    EntityKind(
        "electrolyte",
        "electrolyte",
        "electrolyte.schema.json",
        "electrolyte",
        "electrolyte",
        spec_ref_field="electrolyte_spec_id",
        spec_entity_type="electrolyte-spec",
    ),
    EntityKind("housing-spec", "housing_spec", "housing-spec.schema.json", "housing-spec", "spec"),
    EntityKind(
        "housing",
        "housing",
        "housing.schema.json",
        "housing",
        "housing",
        spec_ref_field="housing_spec_id",
        spec_entity_type="housing-spec",
    ),
    EntityKind("equipment-spec", "equipment_spec", "equipment-spec.schema.json", "equipment-spec", "spec"),
    EntityKind(
        "equipment",
        "equipment",
        "equipment.schema.json",
        "equipment",
        "equipment",
        spec_ref_field="equipment_spec_id",
        spec_entity_type="equipment-spec",
    ),
    # Channels are instance-only (no channel-spec kind): flat IRIs, parent link
    # ``equipment_id`` lives in the record body, uid minted deterministically
    # from (equipment uid, index) — IDENTIFIER_POLICY 6.1.
    EntityKind("channel", "channel", "channel.schema.json", "channel", "channel"),
    # Parameter sets (claim batches and parameter files) are datasets, not
    # descriptions: nothing is ever an instance of one. They mint under
    # dataset/, which they share with dataset records (IDENTIFIER_POLICY 6.3),
    # so the namespace does not say which of the two an IRI names. The target
    # link (material_kind / material_spec_id / cell_spec_id) lives in the
    # record body; a claim batch's uid derives from (target, scope, name), a
    # parameter file's from its parameters_sha256. Parameter sets minted
    # before 2026-10-11 keep their spec/ IRIs (they are superseded, not moved).
    EntityKind(
        "parameter-set",
        "parameter_set",
        "parameter-set.schema.json",
        "parameter-set",
        "dataset",
        legacy_iri_namespaces=("spec",),
        files_named_by_uid=True,
    ),
    # Organizations are identity records (manufacturers, labs, publishers)
    # other records point at. Instance-only, minted under organization/; NEW
    # uids derive deterministically from the normalized name so re-creating
    # "A123 Systems" is idempotent (existing random-minted IRIs stay valid
    # forever).
    EntityKind("organization", "organization", "organization.schema.json", "organization", "organization"),
)


# Entity families that follow the generic component spec/instance pattern (reuse an
# existing embedded holder schema). Underscore identifiers; the generic API derives the
# hyphen IRI namespace via ``family.replace("_", "-")``.
#
# ``electrode`` is deliberately NOT here: it graduated to a first-class family with its
# own typed models, curated ``kind``, deterministic identity and emitter — the same
# promotion ``material`` had. Its records still live under the same registry entries
# above; only the generic authoring/emission plumbing no longer applies to it.
COMPONENT_FAMILIES: tuple[str, ...] = (
    "separator",
    "current_collector",
    "electrolyte",
    "housing",
)

ENTITY_BY_TYPE: dict[str, EntityKind] = {kind.entity_type: kind for kind in ENTITY_KINDS}
ENTITY_BY_RECORD_KEY: dict[str, EntityKind] = {kind.record_key: kind for kind in ENTITY_KINDS}


def kind_for_doc(doc: Mapping[str, object]) -> Optional[EntityKind]:
    """Return the :class:`EntityKind` whose ``record_key`` is present in *doc*."""
    for kind in ENTITY_KINDS:
        if isinstance(doc.get(kind.record_key), Mapping):
            return kind
    return None


def kind_for_type(entity_type: str) -> Optional[EntityKind]:
    """Return the :class:`EntityKind` for a logical ``entity_type``."""
    return ENTITY_BY_TYPE.get(entity_type)


def record_set_dirs() -> tuple[str, ...]:
    """On-disk subdirectory names for every registered record type."""
    return tuple(kind.subdir for kind in ENTITY_KINDS)


RESERVED_NAMESPACE_SEGMENTS = frozenset(
    {
        "id",
        "ontology",
        "vocab",
        "doc",
        "context",
        "resolver",
        "twin",
        "w3id",
        # Claimed by the ontology block in the upstream w3id.org .htaccess —
        # requests to these paths can never reach the record resolver.
        "raw",
        "inferred",
        "turtle",
        "latest",
        "source",
    }
)
_reserved_clash = RESERVED_NAMESPACE_SEGMENTS & {k.iri_namespace for k in ENTITY_KINDS}
if _reserved_clash:  # fail at import: a reserved segment can never become an entity namespace
    raise RuntimeError(f"reserved namespace segment(s) used by ENTITY_KINDS: {sorted(_reserved_clash)}")


def iri_namespace_map() -> dict[str, str]:
    """Map ``entity_type`` -> IRI namespace segment for registered kinds."""
    return {kind.entity_type: kind.iri_namespace for kind in ENTITY_KINDS}


def entity_types_for_namespace(namespace: str) -> list[str]:
    """Logical entity types whose records can have an IRI under *namespace*.

    Multiple kinds can share a namespace (``cell-spec`` and ``test-protocol``
    both use ``spec/``, ``dataset`` and ``parameter-set`` both use
    ``dataset/``). A kind that moved keeps its old records' IRIs, so it is
    listed under its legacy namespace too, after the kinds that mint there
    (``parameter-set`` under ``spec/``). Falls back to ``[namespace]`` when
    nothing matches, to preserve the previous best-effort lookup behavior.
    """
    matches = [kind.entity_type for kind in ENTITY_KINDS if kind.iri_namespace == namespace]
    matches += [kind.entity_type for kind in ENTITY_KINDS if namespace in kind.legacy_iri_namespaces]
    return matches or [namespace]


def entity_id_from_doc(doc: Mapping[str, object]) -> Optional[str]:
    """Return the canonical ``id`` from a record body, or ``None``."""
    kind = kind_for_doc(doc)
    if kind is None:
        return None
    body = doc.get(kind.record_key)
    if isinstance(body, Mapping) and isinstance(body.get("id"), str):
        return body["id"]
    return None


def save_entity_path(entity_type: str, uid: str, source_root: Path) -> Path:
    """Canonical on-disk path for a record of *entity_type* with *uid*.

    *uid* must be a dashed uid (:func:`is_dashed_uid`); anything else raises
    ``ValueError``. It is the end of a record's IRI, which a record file or a
    registry response supplies, and a value such as ``..\\..\\x`` would name a
    file outside *source_root*.
    """
    kind = ENTITY_BY_TYPE.get(entity_type)
    if kind is None:
        raise ValueError(f"Unsupported entity type for save path: {entity_type}")
    if not is_dashed_uid(uid):
        raise ValueError(
            f"Cannot name a {entity_type} file after {uid!r}: it is not a record uid. A uid is four "
            "groups of four characters (digits, and lower-case letters other than i, l, o and u) "
            "joined by dashes, such as pge5-wer6-2q82-v9k0."
        )
    return source_root / kind.subdir / f"{entity_type}-{uid}.json"


def iter_entity_files(entity_type: str, source_root: Path) -> list[Path]:
    """Sorted ``*.json`` files for *entity_type* under *source_root* (or empty)."""
    kind = ENTITY_BY_TYPE.get(entity_type)
    if kind is None:
        return []
    directory = source_root / kind.subdir
    if not directory.exists():
        return []
    return sorted(directory.glob("*.json"))


def entity_files_for_uid(entity_type: str, uid: str, source_root: Path) -> list[Path]:
    """The files a lookup of the *entity_type* record with *uid* opens, in order.

    The canonical path (:func:`save_entity_path`) first, when it exists. A
    record of most kinds may also sit under another file name (written by
    hand or by an older release), so every other file of the kind follows. A
    kind whose files are always named by uid (``files_named_by_uid``, the
    parameter sets) stops at the canonical path: it is searched under two
    namespaces (``dataset/`` and its legacy ``spec/``), and a miss in either
    must not load every one of its files.

    A *uid* that is not a dashed uid names no file of its own (see
    :func:`save_entity_path`), so no path is built from it; the other files
    of the kind are still listed.
    """
    kind = ENTITY_BY_TYPE.get(entity_type)
    if kind is None:
        raise ValueError(f"Unsupported entity type for save path: {entity_type}")
    expected = save_entity_path(entity_type, uid, source_root) if is_dashed_uid(uid) else None
    found = [expected] if expected is not None and expected.exists() else []
    if kind.files_named_by_uid:
        return found
    return found + [path for path in iter_entity_files(entity_type, source_root) if path != expected]
