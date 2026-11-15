"""Adopt the old form of a record IRI that the registry already holds.

The old form of a record IRI, ``https://w3id.org/battinfo/{segment}/{uid}``,
and its ``/id/1001/`` form are one record, and a record that exists keeps the
IRI it has (IRI ruling of 22 October 2026, decision 5; BIG-MAP/BattINFO#483).
A uid never depends on the base, so a folder that mints under ``/id/1001/``
gives a record published earlier in the old form the same uid under the other
form. Before anything is submitted to a registry or deposited, each IRI of the
``/id/1001/`` form is looked up in the registry (``GET
/resources/{segment}/{uid}``, :meth:`battinfo.registry.Registry.get`), which
matches on segment and uid and answers with the record's ``canonical_iri``.
An IRI the registry holds in the old form is adopted: every string that names
it is rewritten to the old form. Only those strings change, never a uid, so
a record that names an adopted one keeps its own IRI.

A record the registry holds, in either form, as ``superseded`` or
``withdrawn`` is not adopted: the record described here has the identity of
a retired one. The submission or deposit stops with :class:`RetiredIrisError`
before anything is rewritten or sent, and ``allow_unchecked_iris=True`` does
not lift it. An answer without a status, from an older registry, counts as
``published``.

A registry that cannot be asked stops the submission or deposit with
:class:`UncheckedIrisError`, which names the IRIs not checked, unless the
caller passes ``allow_unchecked_iris=True``. Only the registry's own answer
that it holds no such record counts as "not held": any other reply, such as a
404 from a wrong address or a proxy, leaves the IRI unchecked. A local build
that sends nothing, such as a publication package, asks only when it is given
a registry (:func:`adopt_model_iris`).
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import warnings
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, NamedTuple

from pydantic import BaseModel

from battinfo._jsonio import atomic_write_text
from battinfo.namespace import (
    BATTERY_GENOME_PREFIX,
    DEFAULT_RECORD_BASE,
    SEGMENT_PATTERN,
    UID_PATTERN,
    parse_record_iri,
    same_record,
)

__all__ = [
    "RetiredIrisError",
    "RetiredRecord",
    "UncheckedIrisError",
    "adopt_model_iris",
    "adopt_registry_iris",
    "adopted_iris",
    "adoption_lines",
    "minted_iris",
    "registry_url_or_default",
    "rewrite_files",
    "rewrite_iris",
    "rewrite_iris_in_place",
]

# An IRI of the /id/1001/ form anywhere in a string, not followed by more of a
# token (``{uid}-aaaa`` is no IRI of that uid).
_MINTED_IRI_RE = re.compile(re.escape(DEFAULT_RECORD_BASE) + rf"{SEGMENT_PATTERN}/{UID_PATTERN}(?![0-9a-z-])")
# Seconds to wait for the registry on each IRI, and how many are asked at once.
# The first lookup is tried once, so a registry that is down is reported
# within one timeout; the others are tried again once.
_LOOKUP_TIMEOUT = 45.0
_LOOKUP_WORKERS = 6
_PROBE_RETRIES = 0
_LOOKUP_RETRIES = 1
# The body of the registry's 404 for a record it does not hold
# (battinfo-registry, GET /resources/{resource_type}/{resource_id}).
_NOT_HELD = {"detail": "Resource not found."}
# The statuses of a record the registry no longer publishes (its ``status``
# field; the other is ``published``).
_RETIRED_STATUSES = frozenset({"superseded", "withdrawn"})


class UncheckedIrisError(RuntimeError):
    """A submission or deposit stopped because the registry could not be asked about some of its IRIs.

    *iris* lists them. Nothing was submitted or deposited.
    """

    def __init__(self, message: str, *, iris: Iterable[str]) -> None:
        super().__init__(message)
        self.iris = list(iris)


class RetiredRecord(NamedTuple):
    """The registry's answer for an IRI whose record it holds as superseded or withdrawn."""

    iri: str
    """The IRI the registry holds the record under, in either form."""
    status: str
    """``"superseded"`` or ``"withdrawn"``."""
    replaced_by: tuple[str, ...] = ()
    """The IRIs of the records that replace a superseded one, as the registry gives them."""


