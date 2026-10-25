"""battinfo.workspace() — simplified authoring API.

Usage::

    import battinfo

    ws = battinfo.workspace("lab", registry_url=None)  # None: no registry lookups
    ws.search("duracell mn2400")  # with a registry, ws.load(hit) reuses a published spec
    ws.template("cell-spec", manufacturer="Duracell", model="MN2400",
                format="cylindrical", chemistry="alkaline-zn-mno2")
    # fill in the draft lab/Duracell-MN2400.cell-spec.json, then:
    spec = ws.load("Duracell-MN2400.cell-spec.json")
    ws.add("cell", spec=spec, serial_numbers=["MYLAB-MN2400-01", "MYLAB-MN2400-02"])  # serials only your lab uses
    ws.template("test-spec", name="CC discharge C/5", type="capacity_check")
    # fill in the draft lab/CC-discharge-C-5.test-spec.json, then:
    protocol = ws.load("CC-discharge-C-5.test-spec.json")
    ws.add("test", spec=protocol, cell="MYLAB-MN2400-01", instrument="NEWARE BTS82")
    ws.save()
"""

from __future__ import annotations

import builtins  # AuthoringWorkspace.list shadows the builtin in class-scope annotations
import copy
import difflib
import functools
import json
import os
import re
import warnings
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import datetime as _datetime

    from battinfo._workspace import Workspace

from battinfo._deposit_files import (
    DepositContext,
    DepositFile,
    DepositFilePlan,
    Omission,
    RemoteSource,
    UnsafeLocation,
    build_deposit_file_plan,
    dataset_distributions,
    deposit_file_problems,
    kept_copy_problems,
    location_key,
    location_path,
    measured_file,
    path_key,
)
from battinfo._deposit_index import (
    ZENODO_HOSTS,
    DepositIndexError,
    IndexedFile,
    concept_of_record,
    concept_records,
    load_deposit_index,
    load_deposit_state,
    note_deposit,
    note_hosted,
    note_published,
    register_sources,
    registered_keys,
    save_deposit_index,
    save_deposit_state,
    state_file,
    state_path,
    zenodo_environment,
)
from battinfo._fs_guard import remove_temp_tree
from battinfo._jsonio import atomic_write_text as _atomic_write_text
from battinfo._jsonio import chmod_owner_only as _chmod_owner_only
from battinfo._jsonio import read_json as _read_json
from battinfo._jsonio import write_private_text as _write_private_text
from battinfo._util import (
    _now_iso,
    is_dataset_series,
    is_local_location,
    is_real_number,
    local_file_references,
    path_name,
    url_segment,
)
from battinfo._util import file_uri_to_path as _file_uri_to_path
from battinfo._util import jsonld_literal as _jsonld_literal
from battinfo._util import jsonld_text as _jsonld_text
from battinfo._util import local_files_message as _local_files_message
from battinfo.canonical_aliases import migrate_quantity_values
from battinfo.entities import entity_id_from_doc, is_dashed_uid, kind_for_type, record_set_dirs, save_entity_path
from battinfo.namespace import BATTINFO_ROOT, record_base, record_iri

# Short-name pattern: 6 lowercase alphanumeric characters at the end of a
# dash-delimited name component (e.g. "666h1s" in "duracell-mn2400-2026-02-666h1s").
_SHORT_ID_RE = re.compile(r"-([a-z0-9]{6})(?:\.|$)")

# NEWARE server suffix in filenames: _<IP>-<instrument>-<channels>
_SERVER_RE = re.compile(r"_\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}-")

# ── Registry publication-intent mode tokens (shared contract with the registry) ──
# The registry is a CURATED INDEX, not a write-through store: submissions are
# STAGED by default — they land in the registry's review queue (status
# "validated") and a curator promotes them. Pass
# publication_mode=CANONICAL_PUBLICATION_MODE for the privileged immediate-publish
# path. STAGED_PUBLICATION_MODE is the token the registry accepts for staged
# submission (confirmed 2026-06-28) and is the single source of truth for the mode.
STAGED_PUBLICATION_MODE = "staged-publication"
CANONICAL_PUBLICATION_MODE = "canonical-publication"


class SubmitError(RuntimeError):
    """Raised when one or more records fail to submit (and ``allow_partial`` is False).

    Carries the structured outcome so a caller / CI / notebook can see exactly what
    happened instead of a misleading success: ``failed`` (records that errored or
    were rejected), ``submitted`` (records that reached the registry), and
    ``outcomes`` (every record's result).
    """

    def __init__(
        self,
        message: str,
        *,
        failed: list[dict] | None = None,
        outcomes: list[dict] | None = None,
    ) -> None:
        super().__init__(message)
        self.outcomes = outcomes or []
        self.failed = failed if failed is not None else [o for o in self.outcomes if not o.get("ok")]
        self.submitted = [o for o in self.outcomes if o.get("ok")]


# ── Template specs included for each cell format/chemistry ────────────────────
# Values are {"value": null, "unit": "<SI unit>"} — user fills in value.
_CYLINDRICAL_PRIMARY_SPECS: dict[str, dict] = {
    "nominal_voltage": {"value": None, "unit": "V"},
    "nominal_capacity": {"value": None, "unit": "Ah"},
    "discharging_cutoff_voltage": {"value": None, "unit": "V"},
    "mass": {"value": None, "unit": "g"},
    "diameter": {"value": None, "unit": "mm"},
    "height": {"value": None, "unit": "mm"},
    "maximum_continuous_discharging_current": {"value": None, "unit": "A"},
    "internal_resistance": {"value": None, "unit": "Ohm"},
    "minimum_discharging_temperature": {"value": None, "unit": "degC"},
    "maximum_discharging_temperature": {"value": None, "unit": "degC"},
    "minimum_storage_temperature": {"value": None, "unit": "degC"},
    "maximum_storage_temperature": {"value": None, "unit": "degC"},
}

# Coin cells: same shape as cylindrical (diameter + height), typically primary
_COIN_PRIMARY_SPECS: dict[str, dict] = {
    "nominal_voltage": {"value": None, "unit": "V"},
    "nominal_capacity": {"value": None, "unit": "Ah"},
    "discharging_cutoff_voltage": {"value": None, "unit": "V"},
    "mass": {"value": None, "unit": "g"},
    "diameter": {"value": None, "unit": "mm"},
    "height": {"value": None, "unit": "mm"},
    "maximum_continuous_discharging_current": {"value": None, "unit": "A"},
    "internal_resistance": {"value": None, "unit": "Ohm"},
    "minimum_discharging_temperature": {"value": None, "unit": "degC"},
    "maximum_discharging_temperature": {"value": None, "unit": "degC"},
    "minimum_storage_temperature": {"value": None, "unit": "degC"},
    "maximum_storage_temperature": {"value": None, "unit": "degC"},
}

# Prismatic / pouch cells: height + width + thickness (no diameter)
_PRISMATIC_SPECS: dict[str, dict] = {
    "nominal_voltage": {"value": None, "unit": "V"},
    "nominal_capacity": {"value": None, "unit": "Ah"},
    "discharging_cutoff_voltage": {"value": None, "unit": "V"},
    "mass": {"value": None, "unit": "g"},
    "height": {"value": None, "unit": "mm"},
    "width": {"value": None, "unit": "mm"},
    "thickness": {"value": None, "unit": "mm"},
    "maximum_continuous_discharging_current": {"value": None, "unit": "A"},
    "internal_resistance": {"value": None, "unit": "Ohm"},
    "minimum_discharging_temperature": {"value": None, "unit": "degC"},
    "maximum_discharging_temperature": {"value": None, "unit": "degC"},
    "minimum_storage_temperature": {"value": None, "unit": "degC"},
    "maximum_storage_temperature": {"value": None, "unit": "degC"},
}

_CYLINDRICAL_SECONDARY_SPECS: dict[str, dict] = {
    "nominal_voltage": {"value": None, "unit": "V"},
    "nominal_capacity": {"value": None, "unit": "Ah"},
    "charging_voltage": {"value": None, "unit": "V"},
    "discharging_cutoff_voltage": {"value": None, "unit": "V"},
    "mass": {"value": None, "unit": "g"},
    "diameter": {"value": None, "unit": "mm"},
    "height": {"value": None, "unit": "mm"},
    "nominal_continuous_charging_current": {"value": None, "unit": "A"},
    "maximum_continuous_charging_current": {"value": None, "unit": "A"},
    "nominal_continuous_discharging_current": {"value": None, "unit": "A"},
    "maximum_continuous_discharging_current": {"value": None, "unit": "A"},
    "specific_energy": {"value": None, "unit": "Wh/kg"},
    "energy_density": {"value": None, "unit": "Wh/L"},
    "cycle_life": {"value": None, "unit": "1"},
    "internal_resistance": {"value": None, "unit": "Ohm"},
    "minimum_charging_temperature": {"value": None, "unit": "degC"},
    "maximum_charging_temperature": {"value": None, "unit": "degC"},
    "minimum_discharging_temperature": {"value": None, "unit": "degC"},
    "maximum_discharging_temperature": {"value": None, "unit": "degC"},
    "minimum_storage_temperature": {"value": None, "unit": "degC"},
    "maximum_storage_temperature": {"value": None, "unit": "degC"},
}

# Primary chemistries
_PRIMARY_CHEMISTRIES = {"zn-mno2", "li-primary", "znmno2", "alkaline", "zinc-carbon"}


def _default_specs_for(format_: str, chemistry: str) -> dict[str, dict]:
    fmt = (format_ or "").lower()
    chem = (chemistry or "").lower()
    if fmt in ("prismatic", "pouch"):
        return dict(_PRISMATIC_SPECS)
    if fmt == "coin":
        return dict(_COIN_PRIMARY_SPECS)
    # cylindrical — primary vs secondary
    if chem in _PRIMARY_CHEMISTRIES:
        return dict(_CYLINDRICAL_PRIMARY_SPECS)
    return dict(_CYLINDRICAL_SECONDARY_SPECS)


def _cell_spec_property_keys() -> frozenset[str]:
    """The keys a cell spec's ``properties`` accept, read from its schema."""
    from battinfo.validate.schema import schema_for_rel_path  # noqa: PLC0415

    ref = schema_for_rel_path("cell-spec.schema.json")["properties"]["properties"]["$ref"]
    file_name, _, pointer = ref.partition("#")
    node: Any = schema_for_rel_path(file_name)
    for part in pointer.strip("/").split("/"):
        node = node[part]
    return frozenset(node.get("properties", {}))


def _short_id(name: str) -> str | None:
    """Extract the 6-char short ID from a batch name or filename stem."""
    m = _SHORT_ID_RE.search(name)
    return m.group(1) if m else None


# A short ID on its own: six characters of the UID alphabet (no i, l, o or u),
# such as "063b77". Only such a label is matched by short ID; any other label
# has to match a cell's serial number or name exactly, so "LAB-2025-000001"
# never binds "LAB-2024-000001" and "NMC-sample" never binds "LFP-sample".
_BARE_SHORT_ID_RE = re.compile(r"[0-9a-hjkmnp-tv-z]{6}")


def _is_short_id(token: str) -> bool:
    """True if *token* is a short ID on its own, not a label that ends in one."""
    return _BARE_SHORT_ID_RE.fullmatch(token) is not None


# Data-format suffixes a data file's name can carry before its extension, such
# as the .bdf in the <serial>.bdf.csv files ws.convert() writes. Only these come
# off after the extension when a file is matched to a cell, so a dot that is
# part of a serial number (S1.5.bdf.csv) stays.
_DATA_FILE_SUFFIXES = frozenset(
    {
        ".arrow",
        ".bdf",
        ".csv",
        ".dat",
        ".feather",
        ".gz",
        ".h5",
        ".hdf5",
        ".json",
        ".jsonld",
        ".mat",
        ".mpr",
        ".mpt",
        ".nda",
        ".ndax",
        ".parquet",
        ".res",
        ".tar",
        ".tsv",
        ".txt",
        ".xls",
        ".xlsx",
        ".zip",
    }
)


def _data_file_stems(name: str) -> builtins.list[str]:
    """The names a data file called *name* can name a cell by, longest first.

    The file name itself, then the name without its extension (the last
    suffix, when it has a letter in it), then without each data-format suffix
    before that (:data:`_DATA_FILE_SUFFIXES`), one at a time. So
    ``LAB-01.bdf.csv`` gives ``LAB-01.bdf`` and ``LAB-01``, while ``S1.6.csv``
    stops at ``S1.6`` and never gives ``S1``.
    """
    stems = [name]
    current = name
    while True:
        stem, dot, suffix = current.rpartition(".")
        if not dot or not stem.strip("."):
            return stems
        suffix = f".{suffix}".lower()
        is_extension = len(stems) == 1 and any(char.isalpha() for char in suffix)
        if not is_extension and suffix not in _DATA_FILE_SUFFIXES:
            return stems
        current = stem
        stems.append(current)


def _iri_short_id(iri: str | None) -> str | None:
    """The short ID of a record IRI: the first six characters of its UID."""
    tail = (iri or "").rstrip("/").rsplit("/", 1)[-1]
    return tail.replace("-", "")[:6] if is_dashed_uid(tail) else None


def _cells_named_by(
    label: str, cells: Sequence[tuple[builtins.list[str], str | None]], short_id: str | None
) -> builtins.list[int]:
    """Indexes of the cells *label* names, exact serial or name matches first.

    *cells* holds each cell's labels (its serial number and name) and its IRI. A
    cell with *label* among its labels matches. Only when none does is
    *short_id* tried: a cell matches when its IRI's short ID, or the short ID one
    of its labels ends in, equals it.
    """
    exact = [i for i, (labels, _) in enumerate(cells) if label in labels]
    if exact or not short_id:
        return exact
    return [
        i
        for i, (labels, iri) in enumerate(cells)
        if short_id == _iri_short_id(iri) or any(_short_id(text) == short_id for text in labels)
    ]


def _describe_session_cell(cell: Any) -> str:
    """One line naming a session cell: serial, name, spec and IRI."""
    serial = getattr(cell, "serial_number", None)
    name = getattr(cell, "name", None)
    spec = getattr(cell, "cell_spec_id", None) or getattr(getattr(cell, "cell_spec", None), "id", None)
    parts = [f"serial {serial!r}" if serial else "no serial"]
    if name and name != serial:
        parts.append(f"name {name!r}")
    if spec:
        parts.append(f"spec {spec}")
    parts.append(getattr(cell, "id", None) or "no IRI until ws.save()")
    return ", ".join(parts)


def _describe_registry_cell(hit: Mapping[str, Any]) -> str:
    """One line naming a registry cell: IRI, label, spec and publisher."""
    label = hit.get("title") or hit.get("serial_number") or hit.get("name") or "untitled"
    details = [str(label)]
    if hit.get("cell_spec_id"):
        details.append(f"spec {hit['cell_spec_id']}")
    publisher = hit.get("publisher_id")
    details.append(f"published by {publisher}" if publisher else "publisher not given")
    return f"{hit.get('id') or '(no IRI)'} ({', '.join(details)})"


# ── Resource-type vocabulary ──────────────────────────────────────────────────
# User-facing `type=` values map to the registry's canonical resource_type. Users
# speak "cell-spec"/"test-spec"; storage/IRIs keep cell_spec/test_protocol.
_RESOURCE_TYPE_CANON: dict[str, str] = {
    "cell-spec": "cell_spec",
    "cell_spec": "cell_spec",
    "cellspec": "cell_spec",
    "spec": "cell_spec",
    "cell": "cell",
    "cell-instance": "cell",
    "cell_instance": "cell",
    "instance": "cell",
    "test-spec": "test_protocol",
    "test_spec": "test_protocol",
    "test-protocol": "test_protocol",
    "test_protocol": "test_protocol",
    "test": "test",
    "dataset": "dataset",
    "datasets": "dataset",
}
# Canonical registry resource_type -> the user-facing label we surface in results.
_RESOURCE_TYPE_DISPLAY: dict[str, str] = {
    "cell_spec": "cell-spec",
    "cell": "cell",
    "test_protocol": "test-spec",
    "test": "test",
    "dataset": "dataset",
}


def _canon_type(value: str) -> str:
    """Map a user-facing ``type=`` value to the registry's canonical resource_type."""
    key = str(value).strip().lower()
    if key in _RESOURCE_TYPE_CANON:
        return _RESOURCE_TYPE_CANON[key]
    raise ValueError(f"Unknown type {value!r}. Valid: cell-spec, cell, test-spec, test, dataset.")


def _make_batch_key(stem: str) -> str:
    """Derive a normalised batch key from a NEWARE NDAX filename stem.

    Strips the server-IP + channel suffix, uppercases the org prefix, and
    lowercases the remainder, e.g.::

        "SINTEF___Duracell-mn2400-2026-02-tpejqj_127.0.0.1-BTS82-1-1-3-4"
        -> "SINTEF__duracell-mn2400-2026-02-tpejqj"
    """
    clean = _SERVER_RE.split(stem, maxsplit=1)[0]
    org_match = re.match(r"^([A-Za-z][A-Za-z0-9]*)", clean)
    org = org_match.group(1).upper() if org_match else ""
    remainder = re.sub(r"^[A-Za-z0-9]+_+", "", clean).lower()
    return f"{org}__{remainder}" if org else remainder


_CREDENTIALS_TEMPLATE = """\
# BattINFO workspace credentials - read by battinfo.workspace() when it opens this folder.
# Keep this out of version control (.battinfo/credentials is git-ignored for you).
#
# Quickest path: do NOT edit this file by hand - just run
#     ws.login(api_key="YOUR_KEY")
# which fills in your workspace and publisher automatically.
#
# Each name is looked up in this order, and the first value found is used:
#   1. an argument passed to the call, such as ws.zenodo(token=...)
#   2. a value ws.login() set on this workspace in this session
#   3. an environment variable of the same name
#   4. this file
#   5. the default, for the few names that have one
# The values here belong to this workspace. They are not copied into the
# environment, so other workspaces in the same Python session never see them.
# The workspace reads this file again when it changes, so an edit takes effect
# without reopening the workspace.
# A name set on more than one line takes the value of the last one.
# ws.credentials_status() shows which names are set and where each one comes
# from, without the values.

BATTINFO_API_KEY       =

# Filled in automatically by ws.login(); override only if you know you need to.
BATTINFO_WORKSPACE_ID  = battinfo-records
BATTINFO_PUBLISHER_ID  = battinfo-authoring
BATTINFO_ADMIN_TOKEN   =

# Optional - the registry this workspace talks to. Used when battinfo.workspace()
# gets no registry_url and the environment has no BATTINFO_REGISTRY_URL; empty
# means the production registry.
BATTINFO_REGISTRY_URL  =

# Optional - only needed for ws.upload() (Cloudflare R2 dataset storage).
# R2_BUCKET is the public bucket. ws.upload(public=False) uses R2_BUCKET_PRIVATE
# and never falls back to the public one.
R2_ENDPOINT            =
R2_ACCESS_KEY_ID       =
R2_SECRET_ACCESS_KEY   =
R2_BUCKET              = battinfo-public
R2_BUCKET_PRIVATE      =
R2_PUBLIC_BASE_URL     =

# Optional - only needed for ws.zenodo() archival.
ZENODO_API_TOKEN       =
ZENODO_SANDBOX_TOKEN   =
"""

_CREDENTIAL_PREFIXES = ("BATTINFO_", "R2_", "ZENODO_")

# Every credential and setting the workspace reads, in the order
# ws.credentials_status() reports them.
_CREDENTIAL_NAMES: tuple[str, ...] = (
    "BATTINFO_API_KEY",
    "BATTINFO_WORKSPACE_ID",
    "BATTINFO_PUBLISHER_ID",
    "BATTINFO_ADMIN_TOKEN",
    "BATTINFO_REGISTRY_URL",
    "R2_ENDPOINT",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET",
    "R2_BUCKET_PUBLIC",
    "R2_BUCKET_PRIVATE",
    "R2_PUBLIC_BASE_URL",
    "ZENODO_API_TOKEN",
    "ZENODO_SANDBOX_TOKEN",
)

# The ids login() and whoami() fall back to, the same as the setup() template's.
_DEFAULT_IDENTITY: dict[str, str] = {
    "BATTINFO_WORKSPACE_ID": "battinfo-records",
    "BATTINFO_PUBLISHER_ID": "battinfo-authoring",
}

# Where a credential came from, as ws.whoami() prints it. The keys are the
# sources ws.credentials_status() reports, in lookup order.
_CREDENTIAL_SOURCE_TEXT = {
    "argument": "passed as an argument",
    "login": "set by ws.login() in this session",
    "environment": "from the environment",
    "credentials_file": "from .battinfo/credentials",
    "default": "the default",
}


class _Unset:
    """The default of an argument the caller left out."""

    def __repr__(self) -> str:
        return "<default>"


# battinfo.workspace(registry_url=...) left out: BATTINFO_REGISTRY_URL from the
# environment, then from the workspace's .battinfo/credentials, then the
# production registry, looked up at each use. Typed Any so it can stand as the
# default of a str | None.
_UNSET: Any = _Unset()


def _read_credentials_file(path: Path) -> dict[str, str]:
    """Parse the BATTINFO_*, R2_* and ZENODO_* ``key = value`` lines of *path*.

    Returns an empty dict when the file does not exist. Comments, blank lines,
    empty values and names with other prefixes are skipped, and a name set on
    more than one line takes the last value (``_set_credentials`` leaves one line
    for each name it writes). Nothing is written to ``os.environ``: the values
    belong to the workspace that reads the file.
    """
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if any(key.startswith(p) for p in _CREDENTIAL_PREFIXES) and value:
            values[key] = value
    return values


def _find_records_repo(root: Path) -> Path | None:
    """Locate the battinfo-records repository from common relative positions."""
    env = os.environ.get("BATTINFO_RECORDS")
    if env:
        p = Path(env)
        if p.exists():
            return p

    candidates = []
    for depth in (1, 2):
        try:
            candidates.append(root.parents[depth] / "battinfo-records")
        except IndexError:
            pass  # shallow path (e.g. a drive root) — fewer ancestors than expected
    candidates.append(root.parent / "battinfo-records")
    candidates.append(root / "battinfo-records")
    for c in candidates:
        if (c / "records").exists():
            return c
    return None


# Conformance verdict → W3C EARL outcome IRI (compact CURIE; the 'earl' prefix is
# in the JSON-LD context). Boolean verdict: passed / failed; "unknown" = not
# assessed (EARL cantTell), used as the fallback for any unrecognised status.
_CONFORMANCE_IRI = {
    "conformant": "earl:passed",
    "non-conformant": "earl:failed",
    "unknown": "earl:cantTell",
}


def _spdx_algorithm_name(checksum: Any) -> str | None:
    """Read the algorithm back out of an emitted ``spdx:Checksum`` node.

    The term may be an IRI reference (``{"@id": "spdx:checksumAlgorithm_md5"}``),
    the same CURIE as a bare string, or a plain algorithm name for something SPDX
    does not define — all three are accepted, so a deposit round-trips whichever
    emitter wrote it.
    """
    if not isinstance(checksum, Mapping):
        return None
    term = checksum.get("spdx:checksumAlgorithm") or checksum.get("spdx:algorithm")
    if isinstance(term, Mapping):
        term = term.get("@id")
    if not isinstance(term, str) or not term.strip():
        return None
    return term.rsplit("checksumAlgorithm_", 1)[-1].strip() or None


_UNIX_EPOCH = "1970-01-01T00:00:00Z"

# Filename for the consolidated linked-data document in a Zenodo deposit. Uses a plain
# ``.json`` extension (not ``.jsonld``) so it previews inline in the Zenodo web viewer;
# the content is still JSON-LD (carries @context/@graph).
BATTINFO_LD_FILENAME = "battinfo.json"
# Legacy name in records published before the switch — still accepted on import.
BATTINFO_LD_FILENAME_LEGACY = "battinfo.jsonld"
# The RO-Crate metadata file a workspace deposit carries next to it.
_ROCRATE_FILENAME = "ro-crate-metadata.json"

# Battery Data Format (BDF) CSVW table schema. A BDF data file declares
# conformance to this so a consumer can resolve every column name, type and unit
# from one link instead of a per-record data dictionary. The VERSIONED IRI is
# used deliberately: an archived deposit must keep pointing at the exact schema
# version it was built against (the floating `.../schema` IRI tracks latest).
BDF_TABLE_SCHEMA_IRI = "https://w3id.org/battery-data-alliance/ontology/battery-data-format/1.2.0/schema"

# Loaded once at import time; used as the base for all JSON-LD context dicts.
# The versioned hosted context is the one authority — inline embedding must
# expand identically to the published URL (the flat assembled context has
# carried stale IRIs; see the 0.8.0 review, F4).
_RECORDS_CONTEXT: dict = json.loads(
    (Path(__file__).parent / "data" / "context" / "records.context.v1.json").read_text(encoding="utf-8")
)["@context"]


def validate_jsonld(doc: dict, *, where: str = "battinfo.json") -> dict:
    """Assert that ``doc`` is syntactically valid JSON-LD, returning it unchanged.

    Runs the document through a strict JSON-LD 1.1 processor (``pyld``) via
    ``expand()`` — the same engine the JSON-LD Playground uses — so any context
    or node error surfaces here, at generation time, instead of after publishing.

    Raises :class:`ValueError` with a human-readable message (including the
    offending IRI/term when the processor reports one) if the document is invalid.
    """
    from pyld import jsonld as _jsonld  # hard dependency (see pyproject)

    try:
        _jsonld.expand(doc)
    except Exception as exc:  # pyld raises jsonld.JsonLdError (and subclasses)
        detail = ""
        details = getattr(exc, "details", None)
        if isinstance(details, dict):
            culprit = details.get("iri") or details.get("term") or details.get("property")
            if culprit:
                detail = f" (offending term/IRI: {culprit})"
        raise ValueError(
            f"Generated {where} is not valid JSON-LD: {exc}{detail}. "
            "This document would be rejected by strict JSON-LD processors "
            "(e.g. the JSON-LD Playground); refusing to publish it."
        ) from exc
    return doc


def _unix_to_iso(ts: int | float | str | None, *, what: str = "a timestamp") -> str | None:
    """An ISO 8601 UTC datetime for a Unix time in seconds.

    A string of digits is read as seconds, and any other string is returned
    as it is: a time a record gives in ISO 8601 (a deviation's
    ``occurred_at`` may be one) needs no conversion. A number no date can be
    made of, such as a time in milliseconds (past the year 9999 as seconds),
    gives ``None`` with a warning that names *what* it is, so a graph leaves
    the time out rather than the record that holds it. Validation under the
    strict policy reports such a time (``semantic.timestamp_out_of_range``).
    """
    if ts is None or isinstance(ts, bool):
        return None
    if isinstance(ts, str):
        text = ts.strip()
        if not text.isdigit():
            return text or None
        ts = int(text)
    import datetime

    try:
        moment = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc) + datetime.timedelta(seconds=ts)
    except (OverflowError, ValueError):
        warnings.warn(
            f"{what} = {ts!r} is out of range as a Unix time in seconds (is it in milliseconds?), so it is left out.",
            stacklevel=2,
        )
        return None
    except TypeError:
        warnings.warn(
            f"{what} = {ts!r} is neither a Unix time nor an ISO 8601 string, so it is left out.",
            stacklevel=2,
        )
        return None
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _given_run_period(started_at: Any, ended_at: Any) -> tuple[int | None, int | None]:
    """The start and end of a run passed to ``ws.add("test")``, in Unix seconds (``None`` when not given).

    Raises ``ValueError`` for a value that is not a time, and for an end before the start.
    """
    from battinfo.api._shared import _to_unix_time  # noqa: PLC0415

    times: dict[str, int | None] = {}
    for keyword, value in (("started_at", started_at), ("ended_at", ended_at)):
        unix = _to_unix_time(value) if value is not None else None
        if value is not None and unix is None:
            raise ValueError(
                f"{keyword}={value!r} is not a time. Pass Unix seconds, an ISO 8601 time such as "
                "'2026-10-01T09:00:00Z' (read as UTC without an offset) or a datetime."
            )
        times[keyword] = unix
    start, end = times["started_at"], times["ended_at"]
    if start is not None and end is not None and end < start:
        raise ValueError(f"ended_at={ended_at!r} is before started_at={started_at!r}.")
    return start, end


def _plan_zenodo_deposit(
    existing_id: str | None,
    existing_published: bool,
    record_id: str | None,
    *,
    recorded_in: str = ".battinfo/zenodo.json",
) -> tuple[str | None, str | None, str | None]:
    """Decide how a ``ws.zenodo()`` call maps to a Zenodo deposit action.

    Re-running ``zenodo()`` on a workspace that already has a record should *not*
    error — it should continue the obvious next step, with a warning:

    * explicit ``record_id`` given, or no record yet  → use it as-is (caller forks a
      new version when a record_id is set, or creates a brand-new record otherwise);
    * existing record is **published**  → fork a NEW VERSION from it;
    * existing record is an **open draft**  → UPDATE that draft in place (Zenodo allows
      only one open draft per concept, so forking again would fail).

    *recorded_in* is the file that records the existing record, named in the
    warning.

    Returns ``(record_id, reuse_draft_id, warning)`` — exactly one of
    ``record_id``/``reuse_draft_id`` is set when versioning an existing record;
    ``warning`` is a user-facing message or None.
    """
    if record_id is not None or not existing_id:
        return record_id, None, None
    if existing_published:
        return (
            existing_id,
            None,
            (
                f"This workspace already has a published Zenodo record ({existing_id}); "
                f"creating a NEW VERSION. (Delete {recorded_in} to start a "
                "brand-new record instead.)"
            ),
        )
    return (
        None,
        existing_id,
        (
            f"This workspace already has an unpublished draft ({existing_id}); updating "
            "that draft in place rather than creating a new record."
        ),
    )


def _unreadable_draft_message(state: Mapping[str, Any], exc: Exception) -> str:
    """The refusal of a deposit whose recorded draft (*state*) Zenodo did not return, with how to go on.

    A draft deleted on the Zenodo website (HTTP 404 or 410) does not take
    the record's lineage with it. When the draft was a new version of a
    published record, the way on is a new version of that record
    (``record_id=``), never a new record. Only when nothing of the record
    was published does the message point at the state file, whose deletion
    starts a new record on that Zenodo alone.
    """
    environment = str(state.get("environment") or "production")
    text = (
        f"The draft {state['record_id']} recorded in {state_file(environment)} could not be read "
        f"on {ZENODO_HOSTS[environment]}: {exc}"
    )
    if getattr(exc, "status", None) in (404, 410):
        published = state.get("version_of")
        if published:
            text += (
                f" If it was deleted there, run ws.zenodo(record_id={published!r}) to make a new "
                f"version of the published record {published}, which the draft was a version of."
            )
        else:
            text += (
                " If it was deleted there, nothing of its record was published: delete "
                f"{state_file(environment)} to start a new record on {ZENODO_HOSTS[environment]}."
            )
    return f"{text} Nothing was created on Zenodo."


#: How a deposit refusal tells the user to give a dataset its local data file back.
_POINT_AT_LOCAL_FILE = "Point each dataset at its local file again (ws.add(..., data=...), then ws.save())"


def _kept_copies_refusal(
    plan: DepositFilePlan, datasets: Iterable[object], lacking: Mapping[str, str], holder: str
) -> str:
    """The refusal of a deposit that keeps copies *holder* does not hold, naming each dataset that points at one.

    *lacking* maps each such file's deposit name to what is wrong, as
    :func:`~battinfo._deposit_files.kept_copy_problems` gives it, and
    *datasets* are the dataset records the deposit read.
    """
    lines: builtins.list[str] = []
    named: set[str] = set()
    for record in datasets:
        body = record.get("dataset") if isinstance(record, dict) else None
        if not isinstance(body, dict):
            continue
        usable, _problems = dataset_distributions(body)
        for dist in usable:
            entry = plan.entry_for(dist["content_url"])
            if entry is None or not entry.kept or entry.name not in lacking:
                continue
            lines.append(
                f"dataset {body.get('id') or '(no id)'}: {dist['content_url']} ({entry.name} {lacking[entry.name]})"
            )
            named.add(entry.name)
    lines += [f"{name} {problem}" for name, problem in lacking.items() if name not in named]
    return (
        f"Refusing to deposit: {holder} does not hold {len(lacking)} data file(s) that the dataset "
        "records point at and for which this workspace has no local file to send: "
        + "; ".join(dict.fromkeys(lines))
        + f". {_POINT_AT_LOCAL_FILE}, then re-run."
    )


def _deposit_record_iris(record_sets: Mapping[str, list[dict]], graph: Mapping[str, Any]) -> list[str]:
    """The IRIs of the workspace records the deposit *graph* has a node for, sorted."""
    nodes = graph.get("@graph")
    node_ids = {node.get("@id") for node in nodes if isinstance(node, dict)} if isinstance(nodes, list) else set()
    iris = {
        entity_id_from_doc(record) for records in record_sets.values() for record in records if isinstance(record, dict)
    }
    return sorted(iri for iri in iris if iri and iri in node_ids)


def _with_citation_doi(record: dict, doi: str | None) -> dict:
    """*record* with ``provenance.citation_doi`` set to *doi* when it has none; *record* itself without a DOI."""
    if not doi:
        return record
    provenance = dict(record.get("provenance") or {})
    provenance.setdefault("citation_doi", doi)
    return {**record, "provenance": provenance}


def _bdf_measurement_period(csv_path: "str | Path") -> tuple[int, int] | None:
    """Return ``(start_unix, end_unix)`` for a BDF CSV from its ``unix_time_second``
    column (first and last data rows), or None if unavailable. The end row is read by
    seeking the tail, so this is cheap even for multi-hundred-MB files."""
    try:
        path = Path(csv_path)
        if not path.is_file():
            return None
        with path.open(encoding="utf-8") as fh:
            header = fh.readline().rstrip("\n").split(",")
            if "unix_time_second" not in header:
                return None
            col = header.index("unix_time_second")
            first_line = fh.readline().rstrip("\n")
        if not first_line:
            return None
        start = int(float(first_line.split(",")[col]))
        size = path.stat().st_size
        with path.open("rb") as fb:
            fb.seek(max(0, size - 8192))
            tail = fb.read().decode("utf-8", "ignore").splitlines()
        last = next((ln for ln in reversed(tail) if ln.strip() and "," in ln), "")
        end = int(float(last.split(",")[col])) if last else start
        # Plausibility gate: epochs outside 2000..2100 are converter garbage
        # (batterydf 0.1.0 emitted epoch/1000 - a 1970 date on a citable record
        # is worse than no date). Warn and withhold rather than stamp it.
        if not (946684800 <= start <= 4102444800):
            print(
                f"  warning: {path.name} unix_time_second={start} is implausible "
                "(outside 2000-2100) - not stamping test/dataset times from it. "
                "Known cause: batterydf<0.2 wrote epoch/1000; upgrade the converter "
                '(pip install "battinfo[processing]") and re-run ws.convert().'
            )
            return None
        return (start, end) if end >= start else (end, start)
    except Exception:
        return None


def _distribution_file_name(url: str) -> str:
    """The file name a distribution URL ends in, decoded, for display.

    A hosted URL carries its file name percent-encoded (``cell%2001.csv``);
    the name shown in the graph is the decoded one (``cell 01.csv``). A URL
    that cannot be parsed gives the text after its last ``/``.
    """
    try:
        if url.startswith(("http://", "https://")):
            from urllib.parse import unquote, urlparse  # noqa: PLC0415

            return unquote(urlparse(url).path.rsplit("/", 1)[-1])
        return path_name(_file_uri_to_path(url))
    except (OSError, ValueError):
        return url.rstrip("/").rsplit("/", 1)[-1]


def _import_web_url(value: Any) -> str:
    """*value* when it is an http(s) URL with a host, as text or as ``{"@id": ...}``; else ``""``.

    ``ws.import_()`` keeps a URL from the document it reads only when this
    returns it.
    """
    from urllib.parse import urlparse  # noqa: PLC0415

    if isinstance(value, Mapping):
        value = value.get("@id")
    if not isinstance(value, str):
        return ""
    text = value.strip()
    try:
        parsed = urlparse(text)
    except ValueError:
        return ""
    return text if parsed.scheme.lower() in ("http", "https") and parsed.netloc else ""


# dcat:mediaType is written as the IANA media-type IRI under this base
# (text/csv -> https://www.iana.org/assignments/media-types/text/csv).
_IANA_MEDIA_TYPES = "https://www.iana.org/assignments/media-types/"


def _media_type_from_jsonld(value: Any) -> str:
    """A distribution's media type, from either shape a deposit writes it in.

    The inverse of the emitter: ``{"@id": <IANA media-type IRI>}`` (or the IRI
    as a string) gives the media type it names, and a plain string such as
    ``"text/csv"`` (older deposits) is returned as it is. Any other IRI is not
    guessed at and gives ``""``.
    """
    if isinstance(value, Mapping):
        value = value.get("@id")
    if not isinstance(value, str):
        return ""
    if value.startswith(_IANA_MEDIA_TYPES):
        return value[len(_IANA_MEDIA_TYPES) :]
    return "" if value.startswith(("http://", "https://")) else value


def _warn_text_moved(source: str, notes: Iterable[str]) -> None:
    """Warn that text read from a quantity's ``value`` moved to ``value_text``.

    *notes* come from ``migrate_quantity_values``; nothing is said when it is empty.
    """
    lines = list(notes)
    if lines:
        warnings.warn(
            f"{source} held text in a quantity's value, which takes a number only from 0.8.0 on: {'; '.join(lines)}.",
            stacklevel=3,
        )


def _typed_date(value: "str | int | float") -> dict:
    """Wrap a date value as a typed JSON-LD value so consumers can parse it.

    Records store dates as Unix timestamps (int); those become xsd:date in UTC.
    For strings, picks the xsd datatype from the shape: ``YYYY`` → gYear,
    ``YYYY-MM`` → gYearMonth, an ISO timestamp → dateTime, else date.
    """
    if isinstance(value, (int, float)):
        import datetime as _dt  # noqa: PLC0415

        day = _dt.datetime.fromtimestamp(value, tz=_dt.timezone.utc).date().isoformat()
        return {"@value": day, "@type": "xsd:date"}
    v = (value or "").strip()
    if len(v) == 4 and v.isdigit():
        datatype = "xsd:gYear"
    elif len(v) == 7 and v[4] == "-":
        datatype = "xsd:gYearMonth"
    elif "T" in v:
        datatype = "xsd:dateTime"
    else:
        datatype = "xsd:date"
    return {"@value": v, "@type": datatype}


def _agent_node(c: dict) -> dict:
    """Build a schema.org Person node (also typed prov:Agent) for a creator/contributor.

    Uses the ORCID as the node @id when present so the agent is globally identifiable.
    """
    node: dict = {"@type": ["schema:Person", "prov:Agent"], "schema:name": c.get("name", "")}
    if c.get("orcid"):
        node["@id"] = f"https://orcid.org/{c['orcid']}"
    if c.get("affiliation"):
        org: dict = {"@type": "schema:Organization", "schema:name": c["affiliation"]}
        # ROR gives the organisation a globally-resolvable identifier.
        if c.get("affiliation_ror"):
            org["@id"] = _ror_url(c["affiliation_ror"])
        node["schema:affiliation"] = org
    if c.get("type"):
        node["schema:roleName"] = c["type"]
    return node


def _ror_url(ror: str) -> str:
    """Normalise a ROR id (bare id or URL) to its canonical https://ror.org/ URL."""
    ror = str(ror).strip()
    return ror if ror.startswith("http") else f"https://ror.org/{ror.rsplit('/', 1)[-1]}"


def _agent_from_record_contributor(c: dict) -> dict:
    """Map a record's stamped ``contributor`` Person dict to the ``_agent_node``
    input shape ``{name, orcid, affiliation}``.

    Record contributors carry the ORCID in ``same_as`` and the affiliation as a
    nested ``Organization``; the publication emitter's agent builder wants the bare
    ORCID and a plain affiliation name.
    """
    same_as = str(c.get("same_as") or "")
    tail = same_as.rstrip("/").rsplit("/", 1)[-1]
    orcid = tail if _ORCID_RE.match(tail) else None
    affiliation = c.get("affiliation")
    if isinstance(affiliation, dict):
        affiliation = affiliation.get("name")
    out: dict = {"name": c.get("name", "")}
    if orcid:
        out["orcid"] = orcid
    if affiliation:
        out["affiliation"] = affiliation
    return out


# ── Funding / project provenance ─────────────────────────────────────────────
# A workspace may be tagged with one funding project (e.g. an EU grant agreement
# number such as 101103997).  The grant *identifier* is authoritative and stored
# verbatim; descriptive fields (title, funder, programme) are resolved lazily
# from OpenAIRE and cached, so the common case is just ``ws.project("101103997")``.
_OPENAIRE_PROJECTS_API = "https://api.openaire.eu/search/projects"
_CORDIS_PROJECT_URL = "https://cordis.europa.eu/project/id/{}"


def _is_eu_grant(identifier: str) -> bool:
    """Heuristic: EU Framework Programme grant agreement numbers are 6-9 digits."""
    return identifier.isdigit() and 6 <= len(identifier) <= 9


@dataclass
class ProjectRef:
    """A funding project (grant) attached to a workspace and its records."""

    identifier: str
    name: str | None = None
    funder: str | None = None
    program: str | None = None
    acronym: str | None = None
    id: str | None = None  # resolvable IRI (CORDIS project page for EU grants)
    resolved: bool = False  # True once remote enrichment has been attempted
    manual: list[str] = field(default_factory=list)  # fields set by hand, kept on refresh

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectRef":
        return cls(
            identifier=str(data.get("identifier") or "").strip(),
            name=data.get("name"),
            funder=data.get("funder"),
            program=data.get("program"),
            acronym=data.get("acronym"),
            id=data.get("id"),
            resolved=bool(data.get("resolved", False)),
            manual=list(data.get("manual") or []),
        )

    def to_dict(self) -> dict:
        out: dict[str, Any] = {"identifier": self.identifier}
        for key in ("name", "funder", "program", "acronym", "id"):
            value = getattr(self, key)
            if value:
                out[key] = value
        out["resolved"] = self.resolved
        if self.manual:
            out["manual"] = sorted(self.manual)
        return out

    def default_iri(self) -> str | None:
        """Canonical resolvable IRI for the grant (CORDIS page for EU numbers)."""
        if _is_eu_grant(self.identifier):
            return _CORDIS_PROJECT_URL.format(self.identifier)
        return None

    def funding_block(self) -> dict:
        """Record-level ``funding`` block (maps to schema:funding/Grant in JSON-LD)."""
        block: dict[str, Any] = {"type": "Grant", "identifier": self.identifier}
        iri = self.id or self.default_iri()
        if iri:
            block["id"] = iri
        if self.name:
            block["name"] = self.name
        if self.acronym:
            block["acronym"] = self.acronym
        if self.funder:
            block["funder"] = {"type": "Organization", "name": self.funder}
        if self.program:
            block["program"] = self.program
        return block

    def summary(self) -> str:
        """One-line human description, e.g. ``DigiBatt (101103997)``."""
        label = self.acronym or self.name
        return f"{label} ({self.identifier})" if label else self.identifier


_ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")


def _normalize_orcid(value: str) -> str:
    """Return the bare ORCID id (``0000-0002-1825-0097``) from an id or full URL."""
    token = str(value).strip()
    token = re.sub(r"^https?://orcid\.org/", "", token, flags=re.IGNORECASE).rstrip("/")
    token = token.upper()
    if not _ORCID_RE.match(token):
        raise ValueError(
            f"invalid ORCID iD: {value!r}. Expected 0000-0002-1825-0097 (or the full https://orcid.org/… URL)."
        )
    return token


# How to give a Zenodo deposit its creators: the refusal and the preview say it.
_CREATORS_HINT = (
    'Pass creators=[{"name": "Family, Given", "orcid": "0000-0002-1825-0097"}], or credit '
    'each author once with ws.contributor("0000-0002-1825-0097", name="Family, Given"), '
    'or set a default with: battinfo config set creator "Family, Given; Institution".'
)


def _deposit_agents(agents: Iterable[Any], role: str) -> list[dict]:
    """Copies of a deposit's creator or contributor dicts, each ORCID a bare id.

    An ORCID may be given as the id or as its ``https://orcid.org/`` (or
    ``http://``) URL. Zenodo takes the bare id, and the deposit graph and the
    RO-Crate put ``https://orcid.org/`` in front of it once. Raises
    ValueError, naming the *role* and the entry, for an entry that is not a
    dict with a name, or an ORCID that is not one.
    """
    out: list[dict] = []
    for position, agent in enumerate(agents, start=1):
        if not isinstance(agent, Mapping) or not str(agent.get("name") or "").strip():
            raise ValueError(
                f"{role} {position} has no name. Give each {role} as a dict such as "
                '{"name": "Family, Given", "orcid": "0000-0002-1825-0097"}.'
            )
        entry = dict(agent)
        if entry.get("orcid"):
            try:
                entry["orcid"] = _normalize_orcid(entry["orcid"])
            except ValueError as exc:
                raise ValueError(f"{role} {entry['name']!r}: {exc}") from None
        else:
            entry.pop("orcid", None)  # an empty ORCID is left out
        out.append(entry)
    return out


# A pragmatic set of the license identifiers Zenodo accepts most often (open
# data + common software licenses), lower-cased for comparison. This is a
# recognition list, not a hard allowlist: an unknown identifier is kept verbatim
# with a warning (see _normalize_license) so a valid-but-unlisted SPDX id is
# never rejected.
_KNOWN_LICENSES: frozenset[str] = frozenset(
    {
        "cc-by-4.0",
        "cc-by-sa-4.0",
        "cc-by-nc-4.0",
        "cc-by-nc-sa-4.0",
        "cc-by-nd-4.0",
        "cc-by-nc-nd-4.0",
        "cc-by-3.0",
        "cc-by-sa-3.0",
        "cc0-1.0",
        "cc-pddc",
        "pddl-1.0",
        "odbl-1.0",
        "odc-by-1.0",
        "mit",
        "apache-2.0",
        "bsd-2-clause",
        "bsd-3-clause",
        "gpl-2.0",
        "gpl-2.0-only",
        "gpl-3.0",
        "gpl-3.0-only",
        "gpl-3.0-or-later",
        "lgpl-2.1",
        "lgpl-3.0",
        "agpl-3.0",
        "mpl-2.0",
    }
)


def _normalize_license(value: str) -> tuple[str, bool]:
    """Return ``(license, known)`` for a user-supplied license string.

    A recognised identifier (case-insensitively in :data:`_KNOWN_LICENSES`) is
    normalised to its canonical lower-cased SPDX-style form; anything else —
    including a license URL — is kept verbatim so a valid-but-unlisted license is
    never rejected. ``known`` is False for the kept-verbatim case so the caller
    can warn.
    """
    token = str(value).strip()
    if not token:
        raise ValueError("license must be a non-empty string, e.g. ws.license('cc-by-4.0').")
    lowered = token.lower()
    if lowered in _KNOWN_LICENSES:
        return lowered, True
    return token, False


def _license_value(license: str) -> dict | str:
    """How a deposit graph or RO-Crate states a licence.

    The same form ``record_to_jsonld`` uses (:func:`battinfo.jsonld.license_node`):
    a URL or a known SPDX id becomes an IRI reference to the SPDX page, spelled
    the way SPDX spells it; any other text stays a plain literal rather than a
    link that resolves to nothing. The catalog node, every member dataset node
    and the RO-Crate root use this one function.
    """
    from battinfo.jsonld import license_node

    return license_node(license) or license.strip()


@dataclass
class ContributorRef:
    """The person contributing records from this workspace, identified by ORCID.

    Stamped onto each dataset's ``creators`` at ``save()`` so platform
    contributions can be attributed to a person (the ORCID is the durable key).
    """

    orcid: str  # bare id, e.g. "0000-0002-1825-0097"
    name: str | None = None
    affiliation: str | None = None

    @property
    def orcid_url(self) -> str:
        return f"https://orcid.org/{self.orcid}"

    @classmethod
    def from_dict(cls, data: dict) -> "ContributorRef":
        return cls(
            orcid=_normalize_orcid(str(data.get("orcid") or "")),
            name=data.get("name"),
            affiliation=data.get("affiliation"),
        )

    def to_dict(self) -> dict:
        out: dict[str, Any] = {"orcid": self.orcid}
        if self.name:
            out["name"] = self.name
        if self.affiliation:
            out["affiliation"] = self.affiliation
        return out

    def person_block(self) -> dict:
        """A schema-valid ``Person`` node carrying the ORCID in ``same_as``.

        Stamped into each record's top-level ``contributor`` list. ``same_as`` is
        the standard ORCID slot that ``_schema_agent_node`` / ``contributor_to_jsonld``
        read, so this flows into JSON-LD (and DataCite) with an ORCID identifier.
        """
        block: dict[str, Any] = {"type": "Person"}
        if self.name:
            block["name"] = self.name
        block["same_as"] = self.orcid_url
        if self.affiliation:
            block["affiliation"] = {"type": "Organization", "name": self.affiliation}
        return block

    def summary(self) -> str:
        return f"{self.name} ({self.orcid_url})" if self.name else self.orcid_url


def _oa_text(value: Any) -> str | None:
    """Pull a plain string out of OpenAIRE's polymorphic JSON values."""
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        for key in ("$", "content", "value", "name", "classname"):
            if key in value:
                text = _oa_text(value[key])
                if text:
                    return text
    if isinstance(value, list):
        for item in value:
            text = _oa_text(item)
            if text:
                return text
    return None


def _find_first(node: Any, key: str) -> Any:
    """Depth-first search for the first value stored under *key* anywhere in *node*."""
    if isinstance(node, dict):
        if key in node:
            return node[key]
        for value in node.values():
            found = _find_first(value, key)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_first(item, key)
            if found is not None:
                return found
    return None


def _parse_openaire_project(payload: dict) -> dict:
    """Extract ``{name, acronym, funder, program}`` from an OpenAIRE projects response.

    Tolerant of the API's deeply-nested, version-dependent shape; returns only
    the fields it can find.
    """
    project = _find_first(payload, "oaf:project")
    if not isinstance(project, dict):
        project = payload  # fall back to scanning the whole payload
    out: dict[str, str] = {}
    name = _oa_text(_find_first(project, "title"))
    if name:
        out["name"] = name
    acronym = _oa_text(_find_first(project, "acronym"))
    if acronym:
        out["acronym"] = acronym
    fundingtree = _find_first(project, "fundingtree")
    scope = fundingtree if fundingtree is not None else project
    funder = _oa_text(_find_first(scope, "funder"))
    if funder:
        out["funder"] = funder
    program = _oa_text(_find_first(scope, "funding_level_0"))
    if program:
        out["program"] = program
    return out


def _resolve_project_openaire(identifier: str, *, timeout: float = 15.0) -> dict:
    """Look up grant descriptive metadata from OpenAIRE.

    Returns ``{}`` on any failure (offline, not found, parse error) so callers
    degrade gracefully to the bare identifier.
    """
    import urllib.parse
    import urllib.request

    query = urllib.parse.urlencode({"grantID": identifier, "format": "json", "size": 1})
    url = f"{_OPENAIRE_PROJECTS_API}?{query}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "battinfo-client/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            payload = json.loads(resp.read().decode())
        return _parse_openaire_project(payload)
    except Exception:
        return {}


def _provider(creators: list[dict] | None, contributors: list[dict] | None) -> tuple[str, str]:
    """Best-effort publishing organisation: the first affiliation (name, ror) among agents."""
    for c in (creators or []) + (contributors or []):
        if c.get("affiliation"):
            return c["affiliation"], c.get("affiliation_ror", "")
    return "", ""


# Record-type subdirectories under a workspace's records source folder
# (``.battinfo/records/`` — or ``.battinfo/records/examples/`` in legacy workspaces).
# Derived from the entity registry so new record types are picked up automatically.
_RECORD_SET_DIRS = record_set_dirs()

# Record types :meth:`AuthoringWorkspace._assemble_zenodo_jsonld` promotes to
# standalone deposit nodes by emitting each record on its own. Every other type
# reaches the graph through a dedicated builder (cell specs, cells, tests, test
# protocols, datasets) or through the record that references it (equipment and
# channels, from the tests that ran on them).
#
# A type in neither group is read off disk by :func:`_read_record_sets` and then
# silently dropped — records that save, validate and emit cleanly but never reach
# the artifact a reader gets. That is what happened to the whole electrode layer.
# ``tests/test_deposit_coverage.py`` sweeps ``ENTITY_KINDS`` against
# :data:`DEPOSIT_COVERAGE_EXEMPT` so the next type added fails a test rather than
# going missing from a deposit.
DEPOSIT_STANDALONE_KINDS: tuple[str, ...] = (
    "material-spec",
    "material",
    "electrode-spec",
    "electrode",
    "parameter-set",
)

# entity_type -> why a record of that type is not a described node in the deposit
# graph. Equipment and channels are NOT here: the test emitter builds a described
# node for each unit and channel a test ran on (hasTestEquipment / prov:used).
DEPOSIT_COVERAGE_EXEMPT: dict[str, str] = {
    "equipment-spec": (
        "the model behind a unit: the deposit describes the units the tests ran "
        "on (built from the test's equipment_id), not the product line, so a "
        "spec with no test attached has nothing to attach to. G11 tracks the "
        "wider equipment-family publication gap"
    ),
    **{
        entity_type: (
            "generic component family: described inline on the cell spec that uses "
            "it, not yet promoted to a standalone deposit node"
        )
        for entity_type in (
            "separator-spec",
            "separator",
            "current-collector-spec",
            "current-collector",
            "electrolyte-spec",
            "electrolyte",
            "housing-spec",
            "housing",
        )
    },
    "organization": (
        "identity record: the deposit inlines schema:manufacturer / "
        "schema:publisher agent nodes on the records that name them rather "
        "than shipping the registry's organization records; organization "
        "publication is a registry catalog concern, not a deposit one"
    ),
}


def _read_record_sets(source_root: Path) -> dict[str, list[dict]]:
    """Load a workspace's saved records into the canonical ``record_sets`` mapping.

    Returns ``{subdir: [record_dict, ...]}`` for each record type, sorted by filename
    so the assembled graph is deterministic. This is the on-disk source feeding the
    shared, input-agnostic builder :meth:`AuthoringWorkspace._assemble_zenodo_jsonld`.
    """
    record_sets: dict[str, list[dict]] = {}
    for name in _RECORD_SET_DIRS:
        recs: list[dict] = []
        subdir = source_root / name
        if subdir.exists():
            for f in sorted(subdir.glob("*.json")):
                try:
                    recs.append(_read_json(f))
                except (OSError, ValueError) as exc:
                    # Fail closed: silently skipping a corrupt/BOM record would publish an
                    # incomplete Zenodo graph with records missing and no error (R-6, R-10).
                    raise ValueError(f"Cannot assemble the record bundle: {f} is unreadable ({exc}).") from exc
        record_sets[name] = recs
    return record_sets


def _replaced_legacy_parameter_sets(record_sets: dict[str, list[dict]]) -> dict[str, str]:
    """Parameter sets minted under ``spec/`` that another record here supersedes.

    Returns ``{old spec/ IRI: replacing IRI}``. The documented migration is
    ``supersede_parameter_set(old)`` then ``ws.add(new)``: the workspace then
    holds both, and the old record is replaced, not published again.
    """
    replaced: dict[str, str] = {}
    for record in record_sets.get("parameter-set", []):
        body = record.get("parameter_set") if isinstance(record, dict) else None
        if not isinstance(body, dict):
            continue
        old, new = body.get("supersedes"), body.get("id")
        if isinstance(old, str) and old.startswith(record_base() + "spec/") and isinstance(new, str) and new != old:
            replaced[old] = new
    return replaced


def _read_deposit_record_sets(source_root: Path) -> tuple[dict[str, list[dict]], dict[str, str]]:
    """The records a deposit carries, and the legacy parameter sets it leaves out.

    A parameter set minted under ``spec/`` that another record in the
    workspace supersedes stays out of the deposit and out of the record check
    (its replacement carries its claims); one that nothing supersedes is
    still refused by the check. Returns ``(record_sets, {old IRI: new IRI})``.
    """
    record_sets = _read_record_sets(source_root)
    replaced = _replaced_legacy_parameter_sets(record_sets)
    if replaced:
        record_sets["parameter-set"] = [
            record
            for record in record_sets.get("parameter-set", [])
            if not (
                isinstance(record, dict)
                and isinstance(body := record.get("parameter_set"), dict)
                and isinstance(body.get("id"), str)
                and body["id"] in replaced
            )
        ]
    return record_sets, replaced


def _print_replaced_legacy_parameter_sets(replaced: dict[str, str]) -> None:
    for old, new in sorted(replaced.items()):
        print(f"  Leaving out {old}: minted under spec/ and superseded by {new} in this workspace.")


def _parameter_set_publication_errors(record_sets: dict[str, list[dict]]) -> list[str]:
    """Why parameter sets in *record_sets* cannot be published, one line per record.

    :meth:`AuthoringWorkspace.submit` validates every record under the
    publisher policy before it sends anything. A deposit describes its
    parameter sets as nodes of its own, so the Zenodo path runs the same
    record check on them: it refuses a parameter set minted under ``spec/``
    (``semantic.parameter_set_legacy_namespace``) and one that reuses a uid
    (``semantic.parameter_set_uid_reused``), so nothing is published under
    ``spec/`` by either route (IDENTIFIER_POLICY 6.3).
    """
    from battinfo.validate.record import validate_record  # noqa: PLC0415

    problems: list[str] = []
    for record in record_sets.get("parameter-set", []):
        label = (entity_id_from_doc(record) if isinstance(record, dict) else None) or "a parameter set"
        try:
            result = validate_record(record, policy="publisher")
        except (ValueError, TypeError) as exc:  # not a recognised record, as ws.submit() reports it
            problems.append(f"{label}: not a recognised record ({exc})")
            continue
        if not result.ok:
            problems.append(f"{label}: {'; '.join(result.errors)}")
    return problems


_MATERIAL_SPEC_STUB_TYPE = ["Description", "schema:ProductModel", "schema:CreativeWork"]


def _parameter_set_target_refs(records: list[dict]) -> list[tuple[str, Any]]:
    """``(IRI, stub @type)`` for every record a parameter set points at, sorted.

    Cell spec, cell instance, material spec, and a parameter file's part
    material specs. Material specs stub with the type their own records emit.
    """
    refs: dict[str, Any] = {}
    for record in records:
        body = record.get("parameter_set") if isinstance(record, dict) else None
        if not isinstance(body, dict):
            continue
        if isinstance(body.get("cell_spec_id"), str):
            refs.setdefault(body["cell_spec_id"], "BatteryCellSpecification")
        if isinstance(body.get("cell_instance_id"), str):
            refs.setdefault(body["cell_instance_id"], "BatteryCell")
        if isinstance(body.get("material_spec_id"), str):
            refs.setdefault(body["material_spec_id"], _MATERIAL_SPEC_STUB_TYPE)
        parts = body.get("parts")
        for part in parts if isinstance(parts, list) else []:
            if isinstance(part, dict) and isinstance(part.get("material_spec_id"), str):
                refs.setdefault(part["material_spec_id"], _MATERIAL_SPEC_STUB_TYPE)
    return sorted(refs.items())


def _defined_elsewhere_stub(iri: str, stub_type: Any, name: str = "") -> dict:
    """A deposit node for a record published at its own IRI and not carried here.

    It states the record's type, its name when the graph labels other nodes
    with it, and ``rdfs:isDefinedBy`` its own IRI, which is where its
    description lives. Nothing else is copied, so the stub cannot drift from
    the published record.
    """
    stub: dict = {"@id": iri, "@type": stub_type, "rdfs:isDefinedBy": {"@id": iri}}
    if name:
        stub["schema:name"] = name
    return stub


# Reference copies a deposit describes with a stub, by the folder the
# workspace keeps them in (``.battinfo/references/<folder>/``). A cell spec
# kept as a copy is left out: every cell spec a cell points at and the deposit
# does not carry already gets an unnamed stub, which the importer recognises
# as one by its keys.
_REFERENCE_STUB_TYPES: dict[str, Any] = {
    "cell-instance": "BatteryCell",
    "test-protocol": ["prov:Plan", "schema:HowTo"],
}


def _reference_stub_sources(
    referenced_records: dict[str, list[dict]] | None,
) -> dict[str, tuple[str, Any, str]]:
    """``{IRI: (folder, stub @type, name)}`` for the published records a workspace keeps copies of.

    Only the type and the name are read from a copy. The record belongs to
    whoever published it, not to the deposit that points at it.
    """
    sources: dict[str, tuple[str, Any, str]] = {}
    for folder, stub_type in _REFERENCE_STUB_TYPES.items():
        for record in (referenced_records or {}).get(folder, []):
            iri = entity_id_from_doc(record) if isinstance(record, dict) else None
            if not isinstance(iri, str) or not iri:
                continue
            body = next((v for v in record.values() if isinstance(v, dict) and v.get("id") == iri), {})
            name = body.get("name")
            sources[iri] = (folder, stub_type, name.strip() if isinstance(name, str) else "")
    return sources


def _unresolved_record_references(doc: dict) -> list[str]:
    """BattINFO IRIs a deposit's tests and datasets point at that have no node in it, sorted.

    The cell a test ran on (``hasTestObject``) and what a dataset is about
    (``schema:about``). A record the workspace keeps a copy of gets a stub,
    so an IRI left here was not found locally.
    """
    graph = [node for node in doc.get("@graph") or [] if isinstance(node, dict)]
    present = {node.get("@id") for node in graph}
    missing: set[str] = set()
    for node in graph:
        types = node.get("@type")
        types = types if isinstance(types, list) else [types]
        refs: list[Any] = []
        if "BatteryTest" in types:
            refs.append(node.get("hasTestObject"))
        if "dcat:Dataset" in types:
            about = node.get("schema:about")
            refs.extend(about if isinstance(about, list) else [about])
        for ref in refs:
            iri = ref.get("@id") if isinstance(ref, dict) else None
            if isinstance(iri, str) and iri.startswith(BATTINFO_ROOT) and iri not in present:
                missing.add(iri)
    return sorted(missing)


def _omission_list(omissions: Iterable[Omission], limit: int = 10) -> str:
    """*omissions* on one line for a message: each once, the first *limit*, then how many more."""
    unique = list(dict.fromkeys(omissions))
    shown = "; ".join(str(omission) for omission in unique[:limit])
    return shown + (f"; and {len(unique) - limit} more" if len(unique) > limit else "")


def _shown_list(items: list[str], limit: int = 10) -> str:
    """*items* on one line for a message: the first *limit*, then how many more."""
    shown = "; ".join(items[:limit])
    return shown + (f"; and {len(items) - limit} more" if len(items) > limit else "")


def _not_found_locally_note(iris: list[str]) -> str:
    """Why the records in *iris* have no node in the deposit, and how to fetch them."""
    shown = ", ".join(iris[:5]) + (f" and {len(iris) - 5} more" if len(iris) > 5 else "")
    return (
        f"Not found locally: {len(iris)} record(s) this deposit points at are neither saved in "
        "this workspace nor kept as a copy under .battinfo/references/ (looked up offline, or "
        f"never looked up): {shown}. Open the workspace with a registry_url and reference each "
        'again, for a cell with ws.load(ws.search(type="cell", serial=...)[0]); the workspace '
        "keeps a copy of the published record, and the deposit describes it from that copy."
    )


def _clean_deposit_text(value: Any) -> str | None:
    """*value* as text, or ``None`` when it is empty or a placeholder (``unknown``).

    Keeps placeholders out of a deposit's title, description and keywords.
    """
    text = str(value).strip() if value is not None else ""
    return text if text and text.lower() != "unknown" else None


def _auto_deposit_title(specs: list[dict]) -> str:
    """The title of a deposit given none, from the first saved cell spec's manufacturer and model."""
    if not specs:
        return "Battery Dataset — BattINFO"
    first = specs[0]
    subject = " ".join(
        part
        for part in (_clean_deposit_text(first.get("manufacturer")), _clean_deposit_text(first.get("model")))
        if part
    )
    return f"{subject or 'Battery'} — BattINFO Battery Dataset"


def _apply_conformance_jsonld(
    node: dict,
    spec_id: str | None,
    conformance: dict | None,
    *,
    add_spec_links: bool = True,
) -> None:
    """Add PROV-O spec linkage + DQV conformance annotation to *node* in place.

    Generic over what is being assessed: *spec_id* is the governing spec — a test
    spec for a test execution, a cell spec for a cell instance.  ``add_spec_links``
    adds ``prov:used``/``dcterms:conformsTo`` (apt for a test activity); set it False
    for entities (e.g. a cell) whose spec link is expressed elsewhere — only the DQV
    quality annotation and deviation activities are added then.
    """
    if add_spec_links and spec_id:
        # prov:used links the activity to the entities it used. The caller may have
        # already recorded the test object (cell) under prov:used; append the spec
        # (the activity's "plan") so PROV alone reaches both the cell and the spec.
        used = node.get("prov:used")
        if used is None:
            node["prov:used"] = {"@id": spec_id}
        else:
            if isinstance(used, dict):
                used = [used]
            used.append({"@id": spec_id})
            node["prov:used"] = used
        # dcterms:conformsTo only when fully conformant (strong claim).
        if conformance and conformance.get("status") == "conformant":
            node["dcterms:conformsTo"] = {"@id": spec_id}

    if not conformance:
        return

    status = conformance.get("status", "unknown")
    status_iri = _CONFORMANCE_IRI.get(status, _CONFORMANCE_IRI["unknown"])
    note = conformance.get("note")

    # DQV carries the human-facing verdict; earl:outcome carries the machine-readable
    # W3C EARL outcome individual via the textbook EARL predicate (rather than
    # overloading dqv:value with an IRI). dqv:value stays a plain status literal.
    annotation: dict = {
        "@type": "dqv:QualityAnnotation",
        "oa:motivatedBy": {"@id": "oa:assessing"},
        "dqv:value": status,
        "earl:outcome": {"@id": status_iri},
    }
    if note:
        annotation["schema:description"] = note

    node["dqv:hasQualityAnnotation"] = annotation

    deviations = conformance.get("deviations") or []
    if deviations:
        influenced_by = []
        for dev in deviations:
            # Structured fields so an agent can read WHICH property deviated and how,
            # rather than parsing prose; the readable summary is kept as rdfs:comment.
            _label = dev.get("category", "deviation")
            if dev.get("type"):
                _label = f"{_label}: {dev['type']}"
            dev_node: dict = {
                "@type": "prov:Activity",
                "rdfs:comment": _label + (f" — {dev['description']}" if dev.get("description") else ""),
            }
            # Standard vocabulary (no battinfo: mints): the deviation category is
            # a dcterms:type on the activity; the affected property is the
            # activity's object, carried as a schema:PropertyValue whose
            # propertyID names the record property that deviated.
            if dev.get("category"):
                dev_node["dcterms:type"] = dev["category"]
            if dev.get("type"):
                dev_node["schema:object"] = {
                    "@type": "schema:PropertyValue",
                    "schema:propertyID": dev["type"],
                }
            if dev.get("description"):
                dev_node["schema:description"] = dev["description"]
            # An ISO 8601 string, as the schema allows, or a Unix time.
            iso_ts = _unix_to_iso(
                dev.get("occurred_at"), what=f"occurred_at of a deviation of {node.get('@id') or 'a record'}"
            )
            if iso_ts:
                dev_node["prov:startedAtTime"] = iso_ts
            duration_s = dev.get("duration_s")
            if duration_s is not None:
                m, s = divmod(int(duration_s), 60)
                h, m = divmod(m, 60)
                dev_node["schema:duration"] = f"PT{h}H{m}M{s}S" if h else (f"PT{m}M{s}S" if m else f"PT{s}S")
            influenced_by.append(dev_node)
        node["prov:wasInfluencedBy"] = influenced_by


def _coerce_conformance(value: Any) -> Any:
    """Normalise a conformance flag (status string, dict, or Conformance) to a Conformance.

    Validates the status against the controlled vocabulary; returns None for None.
    """
    if value is None:
        return None
    from battinfo.bundle import CONFORMANCE_STATUS_VALUES, Conformance  # noqa: PLC0415

    if isinstance(value, Conformance):
        return value
    if isinstance(value, str):
        value = {"status": value}
    if isinstance(value, dict):
        status = str(value.get("status", "unknown"))
        if status not in CONFORMANCE_STATUS_VALUES:
            raise ValueError(
                f"conformance status {status!r} is not valid. Use one of: {', '.join(CONFORMANCE_STATUS_VALUES)}."
            )
        return Conformance.from_record(value)
    raise TypeError("conformance must be a status string, a dict, or a Conformance.")


# ── Cycler format support (via the batterydf library) ────────────────────────
# Extensions safe to auto-detect: instrument-native and unlikely to collide with
# unrelated files in the workspace root.  .csv/.txt are deliberately NOT
# auto-detected (too ambiguous) — pass an explicit pattern or use convert_csv().
_CONVERT_AUTODETECT: dict[str, str] = {
    ".ndax": "NEWARE",
    ".nda": "NEWARE (legacy)",
    ".mpt": "Biologic (EC-Lab text export)",
    ".xlsx": "Excel",
    ".mat": "MATLAB",
}

# Readable by batterydf but ambiguous by extension — require an explicit pattern.
_CONVERT_EXPLICIT: dict[str, str] = {
    ".csv": "Digatron / Landt / Novonix / generic CSV",
    ".txt": "Basytec / Landt text",
}

# Known instrument files with no batterydf reader — flagged with actionable help.
_CONVERT_UNSUPPORTED: dict[str, str] = {
    ".res": "Arbin .res — export a CSV from Arbin MITS Pro, then run "
    "ws.convert('*.csv') or ws.convert_csv(path, hints={...}).",
    ".mpr": "Biologic .mpr (binary) - export as text from EC-Lab "
    "(Experiment > Export as Text -> .mpt), then run ws.convert().",
}

# Result-key -> human label, in display order, for ws.save() confirmation output.
_SAVE_DISPLAY: list[tuple[str, str]] = [
    ("cell_specs", "cell spec"),
    ("cell_instances", "cell"),
    ("test_specs", "test spec"),
    ("tests", "test"),
    ("datasets", "dataset"),
    ("material_specs", "material spec"),
    ("materials", "material"),
    ("electrode_specs", "electrode spec"),
    ("electrodes", "electrode"),
    ("parameter_sets", "param set"),
]

# Result keys written by the side-record path (records the engine does not model),
# in write order: specs before instances so a reference resolves on disk.
_SIDE_RECORD_KEYS: tuple[str, ...] = (
    "material_specs",
    "materials",
    "electrode_specs",
    "electrodes",
    "parameter_sets",
)


def _dedupe_records_by_id(records: list[dict], candidate: dict, body_key: str) -> list[dict]:
    """Append *candidate* unless a record with the same canonical id is present.

    Re-adding an identical (content-derived) material in one session is a no-op —
    the deterministic id makes the duplicate detectable — while a genuinely
    edited record with the same id replaces the earlier one so ws.save writes the
    latest version.
    """
    cand_id = candidate.get(body_key, {}).get("id")
    if cand_id is None:
        return [*records, candidate]
    out = [r for r in records if r.get(body_key, {}).get("id") != cand_id]
    out.append(candidate)
    return out


# Canonical BDF column names — the targets for convert_csv() hints.  This is a
# discovery aid for users; the authoritative mapping lives in interop/battdat.py.
_BDF_CANONICAL_COLUMNS: list[tuple[str, str]] = [
    ("test_time_second", "seconds since test start"),
    ("unix_time_second", "absolute Unix timestamp (s)"),
    ("voltage_volt", "cell voltage (V)"),
    ("current_ampere", "current (A); + charge, - discharge"),
    ("power_watt", "power (W)"),
    ("cycle_count", "cycle index"),
    ("step_count", "step counter"),
    ("step_id", "step number in the cycler program"),
    ("charging_capacity_ah", "charge capacity (Ah)"),
    ("discharging_capacity_ah", "discharge capacity (Ah)"),
    ("charging_energy_wh", "charge energy (Wh)"),
    ("discharging_energy_wh", "discharge energy (Wh)"),
    ("ambient_temperature_celsius", "ambient temperature (degC)"),
    ("internal_resistance_ohm", "internal resistance (Ohm)"),
]


def _unmapped_source_columns(src: Path, plugin_id: str | None, out_columns: list[str]) -> list[str]:
    """Source columns that did not survive a BDF conversion (best-effort).

    Reads the raw column header of *src* through the resolved reader plugin and
    returns every source column that neither resolves to a BDF canonical name
    nor passes through to the converted output. Binary formats whose parsers
    cannot cheaply expose a header return ``[]`` (nothing to compare against),
    and any inspection failure degrades to ``[]`` — the report must never break
    a conversion that already succeeded.
    """
    try:
        import bdf.io as _bdf_io  # noqa: PLC0415

        plugin = _bdf_io.PLUGINS[plugin_id] if plugin_id in _bdf_io.PLUGINS else None
        parser = getattr(plugin, "table_parser", None)
        read_headings = getattr(parser, "read_column_headings", None)
        if read_headings is None:
            return []
        raw_headers = [h for h in read_headings(src) if isinstance(h, str) and h.strip()]
        normalizer = getattr(parser, "normalizer", None)
        survived = set(out_columns)
        unmapped: list[str] = []
        for header in raw_headers:
            if header in survived:
                continue
            try:
                if normalizer is not None and normalizer.resolve([header]):
                    continue  # renamed into a canonical BDF column
            except Exception:  # noqa: BLE001 — treat resolver hiccups as unmapped
                pass
            unmapped.append(header)
        return unmapped
    except Exception:  # noqa: BLE001 — reporting is best-effort by design
        return []


_ROW_COUNTER_MIN_ROWS = 10


def _row_counter_columns(src: Path, plugin_id: str | None, columns: list[str], n_rows: int) -> list[str]:
    """The *columns* of *src* that only number its rows (best-effort).

    A column holding 0, 1, 2, ... or 1, 2, 3, ..., one value per row of the
    converted table, says nothing the row order of the converted file does not
    already say (Neware's ``Record`` column is one), so leaving it out of the
    BDF file loses no data. A column that cannot be read, or whose values are
    anything else, is not a row counter and stays reported as lost.

    A file shorter than ``_ROW_COUNTER_MIN_ROWS`` rows is never judged: a
    single 1, or a 0/1 flag over two rows, looks like a counter by chance, and
    calling it one would hide real data loss.
    """
    if not columns or n_rows < _ROW_COUNTER_MIN_ROWS:
        return []
    try:
        import bdf.io as _bdf_io  # noqa: PLC0415
        import polars as pl  # noqa: PLC0415

        plugin = _bdf_io.PLUGINS[plugin_id] if plugin_id in _bdf_io.PLUGINS else None
        parser = getattr(plugin, "table_parser", None)
        if parser is None:
            return []
        frame = parser.read(src, normalize=False, lazy=True).select(columns).collect()
    except Exception:  # noqa: BLE001 — best-effort, like the loss report itself
        return []
    counters: list[str] = []
    for name in columns:
        try:
            values = frame.get_column(name)
            if values.dtype.is_float() and not (values == values.floor()).all():
                continue
            values = values.cast(pl.Int64, strict=True)
        except Exception:  # noqa: BLE001 — not whole numbers, so not a row counter
            continue
        if len(values) != n_rows or values.null_count() or values[0] not in (0, 1):
            continue
        if not (values.diff().drop_nulls() == 1).all():
            continue
        counters.append(name)
    return counters


# Legacy/authored test-spec condition keys -> (canonical condition name, default unit).
# ws.template() used to emit unit-suffixed keys with bare scalars or {min,max}
# dicts; these keep loading (coerced to proper quantities) so old drafts survive.
_TEMPLATE_CONDITION_KEYS: dict[str, tuple[str, str]] = {
    "temperature": ("temperature", "degC"),
    "temperature_degC": ("temperature", "degC"),
    "applied_pressure": ("applied_pressure", "kPa"),
    "applied_pressure_kilopascal": ("applied_pressure", "kPa"),
    "voltage_window": ("voltage_window", "V"),
    "voltage_window_volt": ("voltage_window", "V"),
    "soc_window": ("soc_window", "%"),
    "c_rate": ("c_rate", "A/Ah"),
    "d_rate": ("d_rate", "A/Ah"),
}


def _clean_template_conditions(raw: Any) -> tuple[dict[str, dict] | None, list[str]]:
    """Lift authored/template ``conditions`` to quantity shapes the model accepts.

    - Drops null placeholders (unfilled template entries) instead of failing.
    - Coerces legacy shapes: bare scalars under unit-suffixed keys
      (``temperature_degC: 25``) and ``{min, max}`` windows become
      ``{value|min_value|max_value, unit}`` quantities.
    - Non-numeric entries (e.g. ``atmosphere: "argon"``) cannot be quantities;
      they are returned as notes so the information is kept, not dropped.
    """
    if not isinstance(raw, dict):
        return None, []
    out: dict[str, dict] = {}
    notes: list[str] = []
    for key, value in raw.items():
        if value is None or str(key).startswith("_"):
            continue
        name, default_unit = _TEMPLATE_CONDITION_KEYS.get(key, (str(key), ""))
        if isinstance(value, bool):
            notes.append(f"condition {key}: {value}")
            continue
        if isinstance(value, (int, float)):
            qty: dict[str, Any] = {"value": float(value)}
        elif isinstance(value, dict):
            qty = {k: v for k, v in value.items() if v is not None and not str(k).startswith("_")}
            # legacy window keys
            if "min" in qty:
                qty["min_value"] = qty.pop("min")
            if "max" in qty:
                qty["max_value"] = qty.pop("max")
            if not any(k in qty for k in ("value", "min_value", "max_value")):
                continue  # placeholder left unfilled
        elif isinstance(value, str):
            if value.strip():
                notes.append(f"condition {key}: {value.strip()}")
            continue
        else:
            notes.append(f"condition {key}: {value!r}")
            continue
        if not qty.get("unit"):
            if not default_unit:
                raise ValueError(f'condition {key!r} needs a unit, e.g. {{"value": 25, "unit": "degC"}}.')
            qty["unit"] = default_unit
        out[name] = qty
    return (out or None), notes


def _clean_template_steps(raw: Any) -> builtins.list[str] | None:
    """Normalize authored/template ``steps`` to the PyBaMM-string list the model parses.

    Strings pass through; the old template's ``{"description": ...}`` dict
    placeholder is dropped, and a dict whose description was actually edited is
    lifted to its string so the authored step is not silently ignored.
    """
    if not isinstance(raw, list):
        return None
    steps: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            steps.append(item.strip())
        elif isinstance(item, dict):
            description = item.get("description")
            if (
                isinstance(description, str)
                and description.strip()
                and description.strip().lower() != "fill in test steps here"
            ):
                steps.append(description.strip())
    return steps or None


# The keys each ws.load() draft loader reads: the fields of the record model the
# draft becomes, the spellings that model's constructor also takes, and a few
# draft-only keys. A key with no home in the record (keys starting with "_" are
# comments) is refused rather than silently dropped, the way the record models
# refuse an unknown field.
#
# Model fields that are not draft keys: the class markers, and the cell spec's
# link to a library specification, which the canonical cell-spec record does
# not carry.
_NOT_DRAFT_KEYS = frozenset({"kind", "schema_version", "cell_specification_id"})
# Flat provenance keys -> the field of the record's nested `source` they fill (the
# spellings every record model's constructor takes).
_DRAFT_PROVENANCE_KEYS = {
    "source_type": "type",
    "source_name": "name",
    "source_file": "file",
    "source_url": "url",
    "citation": "citation",
    "file_hash": "file_hash",
    "retrieved_at": "retrieved_at",
    "workflow_version": "workflow_version",
    "curated_by": "curated_by",
}
# Other spellings that are read: alias -> the key it stands for. `specs` is also
# the cell-spec draft key used until June 2026.
_CELL_SPEC_DRAFT_ALIASES = {"specs": "properties", "model_name": "model", "notes": "comment"}
_TEST_SPEC_DRAFT_ALIASES = {"notes": "comment"}
# The equipment-spec record has no model class; its fields are the keyword
# arguments of create_equipment_spec().
_EQUIPMENT_SPEC_DRAFT_KEYS = frozenset(
    {
        "name",
        "handle",
        "equipment_class",
        "model",
        "channel_count",
        "supported_chemistries",
        "property",
        "manufacturer",
        "supplier",
        "product_id",
        "comment",
        "uid",
        "id",
        "source_type",
        "source_name",
        "source_file",
        "source_url",
        "citation",
        "retrieved_at",
        "notes",
    }
)
# A SpecItem with any of these set carries a value; one with none is an unfilled
# template placeholder.
_QUANTITY_VALUE_KEYS = ("value", "min_value", "max_value", "typical_value", "value_text")


@functools.cache
def _cell_spec_draft_keys() -> frozenset[str]:
    """Every CellSpec field a cell-spec draft can set, and the flat provenance keys."""
    from battinfo.bundle import CellSpec  # noqa: PLC0415

    return frozenset({*CellSpec.model_fields, *_DRAFT_PROVENANCE_KEYS} - _NOT_DRAFT_KEYS)


@functools.cache
def _test_spec_draft_keys() -> frozenset[str]:
    """Every TestSpec field a test-spec draft can set, and the draft's own keys."""
    from battinfo.bundle import TestSpec  # noqa: PLC0415

    # The test type is `type` in the template and is also read as `kind`,
    # `test_type` or `test_kind`; `steps` or `experiment` (with `cycles`) are
    # PyBaMM-style strings parsed into the method; `instrument` and `atmosphere`
    # are kept as notes; `protocol_url` is the URL of the protocol followed.
    own_keys = {
        "type",
        "kind",
        "test_kind",
        "steps",
        "experiment",
        "cycles",
        "instrument",
        "atmosphere",
        "protocol_url",
    }
    return frozenset(({*TestSpec.model_fields, *_DRAFT_PROVENANCE_KEYS} - _NOT_DRAFT_KEYS) | own_keys)


def _draft_text_list(value: Any) -> builtins.list[str]:
    """A draft's comment or notes as a list of strings; one string is one note."""
    if value is None:
        return []
    items = value if isinstance(value, (builtins.list, tuple)) else [value]
    return [str(item) for item in items if item is not None and str(item).strip()]


def _merge_draft_alias(fields: dict[str, Any], alias: str, key: str, path: Path) -> None:
    """Read *alias* as *key*; the two given with different values raise."""
    if alias not in fields:
        return
    value = fields.pop(alias)
    if fields.get(key) not in (None, value):
        raise ValueError(f"{path.name}: {alias!r} and {key!r} disagree; keep one. Nothing was loaded.")
    fields[key] = value


def _draft_source(fields: dict[str, Any], *, default_type: str, path: Path) -> dict[str, Any]:
    """Pop a draft's provenance into the one ``source`` object the record model takes.

    Reads a nested ``source`` object and the flat keys the templates write
    (``source_file``, ``citation``, ``source_url``, ...); a value given both
    ways must agree.
    """
    nested = fields.pop("source", None)
    if nested is not None and not isinstance(nested, Mapping):
        raise ValueError(
            f"{path.name}: 'source' must be an object such as "
            '{"type": "datasheet", "url": "https://..."}. Nothing was loaded.'
        )
    source = {key: value for key, value in (nested or {}).items() if value is not None}
    for flat, key in _DRAFT_PROVENANCE_KEYS.items():
        value = fields.pop(flat, None)
        if value is None:
            continue
        if source.get(key) not in (None, value):
            raise ValueError(f"{path.name}: {flat!r} and 'source.{key}' disagree; keep one. Nothing was loaded.")
        source[key] = value
    source.setdefault("type", default_type)
    return source


def _filled_quantities(quantities: Mapping[str, Any], path: Path) -> dict[str, Any]:
    """The quantities a draft fills in, without the unfilled template placeholders.

    A placeholder is null or an object with no value of any kind; a range or a
    text value is a value. A value that is not a quantity object raises rather
    than being dropped.
    """
    filled: dict[str, Any] = {}
    for key, value in quantities.items():
        if value is None:
            continue
        if not isinstance(value, Mapping):
            raise ValueError(
                f"{path.name}: property {key!r} must be a quantity object such as "
                f'{{"value": 1.5, "unit": "V"}}, not {value!r}. Nothing was loaded.'
            )
        if any(value.get(field) is not None for field in _QUANTITY_VALUE_KEYS):
            filled[key] = value
    return filled


# Registry resource type of each entity type a workspace can reference by IRI. The
# registry envelope carries the canonical record under the same key in
# semantic_payload.battinfo_records.
_REGISTRY_RESOURCE_TYPES = {"cell": "cell", "cell-spec": "cell_spec", "test-protocol": "test_spec"}
# A Zenodo deposit of more than this many data files is zipped, one archive per
# test kind (see AuthoringWorkspace._bundle_data_files).
_ZENODO_ZIP_THRESHOLD = 90
# Seconds to wait for the registry when looking up one referenced record. ws.add()
# blocks on it, and the outcome is remembered for the session either way.
_REFERENCE_LOOKUP_TIMEOUT = 10


def _canonical_record_of(envelope: Any, entity_type: str) -> dict | None:
    """The canonical record inside a registry envelope, or None when it has none."""
    kind = kind_for_type(entity_type)
    if kind is None or not isinstance(envelope, dict):
        return None
    records = (envelope.get("semantic_payload") or {}).get("battinfo_records") or {}
    if not isinstance(records, dict):
        return None
    for key in (_REGISTRY_RESOURCE_TYPES.get(entity_type), kind.record_key):
        candidate = records.get(key) if key else None
        if isinstance(candidate, dict) and isinstance(candidate.get(kind.record_key), dict):
            return candidate
    return None


def _path_key(path: str | Path) -> str:
    """A file path normalised for comparison (absolute, case-folded where the OS is)."""
    return os.path.normcase(os.path.abspath(str(path)))


def _check_draft_keys(
    raw: Mapping[str, Any],
    allowed: frozenset[str],
    *,
    draft: str,
    path: Path,
    aliases: Mapping[str, str] | None = None,
    quiet: frozenset[str] = frozenset(),
) -> None:
    """Raise ValueError for draft keys the loader does not read, with a did-you-mean.

    The *allowed* keys are listed in the message; *aliases* (alias -> the key it
    stands for) and *quiet* keys are read too, but not listed.
    """
    aliases = aliases or {}
    unknown = [
        key
        for key in raw
        if not str(key).startswith("_") and key not in allowed and key not in aliases and key not in quiet
    ]
    if not unknown:
        return
    candidates = sorted({*allowed, *aliases, *quiet})
    parts = []
    for key in unknown:
        close = difflib.get_close_matches(str(key), candidates, n=1)
        suggestion = aliases.get(close[0], close[0]) if close else None
        parts.append(repr(key) + (f" (did you mean {suggestion!r}?)" if suggestion else ""))
    raise ValueError(
        f"{path.name}: unknown key(s) in a {draft} draft: {', '.join(parts)}. "
        f"A {draft} draft accepts: {', '.join(sorted(allowed))}; keys starting with '_' "
        "are comments. Nothing was loaded."
    )


def _signature_keywords(fn: Callable[..., Any]) -> builtins.list[str]:
    """The parameters *fn* takes by name, in signature order; ``**kwargs`` is not one."""
    import inspect  # noqa: PLC0415

    named = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    return [name for name, p in inspect.signature(fn).parameters.items() if p.kind in named]


def _check_add_keywords(record_type: str, accepted: Iterable[str], kwargs: Mapping[str, Any]) -> None:
    """Raise TypeError for keywords ``ws.add(record_type, ...)`` does not take, with a did-you-mean.

    ``ws.add()`` hands its keywords to a private method, and from there to a
    builder or an input model, so a stray keyword used to fail deep inside: as
    Python's message naming the private method, as a pydantic error, or as a
    complaint about another argument. *accepted* is read from those signatures
    and models, so it follows them when they change.
    """
    from battinfo.bundle import _unknown_keyword_parts  # noqa: PLC0415

    accepted = list(dict.fromkeys(accepted))
    unknown = [key for key in kwargs if key not in accepted]
    if not unknown:
        return
    raise TypeError(
        f"Unknown keyword(s) for ws.add({record_type!r}): {_unknown_keyword_parts(unknown, accepted)}. "
        f"ws.add({record_type!r}, ...) accepts: {', '.join(f'{name}=' for name in accepted)}. "
        "Run help(ws.add) for what each one does."
    )


class AuthoringWorkspace:
    """The blessed authoring surface: a simplified workspace for BattINFO records.

    Create one with :func:`battinfo.workspace` and call :meth:`quickstart` for a
    copy-pasteable end-to-end example. Wraps the lower-level object-graph engine
    :class:`battinfo.Workspace` (defined in ``battinfo._workspace``) with a concise
    API designed for interactive / notebook use.
    """

    def __init__(
        self,
        root: str | Path = ".",
        records_repo: str | Path | None = None,
        registry_url: str | None = None,
    ):
        self._root = Path(root).resolve()
        self._records_root = self._root / ".battinfo" / "records"
        self._legacy_layout_announced = False
        self._ws = self._make_engine()
        self._records_repo = Path(records_repo).resolve() if records_repo else _find_records_repo(self._root)
        # This workspace's .battinfo/credentials, parsed into the instance and
        # never into os.environ: process-global state would lend one workspace's
        # identity to every other workspace opened in the same process. Re-read
        # when the file changes (ws.login(), ws.setup() or an edit by hand).
        self._file_credentials: dict[str, str] = {}
        self._file_credentials_stamp: tuple[int, int] | None = None
        self._reload_file_credentials()
        # Credentials established by login() in THIS instance; the same rule
        # applies. _credential() resolves every name through both.
        self._session_credentials: dict[str, str] = {}
        # The registry for lookups (see _workspace_registry). A URL passed in is
        # kept, and None turns registry lookups off. Left out, as
        # battinfo.workspace() leaves it, it is looked up at each use, like the
        # credentials: BATTINFO_REGISTRY_URL from the environment or this
        # workspace's credentials file, else production.
        if registry_url is not _UNSET:
            registry_url = registry_url.rstrip("/") if registry_url else None
        self._registry_url_given: str | None = registry_url
        # Every cell the session can be pointed at by a label, once each, with
        # the labels it answers to (its serial number and name as given). A
        # cell known only by its IRI is not listed. A lookup reads
        # this list, so a label that two or more cells answer to is reported
        # with every candidate rather than resolved to whichever came last: a
        # display name is not an identifier, and a batch may share one.
        self._indexed_cells: builtins.list[tuple[Any, builtins.list[str]]] = []
        # True once cell instances saved in a previous session have been lazily
        # loaded from .battinfo/records/cell-instance/ into the list above, so a
        # fresh process can still resolve a cell by serial (day-2 rehydration).
        self._cells_rehydrated = False
        # (registry, entity type, IRI) -> outcome of looking a referenced record
        # up in that registry this session ("copied", "not_found",
        # "unreachable", ...), so a record is asked for once per registry, and a
        # failed lookup is not retried on every ws.add() that references it.
        self._reference_lookups: dict[tuple[str, str, str], str] = {}
        # channel reference -> (equipment_id, channel_id) for test attachment.
        # Keys: the channel IRI, the channel label, and "unit/CHn" for the
        # unit's name and serial number. Populated by ws.add("equipment", ...)
        # and lazily from channel records already saved in the workspace.
        self._channels_by_ref: dict[str, tuple[str, str]] = {}
        # in-memory search cache; populated lazily from registry API or local index,
        # and built again when the workspace's registry changes
        self._search_cache: list[dict] | None = None
        self._search_cache_registry: str | None = None
        # converted-file → original-source mapping (lazy-loaded from manifest)
        self._conversion_sources: dict[str, Any] | None = None
        # Record files this session wrote: by the most recent ws.save(), by
        # ws.add() (see _added_paths), and by ws.upload() or ws.zenodo(), which
        # rewrite dataset records. submit() sends only these, so records left in
        # the same directory by earlier sessions are not sent again.
        self._session_paths: set[Path] = set()
        # Record files ws.add() wrote itself (an equipment unit, its spec and its
        # channels). ws.save() does not write them, so it starts the session set
        # from this one instead of discarding them.
        self._added_paths: set[Path] = set()
        # First-class material queues (Level 2 spec / Level 3 instance). Materials
        # are not engine model objects, so the AuthoringWorkspace holds their
        # canonical records and writes them in ws.save() through the SAME stamp
        # path as every other record. Keyed spec index lets ws.add("material")
        # resolve spec= by name/short_id/IRI without ws._ws.
        self._material_specs: builtins.list[dict] = []
        self._materials: builtins.list[dict] = []
        self._material_specs_by_ref: dict[str, dict] = {}
        # First-class electrode queues, same arrangement: the designed electrode
        # (spec) and the coated batch (instance).
        self._electrode_specs: builtins.list[dict] = []
        self._electrodes: builtins.list[dict] = []
        self._electrode_specs_by_ref: dict[str, dict] = {}
        # Parameter-set queue (claim batches about a material kind / material
        # spec / cell spec), same side-record arrangement as materials.
        self._parameter_sets: builtins.list[dict] = []
        # workspace-level funding project (grant); lazily loaded from
        # .battinfo/workspace.json on first access via _get_project()
        self._project_ref: ProjectRef | None = None
        self._project_loaded = False
        # workspace-level contributors (ORCID), in call order; lazily loaded from
        # .battinfo/workspace.json on first access via _get_contributors().
        self._contributors: builtins.list[ContributorRef] = []
        self._contributors_loaded = False
        # workspace-level default license (SPDX id or URL), stamped onto every
        # record at save; lazily loaded from .battinfo/workspace.json via
        # _get_license().
        self._license: str | None = None
        self._license_loaded = False

    def _make_engine(self) -> "Workspace":
        """Construct the record engine, choosing the on-disk workspace layout.

        Layout (W5.3): the engine is rooted at ``<root>/.battinfo`` with
        ``source_dir_name="records"``, so user records land under
        ``.battinfo/records/<record-type>/`` — real lab data no longer lives in
        a directory literally named "examples" — and engine siblings
        (index.json, library/, package/) sit under ``.battinfo/``. This was
        chosen over rooting the engine at ``.battinfo/records`` with
        ``source_dir_name="records"`` because that would yield the redundant
        ``.battinfo/records/records/``. Pre-0.8 workspaces that already have
        ``.battinfo/records/examples/`` keep the legacy engine root
        ``.battinfo/records`` (records under ``examples/``, index at
        ``.battinfo/records/index.json``) so existing data stays where it is.
        """
        from battinfo._workspace import Workspace

        legacy_source = self._records_root / "examples"
        if legacy_source.is_dir():
            if not self._legacy_layout_announced:
                print("  note: using legacy records/examples/ layout (pre-0.8 workspace)")
                self._legacy_layout_announced = True
            return Workspace(root=self._records_root)
        return Workspace(root=self._root / ".battinfo", source_dir_name="records")

    # ── Public API ─────────────────────────────────────────────────────────────

    def setup(self) -> Path:
        """Create a credentials file and explain how to log in.

        Run once per project.  Then either run ``ws.login(api_key=...)`` (which
        fills in your workspace/publisher automatically) or edit the generated
        file by hand.  The file is git-ignored, and read by this workspace only:
        each ``battinfo.workspace()`` call reads the file of its own folder, and
        nothing is copied into the environment.  The file's header lists the
        order in which a credential is looked up; :meth:`credentials_status`
        shows where each one comes from.

        The file is readable by its owner only (mode 0600; Windows ignores the
        mode).  A file that already exists is kept as it is, apart from that mode.

        Example::

            ws.setup()
            ws.login(api_key="YOUR_KEY")
        """
        self._ensure_gitignore()
        cred_path = self._credentials_path()
        if cred_path.exists():
            _chmod_owner_only(cred_path)
            print(f"Credentials file already exists: {cred_path}")
        else:
            _write_private_text(cred_path, _CREDENTIALS_TEMPLATE)
            self._reload_file_credentials()
            print(f"Created: {cred_path}")
        print("\n  Next: get an API key (no self-service page yet - request one from")
        print("  the registry operator via https://www.battery-genome.org), then run")
        print('        ws.login(api_key="YOUR_KEY")')
        print("  That fills in your workspace and publisher automatically - you do")
        print("  not need to know any IDs.  ws.quickstart() shows the full flow.")
        return cred_path

    def _credentials_path(self) -> Path:
        return self._root / ".battinfo" / "credentials"

    def _ensure_gitignore(self) -> None:
        """Ensure ``.battinfo/credentials`` is git-ignored."""
        gitignore = self._root / ".gitignore"
        entry = ".battinfo/credentials"
        if gitignore.exists():
            content = gitignore.read_text(encoding="utf-8")
            if entry not in content:
                gitignore.write_text(content.rstrip() + f"\n{entry}\n", encoding="utf-8")
        else:
            gitignore.write_text(entry + "\n", encoding="utf-8")

    def _set_credentials(self, updates: dict[str, str]) -> Path:
        """Merge key=value pairs into .battinfo/credentials, preserving other lines.

        Each updated name ends up on one line: its first line in the file takes
        the new value and any later lines for it are dropped. The file is read
        with the last line winning, so a later line left in place would undo the
        update in the next session.
        """
        path = self._credentials_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # utf-8-sig, as _read_credentials_file reads it: a byte order mark must
        # not hide the name on the first line.
        source = path.read_text(encoding="utf-8-sig") if path.exists() else _CREDENTIALS_TEMPLATE
        written: set[str] = set()
        out: list[str] = []
        for line in source.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                if key in updates:
                    if key not in written:
                        out.append(f"{key:22} = {updates[key]}")
                        written.add(key)
                    continue
            out.append(line)
        for key, value in updates.items():
            if key not in written:
                out.append(f"{key:22} = {value}")
        # This file holds API keys, R2 secrets and Zenodo tokens: owner-only from
        # the first byte, and a failed write keeps the old file.
        _write_private_text(path, "\n".join(out) + "\n")
        self._reload_file_credentials()
        return path

    def _reload_file_credentials(self) -> None:
        """Parse this workspace's ``.battinfo/credentials`` into the instance."""
        path = self._credentials_path()
        try:
            stat = path.stat()
        except OSError:
            self._file_credentials, self._file_credentials_stamp = {}, None
            return
        self._file_credentials = _read_credentials_file(path)
        self._file_credentials_stamp = (stat.st_mtime_ns, stat.st_size)

    def _file_credential_values(self) -> dict[str, str]:
        """This workspace's credentials file, parsed again if it changed since the last read."""
        try:
            stat = self._credentials_path().stat()
            stamp: tuple[int, int] | None = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            stamp = None
        if stamp != self._file_credentials_stamp:
            self._reload_file_credentials()
        return self._file_credentials

    def _registry_read_headers(self) -> dict[str, str]:
        """Headers for the registry's credentialed workspace views.

        Sends the admin token when one is configured (reviewers), otherwise the
        publisher API key stored by :meth:`login`. Either opens a workspace's own
        submission queue; an empty dict lets the registry answer 401 with guidance.
        """
        headers = {"User-Agent": "battinfo-client/1.0"}
        admin_token = self._credential("BATTINFO_ADMIN_TOKEN")
        if admin_token:
            headers["X-Battinfo-Admin-Token"] = admin_token
        api_key = self._credential("BATTINFO_API_KEY")
        if api_key:
            headers["X-Battinfo-API-Key"] = api_key
        return headers

    def _resolve_credential(
        self, key: str, default: str | None = None, *, explicit: str | None = None
    ) -> tuple[str | None, str | None]:
        """Return ``(value, source)`` for the credential *key*; ``(None, None)`` when unset.

        The one lookup order for every credential the workspace reads: *explicit*
        (an argument the caller passed), a value :meth:`login` set on this
        workspace in this session, an exported environment variable, this
        workspace's ``.battinfo/credentials``, then *default*. The source is the
        matching name in :data:`_CREDENTIAL_SOURCE_TEXT`. Nothing here reads
        another workspace's file or writes ``os.environ``.
        """
        if explicit:
            return explicit, "argument"

        def candidates() -> Iterator[tuple[str, str | None]]:
            # Lazy, so the file is read only when nothing before it answers.
            yield "login", self._session_credentials.get(key)
            yield "environment", os.environ.get(key)
            yield "credentials_file", self._file_credential_values().get(key)

        for source, value in candidates():
            if value and value.strip():
                return value.strip(), source
        if default:
            return default, "default"
        return None, None

    def _credential(self, key: str, default: str | None = None, *, explicit: str | None = None) -> str | None:
        """The value of the credential *key* in the order of :meth:`_resolve_credential`."""
        return self._resolve_credential(key, default, explicit=explicit)[0]

    @property
    def _registry_url(self) -> str | None:
        """The registry this workspace looks records up in; None when lookups are off."""
        return self._workspace_registry()[0]

    def _workspace_registry(self) -> tuple[str | None, str | None]:
        """Return ``(url, source)`` of this workspace's registry; ``(None, None)`` when it has none.

        A ``registry_url`` given when the workspace was opened is kept. Left
        out, it is looked up at each use in the order of
        :meth:`_resolve_credential`, with the production registry as the
        default, so a change to ``BATTINFO_REGISTRY_URL`` in the environment or
        in this workspace's credentials file takes effect without reopening the
        workspace.
        """
        if self._registry_url_given is not _UNSET:
            return (self._registry_url_given, "argument") if self._registry_url_given else (None, None)
        url, source = self._resolve_credential("BATTINFO_REGISTRY_URL", _DEFAULT_REGISTRY_URL)
        url = (url or "").rstrip("/")
        return (url, source) if url else (None, None)

    def _registry_base(self, registry_url: str | None = None) -> tuple[str | None, str | None]:
        """Return ``(url, source)`` of the registry a call talks to; ``(None, None)`` when none.

        The call's own *registry_url* wins, then the workspace's registry. A
        workspace opened with ``registry_url=None`` has none for lookups, but a
        call that needs one (login, submit, status ...) still takes
        ``BATTINFO_REGISTRY_URL`` from the environment or this workspace's
        credentials file. It never falls back to the production registry.
        """
        if registry_url:
            return registry_url.rstrip("/"), "argument"
        url, source = self._workspace_registry()
        if url:
            return url, source
        url, source = self._resolve_credential("BATTINFO_REGISTRY_URL")
        return (url.rstrip("/"), source) if url else (None, None)

    def _require_registry(self, registry_url: str | None, call: str) -> str:
        """The registry URL for *call*, or a RuntimeError that says how to give one."""
        url = self._registry_base(registry_url)[0]
        if not url:
            raise RuntimeError(
                f"registry_url required: {call} needs a registry, and this workspace has none "
                "(it was opened with registry_url=None). Pass registry_url=..., or set "
                "BATTINFO_REGISTRY_URL in the environment or in .battinfo/credentials."
            )
        return url

    def credentials_status(self) -> dict[str, dict[str, Any]]:
        """Say which credentials this workspace has and where each one comes from.

        Returns ``{name: {"set": bool, "source": str | None}}`` for every name
        the workspace reads (``BATTINFO_*``, ``R2_*``, ``ZENODO_*``). The source
        is ``"login"`` (set by :meth:`login` in this session), ``"environment"``
        (an exported variable), ``"credentials_file"`` (this workspace's
        ``.battinfo/credentials``) or ``"default"``, and ``None`` when the name
        is not set. ``BATTINFO_REGISTRY_URL`` reports the registry this
        workspace talks to, with ``"argument"`` when it was passed to
        ``battinfo.workspace()``. The values themselves are never returned, so
        the result is safe to print or log.

        Each name is looked up in this order, and the first value found is used:
        an argument passed to the call (such as ``ws.zenodo(token=...)``), a
        value :meth:`login` set in this session, an environment variable of the
        same name, this workspace's ``.battinfo/credentials``, then the default.
        Opening a workspace does not copy its credentials file into
        ``os.environ``, so check a credential here rather than in the
        environment.

        Example::

            ws.credentials_status()["ZENODO_API_TOKEN"]
            # {'set': True, 'source': 'credentials_file'}
        """
        return {name: self._credential_state(name) for name in _CREDENTIAL_NAMES}

    def _credential_state(self, name: str) -> dict[str, Any]:
        """``{"set": ..., "source": ...}`` for one name, without its value."""
        if name == "BATTINFO_REGISTRY_URL":
            value, source = self._registry_base()
        else:
            value, source = self._resolve_credential(name)
        return {"set": value is not None, "source": source}

    def has_credential(self, name: str) -> bool:
        """True when the credential *name* is set for this workspace.

        Looks where the workspace itself looks: a value :meth:`login` set in
        this session, the environment, then this workspace's
        ``.battinfo/credentials``. Use it instead of ``os.environ.get(...)``,
        which does not see the credentials file. :meth:`credentials_status`
        lists every name with its source.

        Example::

            if ws.has_credential("ZENODO_SANDBOX_TOKEN"):
                ws.zenodo(sandbox=True)
        """
        if name not in _CREDENTIAL_NAMES:
            close = difflib.get_close_matches(str(name), _CREDENTIAL_NAMES, n=1)
            raise ValueError(
                f"{name!r} is not a credential the workspace reads"
                + (f" (did you mean {close[0]!r}?)" if close else "")
                + f". Known names: {', '.join(_CREDENTIAL_NAMES)}."
            )
        return bool(self._credential_state(name)["set"])

    def login(self, api_key: str, *, registry_url: str | None = None) -> dict:
        """Log in with a registry API key and cache your workspace identity.

        Fetches your publisher/workspace identity from the registry so you never
        have to know workspace or publisher IDs, and stores the key in
        ``.battinfo/credentials`` (git-ignored) for future sessions.  There is
        no self-service key page yet: request a key from the registry operator
        (Battery Genome - https://www.battery-genome.org, or your team's
        registry admin).

        The key and identity belong to this workspace: they are kept on this
        instance and in its own credentials file, never in the environment.
        The key you pass and the ids the registry returns are saved.

        If the registry cannot be asked (no profile endpoint, or no network),
        the key is still saved and the workspace and publisher ids come from
        the usual lookup: this session, the environment, this workspace's
        credentials file, then the defaults. An id the file lacks is then
        saved there, as the default or as the id an earlier login() in this
        session got, so :meth:`submit` and :meth:`status` work in later
        sessions. An id found only in the environment is used but not saved.

        The registry is *registry_url*, else the workspace's. A workspace opened
        with ``registry_url=None`` needs one passed here or set as
        ``BATTINFO_REGISTRY_URL``. The registry asked is printed with where
        its URL came from.

        Example::

            ws.login(api_key="bk_live_...")
            ws.whoami()
        """
        import urllib.error
        import urllib.request

        api_key = (api_key or "").strip()
        if not api_key:
            raise ValueError(
                "api_key is required. There is no self-service key page yet: "
                "request a key from the registry operator (Battery Genome - "
                "https://www.battery-genome.org, or your team's registry admin)."
            )
        url = self._require_registry(registry_url, "ws.login()")
        url_source = self._registry_base(registry_url)[1]

        profile: dict = {}
        try:
            req = urllib.request.Request(
                f"{url}/me",
                headers={"X-Battinfo-API-Key": api_key, "User-Agent": "battinfo-client/1.0"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
                profile = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise RuntimeError(
                    f"Registry rejected the API key (HTTP {exc.code}). Check the key and try again."
                ) from None
            profile = {}  # 404 / older registry without /me — degrade gracefully
        except Exception:
            profile = {}  # network/registry unavailable — degrade gracefully
        if not isinstance(profile, dict):
            profile = {}

        # The session takes the key passed and the ids the registry returned.
        # The file takes them too and, for an id the registry did not return
        # and the file lacks, this workspace's own (from an earlier login()) or
        # the default, as the setup() template has it, so later sessions can
        # submit. An id found only in the environment may not be this
        # workspace's: it is used here but never saved.
        identity = {"BATTINFO_API_KEY": api_key}
        for key, field_name in (("BATTINFO_WORKSPACE_ID", "workspace_id"), ("BATTINFO_PUBLISHER_ID", "publisher_id")):
            value = profile.get(field_name)
            if isinstance(value, str) and value.strip():
                identity[key] = value.strip()
        self._session_credentials.update(identity)
        # Resolved before the file is written, so the message says where each id came from.
        wid, wid_source = self._resolve_credential("BATTINFO_WORKSPACE_ID", _DEFAULT_IDENTITY["BATTINFO_WORKSPACE_ID"])
        pid, pid_source = self._resolve_credential("BATTINFO_PUBLISHER_ID", _DEFAULT_IDENTITY["BATTINFO_PUBLISHER_ID"])
        saved = dict(identity)
        in_file = self._file_credential_values()
        for key, default in _DEFAULT_IDENTITY.items():
            if key not in saved and not in_file.get(key):
                saved[key] = self._session_credentials.get(key) or default
        self._ensure_gitignore()
        path = self._set_credentials(saved)
        name = profile.get("display_name") or pid

        if profile:
            print(f"Logged in as {name} (workspace: {wid}).")
        else:
            print(
                f"API key saved. Using workspace {wid!r} ({_CREDENTIAL_SOURCE_TEXT[wid_source or 'default']}), "
                f"publisher {pid!r} ({_CREDENTIAL_SOURCE_TEXT[pid_source or 'default']})."
            )
            print(
                "  (Registry profile lookup unavailable - edit BATTINFO_WORKSPACE_ID and "
                "BATTINFO_PUBLISHER_ID in .battinfo/credentials if these are wrong.)"
            )
            for key, source in (("BATTINFO_WORKSPACE_ID", wid_source), ("BATTINFO_PUBLISHER_ID", pid_source)):
                if source == "environment":
                    print(
                        f"  ({key} is taken from the environment and not saved; "
                        f".battinfo/credentials has {self._file_credential_values().get(key)!r}.)"
                    )
        print(f"  Registry:    {url}  ({_CREDENTIAL_SOURCE_TEXT[url_source or 'default']})")
        print(f"  Credentials: {path}")
        return {"workspace_id": wid, "publisher_id": pid, "display_name": name, "registry_url": url}

    def whoami(self, *, registry_url: str | None = None) -> dict:
        """Print the identity behind the API key, and where each credential it used came from.

        Asks the registry's profile endpoint (``/me``) with the API key. Each
        credential is shown with its source: passed as an argument, set by
        :meth:`login` in this session, from the environment, from this
        workspace's ``.battinfo/credentials``, or the default. The returned dict
        holds the profile plus ``credential_sources``, which maps each name used
        to its source as :meth:`credentials_status` names it. Secret values are
        never printed or returned. When the registry cannot be asked, the
        workspace and publisher ids come from the same lookup instead.

        Example::

            ws.whoami()
            #   Ada Lovelace
            #   workspace:  ada-lab
            #   publisher:  ada-lab
            #   registry:   https://battinfo-registry.onrender.com  (the default)
            #   API key:    from .battinfo/credentials
        """
        import urllib.request

        key, key_source = self._resolve_credential("BATTINFO_API_KEY")
        if not key:
            print("Not logged in. Run ws.login(api_key='...').")
            return {}
        sources: dict[str, str | None] = {"BATTINFO_API_KEY": key_source}
        url, url_source = self._registry_base(registry_url)

        def _source_lines() -> None:
            if url:
                print(f"  registry:   {url}  ({_CREDENTIAL_SOURCE_TEXT[url_source or 'default']})")
            print(f"  API key:    {_CREDENTIAL_SOURCE_TEXT[key_source or 'default']}")

        if url:
            sources["BATTINFO_REGISTRY_URL"] = url_source
            try:
                req = urllib.request.Request(
                    f"{url}/me",
                    headers={"X-Battinfo-API-Key": key, "User-Agent": "battinfo-client/1.0"},
                )
                with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
                    profile = json.loads(resp.read().decode())
                if not isinstance(profile, dict):
                    raise ValueError("the profile is not a JSON object")
            except Exception as exc:
                print(f"  (registry profile unavailable: {exc})")
            else:
                print(f"  {profile.get('display_name') or profile.get('publisher_id')}")
                print(f"  workspace:  {profile.get('workspace_id')}")
                print(f"  publisher:  {profile.get('publisher_id')}")
                _source_lines()
                return {**profile, "credential_sources": sources}
        else:
            print(
                "  (no registry: this workspace was opened with registry_url=None. Pass "
                "registry_url=..., or set BATTINFO_REGISTRY_URL.)"
            )
        wid, wid_source = self._resolve_credential("BATTINFO_WORKSPACE_ID", _DEFAULT_IDENTITY["BATTINFO_WORKSPACE_ID"])
        pid, pid_source = self._resolve_credential("BATTINFO_PUBLISHER_ID", _DEFAULT_IDENTITY["BATTINFO_PUBLISHER_ID"])
        sources["BATTINFO_WORKSPACE_ID"] = wid_source
        sources["BATTINFO_PUBLISHER_ID"] = pid_source
        print(f"  workspace:  {wid}  ({_CREDENTIAL_SOURCE_TEXT[wid_source or 'default']})")
        print(f"  publisher:  {pid}  ({_CREDENTIAL_SOURCE_TEXT[pid_source or 'default']})")
        _source_lines()
        return {"workspace_id": wid, "publisher_id": pid, "credential_sources": sources}

    # ── Project / funding provenance ────────────────────────────────────────────

    def project(
        self,
        identifier: str | None = None,
        *,
        name: str | None = None,
        funder: str | None = None,
        program: str | None = None,
        acronym: str | None = None,
        id: str | None = None,
        refresh: bool = False,
        clear: bool = False,
    ) -> dict | None:
        """Tag this workspace with a funding project (grant) for provenance.

        The grant *identifier* (e.g. an EU grant agreement number like
        ``"101103997"``) is normally all you need — the project title, funder and
        programme are looked up from OpenAIRE and cached in
        ``.battinfo/workspace.json``.  Once set, the project is stamped onto every
        record you ``save()``, so you can trace which work belongs to which grant.

        Anything you pass explicitly (``name=``, ``funder=`` …) overrides the
        looked-up value and is preserved across ``refresh=True``.

        Returns the record-level ``funding`` block (or ``None`` when cleared or
        unset).

        Examples
        --------
        ::

            ws.project("101103997")                    # tag with an EU grant
            ws.project()                               # show the current project
            ws.project("101103997", name="DigiBatt")   # override / fill in by hand
            ws.project(refresh=True)                   # re-fetch from OpenAIRE
            ws.project(clear=True)                     # remove the project tag
        """
        if clear:
            self._set_project(None)
            print("Workspace project cleared.")
            return None

        overrides = {
            key: value
            for key, value in (
                ("name", name),
                ("funder", funder),
                ("program", program),
                ("acronym", acronym),
                ("id", id),
            )
            if value is not None
        }
        current = self._get_project()

        # Getter: no identifier supplied.
        if identifier is None:
            if current is None:
                print('No project set. Tag this workspace with a grant, e.g.:\n    ws.project("101103997")')
                return None
            ref = current
            if overrides or refresh:
                ref = self._resolve_and_store(current.identifier, overrides=overrides, base=current, refresh=True)
            self._print_project(ref)
            return ref.funding_block()

        # Setter: identifier supplied.
        identifier = str(identifier).strip()
        if not identifier:
            raise ValueError("project identifier must be a non-empty string.")
        base = current if (current is not None and current.identifier == identifier) else None
        ref = self._resolve_and_store(identifier, overrides=overrides, base=base, refresh=refresh or base is None)
        self._print_project(ref)
        return ref.funding_block()

    def _resolve_and_store(
        self,
        identifier: str,
        *,
        overrides: dict[str, str],
        base: "ProjectRef | None",
        refresh: bool,
    ) -> "ProjectRef":
        """Build the project ref (remote lookup + overrides), persist it, return it.

        Manual overrides always win and are remembered (``ProjectRef.manual``) so
        they survive a later ``refresh=True``.  Remote resolution only fills fields
        the user did not set by hand.  Resolution is skipped when the grant is
        already resolved and ``refresh`` is False, so re-setting the same id never
        re-hits the network.
        """
        fields: dict[str, Any] = {}
        manual: set[str] = set()
        if base is not None:
            manual |= set(base.manual)
            fields.update(
                {
                    key: getattr(base, key)
                    for key in ("name", "funder", "program", "acronym", "id")
                    if getattr(base, key)
                }
            )
        manual |= set(overrides)
        # Effective manual values = this call's overrides on top of remembered ones.
        manual_values = {key: fields[key] for key in manual if key in fields}
        manual_values.update(overrides)

        resolved = base.resolved if base is not None else False
        if refresh or not resolved:
            remote = _resolve_project_openaire(identifier)
            for key, value in remote.items():
                if key not in manual:  # never overwrite a hand-set field
                    fields[key] = value
            resolved = True
        fields.update(manual_values)
        ref = ProjectRef(identifier=identifier, resolved=resolved, manual=sorted(manual), **fields)
        if not ref.id:
            ref.id = ref.default_iri()
        self._set_project(ref)
        return ref

    def _print_project(self, ref: "ProjectRef") -> None:
        print(f"Workspace project: {ref.summary()}")
        if ref.funder:
            print(f"  funder:   {ref.funder}")
        if ref.program:
            print(f"  program:  {ref.program}")
        if ref.id:
            print(f"  id:       {ref.id}")
        if not ref.name and not ref.acronym:
            print("  (descriptive metadata not resolved -- offline, or grant not in")
            print('   OpenAIRE; set it by hand e.g. ws.project(name="...", funder="..."),')
            print("   or retry with ws.project(refresh=True))")
        print("  Saved to .battinfo/workspace.json; stamped onto records on ws.save().")

    def _workspace_state_path(self) -> Path:
        return self._root / ".battinfo" / "workspace.json"

    def _load_workspace_state(self) -> dict:
        p = self._workspace_state_path()
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    def _save_workspace_state(self, state: dict) -> None:
        p = self._workspace_state_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

    def _get_project(self) -> "ProjectRef | None":
        """Current workspace project, loaded from disk on first access."""
        if not self._project_loaded:
            data = self._load_workspace_state().get("project")
            self._project_ref = ProjectRef.from_dict(data) if data else None
            self._project_loaded = True
        return self._project_ref

    def _set_project(self, ref: "ProjectRef | None") -> None:
        state = self._load_workspace_state()
        if ref is None:
            state.pop("project", None)
        else:
            state.setdefault("schema_version", "0.1.0")
            state["project"] = ref.to_dict()
        self._save_workspace_state(state)
        self._project_ref = ref
        self._project_loaded = True

    def _funding_block(self) -> dict | None:
        """The record-level ``funding`` block for this workspace, or ``None``."""
        ref = self._get_project()
        return ref.funding_block() if ref else None

    def _record_stamp(self) -> tuple[Callable[[dict], None] | None, dict[str, int]]:
        """Build the callback that stamps funding + contributors onto a candidate record.

        The callback mutates a record document in place and is applied by
        :meth:`save` *before* each record is written (via ``save_record``'s
        ``stamp`` hook), rather than rewriting the file afterwards.  Doing it on
        the candidate keeps the content-change decision and the on-disk bytes in
        agreement: a re-save whose stamped result is byte-identical is reported as
        ``unchanged`` and is not rewritten.

        The funding block is set when absent; each contributor (a ``Person``
        carrying the ORCID in ``same_as``) is appended if its ORCID is not already
        listed; the workspace default license is set on a record that carries
        none, and a license the record states itself is kept.
        All are idempotent and back-fill records authored before the
        project/contributor/license was set — a re-save whose stamped result is
        byte-identical is reported ``unchanged``, while changing the workspace
        license re-stamps the new value on the records that take the default
        (reported ``updated``).  Returns
        ``(None, counters)`` when none of project/contributor/license is set.
        ``counters`` is updated as the callback runs so :meth:`save` can report
        how many records each stamp reached.
        """
        block = self._funding_block()
        people = [(r.orcid_url, r.person_block()) for r in self._get_contributors()]
        lic = self._get_license()
        counters = {"funding": 0, "contributor": 0, "license": 0}
        if block is None and not people and not lic:
            return None, counters

        def stamp(doc: dict) -> None:
            if block is not None and doc.get("funding") != block:
                doc["funding"] = block
                counters["funding"] += 1
            if people:
                contributors = doc.get("contributor")
                if not isinstance(contributors, list):
                    contributors = []
                present = {c.get("same_as") for c in contributors if isinstance(c, dict)}
                added = False
                for orcid_url, person in people:
                    if orcid_url in present:
                        continue
                    contributors.append(person)
                    present.add(orcid_url)
                    added = True
                if added:
                    doc["contributor"] = contributors
                    counters["contributor"] += 1
            if lic:
                # Datasets carry the license on the dataset body (the existing
                # slot the emitter reads and where an explicit ws.add(license=)
                # lands); other record types carry it at the top level. For
                # every record type the workspace default only back-fills a
                # record that has none: an explicit per-record license, such
                # as ws.add("parameter_set", ..., license=...), is kept.
                ds_body = doc.get("dataset")
                holder = ds_body if isinstance(ds_body, dict) else doc
                if not holder.get("license"):
                    holder["license"] = lic
                    counters["license"] += 1

        return stamp, counters

    def contributor(
        self,
        orcid: str | None = None,
        *,
        name: str | None = None,
        affiliation: str | None = None,
        clear: bool = False,
    ) -> dict | list[dict] | None:
        """Credit a contributor (by ORCID) on everything this workspace publishes.

        Contributors accumulate: call this once per author and each is added, in
        call order, to every record you ``save()`` (as a ``Person`` carrying the
        ORCID) and to the publication bundle. The ORCID is the durable key; a
        second call with the same ORCID updates that person's fields in place
        rather than adding a duplicate. ``name`` is shown in the record.

        Returns the added/updated contributor's ``Person`` block, or the full list
        of contributor blocks for the pure getter (``None`` when none are set or
        after ``clear=True``).

        Examples
        --------
        ::

            ws.contributor("0000-0002-1825-0097", name="Jane Researcher")
            ws.contributor("0000-0001-5109-3700", name="Alex Coauthor")  # both kept
            ws.contributor()                       # show the current contributors
            ws.contributor(affiliation="SINTEF")   # patch the most recent one
            ws.contributor(clear=True)             # remove all contributor tags
        """
        if clear:
            self._set_contributors([])
            print("Workspace contributor(s) cleared.")
            return None

        contributors = list(self._get_contributors())

        # Getter (no ORCID supplied): optionally patch the most recent contributor.
        if orcid is None:
            if not contributors:
                print(
                    "No contributor set. Tag this workspace with your ORCID, e.g.:\n"
                    '    ws.contributor("0000-0002-1825-0097", name="Your Name")'
                )
                return None
            if name is not None or affiliation is not None:
                last = contributors[-1]
                contributors[-1] = ContributorRef(
                    orcid=last.orcid,
                    name=name if name is not None else last.name,
                    affiliation=affiliation if affiliation is not None else last.affiliation,
                )
                self._set_contributors(contributors)
            self._print_contributors(contributors)
            return [c.person_block() for c in contributors]

        # Setter: ORCID supplied. A repeat ORCID updates in place (order preserved);
        # a new ORCID is appended. Unspecified fields are preserved on update.
        ref = ContributorRef(orcid=_normalize_orcid(orcid), name=name, affiliation=affiliation)
        existing_ix = next((i for i, c in enumerate(contributors) if c.orcid == ref.orcid), None)
        if existing_ix is not None:
            prev = contributors[existing_ix]
            if ref.name is None:
                ref.name = prev.name
            if ref.affiliation is None:
                ref.affiliation = prev.affiliation
        if not ref.name:
            raise ValueError(
                'contributor name is required, e.g. ws.contributor("0000-0002-1825-0097", name="Your Name").'
            )
        if existing_ix is not None:
            contributors[existing_ix] = ref
        else:
            contributors.append(ref)
        self._set_contributors(contributors)
        self._print_contributors(contributors)
        return ref.person_block()

    def _get_contributors(self) -> builtins.list["ContributorRef"]:
        """All workspace contributors in call order, loaded from disk on first access.

        Accepts both the current list form and a legacy scalar ``contributor``
        entry in workspace.json (upgraded to a single-element list on load).
        """
        if not self._contributors_loaded:
            raw = self._load_workspace_state().get("contributor")
            if isinstance(raw, list):
                entries = raw
            elif isinstance(raw, dict):
                entries = [raw]  # migrate a legacy scalar entry
            else:
                entries = []
            self._contributors = [ContributorRef.from_dict(e) for e in entries if isinstance(e, dict)]
            self._contributors_loaded = True
        return self._contributors

    def _get_contributor(self) -> "ContributorRef | None":
        """The most recent workspace contributor, or ``None`` (backward-compat helper)."""
        contributors = self._get_contributors()
        return contributors[-1] if contributors else None

    def _set_contributors(self, refs: builtins.list["ContributorRef"]) -> None:
        state = self._load_workspace_state()
        if not refs:
            state.pop("contributor", None)
        else:
            state.setdefault("schema_version", "0.1.0")
            state["contributor"] = [r.to_dict() for r in refs]
        self._save_workspace_state(state)
        self._contributors = list(refs)
        self._contributors_loaded = True

    def _print_contributors(self, refs: builtins.list["ContributorRef"]) -> None:
        if len(refs) == 1:
            print(f"Workspace contributor: {refs[0].summary()}")
        else:
            print(f"Workspace contributors ({len(refs)}):")
            for r in refs:
                print(f"  - {r.summary()}")
        for r in refs:
            if r.affiliation:
                print(f"    {r.summary()} affiliation: {r.affiliation}")
        print("  Saved to .battinfo/workspace.json; stamped onto records on ws.save().")

    def license(
        self,
        license: str | None = None,
        *,
        clear: bool = False,
    ) -> str | None:
        """Set (or show) the default license stamped onto every record you save.

        Mirrors :meth:`contributor` and :meth:`project`: the value is persisted in
        ``.battinfo/workspace.json`` and stamped onto each record at ``save()``, so
        the license travels with the record itself (FAIR R1.1) rather than existing
        only on the Zenodo deposit. It fills in a record that has no license of its
        own; a record that states one keeps it. Pass an SPDX license identifier (e.g.
        ``"cc-by-4.0"``) or a license URL; a recognised identifier is normalised to
        canonical lower-case, anything else is kept verbatim with a warning.

        Precedence when a record is published: an explicit ``ws.zenodo(license=...)``
        wins over an explicit ``ws.add(..., license=...)``, which wins over this
        workspace default.

        Returns the current default (``None`` when unset or after ``clear=True``).

        Examples
        --------
        ::

            ws.license("cc-by-4.0")      # set the workspace default
            ws.license()                  # show the current default
            ws.license(clear=True)        # remove the default
        """
        if clear:
            self._set_license(None)
            print("Workspace license cleared.")
            return None

        # Getter: no license supplied.
        if license is None:
            current = self._get_license()
            if current is None:
                print('No license set. Set a default license for every record, e.g.:\n    ws.license("cc-by-4.0")')
                return None
            print(f"Workspace license: {current}")
            print("  Saved to .battinfo/workspace.json; stamped onto records on ws.save().")
            return current

        # Setter.
        normalized, known = _normalize_license(license)
        if not known:
            import warnings  # noqa: PLC0415

            msg = (
                f"license {normalized!r} is not a recognised SPDX identifier; keeping it "
                "verbatim. If this is a typo, use a known id such as 'cc-by-4.0'."
            )
            warnings.warn(msg, stacklevel=2)
            print(f"  WARNING: {msg}")
        self._set_license(normalized)
        print(f"Workspace license: {normalized}")
        print("  Saved to .battinfo/workspace.json; stamped onto records on ws.save().")
        return normalized

    def _get_license(self) -> str | None:
        """Current workspace default license, loaded from disk on first access."""
        if not self._license_loaded:
            raw = self._load_workspace_state().get("license")
            self._license = raw if isinstance(raw, str) and raw.strip() else None
            self._license_loaded = True
        return self._license

    def _set_license(self, value: str | None) -> None:
        state = self._load_workspace_state()
        if not value:
            state.pop("license", None)
        else:
            state.setdefault("schema_version", "0.1.0")
            state["license"] = value
        self._save_workspace_state(state)
        self._license = value or None
        self._license_loaded = True

    def convert(self, pattern: str | None = None, fmt: str = "csv") -> builtins.list[Path]:
        """Convert raw cycler files to BDF (Battery Data Format).

        With no ``pattern``, auto-detects supported instrument files in the
        workspace root and converts them all.  Each file becomes
        ``bdf/<name>.bdf.<fmt>``; files already converted are skipped.

        Requires the BDF converter (``pip install "battinfo[processing]"``).

        Auto-detected (just run ``ws.convert()``): NEWARE ``.ndax``/``.nda``,
        Biologic ``.mpt``, Excel ``.xlsx``, MATLAB ``.mat``.

        Ambiguous formats need an explicit pattern, e.g. ``ws.convert('*.csv')``
        for Digatron/Landt/Novonix CSV or ``ws.convert('*.txt')`` for Basytec.

        Not yet supported natively: Arbin ``.res`` and Biologic ``.mpr`` (binary)
        — export a CSV from the instrument software first, then
        ``ws.convert('*.csv')`` or :meth:`convert_csv`.

        Each file converted, and each file written, is registered as a data
        file of this workspace in ``.battinfo/deposit-files.json``, so a Zenodo
        deposit may read it (see :meth:`zenodo`).

        Parameters
        ----------
        pattern:
            Glob for input files.  ``None`` (default) auto-detects instrument
            formats.  Pass a glob like ``"*.csv"`` to force a specific set.
        fmt:
            Output format — ``"csv"`` (default, archival) or ``"parquet"``
            (compressed working format for analysis).

        Example::

            ws.convert()                 # auto-detect everything → CSV
            ws.convert(fmt="parquet")    # auto-detect → Parquet
            ws.convert("*.csv")          # force CSV inputs (Digatron/Landt/...)
        """
        if fmt not in ("parquet", "csv"):
            raise ValueError(f"fmt must be 'parquet' or 'csv' (got {fmt!r})")

        try:
            import bdf.repair as _bdf_repair

            from battinfo.processing import _read_bdf_pandas, _reader_plugin_id, _save_bdf
        except ImportError:
            from battinfo._util import CONVERTER_INSTALL_HINT

            raise ImportError(
                f"convert() needs the BDF converter (module 'bdf' from the batterydf package). {CONVERTER_INSTALL_HINT}"
            )

        # ── Resolve input files ────────────────────────────────────────────
        if pattern is not None:
            input_files = sorted(self._root.glob(pattern))
            if not input_files:
                print(f"  No files matched: {pattern!r}")
                return []
        else:
            input_files = []
            detected: dict[str, int] = {}
            for f in sorted(self._root.iterdir()):
                if f.is_file() and f.suffix.lower() in _CONVERT_AUTODETECT:
                    input_files.append(f)
                    detected[f.suffix.lower()] = detected.get(f.suffix.lower(), 0) + 1
            if not input_files:
                self._print_convert_help()
                return []
            summary = ", ".join(f"{n} x {_CONVERT_AUTODETECT[e]} {e}" for e, n in detected.items())
            print(f"Found {len(input_files)} file(s): {summary}")

        bdf_dir = self._root / "bdf"
        bdf_dir.mkdir(exist_ok=True)

        suffix = f".bdf.{fmt}"
        written: list[Path] = []
        failed: list[tuple[str, str]] = []
        lossy: list[tuple[str, list[str]]] = []
        for src in input_files:
            # NEWARE filenames carry an embedded short-ID batch key used later for
            # cell↔file matching; keep that.  Other formats use the plain stem.
            out_stem = _make_batch_key(src.stem) if src.suffix.lower() in (".ndax", ".nda") else src.stem
            out = bdf_dir / f"{out_stem}{suffix}"
            if out.exists():
                print(f"  skip (exists): {out.name}")
                # Still record the source→output link so raw-source provenance works
                # even when the conversion was done in an earlier run.
                self._record_conversion(src, out)
                continue
            try:
                # batterydf >= 0.2: read() returns (polars_frame, metadata); the
                # helper collects to pandas (fix_time/save are pandas-based) and
                # applies the ratified tz="UTC" timestamp policy.
                df, meta = _read_bdf_pandas(src, validate=False)
                df = _bdf_repair.fix_time(df)
                _save_bdf(df, out)
            except Exception as exc:  # one bad file must not abort the batch
                failed.append((src.name, str(exc)))
                print(f"  FAILED: {src.name} -- {exc}")
                continue
            reader = _reader_plugin_id(meta)
            via = f", via {reader}" if reader else ""
            print(f"  {src.name}  ->  {out.name}  ({out.stat().st_size / 1e6:.1f} MB{via})")
            written.append(out)
            # A conversion that silently discards source columns is data loss
            # behind a success message — compare the source header against what
            # actually survived and report every column left behind.
            unmapped = _unmapped_source_columns(src, reader, list(df.columns))
            # A column that only numbers the rows is not data: the row order of
            # the converted file carries it. Say so instead of calling it a loss.
            counters = _row_counter_columns(src, reader, unmapped, len(df))
            if counters:
                unmapped = [col for col in unmapped if col not in counters]
                print(
                    f"  Left out {'a column' if len(counters) == 1 else 'columns'} that only "
                    f"number{'s' if len(counters) == 1 else ''} the rows: {', '.join(counters)}. "
                    f"The row order of {out.name} holds the same information."
                )
            if unmapped:
                lossy.append((src.name, unmapped))
                print(
                    f"  WARNING: {len(unmapped)} source column(s) were NOT mapped to BDF "
                    f"and are missing from {out.name}:"
                )
                for col in unmapped:
                    print(f"    - {col}")
                print(
                    f"    (reader plugin: {reader or 'unknown'} -- if that looks wrong, the "
                    "file was likely detected as the wrong instrument format)"
                )
                print(
                    "    Fix: ws.bdf_columns() lists the canonical names, then "
                    f"ws.convert_csv({src.name!r}, hints={{'<source column>': '<bdf name>'}})."
                )
            # Remember the original so it can travel with the dataset as raw-source
            # provenance when the test is published (see ws.add('test', ...)).
            self._record_conversion(src, out, unmapped_columns=unmapped)

        print(f"\nConverted {len(written)} file(s) -> {bdf_dir}" + (f"  ({len(failed)} failed)" if failed else ""))
        if lossy:
            print(
                f"  DATA-LOSS WARNING: {len(lossy)} file(s) had unmapped source columns "
                "(details above) -- the converted files do NOT contain those columns."
            )
        if failed:
            print(
                "  Failed files may be an unsupported variant -- try exporting a CSV "
                "and ws.convert('*.csv'), or ws.convert_csv(path, hints={...})."
            )
        return written

    def _print_convert_help(self) -> None:
        """Print actionable guidance when no convertible files are auto-detected."""
        print(f"  No convertible instrument files found in {self._root}")
        present_unsupported = [
            (f.name, _CONVERT_UNSUPPORTED[f.suffix.lower()])
            for f in self._root.iterdir()
            if f.is_file() and f.suffix.lower() in _CONVERT_UNSUPPORTED
        ]
        if present_unsupported:
            print("\n  These files need a manual export first:")
            for name, hint in present_unsupported:
                print(f"    {name}\n      {hint}")
        print("\n  Auto-detected (just run ws.convert()):")
        for ext, label in _CONVERT_AUTODETECT.items():
            print(f"    {ext:7} {label}")
        print("\n  Supported with an explicit pattern, e.g. ws.convert('*.csv'):")
        for ext, label in _CONVERT_EXPLICIT.items():
            print(f"    {ext:7} {label}")
        print(
            "\n  Arbin .res / Biologic .mpr / Maccor raw: export a CSV from the "
            "instrument software, then ws.convert('*.csv') or "
            "ws.convert_csv(path, hints={...})."
        )

    def bdf_columns(self) -> builtins.list[str]:
        """Print the canonical BDF column names (the targets for convert_csv hints)."""
        print("Canonical BDF columns -- map your CSV headers to these:")
        for name, desc in _BDF_CANONICAL_COLUMNS:
            print(f"  {name:30} {desc}")
        return [n for n, _ in _BDF_CANONICAL_COLUMNS]

    def convert_csv(
        self,
        path: str | Path,
        *,
        hints: dict[str, str] | None = None,
        fmt: str = "csv",
        validate: bool = True,
    ) -> Path:
        """Convert a non-standard CSV to BDF by mapping its column names.

        For cyclers with no batterydf reader (Arbin, Maccor, in-house exports):
        export a CSV from the instrument software, then map its headers to BDF
        canonical names with *hints*.

        Example::

            ws.convert_csv("maccor_export.csv", hints={
                "Cycle":        "cycle_count",
                "Voltage(V)":   "voltage_volt",
                "Current(A)":   "current_ampere",
                "Test Time(s)": "test_time_second",
            })

        See :meth:`bdf_columns` for the full list of canonical target names.

        Parameters
        ----------
        path:
            Path to the source CSV (absolute, or relative to the workspace root).
        hints:
            ``{source_column: bdf_canonical_name}``.  Columns not listed are
            kept unchanged.
        fmt:
            Output format — ``"csv"`` (default) or ``"parquet"``.
        validate:
            Run ``bdf.validate()`` on the result and report any issues.
        """
        if fmt not in ("parquet", "csv"):
            raise ValueError(f"fmt must be 'parquet' or 'csv' (got {fmt!r})")
        from battinfo._util import require_extra

        pd = require_extra("pandas", "tabular", "convert_csv() reads tabular data files")

        src = Path(path)
        if not src.is_absolute():
            src = self._root / src
        if not src.exists():
            raise FileNotFoundError(f"CSV not found: {src}")

        df = pd.read_csv(src)
        if hints:
            unknown = [c for c in hints if c not in df.columns]
            if unknown:
                print(f"  WARNING: {len(unknown)} hint column(s) not in the CSV (ignored): {unknown}")
            df = df.rename(columns={k: v for k, v in hints.items() if k in df.columns})

        bdf_dir = self._root / "bdf"
        bdf_dir.mkdir(exist_ok=True)
        out = bdf_dir / f"{src.stem}.bdf.{fmt}"

        # Prefer bdf.io.save to keep the BDF round-trip honest; fall back to pandas.
        try:
            from battinfo.processing import _save_bdf

            _save_bdf(df, out)
        except Exception:
            if fmt == "parquet":
                df.to_parquet(out, index=False)
            else:
                df.to_csv(out, index=False)

        if validate:
            try:
                import bdf as _bdf

                report = _bdf.validate(df)
                # batterydf >= 0.2 returns a dict report; older versions returned
                # an object with an ``ok`` attribute.
                if isinstance(report, dict):
                    ok = report.get("ok", True)
                else:
                    ok = getattr(report, "ok", True)
                if ok is False:
                    print(f"  BDF validation issues: {report}")
                else:
                    print("  BDF validation passed.")
            except ImportError:
                print("  (batterydf not installed - skipped BDF validation)")
            except Exception as exc:
                print(f"  BDF validation could not run: {exc}")

        mapped = ", ".join(sorted(set(hints.values()))) if hints else "(no remap)"
        print(f"  {src.name}  ->  {out.name}   mapped: {mapped}")

        # Columns that are still not BDF canonical names were kept as-is, but
        # downstream BDF tooling will not recognize them — say so out loud
        # instead of green-lighting a partially mapped file silently.
        def _is_canonical(column: str) -> bool:
            try:
                from bdf.spec import COLUMN_ONTOLOGY  # noqa: PLC0415

                return COLUMN_ONTOLOGY.get(column) is not None
            except Exception:  # noqa: BLE001 — fall back to the curated subset
                return column in {name for name, _ in _BDF_CANONICAL_COLUMNS}

        unmapped = [c for c in df.columns if not _is_canonical(c)]
        if unmapped:
            print(
                f"  WARNING: {len(unmapped)} column(s) are not BDF canonical names "
                "(kept unchanged, but BDF tooling will ignore them):"
            )
            for col in unmapped:
                print(f"    - {col}")
            print(
                "    Fix: ws.bdf_columns() lists the canonical names; re-run "
                "ws.convert_csv(path, hints={'<source column>': '<bdf name>'})."
            )
        return out

    def commands(self) -> None:
        """Print the workspace commands, grouped by stage of the workflow."""
        groups = [
            (
                "Set up",
                [
                    "setup()",
                    "login(api_key=...)",
                    "whoami()",
                    "credentials_status()                # which credentials are set, and where from",
                    "has_credential('ZENODO_API_TOKEN')  # True or False",
                    "project('101103997')               # tag work with a grant",
                ],
            ),
            (
                "Discover",
                [
                    "search('duracell mn2400')           # cell-specs (fuzzy)",
                    "search(type='cell', serial='...')   # existing instances",
                    "template('cell-spec', ...)",
                    "bdf_columns()",
                ],
            ),
            (
                "Build",
                [
                    "convert()",
                    "convert_csv(path, hints=...)",
                    "load(src)",
                    "add('cell', spec=spec, serial_numbers=[...])",
                    "load(ws.search(type='cell', batch='...'))  # reference existing",
                    "add('test', type='cycling', cell='SN-1', data='f.csv')",
                ],
            ),
            ("Inspect", ["list(verbose=True)", "status()"]),
            ("Publish", ["save()", "publish(note=...)", "zenodo()", "submit()"]),
            ("Review", ["pending()", "approve(id)"]),
            ("Import", ["import_(source)", "reload_cells()", "clear()"]),
        ]
        print("BattINFO workspace commands (call as ws.<command>):\n")
        for title, cmds in groups:
            print(f"  {title}:")
            for c in cmds:
                print(f"      ws.{c}")
        print("\n  New here? Run ws.quickstart() for a copy-paste walkthrough.")

    def quickstart(self) -> None:
        """Print a copy-pasteable, end-to-end example for the common case."""
        print(
            "# === BattINFO quickstart =========================================\n"
            "import battinfo\n"
            'ws = battinfo.workspace(".")\n'
            "\n"
            "# 1. One-time: log in (request a key from the registry operator)\n"
            'ws.login(api_key="YOUR_KEY")        # or ws.setup() to see options\n'
            "\n"
            "# 2. Tag this work with the project that funded it (optional, once per\n"
            "#    workspace). The grant is stamped onto every record you save, so all\n"
            "#    your work stays traceable to the project that produced it.\n"
            'ws.project("101103997")              # e.g. an EU grant agreement number\n'
            "\n"
            "# 3. Convert raw cycler files (NEWARE/Biologic/Excel/... auto-detected)\n"
            "ws.convert()                         # -> bdf/*.bdf.csv\n"
            "\n"
            "# 4. Find your cell in the registry - or describe it yourself offline\n"
            'hits = ws.search("samsung inr21700 50e")   # fuzzy; [] if offline/no match\n'
            "spec = hits[0] if hits else battinfo.CellSpec(\n"
            '    manufacturer="Samsung SDI", model="INR21700-50E",\n'
            '    format="cylindrical", chemistry="Li-ion")\n'
            "\n"
            "# 5. Register the physical cells you tested, by the serials printed on\n"
            "#    them or labels only your lab uses: a cell's IRI comes from its spec\n"
            '#    and serial, so a bare "S1" mints the IRI of every other lab\'s "S1".\n'
            'ws.add("cell", spec=spec, serial_numbers=["MYLAB-50E-001", "MYLAB-50E-002", "MYLAB-50E-003"])\n'
            "\n"
            "# 6. Attach a test + data to a cell (explicit)\n"
            'ws.add("test", type="cycling", cell="MYLAB-50E-001", data="bdf/MYLAB-50E-001.bdf.csv")\n'
            "\n"
            "# 7. Publish (add zenodo=True for a citable DOI)\n"
            "ws.save()\n"
            'ws.publish(note="My cycling campaign, 2026")\n'
            "\n"
            "ws.status()                          # see it live\n"
            "# =================================================================="
        )

    def search(
        self,
        query: str | None = None,
        *,
        type: str = "cell-spec",
        serial: str | None = None,
        serials: builtins.list[str] | None = None,
        batch: str | None = None,
        threshold: float = 0.75,
    ) -> builtins.list[dict]:
        """Search the registry for resources of a given ``type``.

        One verb for every resource type; ``type`` selects which:

        - ``type="cell-spec"`` (default) — fuzzy text search by manufacturer/model;
          tolerates typos. ``ws.search("duracell mn2400")``
        - ``type="cell"`` — look up existing instances by ``serial``/``serials``/
          ``batch``. A serial matches a cell's serial number or name exactly; a
          6-char short ID on its own also matches the cell whose IRI or label
          carries it. ``serial`` and ``batch`` together narrow to both. Each hit
          names its publisher. ``ws.search(type="cell", serial="tpejqj")``
        - ``type="test"`` / ``"test-spec"`` / ``"dataset"`` — list records, optionally
          narrowed by ``query`` (title substring).

        Every result carries an ``"id"`` (canonical IRI) and a ``"type"`` key, and can
        be passed to :meth:`load` to reference it.
        """
        canon = _canon_type(type)

        # Cell specs — fuzzy text search (registry index, local-clone fallback).
        if canon == "cell_spec":
            if serial or serials or batch:
                raise ValueError("serial/serials/batch apply to type='cell'; use query=... for cell-spec.")
            terms = [t.lower() for t in (query or "").split()]
            if not terms:
                raise ValueError("type='cell-spec' needs a query, e.g. ws.search('duracell mn2400').")
            results = self._search_records(terms, threshold=threshold)
            for r in results:
                r["type"] = "cell-spec"
            if results:
                print(f"Found {len(results)} cell-spec match(es):")
                for r in results:
                    print(f"  {r.get('manufacturer', '')} {r.get('model', '')}  {r['id']}")
            else:
                print(f"No cell-spec match for {query!r}.")
                print("  Tip: ws.template('cell-spec', manufacturer='...', model='...')")
            return results

        # Cell instances — look up by serial / batch.
        if canon == "cell":
            reqs = list(serials or [])
            if serial:
                reqs.append(serial)
            if query:
                reqs.extend(query.split())
            if not reqs and not batch:
                raise ValueError("type='cell' needs serial=..., serials=[...], or batch=...")
            found = self._query_registry_cells(serials=reqs or None, batch_id=batch)
            for r in found:
                r["type"] = "cell"
            if found:
                print(f"Found {len(found)} cell instance(s):")
                for c in found:
                    publisher = f"  (published by {c['publisher_id']})" if c.get("publisher_id") else ""
                    print(f"  {c.get('name') or c.get('serial_number') or ''}  {c['id']}{publisher}")
            else:
                print("No matching cell instances found in the registry.")
            return found

        # Tests / test specs / datasets — registry list narrowed by title substring.
        label = _RESOURCE_TYPE_DISPLAY.get(canon, canon)
        rows = self._registry_resources(canon, q=query)
        out = [
            {
                "id": r.get("canonical_iri", ""),
                "type": label,
                "title": r.get("title", ""),
                "metadata": r.get("metadata") or {},
            }
            for r in rows
        ]
        if out:
            print(f"Found {len(out)} {label} record(s):")
            for r in out:
                print(f"  {r['title']}  {r['id']}")
        else:
            print(f"No {label} records found" + (f" matching {query!r}." if query else "."))
        return out

    def template(self, record_type: str | None = None, **kwargs) -> Path:
        """Write a fillable JSON template for a cell spec, test spec, or equipment spec.

        Fill in the generated file, then load it with ``ws.load(path)``.

        Examples::

            ws.template("cell-spec", manufacturer="Duracell", model="MN2400",
                        format="cylindrical", chemistry="Zn-MnO2")

            ws.template("test-spec",
                        name="CC discharge C/5",
                        type="capacity_check",
                        description="Constant-current discharge at C/5 to 2.5 V cutoff.")

            ws.template("equipment-spec",
                        name="SkyRC MC3000", manufacturer="SkyRC", model="MC3000",
                        equipment_class="cycler", channel_count=4)
        """
        if record_type is None:
            raise ValueError(
                "template() needs a record type: 'cell-spec', 'test-spec', or "
                "'equipment-spec'. Example: ws.template('cell-spec', manufacturer='...', model='...')"
            )
        rt = record_type.replace("_", "-")
        if rt in ("test-spec", "test-protocol"):  # accept old name during transition
            return self._template_test_spec(**kwargs)
        if rt == "equipment-spec":
            return self._template_equipment_spec(**kwargs)
        if rt != "cell-spec":
            raise ValueError(
                f"template() supports 'cell-spec', 'test-spec', and 'equipment-spec' (got {record_type!r})"
            )

        manufacturer = kwargs.get("manufacturer", "")
        model = kwargs.get("model", "")
        format_ = kwargs.get("format", "cylindrical")
        chemistry = kwargs.get("chemistry", "")

        template = {
            "manufacturer": manufacturer,
            "model": model,
            "format": format_,
            "chemistry": chemistry,
            "positive_electrode_basis": kwargs.get("positive_electrode_basis", None),
            "negative_electrode_basis": kwargs.get("negative_electrode_basis", None),
            "size_code": kwargs.get("size_code", None),
            "iec_code": kwargs.get("iec_code", None),
            "country_of_origin": kwargs.get("country_of_origin", None),
            # Electrode configuration: full_cell | half_cell | three_electrode_cell.
            # Leave null unless you know it; null is read as a full cell unless a
            # reference_electrode is present.
            "cell_configuration": kwargs.get("cell_configuration", None),
            "reference_electrode": kwargs.get("reference_electrode", None),
            "rechargeable": kwargs.get("rechargeable", None),
            "year": kwargs.get("year", None),
            "source_file": kwargs.get("source_file", None),
            "citation": kwargs.get("citation", None),
            "properties": _default_specs_for(format_, chemistry),
        }

        safe_mfr = re.sub(r"[^a-zA-Z0-9]", "-", manufacturer)
        safe_model = re.sub(r"[^a-zA-Z0-9]", "-", model)
        slug = f"{safe_mfr}-{safe_model}".strip("-") or "cell-spec"
        out_path = self._root / f"{slug}.cell-spec.json"
        if out_path.exists():
            print(f"  exists: {out_path.name}  (delete to regenerate)")
            return out_path
        out_path.write_text(json.dumps(template, indent=2), encoding="utf-8")
        print(f"  wrote: {out_path.name}")
        return out_path

    def _template_test_spec(self, **kwargs) -> Path:
        from battinfo.bundle import BatteryTestType  # noqa: PLC0415

        name = kwargs.get("name", "")
        test_type = kwargs.get("type", kwargs.get("kind", "")) or ""
        allowed_types = [t.value for t in BatteryTestType]
        if test_type and test_type not in allowed_types:
            raise ValueError(f"type must be one of: {', '.join(allowed_types)} (got {test_type!r}).")

        def _scalar(value: Any, unit: str) -> dict:
            return {"value": value, "unit": unit}

        def _window(value: Any, unit: str) -> dict:
            lo = hi = None
            if isinstance(value, dict):
                lo = value.get("min_value", value.get("min"))
                hi = value.get("max_value", value.get("max"))
            elif isinstance(value, (list, tuple)) and len(value) == 2:
                lo, hi = value
            return {"min_value": lo, "max_value": hi, "unit": unit}

        steps = kwargs.get("steps", kwargs.get("experiment"))
        template = {
            "name": name,
            "type": test_type,
            "_allowed_types": allowed_types,
            "description": kwargs.get("description", None),
            "instrument": kwargs.get("instrument", None),
            "atmosphere": kwargs.get("atmosphere", None),
            # PyBaMM-style step strings; ws.load() parses them into the
            # structured method. Leave empty if the method comes later.
            "steps": list(steps) if steps else [],
            "_steps_help": "PyBaMM-style strings, e.g. 'Discharge at C/5 for 10 hours "
            "or until 2.5 V', 'Hold at 4.2 V until C/50', 'Rest for 30 minutes'. "
            "Currents per area work too: 'Charge at 0.1 mA/cm2 until 4.2 V', "
            "'Hold at 4.2 V until 0.05 mA/cm2'.",
            # Every condition is a quantity: {value, unit} or {min_value, max_value, unit}.
            # Fill in what applies and delete the rest; null placeholders are
            # ignored by ws.load(). Keys starting with '_' are comments.
            "conditions": {
                "temperature": _scalar(kwargs.get("temperature_degC"), "degC"),
                "applied_pressure": _scalar(kwargs.get("applied_pressure_kilopascal"), "kPa"),
                "voltage_window": _window(kwargs.get("voltage_window_volt"), "V"),
                "soc_window": _window(kwargs.get("soc_window"), "%"),
                "c_rate": _scalar(kwargs.get("c_rate"), "A/Ah"),
                "d_rate": _scalar(kwargs.get("d_rate"), "A/Ah"),
            },
            "citation": kwargs.get("citation", None),
            "source_file": kwargs.get("source_file", None),
        }
        safe_name = re.sub(r"[^a-zA-Z0-9]", "-", name).strip("-") or "test-spec"
        out_path = self._root / f"{safe_name}.test-spec.json"
        if out_path.exists():
            print(f"  exists: {out_path.name}  (delete to regenerate)")
            return out_path
        out_path.write_text(json.dumps(template, indent=2), encoding="utf-8")
        print(f"  wrote: {out_path.name}")
        return out_path

    def _template_equipment_spec(self, **kwargs) -> Path:
        name = kwargs.get("name", "")
        template = {
            "name": name,
            "manufacturer": kwargs.get("manufacturer", ""),
            "model": kwargs.get("model", ""),
            "equipment_class": kwargs.get("equipment_class", "cycler"),
            "channel_count": kwargs.get("channel_count", None),
            "supported_chemistries": kwargs.get("supported_chemistries", []),
            "product_id": kwargs.get("product_id", None),
            "comment": kwargs.get("comment", None),
            "source_url": kwargs.get("source_url", None),
            "citation": kwargs.get("citation", None),
            # Datasheet quantities: value/min_value/max_value + unit (or
            # value_text for ranges that resist a clean unit).
            "property": kwargs.get(
                "property",
                {
                    "charge_current": {"min_value": None, "max_value": None, "unit": "A"},
                    "discharge_current": {"min_value": None, "max_value": None, "unit": "A"},
                    "channel_voltage_max": {"value": None, "unit": "V"},
                },
            ),
        }
        safe_name = re.sub(r"[^a-zA-Z0-9]", "-", name or "equipment-spec")
        out_path = self._root / f"{safe_name}.equipment-spec.json"
        if out_path.exists():
            print(f"  exists: {out_path.name}  (delete to regenerate)")
            return out_path
        out_path.write_text(json.dumps(template, indent=2), encoding="utf-8")
        print(f"  wrote: {out_path.name}")
        return out_path

    def load(self, source: str | Path | dict | builtins.list) -> Any:
        """Bring a record into the workspace — author a new one, or reference an existing one.

        - A **draft file** (``.cell-spec.json`` / ``.test-spec.json`` /
          ``.equipment-spec.json``) is authored as a NEW record and published
          when you save/submit. A draft reads every field of the record it
          becomes (``CellSpec``, ``TestSpec``, or the arguments of
          ``create_equipment_spec()``), the flat provenance keys
          (``source_url``, ``citation``, ...) and the spellings those models
          also take; a key with no home in the record raises ``ValueError``
          with a did-you-mean and the accepted keys, rather than being
          dropped. Keys starting with ``_`` are comments, and a cell-spec
          draft reads ``specs`` as the older spelling of ``properties``.
        - A **search result** (from :meth:`search`), or a **list** of results, is
          REFERENCED: brought into the session reusing the existing IRI and never
          re-published. A referenced cell is registered for test attachment.

        A relative draft path resolves against the workspace root, not the
        current directory.

        Loading the same draft or result again, as a notebook does when a cell
        is re-run, returns the record the session already holds rather than a
        second copy. A draft whose ``id`` a different record of the session
        already has raises ``ValueError``: one IRI names one record.

        A quantity's ``value`` holds a number only. A cell-spec or
        equipment-spec draft, or a found cell spec, written before 0.8.0 may
        hold text there: a numeric string (``"2.5"``) is read as the number,
        and other text moves to ``value_text`` with a warning. In a draft this
        covers every quantity, those in the electrodes, electrolyte,
        separator, housing and construction included. The equipment spec
        given to ``ws.add("equipment", spec=...)`` is read the same way.

        Example::

            spec = ws.load("duracell.cell-spec.json")               # author new
            spec = ws.load(ws.search("duracell mn2400")[0])         # reference existing
            cell = ws.load(ws.search(type="cell", serial="tpejqj")[0])
            cells = ws.load(ws.search(type="cell", batch="2026-02"))  # reference many
        """
        if isinstance(source, (list, tuple)):
            return [self.load(s) for s in source]
        if isinstance(source, dict):
            return self._load_from_result(source)
        source = Path(source) if not isinstance(source, Path) else source
        if not source.is_absolute():
            source = self._root / source
        if not source.exists():
            raise FileNotFoundError(f"Draft file not found: {source}")
        if ".test-spec" in source.name or ".test-protocol" in source.name:
            return self._load_test_spec(source)
        if ".equipment-spec" in source.name:
            return self._load_equipment_spec(source)
        return self._load_from_file(source)

    def add(self, record_type: str, **kwargs) -> builtins.list:
        """Add records to the workspace.

        **Cells** (``"cell"``)::

            ws.add("cell", spec=spec,
                   serial_numbers=["FAC-001", "FAC-002"], production_date="2026-01-15")

            # Reuse pre-allocated IRIs instead of minting new ones (parallel lists):
            ws.add("cell", spec=spec, serial_numbers=["FAC-001", "FAC-002"],
                   iris=["https://w3id.org/battinfo/cell/....", "https://w3id.org/battinfo/cell/...."])

            # ...or from a JSON map {serial: iri}:
            ws.add("cell", spec=spec, from_file="cell_iris.json")

        It returns the cells it names, in the order given; a serial (or name)
        the workspace already holds returns that cell, so a re-run adds nothing.

        **Tests** (``"test"``) — link a cell and its data explicitly::

            ws.add("test", type="capacity_check", cell="FAC-001",
                   data="data/FAC-001.csv", instrument="Maccor 4200")

        ``cell`` accepts a serial, name, short ID, IRI, ``Cell``, or search
        result, and is resolved in this session, locally, then in the registry
        (referenced if it already exists).  A serial or name has to match a
        cell's exactly; a six-character short ID on its own (``"063b77"``) also
        matches the cell whose IRI or label carries it, but ``"LAB-2025-000001"``
        never binds ``"LAB-2024-000001"``.  A label that several cells answer to,
        here or in the registry, raises ``ValueError`` listing them; pass the
        one you mean by its IRI.  When the registry binds the cell, a line names
        it and its publisher: lab labels such as ``"C01"`` are not scoped to a
        lab until 0.9, so check it is yours.  A cell found in the registry is
        kept as a read-only copy of its published record under
        ``.battinfo/references/``, so the strict
        save resolves it and a Zenodo deposit describes it with a stub node;
        the copy is never submitted or uploaded.  With ``registry_url=None``
        a cell this workspace does not hold cannot be checked, and ``ws.save()``
        reports the reference as unresolved.  ``data`` is a path or list of paths to files that
        exist; a relative path resolves against the workspace root, not the
        current directory, and a missing file raises ``FileNotFoundError``
        naming the path it resolved to.  The workspace registers each data
        file, and each original from ``raw=`` or :meth:`convert`, in
        ``.battinfo/deposit-files.json``, so a Zenodo deposit reads it even
        on a network share outside the workspace folder (see :meth:`zenodo`).
        ``type`` is the test
        type (``"cycling"``, ``"capacity_check"``, …); ``kind`` is accepted as an alias.
        ``channel`` attaches the test to an equipment channel — a channel IRI, a
        channel label, or ``"<unit>/CHn"`` (see ``ws.add("equipment", ...)``).

        For large batches you may instead pass ``datasets="glob"`` to match files to
        already-loaded cells: a file named after a cell's serial or name
        (``C01.csv``, ``C01.bdf.csv``) matches that cell. Otherwise a file named
        by a cell's 6-char short ID alone (``gm6pmr.csv``) matches the cell whose
        IRI or label carries it, and one whose name ends in it
        (``cycling-gm6pmr.csv``) the cell whose IRI it is the short ID of.

        The keywords a test takes are ``type`` (or ``kind``), ``cell``, ``data``,
        ``raw``, ``datasets``, ``spec`` (or ``protocol``), ``conformance``,
        ``name``, ``handle``, ``iri``, ``uid``, ``dataset_iris``, ``series_id``,
        ``instrument``, ``channel``, ``license``, ``description``, ``status``,
        ``started_at`` and ``ended_at``.
        Any other keyword raises ``TypeError`` naming the closest match and
        listing the accepted ones, before anything is created; every record type
        checks its keywords this way.

        - ``spec`` (``protocol`` is the same keyword) is the test spec the run
          followed: a ``battinfo.TestSpec``, saved with the test and linked to
          it, or the IRI of a test spec that is already saved or published.
        - ``description`` is free text about this run; ``status`` is
          ``"completed"`` unless you pass ``"planned"``, ``"running"``,
          ``"aborted"`` or ``"other"``.
        - ``instrument`` names the cycler the test ran on.
        - ``license`` sets the licence of the datasets made from ``data=``,
          instead of the workspace default.
        - ``raw`` attaches the original instrument file for each ``data`` file;
          without it the originals recorded by ``ws.convert()`` are attached.
        - ``conformance`` says whether the run followed its spec:
          ``"conformant"``, ``"non-conformant"``, ``"unknown"``, or a dict with
          ``status``, ``note`` and ``deviations``.
        - ``started_at`` and ``ended_at`` say when the run started and ended
          (Unix seconds, an ISO 8601 time or a datetime). Without them the times
          are read from a BDF data file that records them.

        A test's IRI names one run: it is seeded from the cell, the type, the
        protocol (the IRI of ``spec=`` whenever there is one) and the run, which
        is the location of the first ``data`` file, else ``started_at``, else
        the ``name`` you give. So renaming a test with data or a start time
        keeps its IRI, and a second run of one type on one cell, with its own
        data file, start time or name, gets its own IRI, in this session or a
        later one. A title the workspace generates (``C01 cycling``) and a time
        read from a data file never enter it. A test saved before 0.8.0
        changed this seed keeps the IRI it was saved under.

        ``series_id`` puts every dataset made from ``data=`` in a collection. Pass
        the collection's IRI; the collection itself is saved first, with
        ``battinfo.Dataset`` and ``battinfo.save_dataset``::

            ws.add("test", type="cycling", cell="FAC-001", data="data/FAC-001.csv",
                   series_id="https://w3id.org/battinfo/dataset/....")

        Membership is not identity, so ``series_id`` never changes the IRIs of the
        test or its datasets.

        **Names, handles and pinned identities.** Where a type takes ``name=`` it
        also takes ``handle=`` (cells take ``handles=[...]`` parallel to
        ``names=``), a short slug unique within a registry workspace. Handles are
        never generated here; build them with ``battinfo.naming.handle_for()``.
        Renaming a record must not move its IRI, so pin a published identity
        when the display name changes: ``iris=[...]`` for cells, ``uid=`` for
        material and electrode records, and ``dataset_iris=[...]`` for the data
        files of a test, whose dataset titles are made from the test's name.
        A test keeps its IRI when renamed; pin one published before 0.8.0 with
        ``iri=``/``uid=`` when you rebuild it in a new folder::

            ws.add("test", type="gitt", cell="063b77", name="Graphite AQ-1 cell 063b77 GITT test",
                   handle="flores-ocv/graphite-aq-1-063b77-gitt-test",
                   iri="https://w3id.org/battinfo/test/....")

        **Running a call again.** The same call run a second time in one
        session, as when a notebook cell is re-run, adds nothing: a test with
        the same fields and data files returns the test the session already
        holds, and cells already in the session are skipped. A pinned IRI that
        a different record of the session already has raises ``ValueError``.

        **Equipment** (``"equipment"``) — register a physical unit + its channels::

            ws.add("equipment", spec="skyrc-mc3000.json",
                   serial_number="MC3K-2026-0001", name="Cycler 1", location="Lab B")

        ``spec`` accepts a canonical equipment-spec record dict, a path to one, or
        the IRI of one already saved in this workspace.  ``channels=N`` overrides
        the spec's ``channel_count``.  Re-running with the same inputs is
        idempotent (deterministic equipment + channel IRIs).  A spec saved
        before 0.8.0 may hold text in a quantity's ``value``: a numeric string
        is read as the number and other text moves to ``value_text``, with a
        warning, and the saved spec is rewritten that way.
        """
        rt_key = str(record_type).strip().lower().replace("_", "-")
        if rt_key == "equipment":
            _check_add_keywords("equipment", _signature_keywords(self._add_equipment), kwargs)
            return self._add_equipment(**kwargs)
        if rt_key in ("material-spec", "material", "electrode-spec", "electrode"):
            from battinfo.api._components import (  # noqa: PLC0415
                ElectrodeInput,
                ElectrodeSpecInput,
                MaterialInput,
                MaterialSpecInput,
            )
            from battinfo.bundle import _model_keywords  # noqa: PLC0415

            # The component paths hand their keywords to an input model. The
            # instance paths set the spec link themselves from spec=, so the
            # model's own spec-id keywords are not theirs to take.
            if rt_key == "material-spec":
                _check_add_keywords("material_spec", _model_keywords(MaterialSpecInput), kwargs)
                return self._add_material_spec(**kwargs)
            if rt_key == "electrode-spec":
                _check_add_keywords("electrode_spec", _model_keywords(ElectrodeSpecInput), kwargs)
                return self._add_electrode_spec(**kwargs)
            if rt_key == "material":
                linked = {"material_spec_id", "spec_id"}
                accepted = [
                    *_signature_keywords(self._add_material),
                    *(k for k in _model_keywords(MaterialInput) if k not in linked),
                ]
                _check_add_keywords("material", accepted, kwargs)
                return self._add_material(**kwargs)
            linked = {"electrode_spec_id", "spec_id"}
            accepted = [
                *_signature_keywords(self._add_electrode),
                *(k for k in _model_keywords(ElectrodeInput) if k not in linked),
            ]
            _check_add_keywords("electrode", accepted, kwargs)
            return self._add_electrode(**kwargs)
        if rt_key in ("parameter-set", "parameters"):
            from battinfo.api._parameters import _record_from_parameter_set  # noqa: PLC0415

            accepted = [*_signature_keywords(self._add_parameter_set), *_signature_keywords(_record_from_parameter_set)]
            _check_add_keywords("parameter_set", accepted, kwargs)
            return self._add_parameter_set(**kwargs)
        try:
            rt = _canon_type(record_type)
        except ValueError:
            rt = None
        if rt == "cell":
            _check_add_keywords("cell", _signature_keywords(self._add_cell_instances), kwargs)
            return self._add_cell_instances(**kwargs)
        if rt == "test":
            _check_add_keywords("test", _signature_keywords(self._add_tests), kwargs)
            return self._add_tests(**kwargs)
        raise ValueError(
            f"add() supports type 'cell', 'test', 'equipment', 'material_spec', "
            f"'material', 'electrode_spec', 'electrode', and 'parameter_set' "
            f"(got {record_type!r}). "
            "Author a cell-spec/test-spec with ws.load(<draft file>); attach datasets "
            "via ws.add('test', data=...); register lab equipment via "
            "ws.add('equipment', spec=..., serial_number=...); author materials via "
            "ws.add('material_spec', name=..., kind=...) and "
            "ws.add('material', spec=..., lot=...); author electrodes via "
            "ws.add('electrode_spec', name=..., kind=...) and "
            "ws.add('electrode', spec=..., batch=...); collate parameter claims via "
            "ws.add('parameter_set', name=..., material=..., claims=[...])."
        )

    def save(self, validation_policy: str = "strict", mode: str = "upsert") -> dict:
        """Save all records and rebuild the workspace index.

        Returns a summary dict with counts of written records. A record that
        the index rejects under ``validation_policy`` (a reference that does not
        resolve, for example) is still written, but is listed as ``[failed]``
        with its error, and its summary item carries ``failed`` and ``error``.
        The next ``ws.submit()`` sends the records saved in this call and the
        equipment records that ``ws.add("equipment", ...)`` wrote in this
        session. Records left over from previous sessions in the same
        directory are ignored.

        ``mode`` controls how an existing on-disk record with the same IRI is
        treated. The default ``"upsert"`` updates it in place (the normal
        edit-and-resave loop). Pass ``"create_only"`` to instead refuse to touch
        any record that already exists, so a fresh authoring run cannot silently
        overwrite records left by a previous session.
        """
        # Stamp the workspace's funding project (grant) and every contributor
        # (ORCID) onto each record as it is written, for attribution. Applying the
        # stamp to the candidate before it is saved — rather than rewriting the
        # file afterwards — lets an unchanged, already-stamped re-save report
        # [unchanged] and skip the write entirely.
        stamp_fn, stamp_counts = self._record_stamp()
        # Side records (materials, electrodes) are written first (same stamp path)
        # so the engine's index rebuild picks them up and an instance's spec
        # reference resolves on disk.
        side_results = self._save_side_records(mode=mode, validation_policy=validation_policy, stamp=stamp_fn)
        result = self._ws.save(
            mode=mode,
            resolve_references=False,
            validation_policy=validation_policy,
            stamp=stamp_fn,
        )
        result.update(side_results)
        # How many records the funding block actually reached this save: every
        # candidate is stamped, but only newly-created or genuinely-changed records
        # are written — an unchanged re-save reaches zero, so it prints nothing.
        stamped = 0
        _STAMPED_KEYS = ("cell_specs", "cell_instances", "tests", "datasets", "test_specs", *_SIDE_RECORD_KEYS)
        if stamp_counts["funding"]:
            for key in _STAMPED_KEYS:
                for item in result.get(key, []):
                    if isinstance(item, dict) and (item.get("status") == "created" or item.get("content_changed")):
                        stamped += 1
        # Track the exact files written so submit() only sends this session's work.
        # ws.add("equipment") wrote its records itself, so they start the set.
        self._session_paths = set(self._added_paths)
        for key in _STAMPED_KEYS:
            for item in result.get(key, []):
                p = item.get("path") if isinstance(item, dict) else str(item)
                if p:
                    self._session_paths.add(Path(p))

        # Build id -> human name from the finalized in-memory objects so the
        # confirmation shows what was written, not just counts.
        name_by_id: dict[str, str] = {}
        for spec_obj in self._ws.cell_specs:
            if spec_obj.id:
                name_by_id[spec_obj.id] = spec_obj.name or getattr(spec_obj, "model", None) or "cell spec"
        for cell_obj in self._ws.cells:
            if cell_obj.id:
                name_by_id[cell_obj.id] = getattr(cell_obj, "serial_number", None) or cell_obj.name or "cell"
        for tspec_obj in self._ws.test_specs:
            if tspec_obj.id:
                name_by_id[tspec_obj.id] = tspec_obj.name or "test spec"
        for test_obj in self._ws.tests:
            if test_obj.id:
                name_by_id[test_obj.id] = test_obj.name or "test"
        for ds_obj in self._ws.datasets:
            if ds_obj.id:
                name_by_id[ds_obj.id] = ds_obj.name or "dataset"
        for ms in self._material_specs:
            body = ms.get("material_spec", {})
            if body.get("id"):
                name_by_id[body["id"]] = body.get("name") or "material spec"
        for m in self._materials:
            body = m.get("material", {})
            if body.get("id"):
                name_by_id[body["id"]] = body.get("lot_id") or body.get("name") or "material"
        for es in self._electrode_specs:
            body = es.get("electrode_spec", {})
            if body.get("id"):
                name_by_id[body["id"]] = body.get("name") or "electrode spec"
        for e in self._electrodes:
            body = e.get("electrode", {})
            if body.get("id"):
                name_by_id[body["id"]] = body.get("batch_id") or body.get("lot_id") or body.get("name") or "electrode"
        for ps in self._parameter_sets:
            body = ps.get("parameter_set", {})
            if body.get("id"):
                name_by_id[body["id"]] = body.get("name") or "parameter set"

        total = sum(len(result.get(key, [])) for key, _ in _SAVE_DISPLAY)
        print(f"Saved {total} record(s) under {self._ws.source_root}:")
        # Records the save-time index rejected (a reference that does not resolve,
        # a schema error) are written but not valid: list them as failed, with the
        # error, and mark them in the returned summary.
        failures = self._index_failures(result)
        failed_count = len(failures)
        for key, label in _SAVE_DISPLAY:
            items = [i for i in result.get(key, []) if isinstance(i, dict)]
            hidden = 0
            for position, item in enumerate(items):
                failure = failures.pop(_path_key(item["path"]), None) if item.get("path") else None
                if failure is not None:
                    item["failed"] = True
                    item["error"] = failure["error"]
                elif position >= 10:
                    hidden += 1
                    continue
                rid = item.get("id", "") or ""
                name = name_by_id.get(rid) or (rid.rsplit("/", 1)[-1] if rid else "?")
                status = "failed" if failure is not None else item.get("status", "")
                # A same-IRI upsert whose content is unchanged is a no-op, not an
                # update: report it honestly so an identical re-save reads as such.
                if status == "updated" and item.get("content_changed") is False:
                    status = "unchanged"
                rel = self._rel_to_root(item.get("path", ""))
                print(f"  {label:11} {name[:36]:36} [{status}]  {rel}")
                if failure is not None:
                    for line in str(failure["error"]).splitlines():
                        print(f"      {line.strip()}")
            if hidden:
                print(f"  {label:11} ... +{hidden} more")
        if failures:
            # Rejected records this save did not write (left by an earlier session).
            print("  Other records in the records folder that failed validation:")
            for failure in failures.values():
                first_line = (str(failure.get("error", "")).splitlines() or [""])[0]
                print(f"    {failure.get('file')}: {first_line}")
        if stamped:
            ref = self._get_project()
            label = ref.summary() if ref else "project"
            print(f"  funding:    {label} stamped onto {stamped} record(s)")
        if failed_count:
            print(
                f"\n  {failed_count} record(s) failed validation under the {validation_policy} policy "
                "and are marked [failed] above."
            )
            print(
                "  They are written but not valid: fix the errors, then run ws.save() again "
                "before ws.publish() or ws.submit()."
            )
        elif not getattr(self, "_publishing", False):
            # Suppressed mid-publish: telling the user to run ws.publish()
            # from inside ws.publish() right before a credentials error reads
            # as mockery (red-team W1.3).
            print("\n  Next: ws.list(verbose=True) to inspect, or ws.publish() to publish.")
        return result

    def _index_failures(self, result: dict) -> dict[str, dict]:
        """The save-time index failures of *result*, keyed by the record file they name."""
        failures: dict[str, dict] = {}
        for failure in (result.get("index") or {}).get("failures") or []:
            if not isinstance(failure, dict):
                continue
            path = Path(str(failure.get("file", "")))
            if not path.is_absolute():
                path = self._ws.source_root / path
            error = str(failure.get("error", ""))
            if not self._registry_url and "not found in source_root" in error:
                # Offline, a reference to a record published elsewhere stays an error.
                failure["error"] = (
                    f"{error} It could not be checked offline: this workspace has no "
                    "registry_url, so a published record cannot be looked up. Open the "
                    "workspace with a registry_url, or save the referenced record here first."
                )
            failures[_path_key(path)] = failure
        return failures

    def _save_side_records(self, *, mode: str, validation_policy: str, stamp: Any = None) -> dict:
        """Write queued material and electrode records through the shared stamp path.

        Materials and electrodes are not engine model objects, so they are
        persisted here rather than by ``self._ws.save``. They flow through the SAME
        ``stamp`` callback as every other record (PR #324 pre-compare stamp), so
        funding / contributor / license reach them too, and an unchanged
        already-stamped re-save is reported ``unchanged`` — no compare-before-stamp
        bug. Ordering matters: material specs, then material instances, then
        electrode specs (which may reference a material spec), then electrode
        batches — every reference resolves on disk before the record naming it is
        validated under strict policy.
        """
        from battinfo.api import (  # noqa: PLC0415
            save_electrode,
            save_electrode_spec,
            save_material,
            save_material_spec,
            save_parameter_set,
        )

        source_root = self._ws.source_root

        def _write(saver: Any, records: builtins.list[dict]) -> builtins.list[dict]:
            return [
                saver(
                    rec,
                    source_root=source_root,
                    mode=mode,
                    resolve_references=False,
                    validation_policy=validation_policy,
                    stamp=stamp,
                )
                for rec in records
            ]

        return {
            "material_specs": _write(save_material_spec, self._material_specs),
            "materials": _write(save_material, self._materials),
            "electrode_specs": _write(save_electrode_spec, self._electrode_specs),
            "electrodes": _write(save_electrode, self._electrodes),
            "parameter_sets": _write(save_parameter_set, self._parameter_sets),
        }

    def _rel_to_root(self, path: str) -> str:
        """Render *path* relative to the workspace root for compact display."""
        if not path:
            return ""
        try:
            return str(Path(path).relative_to(self._root))
        except ValueError:
            return path

    def publish(
        self,
        note: str | None = None,
        *,
        zenodo: bool = False,
        sandbox: bool = False,
        creators: builtins.list[dict] | None = None,
        doi: str | None = None,
        only: str | builtins.list[str] | None = None,
        publication_mode: str = STAGED_PUBLICATION_MODE,
        allow_partial: bool = False,
        allow_local_files: bool = False,
        archive_hosted_files: bool = False,
    ) -> builtins.list[dict]:
        """Save and submit the workspace in one call (staged for review by default).

        The common path — save and submit to the registry's review queue::

            ws.publish(note="LFP aging campaign, Feb 2026")

        Archive on Zenodo first (mints a citable DOI), then publish with the DOI
        recorded in provenance::

            ws.publish(zenodo=True, note="...")

        This is equivalent to running, in order::

            ws.save()
            ws.upload()                                 # only with zenodo=True and R2 storage
            ws.zenodo(publish=True, creators=creators)  # only when zenodo=True
            ws.submit(note=note, doi=...)

        With ``zenodo=True`` the Zenodo token and the deposit's creators are
        looked up first, and the file that records the workspace's Zenodo
        record is read (see :meth:`zenodo`), so a call that fails any of these
        is refused before anything is saved, uploaded or sent. A deposit that
        would archive data files hosted in R2 storage is refused after the
        save, before anything is uploaded or sent, unless
        ``archive_hosted_files=True``.

        For finer control — e.g. reviewing a Zenodo draft before it goes live —
        call those four steps individually instead.

        Parameters
        ----------
        note:
            Provenance note attached to every submitted record.
        zenodo:
            Upload data files and archive on Zenodo before submitting.  Publishes
            the Zenodo deposit immediately and records its DOI in each record
            the deposit holds.
            A deposit of more than 90 data files is zipped by test kind, and the
            registry cannot yet point at files inside an archive, so without R2
            object storage such a workspace is refused before anything is
            deposited: publish it with ``ws.zenodo(publish=True)`` alone, or
            split it.
        sandbox:
            Use ``sandbox.zenodo.org`` (only relevant with ``zenodo=True``).
            A sandbox deposit is a dry run: it leaves the records pointing at
            their local files and records no DOI, and the registry refuses
            local files. So unless R2 object storage is configured, or
            ``allow_local_files=True``, the call is refused before anything is
            saved: use ``ws.zenodo(sandbox=True)`` for the dry run.
        creators:
            The Zenodo deposit's creators (only with ``zenodo=True``), as
            :meth:`zenodo` takes them. Without them the workspace contributors
            (:meth:`contributor`) are the creators, and without those the creator
            set with ``battinfo config set creator``.
        doi:
            A pre-existing DOI to attach (e.g. from a Zenodo draft you reviewed).
        only:
            Restrict submission to one or more record types (see :meth:`submit`).
        allow_local_files:
            The registry step refuses records that point at local files (see
            :meth:`submit`); ``zenodo=True`` deposits the files first and points
            the records at the deposited copies. ``True`` lifts the check, for a
            local test registry only.
        archive_hosted_files:
            Archive data files hosted in R2 storage in the Zenodo deposit (only
            with ``zenodo=True``; see :meth:`zenodo`). With R2 storage
            configured, ``zenodo=True`` puts the data files in R2 with
            :meth:`upload` before the deposit, so it needs this too. Without
            it such a call is refused after the save, before anything is
            uploaded or sent, and the refusal names the files.
        """
        if zenodo:
            # A deposit without a token or a creator, or one whose recorded
            # Zenodo record cannot be read, is refused before the save, the zip
            # check and the R2 upload, not by ws.zenodo() after them.
            self._zenodo_token(None, sandbox)
            creators = self._deposit_creators(creators)
            self._load_zenodo_state(zenodo_environment(sandbox))
            if sandbox and not allow_local_files and not self._r2_configured():
                raise ValueError(
                    "Refusing to publish: a sandbox deposit is a dry run, so it leaves the records "
                    "pointing at their local data files, and the registry refuses those. Nothing was "
                    "saved, deposited or sent. Use ws.zenodo(sandbox=True) for the dry run, and "
                    "ws.publish(zenodo=True) to publish (allow_local_files=True is for a local test "
                    "registry only)."
                )
        self._publishing = True
        try:
            self.save()
        finally:
            self._publishing = False
        if zenodo:
            # Both checks below come before the R2 upload and the deposit.
            plan = self._deposit_file_plan(
                self._ws.source_root,
                report=False,
                measure=False,
                context=self._deposit_context(sandbox=sandbox),
            )
            if not archive_hosted_files:
                # Files hosted in R2 go into the deposit only when asked for,
                # those ws.upload() is about to put there included.
                self._refuse_hosted_files(plan, verb="publish", from_publish=True)
            if not allow_local_files and not self._r2_configured():
                # Records point at Zenodo's copies of their files; a zipped deposit has
                # none to point at. Refuse before anything is deposited.
                self._refuse_a_zipped_deposit(plan)
            if self._r2_configured():
                self.upload()
            else:
                print(
                    "  No R2 object storage configured - Zenodo will host the "
                    "data files (records get the Zenodo download URLs). R2 is "
                    "only needed for team-internal registry hosting."
                )
            # ws.submit() takes the DOI from the deposit's record in
            # .battinfo/zenodo.json, and puts it on the records the deposit holds.
            self.zenodo(publish=True, sandbox=sandbox, creators=creators, archive_hosted_files=archive_hosted_files)
        return self.submit(
            note=note,
            doi=doi,
            only=only,
            publication_mode=publication_mode,
            allow_partial=allow_partial,
            allow_local_files=allow_local_files,
        )

    def status(
        self,
        registry_url: str | None = None,
        workspace_id: str | None = None,
    ) -> builtins.list[dict]:
        """Show this workspace's submissions and their live status on the registry.

        Groups by status (published first), so you can see at a glance what is
        live, what is still in the review queue, and what failed.

        The registry is *registry_url*, else the workspace's; a workspace opened
        with ``registry_url=None`` takes ``BATTINFO_REGISTRY_URL`` or raises.

        Example::

            ws.status()
        """
        import urllib.request

        url = self._require_registry(registry_url, "ws.status()")
        wid = self._credential("BATTINFO_WORKSPACE_ID", explicit=workspace_id)
        if not wid:
            raise RuntimeError(
                "workspace_id required. Run ws.login(api_key=...) once - it stores "
                "your workspace automatically - or set BATTINFO_WORKSPACE_ID."
            )

        endpoint = f"{url.rstrip('/')}/workspaces/{wid}/submissions"
        # The registry's workspace views are credentialed (they list staged, not yet
        # public submissions): send the publisher key from login(), or the admin token.
        req = urllib.request.Request(endpoint, headers=self._registry_read_headers())
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                submissions = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                print(
                    "  The registry needs your publisher API key to list this workspace. "
                    "Run ws.login(api_key=...) or set BATTINFO_API_KEY."
                )
                return []
            print(f"  Could not reach registry at {url}: {exc}")
            return []
        except Exception as exc:
            print(f"  Could not reach registry at {url}: {exc}")
            return []

        if not submissions:
            print(f"No submissions for workspace {wid!r} yet. Run ws.publish() or ws.submit().")
            return submissions

        by_status: dict[str, list[dict]] = {}
        for s in submissions:
            by_status.setdefault(s.get("status", "unknown"), []).append(s)

        print(f"Workspace {wid}: {len(submissions)} submission(s)")
        order = ["published", "validated", "publishing", "queued", "rejected", "failed"]
        for status in order + [s for s in by_status if s not in order]:
            group = by_status.get(status)
            if not group:
                continue
            print(f"  {status} ({len(group)}):")
            for s in group[:15]:
                rt = s.get("resource_type", "")
                label = s.get("title") or s.get("source_local_id") or s.get("id", "")
                print(f"    [{rt}] {label}")
            if len(group) > 15:
                print(f"    ... +{len(group) - 15} more")
        return submissions

    def list(self, verbose: bool = False) -> dict:
        """List all records saved in the workspace.

        Prints a summary grouped by record type.  Use ``verbose=True`` to
        show individual record names and IRIs.

        Returns a dict of ``{record_type: [{"name": ..., "id": ..., ...}]}``
        that can be inspected programmatically.

        Example::

            ws.list()
            ws.list(verbose=True)
        """
        records_dir = self._ws.source_root
        summary: dict[str, list[dict]] = {}

        _TYPE_KEYS = {
            "cell-spec": ("cell_spec", "name", "id"),
            "cell-instance": ("cell_instance", "serial_number", "id"),
            "test": ("test", "name", "id"),
            "dataset": ("dataset", "name", "id"),
            "test-protocol": ("test_spec", "name", "id"),
            "material-spec": ("material_spec", "name", "id"),
            "material": ("material", "name", "id"),
        }

        for subdir, (record_key, name_field, id_field) in _TYPE_KEYS.items():
            d = records_dir / subdir
            if not d.exists():
                continue
            items: list[dict] = []
            for f in sorted(d.glob("*.json")):
                try:
                    raw = json.loads(f.read_text(encoding="utf-8"))
                    inner = raw.get(record_key, {}) or {}
                    name = inner.get(name_field) or inner.get("model") or f.stem
                    iri = inner.get(id_field, "")
                    session = f in self._session_paths
                    items.append({"name": name, "id": iri, "file": f.name, "session": session})
                except Exception:
                    items.append({"name": f.stem, "id": "", "file": f.name, "session": f in self._session_paths})
            if items:
                summary[subdir] = items

        if not summary:
            print("  Workspace is empty -- run ws.save() first.")
            return summary

        total = sum(len(v) for v in summary.values())
        print(f"Workspace: {self._ws.source_root}")
        print(f"  {total} record(s) across {len(summary)} type(s):\n")
        for rtype, items in summary.items():
            print(f"  {rtype} ({len(items)})")
            if verbose:
                for i in items:
                    tag = " [this session]" if i["session"] else ""
                    print(f"    {i['name']}{tag}")
                    if i["id"]:
                        print(f"      {i['id']}")
            else:
                names = [i["name"] for i in items[:5]]
                if len(items) > 5:
                    names.append(f"... +{len(items) - 5} more")
                print(f"    {', '.join(names)}")
        if self._session_paths:
            sess_count = sum(1 for v in summary.values() for i in v if i["session"])
            print(f"\n  * {sess_count} record(s) from this session (will be submitted by ws.submit())")
        return summary

    def reload_cells(self) -> int:
        """Load previously saved cell instances into the matching index.

        Call this at the start of a test notebook when the cell instances were
        saved in a previous session.  Populates the serial-number → cell index
        so ``ws.add("test", ...)`` can match dataset files to cells.

        Does **not** re-add cells to the workspace for saving — only the
        new test records created in this session will be written by
        ``ws.save()``.

        Example::

            ws = battinfo.workspace(".")
            ws.reload_cells()           # restore index from saved records
            ws.add("test", ...)         # now files match cells correctly
            ws.save()
            ws.submit()
        """
        ci_dir = self._ws.source_root / "cell-instance"
        if not ci_dir.exists():
            print("  No saved cell instances found.")
            return 0
        count = self._index_saved_cells()
        print(f"  Loaded {count} cell instance(s) into matching index.")
        return count

    def _unsaved_cell_iris(self) -> set[str]:
        """The IRIs the next save mints for the session's cells that have none yet.

        The save's own finalize pass, run on copies (``Workspace._finalized_records``),
        so a cell whose spec collides with another spec of the session, or
        keeps an IRI saved before, is predicted as the save mints it. When that
        pass refuses the session as it stands (a save would raise too), each
        cell is predicted from its own seed and its spec's natural key.
        """
        engine = self._ws
        try:
            finalized = engine._finalized_records()
        except (TypeError, ValueError):
            pass
        else:
            return {
                item.id
                for original, item in zip(engine.cells, finalized["cells"], strict=True)
                if original.id is None and item.id
            }
        specs: dict[int, Any] = {}
        iris: set[str] = set()
        for cell in engine.cells:
            if cell.id is not None:
                continue
            spec = cell.cell_spec
            if spec is not None and getattr(spec, "id", None) is None and id(spec) not in specs:
                specs[id(spec)] = engine._finalize_cell_spec(spec, record_roots=[engine.source_root])
            try:
                minted = engine._finalize_cell(cell, specs).id
            except (TypeError, ValueError):
                continue
            if minted:
                iris.add(minted)
        return iris

    def _index_cell(self, cell: Any, *keys: str | None) -> None:
        """Index ``cell`` under the labels it answers to (its serial number and name).

        A cell's IDENTITY is its serial number; its name is display text, so a
        batch may share one public label across many serials. Indexing never
        decides between two cells that share a label: :meth:`_cells_labelled`
        finds every cell a label names, and :meth:`_resolve_cell` then refuses
        to guess.
        """
        labels = [key for key in keys if key]
        if not labels:
            return  # a cell known only by its IRI is looked up by that IRI each time
        entry = next((item for item in self._indexed_cells if item[0] is cell), None)
        if entry is None:
            self._indexed_cells.append((cell, labels))
        else:
            entry[1].extend(label for label in labels if label not in entry[1])

    def _cells_labelled(self, label: str) -> builtins.list[Any]:
        """Every cell this session indexes that *label* names, exact matches first.

        A cell whose serial number or name is *label* matches. Only when none
        does, and *label* is a short ID on its own, does a cell match whose IRI
        or label carries that short ID. See ``_cells_named_by``; a data file's
        name is matched by :meth:`_cells_for_data_file`.
        """
        cells = [(labels, getattr(cell, "id", None)) for cell, labels in self._indexed_cells]
        short_id = label if _is_short_id(label) else None
        return [self._indexed_cells[i][0] for i in _cells_named_by(label, cells, short_id)]

    def _index_saved_cells(self) -> int:
        """Load cell instances saved on disk into the serial → cell index (quiet).

        Shared core of :meth:`reload_cells` and :meth:`_rehydrate_cell_index`;
        scans ``.battinfo/records/cell-instance/`` and returns the count loaded.
        A saved cell the session already holds is counted but not loaded
        again, so reading the records back never gives one cell two objects:
        one held under its IRI, and one not saved yet whose next save mints the
        IRI the saved cell has. Marks the index as rehydrated so
        :meth:`_rehydrate_cell_index` becomes a no-op afterwards.
        """
        from battinfo.bundle import Cell

        self._cells_rehydrated = True
        ci_dir = self._ws.source_root / "cell-instance"
        if not ci_dir.exists():
            return 0

        held = {getattr(cell, "id", None) for cell, _ in self._indexed_cells} - {None}
        held |= self._unsaved_cell_iris()
        count = 0
        for src in sorted(ci_dir.glob("*.json")):
            try:
                raw = json.loads(src.read_text(encoding="utf-8"))
                ci = raw.get("cell_instance", {})
                if ci.get("id") and ci.get("id") in held:
                    count += 1
                    continue
                cell = Cell(
                    id=ci.get("id"),
                    cell_spec_id=ci.get("cell_spec_id"),
                    name=ci.get("name"),
                    serial_number=ci.get("serial_number"),
                    batch_id=ci.get("batch_id"),
                    working_electrode_id=ci.get("working_electrode_id"),
                    counter_electrode_id=ci.get("counter_electrode_id"),
                )
                self._index_cell(cell, ci.get("serial_number"), ci.get("name"))
                count += 1
            except Exception as exc:
                print(f"  WARNING: could not load {src.name} -- {exc}")

        return count

    def _rehydrate_cell_index(self) -> None:
        """Lazily populate the serial → cell index from records saved on disk.

        Cells authored in a previous session live under
        ``.battinfo/records/cell-instance/`` but are absent from this process's
        in-memory index, so ``ws.add("test", cell="S1")`` in a fresh session
        would otherwise fail to resolve them. Runs the disk scan at most once per
        workspace instance; a no-op when nothing is saved.
        """
        if self._cells_rehydrated:
            return
        self._index_saved_cells()

    _RESOURCES_PAGE_LIMIT = 1000  # registry's maximum limit= for /resources

    def _fetch_resource_pages(self, params: dict, *, timeout: int = 60) -> builtins.list[dict]:
        """GET /resources with exhaustive offset pagination.

        A single GET of /resources is capped by the server (default 100 rows,
        newest first), so listings silently truncate once the corpus outgrows
        one page — the trap that made lookups miss registered records and
        re-mint duplicate IRIs. Pages by advancing offset until a short page
        signals exhaustion. A server that ignores offset (pre-pagination
        deployment) returns the same page again; that repeat is detected and
        the loop stops with the rows it has rather than spinning forever.
        """
        import urllib.parse
        import urllib.request

        base = self._registry_url  # once, so every page comes from the same registry
        rows: list[dict] = []
        prev_page: list | None = None
        offset = 0
        while True:
            query = dict(params, limit=self._RESOURCES_PAGE_LIMIT, offset=offset)
            url = f"{base}/resources?" + urllib.parse.urlencode(query)
            req = urllib.request.Request(url, headers={"User-Agent": "battinfo-client/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                page = json.loads(resp.read().decode())
            if not isinstance(page, list) or (offset and page == prev_page):
                return rows
            rows.extend(page)
            if len(page) < self._RESOURCES_PAGE_LIMIT:
                return rows
            prev_page = page
            offset += self._RESOURCES_PAGE_LIMIT

    def _registry_resources(self, resource_type: str, q: str | None = None) -> builtins.list[dict]:
        """GET /resources?resource_type=... [&q=...] — raw summaries, [] if unreachable."""
        if not self._registry_url:
            print("  No registry configured (registry_url=None).")
            return []
        params = {"resource_type": resource_type}
        if q:
            params["q"] = q
        try:
            return self._fetch_resource_pages(params, timeout=30)
        except Exception as exc:  # registry down / network - degrade gracefully
            print(f"  Registry unreachable ({exc}).")
            return []

    def _query_registry_cells(
        self,
        *,
        serials: builtins.list[str] | None = None,
        batch_id: str | None = None,
    ) -> builtins.list[dict]:
        """Resolve published cell instances by serial or name, short ID, and batch.

        Each label in *serials* matches the cells whose serial number or name
        is exactly that label. Only when none is, and the label is a short ID
        on its own (six characters such as ``"tpejqj"``), does it match the
        cells whose IRI, serial or name carries that short ID; a label that
        merely ends like another cell's serial never matches it. With
        *batch_id*, only cells of that batch count, together with *serials*
        when both are given. Returns one dict per match, in the registry's
        order: id (canonical IRI), name, serial_number, batch_id, cell_spec_id,
        manufacturer, model, title and publisher_id.
        """
        wanted = [s for s in (serials or []) if s]
        rows: list[dict] = []
        for r in self._registry_resources("cell"):
            meta = r.get("metadata") or {}
            if batch_id is not None and meta.get("batch_id") != batch_id:
                continue
            rows.append(
                {
                    "id": r.get("canonical_iri", ""),
                    "name": meta.get("name") or r.get("title"),
                    "serial_number": meta.get("serial_number"),
                    "batch_id": meta.get("batch_id"),
                    "cell_spec_id": meta.get("cell_spec_id"),
                    "manufacturer": meta.get("manufacturer"),
                    "model": meta.get("model"),
                    "title": r.get("title", ""),
                    "publisher_id": r.get("publisher_id"),
                }
            )
        if not wanted:
            return rows
        cells = [([text for text in (row["serial_number"], row["name"]) if text], row["id"]) for row in rows]
        chosen: set[int] = set()
        for token in wanted:
            chosen.update(_cells_named_by(token, cells, token if _is_short_id(token) else None))
        return [row for i, row in enumerate(rows) if i in chosen]

    def import_(
        self,
        source: str,
        sandbox: bool = False,
        token: str | None = None,
    ) -> dict:
        """Import workspace records from a ``battinfo.json`` document.

        Parses the JSON-LD `@graph`, reconstructs cell specs, cell instances,
        tests, and datasets, then populates this workspace ready for
        ``ws.save()`` and ``ws.submit()``.  All canonical IRIs from the source
        document are preserved — no new IRIs are minted. A test that produced
        several data files comes back as one test, with one dataset per file.
        Importing the same deposit again in one session reuses the records the
        first import made. A deposit that gives an IRI the session already
        holds to a different record raises ``ValueError`` and imports nothing.
        A deposit written before 0.8.0 may carry text as a quantity's number:
        a numeric string (``"2.5"``) is read as the number, and other text
        moves to ``value_text`` with a warning.

        A cell spec's chemistry is the first class of its described battery
        that the chemistry vocabulary names, which is the declared chemistry's;
        its electrode bases come from the classes of its electrode nodes and
        its cell configuration from the half-cell or three-electrode classes.
        A deposit written before 0.8.0 also carries classes its electrodes
        added whatever the chemistry, and those are not read as the chemistry.

        Parameters
        ----------
        source:
            One of:

            * A **Zenodo record ID** (string of digits, e.g. ``"14523891"``)
            * An **http(s) URL** pointing directly to a ``battinfo.json`` file;
              a URL with any other scheme is refused
            * A **local file path** to a ``battinfo.json`` file (the legacy
              ``battinfo.jsonld`` name is still accepted)

        sandbox:
            When *source* is a Zenodo record ID, use ``sandbox.zenodo.org``
            instead of production.
        token:
            Optional Zenodo API token for private records. It is sent only
            over https to the Zenodo host *sandbox* chooses (``zenodo.org`` or
            ``sandbox.zenodo.org``): never to another host, and never on a
            redirect. A URL on another host is read without it, with a warning.

        Returns
        -------
        dict
            Counts of the records imported, e.g.
            ``{"properties": 3, "instances": 8, "tests": 8, "datasets": 8}``,
            and under ``skipped`` the tests and datasets left out, each with
            its cell and the reason: ``{"tests": [{"test": ..., "cell": ...,
            "reason": ...}], "datasets": [...]}``. A test on a cell the
            deposit only points at (a "defined elsewhere" stub, for a cell
            published in the registry) is skipped, with its datasets.

        The document may come from anyone, so only http(s) download URLs come
        into the workspace. A distribution whose download URL is anything else, a
        ``file:`` URL or a path to this computer or another one, is left out
        with a warning, so a later deposit of this workspace never reads a file
        a document named. A dataset left with no file keeps the http(s) page
        the deposit gives it (its ``schema:url``, else the deposit record) as
        its ``access_url``, with the URL that was left out in its notes; a
        dataset without such a page is skipped, with the reason ``no http(s)
        download URL``.

        Example::

            ws.import_("14523891")        # from Zenodo
            ws.import_("battinfo.json")   # from local file
            ws.save()
            ws.submit()
        """

        # ── 1. Resolve source → raw JSON-LD text ──────────────────────────────
        raw_text = _import_resolve_source(source, sandbox=sandbox, token=token)
        doc = json.loads(raw_text)
        context = doc.get("@context", {})
        graph = doc.get("@graph", [])

        # ── 2. Build IRI expander from inline context ──────────────────────────
        def _expand(term: str) -> str:
            """Expand a compact IRI or term to its full IRI using the context."""
            if term.startswith("http://") or term.startswith("https://"):
                return term
            if ":" in term:
                prefix, local = term.split(":", 1)
                base = context.get(prefix, "")
                if isinstance(base, str) and base:
                    return base + local
            # Look up as a direct term in context
            mapped = context.get(term)
            if isinstance(mapped, str):
                return _expand(mapped)
            return term

        # ── 3. Build reverse lookup tables ────────────────────────────────────
        from battinfo.bundle import _unit_from_node  # noqa: PLC0415

        # Load prop map directly so we can keep only the FIRST key per IRI
        # (later aliases like "discharging_temperature_min" must not overwrite
        # the canonical "minimum_discharging_temperature"). The first key a cell
        # spec's properties accept wins over any key listed before it: Mass
        # reads back as mass, not as cap_assembly_weight, which the cell-spec
        # schema refuses.
        _prop_map_path = Path(__file__).parent / "data" / "mappings" / "domain-battery" / "property_map.curated.json"
        rev_prop: dict[str, str] = {}
        # class IRI -> the bound the class names ("max" or "min"), from the
        # curated ``bound`` flag the emitter reads too.
        bound_of_class: dict[str, str] = {}
        spec_keys = _cell_spec_property_keys()
        if _prop_map_path.exists():
            for m in json.loads(_prop_map_path.read_text(encoding="utf-8")).get("mappings", []):
                iri = m.get("class_iri", "")
                key = m.get("key", "")
                accepted_first = key in spec_keys and rev_prop.get(iri) not in spec_keys
                if iri and key and (iri not in rev_prop or accepted_first):
                    rev_prop[iri] = key
                if iri and m.get("bound") in ("max", "min"):
                    bound_of_class.setdefault(iri, m["bound"])

        # entity_type_map reversed. An entry with alias_of is an older spelling:
        # it still resolves, but is never the value to reconstruct.
        from battinfo.bundle import CellConfiguration
        from battinfo.transform.json_to_jsonld import chemistry_electrode_conflicts

        _entity_path = Path(__file__).parent / "data" / "mappings" / "domain-battery" / "entity_type_map.json"
        em: dict = json.loads(_entity_path.read_text(encoding="utf-8")).get("mappings", {})

        def _recommended(section: str) -> dict[str, dict]:
            return {
                value: entry
                for value, entry in (em.get(section) or {}).items()
                if isinstance(entry, dict) and "alias_of" not in entry
            }

        # class -> {"format": ...} / {"iec_code": ...}; a later class in the stack wins.
        _etype_rev: dict[str, dict] = {}  # "CylindricalBattery" → {"format": "cylindrical"}
        for section in ("format", "iec_code"):
            for value, entry in _recommended(section).items():
                for cls in entry.get("battery_types", []):
                    _etype_rev.setdefault(cls, {})[section] = value
        # class -> chemistry label, from the chemistry section only: an electrode
        # basis class (LithiumIonGraphiteBattery) never names a chemistry.
        _chemistry_of: dict[str, str] = {}
        for value, entry in _recommended("chemistry").items():
            for cls in entry.get("battery_types", []):
                _chemistry_of.setdefault(cls, value)
        # class -> the cell-spec schema's cell_configuration value
        _configurations = {member.value for member in CellConfiguration}
        _configuration_of: dict[str, str] = {}
        for value, entry in _recommended("cell_configuration").items():
            if value.replace("-", "_") in _configurations:
                for cls in entry.get("battery_types", []):
                    _configuration_of.setdefault(cls, value.replace("-", "_"))
        # electrode class -> basis, and battery class -> basis where only one basis
        # of that side adds the class and no chemistry claims it (nca has no
        # electrode class, so its battery class is all a deposit says of it).
        # Where several bases share an electrode class, the first, most generic
        # one is taken (all NMC grades come back as nmc).
        _basis_of_electrode: dict[str, dict[str, str]] = {}
        _basis_of_class: dict[str, dict[str, str]] = {}
        for section in ("positive_electrode_basis", "negative_electrode_basis"):
            by_electrode = _basis_of_electrode.setdefault(section, {})
            claims: dict[str, list[str]] = {}
            for value, entry in _recommended(section).items():
                for node_type in (entry.get("node_type"), *(entry.get("former_node_types") or [])):
                    if isinstance(node_type, str):
                        by_electrode.setdefault(node_type, value)
                for cls in entry.get("battery_types", []):
                    claims.setdefault(cls, []).append(value)
            _basis_of_class[section] = {
                cls: values[0] for cls, values in claims.items() if len(values) == 1 and cls not in _chemistry_of
            }

        def _type_terms(value: Any) -> list[str]:
            if isinstance(value, str):
                return [value]
            return [t for t in value if isinstance(t, str)] if isinstance(value, list) else []

        def _extract_descriptors(types: list[str]) -> dict:
            """Format, IEC code, chemistry and cell configuration from a class stack.

            The chemistry is the FIRST class the chemistry section names. The
            declared chemistry's class comes before any electrode-basis class,
            and deposits written before 0.8.0 carry basis classes of other
            chemistries after it: an alkaline cell's stack ended in
            LithiumManganeseDioxideBattery, which once made it come back li-mno2.
            """
            d: dict = {}
            for t in types:
                d.update(_etype_rev.get(t, {}))
            chemistry = next((_chemistry_of[t] for t in types if t in _chemistry_of), None)
            if chemistry:
                d["chemistry"] = chemistry
            configuration = next((_configuration_of[t] for t in types if t in _configuration_of), None)
            if configuration:
                d["cell_configuration"] = configuration
            return d

        def _electrode_bases(phys: dict, types: list[str]) -> dict[str, str]:
            """The electrode bases, read from the described battery's electrode nodes.

            An electrode class names its basis; an unrecognised basis was written
            as a generic Electrode labelled with it. Failing both, a battery
            class only one basis adds names it.
            """
            bases: dict[str, str] = {}
            for section, relation in (
                ("positive_electrode_basis", "hasPositiveElectrode"),
                ("negative_electrode_basis", "hasNegativeElectrode"),
            ):
                electrode = phys.get(relation)
                if isinstance(electrode, list):
                    electrode = next((item for item in electrode if isinstance(item, dict)), None)
                basis = None
                if isinstance(electrode, dict):
                    node_types = _type_terms(electrode.get("@type"))
                    basis = next(
                        (_basis_of_electrode[section][t] for t in node_types if t in _basis_of_electrode[section]), None
                    )
                    label = electrode.get("skos:prefLabel")
                    if basis is None and node_types == ["Electrode"] and isinstance(label, str) and label.strip():
                        basis = label.strip()
                if basis is None:
                    basis = next((_basis_of_class[section][t] for t in types if t in _basis_of_class[section]), None)
                if basis:
                    bases[section] = basis
            return bases

        def _specs_from_property_nodes(nodes: list, where: str) -> dict:
            """Reverse EMMO hasProperty nodes → {key: {value, min_value, max_value, value_text, unit}}.

            Accepts both quantity-node generations: the legacy single-string
            ``@type`` with a ``{"@id": ...}`` unit reference, and the canonical
            shape (list ``@type`` of ``[PropertyClass, co-type]`` with the unit
            as a bare IRI string). Units are read back as the publication-package
            reader reads them: an IRI goes through the emitters' unit tables, an
            IRI no table names is kept whole with a warning, and a unit without
            an IRI is read from ``schema:unitText``. PercentUnit reads back as
            wt% or vol% when the node also carries WeightPercent or
            VolumePercent, and as % otherwise.

            The bounds come from ``schema:minValue`` and ``schema:maxValue``.
            The emitter writes a bound given alone as the number too, but only
            on a class the curated map flags as that bound (``max_value`` on a
            Maximum class, ``min_value`` on a Minimum class), so on such a class
            a number equal to that only bound is read back as the bound alone.
            On any other class the number stays.

            A deposit written before 0.8.0 may carry text in
            ``hasNumberValue``: a numeric string comes back as the number, and
            other text moves to ``value_text`` with a warning, so a strict
            ``ws.save()`` accepts the record. A ``hasStringValue`` beside a
            number or a bound comes back as ``value_text``; a property stated
            as text alone is not read back."""
            specs: dict = {}
            moved: builtins.list[str] = []
            for node in nodes if isinstance(nodes, list) else [nodes]:
                if not isinstance(node, Mapping):
                    continue
                type_raw = node.get("@type", "")
                type_terms = (
                    [type_raw]
                    if isinstance(type_raw, str)
                    else [t for t in type_raw if isinstance(t, str)]
                    if isinstance(type_raw, list)
                    else []
                )
                class_iri = next((expanded for term in type_terms if rev_prop.get(expanded := _expand(term))), None)
                if class_iri is None:
                    continue
                prop_key = rev_prop[class_iri]
                numerical = node.get("hasNumericalPart")
                numerical = numerical if isinstance(numerical, Mapping) else {}
                value = _jsonld_literal(numerical.get("hasNumberValue", numerical.get("hasNumericalValue")))
                bounds = {
                    field: bound
                    for field, term in (("min_value", "schema:minValue"), ("max_value", "schema:maxValue"))
                    if is_real_number(bound := _jsonld_literal(node.get(term)))
                }
                named_bound = {"max": "max_value", "min": "min_value"}.get(bound_of_class.get(class_iri, ""))
                if value is not None and named_bound is not None and bounds == {named_bound: value}:
                    value = None
                if value is None and not bounds:
                    continue
                quantity: dict[str, Any] = {} if value is None else {"value": value}
                quantity.update(bounds)
                if text := _jsonld_text(node.get("hasStringValue")):
                    quantity["value_text"] = text
                if unit := _unit_from_node(node, _expand):
                    if unit == "%":
                        # % and vol% share PercentUnit; the basis rides as a class of the node.
                        unit = (
                            "wt%" if "WeightPercent" in type_terms else "vol%" if "VolumePercent" in type_terms else "%"
                        )
                    quantity["unit"] = unit
                moved.extend(migrate_quantity_values(quantity, f"properties.{prop_key}"))
                specs[prop_key] = quantity
            _warn_text_moved(where, moved)
            return specs

        # ── 4. Index graph nodes by type ───────────────────────────────────────
        spec_nodes_by_iri: dict[str, dict] = {}
        cell_nodes_by_iri: dict[str, dict] = {}
        test_nodes_by_iri: dict[str, dict] = {}
        dataset_nodes: list[dict] = []
        stub_cell_iris: set[str] = set()

        for node in graph:
            types = node.get("@type", [])
            if isinstance(types, str):
                types = [types]
            iri = node.get("@id", "")

            if "BatteryCellSpecification" in types:
                spec_nodes_by_iri[iri] = node
            elif (
                any(
                    t in types
                    for t in ("BatteryCell", "CylindricalBattery", "PouchCell", "CoinCell", "PrismaticBattery")
                )
                and "BatteryCellSpecification" not in types
            ):
                defined_by = node.get("rdfs:isDefinedBy")
                if isinstance(defined_by, dict) and defined_by.get("@id") == iri:
                    stub_cell_iris.add(iri)  # a published cell the package points at, described at its own IRI
                    continue
                cell_nodes_by_iri[iri] = node
            elif "BatteryTest" in types:
                test_nodes_by_iri[iri] = node
            elif "dcat:Dataset" in types or "schema:Dataset" in types:
                # Each member dataset carries its own files; a deposit made
                # before the catalog shape carried them all on one dataset.
                dataset_nodes.append(node)

        # A record the session already holds under a deposit IRI, as when the
        # import runs a second time, is reused. A different record under one of
        # those IRIs is a clash: once the deposit is read, the session is put
        # back as it was and the import raises, because one IRI names one record.
        engine = self._ws
        collections: tuple[builtins.list[Any], ...] = (
            engine.cell_specs,
            engine.cells,
            engine.test_specs,
            engine.tests,
            engine.datasets,
        )
        held_before = [builtins.list(collection) for collection in collections]
        index_before = [(cell, builtins.list(labels)) for cell, labels in self._indexed_cells]
        clashes: builtins.list[str] = []

        def _held_or_new(obj: Any, pool: builtins.list[Any], what: str) -> Any:
            repeats = engine._repeats_in(obj, pool)
            if repeats:
                self._discard(obj)
                return repeats[0]
            if obj.id is not None and any(other is not obj and other.id == obj.id for other in pool):
                clashes.append(f"{what} {obj.id}")
            return obj

        # ── 5. Import cell specs ───────────────────────────────────────────────
        spec_objects: dict[str, Any] = {}  # IRI → CellSpec
        for iri, node in sorted(spec_nodes_by_iri.items()):
            # Skip typed stubs for externally-defined specs (no descriptive body):
            # they only assert @type + a pointer to where the real spec lives, so
            # there is nothing to reconstruct a CellSpec from — and doing so would
            # mint an empty spec that shadows the authoritative remote one. A stub
            # is a node with no keys beyond identity/pointer ones — the canonical
            # shape puts isDescriptionFor on EVERY spec node, so its mere presence
            # is not a body (and a reference-only value is legal JSON-LD here).
            phys = node.get("isDescriptionFor")
            if not isinstance(phys, dict):
                phys = {}
            _stub_keys = {"@id", "@type", "rdfs:isDefinedBy", "dcterms:conformsTo", "isDescriptionFor"}
            _phys_body = bool(set(phys) - {"@id", "@type", "skos:prefLabel"})
            if not _phys_body and not (set(node) - _stub_keys):
                continue
            phys_types = phys.get("@type", [])
            if isinstance(phys_types, str):
                phys_types = [phys_types]
            descriptors = _extract_descriptors(phys_types)
            bases = _electrode_bases(phys, phys_types)

            mfr_node = node.get("schema:manufacturer", {})
            mfr_name = mfr_node.get("schema:name", "") if isinstance(mfr_node, dict) else str(mfr_node)
            # Canonical shape: the physical payload (hasProperty, composition)
            # rides the described battery; older packages carried it on the
            # spec node - read both, described side first.
            specs = _specs_from_property_nodes(
                phys.get("hasProperty") or node.get("hasProperty") or [], f"cell spec {iri}"
            )

            # size_code: the canonical shape emits it as schema:size; older
            # packages used schema:identifier. In the canonical shape
            # schema:identifier carries the record uid (the IRI tail) instead,
            # so ignore it as a size code when it matches the tail.
            _ident = node.get("schema:identifier")
            if isinstance(_ident, str) and _ident == iri.rstrip("/").split("/")[-1]:
                _ident = None
            ct = self._ws.cell_spec(
                manufacturer=mfr_name,
                model=node.get("schema:model", ""),
                # Use verbatim strings if present (legacy packages), else fall
                # back to values reverse-mapped from the isDescriptionFor @type stack.
                format=node.get("battinfo:cellFormat") or descriptors.get("format", ""),
                chemistry=node.get("battinfo:chemistry") or descriptors.get("chemistry", ""),
                iec_code=descriptors.get("iec_code") or node.get("schema:productID") or node.get("schema:gtin"),
                size_code=node.get("schema:size") or _ident,
                cell_configuration=descriptors.get("cell_configuration"),
                positive_electrode_basis=bases.get("positive_electrode_basis"),
                negative_electrode_basis=bases.get("negative_electrode_basis"),
                specs=specs or None,
                source_type="zenodo",
            )
            ct.id = iri
            spec_objects[iri] = _held_or_new(ct, engine.cell_specs, "cell spec")
            print(f"  spec:     {node.get('schema:name', iri)}")
            # A deposit whose chemistry was free text kept only the classes its
            # electrode bases added, so the chemistry read back can be one the
            # electrodes contradict. Say so here; the strict save refuses it.
            for problem in chemistry_electrode_conflicts(
                {
                    "chemistry": ct.chemistry,
                    "cell_configuration": descriptors.get("cell_configuration"),
                    **bases,
                }
            ):
                print(
                    f"  WARNING: spec {iri}: {problem} The chemistry was read from the deposit's battery "
                    "classes, and a deposit written before 0.8.0 also carries classes its electrodes "
                    "added. Set the chemistry before saving."
                )

        # ── 6. Import cell instances ───────────────────────────────────────────
        imported_cells = 0
        for iri, node in sorted(cell_nodes_by_iri.items()):
            spec_iri = (node.get("dcterms:conformsTo") or {}).get("@id", "")
            spec_obj = spec_objects.get(spec_iri)
            if spec_obj is None:
                print(f"  WARNING: no spec found for cell {iri} -- skipping")
                continue

            cell = self._ws.cell(
                spec_obj,
                serial_number=node.get("schema:serialNumber"),
                grade=node.get("schema:quality"),
                # Written as typed literals ({"@value": ..., "@type": "xsd:date"}).
                manufactured_at=_jsonld_literal(node.get("schema:productionDate")),
                expires_at=_jsonld_literal(node.get("schema:expires")),
            )
            cell.id = iri
            sn = node.get("schema:serialNumber", "")
            held = _held_or_new(cell, engine.cells, "cell")
            if held is cell:
                self._index_cell(cell, sn)
            imported_cells += 1
            print(f"  instance: {sn or iri}")

        # ── 7. Import tests + datasets ─────────────────────────────────────────
        # The document may come from anyone, so only http(s) download URLs
        # enter the workspace. A file: URL or a path would point this
        # workspace's next deposit at a file on this computer or on another
        # one, so each is left out, with a warning.
        dist_by_url: dict[str, dict] = {}
        dists_by_dataset: dict[str, builtins.list[dict]] = {}
        dataset_node_by_iri: dict[str, dict] = {}
        left_out_urls: dict[str, builtins.list[str]] = {}
        for ds_node in dataset_nodes:
            ds_iri = ds_node.get("@id", "")
            dataset_node_by_iri.setdefault(ds_iri, ds_node)
            ds_dists = ds_node.get("dcat:distribution") or []
            for dist in ds_dists if isinstance(ds_dists, list) else [ds_dists]:
                raw_url = dist.get("dcat:downloadURL") if isinstance(dist, dict) else None
                url = _import_web_url(raw_url)
                if url:
                    dist = {**dist, "dcat:downloadURL": url}
                    dist_by_url[url] = dist
                    dists_by_dataset.setdefault(ds_iri, []).append(dist)
                elif raw_url:
                    shown = raw_url.get("@id", raw_url) if isinstance(raw_url, Mapping) else raw_url
                    left_out_urls.setdefault(ds_iri, []).append(str(shown))
                    warnings.warn(
                        f"Left out the download URL {shown!r} of dataset {ds_iri}: ws.import_() keeps "
                        "only http(s) URLs, so that a deposit cannot point this workspace at a file "
                        "on this computer or on another one.",
                        stacklevel=2,
                    )

        def _first_id(v: Any) -> str:
            """Resolve an @id from a node ref that may be a dict or a list of dicts."""
            if isinstance(v, list):
                v = v[0] if v else {}
            return v.get("@id", "") if isinstance(v, dict) else ""

        def _generated_by(dist: dict, test_iri: str) -> bool:
            generated = dist.get("prov:wasGeneratedBy")
            return isinstance(generated, dict) and generated.get("@id") == test_iri

        imported_tests = imported_datasets = 0
        skipped_tests: builtins.list[dict] = []
        skipped_datasets: builtins.list[dict] = []
        # A dataset that several tests name as an output is one record: the first
        # test that names it is its test, and each other one a related test.
        datasets_here: dict[str, Any] = {}
        made_datasets: builtins.list[Any] = []
        for test_iri, tnode in sorted(test_nodes_by_iri.items()):
            # prov:used may now be a list (cell + spec); hasTestObject is preferred.
            cell_iri = _first_id(tnode.get("hasTestObject")) or _first_id(tnode.get("prov:used"))
            test_cell = (
                self._ws.cells[-1] if not cell_iri else next((c for c in self._ws.cells if c.id == cell_iri), None)
            )
            outputs = [o for o in (tnode.get("hasOutput") or []) if isinstance(o, dict)]
            if test_cell is None:
                # Not attached here: a test on a stub cell (one published in the
                # registry) would need that cell in this workspace first.
                reason = (
                    "cell defined elsewhere"
                    if cell_iri in stub_cell_iris
                    else "cell not imported"
                    if cell_iri in cell_nodes_by_iri
                    else "cell not in the deposit"
                )
                if reason != "cell defined elsewhere":
                    print(f"  WARNING: no cell found for test {test_iri} -- skipping")
                skipped_tests.append({"test": test_iri, "cell": cell_iri, "reason": reason})
                skipped_datasets.extend(
                    {"dataset": o.get("@id", ""), "test": test_iri, "cell": cell_iri, "reason": reason} for o in outputs
                )
                continue
            if not outputs:
                skipped_tests.append({"test": test_iri, "cell": cell_iri, "reason": "no dataset"})
                continue

            protocol = tnode.get("schema:measurementTechnique", "")
            instr_node = tnode.get("hasTestEquipment", {})
            instrument = (
                instr_node.get("schema:name", "")
                if isinstance(instr_node, dict)
                else tnode.get("schema:instrument", "")
            )
            # The emitter states the kind as schema:additionalType; a deposit
            # without it leaves the kind to be read from the technique.
            kind = tnode.get("schema:additionalType")
            if not isinstance(kind, str) or not kind.strip():
                kind = _import_test_kind_from_technique(protocol)

            # One engine test per BatteryTest node, made when its first output
            # resolves and kept under the deposit's IRI; each output becomes one
            # of its datasets, under its own IRI. (One test per output would put
            # several tests on one IRI, which ws.save() refuses.)
            test = None
            for output in outputs:
                ds_iri = output.get("@id", "")
                own = dists_by_dataset.get(ds_iri, [])
                left_out = left_out_urls.get(ds_iri, [])
                dist = None
                if own or not left_out:
                    # Find the distribution for this dataset: its own file the test
                    # generated, then any file the test generated (one dataset held
                    # every file before the catalog shape), then its own first file,
                    # then a file whose URL carries the dataset uid. A dataset whose
                    # own files were all left out never borrows another's.
                    dist = (
                        next((d for d in own if _generated_by(d, test_iri)), None)
                        or next((d for d in dist_by_url.values() if _generated_by(d, test_iri)), None)
                        or (own[0] if own else None)
                    )
                    if dist is None:
                        dist = next(
                            (d for d in dist_by_url.values() if ds_iri.split("/")[-1] in d.get("dcat:downloadURL", "")),
                            None,
                        )
                note = None
                if dist is not None:
                    dl_url = dist["dcat:downloadURL"]
                    cs = dist.get("spdx:checksum") or {}
                    fmt = _media_type_from_jsonld(dist.get("dcat:mediaType"))
                    fname = dist.get("schema:name") or _distribution_file_name(dl_url)
                elif left_out:
                    # Every download URL the dataset had was left out. It is kept
                    # without a file, at the http(s) page the deposit gives it,
                    # and its notes say what was left out.
                    ds_node = dataset_node_by_iri.get(ds_iri) or {}
                    dl_url = _import_web_url(ds_node.get("schema:url")) or _import_web_url(
                        ds_node.get("dcterms:isPartOf")
                    )
                    if not dl_url:
                        skipped_datasets.append(
                            {
                                "dataset": ds_iri,
                                "test": test_iri,
                                "cell": cell_iri,
                                "reason": "no http(s) download URL",
                            }
                        )
                        continue
                    cs, fmt = {}, ""
                    fname = f"{ds_node.get('schema:name') or ds_iri} (without its file)"
                    listed = ", ".join(repr(location) for location in left_out)
                    note = (
                        f"Imported without a file: the deposit gave the download URL {listed}, which "
                        "ws.import_() does not keep, as it is not an http(s) URL."
                        if len(left_out) == 1
                        else f"Imported without a file: the deposit gave the download URLs {listed}, which "
                        "ws.import_() does not keep, as they are not http(s) URLs."
                    )
                else:
                    skipped_datasets.append(
                        {"dataset": ds_iri, "test": test_iri, "cell": cell_iri, "reason": "no distribution"}
                    )
                    continue

                if test is None:
                    test = self._ws.test(
                        test_cell,
                        kind=kind,
                        name=f"{test_cell.serial_number or cell_iri.split('/')[-1]} {protocol}",
                        protocol=protocol or kind.replace("_", " "),
                        instrument=instrument,
                        status="completed",
                    )
                    test.id = test_iri
                    test = _held_or_new(test, engine.tests, "test")
                shared = datasets_here.get(ds_iri) if ds_iri else None
                if shared is not None:
                    primary = shared.test.id if shared.test is not None else shared.test_id
                    if test_iri != primary and test_iri not in shared.related_test_ids:
                        shared.related_test_ids.append(test_iri)
                    continue
                dataset = self._ws.dataset(
                    test_cell,
                    title=f"{test_cell.name or test_cell.serial_number or 'cell'} {kind} dataset",
                    test=test,
                    access_url=dl_url,
                    format=fmt or None,
                    checksum_algorithm=_spdx_algorithm_name(cs),
                    checksum_value=cs.get("spdx:checksumValue") or None,
                )
                if ds_iri:
                    dataset.id = ds_iri
                    datasets_here[ds_iri] = dataset
                if note is not None:
                    dataset.comment.append(note)
                made_datasets.append(dataset)
                imported_datasets += 1
                print(f"  test:     {fname}")
            if test is not None:
                imported_tests += 1
            else:
                skipped_tests.append({"test": test_iri, "cell": cell_iri, "reason": "no distribution"})

        # Compared once every test has named its outputs, related tests included.
        for dataset in made_datasets:
            _held_or_new(dataset, engine.datasets, "dataset")

        if clashes:
            for collection, items in zip(collections, held_before):
                collection[:] = items
            self._indexed_cells = index_before
            shown = ", ".join(clashes[:3]) + (f" and {len(clashes) - 3} more" if len(clashes) > 3 else "")
            raise ValueError(
                f"The deposit has {len(clashes)} record(s) whose IRI a different record of this session "
                f"already has: {shown}. One IRI names one record, so nothing was imported. Import into a "
                "fresh workspace, or start over with ws.clear()."
            )

        counts: dict[str, Any] = {
            "properties": len(spec_objects),
            "instances": imported_cells,
            "tests": imported_tests,
            "datasets": imported_datasets,
        }
        print(f"\nImported: {counts}")
        counts["skipped"] = {"tests": skipped_tests, "datasets": skipped_datasets}
        on_stubs = [s for s in skipped_tests if s["reason"] == "cell defined elsewhere"]
        if on_stubs:
            stub_cells = sorted({s["cell"] for s in on_stubs})
            n_ds = sum(1 for s in skipped_datasets if s["reason"] == "cell defined elsewhere")
            shown = ", ".join(stub_cells[:3]) + (f" and {len(stub_cells) - 3} more" if len(stub_cells) > 3 else "")
            print(
                f"Skipped {len(on_stubs)} test(s) and {n_ds} dataset(s) on {len(stub_cells)} cell(s) "
                f"defined in the registry, not in this deposit: {shown}. ws.import_() does not attach "
                "tests to a cell it does not hold; to bring one in, open a workspace with a registry_url, "
                'reference the cell with ws.load(ws.search(type="cell", serial=...)[0]) and add its '
                'tests with ws.add("test", cell=..., data=...).'
            )
        others = len(skipped_tests) - len(on_stubs)
        if others:
            print(f'Skipped {others} other test(s); counts["skipped"] lists each one and why.')
        return counts

    def clear(self) -> None:
        """Clear all in-memory records and reset the workspace for a new authoring session.

        Does not delete any files already saved to ``.battinfo/records/``.
        A ``ws.load()`` or ``ws.add()`` cell re-run unchanged needs no clear:
        the session reuses what it holds. Call it to start a session over, for
        example after editing a draft whose pinned IRI the session already
        holds.

        Example::

            ws.clear()
            ws.add("cell-instance", spec=spec, serial_numbers=[...])
            ws.save()
        """
        self._ws = self._make_engine()
        self._indexed_cells = []
        self._session_paths = set()
        self._added_paths = set()
        print("Workspace cleared.")

    def submit(
        self,
        only: str | builtins.list[str] | None = None,
        registry_url: str | None = None,
        api_key: str | None = None,
        workspace_id: str | None = None,
        publisher_id: str | None = None,
        source_version: str | None = None,
        note: str | None = None,
        doi: str | None = None,
        *,
        publication_mode: str = STAGED_PUBLICATION_MODE,
        allow_partial: bool = False,
        submit_all: bool = False,
        resume: bool = True,
        allow_local_files: bool = False,
    ) -> builtins.list[dict]:
        """Submit workspace records to the battinfo registry (staged for review).

        Resumable: outcomes are journaled to ``.battinfo/submit-journal.jsonl``
        as they happen, and a record whose identical payload already succeeded
        at the same registry in a previous run is skipped (``status: skipped_journal``) instead of
        re-POSTed — resuming an interrupted bulk submission re-sends only what
        is missing. Pass ``resume=False`` to bypass the journal and re-send
        everything (the registry dedups identical re-submissions server-side).

        POSTs saved records to the registry API.  By default submissions are
        STAGED (``publication_mode="staged-publication"``): they enter the
        registry's review queue (status ``validated``) and a curator promotes them
        to the public index — the registry is a curated index, not a write-through
        store.  Track staged records with :meth:`pending` / :meth:`status`.  Pass
        ``publication_mode="canonical-publication"`` for the privileged
        immediate-publish path.

        Fails closed and observable: every record's outcome is reported, and if any
        record fails (or a record file is unreadable) :class:`SubmitError` is raised
        — unless ``allow_partial=True``, in which case failures are returned in the
        outcome list instead.  Returns a list of per-record outcome dicts (``ok``,
        ``status``, ``error``, ``iri`` …).  No git or filesystem dependency.

        A record the registry already holds with other content is retried once
        as a new version (``version_bumped``).  A record whose IRI another
        publisher holds is not: its outcome has status ``conflict``, names the
        IRI and the publisher, and says how to rename it (a serial or
        ``names=`` only your lab uses) or pin an IRI of your own.  Lab labels
        such as ``"S1"`` are not scoped to a lab until 0.9, so two labs that both
        name a cell of one spec ``"S1"`` mint one IRI.

        Credentials can be passed as arguments, established with ``ws.login()``
        (scoped to this workspace instance), set as environment variables, or
        kept in this workspace's ``.battinfo/credentials``, and are looked up in
        that order:

        * ``BATTINFO_REGISTRY_URL`` (when the workspace has no registry of its own)
        * ``BATTINFO_API_KEY``
        * ``BATTINFO_WORKSPACE_ID``
        * ``BATTINFO_PUBLISHER_ID``

        Parameters
        ----------
        only:
            Restrict submission to one or more record types.  Accepts a single
            string or a list.  Supported values: ``"cell-spec"``,
            ``"cell-instance"``, ``"test-spec"``, ``"test"``, ``"dataset"``.
            Defaults to ``None`` (submit all).

            Examples::

                ws.submit(only="test-spec")
                ws.submit(only=["cell-spec", "cell-instance"])

        registry_url:
            Registry base URL, e.g. ``"https://registry.battery-genome.org"``.
        api_key:
            Publisher API key issued by the registry.
        workspace_id:
            Registry workspace ID.
        publisher_id:
            Registry publisher ID.
        source_version:
            Version label for this submission batch.  Defaults to today's date.
        note:
            Provenance note attached to every submitted record.
        doi:
            A DOI to record on every submitted record, as
            ``provenance.citation_doi``. Without it, the DOI of the Zenodo
            record this workspace continues (``.battinfo/zenodo.json``) goes
            on the records its deposit holds, and only once it is published
            on zenodo.org: never a sandbox DOI, nor the DOI a draft has
            reserved. A recorded draft is first checked with Zenodo (when
            ``ZENODO_API_TOKEN`` is set), in case it was published on the
            website since.
        allow_local_files:
            Records whose download or source locations (``access_url``,
            ``content_url``, ``download_url``, ``provenance.source_url``,
            ``record_url``) are local paths or ``file:`` URIs are refused
            before anything is sent, because the registry would publish paths
            nobody else can open. Deposit the files first (``ws.zenodo()``
            points the records at the deposited copies), then submit.
            ``True`` lifts the check, for a local test registry only.

        Example::

            ws.save()
            ws.submit(note="From SINTEF LR03 experiment, Feb 2026.")
        """
        import datetime

        url = self._require_registry(registry_url, "ws.submit()")
        key = self._credential("BATTINFO_API_KEY", explicit=api_key)
        wid = self._credential("BATTINFO_WORKSPACE_ID", explicit=workspace_id)
        pid = self._credential("BATTINFO_PUBLISHER_ID", explicit=publisher_id)
        ver = source_version or datetime.date.today().isoformat()

        # The schemas do not include a free-text provenance.comment field
        # (additionalProperties: false), so `note` is accepted for API
        # compatibility but not attached to provenance.

        if not key:
            raise RuntimeError(
                "api_key is required. Run ws.login(api_key=...) first, or set "
                "BATTINFO_API_KEY. No self-service key page exists yet - see "
                "https://battinfo.org/publish for how to request one."
            )
        if not wid:
            raise RuntimeError("workspace_id is required. Pass it or set BATTINFO_WORKSPACE_ID.")
        if not pid:
            raise RuntimeError("publisher_id is required. Pass it or set BATTINFO_PUBLISHER_ID.")

        records_dir = self._ws.source_root
        if not records_dir.exists():
            print("  No records found -- run ws.save() first.")
            return []

        journal = _SubmitJournal(self._root / ".battinfo" / "submit-journal.jsonl") if resume else None

        # ── Validate the `only` filter (fail loud on an unknown token) ──────────
        _ALIASES: dict[str, str] = {
            "cell-spec": "cell-spec",
            "cell_spec": "cell-spec",
            "cell-instance": "cell-instance",
            "cell_instance": "cell-instance",
            "test-spec": "test-protocol",
            "test_spec": "test-protocol",
            "test-protocol": "test-protocol",
            "test": "test",
            "dataset": "dataset",
            "material-spec": "material-spec",
            "material": "material",
            "electrode-spec": "electrode-spec",
            "electrode": "electrode",
            "equipment-spec": "equipment-spec",
            "equipment": "equipment",
            "channel": "channel",
            "channels": "channel",
            "parameter-set": "parameter-set",
            "parameters": "parameter-set",
        }
        allowed: set[str] | None
        if only is not None:
            if isinstance(only, str):
                raw_only = [only]
            elif isinstance(only, (list, tuple, set)):
                raw_only = list(only)
            else:
                raise ValueError(f"only= must be a string or list of strings, got {only!r}")
            allowed = set()
            for rt in raw_only:
                if not isinstance(rt, str):
                    raise ValueError(f"only= must be a string or list of strings, got {rt!r}")
                token = _ALIASES.get(rt.lower().replace("_", "-"))
                if token is None:
                    raise ValueError(
                        f"unknown record type {rt!r} in only=. Valid values: "
                        "cell-spec, cell-instance, test-spec, test, dataset, "
                        "material-spec, material, electrode-spec, electrode, "
                        "equipment-spec, equipment, channel, parameter-set."
                    )
                allowed.add(token)
        else:
            allowed = None  # None means all types

        # Every record type ws.save() can write must be submittable, or a saved
        # record silently never reaches the registry. Specs precede the instances
        # that reference them so the registry sees a resolvable target first
        # (channels after equipment, parameter-sets after the specs they target).
        _SUBDIRS = (
            "material-spec",
            "material",
            "electrode-spec",
            "electrode",
            "cell-spec",
            "cell-instance",
            "test-protocol",
            "test",
            "dataset",
            "equipment-spec",
            "equipment",
            "channel",
            "parameter-set",
        )
        # Component-family records exist locally but the registry cannot register
        # their resource types yet (identifiers.py: "Component-spec resource types
        # are not registrable yet"). They are surfaced below, never silently skipped.
        _NOT_REGISTRABLE = (
            "separator-spec",
            "separator",
            "current-collector-spec",
            "current-collector",
            "electrolyte-spec",
            "electrolyte",
            "housing-spec",
            "housing",
        )

        def _all_in(subdir: str) -> list[Path]:
            d = records_dir / subdir
            return sorted(d.glob("*.json")) if d.exists() else []

        wanted = [s for s in _SUBDIRS if allowed is None or s in allowed]

        # ── Select which files to submit (R-9: never silently submit leftovers) ─
        if self._session_paths:
            # Only what this session wrote: the most recent ws.save(), and the
            # records ws.add("equipment") wrote itself.
            selected = {s: [f for f in _all_in(s) if f in self._session_paths] for s in wanted}
        elif submit_all:
            selected = {s: _all_in(s) for s in wanted}
        else:
            on_disk = sum(len(_all_in(s)) for s in wanted)
            if on_disk:
                raise SubmitError(
                    f"No records were saved in this session, but {on_disk} record(s) exist on "
                    "disk. Call ws.save() first, or pass submit_all=True to submit them."
                )
            selected = {s: [] for s in wanted}

        # Fail loud, not silent: component-family records in scope cannot be
        # registered yet, so say so instead of dropping them without a word.
        if self._session_paths or submit_all:
            unregistrable = {
                s: [f for f in _all_in(s) if submit_all or f in self._session_paths] for s in _NOT_REGISTRABLE
            }
            unregistrable = {s: fs for s, fs in unregistrable.items() if fs}
            if unregistrable:
                listing = ", ".join(f"{len(fs)} {s}" for s, fs in unregistrable.items())
                print(
                    f"  NOTE: not submitted ({listing}) -- the registry cannot register "
                    "these component record types yet. They stay local; reference them "
                    "from cell/electrode records, which do submit."
                )

        # ── Up-front integrity pass: parse AND validate every record before any network
        # call. A corrupt/unreadable or invalid record fails the batch loudly here rather
        # than aborting mid-submit or publishing bad data. Records are validated at save(),
        # but re-validating catches hand-edited / external / save-bypassed records, and the
        # real verdict travels in each payload for the registry's promotion gate (instead of
        # a hardcoded validation: ok=True).
        from battinfo.validate.record import validate_record

        parsed: dict[Path, dict] = {}
        validations: dict[Path, dict] = {}
        prefailed: list[dict] = []
        local_offenders: list[tuple[Path, dict, list[tuple[str, str]]]] = []
        for s in wanted:
            for f in selected[s]:
                try:
                    rec = json.loads(f.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
                    print(f"  ERROR: {f.name} -- unreadable/corrupt ({exc})")
                    prefailed.append(
                        {
                            "title": f.name,
                            "source_local_id": f.stem,
                            "ok": False,
                            "status": "unreadable",
                            "error": str(exc),
                            "iri": "",
                            "result": None,
                        }
                    )
                    continue
                if not isinstance(rec, dict):
                    error = "not a JSON object record"
                    print(f"  ERROR: {f.name} -- {error}")
                    prefailed.append(
                        {
                            "title": f.name,
                            "source_local_id": f.stem,
                            "ok": False,
                            "status": "invalid",
                            "error": error,
                            "iri": "",
                            "result": None,
                        }
                    )
                    continue
                try:
                    result = validate_record(rec, policy="publisher")
                except (ValueError, TypeError) as exc:  # unrecognised / non-object record
                    error = f"not a recognised record ({exc})"
                    print(f"  ERROR: {f.name} -- {error}")
                    prefailed.append(
                        {
                            "title": f.name,
                            "source_local_id": f.stem,
                            "ok": False,
                            "status": "invalid",
                            "error": error,
                            "iri": "",
                            "result": None,
                        }
                    )
                    continue
                if not result.ok:
                    error = "; ".join(result.errors)
                    print(f"  ERROR: {f.name} -- failed validation: {error}")
                    prefailed.append(
                        {
                            "title": f.name,
                            "source_local_id": f.stem,
                            "ok": False,
                            "status": "invalid",
                            "error": error,
                            "iri": "",
                            "result": None,
                        }
                    )
                    continue
                if not allow_local_files:
                    found = _submission_local_files(rec, s, records_dir)
                    if found:
                        local_offenders.append((f, rec, found))
                        continue
                parsed[f] = rec
                validations[f] = {"ok": True, "errors": list(result.errors), "policy": "publisher"}
        if local_offenders:
            # Never publish a path on this computer as a download link: refuse the
            # records that carry one, before any network call.
            local_failures = [
                {
                    "title": f.name,
                    "source_local_id": f.stem,
                    "ok": False,
                    "status": "local_files",
                    "error": "; ".join(f"{field}: {value}" for field, value in found),
                    "iri": entity_id_from_doc(rec) or "",
                    "result": None,
                }
                for f, rec, found in local_offenders
            ]
            if not allow_partial:
                message = _local_files_message(
                    [(f"{f.name} ({entity_id_from_doc(rec) or 'no id'})", found) for f, rec, found in local_offenders]
                )
                raise SubmitError(message, failed=local_failures + prefailed, outcomes=local_failures + prefailed)
            for failure in local_failures:
                print(f"  ERROR: {failure['title']} -- points at local files: {failure['error']}")
            prefailed.extend(local_failures)
        if prefailed and not allow_partial:
            raise SubmitError(
                f"{len(prefailed)} record(s) are unreadable or failed validation; aborting before "
                "submitting (nothing was sent). Fix them, or pass allow_partial=True.",
                failed=prefailed,
                outcomes=prefailed,
            )

        # The Zenodo DOI is recorded as provenance.citation_doi, a field the
        # registry record schemas allow, so each submitted record links to its
        # archived dataset: the DOI passed for every record, or else the
        # deposit's DOI for the records it holds, once it is published.
        doi_for = self._submission_doi(doi)

        def _selected(subdir: str) -> list[Path]:
            return [f for f in selected.get(subdir, []) if f in parsed]

        outcomes: list[dict] = list(prefailed)

        # ── Cross-record relationship graph ───────────────────────────────────
        # Read every saved record (not just this session's) so links resolve even
        # when only a subset is re-submitted. Forward references are fine: the
        # registry stores a relationship's target IRI whether or not the target
        # resource exists yet, and per-record submission is not scope-validated.
        _corrupt_siblings: list[tuple[Path, str]] = []

        def _load_all(subdir: str, key: str) -> dict[str, tuple[dict, dict]]:
            out: dict[str, tuple[dict, dict]] = {}
            d = records_dir / subdir
            if d.exists():
                for f in sorted(d.glob("*.json")):
                    try:
                        rec = _read_json(f)
                    except (OSError, ValueError) as exc:
                        # Do NOT silently drop a corrupt/BOM sibling: it would strip the cross-
                        # record relationship it provides from the submitted graph with no error,
                        # publishing a record with real links silently missing (R-6, R-10).
                        _corrupt_siblings.append((f, str(exc)))
                        continue
                    inner = rec.get(key) or {}
                    iri = inner.get("id")
                    if iri:
                        out[iri] = (rec, inner)
            return out

        _all_datasets = _load_all("dataset", "dataset")
        _all_tests = _load_all("test", "test")
        _all_channels = _load_all("channel", "channel")
        if _corrupt_siblings and not allow_partial:
            failures = [
                {
                    "title": f.name,
                    "source_local_id": f.stem,
                    "ok": False,
                    "status": "unreadable",
                    "error": err,
                    "iri": "",
                    "result": None,
                }
                for f, err in _corrupt_siblings
            ]
            listing = "; ".join(f"{f.name} ({err})" for f, err in _corrupt_siblings)
            raise SubmitError(
                f"{len(_corrupt_siblings)} sibling record file(s) are unreadable and would silently "
                f"drop cross-record relationships from the submission: {listing}. Fix them, or pass "
                "allow_partial=True to submit without those relationships.",
                failed=failures,
                outcomes=failures,
            )

        # cell IRI -> [dataset IRIs] / [test IRIs]; cell IRI -> preview png url;
        # dataset IRI -> {"cell": iri, "test": iri}; test_spec IRI -> [test IRIs]
        cell_datasets: dict[str, list[str]] = {}
        cell_tests: dict[str, list[str]] = {}
        cell_preview_png: dict[str, str] = {}
        ds_links: dict[str, dict] = {}
        spec_tests: dict[str, list[str]] = {}
        # equipment IRI -> [(channel IRI, label)] so an equipment submission can
        # carry hasChannel links (mirrors the cell -> dataset/test link pattern).
        equipment_channels: dict[str, list[tuple[str, str]]] = {}
        for ch_iri, (_ch_rec, ch_inner) in _all_channels.items():
            eq_iri = ch_inner.get("equipment_id")
            if eq_iri:
                equipment_channels.setdefault(eq_iri, []).append((ch_iri, str(ch_inner.get("label") or "")))

        for ds_iri, (_ds_rec, ds_inner) in _all_datasets.items():
            about = ds_inner.get("about") or []
            cell_iri = next((a for a in about if "/cell/" in a), None)
            test_iri = next((a for a in about if "/test/" in a), None)
            ds_links[ds_iri] = {"cell": cell_iri, "test": test_iri}
            if cell_iri:
                cell_datasets.setdefault(cell_iri, []).append(ds_iri)
                if cell_iri not in cell_preview_png:
                    for dist in ds_inner.get("distributions") or []:
                        if (dist.get("name") or "").endswith(".png"):
                            cell_preview_png[cell_iri] = dist.get("content_url") or ""
                            break

        for t_iri, (_t_rec, t_inner) in _all_tests.items():
            cell_iri = t_inner.get("cell_id")
            if cell_iri:
                cell_tests.setdefault(cell_iri, []).append(t_iri)
            proto_iri = t_inner.get("protocol_id")
            if proto_iri:
                spec_tests.setdefault(proto_iri, []).append(t_iri)

        # ── Materials, electrodes, equipment, and parameter sets ──────────────
        # These are ordinary records that ws.save() (or ws.add) writes, so they
        # submit like any other; kinds absent from _SUBDIRS meant a saved record
        # silently never reached the registry (materials/electrodes first, then
        # the same gap for equipment/channel/parameter-set — G11).
        # Specs first, then the instances that reference them.
        for subdir, record_key, resource_type, rdf_type, spec_ref in (
            ("material-spec", "material_spec", "material_spec", "MaterialSpec", None),
            ("material", "material", "material", "Material", "material_spec_id"),
            ("electrode-spec", "electrode_spec", "electrode_spec", "ElectrodeSpec", None),
            ("electrode", "electrode", "electrode", "Electrode", "electrode_spec_id"),
            ("equipment-spec", "equipment_spec", "equipment_spec", "EquipmentSpec", None),
            ("equipment", "equipment", "equipment", "Equipment", "equipment_spec_id"),
            ("channel", "channel", "channel", "Channel", None),
            ("parameter-set", "parameter_set", "parameter_set", "ParameterSet", None),
        ):
            spec_resource_type = f"{resource_type}_spec"
            for src in _selected(subdir):
                raw = parsed[src]
                body = raw.get(record_key, {})
                title = (
                    body.get("name")
                    or body.get("label")
                    or body.get("serial_number")
                    or body.get("batch_id")
                    or body.get("lot_id")
                    or body.get("short_id")
                    or src.stem
                )
                source_local_id = body.get("short_id") or src.stem
                raw = _with_citation_doi(raw, doi_for(body.get("id")))
                record_links = []
                if spec_ref and isinstance(body.get(spec_ref), str):
                    record_links.append(
                        {
                            "relationship": "instanceOf",
                            "resource_type": spec_resource_type,
                            "canonical_iri": body[spec_ref],
                        }
                    )
                if isinstance(body.get("active_material_spec_id"), str):
                    record_links.append(
                        {
                            "relationship": "hasActiveMaterial",
                            "resource_type": "material_spec",
                            "canonical_iri": body["active_material_spec_id"],
                        }
                    )
                if record_key == "equipment":
                    for ch_iri, ch_label in equipment_channels.get(body.get("id", ""), []):
                        link = {"relationship": "hasChannel", "resource_type": "channel", "canonical_iri": ch_iri}
                        if ch_label:
                            link["title"] = ch_label
                        record_links.append(link)
                if record_key == "channel" and isinstance(body.get("equipment_id"), str):
                    record_links.append(
                        {
                            "relationship": "channelOf",
                            "resource_type": "equipment",
                            "canonical_iri": body["equipment_id"],
                        }
                    )
                if record_key == "parameter_set":
                    # The claim batch's target, or the cell a parameter file
                    # describes, when it is a registered record (a
                    # material_kind target is vocabulary, not a record).
                    for tgt_field, tgt_type in (
                        ("material_spec_id", "material_spec"),
                        ("cell_spec_id", "cell_spec"),
                        ("cell_instance_id", "cell"),
                    ):
                        if isinstance(body.get(tgt_field), str):
                            record_links.append(
                                {
                                    "relationship": "about",
                                    "resource_type": tgt_type,
                                    "canonical_iri": body[tgt_field],
                                }
                            )
                payload = _simple_submission_payload(
                    raw,
                    resource_type=resource_type,
                    rdf_type=rdf_type,
                    record_key=record_key,
                    wid=wid,
                    pid=pid,
                    ver=ver,
                    source_local_id=source_local_id,
                    title=title,
                    related_resources=record_links,
                )
                outcomes.append(
                    _journaled_submit(
                        journal,
                        payload,
                        url,
                        key,
                        title,
                        source_local_id=source_local_id,
                        publication_mode=publication_mode,
                        validation=validations[src],
                        allow_local_files=allow_local_files,
                    )
                )

        # ── Cell specs ────────────────────────────────────────────────────────
        for src in _selected("cell-spec"):
            raw = parsed[src]
            product = raw.get("cell_spec", {})
            mfr = product.get("manufacturer", {})
            mfr_name = mfr.get("name", "") if isinstance(mfr, dict) else str(mfr)
            model = product.get("model", "")
            year = product.get("year") or datetime.date.today().year
            # The record's own title wins; "<manufacturer> <model>" is the fallback for a
            # cell spec without one. Titles are display text: the registry identity is the
            # IRI and the source_local_id below, never the title.
            name = product.get("name")
            title = name.strip() if isinstance(name, str) and name.strip() else f"{mfr_name} {model}".strip()
            source_local_id = _make_record_slug(mfr_name, model, year)
            raw = _with_citation_doi(raw, doi_for(product.get("id")))

            payload = _cell_spec_submission_payload(
                raw,
                wid=wid,
                pid=pid,
                ver=ver,
                source_local_id=source_local_id,
                title=title,
            )
            outcomes.append(
                _journaled_submit(
                    journal,
                    payload,
                    url,
                    key,
                    title,
                    source_local_id=source_local_id,
                    publication_mode=publication_mode,
                    validation=validations[src],
                    allow_local_files=allow_local_files,
                )
            )

        # ── Cell instances ────────────────────────────────────────────────────
        cell_spec_dir = records_dir / "cell-spec"
        for src in _selected("cell-instance"):
            raw = parsed[src]
            ci = raw.get("cell_instance", {})
            label = ci.get("name") or ci.get("serial_number") or ci.get("short_id", "")
            source_local_id = ci.get("short_id") or label.lower().replace(" ", "-")
            raw = _with_citation_doi(raw, doi_for(ci.get("id")))
            spec_record = _find_spec_record(cell_spec_dir, ci.get("cell_spec_id", ""))

            # Relationships: instanceOf -> cell_spec, hasDataset -> each dataset,
            # hasTest -> each test (mirrors the canonical cell page model).
            self_iri = ci.get("id")
            related: list[dict] = []
            spec_iri = ci.get("cell_spec_id")
            if spec_iri:
                related.append({"relationship": "instanceOf", "resource_type": "cell_spec", "canonical_iri": spec_iri})
            for ds_iri in cell_datasets.get(self_iri, []):
                related.append({"relationship": "hasDataset", "resource_type": "dataset", "canonical_iri": ds_iri})
            for t_iri in cell_tests.get(self_iri, []):
                related.append({"relationship": "hasTest", "resource_type": "test", "canonical_iri": t_iri})

            # Hero preview: a linked dataset's static plot PNG (public R2 URL after upload).
            preview = None
            png = cell_preview_png.get(self_iri)
            if png:
                preview = {
                    "image": {
                        "src": png,
                        "alt": f"{label} dataset preview",
                        "caption": "Measurement preview from a linked dataset.",
                    }
                }

            payload = _cell_instance_submission_payload(
                raw,
                wid=wid,
                pid=pid,
                ver=ver,
                source_local_id=source_local_id,
                title=label,
                spec_record=spec_record,
                related_resources=related,
                preview=preview,
            )
            outcomes.append(
                _journaled_submit(
                    journal,
                    payload,
                    url,
                    key,
                    label,
                    source_local_id=source_local_id,
                    publication_mode=publication_mode,
                    validation=validations[src],
                    allow_local_files=allow_local_files,
                )
            )

        # ── Test specs (protocols) ────────────────────────────────────────────
        # Submitted as resource_type "test_spec"; stored in the spec/ IRI namespace
        # so a test's conformsTo relationship resolves to a real page.
        for src in _selected("test-protocol"):
            raw = parsed[src]
            tp = raw.get("test_spec", {})
            title = tp.get("name") or tp.get("short_id", "")
            source_local_id = tp.get("short_id") or src.stem
            raw = _with_citation_doi(raw, doi_for(tp.get("id")))

            # Reverse links: hasTest -> each test that conforms to this protocol.
            self_iri = tp.get("id")
            related = [
                {"relationship": "hasTest", "resource_type": "test", "canonical_iri": t_iri}
                for t_iri in spec_tests.get(self_iri, [])
            ]

            payload = _simple_submission_payload(
                raw,
                resource_type="test_spec",
                rdf_type="TestSpec",
                record_key="test_spec",
                wid=wid,
                pid=pid,
                ver=ver,
                source_local_id=source_local_id,
                title=title,
                related_resources=related,
            )
            outcomes.append(
                _journaled_submit(
                    journal,
                    payload,
                    url,
                    key,
                    title,
                    source_local_id=source_local_id,
                    publication_mode=publication_mode,
                    validation=validations[src],
                    allow_local_files=allow_local_files,
                )
            )

        # ── Tests ─────────────────────────────────────────────────────────────
        for src in _selected("test"):
            raw = parsed[src]
            test = raw.get("test", {})
            title = test.get("name") or test.get("short_id", "")
            source_local_id = test.get("short_id") or src.stem
            raw = _with_citation_doi(raw, doi_for(test.get("id")))

            # Relationships: testsCell -> cell, conformsTo -> test_spec.
            related = []
            if test.get("cell_id"):
                related.append({"relationship": "testsCell", "resource_type": "cell", "canonical_iri": test["cell_id"]})
            if test.get("protocol_id"):
                related.append(
                    {"relationship": "conformsTo", "resource_type": "test_spec", "canonical_iri": test["protocol_id"]}
                )

            payload = _simple_submission_payload(
                raw,
                resource_type="test",
                rdf_type="BatteryTest",
                record_key="test",
                wid=wid,
                pid=pid,
                ver=ver,
                source_local_id=source_local_id,
                title=title,
                related_resources=related,
            )
            outcomes.append(
                _journaled_submit(
                    journal,
                    payload,
                    url,
                    key,
                    title,
                    source_local_id=source_local_id,
                    publication_mode=publication_mode,
                    validation=validations[src],
                    allow_local_files=allow_local_files,
                )
            )

        # ── Datasets ──────────────────────────────────────────────────────────
        for src in _selected("dataset"):
            raw = parsed[src]
            ds = raw.get("dataset", {})
            title = ds.get("name") or ds.get("short_id", "")
            source_local_id = ds.get("short_id") or src.stem
            # Build the page-model distributions (promoting ws.process()'s plot files to
            # plot_data/plot_static) and strip those plots from the inner record so it
            # stays schema-valid (the inner role enum excludes plot_* roles).
            top_dists, inner_dists = _build_dataset_distributions(ds)
            self_iri = ds.get("id")
            if inner_dists:
                ds = {**ds, "distributions": inner_dists}
            else:
                # A collection (dcat:DatasetSeries) has no files of its own. The
                # schema requires at least one entry when the key is present, so
                # an empty list would be rejected at the registry gate.
                ds = {k: v for k, v in ds.items() if k != "distributions"}
            raw = _with_citation_doi({**raw, "dataset": ds}, doi_for(self_iri))

            # Relationships: aboutCell -> cell, generatedByTest -> test.
            links = ds_links.get(self_iri, {})
            related = []
            if links.get("cell"):
                related.append({"relationship": "aboutCell", "resource_type": "cell", "canonical_iri": links["cell"]})
            if links.get("test"):
                related.append(
                    {"relationship": "generatedByTest", "resource_type": "test", "canonical_iri": links["test"]}
                )

            # Preview image: this dataset's static plot PNG.
            preview = None
            png_dist = next((d for d in top_dists if d.get("role") == "plot_static"), None)
            if png_dist and png_dist.get("access_url"):
                preview = {"image": {"src": png_dist["access_url"], "alt": f"{title} preview"}}

            payload = _simple_submission_payload(
                raw,
                resource_type="dataset",
                rdf_type="Dataset",
                record_key="dataset",
                wid=wid,
                pid=pid,
                ver=ver,
                source_local_id=source_local_id,
                title=title,
                distributions=top_dists,
                related_resources=related,
                preview=preview,
            )
            outcomes.append(
                _journaled_submit(
                    journal,
                    payload,
                    url,
                    key,
                    title,
                    source_local_id=source_local_id,
                    publication_mode=publication_mode,
                    validation=validations[src],
                    allow_local_files=allow_local_files,
                )
            )

        if outcomes:
            self._search_cache = None
            live = [o for o in outcomes if o.get("status") == "published"]
            staged = [o for o in outcomes if o.get("status") == "validated"]
            skipped = [o for o in outcomes if o.get("status") == "skipped_journal"]
            failed = [o for o in outcomes if not o.get("ok")]
            print(
                f"\nAttempted {len(outcomes)} record(s) to {url}: "
                f"{len(live)} live, {len(staged)} staged for review, {len(failed)} failed"
                + (f", {len(skipped)} already submitted (journal)" if skipped else "")
            )
            if live:
                print("  Live records are on the platform. Run ws.status() to see them.")
            if staged:
                print(
                    "  Staged records await a registry admin's approval "
                    "(ws.pending() to list, ws.approve(<id>) to promote)."
                )
            if failed:
                print(f"  {len(failed)} record(s) did NOT publish -- see the ERROR lines above.")
                if not allow_partial:
                    raise SubmitError(
                        f"{len(failed)} of {len(outcomes)} record(s) failed to submit.",
                        failed=failed,
                        outcomes=outcomes,
                    )
        return outcomes

    def pending(
        self,
        registry_url: str | None = None,
        workspace_id: str | None = None,
    ) -> builtins.list[dict]:
        """List submissions staged for review (status ``validated``).

        Most submissions publish immediately, so this is usually empty — it only
        returns records submitted in staged-publication mode, which a registry
        admin must approve with :meth:`approve`.

        Example::

            submissions = ws.pending()
            # returns list of dicts with id, title, status, resource_type
        """
        import urllib.request

        url = self._require_registry(registry_url, "ws.pending()")
        wid = self._credential("BATTINFO_WORKSPACE_ID", explicit=workspace_id)
        if not wid:
            raise RuntimeError("workspace_id required. Pass it or set BATTINFO_WORKSPACE_ID.")

        endpoint = f"{url.rstrip('/')}/workspaces/{wid}/submissions?status_filter=validated"
        # Credentialed on the registry side; the admin token (the reviewer's credential)
        # or this workspace's publisher key both open the queue.
        req = urllib.request.Request(endpoint, headers=self._registry_read_headers())
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            submissions = json.loads(resp.read().decode())

        if not submissions:
            print("No submissions awaiting review.")
        else:
            print(f"{len(submissions)} submission(s) awaiting review:")
            for s in submissions:
                print(f"  {s['id']}  {s['title']}  [{s['status']}]")
        return submissions

    def approve(
        self,
        submission_id: str,
        reviewed_by: str | None = None,
        comment: str | None = None,
        registry_url: str | None = None,
        admin_token: str | None = None,
    ) -> dict:
        """Approve a pending submission.

        Parameters
        ----------
        submission_id:
            The submission ID returned by :meth:`pending`.
        reviewed_by:
            Name or identifier of the reviewer.
        comment:
            Optional review comment.
        registry_url:
            Registry base URL. Falls back to the workspace's registry, then to
            ``BATTINFO_REGISTRY_URL``.
        admin_token:
            Registry admin token. Falls back to ``BATTINFO_ADMIN_TOKEN`` from
            the environment, then from this workspace's ``.battinfo/credentials``.

        Example::

            submissions = ws.pending()
            ws.approve(submissions[0]["id"], reviewed_by="simon",
                       comment="Verified against datasheet.")
        """
        import urllib.request

        url = self._require_registry(registry_url, "ws.approve()")
        token = self._credential("BATTINFO_ADMIN_TOKEN", explicit=admin_token)
        if not token:
            raise RuntimeError(
                "admin_token required. Pass it, or set BATTINFO_ADMIN_TOKEN in the environment "
                "or in .battinfo/credentials."
            )

        body = json.dumps(
            {
                "reviewed_by": reviewed_by or "",
                "review_comment": comment or "",
            }
        ).encode()
        req = urllib.request.Request(
            f"{url.rstrip('/')}/submissions/{submission_id}/approve",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Battinfo-Admin-Token": token,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            result = json.loads(resp.read().decode())

        self._search_cache = None  # force rebuild on next search
        print(f"  approved: {result.get('title')}  [{result.get('status')}]  {result.get('canonical_iri', '')}")
        return result

    def process(self, *, max_points: int = 4000) -> builtins.list[Path]:
        """Generate a curve preview (interactive + static) for each saved dataset.

        For every dataset record, reads its processed BDF file (parquet or csv) and
        writes a downsampled Plotly figure ``<stem>.plot.json`` and a ``<stem>.png``
        next to it, then adds them to the dataset.  ``ws.upload()`` pushes them
        to R2 and ``ws.submit()`` exposes them as ``plot_data`` / ``plot_static``
        distributions — what the platform renders as the dataset's curve preview.

        Run **after** ``ws.save()`` and **before** ``ws.upload()``::

            ws.save()
            ws.process()
            ws.upload()
            ws.submit()

        Requires the plotting extras (``pip install "battinfo[processing]"``);
        datasets whose columns are unrecognised are skipped with a warning.

        The data file's location is screened as a Zenodo deposit screens it
        (see :meth:`zenodo`), before anything asks the file system about it: a
        file on another computer that this workspace did not register, or a
        path that goes up a folder with ``..``, is not read, and its dataset
        is skipped with a warning. The previews are registered as data files
        of this workspace (``.battinfo/deposit-files.json``), so a deposit
        reads them wherever they lie, on a lab share next to the data too.
        """
        import hashlib

        from battinfo import processing

        ds_dir = self._ws.source_root / "dataset"
        if not ds_dir.exists():
            print("  No dataset records -- run ws.save() first.")
            return []

        registered = self._registered_sources()
        written: list[Path] = []
        for record_path in sorted(ds_dir.glob("*.json")):
            raw = json.loads(record_path.read_text(encoding="utf-8"))
            ds = raw.get("dataset", {})
            dists = ds.get("distributions") or []
            if any((d.get("name") or "").endswith(".plot.json") for d in dists):
                continue  # preview already generated

            processed = next((d for d in dists if d.get("role") == "processed"), None)
            src_url = (processed or {}).get("content_url") or ds.get("access_url") or ""
            try:
                local = location_path(src_url, self._root, registered=registered)
            except UnsafeLocation as exc:
                print(f"  WARNING: dataset {ds.get('id') or record_path.name}: {exc.refusal()}; skipping preview")
                continue
            if local is None:
                print(f"  WARNING: processed file is not on this computer, skipping preview: {src_url}")
                continue
            if not local.exists():
                print(f"  WARNING: processed file not found, skipping preview: {local.name}")
                continue

            json_path, png_path = processing.generate_dataset_plots(
                local, local.parent, title=ds.get("name"), max_points=max_points
            )
            if json_path is None and png_path is None:
                print(f"  could not generate a preview for {ds.get('name')} (unrecognised columns?)")
                continue

            previews = [path for path in (json_path, png_path) if path is not None and path.exists()]
            # Registered before a record names them: a deposit reads a file on
            # another computer only when the workspace registered it.
            self._register_sources(previews, by="ws.process")
            for path, fmt in ((json_path, "application/json"), (png_path, "image/png")):
                if path is None or path not in previews:
                    continue
                dists.append(
                    {
                        # Schema-safe inner role; ws.submit() promotes *.plot.json/*.png
                        # to plot_data/plot_static in the page-model distributions.
                        "role": "other",
                        "content_url": path.resolve().as_uri(),
                        "name": path.name,
                        "encoding_format": fmt,
                        "content_size": str(path.stat().st_size),
                        "checksum": {"algorithm": "sha256", "value": hashlib.sha256(path.read_bytes()).hexdigest()},
                    }
                )
                written.append(path)
                print(f"  preview: {path.name}  ->  {ds.get('name')}")

            ds["distributions"] = dists
            raw["dataset"] = ds
            _atomic_write_text(record_path, json.dumps(raw, indent=2, ensure_ascii=False))

        print(f"\nGenerated {len(written)} preview file(s) across the datasets.")
        return written

    def _r2_configured(self) -> bool:
        """True when R2 object storage is configured (environment or this workspace's credentials file)."""
        return bool(self._credential("R2_ENDPOINT"))

    def _apply_zenodo_file_urls(self, record_url: str, plan: DepositFilePlan, *, local_only: bool = False) -> int:
        """Point dataset records at the Zenodo-hosted copies of their files.

        Mirrors what :meth:`upload` does for R2, without any extra storage:
        each distribution whose file the deposit carries as itself (not
        inside a zip archive) gets ``{record_url}/files/{name}``, with the
        deposit name percent-encoded, as its ``content_url``, the primary
        distribution sets the dataset ``access_url``, and a
        ``provenance.source_url`` naming a deposited file follows it. A
        record's file is found in *plan* by its resolved path, so two files
        that share a name each get their own URL. A copy hosted elsewhere (R2,
        ``plan.hosted``) stays as it is.

        The distribution states the file the deposit holds: its ``checksum``
        becomes the sha256 the plan measured, unless it already states the
        file's sha256 or md5, and a ``content_size`` it gives becomes the
        size the plan measured. A checksum written when the file was added
        is stale once the file changes, and the deposit holds the file as it
        is now.

        A record that points at the copy an earlier version of the deposit
        holds is moved to this one, unless *local_only*: a draft run moves
        only the records that still name a local file, which need a URL
        before :meth:`submit`, and leaves a record on a published copy, whose
        URL works, until the draft is published. A record already on this
        deposit's copy is brought up to date either way.

        The datasets in memory get the same locations, so a later
        :meth:`save` keeps them. Returns the number of records updated.
        """
        ds_dir = self._ws.source_root / "dataset"
        if not ds_dir.is_dir():
            return 0
        own_files = f"{record_url}/files/"

        def _deposited(location: object) -> DepositFile | None:
            if isinstance(location, str) and location in plan.hosted:
                return None  # the records keep pointing at a hosted copy
            if local_only and not is_local_location(location) and not str(location).startswith(own_files):
                return None  # a copy in another record moves when the draft is published
            entry = plan.entry_for(location)
            return None if entry is None or entry.archive else entry

        def _public_url(location: object) -> str | None:
            entry = _deposited(location)
            return f"{record_url}/files/{entry.segment}" if entry is not None else None

        patched = 0
        rewritten: dict[str, dict] = {}
        for record_path in sorted(ds_dir.glob("*.json")):
            # Read as the deposit read it (a BOM is allowed), and leave alone what
            # is not a dataset record: this runs after a publish, and must not fail.
            raw = _read_json(record_path)
            ds = raw.get("dataset") if isinstance(raw, dict) else None
            if not isinstance(ds, dict):
                continue
            dists = ds.get("distributions")
            if not dists or not isinstance(dists, list):
                continue
            new_dists: list[dict] = []
            primary_url: str | None = None
            changed = deposited = False
            for dist in dists:
                if not isinstance(dist, dict):
                    new_dists.append(dist)
                    continue
                local_url = dist.get("content_url") or ds.get("access_url") or ""
                entry = _deposited(local_url)
                if entry is None:
                    new_dists.append(dist)
                    continue
                deposited = True
                public_url = f"{record_url}/files/{entry.segment}"
                if public_url != dist.get("content_url"):
                    dist = {**dist, "content_url": public_url}
                    changed = True
                if entry.sha256 and not entry.stated_by(dist.get("checksum")):
                    dist = {**dist, "checksum": {"algorithm": "sha256", "value": entry.sha256}}
                    changed = True
                if entry.sha256 and "content_size" in dist and dist["content_size"] != str(entry.size):
                    dist = {**dist, "content_size": str(entry.size)}
                    changed = True
                new_dists.append(dist)
                if primary_url is None and dist.get("role") != "raw":
                    primary_url = public_url
            # The provenance source of a workspace dataset is its own data file;
            # point it at the deposited copy too, so no local path is left to publish.
            if _point_source_url_at_public_copy(raw, _public_url):
                changed = True
            if primary_url and primary_url != ds.get("access_url"):
                changed = True
            raw["dataset"]["distributions"] = new_dists
            if primary_url:
                raw["dataset"]["access_url"] = primary_url
            if deposited and isinstance(ds.get("id"), str):
                rewritten[ds["id"]] = raw
            if not changed:
                continue
            _atomic_write_text(record_path, json.dumps(raw, indent=2, ensure_ascii=False))
            self._session_paths.add(record_path)
            patched += 1
        self._point_datasets_in_memory_at(rewritten)
        return patched

    def _point_datasets_in_memory_at(self, records: Mapping[str, dict]) -> None:
        """Give each dataset in memory the locations its saved record was just given.

        *records* maps a dataset IRI to its record as written. :meth:`save`
        writes the datasets in memory, so without this the next save would
        point the records back at the local files.
        """
        for dataset in self._ws.datasets:
            record = records.get(dataset.id or "")
            body = record.get("dataset") if isinstance(record, dict) else None
            if not isinstance(body, dict):
                continue
            if isinstance(body.get("access_url"), str):
                dataset.access_url = body["access_url"]
            if isinstance(body.get("distributions"), list):
                dataset.distributions = copy.deepcopy(body["distributions"])
            provenance = record.get("provenance") if isinstance(record, dict) else None
            if isinstance(provenance, dict) and isinstance(provenance.get("source_url"), str):
                dataset.source.url = provenance["source_url"]

    def upload(
        self,
        bucket: str | None = None,
        public: bool = True,
        dry_run: bool = False,
    ) -> builtins.list[str]:
        """Upload dataset files to R2 and update ``access_url`` in saved records.

        Reads these from the environment, then from this workspace's
        ``.battinfo/credentials``:

        * ``R2_ENDPOINT``, e.g. ``https://<account>.eu.r2.cloudflarestorage.com``
        * ``R2_ACCESS_KEY_ID``
        * ``R2_SECRET_ACCESS_KEY``
        * ``R2_BUCKET``: the public bucket, ``battinfo-public`` in the
          ``ws.setup()`` template (``R2_BUCKET_PUBLIC`` is read when it is unset)
        * ``R2_BUCKET_PRIVATE``: the bucket for ``public=False``
        * ``R2_PUBLIC_BASE_URL``: the public bucket's download root, e.g.
          ``https://pub-xxx.r2.dev``

        Upload is **idempotent**: if an object already exists in R2 with a
        matching SHA-256, the file is skipped.  Each dataset record on disk is
        updated in-place so ``ws.submit()`` sends the R2 URL, not the local path,
        and so is each dataset in memory, so a later ``ws.save()`` keeps it.
        ``.battinfo/deposit-files.json`` records the local file behind each R2
        URL, and whether it went to the private bucket. A later
        :meth:`zenodo` refuses a deposit of files hosted in R2 unless it is
        called with ``archive_hosted_files=True``. It then archives each one
        from that local file and names in a warning each one from the private
        bucket, since the deposit makes it public; the records keep the R2
        URLs.

        Parameters
        ----------
        bucket:
            Override the R2 bucket name.
        public:
            Write to the public bucket (default), with a public-read ACL and
            download URLs under ``R2_PUBLIC_BASE_URL``. ``False`` writes to
            ``R2_BUCKET_PRIVATE`` (or *bucket*) without the ACL and gives the
            records ``s3://`` locations. It never falls back to the public
            bucket: with no private bucket set it raises. A Zenodo deposit
            archives such a file only with ``archive_hosted_files=True``,
            which makes it public, and names it in a warning.
        dry_run:
            Print what would be uploaded without doing anything.

        Returns
        -------
        list[str]
            The new location of each dataset's file: a download URL under
            ``R2_PUBLIC_BASE_URL``, or an ``s3://`` location for a private
            upload or when that is unset.

        Example::

            ws.save()
            ws.upload()    # files → R2, access_url updated
            ws.submit()    # registry receives R2 URLs
        """
        try:
            import boto3
            from boto3.s3.transfer import TransferConfig
        except ImportError:
            raise ImportError("boto3 is required for ws.push_datasets(). Install with: pip install boto3")

        endpoint = self._credential("R2_ENDPOINT")
        access_key = self._credential("R2_ACCESS_KEY_ID")
        secret_key = self._credential("R2_SECRET_ACCESS_KEY")
        if public:
            bucket_name = self._credential("R2_BUCKET", explicit=bucket) or self._credential("R2_BUCKET_PUBLIC")
            public_base = (self._credential("R2_PUBLIC_BASE_URL") or "").rstrip("/")
        else:
            # R2_BUCKET is the public bucket (the setup() template sets it to
            # battinfo-public), and R2_PUBLIC_BASE_URL is its download root: a
            # private upload uses neither, and its records get s3:// locations.
            bucket_name = self._credential("R2_BUCKET_PRIVATE", explicit=bucket)
            public_base = ""

        if not endpoint:
            raise RuntimeError("R2_ENDPOINT required. Set it or add to .battinfo/credentials.")
        if not access_key or not secret_key:
            raise RuntimeError("R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY required.")
        if not bucket_name and not public:
            raise RuntimeError(
                "R2_BUCKET_PRIVATE required for upload(public=False). Set it or add it to "
                ".battinfo/credentials, or pass bucket=...; R2_BUCKET is the public bucket, "
                "and a private upload never uses it."
            )
        if not bucket_name:
            raise RuntimeError("R2_BUCKET required. Set it or add to .battinfo/credentials.")

        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        transfer_cfg = TransferConfig(
            multipart_threshold=50 * 1024 * 1024,  # 50 MB
            multipart_chunksize=10 * 1024 * 1024,  # 10 MB
            max_concurrency=4,
        )

        ds_dir = self._ws.source_root / "dataset"
        if not ds_dir.exists():
            print("  No dataset records -- run ws.save() first.")
            return []

        # A location is screened as a Zenodo deposit screens it: a network path
        # outside the workspace that it did not register, or a path that goes
        # up a folder, is never read.
        index = load_deposit_index(self._root)
        registered = registered_keys(index)
        urls: list[str] = []
        rewritten: dict[str, dict] = {}
        for record_path in sorted(ds_dir.glob("*.json")):
            raw = json.loads(record_path.read_text(encoding="utf-8"))
            ds = raw.get("dataset", {})
            short_id = ds.get("short_id", "")
            dists = ds.get("distributions") or []
            if not dists:
                continue

            # Upload every distribution (processed + any raw source files) so each
            # file in the dataset gets a resolvable public URL, not just the first.
            new_dists: list[dict] = []
            primary_url: str | None = None
            public_by_path: dict[str, str] = {}
            hosted: dict[str, IndexedFile] = {}
            for dist in dists:
                local_url = dist.get("content_url") or ds.get("access_url") or ""
                try:
                    local_file = location_path(local_url, self._root, registered=registered)
                except UnsafeLocation as exc:
                    print(f"  WARNING: dataset {ds.get('id') or record_path.name}: {exc.refusal()}")
                    new_dists.append(dist)
                    continue
                if local_file is None:
                    new_dists.append(dist)  # already at a URL elsewhere
                    continue

                if not local_file.exists():
                    print(f"  WARNING: file not found, skipping: {local_file.name}")
                    new_dists.append(dist)
                    continue

                # Size, md5 and SHA-256 of the local file, from one read of it.
                measured = measured_file(local_file, local_file.name)
                sha256 = measured.sha256

                # R2 key: datasets/{short_id}/{filename}; the public URL carries
                # each part of it percent-encoded.
                r2_key = f"datasets/{short_id}/{local_file.name}"
                public_url = (
                    f"{public_base}/{'/'.join(url_segment(part) for part in r2_key.split('/'))}"
                    if public_base
                    else f"s3://{bucket_name}/{r2_key}"
                )

                if dry_run:
                    print(f"  [dry-run] would upload {local_file.name} -> {r2_key}")
                else:
                    # Check if already uploaded with matching checksum
                    already_uploaded = False
                    try:
                        head = client.head_object(Bucket=bucket_name, Key=r2_key)
                        remote_sha = head.get("Metadata", {}).get("sha256", "")
                        if remote_sha == sha256:
                            already_uploaded = True
                    except client.exceptions.ClientError:
                        pass  # object does not exist

                    if already_uploaded:
                        print(f"  skip (exists): {r2_key}")
                    else:
                        print(f"  uploading: {local_file.name}  ({local_file.stat().st_size / 1e6:.1f} MB)")
                        client.upload_file(
                            str(local_file),
                            bucket_name,
                            r2_key,
                            ExtraArgs={
                                "ContentType": dist.get("encoding_format") or "application/octet-stream",
                                "Metadata": {"sha256": sha256},
                                **({"ACL": "public-read"} if public else {}),
                            },
                            Config=transfer_cfg,
                        )

                        # Verify checksum after upload
                        head = client.head_object(Bucket=bucket_name, Key=r2_key)
                        remote_sha = head.get("Metadata", {}).get("sha256", "")
                        if remote_sha != sha256:
                            raise RuntimeError(
                                f"Checksum mismatch after upload for {r2_key}: expected {sha256}, got {remote_sha}"
                            )
                        print(f"    -> {public_url}")

                # Update this distribution with the R2 URL + checksum
                dist = {**dist, "content_url": public_url, "checksum": {"algorithm": "sha256", "value": sha256}}
                new_dists.append(dist)
                public_by_path[path_key(local_file)] = public_url
                hosted[public_url] = IndexedFile(
                    path=str(local_file.resolve()),
                    size=measured.size,
                    md5=measured.md5,
                    sha256=sha256,
                    private=not public,
                )
                # The primary (processed) distribution sets the dataset access_url.
                if primary_url is None and dist.get("role") != "raw":
                    primary_url = public_url

            if not new_dists:
                continue
            urls.append(primary_url or new_dists[0]["content_url"])
            raw["dataset"]["access_url"] = primary_url or new_dists[0]["content_url"]
            raw["dataset"]["distributions"] = new_dists

            def _r2_public_url(location: object) -> str | None:
                key = location_key(location, self._root, registered=registered) if isinstance(location, str) else None
                return public_by_path.get(key) if key is not None else None

            _point_source_url_at_public_copy(raw, _r2_public_url)
            # The local file behind each URL is recorded before the record names
            # only the URL, so a Zenodo deposit can still find the file.
            if note_hosted(index, hosted):
                save_deposit_index(self._root, index)
            _atomic_write_text(record_path, json.dumps(raw, indent=2, ensure_ascii=False))
            if isinstance(ds.get("id"), str):
                rewritten[ds["id"]] = raw

            # Keep session paths in sync so submit() picks up the updated record
            self._session_paths.add(record_path)

        self._point_datasets_in_memory_at(rewritten)
        print(f"\nPushed {len(urls)} dataset(s) to {bucket_name}")
        return urls

    def _zenodo_token(self, token: str | None, sandbox: bool) -> str:
        """The Zenodo token: *token*, else ``ZENODO_SANDBOX_TOKEN`` or ``ZENODO_API_TOKEN``.

        The variable is looked up in the order of :meth:`_resolve_credential`:
        a :meth:`login` of this session, the environment, then this
        workspace's ``.battinfo/credentials``.
        """
        var = "ZENODO_SANDBOX_TOKEN" if sandbox else "ZENODO_API_TOKEN"
        tok = self._credential(var, explicit=token)
        if not tok:
            raise RuntimeError(
                f"Zenodo token required. Pass token= to ws.zenodo(), or set {var} in the environment "
                "or in .battinfo/credentials."
            )
        return tok

    def _deposit_creators(self, creators: builtins.list[dict] | None, *, required: bool = True) -> builtins.list[dict]:
        """The creators of this workspace's Zenodo deposit, each ORCID a bare id.

        The first of these that names anyone: *creators*, the workspace
        contributors (:meth:`contributor`), and the creator set with
        ``battinfo config set creator`` (``~/.battinfo/config.yaml``). With
        *required*, finding none raises ValueError. :meth:`zenodo` asks before
        it sends anything, and :meth:`publish` with ``zenodo=True`` before it
        saves or uploads.
        """
        chosen: builtins.list[Any] = list(creators or [])
        if not chosen:
            chosen = [ref.to_dict() for ref in self._get_contributors()]
        if not chosen:
            from battinfo.config import resolve_creators  # noqa: PLC0415

            chosen = list(resolve_creators(None))
        if not chosen and required:
            raise ValueError(
                "No creators for the Zenodo deposit: creators= is empty, the workspace has no "
                "contributors, and no creator was read from ~/.battinfo/config.yaml. Zenodo does "
                f"not publish a deposit without one. Nothing was sent to Zenodo. {_CREATORS_HINT}"
            )
        return _deposit_agents(chosen, "creator")

    def zenodo(
        self,
        *,
        record_id: str | None = None,
        publish: bool = False,
        sandbox: bool = False,
        token: str | None = None,
        community: str | None = "battery-knowledge-base",
        title: str | None = None,
        description: str | None = None,
        creators: builtins.list[dict] | None = None,
        contributors: builtins.list[dict] | None = None,
        license: str | None = None,
        keywords: builtins.list[str] | None = None,
        archive_hosted_files: bool = False,
    ) -> "ZenodoResult":
        """Deposit workspace records and data files to Zenodo.

        Creates a new Zenodo record or a new version of an existing one, uploads
        all data files plus a ``battinfo.json`` linked data document, and
        optionally publishes.

        Re-running it continues the workspace's record and never starts a second
        one by itself. With ``record_id=None`` it *warns* and moves the workflow
        forward: a published record forks a NEW VERSION; an existing open draft is
        UPDATED in place (Zenodo permits one open draft per concept). A recorded
        draft is first checked with Zenodo, so a draft published on the website
        since, or by a run that stopped before it recorded the publish, gets a new
        version. A run can still stop with a refusal, and each refusal names the
        way on. A recorded draft deleted on the website is one: the way on is a
        new version of the published record the draft was made from
        (``record_id=``), or, when nothing of the record was published, a new
        record. Delete ``.battinfo/zenodo.json`` (``.battinfo/zenodo-sandbox.json``
        for the sandbox) to force a brand-new record. Default ``publish=False``
        leaves a reviewable draft, so a new version is never published (and no DOI
        minted) without an explicit ``publish=True`` or a click on Zenodo.

        Each Zenodo has its own record: ``.battinfo/zenodo.json`` names the one on
        zenodo.org and ``.battinfo/zenodo-sandbox.json`` the one on the sandbox, so
        a dry run with ``sandbox=True`` never touches the record on zenodo.org,
        and the next deposit there continues it. A sandbox deposit leaves the
        dataset records as they are, and :meth:`submit` never records its DOI.

        Nothing is sent before the token and the creators are known and the
        deposit graph passes the publication check. A draft gets that check as
        a publish does, since it is one click from published. The deposit is
        recorded in the state file as soon as it exists, so a run that fails
        after that leaves a draft the next run updates. The metadata goes up
        before any file, and metadata Zenodo does not accept stops the run with
        a :class:`~battinfo.zenodo.ZenodoError` naming the fields. The data
        files go up before the graph and the RO-Crate that describe them, and
        the dataset records are pointed at the deposited files last, after the
        publish when there is one. A record that names a local file is pointed
        there after a draft too, so :meth:`submit` sends https URLs, which work
        once the draft is published. A record on the copy an earlier published
        version holds keeps that working URL until the new version is
        published. The datasets in memory are pointed there too, so a later
        :meth:`save` keeps the URLs. Each distribution then states the sha256 of
        the file the deposit holds (and its size, when it gives one), as the
        deposit graph does, so a file that changed since it was added is
        described as it is now.

        A record pointed at its deposited copy keeps its data in later deposits.
        ``.battinfo/deposit-files.json`` records the local file behind each
        deposited copy, with its size, md5 and sha256, so a new version, a retry
        after a failed run, or a new record after ``.battinfo/zenodo.json`` was
        deleted finds the file again. A draft's files count there only once the
        draft is published, so a draft deleted on the website leaves the entries
        of the published record as they were. A file whose local copy is gone is
        kept as the record the deposit starts from holds it (the copy a new
        version takes over from the one before), when its md5 is the one
        recorded. Zenodo is asked for that record's files before anything is
        created or changed, and a copy it does not hold refuses the deposit,
        naming each dataset and how to point it at its local file again; with no
        record to start from, a file with no local copy refuses the deposit
        before anything is sent. Each file keeps its name, and so its URL, from
        one version to the next.

        A deposit whose records point at files :meth:`upload` put in R2 storage
        is refused before anything is sent, and the refusal names the files,
        unless ``archive_hosted_files=True``: the deposit then archives each from
        the local file :meth:`upload` recorded, and the records keep their R2
        URLs.

        A record that points at a copy of its data the deposit should carry, but
        whose local file this workspace has no record of, refuses the deposit
        rather than being linked to: an R2 copy an earlier build's
        :meth:`upload` made, an ``s3:`` URL, and a file in a sandbox record
        (from a deposit on zenodo.org). Any other Zenodo file URL on the
        deposit's Zenodo that the workspace cannot place is put to Zenodo
        before the deposit is created or changed, whether or not the deposit
        continues a record, since an earlier build pointed records at the drafts
        and versions it made without recording them. A draft of this account
        that is not published refuses the deposit, since no reader can download
        its files, and so does a version of the record the deposit continues.
        A published record of this account in another concept, and anyone
        else's record, stay links. The refusal names each dataset and how to
        point it at its local file again.

        A deposit carries every record or none. A record the deposit graph
        cannot convert, or a distribution entry that is not an object with a
        ``content_url``, refuses the deposit, a draft too, before anything is
        sent, and the refusal names each record and why. A time that is no date,
        such as a Unix time in milliseconds, is only left out, with a warning.
        Once the files are up, the deposit's file list is checked: every file
        sent must be on it with its md5, every download URL in the graph under
        this record must name a file the deposit holds, a sha256 or size a
        distribution of such a file states must be the one the deposit read,
        and every distribution of a member dataset needs a download URL, a
        file of the deposit or an http(s) URL elsewhere. A publish that fails
        the check is refused before the DOI is minted; a draft is kept, with a
        warning that lists the problems.

        Each local data file is deposited once, under its own name, however many
        distributions name it. Names are compared as Windows and macOS compare
        them, ignoring case and Unicode normalisation: a file whose name another
        file of the deposit already has gets a short hash of its path in the
        workspace in front (``3f2a9c1d-cycling.csv``), and the first file keeps
        its name. URLs carry the names percent-encoded.
        A deposit of more than 90 data files is zipped, one archive per test kind.

        Each data file location in the records is screened from its text before
        anything asks the file system about it. A file on this computer is read
        wherever it lies. A file on another computer (``file://server/share/...``
        or ``\\\\server\\share\\...``) is read only when it lies in the workspace
        folder, as every file of a workspace kept on a network share or a mapped
        drive does, or when this workspace registered it: ``ws.add(..., data=...)``
        and :meth:`convert` register the files they are given, and :meth:`process`
        the previews it writes, in ``.battinfo/deposit-files.json``. A path that
        goes up a folder with ``..`` is never read. A record that names a file
        the screen refuses stops the deposit before anything is sent, and the
        refusal names it.

        The token is *token*, else ``ZENODO_API_TOKEN`` (production) or
        ``ZENODO_SANDBOX_TOKEN`` (sandbox) from the environment, then from this
        workspace's ``.battinfo/credentials``.

        Parameters
        ----------
        record_id:
            ``None`` → continue this workspace's record (new version of a published
            record, or update its open draft); first run creates a new record. An
            explicit Zenodo record ID forks a new version from that record.
        publish:
            ``False`` (default) leaves a draft for review: publish it by clicking
            on Zenodo, or re-run with ``publish=True``. Either way the publication
            check runs before Zenodo is contacted, so a refusal leaves no draft
            behind. With ``True`` the deposit's files are checked after the
            upload and before the publish, and a draft whose files do not match
            stays a draft.
        sandbox:
            Use ``sandbox.zenodo.org`` for testing. A dry run there leaves the
            records as they are, and its record is kept in
            ``.battinfo/zenodo-sandbox.json``, apart from the record on
            zenodo.org: nothing needs deleting before the real deposit.
        community:
            Zenodo community identifier (default ``"battery-knowledge-base"``).
            ``None`` leaves the deposit out of any community.
        creators:
            List of ``{"name": "Family, Given", "affiliation": "...", "orcid": "..."}``
            dicts. Without them the workspace contributors (:meth:`contributor`)
            are the creators, and without those the creator set with
            ``battinfo config set creator``. With none of these the call is
            refused before anything is sent. An ORCID may be the bare id or its
            ``https://orcid.org/`` URL; Zenodo gets the bare id.
        contributors:
            More people, as dicts like ``creators``, each with an optional Zenodo
            contributor ``"type"`` (default ``"ProjectMember"``).
        keywords:
            Extra keywords appended to auto-derived list.
        archive_hosted_files:
            Archive the data files :meth:`upload` put in R2 storage, which a
            deposit otherwise refuses. Each comes from its local file, and a
            warning names each one from the private bucket
            (``upload(public=False)``), since the deposit makes it public.

        Returns
        -------
        ZenodoResult

        Example::

            ws.save()
            result = ws.zenodo()               # a draft, for review on Zenodo
            print(result.draft_url)

            result = ws.zenodo(publish=True)   # publishes that same draft
            ws.submit()                        # records carry the deposit's DOI

        License precedence: an explicit ``license=`` here is authoritative for the
        deposit; otherwise the workspace default (``ws.license(...)``) is used; if
        neither is set, ``cc-by-4.0`` is applied (Zenodo requires a license).
        """
        import tempfile

        from battinfo.zenodo import KeptFilesError, ZenodoClient, ZenodoError

        # Each numbered step runs only once the steps before it have passed, so
        # a refusal leaves as little behind as it can. ws.publish(zenodo=True)
        # runs step 1 before it saves or uploads anything.

        # ── 1. Token, creators and the stored record, before anything is sent ─
        # License precedence: explicit arg > workspace default > cc-by-4.0.
        if license is None:
            license = self._get_license() or "cc-by-4.0"
        tok = self._zenodo_token(token, sandbox)
        creators = self._deposit_creators(creators)
        contributors = _deposit_agents(contributors or [], "contributor")
        # The record this workspace continues on this Zenodo (.battinfo/zenodo.json,
        # or .battinfo/zenodo-sandbox.json for the sandbox) and the local files
        # behind its deposits (.battinfo/deposit-files.json); either file that
        # cannot be read stops the run here. The record on the other Zenodo is
        # left as it is.
        environment = zenodo_environment(sandbox)
        recorded_in = state_file(environment)
        state = self._load_zenodo_state(environment)
        index = load_deposit_index(self._root)
        record_id = str(record_id) if record_id is not None else None

        # ── 2. Records, read fail-closed ───────────────────────────────────────
        records_dir = self._ws.source_root
        if not records_dir.exists():
            raise RuntimeError("No records found — run ws.save() first.")

        # The deposit's parameter sets must pass the record check ws.submit() runs.
        deposit_records, replaced_legacy = _read_deposit_record_sets(records_dir)
        _print_replaced_legacy_parameter_sets(replaced_legacy)
        parameter_set_errors = _parameter_set_publication_errors(deposit_records)
        if parameter_set_errors:
            raise RuntimeError(
                f"Refusing to deposit: {len(parameter_set_errors)} parameter set(s) cannot be "
                "published, so nothing was sent to Zenodo: " + " | ".join(parameter_set_errors)
            )

        # One title for the deposit graph, the RO-Crate and the Zenodo metadata:
        # the one given, or the automatic one the metadata would derive, so a
        # deposit made without a title still names its catalog node.
        title = self._deposit_title(title)
        domain = ZENODO_HOSTS[environment]

        # ── 3. File plan ───────────────────────────────────────────────────────
        # One entry per file, with its deposit name and digests. Everything
        # below takes file names and URLs from the plan. A record that points
        # at a copy an earlier deposit made is found through the index: its
        # local file goes up again when it changed, and when it is gone the
        # copy the record already holds is kept.
        context = self._deposit_context(sandbox=sandbox, record_id=record_id, state=state, index=index)
        plan = self._deposit_file_plan(records_dir, context=context)
        kept_files = plan.kept_files()
        # A file ws.upload() put in R2 storage goes into the deposit only when
        # the call asks for it, and one from the private bucket with a warning.
        if archive_hosted_files:
            self._warn_private_hosted_files(plan)
        else:
            self._refuse_hosted_files(plan, verb="publish" if publish else "deposit")

        # ── 4. Placeholder graph, checked for a draft as for a publish ─────────
        # A refusal here leaves no draft behind. The graph is built as
        # ws.preview_jsonld() builds it, with placeholders for the record id and
        # DOI the deposit does not have yet. No check reads those values beyond
        # their form, which the placeholders share, and the dataset records take
        # the deposited file URLs only at the end, so the verdict is the one the
        # deposit's own graph gets. That graph is checked again before a DOI is
        # minted. A record the plan or the graph had to leave out refuses the
        # deposit first, naming each record and why.
        omissions = list(plan.omissions)
        version_of = record_id or (state.get("record_id") if state.get("published") else None)
        placeholder_graph = self._build_zenodo_jsonld(
            zenodo_record_id=0,
            prereserved_doi="10.5281/zenodo.RECORD_ID",
            record_url=f"https://{domain}/records/RECORD_ID",
            file_plan=plan,
            title=title,
            description=description or "",
            creators=creators,
            contributors=contributors,
            license=license or "",
            keywords=keywords or [],
            is_version_of=f"https://{domain}/records/{version_of}" if version_of else "",
            omissions=omissions,
        )
        self._assert_publishable(placeholder_graph, omissions=omissions, nothing_sent=True, draft=not publish)
        # The records the deposit holds: ws.submit() records its DOI on these only.
        held_records = _deposit_record_iris(deposit_records, placeholder_graph)

        # ── 5. Reconcile with the live deposit ─────────────────────────────────
        # A recorded draft may have been published since: on the Zenodo
        # website, or by a run that stopped before it recorded the publish.
        # Zenodo then holds a published record, which gets a new version. A
        # draft deleted there stops the run with the way on that keeps the
        # record's lineage.
        client = ZenodoClient(token=tok, sandbox=sandbox)
        live_draft: dict | None = None
        if record_id is None and state and not state.get("published"):
            try:
                live_draft = self._reconcile_zenodo_draft(client, state, index=index)
            except ZenodoError as exc:
                raise ZenodoError(_unreadable_draft_message(state, exc), status=exc.status) from exc
        # A record may point at a Zenodo file the workspace cannot place: a
        # copy an earlier build made in a draft or a version it never
        # recorded, or a link to someone else's record. Only Zenodo knows; ask
        # before anything is created or changed.
        self._refuse_unknown_zenodo_copies(
            client,
            plan,
            context,
            continues=record_id or state.get("deposit_id") or state.get("record_id"),
            live_draft=live_draft,
        )

        # What this call does to the workspace's record (warn, never error): a
        # published record forks a new version; an open draft is updated in place.
        stored_record = state.get("record_id")
        record_id, reuse_draft_id, _version_warning = _plan_zenodo_deposit(
            stored_record,
            bool(state.get("published")),
            record_id,
            recorded_in=recorded_in,
        )
        # A file with no local copy is kept as the record the deposit starts
        # from holds it; a copy that record lacks refuses the deposit before a
        # draft is made or changed.
        self._refuse_missing_kept_copies(
            client,
            plan,
            deposit_records.get("dataset", []),
            starts_from=reuse_draft_id if reuse_draft_id is not None else record_id,
            updates_draft=reuse_draft_id is not None,
        )
        if _version_warning:
            warnings.warn(_version_warning, stacklevel=2)
            print(f"  WARNING: {_version_warning}")

        tmpdir = Path(tempfile.mkdtemp(prefix="battinfo-zenodo-"))
        try:
            # The files to upload: the data files themselves, or one zip per
            # test kind when there are more than _ZENODO_ZIP_THRESHOLD.
            data_files = self._bundle_data_files(tmpdir, plan)

            # ── 6. Create or reuse the deposit, and record it ──────────────────
            if reuse_draft_id is not None:
                deposit = live_draft if live_draft is not None else client.get_deposit(reuse_draft_id)
            elif record_id is not None:
                deposit = client.create_new_version(record_id)  # fork from published
            else:
                deposit = client.create_empty_deposit()  # brand-new record

            deposit_id: int = deposit["id"]
            zenodo_record_id: int = deposit["record_id"]
            prereserved_doi: str = (
                deposit.get("metadata", {}).get("prereserve_doi", {}).get("doi", f"10.5281/zenodo.{zenodo_record_id}")
            )
            # The concept record groups the versions of one record. A run that
            # continues the stored record keeps the concept id stored with it.
            continues = bool(stored_record) and (reuse_draft_id is not None or record_id == stored_record)
            concept = str(
                (state.get("concept_record_id") if continues else None)
                or deposit.get("conceptrecid")
                or concept_of_record(index, environment, str(record_id or stored_record or ""))
                or record_id
                or (stored_record if continues else None)
                or zenodo_record_id
            )
            # Recorded now, so a run that fails below leaves a draft the next
            # run updates instead of one it forgets. A draft of a new version
            # keeps the published record it was made from, the way on should
            # the draft be deleted on the website.
            made_from = state.get("version_of") if reuse_draft_id is not None else record_id
            state = {
                "environment": environment,
                "concept_record_id": concept,
                "record_id": str(zenodo_record_id),
                "deposit_id": str(deposit_id),
                "doi": prereserved_doi,
                "published": False,
                **({"version_of": str(made_from)} if made_from else {}),
                "records": held_records,
            }
            self._save_zenodo_state(state)
            # The records may point at files under this version, under the one it
            # was made from, and under the one the workspace recorded before.
            known = [str(zenodo_record_id), record_id or "", stored_record if continues else ""]
            if note_deposit(index, environment, concept, record_ids=[item for item in known if item]):
                save_deposit_index(self._root, index)

            # A version (new fork or an updated draft) is a version of its concept record;
            # record the lineage in the JSON-LD. For a new fork that's the source record_id;
            # for a reused draft it's the deposit's concept record id.
            if record_id:
                is_version_of = f"https://{domain}/records/{record_id}"
            elif reuse_draft_id and deposit.get("conceptrecid"):
                is_version_of = f"https://{domain}/records/{deposit['conceptrecid']}"
            else:
                is_version_of = ""

            record_url = f"https://{domain}/records/{zenodo_record_id}"
            draft_url = f"https://{domain}/deposit/{deposit_id}"

            # ── 7. Metadata, before any file ───────────────────────────────────
            # Metadata Zenodo does not accept raises a ZenodoError naming the
            # fields, so no file goes up to a deposit whose metadata was refused.
            try:
                client.update_metadata(
                    deposit_id,
                    self._build_zenodo_metadata(
                        title=title,
                        description=description,
                        creators=creators,
                        contributors=contributors,
                        license=license,
                        community=community,
                        extra_keywords=keywords,
                    ),
                )
            except ZenodoError as exc:
                raise ZenodoError(
                    f"{exc} This run uploaded no file. The draft ({draft_url}) is recorded in "
                    f"{recorded_in}, so the next ws.zenodo() updates it.",
                    status=exc.status,
                ) from exc

            # ── 8. and 9. Data files, then the graph and the RO-Crate ──────────
            # Single consolidated JSON-LD (replaces all individual JSON records)
            jsonld = self._build_zenodo_jsonld(
                zenodo_record_id=zenodo_record_id,
                prereserved_doi=prereserved_doi,
                record_url=record_url,
                file_plan=plan,
                title=title,
                description=description or "",
                creators=creators,
                contributors=contributors,
                license=license or "",
                keywords=keywords or [],
                is_version_of=is_version_of,
            )
            (tmpdir / BATTINFO_LD_FILENAME).write_text(
                json.dumps(jsonld, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            # RO-Crate metadata for EOSC portal compliance
            self._build_rocrate(
                tmpdir,
                [*data_files, *kept_files],
                title=title,
                description=description or "",
                creators=creators,
                contributors=contributors,
                license=license,
                zenodo_record_id=zenodo_record_id,
                prereserved_doi=prereserved_doi,
                sandbox=sandbox,
            )

            # Each file under its deposit name, the data files from where they
            # are, and before the graph and the RO-Crate that link to them. The
            # map is built from the plan, not from a folder listing, which on
            # macOS can hand names back in another Unicode form.
            upload_map = {f.path: f.name for f in sorted(data_files, key=lambda f: f.name)}
            # The md5 of each file as sent, for the check in step 10.
            sent = {f.name: f.md5 for f in data_files}
            for name in (BATTINFO_LD_FILENAME, _ROCRATE_FILENAME):
                upload_map[tmpdir / name] = name
                sent[name] = measured_file(tmpdir / name, name).md5
            # A file with no local copy stays as the deposit holds it, with the
            # md5 recorded when it was deposited. Only files nothing names any
            # more are removed, so a new version keeps the data files it takes
            # over from the one before.
            keep = {f.name: f.md5 for f in kept_files}
            # Incremental sync: only files whose content changed are uploaded;
            # unchanged files already on the deposit are kept.
            try:
                sync = client.sync_files(deposit_id, upload_map, keep=keep)
            except KeptFilesError as exc:
                # Checked in step 5 against the record the draft starts from;
                # the draft itself lacks the copy all the same.
                raise ZenodoError(
                    _kept_copies_refusal(plan, deposit_records.get("dataset", []), exc.files, f"the draft {draft_url}")
                    + f" No file on the draft was changed, and the draft is recorded in {recorded_in}."
                ) from exc
            except ZenodoError as exc:
                raise ZenodoError(
                    f"{exc} The draft ({draft_url}) is recorded in {recorded_in}, so the next ws.zenodo() updates it.",
                    status=exc.status,
                ) from exc
            print(
                f"  Files on deposit {deposit_id}: "
                f"{len(sync['uploaded'])} uploaded, {len(sync['kept'])} unchanged (kept), "
                f"{len(sync['removed'])} removed"
            )
            for name in sync["uploaded"]:
                print(f"    + {name}")
            # The local file behind each copy the draft holds, recorded before
            # any record names only the copy, so the next deposit still finds
            # it. They count for the published versions only once the draft is
            # published: a draft deleted on the website leaves the entries of
            # the record it was made from as they were.
            # A kept copy is listed too when its local file and digests are
            # known, so the draft's entries cover every data file it holds.
            deposited = {
                f.name: IndexedFile(path=str(f.path), size=f.size, md5=f.md5, sha256=f.sha256)
                for f in plan.files
                if not f.archive and (not f.kept or (f.path.parts and f.md5))
            }
            if note_deposit(index, environment, concept, files=deposited, draft=str(zenodo_record_id)):
                save_deposit_index(self._root, index)

        finally:
            remove_temp_tree(tmpdir)

        # ── 10. Check the deposit's files ──────────────────────────────────────
        # The deposit must hold every file sent, with its md5, every file kept,
        # and every file the graph links to under this record; each
        # distribution of a member dataset needs a download URL, a file of the
        # deposit or an http(s) URL elsewhere. A distribution of a planned file
        # must state the sha256 and size the plan measured. A publish is
        # refused here, before the DOI exists; a draft is left as it is, with
        # the problems reported.
        try:
            listing: object = client.list_files(deposit_id)
            file_problems = deposit_file_problems(
                jsonld,
                files_base=f"{record_url}/files",
                listing=listing,
                sent=sent,
                kept=keep,
                planned={f.name: f for f in plan.files},
            )
        except ZenodoError as exc:
            file_problems = [f"the deposit's files could not be listed ({exc})"]
        if file_problems and publish:
            raise RuntimeError(
                "Refusing to publish: the deposit does not hold the files its records point at: "
                + "; ".join(file_problems)
                + f". Nothing was published. The draft ({draft_url}) is recorded in "
                f"{recorded_in}, so the next ws.zenodo() updates it."
            )
        if file_problems:
            warnings.warn(
                f"The Zenodo draft {draft_url} does not hold the files its records point at: "
                + "; ".join(file_problems)
                + ". Do not publish it as it is.",
                stacklevel=2,
            )
            print(f"  WARNING: the draft does not hold the files its records point at ({len(file_problems)}):")
            for problem in file_problems:
                print(f"    {problem}")

        # ── 11. and 12. Publish, and record the deposit as published ───────────
        doi = prereserved_doi
        published = False

        if publish:
            self._assert_publishable(jsonld)  # fail closed BEFORE minting an irreversible DOI (R-7)
            pub = client.publish_deposit(deposit_id)
            doi = pub.get("doi", prereserved_doi)
            published = True
            # Published, the record is the version the next one is made from.
            state = {key: value for key, value in state.items() if key != "version_of"}
            state = {**state, "doi": doi, "published": True}
            self._save_zenodo_state(state)
            self._note_draft_published(index, environment, concept, str(zenodo_record_id))
            print(f"  Published: {record_url}")
            print(f"  DOI: {doi}")
        else:
            print(f"  Draft (not published): {draft_url}")
            print(f"  Pre-reserved DOI: {doi}")
            print('  Review it, then click "Publish" on Zenodo -- or re-run with publish=True.')

        # ── 13. Point the dataset records at the deposited files ───────────────
        # Zenodo now hosts these files: ws.submit() then sends resolvable links
        # even when no R2 object storage is configured (the public path). A
        # draft moves only the records that still name a local file: a record
        # on the copy a published version holds has a working URL, and moves
        # when the new version is published. A sandbox deposit is a dry run,
        # and its URLs must never reach a record.
        if sandbox:
            print("  The dataset records are left as they are: a sandbox deposit is a dry run.")
        else:
            patched = self._apply_zenodo_file_urls(record_url, plan, local_only=not publish)
            if patched:
                print(f"  Dataset records updated with Zenodo file URLs: {patched}")

        return ZenodoResult(
            record_id=str(zenodo_record_id),
            doi=doi,
            record_url=record_url,
            draft_url=draft_url,
            published=published,
            is_new_version=record_id is not None,
        )

    def validate_rocrate(self, path: str | Path | None = None) -> bool:
        """Validate a ``ro-crate-metadata.json`` using the official rocrate library.

        Parameters
        ----------
        path:
            Path to the RO-Crate directory or to ``ro-crate-metadata.json``
            directly.  Defaults to the workspace root.

        Returns
        -------
        bool
            ``True`` if valid.  Prints any issues found.

        Requires the ``rocrate`` library (``pip install battinfo[publish]``).

        Example::

            ws.preview_rocrate()
            ws.validate_rocrate()
        """
        from battinfo._util import require_extra

        try:
            ROCrate = require_extra("rocrate.rocrate", "publish", "validate_rocrate() checks RO-Crate metadata").ROCrate
        except ImportError as exc:
            print(f"  {exc}")
            print("  Alternatively validate at: https://www.researchobject.org/ro-crate/")
            return False

        p = Path(path) if path else self._root
        if p.is_file():
            p = p.parent  # accept the metadata file itself, use its directory

        metadata_path = p / "ro-crate-metadata.json"
        if not metadata_path.exists():
            metadata_path = p / "ro-crate-metadata.preview.json"
        if not metadata_path.exists():
            print(f"  No ro-crate-metadata.json found in {p}")
            print("  Run ws.preview_rocrate() first.")
            return False

        import shutil
        import tempfile

        # rocrate library requires the file to be named ro-crate-metadata.json
        tmpdir = Path(tempfile.mkdtemp())
        try:
            shutil.copy2(metadata_path, tmpdir / "ro-crate-metadata.json")
            crate = ROCrate(str(tmpdir))
            entities = list(crate.get_entities())
            print(f"  Valid RO-Crate 1.1  ({len(entities)} entities)")
            print(f"  Root: {crate.root_dataset.id}")
            return True
        except Exception as exc:
            print(f"  Validation failed: {exc}")
            return False
        finally:
            remove_temp_tree(tmpdir)

    def preview_rocrate(
        self,
        output: str | Path | None = None,
        title: str = "Battery dataset",
        description: str = "Battery dataset published via BattINFO.",
        creators: builtins.list[dict] | None = None,
        contributors: builtins.list[dict] | None = None,
        license: str = "cc-by-4.0",
    ) -> Path:
        """Generate ``ro-crate-metadata.json`` locally for review.

        Uses placeholder values for the Zenodo URL. The creators and their
        ORCIDs are the ones :meth:`zenodo` would give the deposit.

        Example::

            ws.save()
            ws.preview_rocrate()   # writes ro-crate-metadata.preview.json
        """
        import shutil
        import tempfile

        creators = self._deposit_creators(creators, required=False)
        contributors = _deposit_agents(contributors or [], "contributor")
        records_dir = self._ws.source_root
        if not records_dir.exists():
            raise RuntimeError("No records found — run ws.save() first.")

        plan = self._deposit_file_plan(records_dir)
        tmpdir = Path(tempfile.mkdtemp(prefix="battinfo-rocrate-"))
        try:
            data_files = [*self._bundle_data_files(tmpdir, plan), *plan.kept_files()]
            # Write a placeholder linked-data file so contentSize is available
            placeholder = tmpdir / BATTINFO_LD_FILENAME
            placeholder.write_text("{}", encoding="utf-8")
            self._build_rocrate(
                tmpdir,
                data_files,
                title=title,
                description=description,
                creators=creators,
                contributors=contributors,
                license=license,
                zenodo_record_id=0,
                prereserved_doi="10.5281/zenodo.RECORD_ID",
            )
            src = tmpdir / _ROCRATE_FILENAME
            out = Path(output) if output else self._root / "ro-crate-metadata.preview.json"
            shutil.copy2(src, out)
        finally:
            remove_temp_tree(tmpdir)

        print(f"  Written: {out}")
        return out

    def preview_jsonld(
        self,
        output: str | Path | None = None,
        *,
        title: str = "",
        description: str = "",
        creators: builtins.list[dict] | None = None,
        contributors: builtins.list[dict] | None = None,
        license: str = "",
        keywords: builtins.list[str] | None = None,
        version: str = "",
        is_version_of: str = "",
    ) -> Path:
        """Generate ``battinfo.json`` locally for review before uploading to Zenodo.

        Uses placeholder values for the Zenodo record URL and DOI so the
        structure can be inspected without creating a deposit.  Pass the same
        ``title``/``creators``/``license`` you would give :meth:`zenodo` to preview
        the rights and attribution that will be embedded in the published record.
        Without a ``title`` the preview carries the automatic title
        :meth:`zenodo` would give the deposit, and without ``creators`` the
        creators it would find (see :meth:`zenodo`); with none, the checks
        report it, since :meth:`zenodo` refuses such a deposit. A record the
        deposit would leave out, because it cannot be converted or a
        distribution entry of it names no file, is listed as an error too,
        with the reason.

        Parameters
        ----------
        output:
            Path to write the file.  Defaults to ``battinfo.preview.jsonld``
            in the workspace root.

        Returns
        -------
        Path
            Path of the written file.

        Example::

            ws.save()
            ws.preview_jsonld()   # writes battinfo.preview.jsonld
        """
        records_dir = self._ws.source_root
        if not records_dir.exists():
            raise RuntimeError("No records found — run ws.save() first.")

        # Fall back to the workspace default license (ws.license) when none is
        # passed, so the preview reflects what publishing would embed. Left empty
        # when neither is set, which the gold-standard panel then nudges on.
        if not license:
            license = self._get_license() or ""
        # The creators ws.zenodo() would find, every ORCID a bare id.
        creators = self._deposit_creators(creators, required=False)
        contributors = _deposit_agents(contributors or [], "contributor")

        # The data files and their deposit names, planned as ws.zenodo() plans
        # them. The graph needs only the names, so the files are not read.
        plan = self._deposit_file_plan(records_dir, measure=False)

        # What the plan and the graph leave out is listed below as errors, since
        # ws.zenodo() refuses a deposit over any of it.
        omissions = list(plan.omissions)
        jsonld = self._build_zenodo_jsonld(
            zenodo_record_id=0,
            prereserved_doi="10.5281/zenodo.RECORD_ID",
            record_url="https://zenodo.org/records/RECORD_ID",
            file_plan=plan,
            title=self._deposit_title(title),
            description=description or "",
            creators=creators,
            contributors=contributors,
            license=license or "",
            keywords=keywords or [],
            version=version or "",
            is_version_of=is_version_of or "",
            omissions=omissions,
        )

        out = Path(output) if output else self._root / "battinfo.preview.jsonld"

        # Gold-standard review runs BEFORE the file is written, so a metadata-poor or
        # non-conformant record is surfaced up front rather than after an authoritative-looking
        # file has already been produced (D-4). Uses the FULL publication validator (JSON-LD +
        # structural + SHACL), not just the syntactic JSON-LD check.
        # The record check ws.zenodo() runs on the parameter sets before it deposits
        # counts here too.
        try:
            from battinfo.validate import validate_publication_report  # noqa: PLC0415

            report = validate_publication_report(jsonld, policy="publisher")
            deposit_records, replaced_legacy = _read_deposit_record_sets(records_dir)
            _print_replaced_legacy_parameter_sets(replaced_legacy)
            errors = [f"left out of the deposit: {omission}" for omission in dict.fromkeys(omissions)]
            errors += [i.message for i in report.issues if i.severity == "error"] + [
                f"parameter set {problem}" for problem in _parameter_set_publication_errors(deposit_records)
            ]
            if not creators:
                errors.append(f"no creators: ws.zenodo() refuses a deposit without them. {_CREATORS_HINT}")
            warnings = [i for i in report.issues if i.severity == "warning"]
            if not errors and not warnings:
                print("  Gold-standard: PASS (no validation issues)")
            else:
                print(
                    f"  Gold-standard: {len(errors)} error(s), {len(warnings)} warning(s) -- address before publishing:"
                )
                for message in errors:
                    print(f"    ERROR   {message}")
                for i in warnings:
                    print(f"    warning {i.message}")
            # A record left out above has no node because it could not be
            # converted, not because it is missing locally.
            left_out = {omission.record for omission in omissions}
            unresolved = [iri for iri in _unresolved_record_references(jsonld) if iri not in left_out]
            if unresolved:
                print(f"  {_not_found_locally_note(unresolved)}")
        except Exception as exc:  # noqa: BLE001 — preview must still write + return its path
            print(f"  Gold-standard validation could not run: {exc}")

        out.write_text(json.dumps(jsonld, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  Written: {out}")
        print(f"  Graph nodes: {len(jsonld.get('@graph', []))}")
        print(f"  Data files:  {len(plan.deposited_names())}")
        return out

    def _assert_publishable(
        self,
        jsonld: dict,
        *,
        omissions: Iterable[Omission] = (),
        nothing_sent: bool = False,
        draft: bool = False,
    ) -> None:
        """Fail closed before minting an irreversible DOI: refuse to publish a record that has
        validation errors, or a distribution whose data file is missing from the deposit (R-7).

        *omissions* are what the deposit file plan and the deposit graph left out
        (``plan.omissions``, and the list :meth:`_build_zenodo_jsonld` fills):
        any at all refuses, naming each record and why, before the rest is
        checked. Missing data files are checked from the most recent deposit file
        plan (:meth:`_deposit_file_plan`). ``nothing_sent`` says in the refusal that no
        deposit was made (the check :meth:`zenodo` runs before it contacts Zenodo).
        With ``draft`` the refusal is of the deposit itself: :meth:`zenodo` checks a
        draft as it checks a publish, since a draft is one click from published."""
        verb, doing = ("deposit", "depositing") if draft else ("publish", "publishing")
        sent_note = " Nothing was sent to Zenodo." if nothing_sent else ""
        left_out = list(dict.fromkeys(omissions))
        if left_out:
            records = len({(omission.kind, omission.record) for omission in left_out})
            raise RuntimeError(
                f"Refusing to {verb}: {records} record(s) would go into the deposit incomplete: "
                f"{_omission_list(left_out)}. Fix or remove these records, then re-run.{sent_note}"
            )
        missing = getattr(self, "_missing_data_files", [])
        if missing:
            raise RuntimeError(
                f"Refusing to {verb}: {len(missing)} distribution data file(s) are missing and were "
                f"not uploaded, so the deposit would be incomplete: {'; '.join(missing[:5])}. "
                f"Fix the paths (or remove the distributions), then re-run.{sent_note}"
            )
        try:
            from battinfo.validate import validate_publication_report  # noqa: PLC0415

            report = validate_publication_report(jsonld, policy="publisher")
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Could not validate the record before {doing}: {exc}") from exc
        errors = [i for i in report.issues if i.severity == "error"]
        if errors:
            unresolved = _unresolved_record_references(jsonld)
            # Only a draft that already exists can be left as one: the check
            # before anything is sent refuses a draft for the same errors.
            draft_hint = "" if draft or nothing_sent else ", or leave the deposit as a draft"
            raise RuntimeError(
                f"Refusing to {verb}: {len(errors)} validation error(s) in the record "
                f"(run ws.preview_jsonld() to see them{draft_hint}): "
                + "; ".join(i.message for i in errors[:5])
                + (f" {_not_found_locally_note(unresolved)}" if unresolved else "")
                + sent_note
            )

    def _bundle_data_files(self, tmpdir: Path, plan: DepositFilePlan) -> builtins.list[DepositFile]:
        """The data files to upload, each under its deposit name in *plan*.

        A file is uploaded from where it is. When the deposit is zipped (more
        than ``_ZENODO_ZIP_THRESHOLD`` files), the files of each test kind are
        packed into one archive in *tmpdir*, each under its deposit name, so no
        two members share a name, and the archives are uploaded instead. A
        file the deposit keeps (``plan.kept_files()``) has nothing to upload.
        """
        import zipfile

        if not plan.zipped:
            return plan.local_files()
        archives: list[DepositFile] = []
        for archive, members in plan.archives().items():
            target = tmpdir / archive
            with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
                for entry in sorted(members, key=lambda member: member.name):
                    zf.write(entry.path, entry.name)
            archives.append(measured_file(target, archive, kind=members[0].kind))
            print(f"  Bundled {len(members)} files -> {archive}")
        return archives

    def _recorded_deposit_names(self, context: DepositContext) -> dict[str, str]:
        """The deposit names earlier versions of the Zenodo record *context* continues gave its files.

        Keyed by the file's resolved local path (``_deposit_files.path_key``),
        read from ``.battinfo/deposit-files.json``. The deposit file plan gives
        each such file its recorded name before it names any other file, so a
        file keeps its public URL from one version to the next even when a new
        file with the same name comes first.
        """
        return context.recorded_names()

    def _deposit_context(
        self,
        *,
        sandbox: bool | None = None,
        record_id: str | None = None,
        state: Mapping[str, Any] | None = None,
        index: Mapping[str, Any] | None = None,
    ) -> DepositContext:
        """What a deposit of this workspace knows about its Zenodo record before it asks Zenodo.

        Read from the state file of the environment (*state*) and
        ``.battinfo/deposit-files.json`` (*index*) unless given. *sandbox*
        ``None`` is zenodo.org, as for the previews. The deposit continues the
        record the state names, unless *record_id* names a record outside it;
        it then continues that one. The records it knows of are the state's
        record, deposit and the published record a draft of a new version was
        made from, and the versions the index lists for its concept. It starts
        from *record_id* when given, else from the state's record. The R2
        public base URL, when one is configured, tells a copy :meth:`upload`
        made from any other URL.
        """
        environment = zenodo_environment(bool(sandbox))
        state = self._load_zenodo_state(environment) if state is None else state
        index = load_deposit_index(self._root) if index is None else index
        public_base = (self._credential("R2_PUBLIC_BASE_URL") or "").strip().rstrip("/")
        concept: str | None = None
        records: set[str] = set()
        starts_from = record_id
        if state and state.get("environment") == environment:
            stored = str(state["record_id"])
            stored_concept = state.get("concept_record_id") or concept_of_record(index, environment, stored)
            stored_records = {stored, *concept_records(index, environment, stored_concept)}
            for key in ("deposit_id", "version_of"):
                if state.get(key):
                    stored_records.add(str(state[key]))
            if record_id is None or record_id in stored_records:
                concept, records = stored_concept, stored_records
            if record_id is None:
                starts_from = stored
        if record_id is not None and record_id not in records:
            concept = concept_of_record(index, environment, record_id)
            records = {record_id, *concept_records(index, environment, concept)}
        return DepositContext(
            environment=environment,
            concept=concept,
            records=frozenset(records),
            index=index,
            hosted_bases=(public_base,) if public_base else (),
            starts_from=starts_from,
        )

    def _registered_sources(self) -> frozenset[str]:
        """The keys of the local data files this workspace registered (``.battinfo/deposit-files.json``).

        A deposit reads a file on another computer only when it lies in the
        workspace folder or is registered here (see
        :func:`battinfo._deposit_files.location_path`). Raises
        :class:`~battinfo._deposit_index.DepositIndexError` when the file
        cannot be read.
        """
        return registered_keys(load_deposit_index(self._root))

    def _register_sources(self, paths: Iterable[Path | None], *, by: str) -> None:
        """Register each of *paths* (``None`` entries skipped) as a data file of this workspace."""
        register_sources(self._root, [path for path in paths if path is not None], by=by)

    def _deposit_file_plan(
        self,
        records_dir: Path,
        *,
        report: bool = True,
        measure: bool = True,
        context: DepositContext | None = None,
    ) -> DepositFilePlan:
        """The files a Zenodo deposit of this workspace carries, planned before anything is sent.

        Collects every ``file:`` distribution of the dataset records and the
        artifacts placed in the workspace, then plans them (see
        :func:`battinfo._deposit_files.build_deposit_file_plan`): one entry per
        resolved local file, each with its deposit name, percent-encoded URL
        segment, size, md5 and sha256. Staging, the deposit graph, the RO-Crate
        and the record rewrite read their names from the result.

        A distribution whose URL is a copy an earlier deposit or
        :meth:`upload` made is a file of the deposit too, found through
        *context* (by default the one :meth:`_deposit_context` reads): its
        local file is planned when it is there; when it is gone, a deposit
        that continues the record holding the copy keeps that copy, and any
        other lists the file as missing. A ``file:`` location whose file is
        gone is kept the same way when the record the deposit continues holds
        the copy the index noted for that file: a sandbox deposit leaves the
        records on their local files. The URL of a copy :meth:`upload`
        made goes into ``plan.hosted``, which :meth:`zenodo` refuses unless it
        is asked to archive such files. A copy of the workspace's own data
        whose local file the index does not know is an omission instead of a
        link (see ``DepositContext.refusal_for``): an R2 copy an earlier build
        made, an ``s3:`` URL, or a URL in a sandbox record from a deposit on
        zenodo.org. Any other Zenodo file URL on the deposit's Zenodo that
        the workspace cannot place goes into ``plan.unplaced`` for
        :meth:`zenodo` to ask Zenodo about.

        Each location is screened from its text before anything asks the file
        system about it. A network path outside the workspace folder that this
        workspace did not register (``ws.add(..., data=...)`` and
        :meth:`convert` register their files, :meth:`process` its previews),
        and a path that goes up a folder with ``..``, are never read: each is
        an omission that names its dataset.

        With *report* the missing data files and the artifact warnings are printed
        and kept for zenodo() and publish to act on; without it the files are only
        planned (the up-front count in publish()). Without *measure* the files are
        not read.

        Nothing is skipped in silence. A record file that cannot be read, and a
        distribution entry that is not an object with a ``content_url``, become
        omissions (``plan.omissions``, printed with *report*): :meth:`zenodo`
        refuses the deposit over them, and :meth:`preview_jsonld` lists them as
        errors. A record whose body is not an object is left to the deposit
        graph, which names it the same way.
        """
        omissions: list[Omission] = []

        def _saved(folder: str) -> list[tuple[Path, dict]]:
            """The records saved under *folder*, with their files, in file order."""
            saved: list[tuple[Path, dict]] = []
            sub_dir = records_dir / folder
            for path in sorted(sub_dir.glob("*.json")) if sub_dir.is_dir() else []:
                try:
                    record = _read_json(path)
                except (OSError, ValueError) as exc:
                    omissions.append(Omission(folder, path.name, f"its file cannot be read ({exc})"))
                    continue
                if isinstance(record, dict):
                    saved.append((path, record))
            return saved

        # Map dataset IRI → test kind via test records (test.dataset_ids), with the
        # dataset's own about naming its test as the fallback, the same links the
        # deposit graph uses to pick each file's <kind>.zip.
        tests = _saved("test")
        ds_to_kind: dict[str, str] = {}
        test_kind: dict[str, str] = {}
        for _path, raw in tests:
            test = raw.get("test")
            if not isinstance(test, dict):
                continue
            kind = str(test.get("kind") or "other")
            if isinstance(test.get("id"), str) and test["id"]:
                test_kind[test["id"]] = kind
            dataset_ids = test.get("dataset_ids")
            for ds_id in dataset_ids if isinstance(dataset_ids, list) else []:
                if isinstance(ds_id, str):
                    ds_to_kind[ds_id] = kind

        # The local data file locations, as the records give them, in record order.
        # Nothing here touches a data file: the plan screens each location from
        # its text before it asks the file system about it, and refuses a network
        # path outside the workspace that ws.add() did not register, and a path
        # that goes up a folder. A distribution entry that names no file is an
        # omission; the dataset's other files are still planned. A URL that is a
        # copy one of this workspace's deposits or uploads made is a file of the
        # deposit too, found through the index.
        context = context or self._deposit_context()
        locations: list[tuple[str, str]] = []  # (content_url, kind)
        owners: dict[str, str] = {}  # content_url -> the dataset that names it first
        remote: list[tuple[RemoteSource, str]] = []
        unplaced: dict[str, list[tuple[str, str]]] = {}  # record id -> (dataset, URL)
        for record_path, raw in _saved("dataset"):
            ds = raw.get("dataset")
            if not isinstance(ds, dict):
                continue
            ds_id = ds["id"] if isinstance(ds.get("id"), str) and ds["id"] else ""
            short_id = ds["short_id"] if isinstance(ds.get("short_id"), str) else ""
            about = ds.get("about")
            kind = ds_to_kind.get(ds_id) or next(
                (
                    test_kind[a]
                    for a in (about if isinstance(about, list) else [])
                    if isinstance(a, str) and a in test_kind
                ),
                "other",
            )
            usable, problems = dataset_distributions(ds)
            omissions.extend(Omission("dataset", ds_id or record_path.name, problem) for problem in problems)
            for dist in usable:
                url = dist["content_url"]
                if url.startswith("file://"):
                    locations.append((url, kind))
                    owners.setdefault(url, ds_id or record_path.name)
                    continue
                source = context.source_for(url)
                if source is not None:
                    remote.append((source, kind))
                    continue
                refusal = context.refusal_for(url, short_id=short_id)
                if refusal:
                    omissions.append(Omission("dataset", ds_id or record_path.name, refusal))
                    continue
                record = context.unplaced_record(url)
                if record is not None:
                    unplaced.setdefault(record, []).append((ds_id or record_path.name, url))

        # ── Actionable artifacts (Layer B) ─────────────────────────────────────
        # Only files the user has explicitly placed in the workspace are published;
        # artifacts that live elsewhere are flagged (warn, never block) and left out
        # rather than auto-copied, so publication contains exactly what was opted in.
        from battinfo.publication import plan_artifact_inclusion  # noqa: PLC0415

        artifact_records = [raw for _path, raw in _saved("test-protocol")] + [raw for _path, raw in tests]
        artifact_files, artifact_warnings = plan_artifact_inclusion(artifact_records, self._root)

        plan = build_deposit_file_plan(
            locations,
            root=self._root,
            artifacts=artifact_files,
            artifact_warnings=artifact_warnings,
            omissions=omissions,
            recorded_names=self._recorded_deposit_names(context),
            # A data file never takes the name of the deposit's own metadata files.
            reserved_names=(BATTINFO_LD_FILENAME, _ROCRATE_FILENAME),
            zip_threshold=_ZENODO_ZIP_THRESHOLD,
            measure=measure,
            registered=registered_keys(context.index),
            owners=owners,
            remote=remote,
            unplaced=unplaced,
            held=context.held_files(),
        )
        if report:
            # Do NOT silently drop a distribution whose data file is missing: the
            # deposit would be published incomplete (a distribution pointing at a
            # file that was never uploaded). Warn now; block publish later (R-7).
            for path in plan.missing:
                print(f"  WARNING: data file for a distribution is missing (not uploaded): {path}")
            for omission in plan.omissions:
                print(f"  WARNING: left out of the deposit: {omission}")
            # Surfaced to zenodo()/publish so publishing can fail closed on an incomplete deposit.
            self._missing_data_files = list(plan.missing)
            self._artifact_warnings = list(plan.artifact_warnings)
            for warning in plan.artifact_warnings:
                print(f"  WARNING: {warning}")
        return plan

    def _refuse_a_zipped_deposit(self, plan: DepositFilePlan | None = None) -> None:
        """Refuse publish(zenodo=True) before any deposit exists when its files would be zipped.

        A deposit of more than ``_ZENODO_ZIP_THRESHOLD`` data files is zipped by
        test kind, and the registry cannot yet point a record at a file inside an
        archive: the records would keep their local file paths, and the registry
        half would refuse them only after the DOI was minted. *plan* is the
        deposit's file plan, made here when not given.
        """
        if plan is None:
            plan = self._deposit_file_plan(self._ws.source_root, report=False, measure=False)
        count = len(plan.local_files())
        if plan.zipped:
            raise ValueError(
                f"Refusing to publish: this workspace has {count} data files, and a Zenodo deposit "
                f"of more than {_ZENODO_ZIP_THRESHOLD} is zipped by test kind. The registry cannot yet "
                "point a record at a file inside an archive, so it would refuse the records after "
                "the DOI was minted. Nothing was deposited or sent. Publish to Zenodo alone with "
                "ws.zenodo(publish=True), or split the workspace into parts of at most "
                f"{_ZENODO_ZIP_THRESHOLD} data files."
            )

    def _refuse_hosted_files(self, plan: DepositFilePlan, *, verb: str, from_publish: bool = False) -> None:
        """Refuse a deposit that would archive data files hosted in R2 storage, and name the files.

        The files are the copies :meth:`upload` made that the dataset records
        point at (``plan.hosted``). From :meth:`publish` with R2 storage
        configured, they are also the local data files :meth:`upload` is about
        to put there, since :meth:`publish` runs it before the deposit. A
        deposit archives such files only when it is called with
        ``archive_hosted_files=True``. *verb* names what is refused
        (``publish`` or ``deposit``).
        """
        hosted = sorted(plan.hosted)
        uploading = from_publish and self._r2_configured()
        local = [self._rel_to_root(str(entry.path)) for entry in plan.located_files()] if uploading else []
        if not hosted and not local:
            return
        sentences = [f"Refusing to {verb}: the deposit would archive data files hosted in R2 storage."]
        if local:
            sentences.append(
                "R2 storage is configured, so ws.publish(zenodo=True) puts these in R2 with ws.upload() "
                f"before the deposit: {_shown_list(local)}."
            )
        if hosted:
            sentences.append(f"The dataset records point at these copies ws.upload() made: {_shown_list(hosted)}.")
        sentences.append(
            "A Zenodo deposit makes a public copy of each file it holds, so it archives files hosted in "
            "R2 only when asked: pass archive_hosted_files=True to archive them from their local files, "
            "with the records still pointing at R2."
        )
        if local and not hosted:
            sentences.append("To let Zenodo host the files instead, run ws.zenodo(publish=True), then ws.submit().")
        sentences.append("Nothing was uploaded, deposited or sent." if from_publish else "Nothing was sent to Zenodo.")
        raise ValueError(" ".join(sentences))

    def _warn_private_hosted_files(self, plan: DepositFilePlan) -> None:
        """Name in a warning each data file the deposit archives from the private R2 bucket, since it makes them public."""
        private = sorted(plan.private_hosted)
        if not private:
            return
        warnings.warn(
            f"The deposit archives {len(private)} data file(s) that ws.upload(public=False) put in the "
            "private R2 bucket, and it makes them public: " + "; ".join(private),
            stacklevel=3,
        )
        print(f"  WARNING: the deposit makes {len(private)} data file(s) from the private R2 bucket public:")
        for url in private:
            print(f"    {url}")

    @staticmethod
    def _assemble_zenodo_jsonld(
        record_sets: dict[str, builtins.list[dict]],
        *,
        zenodo_record_id: int,
        prereserved_doi: str,
        record_url: str,
        data_filenames: builtins.list[str] | None = None,
        title: str = "",
        description: str = "",
        creators: builtins.list[dict] | None = None,
        contributors: builtins.list[dict] | None = None,
        license: str = "",
        files_base_url: str | None = None,
        keywords: builtins.list[str] | None = None,
        version: str = "",
        is_version_of: str = "",
        referenced_records: dict[str, builtins.list[dict]] | None = None,
        file_plan: DepositFilePlan | None = None,
        omissions: builtins.list[Omission] | None = None,
    ) -> dict:
        """Assemble the consolidated battinfo JSON-LD from canonical record dicts.

        This is the single, input-agnostic graph builder shared by every publication
        path: it takes ``record_sets`` (keys ``cell-spec``, ``cell-instance``,
        ``test``, ``test-protocol``, ``dataset`` → lists of record dicts in the
        canonical on-disk shape) rather than reading a workspace, so both the
        interactive authoring flow (:meth:`_build_zenodo_jsonld`) and the
        programmatic contribution flow (``publication.build_zenodo_package``) emit
        byte-identical graphs.

        A record the builder cannot convert (one that is not an object, has no
        id, or raises while its node is built) and a distribution entry that is
        not an object with a ``content_url`` are left out of the graph with a
        warning that names them and why. Given an ``omissions`` list, the
        builder appends each to it and returns the graph, for the caller to
        refuse (:meth:`zenodo`) or report (:meth:`preview_jsonld`). Without
        one it raises a ``ValueError`` naming them all, so no caller publishes
        a graph with records missing. A time it cannot read as a date is left
        out with a warning, not the record that holds it (see ``_unix_to_iso``).

        A local file's download URL is ``{files_base_url}/{name}`` with the name
        percent-encoded. With ``file_plan`` (a workspace deposit) a distribution
        or artifact finds its file in the plan by resolved path, and takes the
        file's deposit name and, in a zipped deposit, its archive. A
        distribution of a file the plan measured states the plan's sha256 and
        size, not the ones its record gives, which date from when the file was
        added.
        ``data_filenames`` serves the package builders, whose staged files have
        unique names: a local file whose name is among them is deposited under
        that name, and otherwise its ``<kind>.zip`` when that is among them.

        ``referenced_records`` holds copies of published records the deposit
        points at but does not carry, in the same shape (a workspace keeps
        them under ``.battinfo/references/``). A cell or test spec among them
        that a test or dataset points at gets a "defined elsewhere" stub,
        typed and named from its copy; nothing else is taken from it.

        Cell specs use domain-battery OWL classes (``CylindricalBattery`` etc.)
        and EMMO's ``hasProperty`` / ``hasNumericalPart`` / ``hasMeasurementUnit``
        pattern for measurements.  DCAT and schema.org wrap the dataset level for
        broad discoverability.  The document is processable by OWL reasoners and
        any JSON-LD tool that resolves the embedded context.
        """
        from battinfo.jsonld import (
            checksum_node,
            dataset_series_edges,
            dataset_to_jsonld,
            electrode_role_links,
            funding_to_jsonld,
            schema_checksum_terms,
            test_protocol_node,
        )

        # Workspace funding project (grant) → schema:funding/Grant. The grant is
        # workspace-uniform, so the first record carrying it defines the deposit's
        # funding; attached to the catalog and (like license/creators) to each
        # member, since RDF has no part-of inheritance.
        _funding_grant: dict | None = None
        for _recs in record_sets.values():
            for _rec in _recs:
                if isinstance(_rec, dict):
                    _funding_grant = funding_to_jsonld(_rec.get("funding"))
                    if _funding_grant is not None:
                        break
            if _funding_grant is not None:
                break

        # Workspace contributors stamped onto the records (ws.contributor) are
        # carried into the publication graph so the archived record credits authors
        # without requiring creators= to be re-passed at deposit time. Merged with
        # any explicit contributors= (which win), deduped by ORCID then by name,
        # preserving order.
        contributors = list(contributors or [])
        _contrib_present = {(c.get("orcid") or c.get("name")) for c in contributors if isinstance(c, dict)}
        for _recs in record_sets.values():
            for _rec in _recs:
                if not isinstance(_rec, dict):
                    continue
                for _c in _rec.get("contributor") or []:
                    if not isinstance(_c, dict):
                        continue
                    _agent = _agent_from_record_contributor(_c)
                    _key = _agent.get("orcid") or _agent.get("name")
                    if not _key or _key in _contrib_present:
                        continue
                    _contrib_present.add(_key)
                    contributors.append(_agent)

        # Shared canonical builders (also used by the resolver artifact path, so
        # both emitters produce byte-identical cell-spec nodes) plus the
        # prefLabel → compact-IRI table used for inline context terms.
        from battinfo.transform.cell_spec_node import (  # noqa: PLC0415
            build_cell_spec_node,
            label_to_compact,
        )

        named_files = list(data_filenames or [])
        files_base = files_base_url or f"{record_url}/files"

        def _artifact_download_url(loc: str) -> Any:
            """Resolve an artifact locator to its download URL. An http(s) locator is
            already hosted; a workspace file that is being uploaded resolves to its
            hosted URL (like data files, the archive holding it in a zipped deposit);
            an un-uploaded local locator is kept as the relative literal (no hosted
            copy exists)."""
            text = str(loc)
            if text.startswith(("http://", "https://")):
                return {"@id": text}
            if file_plan is not None:
                entry = file_plan.entry_for(text)
                return {"@id": entry.url(files_base)} if entry is not None else text
            fname = path_name(_file_uri_to_path(text))
            if fname in named_files:
                return {"@id": f"{files_base}/{url_segment(fname)}"}
            return text

        def _artifact_distribution(art: dict) -> dict:
            """An actionable artifact link → a dcat:Distribution node, resolving the
            locator against the files being uploaded with this deposit."""
            from battinfo.jsonld import artifact_distribution_node  # noqa: PLC0415

            return artifact_distribution_node(art, locator_url=_artifact_download_url)

        # ── Records left out, never in silence ─────────────────────────────────
        # A record that cannot be converted is named, with the reason, in a
        # warning and in the omissions the caller gets back, or in the
        # ValueError raised once the graph is built when the caller asked for
        # none: a deposit with records missing must not be published.
        _omitted: builtins.list[Omission] = []

        def _omit(kind: str, record: str, reason: object, *, whole: bool = True) -> None:
            """Leave *record* (or, without *whole*, a part of it) out of the graph, and say so."""
            if isinstance(reason, BaseException):
                reason = f"{type(reason).__name__}: {reason}"
            omission = Omission(kind, record, str(reason))
            if omission in _omitted:
                return
            _omitted.append(omission)
            what = (
                f"The {kind} record {record} could not be converted to JSON-LD and is left out"
                if whole
                else f"Part of the {kind} record {record} is left out"
            )
            warnings.warn(f"{what} of the deposit graph: {omission.reason}", stacklevel=3)

        def _record_body(raw: object, key: str, kind: str, index: int) -> tuple[dict, str] | None:
            """A record's body (``raw[key]``) and IRI, or ``None``, and an omission, without them.

            A record without an IRI is named by its place among the records of
            its kind (``#2``).
            """
            body = raw.get(key) if isinstance(raw, dict) else None
            if not isinstance(body, dict):
                _omit(kind, f"#{index + 1}", f"not a {kind} record (no '{key}' object)")
                return None
            iri = body.get("id")
            if not isinstance(iri, str) or not iri:
                _omit(kind, f"#{index + 1}", "it has no id")
                return None
            return body, iri

        # ── Load cell specs ────────────────────────────────────────────────────
        # One canonical builder (shared with the resolver path): the physical
        # @type stack via isDescriptionFor expresses chemistry/format (no
        # battinfo: literals), quantities use the shared EMMO quantity-node
        # shape, and provenance rides along as a standard-vocabulary node.
        spec_nodes: dict[str, dict] = {}
        # chemistry/format keyword strings, collected from the records (the node
        # no longer carries the verbatim literals).
        _spec_keywords: set[str] = set()
        for _index, raw in enumerate(record_sets.get("cell-spec", []) or []):
            _found = _record_body(raw, "cell_spec", "cell-spec", _index)
            if _found is None:
                continue
            prod, iri = _found
            try:
                spec_nodes[iri] = build_cell_spec_node(raw)
            except Exception as exc:  # noqa: BLE001 - collected; the deposit is refused, not sunk
                _omit("cell-spec", iri, exc)
                continue
            for _field in ("chemistry", "cell_format"):
                if prod.get(_field):
                    _spec_keywords.add(str(prod[_field]))

        # ── Map cell instance IRI → {cell_spec_id, serial_number} ──────────────────
        instances: dict[str, dict] = {}
        for _index, raw in enumerate(record_sets.get("cell-instance", []) or []):
            _found = _record_body(raw, "cell_instance", "cell-instance", _index)
            if _found is None:
                continue
            ci, iri = _found
            instances[iri] = {
                "name": ci.get("name", ""),
                "serial_number": ci.get("serial_number", ""),
                "cell_spec_id": ci.get("cell_spec_id", ""),
                "grade": ci.get("grade"),
                "manufactured_at": ci.get("manufactured_at"),
                "expires_at": ci.get("expires_at"),
                "batch_id": ci.get("batch_id"),
                "conformance": ci.get("conformance"),
                # The electrode records built into this cell, kept
                # whole so the node builder can role-type them.
                "cell_instance": ci,
            }

        # Published records this deposit may point at without carrying them:
        # the copies a workspace keeps of a cell or test spec it referenced in
        # the registry. A cell's name labels its tests and datasets whether the
        # cell is carried here or only referenced.
        _referenced = _reference_stub_sources(referenced_records)

        def _cell_name(iri: str) -> str:
            if iri in instances:
                return instances[iri].get("name") or ""
            folder, _stub_type, name = _referenced.get(iri, ("", None, ""))
            return name if folder == "cell-instance" else ""

        # ── Map cell-spec IRI → the spec BODY ──────────────────────────────────
        # Not the built node: the half-cell rule reads cell_configuration, which
        # is a record field, and the emitted node states the configuration only
        # as a @type. Same lookup the physical-type inheritance below uses, so an
        # instance reads one spec, once.
        cell_spec_bodies: dict[str, dict] = {}
        for raw in record_sets.get("cell-spec", []) or []:
            body = raw.get("cell_spec") if isinstance(raw, dict) else None
            if isinstance(body, dict) and body.get("id"):
                cell_spec_bodies[body["id"]] = body

        # ── Equipment / channel lookups (test provenance) ──────────────────────
        # Registered lab equipment records let a test's equipment_id/channel_id
        # resolve to a REAL equipment node (name, serial number, spec link)
        # instead of degrading to a nameless instrument string.
        equipment_by_id: dict[str, dict] = {}
        for raw in record_sets.get("equipment", []) or []:
            body = raw.get("equipment", {}) if isinstance(raw, dict) else {}
            if isinstance(body, dict) and body.get("id"):
                equipment_by_id[body["id"]] = body
        equipment_spec_by_id: dict[str, dict] = {}
        for raw in record_sets.get("equipment-spec", []) or []:
            body = raw.get("equipment_spec", {}) if isinstance(raw, dict) else {}
            if isinstance(body, dict) and body.get("id"):
                equipment_spec_by_id[body["id"]] = body
        channel_by_id: dict[str, dict] = {}
        for raw in record_sets.get("channel", []) or []:
            body = raw.get("channel", {}) if isinstance(raw, dict) else {}
            if isinstance(body, dict) and body.get("id"):
                channel_by_id[body["id"]] = body

        # Equipment/channel nodes referenced by at least one test, emitted as
        # graph-level nodes (an equipment unit is shared across tests).
        equipment_nodes: dict[str, dict] = {}
        channel_nodes: dict[str, dict] = {}

        def _equipment_graph_node(eq_id: str, instrument: str) -> dict:
            """Full equipment node for the publication graph: EMMO instrument
            class (from the equipment-spec's class/name/model, falling back to
            the test's instrument string), display name, serial number, and the
            spec link — mirroring the cell → cell-spec instance pattern."""
            from battinfo._emmo_instruments import _instrument_emmo_type  # noqa: PLC0415

            body = equipment_by_id.get(eq_id, {})
            spec = equipment_spec_by_id.get(body.get("equipment_spec_id", ""), {})
            class_seed = " ".join(
                str(v)
                for v in (
                    spec.get("equipment_class"),
                    spec.get("name"),
                    spec.get("model"),
                    instrument,
                )
                if v
            )
            enode: dict = {
                "@id": eq_id,
                "@type": [_instrument_emmo_type(class_seed), "prov:Entity"],
            }
            display = body.get("name") or spec.get("name") or instrument
            if display:
                enode["schema:name"] = display
                enode["rdfs:label"] = display
            if body.get("serial_number"):
                enode["schema:serialNumber"] = body["serial_number"]
            if body.get("location"):
                enode["schema:location"] = body["location"]
            if body.get("equipment_spec_id"):
                enode["hasDescription"] = {"@id": body["equipment_spec_id"]}
                enode["dcterms:conformsTo"] = {"@id": body["equipment_spec_id"]}
            return enode

        def _channel_graph_node(ch_id: str, eq_id: str) -> dict:
            body = channel_by_id.get(ch_id, {})
            cnode: dict = {"@id": ch_id, "@type": ["schema:Thing", "prov:Entity"]}
            label = body.get("label") or (f"CH{body['index']}" if isinstance(body.get("index"), int) else "")
            if label:
                cnode["schema:name"] = label
                cnode["rdfs:label"] = label
            if isinstance(body.get("index"), int):
                cnode["schema:position"] = body["index"]
            if eq_id:
                cnode["schema:isPartOf"] = {"@id": eq_id}
            return cnode

        # ── Dataset → subject links, read from the dataset's own ``about`` ────
        # A dataset record names what it is about (its cell instance and the
        # test that produced it) in ``about``. That list is the primary link;
        # a test's ``dataset_ids`` is the reverse view, which many corpora never
        # fill in. Each about entry is classified by the record set it belongs to
        # (falling back to the IRI path segment for records outside the deposit),
        # so a test can list its outputs even when only the dataset names it.
        _test_iris: set[str] = set()
        for raw in record_sets.get("test", []) or []:
            _tbody = raw.get("test") if isinstance(raw, dict) else None
            if isinstance(_tbody, dict) and _tbody.get("id"):
                _test_iris.add(_tbody["id"])
        _cell_iris: set[str] = set(instances)

        def _about_kind(iri: str) -> str:
            if iri in _test_iris:
                return "test"
            if iri in _cell_iris:
                return "cell"
            if "/test/" in iri:
                return "test"
            if "/cell/" in iri:
                return "cell"
            return ""

        ds_about: dict[str, builtins.list[str]] = {}
        test_to_ds_from_about: dict[str, builtins.list[str]] = {}
        for raw in record_sets.get("dataset", []) or []:
            _dbody = raw.get("dataset") if isinstance(raw, dict) else None
            if not isinstance(_dbody, dict) or not _dbody.get("id"):
                continue
            _about = [a for a in (_dbody.get("about") or []) if isinstance(a, str) and a]
            ds_about[_dbody["id"]] = list(dict.fromkeys(_about))
            for _a in ds_about[_dbody["id"]]:
                if _about_kind(_a) == "test":
                    test_to_ds_from_about.setdefault(_a, []).append(_dbody["id"])

        # ── Build test instance nodes + dataset→test mapping ──────────────────
        ds_to_test: dict[str, dict] = {}
        test_info: dict[str, dict] = {}  # test IRI → the same fields, for about-derived links
        test_nodes: list[dict] = []
        _test_recs = record_sets.get("test", [])
        if _test_recs:
            for _index, raw in enumerate(_test_recs):
                _found = _record_body(raw, "test", "test", _index)
                if _found is None:
                    continue
                test, test_iri = _found
                try:
                    cell_id = test.get("cell_id", "")
                    protocol = test.get("protocol_name", "")
                    instrument = test.get("instrument_name", "")

                    _tinfo = {
                        "kind": test.get("kind", ""),
                        "cell_id": cell_id,
                        "protocol": protocol,
                        "test_iri": test_iri,
                    }
                    test_info[test_iri] = _tinfo
                    for ds_id in test.get("dataset_ids") or []:
                        ds_to_test[ds_id] = dict(_tinfo)

                    if cell_id:
                        tnode: dict = {
                            "@type": ["BatteryTest", "schema:Action", "prov:Activity"],
                            "@id": test_iri,
                            "hasTestObject": {"@id": cell_id},  # domain-battery: physical object tested
                            # PROV mirror of hasTestObject so a PROV-only consumer
                            # reaches the cell; the spec is appended in _apply below.
                            "prov:used": [{"@id": cell_id}],
                        }
                        # Human label so agents/consumers see more than an opaque IRI.
                        _cell_nm = _cell_name(cell_id)
                        _label = (protocol or test.get("kind", "")).strip()
                        if _label and _cell_nm:
                            _label = f"{_label} — {_cell_nm}"
                        if _label:
                            tnode["schema:name"] = _label
                            tnode["rdfs:label"] = _label
                        if test.get("kind"):
                            tnode["schema:additionalType"] = test["kind"]
                        if protocol:
                            tnode["schema:measurementTechnique"] = protocol
                        # Equipment provenance (EMMO-canonical; schema.org has no apt
                        # predicate — schema:instrument is an Action property and this
                        # node is an Activity, so it is intentionally omitted).
                        # A registered equipment/channel reference wins over the free-
                        # text instrument string: the test links the REAL equipment
                        # node (emitted into the graph below) and the channel it ran
                        # on; the bare instrument string remains the fallback.
                        equipment_id = test.get("equipment_id", "")
                        channel_id = test.get("channel_id", "")
                        if channel_id and not equipment_id:
                            equipment_id = channel_by_id.get(channel_id, {}).get("equipment_id", "")
                        if equipment_id:
                            if equipment_id not in equipment_nodes:
                                equipment_nodes[equipment_id] = _equipment_graph_node(equipment_id, instrument)
                            equip_ref: dict = {"@id": equipment_id}
                            # Keep the display name inline so the round-trip importer
                            # (which reads hasTestEquipment/schema:name) still sees it.
                            equip_name = equipment_nodes[equipment_id].get("schema:name")
                            if equip_name:
                                equip_ref["schema:name"] = equip_name
                            tnode["hasTestEquipment"] = equip_ref
                        elif instrument:
                            tnode["hasTestEquipment"] = {
                                "@type": "schema:Thing",
                                "schema:name": instrument,
                            }
                        if channel_id:
                            if channel_id not in channel_nodes:
                                channel_nodes[channel_id] = _channel_graph_node(channel_id, equipment_id)
                            # The channel is the piece of equipment the activity used.
                            tnode["prov:used"].append({"@id": channel_id})
                        # hasOutput → the dataset IRIs produced by this test, mirrored
                        # as prov:generated so PROV alone reaches the output dataset.
                        # Union of the test's own dataset_ids and every dataset whose
                        # about names this test.
                        outputs = [
                            {"@id": ds_id}
                            for ds_id in dict.fromkeys(
                                [
                                    *(test.get("dataset_ids") or []),
                                    *test_to_ds_from_about.get(test_iri, []),
                                ]
                            )
                        ]
                        if outputs:
                            tnode["hasOutput"] = outputs
                            tnode["prov:generated"] = outputs
                        # Activity timing (measured period, sourced from the data) —
                        # PROV start/end plus schema.org mirror so the test is placed in
                        # time without parsing the time-series. A time that is no date
                        # (one in milliseconds) is left out with a warning, not the test.
                        _start = _unix_to_iso(test.get("started_at") or None, what=f"started_at of test {test_iri}")
                        _end = _unix_to_iso(test.get("ended_at") or None, what=f"ended_at of test {test_iri}")
                        if _start:
                            tnode["prov:startedAtTime"] = _start
                            tnode["schema:startTime"] = _start
                        if _end:
                            tnode["prov:endedAtTime"] = _end
                            tnode["schema:endTime"] = _end
                        # spec conformance ─────────────────────────────────────
                        protocol_id = test.get("protocol_id")
                        conformance = test.get("conformance")
                        _apply_conformance_jsonld(tnode, protocol_id, conformance)
                        # Actionable layer: link the executed/vendor protocol files.
                        if raw.get("artifacts"):
                            tnode["dcat:distribution"] = [
                                _artifact_distribution(a) for a in raw["artifacts"] if isinstance(a, dict)
                            ]
                        test_nodes.append(tnode)
                    else:
                        _omit("test", test_iri, "it names no cell (cell_id)")
                except Exception as exc:  # noqa: BLE001 - collected; the deposit is refused, not sunk
                    _omit("test", test_iri, exc)
                    continue

        # ── Build test spec (protocol) nodes ───────────────────────────────────
        # Each test activity's ``prov:used`` points at the spec it followed. Emit a
        # described node for that spec so the link resolves to a real node in the
        # graph instead of a dangling IRI — mirroring how cell specs and datasets
        # are inlined above. The node itself is built by the shared emitter in
        # battinfo.jsonld, so a protocol published in a deposit and one emitted
        # standalone by record_to_jsonld are the same graph.
        # The importer keys off ``BatteryTest``/``BatteryCellSpecification`` types
        # (see import_), so these nodes are ignored on round-trip — safe to add.
        test_spec_nodes: list[dict] = []
        for _index, raw in enumerate(record_sets.get("test-protocol", []) or []):
            _found = _record_body(raw, "test_spec", "test-protocol", _index)
            if _found is None:
                continue
            try:
                snode = test_protocol_node(raw, locator_url=_artifact_download_url)
            except Exception as exc:  # noqa: BLE001 - collected; the deposit is refused, not sunk
                _omit("test-protocol", _found[1], exc)
                continue
            if snode is not None:
                test_spec_nodes.append(snode)

        # ── Build dataset metadata ─────────────────────────────────────────────
        # A dataset may carry several distributions (files) — e.g. a normalised
        # "processed" file plus the original "raw" instrument file kept for
        # provenance. Collect every distribution, not just the last.
        ds_meta: dict[str, dict] = {}
        for _index, raw in enumerate(record_sets.get("dataset", []) or []):
            _found = _record_body(raw, "dataset", "dataset", _index)
            if _found is None:
                continue
            ds, ds_id = _found
            ti = dict(ds_to_test.get(ds_id, {}))
            own_about = ds_about.get(ds_id, [])
            # No test lists this dataset: take the test and cell from the
            # dataset's own about (first entry of each kind is the primary,
            # matching Dataset.to_record's ordering).
            if not ti.get("test_iri"):
                _t = next((a for a in own_about if _about_kind(a) == "test"), "")
                if _t:
                    ti = {**test_info.get(_t, {}), **{k: v for k, v in ti.items() if v}}
                    ti["test_iri"] = _t
            if not ti.get("cell_id"):
                ti["cell_id"] = next((a for a in own_about if _about_kind(a) == "cell"), "") or test_info.get(
                    ti.get("test_iri", ""), {}
                ).get("cell_id", "")
            # An entry that is not an object with a content_url names no file:
            # it is left out and reported, the dataset's other files kept.
            _usable, _problems = dataset_distributions(ds)
            for _problem in _problems:
                _omit("dataset", ds_id, _problem, whole=False)
            dists = []
            for dist in _usable:
                url = dist["content_url"]
                # A deposited file is named as the deposit names it.
                _entry = file_plan.entry_for(url) if file_plan is not None else None
                fname = _entry.name if _entry is not None else _distribution_file_name(url)
                # The whole checksum block, algorithm included. Carrying only
                # the value here is what let an md5 digest be published under
                # the sha256 term downstream.
                _checksum_block = dist.get("checksum") or {}
                _content_size = dist.get("content_size", "")
                if _entry is not None and _entry.sha256:
                    # The deposit holds the file as the plan measured it: a
                    # checksum or size the record took when the file was added
                    # is stale once the file changed.
                    _checksum_block = {"algorithm": "sha256", "value": _entry.sha256}
                    _content_size = str(_entry.size)
                dists.append(
                    {
                        "filename": fname,
                        "content_url": url,
                        "format": dist.get("encoding_format", ""),
                        "checksum": _checksum_block,
                        "role": dist.get("role", ""),
                        "description": dist.get("description", ""),
                        "content_size": _content_size,
                    }
                )
            ds_meta[ds_id] = {
                "name": ds.get("name", ""),
                "cell_id": ti.get("cell_id", ""),
                "test_iri": ti.get("test_iri", ""),
                "kind": ti.get("kind", ""),
                # schema:about: the record's own about first, then the cell
                # the reverse (test.dataset_ids) mapping found.
                "about": list(dict.fromkeys([*own_about, *([ti["cell_id"]] if ti.get("cell_id") else [])])),
                "is_series": is_dataset_series(ds.get("additional_type")),
                "dists": dists,
                "ds": ds,  # full dataset record for discoverability fields
            }

        # ── Build member dataset nodes (one dcat:Dataset per test result) ──────
        # The Zenodo record is a CATALOG; each test result is its own dcat:Dataset
        # grouping its distributions. A run's processed (.bdf.csv) and raw (.ndax)
        # files are two distributions (forms) of the SAME dataset — distributions of
        # one dataset are alternative representations, which is true within a run but
        # NOT across runs (those are distinct measurements on different cells).
        #
        # Provenance chain: Distribution ──wasGeneratedBy──> BatteryTest (processed)
        #                   BatteryTest  ──hasTestObject──>  Cell
        #                   BatteryTest  ──prov:used──>      TestSpec (plan)
        #                   Cell ──hasDescription──> CellSpec
        # A "raw"-role distribution is the test's INPUT (prov:used), not output, so
        # it is not tagged wasGeneratedBy; it carries a description for provenance.
        dataset_member_nodes: list[dict] = []
        # Aggregated across members for the top-level catalog node: every download (so a
        # Google-Dataset-Search consumer sees the files on the top Dataset, which it does
        # not reliably reach via schema:hasPart) and the overall measured time span.
        _all_downloads: list[dict] = []
        _cov_starts: list[str] = []
        _cov_ends: list[str] = []

        def _download_url(dist: dict, kind: str) -> str:
            cu = dist.get("content_url") or ""
            if file_plan is not None:
                # The deposit file that holds this file, found by resolved path:
                # the file itself, or its archive in a zipped deposit. A URL of
                # a copy an earlier deposit or an upload made counts too, so the
                # graph links to the copy this deposit holds.
                entry = file_plan.entry_for(cu)
                if entry is not None:
                    return entry.url(files_base)
            if cu.startswith(("http://", "https://")):
                return cu  # already a hosted file — use verbatim
            if file_plan is not None:
                return ""
            fname = dist["filename"]
            if fname in named_files:
                return f"{files_base}/{url_segment(fname)}"
            kind_zip = f"{kind}.zip"
            return f"{files_base}/{url_segment(kind_zip)}" if kind_zip in named_files else ""

        for ds_id, meta in sorted(ds_meta.items()):
            dists = []
            schema_dists = []  # schema.org mirror of dcat:distribution (generated)
            # The hosted URL of the raw (pre-conversion) file, so each processed file
            # can declare prov:wasDerivedFrom it (the conversion provenance chain).
            _raw_url = next((_download_url(d, meta["kind"]) for d in meta["dists"] if d.get("role") == "raw"), "")
            for dist in meta["dists"]:
                fname = dist["filename"]
                dl_url = _download_url(dist, meta["kind"])

                media_type = dist["format"] or "application/x-parquet"
                # DCAT-AP: dcat:mediaType should be the IANA media-type IRI, not a bare
                # string. schema:encodingFormat (below) keeps the MIME string for
                # schema.org consumers.
                _iana_media = f"{_IANA_MEDIA_TYPES}{media_type}" if "/" in media_type else None
                dnode: dict = {
                    "@type": "dcat:Distribution",
                    "dcat:downloadURL": dl_url,
                    "dcat:mediaType": {"@id": _iana_media} if _iana_media else media_type,
                    "schema:name": fname,
                }
                # Identify the distribution by its download URL so it is referenceable
                # (e.g. as the source of a derivation), not an anonymous blank node.
                if dl_url:
                    dnode["@id"] = dl_url
                is_raw = dist.get("role") == "raw"
                # A BDF data file (.bdf.csv / .bdf.parquet) conforms to the published
                # BDF table schema; link it so the column/unit semantics are one
                # dereference away. Raw instrument files (.ndax) are not BDF, so skip.
                is_bdf = ".bdf." in fname and not is_raw
                if is_bdf:
                    dnode["dcterms:conformsTo"] = {"@id": BDF_TABLE_SCHEMA_IRI}
                # Conversion provenance: the processed file was derived from the raw
                # instrument file (BDF CSV ← .ndax), so a consumer can trace the chain.
                if not is_raw and _raw_url and _raw_url != dl_url:
                    dnode["prov:wasDerivedFrom"] = {"@id": _raw_url}
                if dist.get("description"):
                    dnode["schema:description"] = dist["description"]
                # wasGeneratedBy → BatteryTest (the Activity), not the cell (Entity).
                # A raw source file is the test's INPUT, not its output, so it is not
                # tagged as generated by the test; its description records provenance.
                if meta.get("test_iri") and not is_raw:
                    dnode["prov:wasGeneratedBy"] = {"@id": meta["test_iri"]}

                # The algorithm is the record's, never assumed: a deposit is
                # permanent, and an md5 digest published as a sha256 is a false
                # statement about the file rather than a missing one.
                _checksum = checksum_node(dist["checksum"])
                if _checksum is not None:
                    dnode["spdx:checksum"] = _checksum
                # File size: dcat:byteSize is an integer; schema:contentSize is text.
                _size = str(dist.get("content_size") or "")
                if _size.isdigit():
                    dnode["dcat:byteSize"] = int(_size)
                dists.append(dnode)

                # schema.org DataDownload mirror so a schema.org-only consumer can
                # reach the file bytes (schema.org has no dcat:downloadURL). Generated
                # from the same source in one pass, so it cannot drift from the DCAT form.
                sdl: dict = {
                    "@type": "schema:DataDownload",
                    "schema:contentUrl": dl_url,
                    "schema:encodingFormat": media_type,
                    "schema:name": fname,
                    "schema:isPartOf": {"@id": ds_id},
                }
                # schema:sha256 names one algorithm, so it is reserved for a real
                # sha256; anything else rides a named PropertyValue.
                sdl.update(schema_checksum_terms(dist["checksum"]))
                if dist.get("description"):
                    sdl["schema:description"] = dist["description"]
                if _size.isdigit():
                    sdl["schema:contentSize"] = _size
                if is_bdf:
                    sdl["dcterms:conformsTo"] = {"@id": BDF_TABLE_SCHEMA_IRI}
                schema_dists.append(sdl)

            cell_name = _cell_name(meta.get("cell_id", ""))
            ds_name = meta.get("name") or (f"{cell_name} {meta.get('kind', '')}".strip() or ds_id.split("/")[-1])
            member: dict = {
                "@type": ["dcat:Dataset", "schema:Dataset"],
                "@id": ds_id,
                "schema:name": ds_name,
                "dcat:distribution": dists,
                "schema:distribution": schema_dists,
                "dcterms:isPartOf": {"@id": record_url},
            }
            if meta.get("is_series"):
                # A collection (DCAT 3 dataset series) groups the member datasets
                # that point at it; it has no files of its own, so it carries the
                # series type and no (empty) distribution arrays.
                member["@type"].append("dcat:DatasetSeries")
                if not dists:
                    del member["dcat:distribution"]
                    del member["schema:distribution"]
            if meta.get("about"):
                # List form: schema:about may carry several subjects, and the
                # publication validator expects a uniform array of @id references.
                member["schema:about"] = [{"@id": iri} for iri in meta["about"]]
            # Series membership (dcat:inSeries + schema:isPartOf). dcterms:isPartOf
            # above still ties the dataset to the deposit's catalog record.
            member.update(dataset_series_edges((meta.get("ds") or {}).get("series_id")))

            # ── Discoverability metadata (FAIR / Google Dataset Search) ────────
            # Carried straight from the dataset record when present, so every member
            # dataset — not just the catalog — is independently discoverable. All
            # additive: records that omit a field simply don't emit it.
            _ds = meta.get("ds") or {}
            if _ds.get("description"):
                member["schema:description"] = _ds["description"]
            if isinstance(_ds.get("access_url"), str) and _ds["access_url"].startswith(("http://", "https://")):
                # Only publish a web access URL here; a local file:// directory URL
                # (local-publication case) is set by that path's adapter instead.
                member["schema:url"] = _ds["access_url"]
            # Rights and attribution on each member: RDF has no inheritance, so a
            # dataset lifted out of the catalog would otherwise lose its licence and
            # creators. The dataset's own licence wins over the catalog's, and either
            # is stated as an IRI, expanded the same way as the catalog's.
            _own_license = _ds.get("license")
            _member_license = _own_license if isinstance(_own_license, str) and _own_license.strip() else license
            if _member_license:
                _lic_value = _license_value(_member_license)
                member["schema:license"] = _lic_value
                member["dcterms:license"] = _lic_value
            # What the dataset record states about itself wins over the deposit, as
            # its licence does above: its own creators, publisher, publication and
            # DOI, read through the record's own JSON-LD writer.
            _own = dataset_to_jsonld(
                {"dataset": {k: _ds[k] for k in ("creators", "publisher", "citations", "same_as") if k in _ds}}
            )
            for _term in ("dcterms:publisher", "schema:citation", "schema:sameAs"):
                if _term in _own:
                    member[_term] = _own[_term]
            if _own.get("dcterms:creator") or creators:
                # Full creator nodes (not @id refs) so a member is self-describing even
                # lifted out of the catalog, and so creators without an ORCID @id are
                # still carried.
                member["schema:creator"] = _own.get("dcterms:creator") or [_agent_node(c) for c in creators or []]
            if _ds.get("keywords"):
                member["schema:keywords"] = list(_ds["keywords"])
            if _ds.get("version"):
                member["schema:version"] = _ds["version"]
            if _ds.get("measurement_techniques"):
                member["schema:measurementTechnique"] = list(_ds["measurement_techniques"])
            if _ds.get("measurement_methods"):
                member["schema:measurementMethod"] = list(_ds["measurement_methods"])
            # Dates: Unix times as ISO 8601, ISO strings as they are. A time that
            # is no date (one in milliseconds) is left out with a warning.
            for _field, _term in (("created_at", "schema:dateCreated"), ("modified_at", "schema:dateModified")):
                _when = _unix_to_iso(_ds.get(_field) or None, what=f"{_field} of dataset {ds_id}")
                if _when:
                    member[_term] = _when
            # NOTE: no per-member schema:datePublished — a member dataset isn't published
            # independently; the deposit's publication date lives on the catalog (set at
            # Zenodo publish). The *measured* period is schema:temporalCoverage below,
            # sourced from the data's timestamps (not the record-assembly time).
            if _ds.get("temporal_coverage"):
                member["schema:temporalCoverage"] = _ds["temporal_coverage"]
                _tc = str(_ds["temporal_coverage"])
                if "/" in _tc:
                    _s, _e = _tc.split("/", 1)
                    if _s:
                        _cov_starts.append(_s)
                    if _e:
                        _cov_ends.append(_e)
            if _ds.get("spatial_coverage"):
                member["schema:spatialCoverage"] = _ds["spatial_coverage"]
            if _funding_grant is not None:
                member["schema:funding"] = _funding_grant
            _all_downloads.extend(schema_dists)
            dataset_member_nodes.append(member)

        # ── Build cell instance nodes ──────────────────────────────────────────
        # Each instance is a physical battery whose type is described by its spec.
        instance_nodes: list[dict] = []
        for cell_iri, inst in sorted(instances.items()):
            cell_spec_id = inst.get("cell_spec_id", "")
            try:
                spec_node = spec_nodes.get(cell_spec_id, {})
                # Inherit the physical type from the spec's isDescriptionFor
                phys_type = spec_node.get("isDescriptionFor", {}).get("@type", "BatteryCell")

                inode: dict = {
                    "@type": phys_type,
                    "@id": cell_iri,
                    "dcterms:conformsTo": {"@id": cell_spec_id},  # instance-of link
                    "hasDescription": {"@id": cell_spec_id},
                    "schema:isVariantOf": {"@id": cell_spec_id},  # ProductModel persona
                }
                # The electrode records this cell was built from. The spec body is in
                # hand here, so a half cell's counter electrode also carries
                # ReferenceElectrode — the reading an instance cannot make alone.
                inode.update(electrode_role_links(inst.get("cell_instance") or {}, cell_spec_bodies.get(cell_spec_id)))
                if inst.get("name"):
                    inode["schema:name"] = inst["name"]
                if inst.get("serial_number"):
                    inode["schema:serialNumber"] = inst["serial_number"]
                if inst.get("grade"):
                    inode["schema:quality"] = inst["grade"]
                if inst.get("manufactured_at"):
                    inode["schema:productionDate"] = _typed_date(inst["manufactured_at"])
                if inst.get("expires_at"):
                    inode["schema:expires"] = _typed_date(inst["expires_at"])
                if inst.get("batch_id"):
                    inode["schema:identifier"] = inst["batch_id"]
                # Conformance assessment (vs the cell spec) as a DQV annotation; the
                # instance-of link above already ties the cell to its spec.
                _apply_conformance_jsonld(inode, cell_spec_id, inst.get("conformance"), add_spec_links=False)
            except Exception as exc:  # noqa: BLE001 - collected; the deposit is refused, not sunk
                _omit("cell-instance", cell_iri, exc)
                continue
            instance_nodes.append(inode)

        # ── Build typed stubs for externally-defined cell specs ────────────────
        # A cell conforms to a cell specification published authoritatively at its
        # own IRI (e.g. the registry). We deliberately do NOT inline the remote spec
        # — copying its body here would risk drift against the authoritative source.
        # But a bare @id leaves a consumer stranded, so emit a minimal, non-drifting
        # stub: the stable @type plus an explicit "defined elsewhere" pointer. Only
        # specs not already inlined locally (in spec_nodes) get a stub.
        external_spec_stubs: list[dict] = []
        _stub_iris = set(spec_nodes)
        for inst in instances.values():
            tid = inst.get("cell_spec_id", "")
            if tid and tid not in _stub_iris:
                _stub_iris.add(tid)
                external_spec_stubs.append(_defined_elsewhere_stub(tid, "BatteryCellSpecification"))

        # ── Compose @graph ─────────────────────────────────────────────────────
        # The Zenodo record is a CATALOG of the per-test datasets above, not a flat
        # bag of distributions: those files are distinct measurements, not
        # alternative encodings of one dataset. schema:Dataset/Collection typing is
        # kept so Zenodo and schema.org consumers still see a top-level dataset — it
        # carries the DOI for the whole deposit.
        # Parameter sets are datasets too (IDENTIFIER_POLICY 6.3), described by
        # their own standalone nodes below: the catalog lists them as members
        # after the per-test datasets, so a deposit holding only parameter sets
        # still references a member dataset.
        _parameter_set_iris = sorted(
            {
                _body["id"]
                for _rec in record_sets.get("parameter-set", [])
                if isinstance(_rec, dict)
                and isinstance(_body := _rec.get("parameter_set"), dict)
                and isinstance(_body.get("id"), str)
                and _body["id"] not in ds_meta
            }
        )
        member_refs = [{"@id": ds_id} for ds_id in sorted(ds_meta)] + [{"@id": iri} for iri in _parameter_set_iris]
        catalog_node: dict = {
            # dcat:Catalog + schema:DataCatalog so catalog-aware consumers in both
            # vocabularies recognise it; schema:Dataset is retained so generic
            # schema.org/Zenodo consumers still see a top-level dataset carrying the DOI.
            "@type": ["dcat:Catalog", "schema:DataCatalog", "schema:Dataset"],
            "@id": record_url,
            "schema:url": record_url,
            "dcat:dataset": member_refs,  # DCAT: catalog → member datasets
            "schema:hasPart": member_refs,  # schema.org equivalent
            "rdfs:seeAlso": {"@id": "https://www.battery-genome.org/registry"},
        }
        if prereserved_doi:  # local publication packages have no DOI
            catalog_node["schema:identifier"] = prereserved_doi
            # @id is the landing page; link the persistent DOI as the canonical identity
            # so a consumer can resolve the citable object, not just the HTML page.
            _doi_url = prereserved_doi if prereserved_doi.startswith("http") else f"https://doi.org/{prereserved_doi}"
            catalog_node["schema:sameAs"] = {"@id": _doi_url}
            catalog_node["dcterms:identifier"] = prereserved_doi
        # Surface every download on the top Dataset (GDS doesn't traverse hasPart) and
        # the overall measured time span (from the data, not record-assembly time).
        if _all_downloads:
            catalog_node["schema:distribution"] = _all_downloads
        if _cov_starts and _cov_ends:
            catalog_node["schema:temporalCoverage"] = f"{min(_cov_starts)}/{max(_cov_ends)}"
        # ── Embed rights + attribution so the artifact is self-describing (FAIR) ──
        # These also go to Zenodo's deposition API, but a portable JSON-LD record
        # must carry its own licence and provenance, not rely on the hosting platform.
        if title:
            catalog_node["schema:name"] = title
            catalog_node["dcterms:title"] = title  # DCAT consumers key on dcterms
        if description:
            catalog_node["schema:description"] = description
            catalog_node["dcterms:description"] = description
        # English text; declare it so language-aware consumers don't have to guess.
        catalog_node["dcterms:language"] = "en"
        catalog_node["schema:inLanguage"] = "en"
        if license:
            # Emit the licence as a dereferenceable IRI (SPDX) rather than a bare code,
            # so a consumer can resolve the exact terms. Matches the RO-Crate path.
            lic_value = _license_value(license)
            catalog_node["dcterms:license"] = lic_value
            catalog_node["schema:license"] = lic_value
        if _funding_grant is not None:
            # Deposit-level funding: the grant under which the whole collection was produced.
            catalog_node["schema:funding"] = _funding_grant
        provider_node = None
        if creators:
            catalog_node["schema:creator"] = [_agent_node(c) for c in creators]
        if contributors:
            catalog_node["schema:contributor"] = [_agent_node(c) for c in contributors]
        # Data provider (publisher) modelled as an Agent/Organization and attributed.
        # Prefer the organisation's ROR as its canonical @id; fall back to a local
        # record-scoped fragment when no ROR is known.
        provider_name, provider_ror = _provider(creators, contributors)
        if provider_name:
            provider_node = {
                "@type": ["schema:Organization", "prov:Agent"],
                "@id": _ror_url(provider_ror) if provider_ror else f"{record_url}#provider",
                "schema:name": provider_name,
            }
            catalog_node["schema:publisher"] = {"@id": provider_node["@id"]}
            catalog_node["dcterms:publisher"] = {"@id": provider_node["@id"]}  # DCAT mirror
            catalog_node["prov:wasAttributedTo"] = {"@id": provider_node["@id"]}
        if spec_nodes:
            catalog_node["schema:about"] = [{"@id": iri} for iri in spec_nodes]

        # ── Versioning (living-record provenance) ─────────────────────────────
        if version:
            catalog_node["schema:version"] = version
        if is_version_of:
            catalog_node["dcterms:isVersionOf"] = {"@id": is_version_of}

        # ── Keywords (FAIR Findable / Google Dataset Search) ──────────────────
        # Auto-derived from the cells, specs and test kinds so every record is
        # discoverable without manual tagging; merged with any explicit keywords.
        _kw: set[str] = {"battery"}
        _kw |= _spec_keywords  # chemistry/format strings from the cell-spec records
        for _sn in spec_nodes.values():
            _mfr = _sn.get("schema:manufacturer")
            if isinstance(_mfr, dict) and _mfr.get("schema:name"):
                _kw.add(_mfr["schema:name"])
        for _m in ds_meta.values():
            if _m.get("kind"):
                _kw.add(str(_m["kind"]))
        for _k in keywords or []:
            _kw.add(str(_k))
        _kw.discard("")
        if _kw:
            catalog_node["schema:keywords"] = sorted(_kw)
            catalog_node["dcat:keyword"] = sorted(_kw)  # DCAT mirror of schema:keywords

        # Standalone material and electrode records (Level 2 spec / Level 3
        # instance) become first-class deposit nodes: the domain-battery emitter
        # types each by its kind (kind -> EMMO class + chemical-substance sameAs
        # for materials, chemistry + polarity classes for electrodes, labeled
        # fallback where a class is missing) and carries its composition,
        # processing and spec link; the consolidated context resolves those
        # terms. Cells reference these via material_spec_id / electrode_spec_id
        # on their components, so publishing the standalone nodes is what makes
        # those links resolve inside the deposit.
        standalone_nodes: builtins.list[dict] = []
        for _mkey in DEPOSIT_STANDALONE_KINDS:
            for _mrec in record_sets.get(_mkey, []):
                if not isinstance(_mrec, dict):
                    continue
                from battinfo.transform.json_to_jsonld import to_jsonld  # noqa: PLC0415

                _mg = to_jsonld(_mrec, target="domain-battery").get("@graph") or []
                if _mg:
                    standalone_nodes.append(dict(_mg[0]))

        graph = (
            [catalog_node]
            + ([provider_node] if provider_node else [])
            + dataset_member_nodes
            + list(spec_nodes.values())
            + external_spec_stubs
            + test_spec_nodes
            + instance_nodes
            + test_nodes
            + standalone_nodes
            # Equipment provenance: the units/channels the tests actually ran on,
            # so hasTestEquipment / prov:used resolve to described nodes.
            + [equipment_nodes[k] for k in sorted(equipment_nodes)]
            + [channel_nodes[k] for k in sorted(channel_nodes)]
        )

        _present_ids = {node.get("@id") for node in graph if isinstance(node, dict)}

        # A test or dataset may point at a cell or test spec that lives only in
        # the registry (referenced by IRI or search hit). The workspace keeps a
        # read-only copy of that published record, and the copy gives it the
        # same non-drifting "defined elsewhere" stub as an external cell spec
        # above, named as the tests and datasets that point at it are. Its body
        # stays with the published record: this deposit does not carry it. A
        # reference with no copy gets no node, and the graph check reports it.
        _pointed_at: set[str] = set()
        for _node in test_nodes:
            _used = _node.get("prov:used")
            for _ref in [_node.get("hasTestObject"), *(_used if isinstance(_used, list) else [_used])]:
                if isinstance(_ref, dict) and isinstance(_ref.get("@id"), str):
                    _pointed_at.add(_ref["@id"])
        for _node in dataset_member_nodes:
            _pointed_at.update(_ref["@id"] for _ref in _node.get("schema:about") or [])
        for _target_iri in sorted(_pointed_at - _present_ids):
            if _target_iri in _referenced:
                _folder, _target_type, _name = _referenced[_target_iri]
                _present_ids.add(_target_iri)
                graph.append(_defined_elsewhere_stub(_target_iri, _target_type, _name))

        # A parameter set names the cell spec, cell or material spec it is
        # about; one the deposit does not carry gets the same stub, so the
        # reference resolves to a node instead of failing the graph check.
        for _target_iri, _target_type in _parameter_set_target_refs(record_sets.get("parameter-set", [])):
            if _target_iri not in _present_ids:
                _present_ids.add(_target_iri)
                graph.append(
                    _defined_elsewhere_stub(
                        _target_iri,
                        _target_type,
                        _cell_name(_target_iri) if _target_type == "BatteryCell" else "",
                    )
                )

        # ── Record-level free-text notes → schema:comment ─────────────────────
        # Each record's top-level notes[] were dropped from the publication graph;
        # attach them to the node carrying that record's id so authored context
        # survives the deposit. Additive: nodes with an existing comment are left.
        _notes_by_id: dict[str, builtins.list[str]] = {}
        for _recs in record_sets.values():
            for _rec in _recs:
                if not isinstance(_rec, dict):
                    continue
                _notes = [n for n in (_rec.get("notes") or []) if isinstance(n, str) and n.strip()]
                if not _notes:
                    continue
                for _body in _rec.values():
                    if isinstance(_body, dict) and _body.get("id"):
                        _notes_by_id[_body["id"]] = _notes
                        break
        for _node in graph:
            _nid = _node.get("@id")
            if _nid in _notes_by_id and "schema:comment" not in _node:
                _texts = _notes_by_id[_nid]
                _node["schema:comment"] = _texts[0] if len(_texts) == 1 else _texts

        # ── Inline context: the versioned v1 context + dynamic prefLabel terms ─
        # _RECORDS_CONTEXT is records.context.v1.json, the file served at the
        # hosted context URL (generated by `python scripts/gen_context.py`).
        # label_to_compact() adds the core class terms plus quantity/unit
        # prefLabels loaded from the curated maps and the entity-type map.
        context = dict(_RECORDS_CONTEXT)
        context.update(label_to_compact())
        # Test-protocol vocabulary (control/termination parameters + their quantity
        # classes) — only needed when conditions are emitted, but harmless otherwise.
        from battinfo.jsonld import (  # noqa: PLC0415
            TEST_METHOD_CONTEXT_TERMS,
            TEST_PROTOCOL_CONTEXT_TERMS,
        )

        for _term, _val in TEST_PROTOCOL_CONTEXT_TERMS.items():
            context.setdefault(_term, _val)
        # EMMO process/quantity terms used by the descriptive method graph.
        for _term, _val in TEST_METHOD_CONTEXT_TERMS.items():
            context.setdefault(_term, _val)

        # What was left out goes back to a caller that asked for it, and stops
        # any other: a graph with records missing is not published.
        if _omitted:
            if omissions is None:
                _records = len({(omission.kind, omission.record) for omission in _omitted})
                raise ValueError(
                    f"{_records} record(s) could not be converted in full to JSON-LD, so a graph "
                    f"of them would be incomplete: {_omission_list(_omitted)}. Fix or remove these "
                    "records, then build the graph again."
                )
            omissions.extend(omission for omission in _omitted if omission not in omissions)

        doc = {"@context": context, "@graph": graph}
        # Fail fast if the assembled document is not valid JSON-LD, rather than
        # discovering it only after upload (or in a downstream consumer).
        return validate_jsonld(doc, where=BATTINFO_LD_FILENAME)

    def _build_zenodo_jsonld(
        self,
        *,
        zenodo_record_id: int,
        prereserved_doi: str,
        record_url: str,
        data_filenames: builtins.list[str] | None = None,
        title: str = "",
        description: str = "",
        creators: builtins.list[dict] | None = None,
        contributors: builtins.list[dict] | None = None,
        license: str = "",
        keywords: builtins.list[str] | None = None,
        version: str = "",
        is_version_of: str = "",
        file_plan: DepositFilePlan | None = None,
        omissions: builtins.list[Omission] | None = None,
    ) -> dict:
        """Read this workspace's saved records and assemble the deposit JSON-LD.

        Thin adapter over :meth:`_assemble_zenodo_jsonld` (the shared graph builder):
        it only sources the canonical record dicts from the workspace directory,
        and the copies of published records it references from
        ``.battinfo/references/`` (read for stub nodes, never deposited).
        :meth:`zenodo` and :meth:`preview_jsonld` pass the deposit's ``file_plan``
        (:meth:`_deposit_file_plan`), which names every local file, and an
        ``omissions`` list that collects the records the graph leaves out;
        without one a record left out raises a ``ValueError``.
        """
        record_sets, _replaced = _read_deposit_record_sets(self._ws.source_root)
        return self._assemble_zenodo_jsonld(
            record_sets,
            referenced_records=_read_record_sets(self._references_root),
            zenodo_record_id=zenodo_record_id,
            prereserved_doi=prereserved_doi,
            record_url=record_url,
            data_filenames=data_filenames,
            file_plan=file_plan,
            omissions=omissions,
            title=title,
            description=description,
            creators=creators,
            contributors=contributors,
            license=license,
            keywords=keywords,
            version=version,
            is_version_of=is_version_of,
        )

    def _build_rocrate(
        self,
        tmpdir: Path,
        data_files: builtins.list[DepositFile],
        *,
        title: str,
        description: str,
        creators: builtins.list[dict],
        contributors: builtins.list[dict],
        license: str,
        zenodo_record_id: int,
        prereserved_doi: str,
        sandbox: bool = False,
    ) -> None:
        """Write a conforming ``ro-crate-metadata.json`` to *tmpdir*.

        Produces a minimal RO-Crate 1.1 that:
        - Lists ``battinfo.json`` and all data files as ``hasPart``
        - References the Zenodo record URL and DOI
        - Is processable by any RO-Crate-aware tool (EOSC portals, WorkflowHub, etc.)

        *data_files* are the data files the deposit holds: those
        :meth:`_bundle_data_files` uploads and those it keeps. A file's ``@id``
        is its deposit name percent-encoded, a relative URL, and its ``name``
        the name itself; size and sha256 come from the plan.
        """
        domain = "sandbox.zenodo.org" if sandbox else "zenodo.org"
        record_url = f"https://{domain}/records/{zenodo_record_id}"

        def _creator_node(c: dict) -> dict:
            node: dict = {"@type": "Person", "name": c.get("name", "")}
            if c.get("affiliation"):
                node["affiliation"] = {"@type": "Organization", "name": c["affiliation"]}
            if c.get("orcid"):
                node["@id"] = f"https://orcid.org/{c['orcid']}"
            return node

        def _contributor_node(c: dict) -> dict:
            node = _creator_node(c)
            if c.get("type"):
                node["roleName"] = c["type"]
            return node

        creator_nodes = [_creator_node(c) for c in creators] if creators else []
        contributor_nodes = [_contributor_node(c) for c in contributors] if contributors else []

        # Root Dataset
        parts = [{"@id": BATTINFO_LD_FILENAME}] + [{"@id": f.segment} for f in data_files]
        root: dict = {
            "@type": "Dataset",
            "@id": "./",
            "name": title,
            "description": description,
            "datePublished": _now_iso()[:10],
            "license": _license_value(license),
            "url": record_url,
            "identifier": prereserved_doi,
            "hasPart": parts,
        }
        if creator_nodes:
            root["creator"] = creator_nodes if len(creator_nodes) > 1 else creator_nodes[0]
        if contributor_nodes:
            root["contributor"] = contributor_nodes if len(contributor_nodes) > 1 else contributor_nodes[0]

        # linked-data file entity
        jsonld_entity: dict = {
            "@type": ["File", "CreativeWork"],
            "@id": BATTINFO_LD_FILENAME,
            "name": "BattINFO linked data",
            "description": "Battery domain metadata using EMMO/domain-battery ontology terms.",
            "encodingFormat": "application/ld+json",
            "conformsTo": {"@id": "https://w3id.org/battinfo/"},
        }
        jsonld_path = tmpdir / BATTINFO_LD_FILENAME
        if jsonld_path.exists():
            jsonld_entity["contentSize"] = str(jsonld_path.stat().st_size)

        # Data file entities
        file_entities: list[dict] = []
        for data_file in data_files:
            fn = data_file.name
            entity: dict = {
                "@type": "File",
                "@id": data_file.segment,
                "name": fn,
                "encodingFormat": (
                    "application/x-parquet"
                    if fn.endswith(".parquet")
                    else "text/csv"
                    if fn.endswith(".csv")
                    else "application/zip"
                    if fn.endswith(".zip")
                    else "application/octet-stream"
                ),
            }
            if data_file.sha256:
                entity["contentSize"] = str(data_file.size)
                entity["sha256"] = data_file.sha256
            file_entities.append(entity)

        graph = [
            # Required self-reference node
            {
                "@type": "CreativeWork",
                "@id": _ROCRATE_FILENAME,
                "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
                "about": {"@id": "./"},
            },
            root,
            jsonld_entity,
            *file_entities,
        ]

        crate = {
            "@context": "https://w3id.org/ro/crate/1.1/context",
            "@graph": graph,
        }
        (tmpdir / _ROCRATE_FILENAME).write_text(
            json.dumps(crate, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _deposit_spec_summaries(self) -> builtins.list[dict]:
        """Manufacturer, model, chemistry, format and IEC code of each saved cell spec, by file name."""
        ct_dir = self._ws.source_root / "cell-spec"
        specs: list[dict] = []
        if ct_dir.exists():
            for f in sorted(ct_dir.glob("*.json")):
                try:
                    raw = json.loads(f.read_text(encoding="utf-8"))
                    prod = raw.get("cell_spec", {})
                    mfr = prod.get("manufacturer", {})
                    specs.append(
                        {
                            "manufacturer": mfr.get("name", "") if isinstance(mfr, dict) else str(mfr),
                            "model": prod.get("model", ""),
                            "chemistry": prod.get("chemistry", ""),
                            "format": prod.get("cell_format", ""),
                            "iec_code": prod.get("iec_code", ""),
                        }
                    )
                except Exception:
                    continue
        return specs

    def _deposit_title(self, title: str | None, specs: builtins.list[dict] | None = None) -> str:
        """The deposit's title: *title* when given, else the automatic one.

        The Zenodo metadata, the deposit graph's catalog node and the RO-Crate
        all take this one value, so a deposit made without a title still
        names its catalog, and the preview shows the name the deposit gets.
        """
        if isinstance(title, str) and title.strip():
            return title
        return _auto_deposit_title(self._deposit_spec_summaries() if specs is None else specs)

    def _build_zenodo_metadata(
        self,
        *,
        title: str | None,
        description: str | None,
        creators: builtins.list[dict],
        contributors: builtins.list[dict] | None = None,
        license: str,
        community: str | None,
        extra_keywords: builtins.list[str] | None,
    ) -> dict:
        specs = self._deposit_spec_summaries()
        _clean_meta = _clean_deposit_text

        s0 = specs[0] if specs else {}
        ds_dir = self._ws.source_root / "dataset"
        n_ds = len(list(ds_dir.glob("*.json")) if ds_dir.exists() else [])

        if s0:
            name_parts = [p for p in (_clean_meta(s0.get("manufacturer")), _clean_meta(s0.get("model"))) if p]
            attr_parts = [p for p in (_clean_meta(s0.get("format")), _clean_meta(s0.get("chemistry"))) if p]
            subject = " ".join(name_parts)
            if attr_parts:
                subject = f"{subject} ({', '.join(attr_parts)})".strip()
            auto_desc = (
                f"Battery dataset for {subject or 'battery cells'}. "
                f"Contains {n_ds} dataset(s). "
                "Published via BattINFO (https://github.com/BIG-MAP/BattINFO)."
            )
        else:
            auto_desc = "Battery dataset published via BattINFO."

        kw: list[str] = ["BattINFO", "battery", "electrochemistry"]
        for s in specs:
            for v in (s["manufacturer"], s["model"], s["chemistry"], s["format"], s["iec_code"]):
                cv = _clean_meta(v)
                if cv and cv not in kw:
                    kw.append(cv)
        for k in extra_keywords or []:
            if k not in kw:
                kw.append(k)

        meta: dict = {
            "upload_type": "dataset",
            "title": self._deposit_title(title, specs),
            "description": description or auto_desc,
            "creators": creators,
            "access_right": "open",
            "license": license,
            "keywords": kw,
        }
        if contributors:
            # Zenodo requires a "type" on each contributor; default to "ProjectMember"
            meta["contributors"] = [{**c, "type": c.get("type", "ProjectMember")} for c in contributors]
        if community:
            meta["communities"] = [{"identifier": community}]
        # Funding project (grant) → a related identifier pointing at the project's
        # resolvable page (CORDIS for EU grants). Safe: Zenodo always accepts a URL
        # related identifier, so it never risks failing the deposit (unlike the
        # native `grants` field, which 400s on an id Zenodo doesn't recognise).
        ref = self._get_project()
        if ref is not None and ref.id:
            meta.setdefault("related_identifiers", []).append(
                {
                    "identifier": ref.id,
                    "relation": "isPartOf",
                    "scheme": "url",
                }
            )
        return meta

    def _load_zenodo_state(self, environment: str = "production") -> dict:
        """The record this workspace continues on the Zenodo of *environment*, or ``{}``.

        ``.battinfo/zenodo.json`` for zenodo.org, ``.battinfo/zenodo-sandbox.json``
        for the sandbox. Raises :class:`~battinfo._deposit_index.DepositIndexError`,
        naming the file, when it cannot be read.
        """
        return load_deposit_state(self._root, environment)

    def _save_zenodo_state(self, state: dict) -> None:
        """Write *state* to the state file of its environment, atomically."""
        save_deposit_state(self._root, state)

    def _reconcile_zenodo_draft(self, client: Any, state: dict, *, index: dict[str, Any] | None = None) -> dict | None:
        """Ask Zenodo whether the draft *state* records is still a draft.

        Returns the live draft when it is. When it was published since, on the
        Zenodo website or by a run that stopped before it recorded the
        publish, *state* is updated to say so (with the DOI) and saved, the
        files the draft holds count among those of the published versions in
        the deposit index (*index*, else the one on disk, when it can be
        read), and ``None`` is returned.
        """
        from battinfo.zenodo import deposit_is_published  # noqa: PLC0415

        draft = state["record_id"]
        deposit = client.get_deposit(state.get("deposit_id") or draft)
        if not deposit_is_published(deposit):
            return deposit
        metadata = deposit.get("metadata") if isinstance(deposit.get("metadata"), dict) else {}
        doi = deposit.get("doi") or metadata.get("doi") or state.get("doi")
        state.update(
            published=True,
            doi=str(doi or ""),
            record_id=str(deposit.get("record_id") or draft),
        )
        state.pop("version_of", None)  # published, it is the version the next one is made from
        self._save_zenodo_state(state)
        environment = str(state.get("environment") or "production")
        if index is None:
            try:
                index = load_deposit_index(self._root)
            except DepositIndexError:
                index = None  # ws.zenodo() names the file when it reads it
        if index is not None:
            concept = state.get("concept_record_id") or concept_of_record(index, environment, draft)
            self._note_draft_published(index, environment, concept, draft)
        print(
            f"  The Zenodo draft {state['record_id']} has been published since this workspace "
            f"recorded it; {state_file(environment)} now says so."
        )
        return None

    def _note_draft_published(
        self, index: dict[str, Any], environment: str, concept: str | None, record_id: str
    ) -> None:
        """Count the files the draft *record_id*, now published, holds among those of the published versions.

        An index that cannot be written is left as it is, with a warning:
        the draft's own entries give the next deposit, which starts from
        this record, the same files.
        """
        try:
            if note_published(index, environment, concept, record_id):
                save_deposit_index(self._root, index)
        except OSError as exc:
            warnings.warn(
                f"The Zenodo record {record_id} is published, but .battinfo/deposit-files.json could not "
                f"be written ({exc}). It still lists the record's files as those of a draft, which the "
                "next deposit reads the same way.",
                stacklevel=3,
            )

    def _refuse_unknown_zenodo_copies(
        self,
        client: Any,
        plan: DepositFilePlan,
        context: DepositContext,
        *,
        continues: str | None,
        live_draft: Mapping[str, Any] | None,
    ) -> None:
        """Refuse a deposit whose records point at Zenodo files that may be copies of its own data no reader can use.

        *plan* lists such URLs by record id (``plan.unplaced``): Zenodo file
        URLs on the deposit's Zenodo, under a record the deposit does not
        continue, whose file the deposit index does not know. An earlier build
        pointed records at the drafts and versions it made without recording
        them, so the URL may be a copy of a file whose local source this
        workspace does not know. Zenodo is asked about each such record, before
        anything is created or changed:

        - a record Zenodo does not show this account (HTTP 403, 404 or 410) is
          someone else's, and the deposit links to it;
        - a draft of this account that is not published serves its files to no
          reader, and refuses the deposit;
        - a published record of this account refuses the deposit when it is a
          version of the record the deposit continues (*continues*, the record
          or draft the run starts from; *live_draft* is that draft as Zenodo
          returned it, when the run already asked), since the version the
          deposit is made from need not hold its files. Any other is a link.

        The concept record of the continued record is looked up only when a
        published record needs the comparison. The refusal names each dataset
        and how to point it at its local file again.
        """
        if not plan.unplaced:
            return
        from battinfo.zenodo import ZenodoError, deposit_is_published  # noqa: PLC0415

        host = ZENODO_HOSTS[context.environment]
        concept = context.concept
        # Without a recorded concept, the continued record's is asked of
        # Zenodo once, when a published record needs the comparison.
        concept_known = bool(concept) or not continues
        refused: builtins.list[str] = []
        try:
            for record, uses in sorted(plan.unplaced.items()):
                try:
                    found = client.get_deposit(record)
                except ZenodoError as exc:
                    if exc.status in (403, 404, 410):
                        continue  # not this account's record: a link elsewhere
                    raise
                if not deposit_is_published(found):
                    why = (
                        f"is in the draft {record} on {host}, which this Zenodo account has not "
                        "published, so no reader can download it"
                    )
                else:
                    if not concept_known:
                        stored = live_draft if live_draft is not None else client.get_deposit(continues)
                        concept = str(stored.get("conceptrecid") or "") or None
                        concept_known = True
                    if not concept or str(found.get("conceptrecid") or "") != concept:
                        continue  # another published record of this account: a link
                    why = (
                        f"is in the record {record}, a version of this workspace's own Zenodo record "
                        f"(concept {concept} on {host}) that the workspace never recorded, and the "
                        "version this deposit is made from need not hold it"
                    )
                refused.extend(f"dataset {dataset}: {url} {why}" for dataset, url in uses)
        except ZenodoError as exc:
            raise ZenodoError(
                f"{exc} (asked to tell which Zenodo record holds files the dataset records point at). "
                "Nothing was created on Zenodo.",
                status=exc.status,
            ) from exc
        if refused:
            raise RuntimeError(
                f"Refusing to deposit: {len(refused)} distribution(s) point at a copy on Zenodo whose "
                "local file this workspace has no record of, and the deposit cannot link to it: "
                + "; ".join(refused)
                + f". {_POINT_AT_LOCAL_FILE}, then re-run. Nothing was created on Zenodo."
            )

    def _refuse_missing_kept_copies(
        self,
        client: Any,
        plan: DepositFilePlan,
        datasets: Iterable[object],
        *,
        starts_from: str | None,
        updates_draft: bool,
    ) -> None:
        """Refuse a deposit whose kept copies the record it starts from does not hold, before anything is created.

        A data file with no local copy is kept as the record the deposit
        starts from (*starts_from*) holds it: the draft it updates
        (*updates_draft*), or the published record a new version is made from,
        whose files the new version takes over. Zenodo is asked for that
        record's files, so a copy it does not hold, or holds with another md5
        than the one recorded, refuses the deposit before a draft is made or
        changed. *datasets* are the dataset records, to name the ones whose
        copy is missing.
        """
        kept = plan.kept_files()
        if not kept or starts_from is None:
            return
        from battinfo.zenodo import ZenodoError  # noqa: PLC0415

        try:
            listing = client.list_files(starts_from)
        except ZenodoError as exc:
            raise ZenodoError(
                f"{exc} (asked which data files the Zenodo record {starts_from} holds). Nothing was created on Zenodo.",
                status=exc.status,
            ) from exc
        lacking = kept_copy_problems(listing, {entry.name: entry.md5 for entry in kept})
        if lacking:
            holder = (
                f"the draft {starts_from} that this deposit updates"
                if updates_draft
                else f"the published record {starts_from} that this deposit makes a new version of"
            )
            raise RuntimeError(
                _kept_copies_refusal(plan, datasets, lacking, holder) + " Nothing was created or changed on Zenodo."
            )

    def _submission_doi(self, doi: str | None) -> Callable[[object], str | None]:
        """The DOI :meth:`submit` records on a record, by the record's IRI.

        *doi*, when given, goes on every record. Without it, the DOI of the
        Zenodo record this workspace continues goes on the records its deposit
        holds, and only once it is published on zenodo.org. A recorded draft is
        first checked with Zenodo (when ``ZENODO_API_TOKEN`` is set), in case
        it was published on the website since.
        """
        if doi:
            return lambda iri: doi
        state = self._load_zenodo_state("production")
        if not state:
            # No record on zenodo.org: a state file that is there names a sandbox
            # record (zenodo.json does so only as an earlier build wrote it).
            if any(state_path(self._root, environment).exists() for environment in ZENODO_HOSTS):
                print(
                    f"  NOTE: this workspace's Zenodo record is on the sandbox ({state_file('sandbox')}), "
                    "and a sandbox DOI is never recorded on the records."
                )
            return lambda iri: None
        record = f"The Zenodo record {state['record_id']} in {state_file('production')}"
        checked = True
        if not state.get("published"):
            checked = self._check_zenodo_draft(state)
        if not state.get("published"):
            unchecked = "" if checked else " (it could not be checked whether it was published since)"
            print(
                f"  NOTE: {record} is a draft{unchecked}, so its DOI is not recorded on the records. "
                "Publish it, then submit again."
            )
            return lambda iri: None
        stored = str(state.get("doi") or "")
        if "records" not in state:
            hint = f"Pass doi={stored!r} to record it on every record." if stored else "Pass doi= to record one."
            print(
                f"  NOTE: {record} does not list the records its deposit holds, so its DOI is not "
                f"recorded on them. {hint}"
            )
            return lambda iri: None
        held = frozenset(state["records"])
        return lambda iri: stored if stored and isinstance(iri, str) and iri in held else None

    def _check_zenodo_draft(self, state: dict) -> bool:
        """For :meth:`submit`: ask Zenodo about the draft *state* records, if a token is set.

        Returns False when it could not be checked: no ``ZENODO_API_TOKEN``,
        or Zenodo did not answer (a warning says why).
        """
        from battinfo.zenodo import ZenodoClient, ZenodoError  # noqa: PLC0415

        token = self._credential("ZENODO_API_TOKEN")
        if not token:
            return False
        try:
            self._reconcile_zenodo_draft(ZenodoClient(token=token), state)
        except ZenodoError as exc:
            warnings.warn(f"The Zenodo draft {state['record_id']} could not be checked: {exc}", stacklevel=3)
            return False
        return True

    # ── Conversion provenance: converted-file → original-source mapping ──────────
    def _conversions_path(self) -> Path:
        return self._root / ".battinfo" / "conversions.json"

    def _load_conversions(self) -> dict[str, Any]:
        """Mapping of converted-file path → source path (str) or a dict with
        ``source`` + ``unmapped_columns`` (both paths absolute)."""
        if self._conversion_sources is None:
            p = self._conversions_path()
            self._conversion_sources = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        return self._conversion_sources

    def _record_conversion(self, src: Path, out: Path, *, unmapped_columns: builtins.list[str] | None = None) -> None:
        """Remember that *out* was converted from *src*, for provenance at publish.

        When the conversion dropped source columns (see :meth:`convert`), their
        names are recorded alongside the source link so the loss stays visible
        after the session ends. Entries without loss keep the legacy plain-string
        form (out -> src) for compatibility with existing manifests.

        Both files are registered as data files of this workspace too, so a
        Zenodo deposit may read them wherever they lie (see :meth:`zenodo`).
        """
        self._register_sources([src, out], by="ws.convert")
        conv = self._load_conversions()
        if unmapped_columns:
            conv[str(out.resolve())] = {
                "source": str(src.resolve()),
                "unmapped_columns": list(unmapped_columns),
            }
        else:
            existing = conv.get(str(out.resolve()))
            # Don't erase a previously recorded loss report with a bare re-link.
            if isinstance(existing, dict) and existing.get("unmapped_columns"):
                existing["source"] = str(src.resolve())
            else:
                conv[str(out.resolve())] = str(src.resolve())
        p = self._conversions_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(conv, indent=2, ensure_ascii=False), encoding="utf-8")

    def _resolve_raw_source(self, data_path: Path) -> Path | None:
        """Return the original (pre-conversion) source file for a converted file.

        Looks up the conversion manifest written by :meth:`convert`. Returns
        ``None`` if the file was not produced by ``ws.convert`` or the original
        no longer exists.
        """
        conv = self._load_conversions()
        entry = conv.get(str(data_path.resolve()))
        # Entries are either the legacy plain source string or a dict carrying
        # the source plus an unmapped-column loss report (see _record_conversion).
        src = entry.get("source") if isinstance(entry, dict) else entry
        if not src:
            return None
        sp = Path(src)
        return sp if sp.exists() else None

    def export(
        self,
        fmt: str = "json-ld",
        output_dir: str | Path | None = None,
    ) -> builtins.list[Path]:
        """Export the workspace's saved cell specs, cells, test specs, tests and datasets as RDF.

        Converts each record to JSON-LD, loads it into an RDF graph, then
        serializes to the requested format.  Requires ``ws.save()`` first.

        Parameters
        ----------
        fmt:
            RDF serialization format.  Common values:

            * ``"json-ld"`` (default) — JSON-LD, ``.jsonld``
            * ``"ttl"`` / ``"turtle"`` — Turtle, ``.ttl``
            * ``"xml"`` — RDF/XML, ``.rdf``
            * ``"nt"`` — N-Triples, ``.nt``
            * ``"n3"`` — Notation3, ``.n3``

        output_dir:
            Write files here instead of alongside the originals.

        Example::

            ws.save()
            ws.export()              # JSON-LD (default)
            ws.export("ttl")         # Turtle
            ws.export("ttl", "rdf/") # Turtle in a separate folder
        """
        from rdflib import Graph

        from battinfo.jsonld import record_to_jsonld

        _FMT_MAP: dict[str, tuple[str, str]] = {
            "json-ld": ("json-ld", ".jsonld"),
            "jsonld": ("json-ld", ".jsonld"),
            "json_ld": ("json-ld", ".jsonld"),
            "ttl": ("turtle", ".ttl"),
            "turtle": ("turtle", ".ttl"),
            "xml": ("xml", ".rdf"),
            "rdf": ("xml", ".rdf"),
            "nt": ("nt", ".nt"),
            "ntriples": ("nt", ".nt"),
            "n3": ("n3", ".n3"),
        }
        rdflib_fmt, ext = _FMT_MAP.get(fmt.lower(), (fmt.lower(), f".{fmt.lower()}"))

        records_root = self._ws.source_root
        if not records_root.exists():
            print("  No records found -- run ws.save() first.")
            return []

        out_root = Path(output_dir).resolve() if output_dir else None
        written: list[Path] = []

        _TYPE_MAP = {
            "cell-spec": "cell-spec",
            "cell-instance": "cell-instance",
            "test": "test",
            "test-protocol": "test-protocol",
            "dataset": "dataset",
        }

        for record_type, jsonld_type in _TYPE_MAP.items():
            src_dir = records_root / record_type
            if not src_dir.exists():
                continue
            dst_dir = out_root / record_type if out_root else src_dir
            dst_dir.mkdir(parents=True, exist_ok=True)

            for src in sorted(src_dir.glob("*.json")):
                try:
                    raw = json.loads(src.read_text(encoding="utf-8"))
                    # JSON-LD files carry the one-line hosted-context URL (the
                    # default); RDF conversions must inline, or rdflib would
                    # fetch the context URL over the network at parse time.
                    doc = record_to_jsonld(
                        raw,
                        jsonld_type,
                        context="url" if rdflib_fmt == "json-ld" else "inline",
                    )
                    dst = dst_dir / src.with_suffix(ext).name
                    if rdflib_fmt == "json-ld":
                        # Write directly — preserves compact IRIs and context
                        dst.write_text(
                            json.dumps(doc, indent=2, ensure_ascii=False),
                            encoding="utf-8",
                        )
                    else:
                        g = Graph()
                        g.parse(data=json.dumps(doc), format="json-ld")
                        dst.write_text(g.serialize(format=rdflib_fmt), encoding="utf-8")
                    written.append(dst)
                except Exception as exc:
                    print(f"  WARNING: {src.name} -- {exc}")

        print(f"Exported {len(written)} file(s) [{fmt}] to {out_root or records_root}")
        return written

    # ── Internal helpers ────────────────────────────────────────────────────────

    def _search_records(self, terms: builtins.list[str], threshold: float = 0.75) -> builtins.list[dict]:
        cache = self._get_search_cache()
        scored: list[tuple[float, dict]] = []
        for entry in cache:
            score = _fuzzy_score(terms, entry["_mfr"], entry["_model"], frozenset(entry.get("_size") or []))
            if score < threshold:
                continue

            if entry.get("source") == "api":
                scored.append(
                    (
                        score,
                        {
                            "id": entry["id"],
                            "_canonical_id": entry.get("_canonical_id", ""),
                            "manufacturer": entry["_mfr"],
                            "model": entry["_model"],
                            "source": "api",
                        },
                    )
                )
            else:
                try:
                    data = json.loads(Path(entry["source"]).read_text(encoding="utf-8"))
                except Exception:
                    continue
                product = data.get("cell_spec", {})
                mfr = product.get("manufacturer", {})
                scored.append(
                    (
                        score,
                        {
                            "id": entry["id"],
                            "manufacturer": mfr.get("name", "") if isinstance(mfr, dict) else str(mfr),
                            "model": product.get("model", ""),
                            "source": entry["source"],
                            "_record": data,
                        },
                    )
                )
        scored.sort(key=lambda x: -x[0])
        return [r for _, r in scored]

    _INDEX_FILE = ".search-index.json"

    def _get_search_cache(self) -> builtins.list[dict]:
        """Return the search index: registry API first, local clone as fallback.

        The index is kept for the session, and built again when the workspace's
        registry changes (a new ``BATTINFO_REGISTRY_URL``).
        """
        registry = self._registry_url
        if self._search_cache is not None and self._search_cache_registry == registry:
            return self._search_cache
        self._search_cache_registry = registry
        if registry:
            try:
                self._search_cache = self._build_api_cache()
                return self._search_cache
            except Exception as exc:
                print(f"  Registry unreachable ({exc}), falling back to local clone.")
        if self._records_repo is not None:
            self._search_cache = self._load_or_build_index()
        else:
            self._search_cache = []
        return self._search_cache

    def _build_api_cache(self) -> builtins.list[dict]:
        """Fetch all published cell-spec summaries from the registry API."""
        data = self._fetch_resource_pages({"resource_type": "cell_spec"})

        entries: list[dict] = []
        for r in data:
            title = r.get("title", "")
            metadata = r.get("metadata") or {}

            mfr = str(metadata.get("manufacturer") or "").lower()
            model = str(metadata.get("model") or "").lower()
            if not mfr:
                # Fall back: parse first token of title as manufacturer
                parts = title.split(None, 1)
                mfr = parts[0].lower() if parts else ""
                model = parts[1].lower() if len(parts) > 1 else ""

            size_code = str(metadata.get("size_code") or "")
            iec_code = str(metadata.get("iec_code") or "")
            size_exp = _expand_size_codes(size_code, iec_code)

            entries.append(
                {
                    "id": r.get("canonical_iri", ""),
                    "_canonical_id": r.get("canonical_id", ""),
                    "_mfr": mfr,
                    "_model": model,
                    "_size": size_exp.split() if size_exp else [],
                    "_title": title,
                    "source": "api",
                }
            )
        return entries

    def _load_or_build_index(self) -> builtins.list[dict]:
        """Load the persisted index if it matches current record count; rebuild otherwise."""
        # Callers guard on self._records_repo (see search()); loud failure otherwise.
        assert self._records_repo is not None, "a records repo is required to build the cell-spec index"
        curated = self._records_repo / "records" / "cell-spec"
        staging = self._records_repo / "records" / "_staging" / "cell-spec"
        index_path = self._records_repo / self._INDEX_FILE

        current_count = (sum(1 for _ in curated.glob("*/record.json")) if curated.exists() else 0) + (
            sum(1 for _ in staging.glob("*.json")) if staging.exists() else 0
        )

        if index_path.exists():
            try:
                stored = json.loads(index_path.read_text(encoding="utf-8"))
                if stored.get("count") == current_count:
                    return stored["entries"]
            except Exception:
                pass

        # Build from scratch
        entries: list[dict] = []
        for search_root, pattern in [
            (curated, "*/record.json"),
            (staging, "*.json"),
        ]:
            if not search_root.exists():
                continue
            for f in search_root.glob(pattern):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                except Exception:
                    continue
                product = data.get("cell_spec", {})
                mfr = product.get("manufacturer", {})
                mfr_name = mfr.get("name", "") if isinstance(mfr, dict) else str(mfr)
                size_code = str(product.get("size_code") or "")
                iec_code = str(product.get("iec_code") or "")
                size_exp = _expand_size_codes(size_code, iec_code)
                entries.append(
                    {
                        "id": product.get("id", ""),
                        "_mfr": mfr_name.lower(),
                        "_model": str(product.get("model", "") or "").lower(),
                        "_size": size_exp.split() if size_exp else [],
                        "source": str(f),
                    }
                )

        try:
            index_path.write_text(
                json.dumps({"count": current_count, "entries": entries}, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass  # index is optional — searches will be slower without it

        return entries

    def _load_from_file(self, path: Path) -> Any:
        from battinfo.bundle import CELL_TYPE_AUTHORING_PROPERTY_FIELDS, CellSpec  # noqa: PLC0415

        raw = json.loads(path.read_text(encoding="utf-8"))
        flat_names = frozenset(CELL_TYPE_AUTHORING_PROPERTY_FIELDS)
        _check_draft_keys(
            raw,
            _cell_spec_draft_keys(),
            draft="cell-spec",
            path=path,
            aliases=_CELL_SPEC_DRAFT_ALIASES,
            quiet=flat_names,
        )
        # A null is an unfilled template entry: the model default applies.
        fields = {key: value for key, value in raw.items() if not str(key).startswith("_") and value is not None}
        # `specs` (the draft key until June 2026) is read as an alias of
        # `properties`, merged the way CellSpec(specs=...) merges it (properties
        # wins), and a flat property name ("nominal_voltage": {...}) the way
        # CellSpec(nominal_voltage=...) reads it (it wins over both).
        flat = {key: fields.pop(key) for key in [key for key in fields if key in flat_names]}
        quantities = {**(fields.pop("specs", None) or {}), **(fields.pop("properties", None) or {}), **flat}
        # A draft written before 0.8.0 may hold text in a quantity's value: a
        # numeric string becomes the number, other text moves to value_text.
        # The component holders (electrodes, electrolyte, separator, housing,
        # construction) carry quantities too, so the rest of the draft is read
        # the same way; only quantity-shaped objects are touched.
        moved = migrate_quantity_values(quantities, "properties")
        moved.extend(migrate_quantity_values(fields))
        _warn_text_moved(path.name, moved)
        fields["properties"] = _filled_quantities(quantities, path)
        _merge_draft_alias(fields, "model_name", "model", path)
        comment = [*_draft_text_list(fields.pop("comment", None)), *_draft_text_list(fields.pop("notes", None))]
        if comment:
            fields["comment"] = comment
        fields["source"] = _draft_source(fields, default_type="datasheet", path=path)
        # An explicit identity in the draft pins a published cell spec, so a
        # corrected manufacturer, model, format or chemistry does not mint a new IRI.
        pinned = _draft_spec_iri(fields.pop("id", None), fields.pop("uid", None), path.name)
        if pinned is not None:
            fields["id"] = pinned
        missing = [key for key in ("manufacturer", "model", "format", "chemistry") if key not in fields]
        if missing:
            raise ValueError(
                f"{path.name}: fill in {', '.join(missing)} before loading a cell-spec draft. Nothing was loaded."
            )
        handle = fields.pop("handle", None)
        name = fields.pop("name", None)
        ct = CellSpec(**fields)
        if handle:
            ct.handle = handle
        # A draft's own title wins over the "<manufacturer> <model>" default. The
        # identity seed reads manufacturer and model, never the name, so a title
        # change does not move the IRI.
        if isinstance(name, str) and name.strip():
            ct.name = name.strip()
        # Loading the same draft again (a notebook cell run twice) reuses the
        # spec the session already holds.
        repeat = self._session_repeat(ct, self._ws.cell_specs, what=path.name)
        if repeat is not None:
            return repeat
        self._ws.cell_specs.append(ct)
        return ct

    def _load_from_result(self, result: dict) -> Any:
        """Reference an existing resource from a search result (never re-published)."""
        if result.get("type") == "cell":
            return self._reference_cell(result)
        return self._reference_spec(result)  # cell-spec (default)

    def _reference_cell(self, result: dict) -> Any:
        """Register an existing cell instance for test attachment, by reference.

        The cell is added to the matching index but NOT to the save set, so it is
        never re-saved or re-submitted — downstream tests just record its IRI.
        A cell this workspace does not hold is looked up in the registry and kept
        as a read-only reference copy, so the strict save resolves it.
        """
        from battinfo.bundle import Cell  # noqa: PLC0415

        # Loading the same result again (a notebook cell re-run) reuses the cell
        # already referenced; a second object would make its serial ambiguous.
        iri = result.get("id")
        known = next((cell for cell, _ in self._indexed_cells if iri and cell.id == iri), None)
        if known is not None:
            return known
        cell = Cell(
            id=iri,
            cell_spec_id=result.get("cell_spec_id"),
            name=result.get("name"),
            serial_number=result.get("serial_number"),
            batch_id=result.get("batch_id"),
        )
        self._index_cell(cell, result.get("serial_number"), result.get("name"))
        if cell.id:
            self._resolve_published_reference(cell.id, "cell")
        return cell

    # ── Published records referenced from this workspace ──────────────────────

    @property
    def _references_root(self) -> Path:
        """Read-only copies of the published records this workspace references.

        Written when a reference is resolved in the registry, read by save-time
        reference validation, and never saved over or submitted.
        """
        return self._root / ".battinfo" / "references"

    def _knows_record(self, iri: str, entity_type: str) -> bool:
        """True when *iri* is in this session, saved in this workspace, or kept as a copy."""
        sessions: dict[str, builtins.list[Any]] = {
            "cell": self._ws.cells,
            "cell-spec": self._ws.cell_specs,
            "test-protocol": self._ws.test_specs,
        }
        if any(getattr(obj, "id", None) == iri for obj in sessions.get(entity_type, [])):
            return True
        uid = iri.rstrip("/").rsplit("/", 1)[-1]
        if not is_dashed_uid(uid):
            return False  # no file is named after it
        for root in (self._ws.source_root, self._references_root):
            path = save_entity_path(entity_type, uid, root)
            try:
                if path.exists() and entity_id_from_doc(_read_json(path)) == iri:
                    return True
            except (OSError, ValueError):
                continue
        return False

    def _fetch_registry_record(self, iri: str, entity_type: str) -> tuple[dict | None, str]:
        """GET the published record behind *iri*: ``(canonical record or None, outcome)``.

        The outcome is ``found``, ``not_found`` (the registry does not hold it),
        ``unreachable``, or ``unreadable`` (its entry carries no canonical record).
        """
        import urllib.error  # noqa: PLC0415
        import urllib.request  # noqa: PLC0415

        uid = iri.rstrip("/").rsplit("/", 1)[-1]
        request = urllib.request.Request(
            f"{self._registry_url}/resources/{_REGISTRY_RESOURCE_TYPES[entity_type]}/{uid}",
            headers={"User-Agent": "battinfo-client/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=_REFERENCE_LOOKUP_TIMEOUT) as response:  # noqa: S310
                envelope = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return None, "not_found" if exc.code == 404 else "unreachable"
        except Exception:  # noqa: BLE001 - registry down or network blocked: degrade, never fail ws.add
            return None, "unreachable"
        record = _canonical_record_of(envelope, entity_type)
        if record is None or entity_id_from_doc(record) != iri:
            return None, "unreadable"
        return record, "found"

    def _keep_reference_copy(self, record: dict, entity_type: str) -> Path:
        """Write a read-only copy of a published record to ``.battinfo/references/<kind>/``.

        The file is named after the uid that ends the record's IRI. The record
        comes from a registry, so an IRI that does not end in a uid raises
        ``ValueError`` and nothing is written.
        """
        iri = entity_id_from_doc(record) or ""
        uid = iri.rstrip("/").rsplit("/", 1)[-1]
        if not is_dashed_uid(uid):
            raise ValueError(
                f"The registry returned a {entity_type} record whose IRI {iri!r} does not end in a "
                "record uid (such as pge5-wer6-2q82-v9k0), so it is not copied into this workspace."
            )
        path = save_entity_path(entity_type, uid, self._references_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(path, json.dumps(record, indent=2, ensure_ascii=False))
        return path

    def _resolve_published_reference(self, iri: str, entity_type: str) -> str:
        """Make a reference to a published record resolvable when ws.save() validates it.

        A record this workspace already holds needs nothing. Otherwise, with a
        registry configured, the published record is looked up and a read-only
        copy kept under ``.battinfo/references/``; offline, the reference cannot
        be checked and ws.save() reports it. Returns ``local``, ``copied``,
        ``offline``, ``not_found``, ``unreachable`` or ``unreadable``. Each record
        is looked up at most once per registry in a session: a later reference to
        it reuses the outcome, so a registry that is down costs one timeout, not
        one per test. A record found under an IRI that does not end in a uid
        raises ``ValueError`` (see ``_keep_reference_copy``).
        """
        if self._knows_record(iri, entity_type):
            return "local"
        registry = self._registry_url
        if not registry:
            print(f"  note: {iri} is not in this workspace and could not be checked offline (registry_url=None).")
            return "offline"
        remembered = self._reference_lookups.get((registry, entity_type, iri))
        if remembered is not None:
            return remembered
        record, outcome = self._fetch_registry_record(iri, entity_type)
        if record is not None:
            self._keep_reference_copy(record, entity_type)
            self._reference_lookups[(registry, entity_type, iri)] = "copied"
            return "copied"
        self._reference_lookups[(registry, entity_type, iri)] = outcome
        reason = {
            "not_found": f"was not found in the registry at {registry}",
            "unreachable": f"could not be looked up in the registry at {registry}",
            "unreadable": "has no canonical record in its registry entry",
        }[outcome]
        print(f"  WARNING: {iri} {reason}; ws.save() will report the reference as unresolved.")
        return outcome

    def _reference_spec(self, result: dict) -> Any:
        """Build a referenced CellSpec reusing its existing IRI (NOT queued to publish)."""
        from battinfo.bundle import CellSpec, ProvenanceInfo  # noqa: PLC0415

        record = self._fetch_cell_spec_record(result) if result.get("source") == "api" else result.get("_record", {})
        product = record.get("cell_spec", {}) or {}
        # A copy, so the reference copy kept below stays as published. A spec
        # saved before 0.8.0 may hold text in a quantity's value: it is read
        # into value_text (a numeric string into the number).
        specs_raw = copy.deepcopy(record.get("properties", {}) or {})
        _warn_text_moved(
            f"cell spec {result.get('id') or product.get('id') or ''}".strip(),
            migrate_quantity_values(specs_raw, "properties"),
        )
        specs = {
            k: v
            for k, v in specs_raw.items()
            if isinstance(v, dict) and any(v.get(field) is not None for field in _QUANTITY_VALUE_KEYS)
        }
        mfr = product.get("manufacturer") or {}
        mfr_name = mfr.get("name", "") if isinstance(mfr, dict) else str(mfr)
        ct = CellSpec(
            manufacturer=mfr_name or result.get("manufacturer", ""),
            model=product.get("model", "") or result.get("model", ""),
            format=product.get("cell_format") or product.get("format") or "",
            chemistry=product.get("chemistry", ""),
            positive_electrode_basis=product.get("positive_electrode_basis"),
            negative_electrode_basis=product.get("negative_electrode_basis"),
            size_code=product.get("size_code"),
            iec_code=product.get("iec_code"),
            country_of_origin=product.get("country_of_origin"),
            year=product.get("year"),
            properties=specs,
            source=ProvenanceInfo(type="registry"),
        )
        ct.id = result.get("id") or product.get("id")
        if ct.id:
            # Keep the fetched published record as a reference copy, so cells
            # authored against this spec resolve it when ws.save() validates them.
            if result.get("source") == "api" and entity_id_from_doc(record) == ct.id:
                if not self._knows_record(ct.id, "cell-spec"):
                    self._keep_reference_copy(record, "cell-spec")
            else:
                self._resolve_published_reference(ct.id, "cell-spec")
        return ct

    def _fetch_cell_spec_record(self, result: dict) -> dict:
        """Fetch the full cell-spec record from the registry API (empty dict on failure)."""
        import urllib.request  # noqa: PLC0415

        if not self._registry_url:
            return {}
        canonical_id = result.get("_canonical_id", "")
        url = f"{self._registry_url}/resources/cell_spec/{canonical_id}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
                data = json.loads(resp.read().decode())
        except Exception:
            return {}
        payload = data.get("semantic_payload") or {}
        return (payload.get("battinfo_records") or {}).get("cell_spec") or payload

    def _coerce_cell_spec_arg(self, spec: Any) -> Any:
        """Accept a ``ws.search()`` hit, a ``CellSpec``, or an authoring dict for ``spec=``.

        Search hits carry index metadata (``_canonical_id``, ``type``, ``source``),
        not authoring fields — feeding one straight into the model trips the
        unknown-kwarg check. Resolve hits through ``_reference_spec`` (reusing the
        existing IRI, never re-published); pass everything else to the model,
        whose validation errors teach.
        """
        from battinfo.bundle import CellSpec  # noqa: PLC0415

        if isinstance(spec, dict):
            if "_canonical_id" in spec or "type" in spec:
                return self._reference_spec(dict(spec))
            spec = CellSpec(**spec)  # authoring dict — model errors teach
        if isinstance(spec, CellSpec):
            # A NEW spec (no id yet) must join the save set, or the instances
            # would reference a spec that never gets saved and fail at save
            # time with an obscure error. IRI is minted at ws.save(). A new
            # object equal to a spec the session already holds (the cell that
            # builds it run again) is not added twice: the cells link the held one.
            if spec.id is None and not any(existing is spec for existing in self._ws.cell_specs):
                repeat = self._session_repeat(spec, self._ws.cell_specs, what="cell spec", note=False)
                if repeat is not None:
                    return repeat
                self._ws.cell_specs.append(spec)
            return spec
        if isinstance(spec, str):
            raise TypeError(
                f"spec= takes a ws.search() hit or a battinfo.CellSpec, not the string {spec!r}. "
                f"Try: spec = ws.search({spec!r})[0]"
            )
        return spec

    def _add_cell_instances(
        self,
        spec: Any,
        from_file: str | Path | None = None,
        match: str | None = None,
        iris: builtins.list[str] | None = None,
        names: builtins.list[str] | None = None,
        serial_numbers: builtins.list[str] | None = None,
        handles: builtins.list[str | None] | None = None,
        grade: str | None = None,
        production_date: int | str | None = None,
        expiration_date: int | str | None = None,
        conformance: Any = None,
        working_electrode_id: Any = None,
        counter_electrode_id: Any = None,
    ) -> builtins.list:
        """Create cell instances, and return the cells the call names.

        The cells come back in the order given. A serial number (or, for a
        cell without one, a name) the workspace already holds a cell under
        returns that cell instead of adding another, so running the same call
        again returns the same cells and adds nothing.

        * ``names`` — human labels (e.g. lab batch IDs); display text, which
          several cells of one batch may share.
        * ``serial_numbers`` — manufacturer serials (optional); parallel to ``names``
          when both are given. The serial is the cell's identity: it de-duplicates
          the batch and must be unique within it.
        * ``iris`` — pre-allocated IRIs to reuse instead of minting (parallel, equal length).
          Use it to pin a published identity when the display name changes.
        * ``handles`` — one handle per cell (parallel, equal length; ``None`` skips
          one). A handle is a short slug, see :mod:`battinfo.naming`; it is never
          generated for you.
        * ``from_file`` — JSON file mapping ``{name: pre-allocated-IRI}``.
        * ``working_electrode_id`` / ``counter_electrode_id`` — the ``electrode``
          record each cell was built from. One IRI applies to every cell (a batch
          of cells punched from one coated web); a list assigns them one per cell,
          in the order the cells are created, for the case where each cell got its
          own disc. Same one-or-parallel shape as ``conformance``.
        """
        spec = self._coerce_cell_spec_arg(spec)
        # Build (name, serial, iri, handle) entries.
        entries: list[tuple[str | None, str | None, str | None, str | None]] = []

        if from_file is not None:
            if handles is not None:
                raise ValueError("handles= needs names= or serial_numbers= (it is parallel to them), not from_file=.")
            fp = Path(from_file)
            if not fp.is_absolute():
                fp = self._root / fp
            raw = json.loads(fp.read_text(encoding="utf-8"))
            items = {k: v for k, v in raw.items() if not k.startswith("_") and v}
            if match:
                items = {k: v for k, v in items.items() if match.lower() in k.lower()}
            entries = [(label, None, iri, None) for label, iri in items.items()]
        else:
            pairs: list[tuple[str | None, str | None]]
            if names is not None and serial_numbers is not None:
                if len(names) != len(serial_numbers):
                    raise ValueError(
                        f"names and serial_numbers must have the same length ({len(names)} vs {len(serial_numbers)})."
                    )
                pairs = list(zip(names, serial_numbers))
            elif names is not None:
                pairs = [(n, None) for n in names]
            elif serial_numbers is not None:
                pairs = [(None, s) for s in serial_numbers]
            else:
                print("  No cell instances to add (pass names=[...] or serial_numbers=[...]).")
                return []

            if iris is not None and len(iris) != len(pairs):
                raise ValueError(f"iris must match the number of cells ({len(iris)} IRIs vs {len(pairs)} cells).")
            if handles is not None and len(handles) != len(pairs):
                raise ValueError(
                    f"handles must match the number of cells ({len(handles)} handles vs {len(pairs)} cells)."
                )
            iri_list = builtins.list(iris) if iris is not None else [None] * len(pairs)
            handle_list = builtins.list(handles) if handles is not None else [None] * len(pairs)
            entries = [(n, s, iri, h) for (n, s), iri, h in zip(pairs, iri_list, handle_list)]

        # Drop cells already in this session, keyed on IDENTITY, so the same call
        # run twice (a notebook cell re-run) adds nothing. A from_file= map is
        # keyed on its labels, the names its cells are indexed under.
        #
        # A cell instance is identified by its serial number. The name is
        # display text: a batch may legitimately share one public label
        # across many physical cells (95 cells under 12 labels is a real
        # shape), so keying the de-duplication on the label collapsed such a
        # batch to one cell per label and lost the rest without failing.
        # Prefer the serial; fall back to the name only when no serial is
        # supplied, which is the single-label case the old key served.
        seen: dict[str, str | None] = {}
        already: list[str] = []
        repeated_serials: list[str] = []
        repeated_names: list[str] = []
        deduped: list[tuple[str | None, str | None, str | None, str | None]] = []
        # What the call returns, in input order: a cell the workspace already
        # holds, or the place of a cell about to be made in `deduped`.
        returned: list[Any] = []
        for n, s, iri, h in entries:
            key = s or n or ""
            if key and key in seen:
                # Two entries claiming one identity. A repeated serial is a
                # contradiction in the input (loud); a repeated bare name is
                # merely indistinguishable (warn and keep the first).
                (repeated_serials if s else repeated_names).append(key)
                continue
            held = next((cell for cell, labels in self._indexed_cells if key and key in labels), None)
            if held is not None:
                already.append(key)
                returned.append(held)
                continue
            if key:
                seen[key] = n
            returned.append(len(deduped))
            deduped.append((n, s, iri, h))
        if repeated_serials:
            dupes = sorted(set(repeated_serials))
            raise ValueError(
                f"serial_numbers contains {len(repeated_serials)} repeated serial(s): "
                f"{dupes[:5]}" + (" ..." if len(dupes) > 5 else "") + ". "
                "A serial number identifies one physical cell, so it cannot appear "
                "twice in one batch. Names may repeat; serials may not."
            )
        if repeated_names:
            dupes = sorted(set(repeated_names))
            print(
                f"  WARNING: {len(repeated_names)} repeated name(s) with no serial "
                f"-- keeping the first of each: {dupes[:5]}"
                + (" ..." if len(dupes) > 5 else "")
                + "\n           Pass serial_numbers=[...] to author them as distinct cells."
            )
        if already:
            print(
                f"  {len(already)} already in this workspace, reusing them: {already[:5]}"
                + (" ..." if len(already) > 5 else "")
            )
        entries = deduped
        self._refuse_shared_cell_iris(entries)

        if not entries:
            if not already:
                print("  No cell instances to add" + (f" (match={match!r})." if match else "."))
            return returned

        # NOTE: spec nominal ratings are deliberately NOT copied into each
        # instance's `measured` block. Rated/nominal values are not
        # measurements — auto-copying them fabricated per-cell "measurement"
        # provenance for values nobody measured. The spec's ratings stay on
        # the spec record, which every instance already references via
        # cell_spec_id; genuine measurements arrive via measured=... on
        # ws.cell()/Cell or from test data.

        # Conformance (vs the cell spec): one value applied to all, or a parallel list.
        if isinstance(conformance, (list, tuple)):
            if len(conformance) != len(entries):
                raise ValueError(
                    f"conformance list must match the number of cells ({len(conformance)} vs {len(entries)})."
                )
            confs = [_coerce_conformance(c) for c in conformance]
        else:
            confs = [_coerce_conformance(conformance)] * len(entries)

        # Electrode links: one IRI shared by the batch, or one per cell. A list of
        # the wrong length is a silent mis-assignment of physical parts to physical
        # cells, so it is refused rather than zipped short.
        def _per_cell(value: Any, label: str) -> builtins.list[Any]:
            if isinstance(value, (builtins.list, tuple)):
                if len(value) != len(entries):
                    raise ValueError(f"{label} list must match the number of cells ({len(value)} vs {len(entries)}).")
                return builtins.list(value)
            return [value] * len(entries)

        working_ids = _per_cell(working_electrode_id, "working_electrode_id")
        counter_ids = _per_cell(counter_electrode_id, "counter_electrode_id")

        cells = []
        for (name, serial, iri, cell_handle), conf, working_id, counter_id in zip(
            entries, confs, working_ids, counter_ids
        ):
            cell = self._ws.cell(
                spec,
                name=name,
                serial_number=serial,
                grade=grade,
                manufactured_at=production_date,
                expires_at=expiration_date,
                conformance=conf,
                working_electrode_id=working_id,
                counter_electrode_id=counter_id,
            )
            if iri is not None:
                cell.id = iri
            if cell_handle is not None:
                cell.handle = cell_handle
            # Index by both the serial and the name (and their short IDs) for
            # matching. The serial goes first so it wins the identity slot; a
            # name shared by several cells is flagged ambiguous, not overwritten.
            self._index_cell(cell, serial, name)
            cells.append(cell)
            print(f"  cell: {name or serial}  {iri or '(IRI auto-assigned)'}")
        return [cells[item] if isinstance(item, int) else item for item in returned]

    def _refuse_shared_cell_iris(
        self, entries: builtins.list[tuple[str | None, str | None, str | None, str | None]]
    ) -> None:
        """Raise ``ValueError`` when two new cells pin one IRI, or one pins the IRI of a cell this session saves.

        *entries* are the ``(name, serial, iri, handle)`` of the cells about to
        be made. One IRI names one cell. A cell the session only references
        (rehydrated from disk or found in the registry) is not in the save set,
        so pinning its IRI on a renamed cell is allowed: the save rewrites it.
        """
        pinned = [iri for _, _, iri, _ in entries if iri]
        repeated = sorted({iri for iri in pinned if pinned.count(iri) > 1})
        if repeated:
            raise ValueError(
                f"{repeated[0]} is given to more than one cell; one IRI names one cell. Nothing was added."
            )
        for name, serial, iri, _ in entries:
            holder = next((cell for cell in self._ws.cells if iri and cell.id == iri), None)
            if holder is not None:
                held_by = holder.serial_number or holder.name or iri
                raise ValueError(
                    f"{iri} is already the IRI of cell {held_by!r} in this session, so it cannot also name "
                    f"{serial or name!r}; one IRI names one cell. Nothing was added."
                )

    def _load_test_spec(self, path: Path) -> Any:
        from battinfo.bundle import BatteryTestType, ProvenanceInfo  # noqa: PLC0415

        raw = json.loads(path.read_text(encoding="utf-8"))
        # Keys starting with "_" are in-file comments written by ws.template()
        # (e.g. _allowed_types, _steps_help) — never record content.
        raw = {k: v for k, v in raw.items() if not str(k).startswith("_")}
        if "termination_criteria" in raw:
            # Older drafts stated a protocol-level cutoff here. It has no faithful
            # home without knowing which step ends at it, so say where it goes.
            raise ValueError(
                f"{path.name}: 'termination_criteria' is an older draft key that is no longer "
                "read, and it was not loaded. State a cutoff in the step that ends at it, for "
                'example "steps": ["Discharge at C/5 until 0.9 V"], or as a structured '
                '"termination" on a "method" step: {"quantity": "voltage", "value": 0.9, '
                '"unit": "V", "direction": "below"}. Nothing was loaded.'
            )
        _check_draft_keys(raw, _test_spec_draft_keys(), draft="test-spec", path=path, aliases=_TEST_SPEC_DRAFT_ALIASES)

        allowed_types = [t.value for t in BatteryTestType]
        spellings = {key: raw[key] for key in ("type", "kind", "test_type", "test_kind") if raw.get(key)}
        if len(set(spellings.values())) > 1:
            raise ValueError(
                f"{path.name}: {' and '.join(repr(key) for key in spellings)} name different "
                "test types; keep one. Nothing was loaded."
            )
        test_type = next(iter(spellings.values()), "")
        if not test_type:
            raise ValueError(f"{path.name}: fill in 'type' before loading. Allowed values: {', '.join(allowed_types)}.")
        if test_type not in allowed_types:
            raise ValueError(f"{path.name}: unknown type {test_type!r}. Allowed values: {', '.join(allowed_types)}.")

        conditions, condition_notes = _clean_template_conditions(raw.get("conditions"))
        steps = _clean_template_steps(raw.get("experiment") or raw.get("steps"))

        # The protocol followed: the record keeps its URL (protocol_url) but has no
        # field for its name, so a named protocol is kept as a note.
        protocol = raw.get("protocol")
        if protocol is not None and not isinstance(protocol, (str, Mapping)):
            raise ValueError(
                f"{path.name}: 'protocol' must be the protocol's name or an object with "
                "'name' and 'url'. Nothing was loaded."
            )
        protocol_info = {"name": protocol} if isinstance(protocol, str) else dict(protocol or {})
        unknown = sorted(set(protocol_info) - {"name", "url"})
        if unknown:
            raise ValueError(
                f"{path.name}: 'protocol' takes 'name' and 'url', not "
                f"{', '.join(map(repr, unknown))}. Nothing was loaded."
            )
        if raw.get("protocol_url") is not None:
            if protocol_info.get("url") not in (None, raw["protocol_url"]):
                raise ValueError(
                    f"{path.name}: 'protocol_url' and 'protocol.url' disagree; keep one. Nothing was loaded."
                )
            protocol_info["url"] = raw["protocol_url"]

        # The record's own comment (or notes) first. Fields with no structured home
        # on a test spec are kept as notes rather than silently dropped (instrument
        # belongs on the test run; atmosphere has no numeric quantity form).
        notes = [*_draft_text_list(raw.get("comment")), *_draft_text_list(raw.get("notes"))]
        for label, value in (
            ("instrument", raw.get("instrument")),
            ("atmosphere", raw.get("atmosphere")),
            ("protocol", protocol_info.get("name")),
        ):
            if isinstance(value, str) and value.strip():
                notes.append(f"{label}: {value.strip()}")
        notes.extend(condition_notes)
        source = ProvenanceInfo(**_draft_source(dict(raw), default_type="manual", path=path))
        # An explicit identity in the draft pins a published test spec, so a
        # corrected name does not mint a new IRI (the seed includes the name).
        pinned = _draft_spec_iri(raw.get("id"), raw.get("uid"), path.name)

        # Forward the authored method so it survives into the saved record (and
        # thence the published JSON-LD as an EMMO process graph). Humans author the
        # PyBaMM-style `experiment`/`steps` strings; a pre-built structured `method`
        # is also accepted. Protocol-level record/safety/conditions/artifacts pass through.
        tp = self._ws.test_protocol(
            name=raw.get("name", ""),
            type=test_type,
            description=raw.get("description"),
            experiment=steps,
            cycles=raw.get("cycles"),
            method=raw.get("method"),
            version=raw.get("version"),
            protocol_url=protocol_info.get("url"),
            conditions=conditions,
            record=raw.get("record"),
            safety=raw.get("safety"),
            artifacts=raw.get("artifacts"),
            comment=notes or None,
        )
        tp.source = source
        if pinned is not None:
            tp.id = pinned
        if raw.get("handle"):
            tp.handle = raw["handle"]
        # Held back until it is known to be new: loading the same draft again
        # reuses the spec the session already holds.
        self._discard(tp)
        repeat = self._session_repeat(tp, self._ws.test_specs, what=path.name)
        if repeat is not None:
            return repeat
        self._ws.test_specs.append(tp)
        return tp

    def _load_equipment_spec(self, path: Path) -> dict:
        """Lift an equipment-spec draft (from ``ws.template``) to a canonical record.

        The uid is minted deterministically from the draft's natural key
        (manufacturer :: model :: name, each normalised by
        ``entities.seed_text``), so re-loading the same draft converges on the
        same spec IRI instead of minting a duplicate. An ``id`` or ``uid`` in
        the draft pins the IRI instead.
        """
        from battinfo.api import create_equipment_spec  # noqa: PLC0415
        from battinfo.entities import seed_text, stable_uid  # noqa: PLC0415

        raw = json.loads(path.read_text(encoding="utf-8"))
        _check_draft_keys(raw, _EQUIPMENT_SPEC_DRAFT_KEYS, draft="equipment-spec", path=path)
        name = raw.get("name") or ""
        manufacturer = raw.get("manufacturer") or None
        model = raw.get("model") or None
        if not (name or manufacturer or model):
            raise ValueError(
                f"{path.name} needs at least a name (or manufacturer/model) - fill in the template before loading it."
            )
        pinned = _draft_spec_iri(raw.get("id"), raw.get("uid"), path.name)
        uid = (
            None
            if pinned
            else stable_uid("::".join(["equipment-spec", seed_text(manufacturer), seed_text(model), seed_text(name)]))
        )
        # A draft written before 0.8.0 may hold text in a quantity's value: a
        # numeric string becomes the number, other text moves to value_text.
        # The whole draft is read, so a quantity outside `property` is covered too.
        _warn_text_moved(path.name, migrate_quantity_values(raw))
        # Drop template placeholders (null quantity fields) so the record stays valid.
        props: dict[str, dict] = {}
        for key, value in (raw.get("property") or {}).items():
            if not isinstance(value, dict):
                continue
            cleaned = {f: fv for f, fv in value.items() if fv is not None}
            if any(f in cleaned for f in ("value", "min_value", "max_value", "typical_value", "value_text")):
                props[key] = cleaned
        chemistries = [c for c in (raw.get("supported_chemistries") or []) if c]
        record = create_equipment_spec(
            uid=uid,
            id=pinned,
            name=name or " ".join(p for p in (manufacturer, model) if p),
            handle=raw.get("handle") or None,
            equipment_class=raw.get("equipment_class"),
            model=model,
            channel_count=raw.get("channel_count"),
            supported_chemistries=chemistries or None,
            property=props or None,
            manufacturer=manufacturer,
            supplier=raw.get("supplier"),
            product_id=raw.get("product_id"),
            comment=raw.get("comment"),
            source_type=raw.get("source_type") or "datasheet",
            source_name=raw.get("source_name"),
            source_file=raw.get("source_file"),
            source_url=raw.get("source_url"),
            citation=raw.get("citation"),
            retrieved_at=raw.get("retrieved_at"),
            notes=_draft_text_list(raw.get("notes")) or None,
        )
        body = record["equipment_spec"]
        print(f"  equipment-spec: {body['name']}  {body['id']}")
        return record

    def _resolve_equipment_spec_arg(self, spec: Any) -> tuple[dict, Path | None, builtins.list[str]]:
        """Resolve ``spec=`` for ``ws.add('equipment', ...)`` to a canonical record.

        Accepts a canonical equipment-spec record dict, a path to one (a
        template draft is also accepted and lifted like ``ws.load`` would), or
        the IRI of a spec already saved in this workspace's records tree.

        Returns the record, the file it was read from (None for a dict or a
        draft) and the notes ``migrate_quantity_values`` gave on it. A record
        saved before 0.8.0 may hold text in a quantity's value: it comes back
        with a numeric string as the number and other text in ``value_text``,
        and the caller warns with the notes. A dict passed in is copied, never
        changed. A draft is migrated and warned about by ``_load_equipment_spec``.
        """
        if isinstance(spec, dict):
            if isinstance(spec.get("equipment_spec"), dict):
                doc = copy.deepcopy(spec)
                return doc, None, migrate_quantity_values(doc)
            raise TypeError(
                "spec= must be a canonical equipment-spec record (a dict with an "
                "'equipment_spec' key), a path to one, or its IRI. Author one with "
                "ws.template('equipment-spec', ...) then ws.load(<draft file>)."
            )
        if isinstance(spec, str) and spec.startswith("http"):
            spec_dir = self._ws.source_root / "equipment-spec"
            for path in sorted(spec_dir.glob("*.json")) if spec_dir.exists() else []:
                try:
                    doc = _read_json(path)
                except (OSError, ValueError):
                    continue
                body = doc.get("equipment_spec") or {}
                if body.get("id") == spec:
                    return doc, path, migrate_quantity_values(doc)
            raise ValueError(
                f"No equipment-spec record with id {spec!r} in this workspace. "
                "Pass the record dict (or a path to it) instead - "
                "ws.add('equipment', ...) saves it for you."
            )
        if isinstance(spec, (str, Path)):
            path = Path(spec) if not isinstance(spec, Path) else spec
            if not path.is_absolute():
                path = self._root / path
            if not path.exists():
                raise FileNotFoundError(f"equipment-spec file not found: {path}")
            doc = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(doc.get("equipment_spec"), dict):
                return doc, path, migrate_quantity_values(doc)
            # A template draft (no canonical envelope): lift it like ws.load would.
            return self._load_equipment_spec(path), None, []
        raise TypeError(
            "spec= must be a canonical equipment-spec record dict, a path to one, "
            "or its IRI (https://w3id.org/battinfo/spec/...)."
        )

    def _add_equipment(
        self,
        spec: Any = None,
        *,
        serial_number: str | None = None,
        name: str | None = None,
        handle: str | None = None,
        location: str | None = None,
        status: str = "active",
        channels: int | None = None,
        commissioned_at: int | str | None = None,
    ) -> builtins.list:
        """Register a physical equipment unit and its channels (saved immediately).

        Saves the spec record into the workspace records tree if it is new,
        then creates the equipment record and N channel records (N =
        ``channels=`` or the spec's ``channel_count``) via the same canonical
        ``save_record`` path the api builders use (the entities registry picks
        the subdir/namespace per kind). Idempotent: the equipment uid is minted
        deterministically from (spec uid, serial_number) and channel uids from
        (equipment uid, index), so re-running with the same inputs converges on
        the same records instead of duplicating them.
        """
        from battinfo.api import create_channel, create_equipment, save_record  # noqa: PLC0415
        from battinfo.entities import seed_text, stable_uid  # noqa: PLC0415

        if spec is None:
            raise ValueError(
                "ws.add('equipment', ...) needs spec=<equipment-spec record, path, or IRI>. "
                "Author one with ws.template('equipment-spec', ...) + ws.load(<draft file>)."
            )
        if not serial_number:
            raise ValueError(
                "ws.add('equipment', ...) needs serial_number=... - it is the unit's "
                "stable identity (the equipment IRI is minted from spec uid + serial number)."
            )
        spec_record, spec_read_from, spec_moved = self._resolve_equipment_spec_arg(spec)
        spec_body = spec_record["equipment_spec"]
        spec_id = spec_body["id"]
        spec_uid = spec_id.rsplit("/", 1)[-1]

        n_channels = channels if channels is not None else spec_body.get("channel_count")
        if n_channels is None:
            raise ValueError(
                f"{spec_body.get('name', 'this equipment-spec')!r} has no channel_count - "
                "pass channels=<N> to say how many channels this unit has."
            )
        if isinstance(n_channels, bool) or not isinstance(n_channels, int) or n_channels < 0:
            raise ValueError(f"channels must be a non-negative integer (got {n_channels!r}).")

        source_root = self._ws.source_root

        def _track(result: dict) -> dict:
            # Equipment records are written at add() time, not by ws.save(), so
            # register them in the session set here, and in _added_paths, which
            # ws.save() starts the session set from. Otherwise a later
            # ws.submit() or ws.publish() in the same session would not select them.
            path = result.get("path")
            if path:
                self._session_paths.add(Path(path))
                self._added_paths.add(Path(path))
            return result

        spec_result = _track(save_record(spec_record, source_root=source_root, mode="upsert"))
        # Text read out of the spec is reported once. When spec= named the
        # saved copy itself (by IRI or path), the upsert finds that file
        # unchanged, rewrites it and warns with the same notes.
        rewrote_the_source = (
            spec_read_from is not None
            and not spec_result.get("content_changed")
            and Path(spec_result["path"]).resolve() == spec_read_from.resolve()
        )
        if not rewrote_the_source:
            _warn_text_moved(spec_read_from.name if spec_read_from else f"equipment spec {spec_id}", spec_moved)

        # Deterministic equipment identity: the same (spec, serial_number) always
        # mints the same equipment IRI - the seed mirrors the ratified channel
        # seed "channel:{equipment_uid}:{index}" - so re-running
        # ws.add('equipment', ...) with the same inputs converges on the existing
        # unit instead of minting a duplicate. Chosen over random minting because
        # a physical unit's natural key IS its model + serial number.
        equipment_uid = stable_uid(f"equipment:{spec_uid}:{seed_text(serial_number)}")
        equipment_record = create_equipment(
            uid=equipment_uid,
            equipment_spec_id=spec_id,
            serial_number=serial_number,
            name=name,
            handle=handle,
            location=location,
            status=status,
            commissioned_at=commissioned_at,
        )
        _track(save_record(equipment_record, source_root=source_root, mode="upsert"))
        equipment_id = equipment_record["equipment"]["id"]

        unit_label = name or serial_number
        channel_records = []
        for index in range(1, n_channels + 1):
            channel_record = create_channel(
                equipment_id=equipment_id,
                index=index,
                label=f"{unit_label}/CH{index}",
            )
            _track(save_record(channel_record, source_root=source_root, mode="upsert"))
            self._register_channel_keys(channel_record["channel"], equipment_record["equipment"])
            channel_records.append(channel_record)

        spec_label = spec_body.get("name") or spec_body.get("model") or spec_id
        print(f"  equipment-spec: {spec_label}  [{spec_result.get('status', '')}]")
        print(f"  equipment:      {unit_label}  {equipment_id}")
        if n_channels:
            print(f"  channels:       {n_channels} registered  ({unit_label}/CH1 .. {unit_label}/CH{n_channels})")
            print(f"\n  Next: ws.add('test', ..., channel='{unit_label}/CH1') to attach a test.")
        return [equipment_record, *channel_records]

    def _add_material_spec(self, name: str | None = None, **kwargs) -> builtins.list:
        """Author a first-class material spec (Level 2), queued for ws.save().

        ``ws.add("material_spec", name="Targray NMC811", kind="nmc811",
        manufacturer="Targray", grade="grade X", property={...})``

        The IRI is content-derived from (manufacturer, product, grade): re-adding
        the same product is a no-op, never a duplicate. ``kind`` is required and
        resolved against the curated vocabulary (aliases welcome); an unknown kind
        raises listing the valid keys. Attribution (contributor/license/funding)
        is stamped onto the record by ws.save, like every other record type.
        """
        from battinfo.api import create_material_spec  # noqa: PLC0415

        if not name and not kwargs.get("id") and not kwargs.get("uid"):
            raise ValueError(
                "ws.add('material_spec', ...) needs name=... (and kind=...). "
                "Example: ws.add('material_spec', name='LFP', kind='lfp')."
            )
        record = create_material_spec(validate=False, name=name, **kwargs)
        self._material_specs = _dedupe_records_by_id(self._material_specs, record, "material_spec")
        body = record["material_spec"]
        self._register_material_spec_keys(body)
        kind = body.get("kind", "")
        print(f"  material-spec:  {body.get('name', name)}  [{kind}]  {body['id']}")
        return [record]

    def _register_material_spec_keys(self, spec_body: dict) -> None:
        """Index a material spec under every reference form ``spec=`` accepts."""
        spec_id = spec_body.get("id")
        if not spec_id:
            return
        self._material_specs_by_ref[spec_id] = spec_body
        for key in (spec_body.get("name"), spec_body.get("short_id"), spec_body.get("product_id")):
            if isinstance(key, str) and key.strip():
                self._material_specs_by_ref[key.strip().lower()] = spec_body

    def _resolve_material_spec_arg(self, spec: Any) -> str:
        """Resolve ``spec=`` for ws.add('material', ...) to a material_spec IRI."""
        if isinstance(spec, dict) and isinstance(spec.get("material_spec"), dict):
            body = spec["material_spec"]
            self._register_material_spec_keys(body)
            return body["id"]
        if isinstance(spec, str) and spec.strip():
            text = spec.strip()
            if text.startswith(BATTINFO_ROOT):
                return text
            found = self._material_specs_by_ref.get(text.lower())
            if found is not None:
                return found["id"]
            raise ValueError(
                f"Unknown material spec {spec!r}. Pass a material_spec IRI, the record "
                "from ws.add('material_spec', ...), or a name added in this session."
            )
        raise ValueError("ws.add('material', ...) needs spec=<material-spec record, IRI, or name>.")

    def _add_material(self, spec: Any = None, *, lot: str | None = None, **kwargs) -> builtins.list:
        """Author a first-class material instance (Level 3), queued for ws.save().

        ``ws.add("material", spec=nmc811_spec, lot="LOT-2026-04",
        processing={"route": "nmp", "solvent": "NMP"}, storage="dry room")``

        Links a material spec (required), carries the lot/batch, dates, amount,
        storage, an instance-level ``processing`` block (aqueous vs NMP lives
        here, never on the spec), and an OPEN property block for as-received
        measurements. The IRI is content-derived from (spec_id, lot).
        """
        from battinfo.api import create_material  # noqa: PLC0415

        spec_id = self._resolve_material_spec_arg(spec)
        record = create_material(validate=False, material_spec_id=spec_id, lot=lot, **kwargs)
        self._materials = _dedupe_records_by_id(self._materials, record, "material")
        body = record["material"]
        label = body.get("lot_id") or body.get("name") or body["id"].rsplit("/", 1)[-1]
        print(f"  material:       {label}  {body['id']}")
        return [record]

    def _add_parameter_set(
        self,
        name: str | None = None,
        *,
        material: Any = None,
        record: Mapping[str, Any] | None = None,
        **kwargs,
    ) -> builtins.list:
        """Collate parameter claims from one source about one target, queued for ws.save().

        ``ws.add("parameter_set", name="Chen 2020 - graphite", material="graphite",
        citation_doi="10.1149/1945-7111/ab9050", default_provenance_class="fitted",
        claims=[{"parameter": "particle_radius",
                 "quantity": {"value": 5.86e-6, "unit": "m"}}, ...])``

        ``material=`` resolves ergonomically: a curated material-kind key or alias
        ("graphite", "NMC 811") targets the generic chemistry; a material-spec
        record, IRI, or a name added in this session targets that product. Pass
        ``cell_spec_id=`` instead for cell-level fitted sets. One source = one
        record; the IRI derives from (target, scope, name), so re-adding the same
        source is a no-op, never a duplicate.

        ``record=`` queues a parameter-set record built elsewhere instead, of
        either flavour: a claim batch, or the record of a BPX file from
        ``from_bpx_parameters(...).to_parameter_set(...)``. ``ws.save()``
        validates it like any other record and ``ws.submit()`` sends it under
        the publisher policy, which refuses a parameter file without its
        source file. Re-adding a record with the same IRI replaces it.
        """
        from battinfo.api import create_parameter_set  # noqa: PLC0415
        from battinfo.materials import resolve_material_kind  # noqa: PLC0415

        if record is not None:
            if name is not None or material is not None or kwargs:
                given = [k for k, v in (("name", name), ("material", material)) if v is not None]
                raise ValueError(
                    "ws.add('parameter_set', record=...) takes the record alone; it already holds "
                    f"its name, target and claims (got {', '.join([*given, *kwargs])} too)."
                )
            if not isinstance(record, Mapping) or not isinstance(record.get("parameter_set"), Mapping):
                raise TypeError(
                    "record= is a parameter-set record, a dict with a 'parameter_set' body (for "
                    "a BPX file: from_bpx_parameters(path).to_parameter_set(...))."
                )
            queued = copy.deepcopy(dict(record))
            if not isinstance(queued["parameter_set"].get("id"), str):
                raise ValueError("record= has no parameter_set.id; build it with create_parameter_set.")
            return self._queue_parameter_set(queued, name)

        if not name:
            raise ValueError(
                "ws.add('parameter_set', ...) needs name=... (convention: "
                "'<source> - <target>'), a target (material=... or cell_spec_id=...), "
                "and claims=[...]."
            )
        if material is not None:
            if any(kwargs.get(f) for f in ("material_kind", "material_spec_id", "cell_spec_id")):
                raise ValueError(
                    "pass either material=... or an explicit target "
                    "(material_kind/material_spec_id/cell_spec_id), not both."
                )
            kind = resolve_material_kind(material) if isinstance(material, str) else None
            if kind is not None:
                kwargs["material_kind"] = kind
            else:
                kwargs["material_spec_id"] = self._resolve_material_spec_arg(material)
        built = create_parameter_set(validate=False, name=name, **kwargs)
        return self._queue_parameter_set(built, name)

    def _queue_parameter_set(self, record: dict, name: str | None) -> builtins.list:
        """Queue a parameter-set record for ws.save(), replacing one with the same IRI."""
        self._parameter_sets = _dedupe_records_by_id(self._parameter_sets, record, "parameter_set")
        body = record["parameter_set"]
        target = (
            body.get("material_kind")
            or body.get("material_spec_id")
            or body.get("cell_spec_id")
            or body.get("cell_instance_id")
            or ("virtual cell" if body.get("virtual_cell") else "?")
        )
        n_claims = len(body.get("claims", [])) + sum(len(part.get("claims", [])) for part in body.get("parts", []))
        print(f"  param set:      {body.get('name', name)}  [{target}, {n_claims} claim(s)]  {body['id']}")
        return [record]

    def _add_electrode_spec(self, name: str | None = None, **kwargs) -> builtins.list:
        """Author a first-class electrode spec (the designed electrode), queued for ws.save().

        ``ws.add("electrode_spec", name="Si-Gr anode (aqueous)", kind="silicon_graphite",
        manufacturer="SINTEF", composition={"active": 0.90, "binder": {"name": "CMC", "fraction": 0.05},
        "additive": {"name": "Carbon black", "fraction": 0.05}},
        processing={"route": "aqueous", "solvent": "water"},
        current_collector={"name": "Copper foil", "thickness": {"value": 10, "unit": "um"}},
        property={"loading": {"value": 6.2, "unit": "mg/cm2"}})``

        ``kind`` names the ACTIVE material and is required — that is what makes a
        purchased electrode with unknown powder still describable and comparable.
        ``active_material_spec_id`` is optional and links the powder record when
        it exists. The IRI is content-derived from (producer, product, grade,
        kind, processing route): re-adding the same design is a no-op, while an
        aqueous and an NMP version of the same recipe are two specs, as they
        should be. Attribution is stamped by ws.save like every other record.
        """
        from battinfo.api import create_electrode_spec  # noqa: PLC0415

        if not name and not kwargs.get("id") and not kwargs.get("uid"):
            raise ValueError(
                "ws.add('electrode_spec', ...) needs name=... (and kind=...). Example: "
                "ws.add('electrode_spec', name='Graphite anode', kind='graphite')."
            )
        record = create_electrode_spec(validate=False, name=name, **kwargs)
        self._electrode_specs = _dedupe_records_by_id(self._electrode_specs, record, "electrode_spec")
        body = record["electrode_spec"]
        self._register_electrode_spec_keys(body)
        kind = body.get("kind", "")
        route = (body.get("processing") or {}).get("route")
        label = f"{kind}/{route}" if route else kind
        print(f"  electrode-spec: {body.get('name', name)}  [{label}]  {body['id']}")
        return [record]

    def _register_electrode_spec_keys(self, spec_body: dict) -> None:
        """Index an electrode spec under every reference form ``spec=`` accepts."""
        spec_id = spec_body.get("id")
        if not spec_id:
            return
        self._electrode_specs_by_ref[spec_id] = spec_body
        for key in (spec_body.get("name"), spec_body.get("short_id"), spec_body.get("product_id")):
            if isinstance(key, str) and key.strip():
                self._electrode_specs_by_ref[key.strip().lower()] = spec_body

    def _resolve_electrode_spec_arg(self, spec: Any) -> str:
        """Resolve ``spec=`` for ws.add('electrode', ...) to an electrode_spec IRI."""
        if isinstance(spec, dict) and isinstance(spec.get("electrode_spec"), dict):
            body = spec["electrode_spec"]
            self._register_electrode_spec_keys(body)
            return str(body["id"])
        if isinstance(spec, str) and spec.strip():
            text = spec.strip()
            if text.startswith(BATTINFO_ROOT):
                return text
            found = self._electrode_specs_by_ref.get(text.lower())
            if found is not None:
                return str(found["id"])
            raise ValueError(
                f"Unknown electrode spec {spec!r}. Pass an electrode_spec IRI, the record "
                "from ws.add('electrode_spec', ...), or a name added in this session."
            )
        raise ValueError("ws.add('electrode', ...) needs spec=<electrode-spec record, IRI, or name>.")

    def _add_electrode(self, spec: Any = None, *, batch: str | None = None, **kwargs) -> builtins.list:
        """Author a first-class electrode batch (the coated web/discs), queued for ws.save().

        ``ws.add("electrode", spec=si_gr_anode, batch="Si-AQ-1",
        manufactured_at="2026-03-04", count=40, storage="dry room",
        property={"loading": {"value": 6.4, "unit": "mg/cm2"}})``

        Links an electrode spec (required), carries the batch label, dates,
        amount/count, storage, and an OPEN ``property`` block for as-built
        actuals — whatever this batch was actually measured for, without a schema
        change. The IRI is content-derived from (spec_id, batch).
        """
        from battinfo.api import create_electrode  # noqa: PLC0415

        spec_id = self._resolve_electrode_spec_arg(spec)
        record = create_electrode(validate=False, electrode_spec_id=spec_id, batch=batch, **kwargs)
        self._electrodes = _dedupe_records_by_id(self._electrodes, record, "electrode")
        body = record["electrode"]
        label = body.get("batch_id") or body.get("lot_id") or body.get("name") or body["id"].rsplit("/", 1)[-1]
        print(f"  electrode:      {label}  {body['id']}")
        return [record]

    def _register_channel_keys(self, channel_body: dict, equipment_body: dict) -> None:
        """Index a channel under every reference form ``channel=`` accepts."""
        channel_id = channel_body.get("id")
        if not channel_id:
            return
        equipment_id = channel_body.get("equipment_id") or equipment_body.get("id") or ""
        pair = (equipment_id, channel_id)
        keys = {channel_id}
        label = channel_body.get("label")
        if label:
            keys.add(str(label))
        index = channel_body.get("index")
        if index is not None:
            for unit_key in (equipment_body.get("name"), equipment_body.get("serial_number")):
                if unit_key:
                    keys.add(f"{unit_key}/CH{index}")
        for key in keys:
            self._channels_by_ref[key] = pair

    def _reload_channels(self) -> None:
        """Merge channel records already saved in this workspace into the index."""
        channel_dir = self._ws.source_root / "channel"
        if not channel_dir.exists():
            return
        equipment_by_id: dict[str, dict] = {}
        equipment_dir = self._ws.source_root / "equipment"
        if equipment_dir.exists():
            for path in sorted(equipment_dir.glob("*.json")):
                try:
                    body = _read_json(path).get("equipment") or {}
                except (OSError, ValueError):
                    continue
                if body.get("id"):
                    equipment_by_id[body["id"]] = body
        for path in sorted(channel_dir.glob("*.json")):
            try:
                body = _read_json(path).get("channel") or {}
            except (OSError, ValueError):
                continue
            self._register_channel_keys(body, equipment_by_id.get(body.get("equipment_id") or "", {}))

    def _resolve_channel(self, ref: Any) -> tuple[str, str]:
        """Resolve a channel reference to ``(equipment_id, channel_id)``.

        Accepts a channel IRI, a channel label, or ``"unit/CHn"`` (unit = the
        equipment's name or serial number). Looks among channels registered
        this session, then channel records already saved in this workspace.
        """
        if isinstance(ref, dict) and isinstance(ref.get("channel"), dict):
            body = ref["channel"]
            return body.get("equipment_id", ""), body["id"]
        if not isinstance(ref, str):
            raise TypeError("channel= must be a channel IRI, a channel label, or 'unit/CHn'.")
        key = ref.strip()
        hit = self._channels_by_ref.get(key)
        if hit is None:
            self._reload_channels()
            hit = self._channels_by_ref.get(key)
        if hit is not None:
            return hit
        known = sorted(k for k in self._channels_by_ref if not k.startswith("http"))
        if known:
            shown = ", ".join(known[:8]) + (" ..." if len(known) > 8 else "")
            hint = f"  Channels in this workspace: {shown}"
        else:
            hint = "  No channels registered yet - run ws.add('equipment', spec=..., serial_number=...) first."
        raise ValueError(f"Unknown channel {ref!r}. Pass a channel IRI, a channel label, or 'unit/CHn'.\n" + hint)

    def _register_test_spec(self, spec: Any) -> Any:
        """Register a ``TestSpec`` object so its protocol record is saved and its
        minted IRI links back to the tests that reference it; returns the spec
        the tests should link.

        Idempotent by identity: passing the same spec object to several tests
        registers one protocol record, and the finalizer maps the linked test's
        ``protocol_entity`` back to it by object identity. A new object equal
        to a spec the session already holds, as when a notebook cell that
        builds it runs again, is not registered twice: the held spec is
        returned instead. A spec that pins an IRI another spec of the session
        has raises ``ValueError``.
        """
        specs = self._ws.test_specs
        if any(existing is spec for existing in specs):
            return spec
        repeat = self._session_repeat(spec, specs, what=f"test spec {spec.name!r}", note=False)
        if repeat is not None:
            return repeat
        specs.append(spec)
        return spec

    def _session_repeat(self, obj: Any, pool: builtins.list[Any], *, what: str, note: bool = True) -> Any:
        """The object of *pool* that *obj*, just built by a load or an add, repeats, else ``None``.

        A repeat would save as the same record (see ``Workspace._session_view``)
        and has *obj*'s IRI if *obj* pins one; it is reused, with a note unless
        *note* is false. When *obj* pins an IRI that a different object of
        *pool* already has, raises ``ValueError``: one IRI names one record.
        """
        repeats = self._ws._repeats_in(obj, pool)
        if repeats:
            if note:
                print(f"  {what}: already in this session, reusing it")
            return repeats[0]
        pinned = getattr(obj, "id", None)
        if pinned is not None and any(other is not obj and getattr(other, "id", None) == pinned for other in pool):
            raise ValueError(
                f"{what} has the IRI {pinned}, which a different record in this session already has. "
                "One IRI names one record: correct the IRI, or start over with ws.clear() and run the "
                "cells again."
            )
        return None

    def _discard(self, *objects: Any) -> None:
        """Take *objects* out of the session (by identity), as if the call that made them had not run."""
        engine = self._ws
        collections: tuple[builtins.list[Any], ...] = (
            engine.cell_specs,
            engine.cells,
            engine.test_specs,
            engine.tests,
            engine.datasets,
        )
        for collection in collections:
            collection[:] = [item for item in collection if not any(item is obj for obj in objects)]

    def _resolve_test_protocol_ref(self, iri: str) -> tuple[str | None, str | None]:
        """Look up a saved test-protocol record by IRI → ``(name, test_kind)``.

        Both are ``None`` when no record with that IRI exists in this workspace;
        the IRI is still accepted as a reference to a protocol published elsewhere.
        """
        proto_dir = self._ws.source_root / "test-protocol"
        for path in sorted(proto_dir.glob("*.json")) if proto_dir.exists() else []:
            try:
                body = _read_json(path).get("test_spec") or {}
            except (OSError, ValueError):
                continue
            if body.get("id") == iri:
                return body.get("name"), (body.get("kind") or body.get("test_kind") or body.get("test_type"))
        return None, None

    def _add_tests(
        self,
        type: str | None = None,
        *,
        cell: Any = None,
        data: "str | Path | builtins.list[str | Path] | None" = None,
        raw: "str | Path | builtins.list[str | Path] | None" = None,
        datasets: "str | builtins.list[str | Path] | None" = None,
        kind: str | None = None,  # backward-compat alias for type
        spec: Any = None,
        protocol: Any = None,  # backward-compat alias for spec
        conformance: Any = None,
        name: str | None = None,
        handle: str | None = None,
        iri: str | None = None,
        uid: str | None = None,
        dataset_iris: "builtins.list[str] | None" = None,
        series_id: str | None = None,
        instrument: str | None = None,
        channel: Any = None,
        license: str | None = None,
        description: str | None = None,
        status: str = "completed",
        started_at: "int | float | str | _datetime.datetime | None" = None,
        ended_at: "int | float | str | _datetime.datetime | None" = None,
    ) -> builtins.list:
        """Create a test (+ dataset(s)).

        Explicit (preferred): ``cell=<serial|IRI|object>`` and ``data=<path|list>``.
        Batch: ``datasets="glob"`` matches files to loaded cells by serial
        number or name, else by short ID (``_cells_for_data_file``).
        Relative paths resolve against the workspace root, and a data file that
        does not exist raises ``FileNotFoundError`` before anything is created.

        ``name`` is the test's title and ``handle`` its short slug (see
        :mod:`battinfo.naming`); neither is generated for you.

        The test IRI names one run (``entities.test_identity_seed``): it
        comes from the cell, the type, the protocol (the IRI of ``spec=``
        whenever there is one, saved in this workspace or not) and the run,
        which is the location of the first ``data`` file, else
        ``started_at``, else the ``name`` you give. Renaming a test with data
        or a start time keeps its IRI, and two runs of one type on one cell,
        with other data files, start times or names, get two IRIs. A test
        with none of these is one run per cell, type and protocol: a later
        ``ws.save()`` refuses to let such a test replace a saved run with
        another instrument or time window.

        ``started_at`` and ``ended_at`` (Unix seconds, an ISO 8601 time or a
        datetime) say when the run started and ended. Without them, the times
        are read from a BDF data file's ``unix_time_second`` column when it has
        one. A time read from a file never enters the IRI, so converting the
        data again after a converter upgrade keeps it.

        ``iri`` (a full ``https://w3id.org/battinfo/test/...`` IRI) or ``uid``
        (its 16-character uid) pins a published identity, such as a test
        published before the test seed changed in 0.8.0 and rebuilt in a new
        folder. ``dataset_iris`` does the same for the datasets made from
        ``data=``: one IRI per data file, in the same order. A dataset's IRI is
        seeded from its test, its file's location and its title, which is made
        from the test's name. ``iri``, ``uid``, ``dataset_iris``, ``started_at``
        and ``ended_at`` need the explicit ``cell=`` form.

        ``series_id`` puts the datasets made from ``data=`` in a collection: it is
        the collection's IRI (``https://w3id.org/battinfo/dataset/...``) and is set
        on every one of them. It needs ``data=`` and the explicit ``cell=`` form,
        and it is checked before anything is created. Membership is not identity,
        so it never enters the test or dataset IRI seeds. The collection itself is
        written with ``battinfo.Dataset`` and ``battinfo.save_dataset``.

        ``channel`` attaches the test to an equipment channel (a channel IRI, a
        channel label, or ``"unit/CHn"``); the test record then carries
        ``equipment_id`` + ``channel_id``.

        ``raw`` attaches the original, pre-conversion instrument file(s) alongside
        each processed ``data`` file as a "raw"-role distribution, so the source
        travels with the deposit for provenance. If omitted, originals recorded by
        :meth:`convert` are attached automatically.

        ``conformance`` flags how the run followed its referenced test spec — a status
        string (``"conformant"`` / ``"non-conformant"``; ``"unknown"`` = not assessed)
        or a dict ``{"status": ..., "note": ..., "deviations": [...]}``. Pass the spec
        via ``spec=`` so the conformance binds to it.

        ``license`` sets the license on the dataset(s) produced here, overriding the
        workspace default (``ws.license``) for these records. Precedence at publish:
        an explicit ``ws.zenodo(license=...)`` > this ``license=`` > workspace default.
        """
        # The collection for the datasets made from data=. Checked first, so a bad
        # value fails before any test, dataset or test spec is created.
        member_series_id = self._checked_series_id(series_id, cell=cell, data=data)
        given_start, given_end = _given_run_period(started_at, ended_at)

        # Resolve the test type (type=, legacy kind=, or from a linked spec).
        test_type = type or kind
        test_spec = spec if spec is not None else protocol
        protocol_name = protocol_url = None
        # An IRI reference (spec=<test-protocol IRI>) links the test to an
        # already-saved protocol; stamped onto every test built below.
        protocol_id_ref: str | None = None
        # A TestSpec object is registered for save so its protocol record is
        # written and its minted IRI links back to this test (same outcome as
        # the ws.load(<draft>) path). Never reduce a spec to a name string.
        protocol_ref = None
        registered_here = False  # this call added protocol_ref to the session
        if test_spec is not None:
            if isinstance(test_spec, str):
                # A bare string is meaningful only as a reference to a saved
                # test-protocol (its IRI). Treating it as a display name would
                # drop the protocol entirely and mint a test with protocol_id
                # null, so require an IRI (resolved here) and reject anything else.
                if test_spec.startswith(("http://", "https://")):
                    protocol_id_ref = test_spec
                    protocol_name, resolved_kind = self._resolve_test_protocol_ref(test_spec)
                    if protocol_name is None and resolved_kind is None:
                        # Not saved here: a protocol published elsewhere, so make the
                        # reference resolvable at save time (its name and kind stay
                        # unread, so the test's identity does not change).
                        self._resolve_published_reference(test_spec, "test-protocol")
                    if resolved_kind and not test_type:
                        test_type = resolved_kind
                else:
                    raise ValueError(
                        f"spec={test_spec!r} is not a test-protocol reference. Pass a "
                        "battinfo.TestSpec (authored inline or via ws.load(<draft file>)), "
                        "or the IRI of a test-protocol saved in this workspace "
                        "(https://w3id.org/battinfo/spec/...). A plain string is "
                        "not accepted as a protocol name: it would leave the run unlinked "
                        "to any saved protocol."
                    )
            else:
                from battinfo.bundle import TestSpec as _TestSpec  # noqa: PLC0415

                if not isinstance(test_spec, _TestSpec):
                    # NB: the `type` parameter shadows the builtin here, so read the
                    # class name off the object rather than calling type().
                    raise TypeError(
                        f"spec= must be a battinfo.TestSpec or a test-protocol IRI, got "
                        f"{test_spec.__class__.__name__}. Author one inline "
                        "(battinfo.TestSpec(...)) or via ws.load(<draft file>)."
                    )
                held = any(existing is test_spec for existing in self._ws.test_specs)
                protocol_ref = self._register_test_spec(test_spec)
                registered_here = not held and protocol_ref is test_spec
                protocol_name = test_spec.name
                protocol_url = test_spec.protocol_url
                spec_kind = getattr(test_spec, "test_type", None)
                if spec_kind is not None and not test_type:
                    test_type = spec_kind.value if hasattr(spec_kind, "value") else str(spec_kind)
        if not test_type:
            raise ValueError("ws.add('test', ...) requires type=... (or a spec that defines it). " + _test_kind_hint())
        test_type = _normalize_test_kind(test_type)
        protocol_name = protocol_name or test_type.replace("_", " ")

        # Normalise / validate the conformance flag (status + optional deviations).
        conformance = _coerce_conformance(conformance)

        # Resolve the equipment channel (if any) up front so an unknown
        # reference fails before any test is created.
        equipment_id = channel_id = None
        if channel is not None:
            equipment_id, channel_id = self._resolve_channel(channel)

        # Identity pins and the handle name ONE test, so they need the explicit
        # form; check them before anything is created.
        pinned_test_id = self._pinned_test_iri(iri, uid)
        if cell is None and any(v is not None for v in (handle, iri, uid, dataset_iris, started_at, ended_at)):
            raise ValueError(
                "handle=, iri=, uid=, dataset_iris=, started_at= and ended_at= describe one test; use "
                "the explicit form ws.add('test', cell=..., ...) rather than datasets='glob'."
            )

        # ── Explicit mode: a named cell (+ optional data files) ──────────────────
        if cell is not None:
            files = self._as_data_paths(data)
            raw_files = self._as_data_paths(raw)
            # A dataset for a file that does not exist would be saved without a word
            # and only fail at deposit time; refuse it before anything is created.
            self._require_files(files, "data")
            self._require_files(raw_files, "raw")
            resolved = self._resolve_cell(cell)
            if raw_files and len(raw_files) != len(files):
                raise ValueError(
                    f"raw= has {len(raw_files)} file(s) but data= has {len(files)}; "
                    "pass one original per processed file (same order), or omit raw= "
                    "to use the originals recorded by ws.convert()."
                )
            pinned_dataset_ids = self._pinned_dataset_iris(dataset_iris, len(files))
            # The original of each data file: explicit raw= wins; otherwise the
            # convert() manifest.
            sources: builtins.list[Path | None] = (
                list(raw_files) if raw_files else [self._resolve_raw_source(f) for f in files]
            )
            # The workspace registers every file it makes a dataset from, so a
            # Zenodo deposit may read it wherever it lies (a lab share, say).
            self._register_sources([*files, *sources], by="ws.add")
            # Measured period per data file (from the BDF unix_time_second column), so
            # the test activity and each dataset are placed in time from the data itself
            # rather than the record-assembly clock. A start or end the caller gives wins.
            # Neither measured time enters the test IRI: the first data file's location
            # tells the run apart (entities.test_identity_seed).
            periods = [_bdf_measurement_period(f) for f in files]
            _spans = [p for p in periods if p]
            run_start = given_start if given_start is not None else (min(s for s, _ in _spans) if _spans else None)
            run_end = given_end if given_end is not None else (max(e for _, e in _spans) if _spans else None)
            test = self._ws.test(
                resolved,
                kind=test_type,
                name=name,
                protocol_ref=protocol_ref,
                protocol=protocol_name,
                protocol_url=protocol_url,
                description=description,
                status=status,
                conformance=conformance,
                instrument=instrument,
                started_at=run_start,
                ended_at=run_end,
            )
            if pinned_test_id is not None:
                test.id = pinned_test_id
            if handle is not None:
                test.handle = handle
            if protocol_id_ref is not None:
                # Reference by IRI: link the run to the already-saved protocol.
                test.protocol_id = protocol_id_ref
            if channel_id is not None:
                # The engine constructor predates equipment support; the Test
                # model already declares the fields, so stamp them on the
                # object - they flow into the saved record via Test.to_record().
                test.equipment_id = equipment_id
                test.channel_id = channel_id
            label = getattr(resolved, "name", None) or getattr(resolved, "serial_number", None) or resolved.id or "cell"
            n_raw = 0
            made: builtins.list[Any] = []
            for i, f in enumerate(files):
                src = sources[i]
                if src is not None:
                    n_raw += 1
                _per = periods[i]
                _tc = f"{_unix_to_iso(_per[0])}/{_unix_to_iso(_per[1])}" if _per else None
                dataset_obj = self._ws.dataset(
                    resolved,
                    title=f"{name or label} data",
                    test=test,
                    path=f,
                    source_path=src,
                    license=license,
                    format=_guess_format(f),
                    temporal_coverage=_tc,
                )
                if pinned_dataset_ids is not None:
                    dataset_obj.id = pinned_dataset_ids[i]
                if member_series_id is not None:
                    dataset_obj.series_id = member_series_id
                made.append(dataset_obj)
            # The same call run again (a notebook cell re-run) reuses the test
            # and datasets the session already holds.
            repeat = self._repeated_test(test, made)
            if repeat is not None:
                self._discard(test, *made, *([protocol_ref] if registered_here else []))
                print(f"  test [{test_type}] on {label}: already in this session, reusing it")
                return [repeat]
            try:
                self._refuse_taken_test_pins(test, made)
            except ValueError:
                self._discard(test, *made, *([protocol_ref] if registered_here else []))
                raise
            conf_status = conformance.status if conformance is not None else None
            print(
                f"  test [{test_type}] on {label}"
                + (f"  +{len(files)} dataset(s)" if files else "")
                + (f"  (+{n_raw} raw source{'s' if n_raw != 1 else ''})" if n_raw else "")
                + (f"  channel: {channel}" if channel_id is not None else "")
                + (f"  conformance: {conf_status}" if conf_status else "")
                + (f"  collection: {member_series_id}" if member_series_id else "")
            )
            return [test]

        # ── Batch mode: match a glob of files to loaded cells by name ────────────
        if datasets is not None:
            if conformance is not None:
                raise ValueError(
                    "conformance is per-test — use the explicit form "
                    "ws.add('test', cell=..., conformance=...) to flag each test."
                )
            tests = self._add_tests_by_filename(
                test_type,
                datasets,
                protocol_name,
                protocol_url,
                protocol_ref,
                instrument,
                license,
                description,
                status,
            )
            if protocol_id_ref is not None:
                for t in tests:
                    t.protocol_id = protocol_id_ref
            if channel_id is not None:
                for t in tests:
                    t.equipment_id = equipment_id
                    t.channel_id = channel_id
            # Matching the same files again (a notebook cell re-run) reuses the
            # tests and datasets the session already holds.
            kept: builtins.list[Any] = []
            for t in tests:
                made = [d for d in self._ws.datasets if d.test is t]
                repeat = self._repeated_test(t, made)
                if repeat is not None:
                    self._discard(t, *made)
                kept.append(repeat if repeat is not None else t)
            reused = sum(1 for new, held in zip(tests, kept) if new is not held)
            if reused:
                print(f"  {reused} of these test(s) already in this session, reusing them")
            return kept

        raise ValueError(
            "ws.add('test', ...) needs either cell=<serial|IRI|object> (with data=...) "
            "for an explicit test, or datasets='glob' to match files to loaded cells."
        )

    def _pinned_test_iri(self, iri: str | None, uid: str | None) -> str | None:
        """The test IRI pinned by ``iri=`` / ``uid=``, checked, or ``None``.

        Same contract as the cell ``iris=`` path: the caller supplies an
        identity that was published before, and it replaces the seeded IRI.
        The shape is checked here so a typo fails before anything is created.
        A pin another test of this session already has is refused once the
        test is built (``_refuse_taken_test_pins``), unless the call repeats
        that test.
        """
        from battinfo.api._shared import TEST_IRI_RE, _normalized_dashed_uid  # noqa: PLC0415

        if iri is None and uid is None:
            return None
        pinned: str | None = None
        if iri is not None:
            if not isinstance(iri, str) or not TEST_IRI_RE.fullmatch(iri.strip()):
                raise ValueError(
                    f"iri={iri!r} is not a test IRI; expected https://w3id.org/battinfo/test/xxxx-xxxx-xxxx-xxxx."
                )
            pinned = iri.strip()
        if uid is not None:
            from_uid = record_iri("test", _normalized_dashed_uid(str(uid)))
            if pinned is not None and pinned != from_uid:
                raise ValueError(f"iri={iri!r} and uid={uid!r} name different tests; pass one.")
            pinned = from_uid
        return pinned

    def _pinned_dataset_iris(
        self, dataset_iris: "builtins.list[str] | None", n_files: int
    ) -> "builtins.list[str] | None":
        """``dataset_iris=`` checked against the data files it pins, or ``None``.

        The shape, the count and that no IRI repeats are checked here; that no
        other dataset of the session has one of them, once the datasets are
        built (``_refuse_taken_test_pins``).
        """
        from battinfo.api._shared import DATASET_IRI_RE  # noqa: PLC0415

        if dataset_iris is None:
            return None
        if isinstance(dataset_iris, str):
            dataset_iris = [dataset_iris]
        pinned = [str(item).strip() for item in dataset_iris]
        if len(pinned) != n_files:
            raise ValueError(
                f"dataset_iris must match the number of data files ({len(pinned)} IRIs vs {n_files} files)."
            )
        bad = [item for item in pinned if not DATASET_IRI_RE.fullmatch(item)]
        if bad:
            raise ValueError(
                f"dataset_iris entries must be dataset IRIs "
                f"(https://w3id.org/battinfo/dataset/xxxx-xxxx-xxxx-xxxx); got {bad[:3]}."
            )
        if len(set(pinned)) != len(pinned):
            raise ValueError("dataset_iris must name distinct datasets not already used in this session.")
        return pinned

    def _repeated_test(self, test: Any, datasets: builtins.list[Any]) -> Any:
        """The test of this session that *test*, just added with *datasets*, repeats, else ``None``.

        A repeat saves as the same test record (``Workspace._session_view``) and
        has the same data: as many datasets, each saving as the same record
        apart from its link to the test, with every IRI *datasets* pin.
        """
        engine = self._ws
        # The datasets of each test, read in one pass: by the test object, or by
        # its IRI for a dataset that holds only that.
        by_test: dict[int, builtins.list[Any]] = {}
        by_iri: dict[str, builtins.list[Any]] = {}
        for dataset in engine.datasets:
            if dataset.test is not None:
                by_test.setdefault(id(dataset.test), []).append(dataset)
            elif dataset.test_id is not None:
                by_iri.setdefault(dataset.test_id, []).append(dataset)

        def data_of(other: Any) -> builtins.list[Any]:
            return by_test.get(id(other), []) + (by_iri.get(other.id, []) if other.id is not None else [])

        def places(items: Iterable[Any]) -> builtins.list[str]:
            return sorted(engine._dataset_locator(item) for item in items)

        # A repeat has the same data files, so only tests with them are compared
        # in full; the session view is far dearer than the file's locator.
        mine_places = places(datasets)
        pool = [other for other in engine.tests if other is not test and places(data_of(other)) == mine_places]
        candidates = engine._repeats_in(test, pool)
        if not candidates:
            return None

        def views(items: Iterable[Any]) -> builtins.list[tuple[str, str]]:
            return sorted((engine._session_view(item, without=("test_id",)), item.id or "") for item in items)

        mine = views(datasets)
        for other in candidates:
            theirs = views(data_of(other))
            same_data = [view for view, _ in mine] == [view for view, _ in theirs]
            if same_data and all(not own or own == held for (_, own), (_, held) in zip(mine, theirs)):
                return other
        return None

    def _refuse_taken_test_pins(self, test: Any, datasets: builtins.list[Any]) -> None:
        """Raise ``ValueError`` when *test* pins an IRI another test of this session has, or *datasets* one
        another dataset has. One IRI names one record; a call that repeats a whole test reused it before."""
        if test.id is not None and any(other is not test and other.id == test.id for other in self._ws.tests):
            raise ValueError(f"{test.id} is already used by another test in this session.")
        pinned = {dataset.id for dataset in datasets if dataset.id is not None}
        taken = {
            other.id for other in self._ws.datasets if other.id is not None and not any(other is d for d in datasets)
        }
        if pinned & taken:
            raise ValueError("dataset_iris must name distinct datasets not already used in this session.")

    def _require_files(self, paths: builtins.list[Path], argument: str) -> None:
        """Raise FileNotFoundError naming each resolved path in *paths* that does not exist."""
        missing = [path for path in paths if not path.exists()]
        if missing:
            listing = ", ".join(str(path) for path in missing)
            raise FileNotFoundError(
                f"{argument}= file not found: {listing}. A relative path resolves against the "
                f"workspace root ({self._root}), not the current directory."
            )

    def _checked_series_id(self, series_id: str | None, *, cell: Any, data: Any) -> str | None:
        """``series_id=`` checked as a collection's dataset IRI, or ``None``.

        The value goes on the datasets made from ``data=``, so it needs that and
        the explicit ``cell=`` form. Only its shape is checked: the collection may
        be saved in this workspace or published elsewhere earlier.
        """
        from battinfo.api._shared import DATASET_IRI_RE  # noqa: PLC0415

        if series_id is None:
            return None
        if cell is None or not self._as_data_paths(data):
            raise ValueError(
                "series_id= puts the datasets made from data= in a collection; use "
                "ws.add('test', cell=..., data=..., series_id=...). The collection itself "
                "is written with battinfo.Dataset and battinfo.save_dataset."
            )
        text = series_id.strip() if isinstance(series_id, str) else ""
        if not DATASET_IRI_RE.fullmatch(text):
            raise ValueError(
                f"series_id={series_id!r} is not a dataset IRI; expected the collection's "
                "IRI, https://w3id.org/battinfo/dataset/xxxx-xxxx-xxxx-xxxx."
            )
        return text

    def _as_data_paths(self, data: Any) -> builtins.list[Path]:
        """Normalise a data= value (path, str, or list) to a list of absolute Paths."""
        if data is None:
            return []
        items = [data] if isinstance(data, (str, Path)) else list(data)
        out: list[Path] = []
        for p in items:
            p = Path(p) if not isinstance(p, Path) else p
            out.append(p if p.is_absolute() else self._root / p)
        return out

    def _resolve_cell(self, ref: Any) -> Any:
        """Resolve a cell reference: this session, then records saved on disk, then the registry.

        Accepts a ``Cell``, a search result, a serial number or name, a short
        ID, or an IRI. A serial number or name has to match a cell's exactly; a
        short ID is matched only when the label is one on its own (see
        :meth:`_cells_labelled`). Serials authored in a previous session are
        rehydrated from ``.battinfo/records/cell-instance/`` (so resolution
        works in a fresh process). An instance found only in the registry is
        referenced (not re-published), with a line naming it and its
        publisher. A label that several cells answer to, in the session or in
        the registry, raises ``ValueError`` listing them.
        """
        from battinfo.bundle import Cell  # noqa: PLC0415

        if isinstance(ref, Cell):
            return ref
        if isinstance(ref, dict):  # a search result
            return self.load(ref)
        if isinstance(ref, str):
            s = ref.strip()
            if s.startswith("http"):  # an IRI
                # A cell already found (by serial, a search hit or an earlier IRI) is
                # reused, not referenced and looked up in the registry again.
                known = next((cell for cell, _ in self._indexed_cells if getattr(cell, "id", None) == s), None)
                if known is not None:
                    return known
                return self._reference_cell({"id": s, "type": "cell"})

            hit = self._session_cell(s)
            if hit is None:
                # Day-2: this fresh process has an empty index; load cells saved
                # to disk in a previous session before falling back to the registry.
                self._rehydrate_cell_index()
                hit = self._session_cell(s)
            if hit is not None:
                return hit
            found = self._query_registry_cells(serials=[s])
            if len(found) > 1:
                listing = "\n".join(f"  {_describe_registry_cell(c)}" for c in found)
                raise ValueError(
                    f"{s!r} matches {len(found)} cells in the registry, so it cannot pick one:\n{listing}\n"
                    'Pass the one you mean by its IRI, cell="https://w3id.org/battinfo/cell/...", '
                    f"or reference it first with ws.load(ws.search(type='cell', serial={s!r})[i])."
                )
            if found:
                print(f"  cell {s!r} found in the registry: {_describe_registry_cell(found[0])}")
                return self._reference_cell({**found[0], "type": "cell"})
            searched = "this session, the records saved under {root}".format(root=self._ws.source_root)
            searched += ", or the registry" if self._registry_url else " (registry not configured)"
            raise ValueError(
                f"Could not resolve cell {ref!r} in {searched}. "
                "Create it with ws.add('cell', ...), or check the serial."
            )
        raise TypeError("cell= must be a serial, IRI, Cell, or search result.")

    def _cells_for_data_file(self, path: Path) -> tuple[builtins.list[Any], str | None, bool]:
        """The cells a data file's name names, the part of the name that named them, and whether it was a label.

        The name, then the name with its extension and data-format suffixes
        taken off one at a time (``LAB-01.bdf.csv`` gives ``LAB-01.bdf``, then
        ``LAB-01``; see :func:`_data_file_stems`), is matched against every
        cell's serial number and name exactly; the first that matches a cell
        decides. A dot that is part of a serial stays, so ``S1.6.csv`` never
        names the cell ``S1``. Only when no cell matches is a short ID tried. A
        name that is a short ID on its own (``gm6pmr.bdf.csv``) finds a cell
        whose IRI or label carries it. A short ID a name ends in
        (``cycling-gm6pmr.csv``) finds only the cell whose IRI it is the short
        ID of, because a serial number such as ``LAB-2024-000001`` ends in six
        characters another serial can share.
        """
        stems = _data_file_stems(path.name)
        for stem in stems:
            exact = [cell for cell, labels in self._indexed_cells if stem in labels]
            if exact:
                return exact, stem, True
        base = stems[-1]
        if _is_short_id(base):
            cells = [(labels, getattr(cell, "id", None)) for cell, labels in self._indexed_cells]
            return [self._indexed_cells[i][0] for i in _cells_named_by(base, cells, base)], base, False
        short_id = next((sid for sid in (_short_id(stem) for stem in stems) if sid and _is_short_id(sid)), None)
        if short_id is None:
            return [], None, False
        by_iri = [cell for cell, _ in self._indexed_cells if _iri_short_id(getattr(cell, "id", None)) == short_id]
        return by_iri, short_id, False

    def _session_cell(self, label: str) -> Any:
        """The one session cell *label* names, or None; raises when it names several."""
        cells = self._cells_labelled(label)
        if len(cells) > 1:
            listing = "\n".join(f"  {_describe_session_cell(c)}" for c in cells)
            raise ValueError(
                f"{label!r} matches more than one cell in this workspace, so it cannot identify one:\n"
                f"{listing}\n"
                "Pass the cell itself (the object ws.add('cell') returned), its IRI, or a serial "
                "number only it has."
            )
        return cells[0] if cells else None

    def _add_tests_by_filename(
        self,
        test_type: str,
        datasets: "str | builtins.list[str | Path]",
        protocol_name: str | None,
        protocol_url: str | None,
        protocol_ref: Any,
        instrument: str | None,
        license: str | None,
        description: str | None,
        status: str,
    ) -> builtins.list:
        """Batch helper: match a glob of data files to loaded cells by serial, name or short ID."""
        if isinstance(datasets, str):
            matched_files = sorted(self._root.glob(datasets))
        else:
            matched_files = [Path(p) if not isinstance(p, Path) else p for p in datasets]
            matched_files = [p if p.is_absolute() else self._root / p for p in matched_files]
            self._require_files(matched_files, "datasets")
        if not matched_files:
            print(f"  No dataset files matched: {datasets!r}")
            return []

        # Auto-reload cells saved in a previous session so matching can succeed.
        if not self._indexed_cells:
            ci_dir = self._ws.source_root / "cell-instance"
            if ci_dir.exists() and any(ci_dir.glob("*.json")):
                print("  No cells in memory - reloading saved cell instances...")
                self.reload_cells()
        if not self._indexed_cells:
            raise RuntimeError(
                "No cell instances available to match.\n"
                "  Create them:                ws.add('cell', spec=spec, serial_numbers=[...])\n"
                "  Or reference existing ones: ws.load(ws.search(type='cell', batch='...'))"
            )

        # Registered as the explicit form registers its files (see _register_sources).
        self._register_sources([*matched_files, *(self._resolve_raw_source(f) for f in matched_files)], by="ws.add")
        print(f"Matching {len(matched_files)} file(s) to cell instances...")
        unmatched: list[Path] = []
        tests = []
        for f in matched_files:
            # A file named after a cell's serial or name matches that cell; only
            # otherwise does the short ID in its name count.
            candidates, key, by_label = self._cells_for_data_file(f)
            if len(candidates) > 1:
                # Matching this file to "a" cell would attach the measurement to
                # an arbitrary one of several. Skip it and say why.
                unmatched.append(f)
                print(
                    f"  AMBIGUOUS {f.name} -- {key!r} matches more than one cell; name the file after the serial number"
                )
                continue
            if not candidates:
                unmatched.append(f)
                print(f"  NO MATCH  {f.name}")
                continue
            cell = candidates[0]
            if not by_label:
                how = f'short id "{key}"'
            else:
                how = "serial number" if key == getattr(cell, "serial_number", None) else "name"
            test = self._ws.record_test(
                cell,
                kind=test_type,
                path=f,
                protocol=protocol_name,
                protocol_url=protocol_url,
                protocol_ref=protocol_ref,
                description=description,
                instrument=instrument,
                status=status,
                license=license,
                format=_guess_format(f),
                source_path=self._resolve_raw_source(f),
            )
            print(f"  matched   {f.name}  ->  {cell.name or cell.serial_number}  (by {how})")
            tests.append(test)

        if unmatched:
            known = sorted(
                {
                    (c.name or c.serial_number)
                    for c, _ in self._indexed_cells
                    if getattr(c, "name", None) or getattr(c, "serial_number", None)
                }
            )
            print(f"\n  {len(unmatched)} file(s) had no matching cell instance:")
            for f in unmatched:
                print(f"    {f.name}")
            stems = ", ".join(repr(_data_file_stems(f.name)[-1]) for f in unmatched[:5])
            print("  Reference the missing cells (e.g. registered at manufacture), then re-run:")
            print(f"      ws.load(ws.search(type='cell', serials=[{stems}]))")
            print("  ...or pass them explicitly: ws.add('test', cell='<serial>', data='<file>').")
            if known:
                shown = ", ".join(known[:8]) + (" ..." if len(known) > 8 else "")
                print(f"  Cells currently in this workspace: {shown}")

        print(
            f"\nCreated {len(tests)} test(s)" + (f"; {len(unmatched)} unmatched file(s) skipped" if unmatched else "")
        )
        return tests


def _norm(s: str) -> str:
    """Lowercase and strip all non-alphanumeric characters."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


# Canonical size-code alias groups.  Every alias in a group expands to all others,
# so searching any of them matches cells indexed under any of them.
_SIZE_ALIAS_GROUPS: list[list[str]] = [
    ["r03", "lr03", "fr03", "aaa", "tripleа"],
    ["r6", "lr6", "fr6", "aa", "doublea"],
    ["r14", "lr14", "c"],
    ["r20", "lr20", "d"],
    ["lr1", "r1", "n"],
    ["6lr61", "6f22", "9v"],
    ["18650"],
    ["21700"],
    ["26650"],
    ["14500"],
    ["4680"],
    ["cr2032"],
    ["cr2016"],
    ["cr2025"],
]
_SIZE_ALIAS_MAP: dict[str, list[str]] = {}
for _group in _SIZE_ALIAS_GROUPS:
    for _code in _group:
        _SIZE_ALIAS_MAP[_code] = _group


def _expand_size_codes(*codes: str) -> str:
    """Return a space-separated string of all aliases for the given size codes."""
    seen: list[str] = []
    for code in codes:
        key = _norm(code)
        for alias in _SIZE_ALIAS_MAP.get(key, [key] if key else []):
            if alias not in seen:
                seen.append(alias)
    return " ".join(seen)


def _fuzzy_score(
    terms: list[str],
    mfr: str,
    model: str,
    size_tokens: frozenset[str] = frozenset(),
) -> float:
    """Return a [0, 1] match score for *terms* against manufacturer + model.

    Size codes are matched as exact tokens (whole-word) so "AA" does not
    accidentally match "AAA" cells.

    Strategy per term:
      1. Exact size-code token match → 1.0
      2. Exact substring on normalised mfr+model → 1.0
      3. Best SequenceMatcher ratio against each word → that ratio
    Final score = min across terms (every term must match something).
    """
    combined_words = f"{mfr} {model}".lower().split()
    combined_compact = _norm(f"{mfr} {model}")

    scores: list[float] = []
    for raw_term in terms:
        t = _norm(raw_term)
        if not t:
            continue
        # 1. Exact size-code token match (whole-word, no substring bleed)
        if t in size_tokens:
            scores.append(1.0)
            continue
        # 2. Substring match against normalised mfr+model
        if t in combined_compact:
            scores.append(1.0)
            continue
        # 3. Fuzzy match against individual words + compact combined
        candidates = [c for c in ([_norm(w) for w in combined_words] + [combined_compact]) if c]
        if not candidates:
            scores.append(0.0)
            continue
        best = max(difflib.SequenceMatcher(None, t, c).ratio() for c in candidates)
        scores.append(best)

    return min(scores) if scores else 0.0


def _make_record_slug(manufacturer: str, model: str, year: int | str) -> str:
    """Generate the battinfo-records directory slug: manufacturer--model--year."""

    def slugify(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")

    return f"{slugify(manufacturer)}--{slugify(model)}--{year}"


def _guess_format(path: Path) -> str | None:
    name = path.name.lower()
    if name.endswith(".parquet") or ".bdf.parquet" in name:
        return "application/x-parquet"
    if name.endswith(".csv") or ".bdf.csv" in name:
        return "text/csv"
    if name.endswith(".ndax") or name.endswith(".nda"):
        return "application/x-neware-ndax"
    return None


def _authoring_envelope(**kwargs) -> dict:
    """All authoring-workspace submissions share ONE envelope core (api.py, 4.3);
    only the staged mode and authoring provenance identify this path."""
    from battinfo.api import build_submission_envelope  # noqa: PLC0415

    return build_submission_envelope(
        publication_mode=STAGED_PUBLICATION_MODE,
        source_system="battinfo-authoring",
        workflow_name="authoring-workspace-submission",
        **kwargs,
    )


def _cell_spec_submission_payload(
    record: dict,
    *,
    wid: str,
    pid: str,
    ver: str,
    source_local_id: str,
    title: str,
    related_resources: list[dict] | None = None,
) -> dict:
    return _authoring_envelope(
        resource_type="cell_spec",
        records={"cell_spec": record},
        rdf_type="CellSpec",
        workspace_id=wid,
        publisher_id=pid,
        source_version=ver,
        source_local_id=source_local_id,
        title=title,
        related_resources=related_resources,
    )


def _point_source_url_at_public_copy(record: dict, public_url_for: Callable[[object], str | None]) -> bool:
    """Replace a local ``provenance.source_url`` with the public URL of the same file.

    *public_url_for* maps a location (a ``file:`` URI or a path) to the public
    URL of the file it names, found by resolved path, or to ``None`` when that
    file has no public copy; a file that merely shares the name of an uploaded
    one is not taken for it. Returns True when the record changed.
    """
    provenance = record.get("provenance")
    if not isinstance(provenance, dict):
        return False
    public = public_url_for(provenance.get("source_url"))
    if not public:
        return False
    provenance["source_url"] = public
    return True


def _submission_local_files(record: dict, subdir: str, records_dir: Path) -> list[tuple[str, str]]:
    """Local file paths a submission of *record* would publish (see local_file_references).

    A cell's submission embeds its saved cell spec, so that record is checked too.
    """
    found = local_file_references(record)
    if subdir == "cell-instance":
        spec_id = (record.get("cell_instance") or {}).get("cell_spec_id") or ""
        spec_record = _find_spec_record(records_dir / "cell-spec", spec_id) if spec_id else None
        if spec_record:
            found += [(f"(its cell spec) {field}", value) for field, value in local_file_references(spec_record)]
    return found


def _find_spec_record(cell_spec_dir: Path, cell_spec_id: str) -> dict | None:
    """Return the cell-spec record dict whose product.id matches cell_spec_id."""
    if not cell_spec_dir.exists():
        return None
    for f in cell_spec_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("cell_spec", {}).get("id") == cell_spec_id:
                return data
        except Exception:
            continue
    return None


def _cell_instance_submission_payload(
    record: dict,
    *,
    wid: str,
    pid: str,
    ver: str,
    source_local_id: str,
    title: str,
    spec_record: dict | None = None,
    related_resources: list[dict] | None = None,
    preview: dict | None = None,
) -> dict:
    ci = record.get("cell_instance", {})
    if related_resources is not None:
        related = related_resources
    else:
        related = []
        cell_spec_id = ci.get("cell_spec_id")
        if cell_spec_id:
            related.append(
                {
                    "relationship": "instanceOf",
                    "resource_type": "cell_spec",
                    "canonical_iri": cell_spec_id,
                }
            )

    return _authoring_envelope(
        resource_type="cell",
        records={"cell": record, **({"cell_spec": spec_record} if spec_record else {})},
        rdf_type="BatteryCell",
        workspace_id=wid,
        publisher_id=pid,
        source_version=ver,
        source_local_id=source_local_id,
        title=title,
        related_resources=related,
        preview=preview,
    )


def _build_dataset_distributions(ds: dict) -> tuple[list[dict], list[dict]]:
    """Split a dataset's distributions into (page-model, inner-record) lists.

    Returns ``(top_level, inner)``. Plot files (added by :meth:`AuthoringWorkspace.process`
    as role ``other`` with ``*.plot.json`` / ``*.png`` names) are *promoted* to
    ``plot_data`` / ``plot_static`` in the page-model ``top_level`` list (the platform
    renders these as the curve preview) and *dropped* from the schema-validated inner
    record, which keeps only the measurement distributions. Measurement distributions
    appear in both. URLs are whatever the record holds — public R2 URLs after
    :meth:`upload`."""
    top_level: list[dict] = []
    inner: list[dict] = []
    for d in ds.get("distributions") or []:
        name = d.get("name") or ""
        url = d.get("content_url") or ds.get("access_url") or ""
        fmt = d.get("encoding_format")
        if name.endswith(".plot.json"):
            top_level.append(
                {"title": name, "access_url": url, "role": "plot_data", "media_type": fmt or "application/json"}
            )
        elif name.endswith(".png"):
            top_level.append(
                {"title": name, "access_url": url, "role": "plot_static", "media_type": fmt or "image/png"}
            )
        else:
            inner.append(d)
            top_level.append(
                {
                    "title": name or d.get("role") or "data",
                    "access_url": url,
                    "role": d.get("role") or "processed",
                    "media_type": fmt,
                }
            )
    return top_level, inner


def _simple_submission_payload(
    record: dict,
    *,
    resource_type: str,
    rdf_type: str,
    record_key: str,
    wid: str,
    pid: str,
    ver: str,
    source_local_id: str,
    title: str,
    related_cell_id: str | None = None,
    distributions: list[dict] | None = None,
    related_resources: list[dict] | None = None,
    preview: dict | None = None,
) -> dict:
    if related_resources is not None:
        related = related_resources
    else:
        related = []
        if related_cell_id:
            related.append(
                {
                    "relationship": "about",
                    "resource_type": "cell",
                    "canonical_iri": related_cell_id,
                }
            )
    return _authoring_envelope(
        resource_type=resource_type,
        records={record_key: record},
        rdf_type=rdf_type,
        workspace_id=wid,
        publisher_id=pid,
        source_version=ver,
        source_local_id=source_local_id,
        title=title,
        related_resources=related,
        distributions=distributions,
        preview=preview,
    )


def _lift_funding_to_provenance(payload: dict) -> None:
    """Surface the record's funding grant at the submission provenance level.

    Funding is already stamped on the embedded record (``ws.save()``); lifting it
    to ``provenance.project`` gives the registry a normalised, top-level field to
    filter on (\"everything from grant X\") without parsing each record kind.
    """
    records = ((payload.get("resource") or {}).get("semantic_payload") or {}).get("battinfo_records") or {}
    if not isinstance(records, dict):
        return
    for rec in records.values():
        if isinstance(rec, dict) and isinstance(rec.get("funding"), dict):
            payload.setdefault("provenance", {})["project"] = rec["funding"]
            return


# Statuses we will echo verbatim in a progress line; anything else prints as "unknown".
_DISPLAY_STATUSES = frozenset(
    {"validated", "published", "staged_unanchored", "ok", "unknown", "failed", "rejected", "error"}
)

# Envelope fields that vary across authoring re-runs without changing what is
# being submitted; stripped before hashing a payload for the submit journal.
_JOURNAL_VOLATILE_KEYS = frozenset({"generated_at"})


def _journal_payload_hash(payload: dict) -> str:
    import hashlib  # noqa: PLC0415

    def strip(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: strip(v) for k, v in value.items() if k not in _JOURNAL_VOLATILE_KEYS}
        if isinstance(value, list):
            return [strip(v) for v in value]
        return value

    canonical = json.dumps(strip(dict(payload)), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _normalize_registry_url(url: str) -> str:
    """A registry base URL in one spelling, as the submit journal records it.

    Scheme and host are lower-cased; a default port, user name and password,
    query, fragment and trailing slashes are dropped. Host names are not
    resolved, so ``localhost`` and ``127.0.0.1`` count as two registries: a
    record sent to one is sent again to the other, which is safe because the
    registry de-duplicates identical submissions.
    """
    from urllib.parse import urlsplit  # noqa: PLC0415

    text = (url or "").strip()
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        return text.rstrip("/").lower()
    host = parts.hostname or ""
    if not parts.scheme or not host:
        return text.rstrip("/").lower()
    scheme = parts.scheme.lower()
    if ":" in host:
        host = f"[{host}]"  # an IPv6 literal
    if port is not None and (scheme, port) not in {("http", 80), ("https", 443)}:
        host = f"{host}:{port}"
    return f"{scheme}://{host}{parts.path.rstrip('/')}"


class _SubmitJournal:
    """Append-only outcome journal making ``ws.submit()`` resumable (3.5).

    Every submission outcome is appended to ``.battinfo/submit-journal.jsonl``
    as it happens, with the registry it went to. On a later run, a record whose
    *identical* payload (envelope timestamps excluded) already succeeded at the
    same registry is skipped locally instead of being re-POSTed — so resuming
    an interrupted bulk submission re-sends only what is missing. The registry
    would dedup identical re-submissions anyway; the journal saves the
    round-trips. Changed content (or a new ``source_version``, e.g. a next-day
    run) hashes differently and is submitted normally. A success at one
    registry never counts for another, so a workspace rehearsed against a local
    registry still sends everything to production; entries written before the
    registry was recorded match none. ``ws.submit(resume=False)`` bypasses the
    journal.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._succeeded: dict[tuple[str, str, str], dict] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue  # a torn final line from a crash must not poison the journal
                registry = entry.get("registry_url")
                if (
                    entry.get("ok")
                    and isinstance(registry, str)
                    and registry
                    and entry.get("source_local_id")
                    and entry.get("payload_hash")
                ):
                    key = (_normalize_registry_url(registry), entry["source_local_id"], entry["payload_hash"])
                    self._succeeded[key] = entry

    def previous_success(self, source_local_id: str, payload_hash: str, *, registry_url: str) -> dict | None:
        return self._succeeded.get((_normalize_registry_url(registry_url), source_local_id, payload_hash))

    def record(self, outcome: dict, payload_hash: str, *, registry_url: str) -> None:
        import datetime as _dt  # noqa: PLC0415

        entry = {
            "ts": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "registry_url": _normalize_registry_url(registry_url),
            "source_local_id": outcome.get("source_local_id", ""),
            "title": outcome.get("title", ""),
            "ok": bool(outcome.get("ok")),
            "status": outcome.get("status", ""),
            "iri": outcome.get("iri", ""),
            "payload_hash": payload_hash,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        if entry["ok"]:
            self._succeeded[(entry["registry_url"], entry["source_local_id"], entry["payload_hash"])] = entry


def _journaled_submit(
    journal: "_SubmitJournal | None",
    payload: dict,
    url: str,
    key: str,
    title: str,
    *,
    source_local_id: str = "",
    publication_mode: str = STAGED_PUBLICATION_MODE,
    validation: dict[str, Any] | None = None,
    allow_local_files: bool = False,
) -> dict:
    """Run one submission through the resume journal (no journal → plain submit)."""
    if journal is None:
        return _do_submit(
            payload,
            url,
            key,
            title,
            source_local_id=source_local_id,
            publication_mode=publication_mode,
            validation=validation,
            allow_local_files=allow_local_files,
        )
    payload_hash = _journal_payload_hash(payload)
    previous = journal.previous_success(source_local_id, payload_hash, registry_url=url) if source_local_id else None
    if previous is not None:
        print(f"  {title}  [already submitted -- skipped; pass resume=False to re-send]")
        return {
            "title": title,
            "source_local_id": source_local_id,
            "ok": True,
            "status": "skipped_journal",
            "iri": previous.get("iri", ""),
            "error": None,
            "result": None,
            "version_bumped": None,
        }
    outcome = _do_submit(
        payload,
        url,
        key,
        title,
        source_local_id=source_local_id,
        publication_mode=publication_mode,
        validation=validation,
        allow_local_files=allow_local_files,
    )
    journal.record(outcome, payload_hash, registry_url=url)
    return outcome


def _registry_conflict_detail(exc: Exception) -> dict | None:
    """Detect a registry 409 conflict, returning its structured detail (or ``{}``).

    Prefers the parsed HTTP status code and JSON body carried by
    ``RegistryClientError`` (``status_code`` + ``response_body``); the registry
    declares the 409 body with ``conflict`` (the kind, such as
    ``canonical_identity``) / ``keys`` / ``existing_id`` / ``existing_status`` /
    ``context``. Falls back to a bare ``"409"`` substring match only when neither
    the status code nor a parseable body is available (a plain ``RuntimeError``).

    Returns:
        the parsed conflict detail dict (``{}`` when the status says 409 but the
        body is absent/opaque), or ``None`` when this is not a conflict.
    """
    status = getattr(exc, "status_code", None)
    body = getattr(exc, "response_body", None)
    detail: dict | None = None
    if isinstance(body, str) and body.strip():
        try:
            parsed = json.loads(body)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, dict):
            # FastAPI wraps HTTPException(detail=...) under a "detail" key; accept
            # either the wrapped or the bare shape (declared registry-side).
            inner = parsed.get("detail")
            candidate = inner if isinstance(inner, dict) else parsed
            if isinstance(candidate, dict) and any(
                candidate.get(k) is not None for k in ("conflict", "existing_id", "existing_status", "keys")
            ):
                detail = candidate
    if status == 409:
        return detail if detail is not None else {}
    if detail is not None:
        return detail
    # Last-resort fallback: status code and structured body both unavailable.
    if "409" in str(exc):
        return {}
    return None


def _do_submit(
    payload: dict,
    url: str,
    key: str,
    title: str,
    *,
    source_local_id: str = "",
    publication_mode: str = STAGED_PUBLICATION_MODE,
    validation: dict[str, Any] | None = None,
    allow_local_files: bool = False,
) -> dict:
    """Submit one record; return a structured outcome (never silently drop it).

    Retries once with a bumped source_version on a 409, except one with
    ``conflict == "canonical_identity"``: the record's IRI belongs to another
    publisher, so a new version would clash the same way. That outcome has
    status ``conflict``, names the IRI and its publisher (``existing_iri``,
    ``publisher_id``) and says how to rename or pin the record. Returns a dict
    with ``ok`` (True for published/validated, False for failed/rejected/errored),
    ``status``, ``error`` (the message when not ok), ``iri`` and the raw
    ``result``. A failed record is reported in the outcome, never swallowed, so
    the batch surfaces it.
    """
    import copy

    from battinfo.api import submit_publication_package

    payload.setdefault("publication_intent", {})["mode"] = publication_mode
    if validation is not None:
        payload["validation"] = validation  # the real verdict, not the builder's ok=True default
    _lift_funding_to_provenance(payload)
    bumped_version: str | None = None
    for attempt in range(2):
        try:
            result = submit_publication_package(
                payload, registry_base_url=url, api_key=key, allow_local_files=allow_local_files
            )
            raw_response = result.get("response")
            response = raw_response if isinstance(raw_response, dict) else {}
            status = response.get("status", "unknown")
            resources = response.get("resources") or []
            iri = resources[0].get("canonical_iri", "") if resources else ""
            ok = status not in ("failed", "rejected", "error")
            # Progress line: log only local/sanitised fields, never a raw registry-response value.
            # `title` is local and the status is resolved to a literal from a fixed set; the
            # canonical IRI is returned below for programmatic use but not echoed here. (CodeQL
            # conservatively treats the whole HTTP response as credential-tainted because the
            # api_key travels in the request headers, so any response-derived value read into a
            # log is flagged.)
            display_status = next((s for s in _DISPLAY_STATUSES if s == status), "unknown")
            print(f"  {title}  [{display_status}]")
            return {
                "title": title,
                "source_local_id": source_local_id,
                "ok": ok,
                "status": status,
                "iri": iri,
                "error": None,
                "result": result,
                "version_bumped": bumped_version,
            }
        except RuntimeError as exc:
            # Parse the structured 409 (status code + JSON body) over matching the
            # string "409", which could appear anywhere in an error/response body.
            conflict = _registry_conflict_detail(exc)
            if conflict is not None and conflict.get("conflict") == "canonical_identity":
                existing = str(conflict.get("canonical_iri") or conflict.get("existing_id") or "")
                owner = str(conflict.get("publisher_id") or "")
                resource = payload.get("resource")
                resource_type = resource.get("resource_type") if isinstance(resource, dict) else None
                head, hint = _canonical_identity_message(existing, owner, resource_type)
                print(f"  ERROR: {title} -- {head}")
                print(f"    {hint}")
                return {
                    "title": title,
                    "source_local_id": source_local_id,
                    "ok": False,
                    "status": "conflict",
                    "iri": "",
                    "error": f"{head} {hint}",
                    "result": None,
                    "version_bumped": bumped_version,
                    "conflict": "canonical_identity",
                    "existing_iri": existing,
                    "publisher_id": owner,
                }
            if attempt == 0 and conflict is not None:
                # The registry already holds a record for this identity. It de-duplicates an
                # identical re-submission on its side, so a 409 here means the content genuinely
                # differs — bump source_version and retry as a new version. This is surfaced
                # (printed + returned as version_bumped) rather than silently proliferating -vN.
                payload = copy.deepcopy(payload)
                ver = payload.get("source_version", "")
                bumped_version = _bump_version(ver)
                payload["source_version"] = bumped_version
                if "resource" in payload:
                    payload["resource"]["source_version"] = bumped_version  # type: ignore[index]
                # Name the conflicting record when the registry says which one.
                _existing = conflict.get("existing_id") or conflict.get("existing_status")
                _hint = f" (conflicts with {_existing})" if _existing else ""
                print(f"  {title}  [conflict{_hint} -- retrying as version {bumped_version}]")
                continue
            print(f"  ERROR: {title} -- {exc}")
            return {
                "title": title,
                "source_local_id": source_local_id,
                "ok": False,
                "status": "error",
                "iri": "",
                "error": str(exc),
                "result": None,
                "version_bumped": bumped_version,
            }
    # Unreachable in practice (the loop returns on every path); defensive for mypy.
    return {
        "title": title,
        "source_local_id": source_local_id,
        "ok": False,
        "status": "error",
        "iri": "",
        "error": "submission failed after retry",
        "result": None,
        "version_bumped": bumped_version,
    }


# Record types whose IRI comes from what they describe (a product, a protocol,
# a parameter file's content), the same for everyone, so a clash means the same
# thing was published before.
_SHARED_KEY_RESOURCE_TYPES = frozenset(
    {"cell_spec", "test_spec", "test_protocol", "material_spec", "electrode_spec", "equipment_spec", "parameter_set"}
)


def _canonical_identity_message(iri: str, publisher: str, resource_type: str | None) -> tuple[str, str]:
    """The line and the advice for a record whose IRI another publisher holds."""
    owner = f"publisher {publisher!r}" if publisher else "another publisher"
    head = f"{iri or 'its IRI'} is already registered to {owner}; not retried as a new version."
    if resource_type in _SHARED_KEY_RESOURCE_TYPES:
        hint = (
            "This record's IRI comes from what it describes (a product's manufacturer and model, a "
            "protocol, a parameter file's content), so that publisher has published the same thing. "
            "Reference theirs with ws.load(ws.search(...)) instead of submitting a copy. If yours "
            "describes something else, correct its identity fields, or pin an IRI of your own with id= "
            "or uid=."
        )
    else:
        hint = (
            "Your record mints the same IRI as theirs from the same identity fields: labels such as "
            "serial 'S1' or name 'C01' are not scoped to a lab until BattINFO 0.9. Give it an identity "
            "only your lab uses and save again: the serial printed on the cell or a lab-specific one "
            "(ws.add('cell', ..., serial_numbers=[...])), a lab-specific name for a cell without a "
            "serial (names=[...]), or an IRI of your own pinned with iris=[...] (iri= or uid= for a "
            "test). A cell's tests and datasets get new IRIs with it. If the record is yours, submit "
            "with that publisher's key instead."
        )
    return head, hint


def _bump_version(ver: str) -> str:
    """Increment a trailing counter on a version string: '2026-05-29' → '2026-05-29-v2'."""
    import re

    m = re.search(r"-v(\d+)$", ver)
    if m:
        return ver[: m.start()] + f"-v{int(m.group(1)) + 1}"
    return ver + "-v2"


def _import_resolve_source(source: str, *, sandbox: bool = False, token: str | None = None) -> str:
    """Return raw JSON-LD text from a Zenodo record ID, an http(s) URL, or a local file path.

    *token* goes only over https to the Zenodo API host of the environment
    *sandbox* chooses (``zenodo.org``, or ``sandbox.zenodo.org``), for the
    record's file list and for a file link on that host: never to another
    host, never over plain http, and never on a redirect (see
    :func:`_import_fetch`). A source URL whose scheme is not http or https is
    refused, and so is a link in Zenodo's file list that is not an http(s) URL;
    such a link is never read as a local path.
    """
    from urllib.parse import urlparse  # noqa: PLC0415

    api_host = "sandbox.zenodo.org" if sandbox else "zenodo.org"

    # Local file
    p = Path(source)
    if p.exists():
        return p.read_text(encoding="utf-8")

    # URL
    scheme = urlparse(source).scheme.lower()
    if scheme in ("http", "https"):
        return _import_fetch(source, token=token, api_host=api_host, timeout=30)

    # Zenodo record ID (numeric string)
    if source.isdigit():
        api_url = f"https://{api_host}/api/records/{source}/files"
        files = json.loads(_import_fetch(api_url, token=token, api_host=api_host, timeout=15))

        # Find the linked-data document (current battinfo.json, or legacy battinfo.jsonld).
        entry = next(
            (
                f
                for f in (files.get("entries") or [])
                if f.get("key") in (BATTINFO_LD_FILENAME, BATTINFO_LD_FILENAME_LEGACY)
            ),
            None,
        )
        if entry is None:
            raise RuntimeError(
                f"No {BATTINFO_LD_FILENAME} found in Zenodo record {source}. "
                "Is this a battinfo-published record? "
                f"({BATTINFO_LD_FILENAME} is the standard entry point for battinfo Zenodo deposits.)"
            )
        download_url = entry.get("links", {}).get("content") or entry.get("url", "")
        if not _import_web_url(download_url):
            raise RuntimeError(
                f"Zenodo record {source} links its {entry.get('key')} at {download_url!r}, which is "
                "not an http(s) URL, so nothing was read from it."
            )
        return _import_fetch(download_url, token=token, api_host=api_host, timeout=30)

    # A URL of any other scheme (a one-letter scheme is a Windows drive).
    if len(scheme) > 1:
        raise ValueError(
            f"Cannot import from {source!r}: ws.import_() reads only http and https URLs. "
            "Pass a Zenodo record ID, an http(s) URL, or the path of a local file."
        )
    raise ValueError(f"Cannot resolve import source {source!r}. Pass a Zenodo record ID, a URL, or a local file path.")


def _import_fetch(url: str, *, token: str | None, api_host: str, timeout: float) -> str:
    """The text at the http(s) *url*, sent with *token* only where a Zenodo token may go.

    The token goes along only when urllib will connect to *api_host* over
    https. It is added as an unredirected header, which urllib leaves behind
    when it follows a redirect: urllib copies every other header onto the
    request it is redirected to, whatever host that request goes to.
    """
    import urllib.request  # noqa: PLC0415

    request = urllib.request.Request(url, headers={"User-Agent": "battinfo-client/1.0"})
    if token:
        if request.type == "https" and request.host.lower() in (api_host, f"{api_host}:443"):
            request.add_unredirected_header("Authorization", f"Bearer {token}")
        else:
            warnings.warn(
                f"The Zenodo token was not sent to {url}: ws.import_() sends it only over https to {api_host}.",
                stacklevel=4,
            )
    with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310
        return resp.read().decode("utf-8")


def _test_kind_values() -> list[str]:
    """Return the canonical test-kind strings from the BatteryTestType enum."""
    from battinfo.bundle import BatteryTestType  # noqa: PLC0415

    return [m.value for m in BatteryTestType]


# Common synonyms accepted as input and mapped to canonical BatteryTestType values.
# Keeps the authoring API forgiving without polluting the canonical vocabulary.
_TEST_KIND_ALIASES: dict[str, str] = {
    "calendar_aging": "calendar_ageing",  # American spelling
    "calendar_age": "calendar_ageing",
    "aging": "calendar_ageing",
    "ageing": "calendar_ageing",
    "rate": "rate_capability",
    "rate_test": "rate_capability",
    "cycle": "cycling",
    "cycle_life": "cycling",
    "capacity": "capacity_check",
    "ocv": "quasi_ocv",
    "impedance_spectroscopy": "eis",
}


def _test_kind_hint() -> str:
    return "Valid kinds: " + ", ".join(_test_kind_values()) + "."


def _draft_spec_iri(draft_id: Any, draft_uid: Any, source: str) -> str | None:
    """The spec IRI a draft file pins with ``"id"`` and/or ``"uid"``, or ``None``."""
    from battinfo.api._shared import SPEC_IRI_RE, _normalized_dashed_uid  # noqa: PLC0415

    pinned: str | None = None
    if draft_id:
        text = str(draft_id).strip()
        if not SPEC_IRI_RE.fullmatch(text):
            raise ValueError(
                f"{source}: 'id' {draft_id!r} is not a spec IRI; expected "
                "https://w3id.org/battinfo/spec/xxxx-xxxx-xxxx-xxxx."
            )
        pinned = text
    if draft_uid:
        from_uid = record_iri("spec", _normalized_dashed_uid(str(draft_uid)))
        if pinned is not None and pinned != from_uid:
            raise ValueError(f"{source}: 'id' and 'uid' name different specs; keep one.")
        pinned = from_uid
    return pinned


def _closest_kind(key: str, valid: set[str]) -> str | None:
    matches = difflib.get_close_matches(key, sorted(valid), n=1, cutoff=0.6)
    return matches[0] if matches else None


def _normalize_test_kind(kind: str) -> str:
    """Validate and canonicalise a test kind against BatteryTestType.

    Case- and separator-insensitive, and accepts common synonyms
    (``"rate"`` → ``"rate_capability"``, ``"calendar_aging"`` →
    ``"calendar_ageing"``).  Raises ``ValueError`` with the full list of
    valid kinds — and the closest suggestion — on no match.
    """
    raw = str(kind).strip()
    key = re.sub(r"[\s\-]+", "_", raw).lower()
    valid = set(_test_kind_values())
    if key in valid:
        return key
    if key in _TEST_KIND_ALIASES:
        return _TEST_KIND_ALIASES[key]
    compact = key.replace("_", "")
    for v in valid:
        if v.replace("_", "") == compact:
            return v
    suggestion = _closest_kind(key, valid)
    raise ValueError(
        f"{kind!r} is not a valid test kind. "
        + _test_kind_hint()
        + (f"  Did you mean {suggestion!r}?" if suggestion else "")
    )


def _import_test_kind_from_technique(technique: str) -> str:
    """Infer a BattINFO test kind from a measurement technique string."""
    t = technique.lower()
    if "cycling" in t or "cycle" in t:
        return "cycling"
    if "capacity" in t or "discharge" in t:
        return "capacity_check"
    if "rate" in t:
        return "rate_capability"
    if "hppc" in t:
        return "hppc"
    if "eis" in t or "impedance" in t:
        return "eis"
    if "gitt" in t:
        return "gitt"
    return "other"


@dataclass
class ZenodoResult:
    """Result of ``ws.zenodo()``."""

    record_id: str
    doi: str
    record_url: str
    draft_url: str
    published: bool
    is_new_version: bool


_DEFAULT_REGISTRY_URL = "https://battinfo-registry.onrender.com"


def workspace(
    root: str | Path = ".",
    records_repo: str | Path | None = None,
    registry_url: str | None = _UNSET,
) -> AuthoringWorkspace:
    """Open (or create) a BattINFO workspace for authoring records.

    Opening a workspace reads ``{root}/.battinfo/credentials`` into the
    workspace object, and the workspace reads it again when it changes.
    Nothing is copied into ``os.environ``, so two workspaces open in one Python
    session each use their own credentials; check them with
    ``ws.credentials_status()`` or ``ws.has_credential(name)``.

    Parameters
    ----------
    root:
        Workspace directory. Records are written to ``{root}/.battinfo/records/``.
        Defaults to the current working directory.
    registry_url:
        Base URL of the battinfo-registry API.  Left out, it is
        ``BATTINFO_REGISTRY_URL`` from the environment, then from
        ``{root}/.battinfo/credentials``, then the canonical production
        registry, the same default ``battinfo.registry.Registry()`` uses.  It
        is looked up at each use, so a change to either takes effect without
        reopening the workspace.  Pass
        ``None`` to force offline/local-clone mode: no registry lookups, and
        no registry for :meth:`~AuthoringWorkspace.login`,
        :meth:`~AuthoringWorkspace.submit` or
        :meth:`~AuthoringWorkspace.status` unless ``BATTINFO_REGISTRY_URL``
        is set or the call passes its own ``registry_url``.
    records_repo:
        Path to a local ``battinfo-records`` clone for offline or development use.
        Auto-detected from sibling directories or ``BATTINFO_RECORDS`` env var
        if not given.  Only used when the registry is unreachable or ``registry_url``
        is ``None``.
    """
    return AuthoringWorkspace(root=root, records_repo=records_repo, registry_url=registry_url)