class RetiredIrisError(RuntimeError):
    """A submission or deposit stopped because the registry holds some of its records as superseded or withdrawn.

    *retired* maps each IRI minted here to the :class:`RetiredRecord` the
    registry answered, and *iris* lists those IRIs. Nothing was rewritten,
    submitted or deposited.
    """

    def __init__(self, message: str, *, retired: Mapping[str, RetiredRecord]) -> None:
        super().__init__(message)
        self.retired = dict(retired)
        self.iris = list(self.retired)


def _is_minted(iri: object) -> bool:
    parsed = parse_record_iri(iri)
    return parsed is not None and parsed.prefix == BATTERY_GENOME_PREFIX


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, BaseModel):
        for name in type(value).model_fields:
            yield from _strings(getattr(value, name, None))


def minted_iris(value: Any) -> set[str]:
    """Every record IRI of the ``/id/1001/`` form that *value* names.

    *value* is a string, such as the text of a file, a parsed JSON document,
    or a record model. An IRI followed by more, such as ``#described`` or a
    version, counts as the IRI.
    """
    found: set[str] = set()
    for text in _strings(value):
        if DEFAULT_RECORD_BASE in text:
            found.update(match.group(0) for match in _MINTED_IRI_RE.finditer(text) if _is_minted(match.group(0)))
    return found


def _rewrite_text(text: str, adopted: Mapping[str, str]) -> str:
    if DEFAULT_RECORD_BASE not in text:
        return text
    return _MINTED_IRI_RE.sub(lambda match: adopted.get(match.group(0), match.group(0)), text)


def rewrite_iris(value: Any, adopted: Mapping[str, str]) -> Any:
    """A copy of *value* in which each IRI of *adopted* is replaced by the IRI it maps to.

    *value* is a string or a parsed JSON document (mappings, lists and
    tuples). A string that only starts with the IRI, such as one with a
    ``#fragment``, is rewritten too. Parts that do not change are returned as
    they are.
    """
    if not adopted:
        return value
    if isinstance(value, str):
        return _rewrite_text(value, adopted)
    if isinstance(value, Mapping):
        return {key: rewrite_iris(item, adopted) for key, item in value.items()}
    if isinstance(value, list):
        return [rewrite_iris(item, adopted) for item in value]
    if isinstance(value, tuple):
        return tuple(rewrite_iris(item, adopted) for item in value)
    return value


def rewrite_iris_in_place(value: Any, adopted: Mapping[str, str]) -> None:
    """Replace each IRI of *adopted* in *value*, a record model, dict or list, where it is.

    For the records a session holds in memory, so the next save writes the
    adopted IRIs. Models nested in fields and shared between records are
    rewritten once.
    """
    if not adopted:
        return
    seen: set[int] = set()

    def rewritten(item: Any) -> Any:
        if isinstance(item, str):
            text = _rewrite_text(item, adopted)
            return item if text == item else text
        if isinstance(item, (BaseModel, dict, list)):
            visit(item)
            return item
        if isinstance(item, tuple):
            items = tuple(rewritten(part) for part in item)
            return item if items == item else items
        return item

    def visit(item: Any) -> None:
        if id(item) in seen:
            return
        seen.add(id(item))
        if isinstance(item, BaseModel):
            for name in type(item).model_fields:
                current = getattr(item, name, None)
                new = rewritten(current)
                if new is not current:
                    setattr(item, name, new)
        elif isinstance(item, dict):
            for key, current in list(item.items()):
                new = rewritten(current)
                if new is not current:
                    item[key] = new
        elif isinstance(item, list):
            for position, current in enumerate(item):
                new = rewritten(current)
                if new is not current:
                    item[position] = new

    visit(value)


def rewrite_files(paths: Iterable[Path], adopted: Mapping[str, str]) -> list[Path]:
    """Rewrite each IRI of *adopted* in the text files *paths*; return the files that changed.

    A file is read and written as UTF-8 text, and one that cannot be read is
    left as it is.
    """
    changed: list[Path] = []
    if not adopted:
        return changed
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        new = _rewrite_text(text, adopted)
        if new != text:
            atomic_write_text(path, new)
            changed.append(path)
    return changed


def adopted_iris(checked: Mapping[str, str]) -> dict[str, str]:
    """The IRIs of *checked* (as :func:`adopt_registry_iris` returns it) that were adopted, each mapped to its old form."""
    return {minted: held for minted, held in checked.items() if minted != held}


def _says_not_held(exc: urllib.error.HTTPError) -> bool:
    """True when *exc* is the registry's own 404 for a record it does not hold, not any 404."""
    if exc.code != 404:
        return False
    try:
        body = json.loads(exc.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - no body, or not the registry's: not its answer
        return False
    return body == _NOT_HELD


def _replacements(entry: Mapping[str, Any]) -> tuple[str, ...]:
    """The IRIs that replace a superseded record, from its entry's ``replaced_by_iris``, else ``replaced_by_iri``."""
    listed = entry.get("replaced_by_iris")
    if isinstance(listed, list) and listed:
        return tuple(item for item in listed if isinstance(item, str))
    single = entry.get("replaced_by_iri")
    return (single,) if isinstance(single, str) and single else ()


def _registry_answer(registry: Any, iri: str, *, retries: int = _LOOKUP_RETRIES) -> str | RetiredRecord | None:
    """The IRI to use for *iri*: the old form *registry* holds the record under, else *iri*.

    A :class:`RetiredRecord` when the registry holds the record as superseded
    or withdrawn; None when it could not be asked.
    """
    try:
        entry = registry.get(iri, retries=retries)
    except urllib.error.HTTPError as exc:
        return iri if _says_not_held(exc) else None
    except Exception:  # noqa: BLE001 - down, blocked or answering nonsense: the IRI stays unchecked
        return None
    held = entry.get("canonical_iri") if isinstance(entry, Mapping) else None
    if not isinstance(held, str):
        return None
    # The registry matches on segment and uid. It holds this record when its
    # IRI is this one or the other form of it; anything else leaves the IRI
    # as it was minted.
    if not same_record(held, iri):
        return iri
    # A record it no longer publishes is never adopted. An entry without a
    # status comes from a registry older than the field: it is published.
    status = entry.get("status")
    if status in _RETIRED_STATUSES:
        return RetiredRecord(held, status, _replacements(entry) if status == "superseded" else ())
    return held


def _retired_message(action: str, registry_url: str | None, retired: Mapping[str, RetiredRecord]) -> str:
    lines = []
    for minted, record in sorted(retired.items()):
        if record.replaced_by:
            what = f"superseded by {', '.join(record.replaced_by)}"
        else:
            what = record.status
        lines.append(f"  {minted}: the registry holds it as {record.iri}, which was {what}.")
    where = f"the registry at {registry_url}" if registry_url else "the registry"
    return (
        f"{action} stopped before anything was sent or written: {where} holds {len(retired)} "
        "record(s) named here as retired, so they cannot be published again.\n"
        + "\n".join(lines)
        + "\nEach of these records has the identity of the retired record. If it means the record that "
        "replaced it, refer to that record instead. If it is a new record, the fields that identify it "
        "must differ, so that it gets a uid of its own."
    )


def adopt_registry_iris(
    iris: Iterable[str],
    *,
    registry_url: str | None,
    action: str,
    allow_unchecked_iris: bool = False,
    answers: dict[str, str | RetiredRecord] | None = None,
) -> dict[str, str]:
    """Each IRI of the ``/id/1001/`` form among *iris*, mapped to the IRI to use for it.

    That is the old form when the registry at *registry_url* holds the record
    under it, and the IRI itself when the registry does not hold the record,
    or holds it under that IRI. Other IRIs are left out. *answers* holds what
    this registry already answered, in the same shape or as a
    :class:`RetiredRecord`, and is updated in place, so a caller asks about
    each IRI once.

    An IRI whose record the registry holds as superseded or withdrawn raises
    :class:`RetiredIrisError`, naming each such record and what replaced it,
    before anything is sent; *allow_unchecked_iris* does not lift it. An IRI
    the registry cannot be asked about, and every IRI when there is no
    *registry_url*, raises :class:`UncheckedIrisError`, naming them and
    *action* (the call, such as ``"ws.submit()"``), before anything is sent.
    With *allow_unchecked_iris* they map to themselves instead, with a
    warning. The first lookup is tried once, and a registry that does not
    answer it is not asked about the rest.
    """
    from battinfo.registry import Registry  # noqa: PLC0415

    wanted = sorted({iri for iri in iris if _is_minted(iri)})
    known = answers if answers is not None else {}
    checked = {iri: known[iri] for iri in wanted if iri in known}
    pending = [iri for iri in wanted if iri not in known]
    unchecked: list[str] = []
    if pending and registry_url is None:
        unchecked = pending
    elif pending:
        registry = Registry(registry_url, timeout=_LOOKUP_TIMEOUT)
        first = _registry_answer(registry, pending[0], retries=_PROBE_RETRIES)
        if first is None:
            unchecked = pending
        else:
            found: dict[str, str | RetiredRecord] = {pending[0]: first}
            rest = pending[1:]
            if rest:
                with ThreadPoolExecutor(max_workers=_LOOKUP_WORKERS) as pool:
                    for iri, answer in zip(rest, pool.map(lambda item: _registry_answer(registry, item), rest)):
                        if answer is None:
                            unchecked.append(iri)
                        else:
                            found[iri] = answer
            known.update(found)
            checked.update(found)
    # A retired record is a conflict, not a missing answer: it stops the call
    # whatever else could not be checked, and allow_unchecked_iris does not
    # lift it. *answers* keeps it, so asking again stops again.
    retired = {iri: answer for iri, answer in checked.items() if isinstance(answer, RetiredRecord)}
    if retired:
        raise RetiredIrisError(_retired_message(action, registry_url, retired), retired=retired)
    if unchecked:
        where = (
            f"the registry at {registry_url}"
            if registry_url
            else "a registry (none is configured: pass registry_url=... or set BATTINFO_REGISTRY_URL)"
        )
        listing = ", ".join(unchecked)
        if not allow_unchecked_iris:
            raise UncheckedIrisError(
                f"{action} stopped before anything was sent or written: {len(unchecked)} IRI(s) minted under "
                f"{DEFAULT_RECORD_BASE} could not be checked with {where}, which may hold the same "
                f"record under its old form, https://w3id.org/battinfo/{{segment}}/{{uid}}: {listing}. "
                "Run it again when the registry answers, or pass allow_unchecked_iris=True to go on "
                "with these IRIs as they are.",
                iris=unchecked,
            )
        warnings.warn(
            f"{action}: {len(unchecked)} IRI(s) minted under {DEFAULT_RECORD_BASE} were not checked with "
            f"{where} and are kept as they are (allow_unchecked_iris=True): {listing}.",
            stacklevel=3,
        )
        checked.update({iri: iri for iri in unchecked})
    # Every answer left names an IRI: a retired one raised above.
    return {iri: answer for iri, answer in sorted(checked.items()) if isinstance(answer, str)}


def registry_url_or_default(registry_url: str | None) -> str:
    """*registry_url*, else ``BATTINFO_REGISTRY_URL``, else the public registry, as :class:`battinfo.registry.Registry` takes them."""
    from battinfo.registry import DEFAULT_REGISTRY_URL  # noqa: PLC0415

    return (registry_url or os.environ.get("BATTINFO_REGISTRY_URL") or DEFAULT_REGISTRY_URL).rstrip("/")


def adopt_model_iris(
    models: Iterable[Any],
    *,
    registry_url: str | None,
    action: str,
    allow_unchecked_iris: bool = False,
    answers: dict[str, str | RetiredRecord] | None = None,
) -> dict[str, str]:
    """Adopt, in the record models *models*, the old form of each ``/id/1001/`` IRI the registry holds in it.

    For a publication package, which is built from models on this machine and
    sends nothing. It asks only when it is given a registry: *registry_url*,
    else ``BATTINFO_REGISTRY_URL``. Without one it asks nothing and adopts
    nothing. *answers* is passed on to :func:`adopt_registry_iris`. Returns
    the IRIs adopted, each mapped to its old form; the models are rewritten
    in place, unless a record is held as superseded or withdrawn, which
    raises :class:`RetiredIrisError` and leaves them as they were.
    """
    registry = registry_url or os.environ.get("BATTINFO_REGISTRY_URL")
    if not registry:
        return {}
    models = list(models)
    adopted = adopted_iris(
        adopt_registry_iris(
            minted_iris(models),
            registry_url=registry.rstrip("/"),
            action=action,
            allow_unchecked_iris=allow_unchecked_iris,
            answers=answers,
        )
    )
    for model in models:
        rewrite_iris_in_place(model, adopted)
    return adopted


def adoption_lines(adopted: Mapping[str, str]) -> list[str]:
    """The lines a summary prints for the IRIs *adopted*, empty when there are none."""
    if not adopted:
        return []
    return [
        f"  Adopted the old form the registry holds for {len(adopted)} record(s):",
        *(f"    {minted} -> {held}" for minted, held in sorted(adopted.items())),
    ]
