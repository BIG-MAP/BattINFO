"""battinfo.workspace() — simplified authoring API.

Usage::

    import battinfo

    ws = battinfo.workspace()
    ws.search("duracell mn2400")
    ws.template("cell-spec", manufacturer="Duracell", model="MN2400")
    # edit the generated JSON, then:
    spec = ws.load("Duracell-MN2400.cell-spec.json")
    ws.add("cell-instance", spec=spec, from_file="cell_iris.json", match="duracell-mn2400")
    ws.add("test", kind="capacity_check", datasets="bdf/*.bdf.parquet",
           protocol="constant current discharge", instrument="NEWARE BTS82 cycler")
    ws.save()
"""
from __future__ import annotations

import difflib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from battinfo._jsonio import atomic_write_text as _atomic_write_text
from battinfo._jsonio import read_json as _read_json
from battinfo.entities import record_set_dirs

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
    "nominal_voltage":                        {"value": None, "unit": "V"},
    "nominal_capacity":                       {"value": None, "unit": "Ah"},
    "discharging_cutoff_voltage":             {"value": None, "unit": "V"},
    "mass":                                   {"value": None, "unit": "g"},
    "diameter":                               {"value": None, "unit": "mm"},
    "height":                                 {"value": None, "unit": "mm"},
    "maximum_continuous_discharging_current": {"value": None, "unit": "A"},
    "internal_resistance":                    {"value": None, "unit": "Ohm"},
    "minimum_discharging_temperature":        {"value": None, "unit": "degC"},
    "maximum_discharging_temperature":        {"value": None, "unit": "degC"},
    "minimum_storage_temperature":            {"value": None, "unit": "degC"},
    "maximum_storage_temperature":            {"value": None, "unit": "degC"},
}

# Coin cells: same shape as cylindrical (diameter + height), typically primary
_COIN_PRIMARY_SPECS: dict[str, dict] = {
    "nominal_voltage":                        {"value": None, "unit": "V"},
    "nominal_capacity":                       {"value": None, "unit": "Ah"},
    "discharging_cutoff_voltage":             {"value": None, "unit": "V"},
    "mass":                                   {"value": None, "unit": "g"},
    "diameter":                               {"value": None, "unit": "mm"},
    "height":                                 {"value": None, "unit": "mm"},
    "maximum_continuous_discharging_current": {"value": None, "unit": "A"},
    "internal_resistance":                    {"value": None, "unit": "Ohm"},
    "minimum_discharging_temperature":        {"value": None, "unit": "degC"},
    "maximum_discharging_temperature":        {"value": None, "unit": "degC"},
    "minimum_storage_temperature":            {"value": None, "unit": "degC"},
    "maximum_storage_temperature":            {"value": None, "unit": "degC"},
}

# Prismatic / pouch cells: height + width + thickness (no diameter)
_PRISMATIC_SPECS: dict[str, dict] = {
    "nominal_voltage":                        {"value": None, "unit": "V"},
    "nominal_capacity":                       {"value": None, "unit": "Ah"},
    "discharging_cutoff_voltage":             {"value": None, "unit": "V"},
    "mass":                                   {"value": None, "unit": "g"},
    "height":                                 {"value": None, "unit": "mm"},
    "width":                                  {"value": None, "unit": "mm"},
    "thickness":                              {"value": None, "unit": "mm"},
    "maximum_continuous_discharging_current": {"value": None, "unit": "A"},
    "internal_resistance":                    {"value": None, "unit": "Ohm"},
    "minimum_discharging_temperature":        {"value": None, "unit": "degC"},
    "maximum_discharging_temperature":        {"value": None, "unit": "degC"},
    "minimum_storage_temperature":            {"value": None, "unit": "degC"},
    "maximum_storage_temperature":            {"value": None, "unit": "degC"},
}

_CYLINDRICAL_SECONDARY_SPECS: dict[str, dict] = {
    "nominal_voltage":                      {"value": None, "unit": "V"},
    "nominal_capacity":                     {"value": None, "unit": "Ah"},
    "charging_voltage":                     {"value": None, "unit": "V"},
    "discharging_cutoff_voltage":           {"value": None, "unit": "V"},
    "mass":                                 {"value": None, "unit": "g"},
    "diameter":                             {"value": None, "unit": "mm"},
    "height":                               {"value": None, "unit": "mm"},
    "nominal_continuous_charging_current":  {"value": None, "unit": "A"},
    "maximum_continuous_charging_current":  {"value": None, "unit": "A"},
    "nominal_continuous_discharging_current": {"value": None, "unit": "A"},
    "maximum_continuous_discharging_current": {"value": None, "unit": "A"},
    "specific_energy":                      {"value": None, "unit": "Wh/kg"},
    "energy_density":                       {"value": None, "unit": "Wh/L"},
    "cycle_life":                           {"value": None, "unit": "1"},
    "internal_resistance":                  {"value": None, "unit": "Ohm"},
    "minimum_charging_temperature":         {"value": None, "unit": "degC"},
    "maximum_charging_temperature":         {"value": None, "unit": "degC"},
    "minimum_discharging_temperature":      {"value": None, "unit": "degC"},
    "maximum_discharging_temperature":      {"value": None, "unit": "degC"},
    "minimum_storage_temperature":          {"value": None, "unit": "degC"},
    "maximum_storage_temperature":          {"value": None, "unit": "degC"},
}

# Primary chemistries
_PRIMARY_CHEMISTRIES = {"zn-mno2", "li-primary", "znmno2", "alkaline", "zinc-carbon"}


def _default_specs_for(format_: str, chemistry: str) -> dict[str, dict]:
    fmt  = (format_  or "").lower()
    chem = (chemistry or "").lower()
    if fmt in ("prismatic", "pouch"):
        return dict(_PRISMATIC_SPECS)
    if fmt == "coin":
        return dict(_COIN_PRIMARY_SPECS)
    # cylindrical — primary vs secondary
    if chem in _PRIMARY_CHEMISTRIES:
        return dict(_CYLINDRICAL_PRIMARY_SPECS)
    return dict(_CYLINDRICAL_SECONDARY_SPECS)


def _short_id(name: str) -> str | None:
    """Extract the 6-char short ID from a batch name or filename stem."""
    m = _SHORT_ID_RE.search(name)
    return m.group(1) if m else None


def _serial_matches(token: str, serial: str | None) -> bool:
    """True if *token* identifies *serial* — by exact match or shared 6-char short ID.

    Lets a filename stem, a short ID, or a full serial all resolve to the same cell.
    """
    if not serial or not token:
        return False
    if token == serial:
        return True
    return (_short_id(token) or token) == (_short_id(serial) or serial)


# ── Resource-type vocabulary ──────────────────────────────────────────────────
# User-facing `type=` values map to the registry's canonical resource_type. Users
# speak "cell-spec"/"test-spec"; storage/IRIs keep cell_spec/test_protocol.
_RESOURCE_TYPE_CANON: dict[str, str] = {
    "cell-spec": "cell_spec", "cell_spec": "cell_spec", "cellspec": "cell_spec",
    "spec": "cell_spec",
    "cell": "cell", "cell-instance": "cell", "cell_instance": "cell", "instance": "cell",
    "test-spec": "test_protocol", "test_spec": "test_protocol",
    "test-protocol": "test_protocol", "test_protocol": "test_protocol",
    "test": "test",
    "dataset": "dataset", "datasets": "dataset",
}
# Canonical registry resource_type -> the user-facing label we surface in results.
_RESOURCE_TYPE_DISPLAY: dict[str, str] = {
    "cell_spec": "cell-spec", "cell": "cell",
    "test_protocol": "test-spec", "test": "test", "dataset": "dataset",
}


def _canon_type(value: str) -> str:
    """Map a user-facing ``type=`` value to the registry's canonical resource_type."""
    key = str(value).strip().lower()
    if key in _RESOURCE_TYPE_CANON:
        return _RESOURCE_TYPE_CANON[key]
    raise ValueError(
        f"Unknown type {value!r}. Valid: cell-spec, cell, test-spec, test, dataset."
    )


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
# BattINFO workspace credentials - loaded automatically by battinfo.workspace().
# Keep this out of version control (.battinfo/credentials is git-ignored for you).
#
# Quickest path: do NOT edit this file by hand - just run
#     ws.login(api_key="YOUR_KEY")
# which fills in your workspace and publisher automatically.

BATTINFO_API_KEY       =

# Filled in automatically by ws.login(); override only if you know you need to.
BATTINFO_WORKSPACE_ID  = battinfo-records
BATTINFO_PUBLISHER_ID  = battinfo-authoring
BATTINFO_ADMIN_TOKEN   =

# Optional - only needed for ws.upload() (Cloudflare R2 dataset storage).
R2_ENDPOINT            =
R2_ACCESS_KEY_ID       =
R2_SECRET_ACCESS_KEY   =
R2_BUCKET              = battinfo-public
R2_PUBLIC_BASE_URL     =

# Optional - only needed for ws.zenodo() archival.
ZENODO_API_TOKEN       =
ZENODO_SANDBOX_TOKEN   =
"""

_CREDENTIAL_PREFIXES = ("BATTINFO_", "R2_", "ZENODO_")


def _load_credentials(path: Path) -> None:
    """Load BATTINFO_* and R2_* key=value pairs from *path* into os.environ."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if any(key.startswith(p) for p in _CREDENTIAL_PREFIXES) and value and key not in os.environ:
            os.environ[key] = value


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
    "conformant":     "earl:passed",
    "non-conformant": "earl:failed",
    "unknown":        "earl:cantTell",
}

_UNIX_EPOCH = "1970-01-01T00:00:00Z"

# Filename for the consolidated linked-data document in a Zenodo deposit. Uses a plain
# ``.json`` extension (not ``.jsonld``) so it previews inline in the Zenodo web viewer;
# the content is still JSON-LD (carries @context/@graph).
BATTINFO_LD_FILENAME = "battinfo.json"
# Legacy name in records published before the switch — still accepted on import.
BATTINFO_LD_FILENAME_LEGACY = "battinfo.jsonld"

# Battery Data Format (BDF) CSVW table schema. A BDF data file declares
# conformance to this so a consumer can resolve every column name, type and unit
# from one link instead of a per-record data dictionary. The VERSIONED IRI is
# used deliberately: an archived deposit must keep pointing at the exact schema
# version it was built against (the floating `.../schema` IRI tracks latest).
BDF_TABLE_SCHEMA_IRI = (
    "https://w3id.org/battery-data-alliance/ontology/battery-data-format/1.2.0/schema"
)

# Loaded once at import time; used as the base for all JSON-LD context dicts.
# Generated by `python scripts/assemble_context.py` from schema/*.yaml.
_RECORDS_CONTEXT: dict = json.loads(
    (Path(__file__).parent / "data" / "context" / "records.context.json")
    .read_text(encoding="utf-8")
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


def _unix_to_iso(ts: int | None) -> str | None:
    """Convert a Unix timestamp (seconds) to an ISO-8601 datetime string."""
    if ts is None:
        return None
    import datetime
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _plan_zenodo_deposit(
    existing_id: str | None,
    existing_published: bool,
    record_id: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Decide how a ``ws.zenodo()`` call maps to a Zenodo deposit action.

    Re-running ``zenodo()`` on a workspace that already has a record should *not*
    error — it should continue the obvious next step, with a warning:

    * explicit ``record_id`` given, or no record yet  → use it as-is (caller forks a
      new version when a record_id is set, or creates a brand-new record otherwise);
    * existing record is **published**  → fork a NEW VERSION from it;
    * existing record is an **open draft**  → UPDATE that draft in place (Zenodo allows
      only one open draft per concept, so forking again would fail).

    Returns ``(record_id, reuse_draft_id, warning)`` — exactly one of
    ``record_id``/``reuse_draft_id`` is set when versioning an existing record;
    ``warning`` is a user-facing message or None.
    """
    if record_id is not None or not existing_id:
        return record_id, None, None
    if existing_published:
        return existing_id, None, (
            f"This workspace already has a published Zenodo record ({existing_id}); "
            "creating a NEW VERSION. (Delete .battinfo/zenodo.json to start a "
            "brand-new record instead.)"
        )
    return None, existing_id, (
        f"This workspace already has an unpublished draft ({existing_id}); updating "
        "that draft in place rather than creating a new record."
    )


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
        return (start, end) if end >= start else (end, start)
    except Exception:
        return None


def _typed_date(value: str) -> dict:
    """Wrap a date string as a typed JSON-LD value so consumers can parse it.

    Picks the xsd datatype from the string's shape: ``YYYY`` → gYear,
    ``YYYY-MM`` → gYearMonth, an ISO timestamp → dateTime, else date.
    """
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
            f"invalid ORCID iD: {value!r}. Expected 0000-0002-1825-0097 "
            "(or the full https://orcid.org/… URL)."
        )
    return token


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


def _property_value(name: str, value: Any, group: str = "") -> dict:
    """Build a schema:PropertyValue for a structured test condition/setpoint.

    Handles scalars, ``{value, unit}`` quantity dicts, and other mappings (stringified).
    ``group`` (conditions/setpoints/termination_criteria) is recorded as schema:propertyID
    so consumers can tell a setpoint from a termination criterion.
    """
    node: dict = {"@type": "schema:PropertyValue", "schema:name": name}
    if group:
        node["schema:propertyID"] = group
    if isinstance(value, dict):
        if value.get("value") is not None:
            node["schema:value"] = value["value"]
            if value.get("unit"):
                node["schema:unitText"] = value["unit"]
        else:
            node["schema:value"] = json.dumps(value, ensure_ascii=False, sort_keys=True)
    else:
        node["schema:value"] = value
    return node


def _provider(creators: list[dict] | None, contributors: list[dict] | None) -> tuple[str, str]:
    """Best-effort publishing organisation: the first affiliation (name, ror) among agents."""
    for c in (creators or []) + (contributors or []):
        if c.get("affiliation"):
            return c["affiliation"], c.get("affiliation_ror", "")
    return "", ""


# Record-type subdirectories under a workspace's records ``examples/`` folder.
# Derived from the entity registry so new record types are picked up automatically.
_RECORD_SET_DIRS = record_set_dirs()


def _read_record_sets(examples: Path) -> dict[str, list[dict]]:
    """Load a workspace's saved records into the canonical ``record_sets`` mapping.

    Returns ``{subdir: [record_dict, ...]}`` for each record type, sorted by filename
    so the assembled graph is deterministic. This is the on-disk source feeding the
    shared, input-agnostic builder :meth:`AuthoringWorkspace._assemble_zenodo_jsonld`.
    """
    record_sets: dict[str, list[dict]] = {}
    for name in _RECORD_SET_DIRS:
        recs: list[dict] = []
        subdir = examples / name
        if subdir.exists():
            for f in sorted(subdir.glob("*.json")):
                try:
                    recs.append(_read_json(f))
                except (OSError, ValueError) as exc:
                    # Fail closed: silently skipping a corrupt/BOM record would publish an
                    # incomplete Zenodo graph with records missing and no error (R-6, R-10).
                    raise ValueError(
                        f"Cannot assemble the record bundle: {f} is unreadable ({exc})."
                    ) from exc
        record_sets[name] = recs
    return record_sets


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
                "rdfs:comment": _label
                + (f" — {dev['description']}" if dev.get("description") else ""),
            }
            if dev.get("category"):
                dev_node["battinfo:deviationCategory"] = dev["category"]
            if dev.get("type"):
                dev_node["battinfo:affectedProperty"] = dev["type"]
            if dev.get("description"):
                dev_node["schema:description"] = dev["description"]
            iso_ts = _unix_to_iso(dev.get("occurred_at"))
            if iso_ts:
                dev_node["prov:startedAtTime"] = iso_ts
            duration_s = dev.get("duration_s")
            if duration_s is not None:
                m, s = divmod(int(duration_s), 60)
                h, m = divmod(m, 60)
                dev_node["schema:duration"] = (
                    f"PT{h}H{m}M{s}S" if h else (f"PT{m}M{s}S" if m else f"PT{s}S")
                )
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
                f"conformance status {status!r} is not valid. "
                f"Use one of: {', '.join(CONFORMANCE_STATUS_VALUES)}."
            )
        return Conformance.from_record(value)
    raise TypeError("conformance must be a status string, a dict, or a Conformance.")


# ── Cycler format support (via the batterydf library) ────────────────────────
# Extensions safe to auto-detect: instrument-native and unlikely to collide with
# unrelated files in the workspace root.  .csv/.txt are deliberately NOT
# auto-detected (too ambiguous) — pass an explicit pattern or use convert_csv().
_CONVERT_AUTODETECT: dict[str, str] = {
    ".ndax": "NEWARE",
    ".nda":  "NEWARE (legacy)",
    ".mpt":  "Biologic (EC-Lab text export)",
    ".xlsx": "Excel",
    ".mat":  "MATLAB",
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
]

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
    ("step_index", "step index within a cycle"),
    ("charging_capacity_ah", "charge capacity (Ah)"),
    ("discharging_capacity_ah", "discharge capacity (Ah)"),
    ("charging_energy_wh", "charge energy (Wh)"),
    ("discharging_energy_wh", "discharge energy (Wh)"),
    ("ambient_temperature_celsius", "ambient temperature (degC)"),
    ("internal_resistance_ohm", "internal resistance (Ohm)"),
]


class AuthoringWorkspace:
    """Simplified workspace for authoring BattINFO records.

    Wraps the lower-level :class:`battinfo.workspace.Workspace` with a
    concise API designed for interactive / notebook use.
    """

    def __init__(
        self,
        root: str | Path = ".",
        records_repo: str | Path | None = None,
        registry_url: str | None = None,
    ):
        from battinfo._workspace import Workspace

        self._root = Path(root).resolve()
        self._records_root = self._root / ".battinfo" / "records"
        self._ws = Workspace(root=self._records_root)
        self._records_repo = (
            Path(records_repo).resolve() if records_repo else _find_records_repo(self._root)
        )
        self._registry_url = registry_url.rstrip("/") if registry_url else None
        _load_credentials(self._root / ".battinfo" / "credentials")
        # name -> CellInstance, keyed by short_id for test matching
        self._cells_by_short_id: dict[str, Any] = {}
        # in-memory search cache; populated lazily from registry API or local index
        self._search_cache: list[dict] | None = None
        # converted-file → original-source mapping (lazy-loaded from manifest)
        self._conversion_sources: dict[str, str] | None = None
        # paths written by the most recent ws.save() — submit() uses this to
        # avoid re-submitting records from previous sessions in the same directory
        self._session_paths: set[Path] = set()
        # workspace-level funding project (grant); lazily loaded from
        # .battinfo/workspace.json on first access via _get_project()
        self._project_ref: ProjectRef | None = None
        self._project_loaded = False
        # workspace-level contributor (ORCID); lazily loaded from
        # .battinfo/workspace.json on first access via _get_contributor()
        self._contributor_ref: ContributorRef | None = None
        self._contributor_loaded = False

    # ── Public API ─────────────────────────────────────────────────────────────

    def setup(self) -> Path:
        """Create a credentials file and explain how to log in.

        Run once per project.  Then either run ``ws.login(api_key=...)`` (which
        fills in your workspace/publisher automatically) or edit the generated
        file by hand.  The file is git-ignored and loaded on every
        ``battinfo.workspace()`` call.

        Example::

            ws.setup()
            ws.login(api_key="YOUR_KEY")
        """
        self._ensure_gitignore()
        cred_path = self._credentials_path()
        if cred_path.exists():
            print(f"Credentials file already exists: {cred_path}")
        else:
            cred_path.parent.mkdir(parents=True, exist_ok=True)
            cred_path.write_text(_CREDENTIALS_TEMPLATE, encoding="utf-8")
            print(f"Created: {cred_path}")
        print("\n  Next: get an API key from the registry settings page, then run")
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
        """Merge key=value pairs into .battinfo/credentials, preserving other lines."""
        path = self._credentials_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        source = path.read_text(encoding="utf-8") if path.exists() else _CREDENTIALS_TEMPLATE
        remaining = dict(updates)
        out: list[str] = []
        for line in source.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.split("=", 1)[0].strip()
                if key in remaining:
                    out.append(f"{key:22} = {remaining.pop(key)}")
                    continue
            out.append(line)
        for key, value in remaining.items():
            out.append(f"{key:22} = {value}")
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
        # A-6: this file holds API keys / R2 secrets / Zenodo tokens — restrict to owner-only.
        # Best-effort: a no-op on Windows and filesystems without POSIX permission bits.
        try:
            import os
            os.chmod(path, 0o600)
        except OSError:
            pass
        return path

    def login(self, api_key: str, *, registry_url: str | None = None) -> dict:
        """Log in with a registry API key and cache your workspace identity.

        Fetches your publisher/workspace identity from the registry so you never
        have to know workspace or publisher IDs, and stores the key in
        ``.battinfo/credentials`` (git-ignored) for future sessions.  Get an API
        key from the registry settings page.

        If the registry does not expose a profile endpoint yet, the key is still
        saved and sensible defaults are used — everything keeps working.

        Example::

            ws.login(api_key="bk_live_...")
            ws.whoami()
        """
        import urllib.error
        import urllib.request

        api_key = (api_key or "").strip()
        if not api_key:
            raise ValueError("api_key is required. Get one from the registry settings page.")
        url = (registry_url or self._registry_url or os.environ.get("BATTINFO_REGISTRY_URL")
               or _DEFAULT_REGISTRY_URL).rstrip("/")

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
                    "Registry rejected the API key (HTTP "
                    f"{exc.code}). Check the key and try again."
                ) from None
            profile = {}  # 404 / older registry without /me — degrade gracefully
        except Exception:
            profile = {}  # network/registry unavailable — degrade gracefully

        wid = profile.get("workspace_id") or os.environ.get("BATTINFO_WORKSPACE_ID") or "battinfo-records"
        pid = profile.get("publisher_id") or os.environ.get("BATTINFO_PUBLISHER_ID") or "battinfo-authoring"
        name = profile.get("display_name") or pid

        os.environ["BATTINFO_API_KEY"] = api_key
        os.environ["BATTINFO_WORKSPACE_ID"] = wid
        os.environ["BATTINFO_PUBLISHER_ID"] = pid
        self._ensure_gitignore()
        path = self._set_credentials({
            "BATTINFO_API_KEY": api_key,
            "BATTINFO_WORKSPACE_ID": wid,
            "BATTINFO_PUBLISHER_ID": pid,
        })

        if profile:
            print(f"Logged in as {name} (workspace: {wid}).")
        else:
            print(f"API key saved. Using workspace {wid!r}, publisher {pid!r}.")
            print("  (Registry profile lookup unavailable - edit BATTINFO_WORKSPACE_ID "
                  "in .battinfo/credentials if these defaults are wrong.)")
        print(f"  Credentials: {path}")
        return {"workspace_id": wid, "publisher_id": pid, "display_name": name, "registry_url": url}

    def whoami(self, *, registry_url: str | None = None) -> dict:
        """Print the identity associated with the current API key."""
        import urllib.request

        key = os.environ.get("BATTINFO_API_KEY")
        if not key:
            print("Not logged in. Run ws.login(api_key='...').")
            return {}
        url = (registry_url or self._registry_url or os.environ.get("BATTINFO_REGISTRY_URL")
               or _DEFAULT_REGISTRY_URL).rstrip("/")
        try:
            req = urllib.request.Request(
                f"{url}/me",
                headers={"X-Battinfo-API-Key": key, "User-Agent": "battinfo-client/1.0"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
                profile = json.loads(resp.read().decode())
            print(f"  {profile.get('display_name') or profile.get('publisher_id')}")
            print(f"  workspace:  {profile.get('workspace_id')}")
            print(f"  publisher:  {profile.get('publisher_id')}")
            return profile
        except Exception as exc:
            wid = os.environ.get("BATTINFO_WORKSPACE_ID", "battinfo-records")
            pid = os.environ.get("BATTINFO_PUBLISHER_ID", "battinfo-authoring")
            print(f"  (registry profile unavailable: {exc})")
            print(f"  workspace:  {wid}")
            print(f"  publisher:  {pid}")
            return {"workspace_id": wid, "publisher_id": pid}

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
                ("name", name), ("funder", funder), ("program", program),
                ("acronym", acronym), ("id", id),
            )
            if value is not None
        }
        current = self._get_project()

        # Getter: no identifier supplied.
        if identifier is None:
            if current is None:
                print('No project set. Tag this workspace with a grant, e.g.:\n'
                      '    ws.project("101103997")')
                return None
            ref = current
            if overrides or refresh:
                ref = self._resolve_and_store(current.identifier, overrides=overrides,
                                              base=current, refresh=True)
            self._print_project(ref)
            return ref.funding_block()

        # Setter: identifier supplied.
        identifier = str(identifier).strip()
        if not identifier:
            raise ValueError("project identifier must be a non-empty string.")
        base = current if (current is not None and current.identifier == identifier) else None
        ref = self._resolve_and_store(identifier, overrides=overrides, base=base,
                                      refresh=refresh or base is None)
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
            fields.update({
                key: getattr(base, key)
                for key in ("name", "funder", "program", "acronym", "id")
                if getattr(base, key)
            })
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
        ref = ProjectRef(identifier=identifier, resolved=resolved,
                         manual=sorted(manual), **fields)
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
            print("  (descriptive metadata not resolved — offline, or grant not in")
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

    def _stamp_project_funding(self, result: dict) -> int:
        """Stamp the workspace's ``funding`` block onto every record just written.

        Called by :meth:`save` after the records are serialized.  Re-stamps the
        full set each save, so records authored before the project was assigned
        are back-filled on the next save.  No-op when no project is set (existing
        records are left untouched — clearing the project does not strip them).
        """
        block = self._funding_block()
        if block is None:
            return 0
        stamped = 0
        for key in ("cell_specs", "cell_instances", "tests", "datasets", "test_specs"):
            for item in result.get(key, []):
                path = item.get("path") if isinstance(item, dict) else str(item)
                if not path:
                    continue
                p = Path(path)
                if not p.exists():
                    continue
                record = json.loads(p.read_text(encoding="utf-8"))
                if record.get("funding") == block:
                    continue
                record["funding"] = block
                _atomic_write_text(p, json.dumps(record, indent=2, ensure_ascii=False) + "\n")
                stamped += 1
        return stamped

    def contributor(
        self,
        orcid: str | None = None,
        *,
        name: str | None = None,
        affiliation: str | None = None,
        clear: bool = False,
    ) -> dict | None:
        """Tag this workspace with the contributor's ORCID for attribution.

        Once set, the contributor is added to every dataset you ``save()`` (as a
        ``creators`` entry carrying the ORCID), so platform contributions can be
        traced back to a person. The ORCID is the durable key; ``name`` is shown
        in the record.

        Returns the record-level ``creators`` entry (or ``None`` when cleared or
        unset).

        Examples
        --------
        ::

            ws.contributor("0000-0002-1825-0097", name="Jane Researcher")
            ws.contributor()                       # show the current contributor
            ws.contributor(affiliation="SINTEF")   # fill in / update a field
            ws.contributor(clear=True)             # remove the contributor tag
        """
        if clear:
            self._set_contributor(None)
            print("Workspace contributor cleared.")
            return None

        current = self._get_contributor()

        # Getter (no ORCID supplied): optionally patch name/affiliation in place.
        if orcid is None:
            if current is None:
                print('No contributor set. Tag this workspace with your ORCID, e.g.:\n'
                      '    ws.contributor("0000-0002-1825-0097", name="Your Name")')
                return None
            if name is not None or affiliation is not None:
                current = ContributorRef(
                    orcid=current.orcid,
                    name=name if name is not None else current.name,
                    affiliation=affiliation if affiliation is not None else current.affiliation,
                )
                self._set_contributor(current)
            self._print_contributor(current)
            return current.person_block()

        # Setter: ORCID supplied. Preserve unspecified fields when re-setting the same id.
        ref = ContributorRef(orcid=_normalize_orcid(orcid), name=name, affiliation=affiliation)
        if current is not None and current.orcid == ref.orcid:
            if ref.name is None:
                ref.name = current.name
            if ref.affiliation is None:
                ref.affiliation = current.affiliation
        if not ref.name:
            raise ValueError(
                'contributor name is required, e.g. '
                'ws.contributor("0000-0002-1825-0097", name="Your Name").'
            )
        self._set_contributor(ref)
        self._print_contributor(ref)
        return ref.person_block()

    def _get_contributor(self) -> "ContributorRef | None":
        """Current workspace contributor, loaded from disk on first access."""
        if not self._contributor_loaded:
            data = self._load_workspace_state().get("contributor")
            self._contributor_ref = ContributorRef.from_dict(data) if data else None
            self._contributor_loaded = True
        return self._contributor_ref

    def _set_contributor(self, ref: "ContributorRef | None") -> None:
        state = self._load_workspace_state()
        if ref is None:
            state.pop("contributor", None)
        else:
            state.setdefault("schema_version", "0.1.0")
            state["contributor"] = ref.to_dict()
        self._save_workspace_state(state)
        self._contributor_ref = ref
        self._contributor_loaded = True

    def _print_contributor(self, ref: "ContributorRef") -> None:
        print(f"Workspace contributor: {ref.summary()}")
        if ref.affiliation:
            print(f"  affiliation: {ref.affiliation}")
        print("  Saved to .battinfo/workspace.json; stamped onto records on ws.save().")

    def _stamp_contributor(self, result: dict) -> int:
        """Stamp the workspace contributor onto every record's ``contributor`` list.

        Mirrors :meth:`_stamp_project_funding`: the contributor (a ``Person`` with
        the ORCID in ``same_as``) is added to the top-level ``contributor`` array of
        every record written, so contributions of any kind are attributable.
        Idempotent (a record already listing the ORCID is skipped, so re-saving
        never duplicates) and back-fills records authored before the contributor was
        set. No-op when no contributor is set.
        """
        ref = self._get_contributor()
        if ref is None:
            return 0
        person = ref.person_block()
        stamped = 0
        for key in ("cell_specs", "cell_instances", "tests", "datasets", "test_specs"):
            for item in result.get(key, []):
                path = item.get("path") if isinstance(item, dict) else str(item)
                if not path:
                    continue
                p = Path(path)
                if not p.exists():
                    continue
                record = json.loads(p.read_text(encoding="utf-8"))
                contributors = record.get("contributor")
                if not isinstance(contributors, list):
                    contributors = []
                if any(isinstance(c, dict) and c.get("same_as") == ref.orcid_url for c in contributors):
                    continue
                contributors.append(person)
                record["contributor"] = contributors
                _atomic_write_text(p, json.dumps(record, indent=2, ensure_ascii=False) + "\n")
                stamped += 1
        return stamped

    def convert(self, pattern: str | None = None, fmt: str = "csv") -> list[Path]:
        """Convert raw cycler files to BDF (Battery Data Format).

        With no ``pattern``, auto-detects supported instrument files in the
        workspace root and converts them all.  Each file becomes
        ``bdf/<name>.bdf.<fmt>``; files already converted are skipped.

        Requires the ``batterydf`` package (``pip install batterydf``).

        Auto-detected (just run ``ws.convert()``): NEWARE ``.ndax``/``.nda``,
        Biologic ``.mpt``, Excel ``.xlsx``, MATLAB ``.mat``.

        Ambiguous formats need an explicit pattern, e.g. ``ws.convert('*.csv')``
        for Digatron/Landt/Novonix CSV or ``ws.convert('*.txt')`` for Basytec.

        Not yet supported natively: Arbin ``.res`` and Biologic ``.mpr`` (binary)
        — export a CSV from the instrument software first, then
        ``ws.convert('*.csv')`` or :meth:`convert_csv`.

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
            import bdf as _bdf
            import bdf.io as _bdf_io
            import bdf.repair as _bdf_repair
        except ImportError:
            raise ImportError("batterydf not installed.  Run: pip install batterydf")

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
            summary = ", ".join(
                f"{n} x {_CONVERT_AUTODETECT[e]} {e}" for e, n in detected.items()
            )
            print(f"Found {len(input_files)} file(s): {summary}")

        bdf_dir = self._root / "bdf"
        bdf_dir.mkdir(exist_ok=True)

        suffix = f".bdf.{fmt}"
        written: list[Path] = []
        failed: list[tuple[str, str]] = []
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
                df = _bdf.read(src, validate=False)
                df = _bdf_repair.fix_time(df)
                _bdf_io.save(df, out)
            except Exception as exc:  # one bad file must not abort the batch
                failed.append((src.name, str(exc)))
                print(f"  FAILED: {src.name} — {exc}")
                continue
            print(f"  {src.name}  ->  {out.name}  ({out.stat().st_size / 1e6:.1f} MB)")
            written.append(out)
            # Remember the original so it can travel with the dataset as raw-source
            # provenance when the test is published (see ws.add('test', ...)).
            self._record_conversion(src, out)

        print(f"\nConverted {len(written)} file(s) → {bdf_dir}"
              + (f"  ({len(failed)} failed)" if failed else ""))
        if failed:
            print("  Failed files may be an unsupported variant — try exporting a CSV "
                  "and ws.convert('*.csv'), or ws.convert_csv(path, hints={...}).")
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
        print("\n  Arbin .res / Biologic .mpr / Maccor raw: export a CSV from the "
              "instrument software, then ws.convert('*.csv') or "
              "ws.convert_csv(path, hints={...}).")

    def bdf_columns(self) -> list[str]:
        """Print the canonical BDF column names (the targets for convert_csv hints)."""
        print("Canonical BDF columns — map your CSV headers to these:")
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
        try:
            import pandas as pd
        except ImportError:
            raise ImportError("pandas is required for convert_csv().  Run: pip install batterydf")

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
            import bdf.io as _bdf_io
            _bdf_io.save(df, out)
        except Exception:
            if fmt == "parquet":
                df.to_parquet(out, index=False)
            else:
                df.to_csv(out, index=False)

        if validate:
            try:
                import bdf as _bdf
                report = _bdf.validate(df)
                if getattr(report, "ok", True) is False:
                    print(f"  BDF validation issues: {report}")
                else:
                    print("  BDF validation passed.")
            except ImportError:
                print("  (batterydf not installed - skipped BDF validation)")
            except Exception as exc:
                print(f"  BDF validation could not run: {exc}")

        mapped = ", ".join(sorted(set(hints.values()))) if hints else "(no remap)"
        print(f"  {src.name}  ->  {out.name}   mapped: {mapped}")
        return out

    def commands(self) -> None:
        """Print the workspace commands, grouped by stage of the workflow."""
        groups = [
            ("Set up",   ["setup()", "login(api_key=...)", "whoami()",
                          "project('101103997')               # tag work with a grant"]),
            ("Discover", ["search('duracell mn2400')           # cell-specs (fuzzy)",
                          "search(type='cell', serial='...')   # existing instances",
                          "template('cell-spec', ...)", "bdf_columns()"]),
            ("Build",    ["convert()", "convert_csv(path, hints=...)", "load(src)",
                          "add('cell', spec=spec, serial_numbers=[...])",
                          "load(ws.search(type='cell', batch='...'))  # reference existing",
                          "add('test', type='cycling', cell='SN-1', data='f.csv')"]),
            ("Inspect",  ["list(verbose=True)", "status()"]),
            ("Publish",  ["save()", "publish(note=...)", "zenodo()", "submit()"]),
            ("Review",   ["pending()", "approve(id)"]),
            ("Import",   ["import_(source)", "reload_cells()", "clear()"]),
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
            "# 1. One-time: log in (get a key at the registry settings page)\n"
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
            "# 4. Find your cell in the registry (fuzzy search)\n"
            'spec = ws.search("samsung inr21700 50e")[0]\n'
            "\n"
            "# 5. Register the physical cells you tested\n"
            'ws.add("cell", spec=spec, serial_numbers=["S1", "S2", "S3"])\n'
            "\n"
            "# 6. Attach a test + data to a cell (explicit)\n"
            'ws.add("test", type="cycling", cell="S1", data="bdf/S1.bdf.csv")\n'
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
        serials: list[str] | None = None,
        batch: str | None = None,
        threshold: float = 0.75,
    ) -> list[dict]:
        """Search the registry for resources of a given ``type``.

        One verb for every resource type; ``type`` selects which:

        - ``type="cell-spec"`` (default) — fuzzy text search by manufacturer/model;
          tolerates typos. ``ws.search("duracell mn2400")``
        - ``type="cell"`` — look up existing instances by ``serial``/``serials``/
          ``batch`` (exact or 6-char short ID). ``ws.search(type="cell", serial="tpejqj")``
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
                    print(f"  {r.get('manufacturer','')} {r.get('model','')}  {r['id']}")
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
                    print(f"  {c.get('name') or c.get('serial_number') or ''}  {c['id']}")
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

    def template(self, record_type: str, **kwargs) -> Path:
        """Write a fillable JSON template for a cell spec or test spec.

        Fill in the generated file, then load it with ``ws.load(path)``.

        Examples::

            ws.template("cell-spec", manufacturer="Duracell", model="MN2400",
                        format="cylindrical", chemistry="Zn-MnO2")

            ws.template("test-spec",
                        name="CC discharge C/5",
                        type="capacity_check",
                        description="Constant-current discharge at C/5 to 2.5 V cutoff.")
        """
        rt = record_type.replace("_", "-")
        if rt in ("test-spec", "test-protocol"):   # accept old name during transition
            return self._template_test_spec(**kwargs)
        if rt != "cell-spec":
            raise ValueError(
                f"template() supports 'cell-spec' and 'test-spec' (got {record_type!r})"
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
            "rechargeable": kwargs.get("rechargeable", None),
            "year": kwargs.get("year", None),
            "source_file": kwargs.get("source_file", None),
            "citation": kwargs.get("citation", None),
            "properties": _default_specs_for(format_, chemistry),
        }

        safe_mfr = re.sub(r"[^a-zA-Z0-9]", "-", manufacturer)
        safe_model = re.sub(r"[^a-zA-Z0-9]", "-", model)
        out_path = self._root / f"{safe_mfr}-{safe_model}.cell-spec.json"
        if out_path.exists():
            print(f"  exists: {out_path.name}  (delete to regenerate)")
            return out_path
        out_path.write_text(json.dumps(template, indent=2), encoding="utf-8")
        print(f"  wrote: {out_path.name}")
        return out_path

    def _template_test_spec(self, **kwargs) -> Path:
        name = kwargs.get("name", "")
        test_type = kwargs.get("type", kwargs.get("kind", ""))
        template = {
            "name":        name,
            "type":        test_type,
            "description": kwargs.get("description", None),
            "instrument":  kwargs.get("instrument",  None),
            "steps": kwargs.get("steps", [
                {"description": "Fill in test steps here"}
            ]),
            "conditions": {
                "temperature_degC": kwargs.get("temperature_degC", None),
                "applied_pressure_kilopascal": kwargs.get("applied_pressure_kilopascal", None),
                "atmosphere":       kwargs.get("atmosphere",       None),
                "voltage_window_volt": kwargs.get("voltage_window_volt", {"min": None, "max": None}),
                "soc_window":       kwargs.get("soc_window",       {"min": None, "max": None}),
                "c_rate":           kwargs.get("c_rate",           None),
                "d_rate":           kwargs.get("d_rate",           None),
            },
            "citation":    kwargs.get("citation",    None),
            "source_file": kwargs.get("source_file", None),
        }
        safe_name = re.sub(r"[^a-zA-Z0-9]", "-", name or "test-spec")
        out_path = self._root / f"{safe_name}.test-spec.json"
        if out_path.exists():
            print(f"  exists: {out_path.name}  (delete to regenerate)")
            return out_path
        out_path.write_text(json.dumps(template, indent=2), encoding="utf-8")
        print(f"  wrote: {out_path.name}")
        return out_path

    def load(self, source: str | Path | dict | list) -> Any:
        """Bring a record into the workspace — author a new one, or reference an existing one.

        - A **draft file** (``.cell-spec.json`` / ``.test-spec.json``) is authored as a
          NEW record and published when you save/submit.
        - A **search result** (from :meth:`search`), or a **list** of results, is
          REFERENCED: brought into the session reusing the existing IRI and never
          re-published. A referenced cell is registered for test attachment.

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
        return self._load_from_file(source)

    def add(self, record_type: str, **kwargs) -> list:
        """Add records to the workspace.

        **Cells** (``"cell"``)::

            ws.add("cell", spec=spec,
                   serial_numbers=["FAC-001", "FAC-002"], production_date="2026-01")

            # Reuse pre-allocated IRIs instead of minting new ones (parallel lists):
            ws.add("cell", spec=spec, serial_numbers=["FAC-001", "FAC-002"],
                   iris=["https://w3id.org/battinfo/cell/....", "https://w3id.org/battinfo/cell/...."])

            # ...or from a JSON map {serial: iri}:
            ws.add("cell", spec=spec, from_file="cell_iris.json")

        **Tests** (``"test"``) — link a cell and its data explicitly::

            ws.add("test", type="capacity_check", cell="FAC-001",
                   data="data/FAC-001.csv", instrument="Maccor 4200")

        ``cell`` accepts a serial, IRI, ``CellInstance``, or search result, and is
        resolved in this session, locally, then in the registry (referenced if it
        already exists).  ``data`` is a path or list of paths.  ``type`` is the test
        type (``"cycling"``, ``"capacity_check"``, …); ``kind`` is accepted as an alias.

        For large batches you may instead pass ``datasets="glob"`` to match files to
        already-loaded cells by the 6-char short ID in each filename.
        """
        rt = _canon_type(record_type)
        if rt == "cell":
            return self._add_cell_instances(**kwargs)
        if rt == "test":
            return self._add_tests(**kwargs)
        raise ValueError(
            f"add() supports type 'cell' and 'test' (got {record_type!r}). "
            "Author a cell-spec/test-spec with ws.load(<draft file>); attach datasets "
            "via ws.add('test', data=...)."
        )

    def save(self, validation_policy: str = "strict", mode: str = "upsert") -> dict:
        """Save all records and rebuild the workspace index.

        Returns a summary dict with counts of written records.
        Only the records saved in this call will be submitted by the next
        ``ws.submit()`` — records left over from previous sessions in the
        same directory are ignored.

        ``mode`` controls how an existing on-disk record with the same IRI is
        treated. The default ``"upsert"`` updates it in place (the normal
        edit-and-resave loop). Pass ``"create_only"`` to instead refuse to touch
        any record that already exists, so a fresh authoring run cannot silently
        overwrite records left by a previous session.
        """
        result = self._ws.save(
            mode=mode,
            resolve_references=False,
            validation_policy=validation_policy,
        )
        # Track the exact files written so submit() only sends this session's work.
        self._session_paths = set()
        for key in ("cell_specs", "cell_instances", "tests", "datasets", "test_specs"):
            for item in result.get(key, []):
                p = item.get("path") if isinstance(item, dict) else str(item)
                if p:
                    self._session_paths.add(Path(p))

        # Stamp the workspace's funding project (grant) onto every record written,
        # and the contributor (ORCID) onto every dataset, for attribution.
        stamped = self._stamp_project_funding(result)
        self._stamp_contributor(result)

        # Build id -> human name from the finalized in-memory objects so the
        # confirmation shows what was written, not just counts.
        name_by_id: dict[str, str] = {}
        for obj in self._ws.cell_specs:
            if getattr(obj, "id", None):
                name_by_id[obj.id] = obj.name or getattr(obj, "model", None) or "cell spec"
        for obj in self._ws.cells:
            if getattr(obj, "id", None):
                name_by_id[obj.id] = getattr(obj, "serial_number", None) or obj.name or "cell"
        for obj in self._ws.test_specs:
            if getattr(obj, "id", None):
                name_by_id[obj.id] = obj.name or "test spec"
        for obj in self._ws.tests:
            if getattr(obj, "id", None):
                name_by_id[obj.id] = obj.name or "test"
        for obj in self._ws.datasets:
            if getattr(obj, "id", None):
                name_by_id[obj.id] = obj.name or "dataset"

        total = sum(len(result.get(key, [])) for key, _ in _SAVE_DISPLAY)
        print(f"Saved {total} record(s) under {self._records_root}:")
        for key, label in _SAVE_DISPLAY:
            items = [i for i in result.get(key, []) if isinstance(i, dict)]
            for item in items[:10]:
                rid = item.get("id", "") or ""
                name = name_by_id.get(rid) or (rid.rsplit("/", 1)[-1] if rid else "?")
                status = item.get("status", "")
                rel = self._rel_to_root(item.get("path", ""))
                print(f"  {label:11} {name[:36]:36} [{status}]  {rel}")
            if len(items) > 10:
                print(f"  {label:11} ... +{len(items) - 10} more")
        if stamped:
            ref = self._get_project()
            label = ref.summary() if ref else "project"
            print(f"  funding:    {label} stamped onto {stamped} record(s)")
        print("\n  Next: ws.list(verbose=True) to inspect, or ws.publish() to publish.")
        return result

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
        doi: str | None = None,
        only: str | list[str] | None = None,
        publication_mode: str = STAGED_PUBLICATION_MODE,
        allow_partial: bool = False,
    ) -> list[dict]:
        """Save and submit the workspace in one call (staged for review by default).

        The common path — save and submit to the registry's review queue::

            ws.publish(note="LFP aging campaign, Feb 2026")

        Archive on Zenodo first (mints a citable DOI), then publish with the DOI
        recorded in provenance::

            ws.publish(zenodo=True, note="...")

        This is equivalent to running, in order::

            ws.save()
            ws.upload()              # only when zenodo=True
            ws.zenodo(publish=True)  # only when zenodo=True
            ws.submit(note=note, doi=...)

        For finer control — e.g. reviewing a Zenodo draft before it goes live —
        call those four steps individually instead.

        Parameters
        ----------
        note:
            Provenance note attached to every submitted record.
        zenodo:
            Upload data files and archive on Zenodo before submitting.  Publishes
            the Zenodo deposit immediately and records its DOI in each record.
        sandbox:
            Use ``sandbox.zenodo.org`` (only relevant with ``zenodo=True``).
        doi:
            A pre-existing DOI to attach (e.g. from a Zenodo draft you reviewed).
        only:
            Restrict submission to one or more record types (see :meth:`submit`).
        """
        self.save()
        if zenodo:
            self.upload()
            result = self.zenodo(publish=True, sandbox=sandbox)
            doi = doi or result.doi
        return self.submit(
            note=note, doi=doi, only=only,
            publication_mode=publication_mode, allow_partial=allow_partial,
        )

    def status(
        self,
        registry_url: str | None = None,
        workspace_id: str | None = None,
    ) -> list[dict]:
        """Show this workspace's submissions and their live status on the registry.

        Groups by status (published first), so you can see at a glance what is
        live, what is still in the review queue, and what failed.

        Example::

            ws.status()
        """
        import urllib.request

        url = registry_url or self._registry_url or os.environ.get("BATTINFO_REGISTRY_URL")
        wid = workspace_id or os.environ.get("BATTINFO_WORKSPACE_ID")
        if not url:
            raise RuntimeError("registry_url required. Pass it or set BATTINFO_REGISTRY_URL.")
        if not wid:
            raise RuntimeError("workspace_id required. Pass it or set BATTINFO_WORKSPACE_ID.")

        endpoint = f"{url.rstrip('/')}/workspaces/{wid}/submissions"
        try:
            with urllib.request.urlopen(endpoint, timeout=10) as resp:  # noqa: S310
                submissions = json.loads(resp.read().decode())
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
        examples = self._records_root / "examples"
        summary: dict[str, list[dict]] = {}

        _TYPE_KEYS = {
            "cell-spec":     ("cell_spec",       "name",          "id"),
            "cell-instance": ("cell_instance",  "serial_number", "id"),
            "test":          ("test",           "name",          "id"),
            "dataset":       ("dataset",        "name",          "id"),
            "test-protocol": ("test_spec",  "name",          "id"),
            "material-spec": ("material_spec",  "name",          "id"),
            "material":      ("material",       "name",          "id"),
        }

        for subdir, (record_key, name_field, id_field) in _TYPE_KEYS.items():
            d = examples / subdir
            if not d.exists():
                continue
            items: list[dict] = []
            for f in sorted(d.glob("*.json")):
                try:
                    raw = json.loads(f.read_text(encoding="utf-8"))
                    inner = raw.get(record_key, {}) or {}
                    name = inner.get(name_field) or inner.get("model") or f.stem
                    iri  = inner.get(id_field, "")
                    session = f in self._session_paths
                    items.append({"name": name, "id": iri, "file": f.name,
                                  "session": session})
                except Exception:
                    items.append({"name": f.stem, "id": "", "file": f.name,
                                  "session": f in self._session_paths})
            if items:
                summary[subdir] = items

        if not summary:
            print("  Workspace is empty — run ws.save() first.")
            return summary

        total = sum(len(v) for v in summary.values())
        print(f"Workspace: {self._records_root}")
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
        from battinfo.bundle import CellInstance

        ci_dir = self._records_root / "examples" / "cell-instance"
        if not ci_dir.exists():
            print("  No saved cell instances found.")
            return 0

        count = 0
        for src in sorted(ci_dir.glob("*.json")):
            try:
                raw = json.loads(src.read_text(encoding="utf-8"))
                ci = raw.get("cell_instance", {})
                cell = CellInstance(
                    id=ci.get("id"),
                    cell_spec_id=ci.get("cell_spec_id"),
                    name=ci.get("name"),
                    serial_number=ci.get("serial_number"),
                    batch_id=ci.get("batch_id"),
                )
                for label in (ci.get("name"), ci.get("serial_number")):
                    if label:
                        self._cells_by_short_id[label] = cell
                        sid = _short_id(label)
                        if sid:
                            self._cells_by_short_id[sid] = cell
                stored_sid = ci.get("short_id", "")
                if stored_sid:
                    self._cells_by_short_id[stored_sid] = cell
                count += 1
            except Exception as exc:
                print(f"  WARNING: could not load {src.name} — {exc}")

        print(f"  Loaded {count} cell instance(s) into matching index.")
        return count

    def _registry_resources(self, resource_type: str, q: str | None = None) -> list[dict]:
        """GET /resources?resource_type=... [&q=...] — raw summaries, [] if unreachable."""
        import urllib.parse
        import urllib.request

        if not self._registry_url:
            print("  No registry configured (registry_url=None).")
            return []
        params = {"resource_type": resource_type}
        if q:
            params["q"] = q
        url = f"{self._registry_url}/resources?" + urllib.parse.urlencode(params)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "battinfo-client/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                return json.loads(resp.read().decode())
        except Exception as exc:  # registry down / network - degrade gracefully
            print(f"  Registry unreachable ({exc}).")
            return []

    def _query_registry_cells(
        self,
        *,
        serials: list[str] | None = None,
        batch_id: str | None = None,
    ) -> list[dict]:
        """Resolve published cell instances by serial/short-ID or batch.

        Returns one dict per match: id (canonical IRI), serial_number, batch_id,
        cell_spec_id, manufacturer, model, title.
        """
        wanted = [s for s in (serials or []) if s]
        out: list[dict] = []
        for r in self._registry_resources("cell"):
            meta = r.get("metadata") or {}
            name = meta.get("name") or r.get("title")
            serial = meta.get("serial_number")
            batch = meta.get("batch_id")
            if batch_id is not None:
                if batch != batch_id:
                    continue
            elif wanted:
                if not any(_serial_matches(t, name) or _serial_matches(t, serial) for t in wanted):
                    continue
            out.append({
                "id": r.get("canonical_iri", ""),
                "name": name,
                "serial_number": serial,
                "batch_id": batch,
                "cell_spec_id": meta.get("cell_spec_id"),
                "manufacturer": meta.get("manufacturer"),
                "model": meta.get("model"),
                "title": r.get("title", ""),
            })
        return out

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
        document are preserved — no new IRIs are minted.

        Parameters
        ----------
        source:
            One of:

            * A **Zenodo record ID** (string of digits, e.g. ``"14523891"``)
            * A **URL** pointing directly to a ``battinfo.json`` file
            * A **local file path** to a ``battinfo.json`` file (the legacy
              ``battinfo.jsonld`` name is still accepted)

        sandbox:
            When *source* is a Zenodo record ID, use ``sandbox.zenodo.org``
            instead of production.
        token:
            Optional Zenodo API token for private records.

        Returns
        -------
        dict
            Counts of imported entities, e.g.
            ``{"properties": 3, "instances": 8, "tests": 8, "datasets": 8}``.

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
        graph   = doc.get("@graph", [])

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
        from battinfo.jsonld import _UNIT_MAP

        # Load prop map directly so we can keep only the FIRST key per IRI
        # (later aliases like "discharging_temperature_min" must not overwrite
        # the canonical "minimum_discharging_temperature").
        _prop_map_path = Path(__file__).parent / "data" / "mappings" / "domain-battery" / "property_map.curated.json"
        rev_prop: dict[str, str] = {}
        if _prop_map_path.exists():
            for m in json.loads(_prop_map_path.read_text(encoding="utf-8")).get("mappings", []):
                iri = m.get("class_iri", "")
                key = m.get("key", "")
                if iri and key and iri not in rev_prop:   # first occurrence wins
                    rev_prop[iri] = key

        rev_unit: dict[str, str] = {v: k for k, v in _UNIT_MAP.items()}

        # Build chemistry value reverse map (IRI → original-case chemistry string)
        # so the reconstructed records match the source exactly.
        _chem_case: dict[str, str] = {}  # lower → canonical e.g. "zn-mno2" → "Zn-MnO2"
        _entity_path2 = Path(__file__).parent / "data" / "mappings" / "domain-battery" / "entity_type_map.json"
        if _entity_path2.exists():
            em2 = json.loads(_entity_path2.read_text(encoding="utf-8")).get("mappings", {})
            for val in (em2.get("chemistry") or {}):
                _chem_case[val.lower()] = val  # keep as-is from map (already lowercase)

        # entity_type_map reverse: class_name → {field, value}
        _entity_path = Path(__file__).parent / "data" / "mappings" / "domain-battery" / "entity_type_map.json"
        _etype_rev: dict[str, dict] = {}  # "CylindricalBattery" → {"format": "cylindrical"}
        if _entity_path.exists():
            em = json.loads(_entity_path.read_text(encoding="utf-8")).get("mappings", {})
            for field, entries in em.items():
                if field not in ("format", "chemistry", "iec_code"):
                    continue
                for value, entry in entries.items():
                    for cls in entry.get("battery_types", []):
                        _etype_rev.setdefault(cls, {})[field] = value

        def _extract_descriptors(types: list[str]) -> dict:
            """Extract format/chemistry/iec_code from a list of class names."""
            d: dict = {}
            for t in types:
                info = _etype_rev.get(t, {})
                d.update(info)
            return d

        def _specs_from_property_nodes(nodes: list) -> dict:
            """Reverse EMMO hasProperty nodes → {key: {value, unit}}."""
            specs: dict = {}
            for node in nodes:
                type_raw = node.get("@type", "")
                class_iri = _expand(type_raw) if isinstance(type_raw, str) else ""
                prop_key = rev_prop.get(class_iri)
                if not prop_key:
                    continue
                value = (node.get("hasNumericalPart") or {}).get("hasNumberValue", (node.get("hasNumericalPart") or {}).get("hasNumericalValue"))
                unit_term = (node.get("hasMeasurementUnit") or {}).get("@id", "")
                unit_iri  = _expand(unit_term)
                unit_sym  = rev_unit.get(unit_iri, unit_term.split(":")[-1])
                if value is not None:
                    specs[prop_key] = {"value": value, "unit": unit_sym}
            return specs

        # ── 4. Index graph nodes by type ───────────────────────────────────────
        spec_nodes_by_iri: dict[str, dict] = {}
        cell_nodes_by_iri: dict[str, dict] = {}
        test_nodes_by_iri: dict[str, dict] = {}
        dataset_node: dict | None = None

        for node in graph:
            types = node.get("@type", [])
            if isinstance(types, str):
                types = [types]
            iri = node.get("@id", "")

            if "BatteryCellSpecification" in types:
                spec_nodes_by_iri[iri] = node
            elif any(t in types for t in ("BatteryCell", "CylindricalBattery", "PouchCell", "CoinCell", "PrismaticBattery")) \
                 and "BatteryCellSpecification" not in types:
                cell_nodes_by_iri[iri] = node
            elif "BatteryTest" in types:
                test_nodes_by_iri[iri] = node
            elif "dcat:Dataset" in types or "schema:Dataset" in types:
                dataset_node = node

        # ── 5. Import cell specs ───────────────────────────────────────────────
        spec_objects: dict[str, Any] = {}   # IRI → CellSpecification
        for iri, node in sorted(spec_nodes_by_iri.items()):
            # Skip typed stubs for externally-defined specs (no descriptive body):
            # they only assert @type + a pointer to where the real spec lives, so
            # there is nothing to reconstruct a CellSpecification from — and doing so would
            # mint an empty spec that shadows the authoritative remote one.
            if not node.get("hasProperty") and not node.get("isDescriptionFor"):
                continue
            phys = node.get("isDescriptionFor", {})
            phys_types = phys.get("@type", [])
            if isinstance(phys_types, str):
                phys_types = [phys_types]
            descriptors = _extract_descriptors(phys_types)

            mfr_node = node.get("schema:manufacturer", {})
            mfr_name  = mfr_node.get("schema:name", "") if isinstance(mfr_node, dict) else str(mfr_node)
            specs = _specs_from_property_nodes(node.get("hasProperty", []))

            ct = self._ws.cell_spec(
                manufacturer=mfr_name,
                model=node.get("schema:model", ""),
                # Use verbatim strings if present, else fall back to reverse-mapped values
                format=node.get("battinfo:cellFormat") or descriptors.get("format", ""),
                chemistry=node.get("battinfo:chemistry") or descriptors.get("chemistry", ""),
                iec_code=descriptors.get("iec_code") or node.get("schema:productID") or node.get("schema:gtin"),
                size_code=node.get("schema:identifier"),
                specs=specs or None,
                source_type="zenodo",
            )
            ct.id = iri
            spec_objects[iri] = ct
            print(f"  spec:     {node.get('schema:name', iri)}")

        # ── 6. Import cell instances ───────────────────────────────────────────
        for iri, node in sorted(cell_nodes_by_iri.items()):
            spec_iri = (node.get("dcterms:conformsTo") or {}).get("@id", "")
            spec_obj  = spec_objects.get(spec_iri)
            if spec_obj is None:
                print(f"  WARNING: no spec found for cell {iri} — skipping")
                continue

            cell = self._ws.cell(
                spec_obj,
                serial_number=node.get("schema:serialNumber"),
                grade=node.get("schema:quality"),
                manufactured_at=node.get("schema:productionDate"),
                expires_at=node.get("schema:expires"),
            )
            cell.id = iri
            sn = node.get("schema:serialNumber", "")
            if sn:
                self._cells_by_short_id[sn] = cell
            sid = _short_id(sn)
            if sid:
                self._cells_by_short_id[sid] = cell
            print(f"  instance: {sn or iri}")

        # ── 7. Import tests + datasets ─────────────────────────────────────────
        dist_by_url: dict[str, dict] = {}
        if dataset_node:
            for dist in (dataset_node.get("dcat:distribution") or []):
                url = dist.get("dcat:downloadURL", "")
                if url:
                    dist_by_url[url] = dist

        def _first_id(v: Any) -> str:
            """Resolve an @id from a node ref that may be a dict or a list of dicts."""
            if isinstance(v, list):
                v = v[0] if v else {}
            return v.get("@id", "") if isinstance(v, dict) else ""

        for test_iri, tnode in sorted(test_nodes_by_iri.items()):
            # prov:used may now be a list (cell + spec); hasTestObject is preferred.
            cell_iri = _first_id(tnode.get("hasTestObject")) or _first_id(tnode.get("prov:used"))
            cell = self._ws.cells[-1] if not cell_iri else next(
                (c for c in self._ws.cells if c.id == cell_iri), None
            )
            if cell is None:
                print(f"  WARNING: no cell found for test {test_iri} — skipping")
                continue

            protocol  = tnode.get("schema:measurementTechnique", "")
            instr_node = tnode.get("hasTestEquipment", {})
            instrument = instr_node.get("schema:name", "") if isinstance(instr_node, dict) \
                         else tnode.get("schema:instrument", "")

            for output in (tnode.get("hasOutput") or []):
                ds_iri = output.get("@id", "")
                # Find the distribution for this dataset
                dist = next(
                    (d for d in dist_by_url.values()
                     if (d.get("prov:wasGeneratedBy") or {}).get("@id") == test_iri),
                    None,
                )
                if dist is None:
                    # Try matching by dataset IRI embedded in distribution URL or name
                    dist = next(
                        (d for d in dist_by_url.values()
                         if ds_iri.split("/")[-1] in d.get("dcat:downloadURL", "")),
                        None,
                    )
                if dist is None:
                    continue

                dl_url = dist.get("dcat:downloadURL", "")
                cs     = (dist.get("spdx:checksum") or {})
                fmt    = dist.get("dcat:mediaType", "")
                fname  = dist.get("schema:name", dl_url.split("/")[-1])

                self._ws.record_test(
                    cell,
                    kind=_import_test_kind_from_technique(protocol),
                    name=f"{cell.serial_number or cell_iri.split('/')[-1]} {protocol}",
                    protocol=protocol,
                    instrument=instrument,
                    status="completed",
                    access_url=dl_url,
                    format=fmt,
                    checksum_algorithm=cs.get("spdx:checksumAlgorithm", "").split("_")[-1] or None,
                    checksum_value=cs.get("spdx:checksumValue") or None,
                )
                # Preserve the test IRI and the dataset IRI from the JSON-LD
                if self._ws.tests:
                    self._ws.tests[-1].id = test_iri
                if self._ws.datasets and ds_iri:
                    self._ws.datasets[-1].id = ds_iri
                print(f"  test:     {fname}")

        counts = {
            "properties":     len(spec_objects),
            "instances": len(cell_nodes_by_iri),
            "tests":     len(test_nodes_by_iri),
            "datasets":  sum(1 for t in test_nodes_by_iri.values()
                             if t.get("hasOutput")),
        }
        print(f"\nImported: {counts}")
        return counts

    def clear(self) -> None:
        """Clear all in-memory records and reset the workspace for a new authoring session.

        Does not delete any files already saved to ``.battinfo/records/``.
        Call before re-running ``ws.add()`` + ``ws.save()`` in a notebook to
        avoid accumulating duplicate records across cells.

        Example::

            ws.clear()
            ws.add("cell-instance", spec=spec, serial_numbers=[...])
            ws.save()
        """
        from battinfo._workspace import Workspace

        self._ws = Workspace(root=self._records_root)
        self._cells_by_short_id = {}
        self._session_paths = set()
        print("Workspace cleared.")

    def submit(
        self,
        only: str | list[str] | None = None,
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
    ) -> list[dict]:
        """Submit workspace records to the battinfo registry (staged for review).

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

        Credentials can be passed as arguments or set as environment variables:

        * ``BATTINFO_REGISTRY_URL``
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

        Example::

            ws.save()
            ws.submit(note="From SINTEF LR03 experiment, Feb 2026.")
        """
        import datetime

        url = registry_url or self._registry_url or os.environ.get("BATTINFO_REGISTRY_URL")
        key = api_key       or os.environ.get("BATTINFO_API_KEY")
        wid = workspace_id  or os.environ.get("BATTINFO_WORKSPACE_ID")
        pid = publisher_id  or os.environ.get("BATTINFO_PUBLISHER_ID")
        ver = source_version or datetime.date.today().isoformat()

        # The Zenodo DOI (passed, or stored from ws.zenodo()) is recorded as
        # provenance.citation_doi — a field the registry record schemas allow — so
        # each submitted record links to its archived dataset. The schemas do not
        # include a free-text provenance.comment field (additionalProperties: false),
        # so `note` is accepted for API compatibility but not attached to provenance.
        resolved_doi = doi or self._load_zenodo_state().get("doi")

        if not url:
            raise RuntimeError(
                "registry_url is required. Pass it or set BATTINFO_REGISTRY_URL."
            )
        if not key:
            raise RuntimeError(
                "api_key is required. Pass it or set BATTINFO_API_KEY."
            )
        if not wid:
            raise RuntimeError(
                "workspace_id is required. Pass it or set BATTINFO_WORKSPACE_ID."
            )
        if not pid:
            raise RuntimeError(
                "publisher_id is required. Pass it or set BATTINFO_PUBLISHER_ID."
            )


        examples = self._records_root / "examples"
        if not examples.exists():
            print("  No records found — run ws.save() first.")
            return []

        # ── Validate the `only` filter (fail loud on an unknown token) ──────────
        _ALIASES: dict[str, str] = {
            "cell-spec": "cell-spec", "cell_spec": "cell-spec",
            "cell-instance": "cell-instance", "cell_instance": "cell-instance",
            "test-spec": "test-protocol", "test_spec": "test-protocol",
            "test-protocol": "test-protocol",
            "test": "test", "dataset": "dataset",
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
                        "cell-spec, cell-instance, test-spec, test, dataset."
                    )
                allowed.add(token)
        else:
            allowed = None  # None means all types

        _SUBDIRS = ("cell-spec", "cell-instance", "test-protocol", "test", "dataset")

        def _all_in(subdir: str) -> list[Path]:
            d = examples / subdir
            return sorted(d.glob("*.json")) if d.exists() else []

        wanted = [s for s in _SUBDIRS if allowed is None or s in allowed]

        # ── Select which files to submit (R-9: never silently submit leftovers) ─
        if self._session_paths:
            # Only what the most recent ws.save() wrote this session.
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
        for s in wanted:
            for f in selected[s]:
                try:
                    rec = json.loads(f.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
                    print(f"  ERROR: {f.name} — unreadable/corrupt ({exc})")
                    prefailed.append({"title": f.name, "source_local_id": f.stem, "ok": False,
                                      "status": "unreadable", "error": str(exc), "iri": "", "result": None})
                    continue
                if not isinstance(rec, dict):
                    error = "not a JSON object record"
                    print(f"  ERROR: {f.name} — {error}")
                    prefailed.append({"title": f.name, "source_local_id": f.stem, "ok": False,
                                      "status": "invalid", "error": error, "iri": "", "result": None})
                    continue
                try:
                    result = validate_record(rec, policy="publisher")
                except (ValueError, TypeError) as exc:  # unrecognised / non-object record
                    error = f"not a recognised record ({exc})"
                    print(f"  ERROR: {f.name} — {error}")
                    prefailed.append({"title": f.name, "source_local_id": f.stem, "ok": False,
                                      "status": "invalid", "error": error, "iri": "", "result": None})
                    continue
                if not result.ok:
                    error = "; ".join(result.errors)
                    print(f"  ERROR: {f.name} — failed validation: {error}")
                    prefailed.append({"title": f.name, "source_local_id": f.stem, "ok": False,
                                      "status": "invalid", "error": error, "iri": "", "result": None})
                    continue
                parsed[f] = rec
                validations[f] = {"ok": True, "errors": list(result.errors), "policy": "publisher"}
        if prefailed and not allow_partial:
            raise SubmitError(
                f"{len(prefailed)} record(s) are unreadable or failed validation; aborting before "
                "submitting (nothing was sent). Fix them, or pass allow_partial=True.",
                failed=prefailed, outcomes=prefailed,
            )

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
            d = examples / subdir
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
        if _corrupt_siblings and not allow_partial:
            failures = [
                {"title": f.name, "source_local_id": f.stem, "ok": False, "status": "unreadable",
                 "error": err, "iri": "", "result": None}
                for f, err in _corrupt_siblings
            ]
            listing = "; ".join(f"{f.name} ({err})" for f, err in _corrupt_siblings)
            raise SubmitError(
                f"{len(_corrupt_siblings)} sibling record file(s) are unreadable and would silently "
                f"drop cross-record relationships from the submission: {listing}. Fix them, or pass "
                "allow_partial=True to submit without those relationships.",
                failed=failures, outcomes=failures,
            )

        # cell IRI -> [dataset IRIs] / [test IRIs]; cell IRI -> preview png url;
        # dataset IRI -> {"cell": iri, "test": iri}; test_spec IRI -> [test IRIs]
        cell_datasets: dict[str, list[str]] = {}
        cell_tests: dict[str, list[str]] = {}
        cell_preview_png: dict[str, str] = {}
        ds_links: dict[str, dict] = {}
        spec_tests: dict[str, list[str]] = {}

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

        # ── Cell specs ────────────────────────────────────────────────────────
        for src in _selected("cell-spec"):
            raw = parsed[src]
            product = raw.get("cell_spec", {})
            mfr = product.get("manufacturer", {})
            mfr_name = mfr.get("name", "") if isinstance(mfr, dict) else str(mfr)
            model = product.get("model", "")
            year  = product.get("year") or datetime.date.today().year
            title = f"{mfr_name} {model}".strip()
            source_local_id = _make_record_slug(mfr_name, model, year)

            if resolved_doi:
                raw = dict(raw)
                prov = dict(raw.get("provenance") or {})
                prov.setdefault("citation_doi", resolved_doi)
                raw["provenance"] = prov

            payload = _cell_spec_submission_payload(
                raw, wid=wid, pid=pid, ver=ver,
                source_local_id=source_local_id, title=title,
            )
            outcomes.append(_do_submit(payload, url, key, title,
                                       source_local_id=source_local_id, publication_mode=publication_mode,
                                       validation=validations[src]))

        # ── Cell instances ────────────────────────────────────────────────────
        cell_spec_dir = examples / "cell-spec"
        for src in _selected("cell-instance"):
            raw = parsed[src]
            ci = raw.get("cell_instance", {})
            label = ci.get("name") or ci.get("serial_number") or ci.get("short_id", "")
            source_local_id = ci.get("short_id") or label.lower().replace(" ", "-")
            if resolved_doi:
                raw = dict(raw)
                prov = dict(raw.get("provenance") or {})
                prov.setdefault("citation_doi", resolved_doi)
                raw["provenance"] = prov
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
                preview = {"image": {
                    "src": png,
                    "alt": f"{label} dataset preview",
                    "caption": "Measurement preview from a linked dataset.",
                }}

            payload = _cell_instance_submission_payload(
                raw, wid=wid, pid=pid, ver=ver,
                source_local_id=source_local_id, title=label,
                spec_record=spec_record,
                related_resources=related,
                preview=preview,
            )
            outcomes.append(_do_submit(payload, url, key, label,
                                       source_local_id=source_local_id, publication_mode=publication_mode,
                                       validation=validations[src]))

        # ── Test specs (protocols) ────────────────────────────────────────────
        # Submitted as resource_type "test_spec"; stored in the spec/ IRI namespace
        # so a test's conformsTo relationship resolves to a real page.
        for src in _selected("test-protocol"):
            raw = parsed[src]
            tp = raw.get("test_spec", {})
            title = tp.get("name") or tp.get("short_id", "")
            source_local_id = tp.get("short_id") or src.stem
            if resolved_doi:
                raw = dict(raw)
                prov = dict(raw.get("provenance") or {})
                prov.setdefault("citation_doi", resolved_doi)
                raw["provenance"] = prov

            # Reverse links: hasTest -> each test that conforms to this protocol.
            self_iri = tp.get("id")
            related = [
                {"relationship": "hasTest", "resource_type": "test", "canonical_iri": t_iri}
                for t_iri in spec_tests.get(self_iri, [])
            ]

            payload = _simple_submission_payload(
                raw, resource_type="test_spec", rdf_type="TestSpec",
                record_key="test_spec", wid=wid, pid=pid, ver=ver,
                source_local_id=source_local_id, title=title,
                related_resources=related,
            )
            outcomes.append(_do_submit(payload, url, key, title,
                                       source_local_id=source_local_id, publication_mode=publication_mode,
                                       validation=validations[src]))

        # ── Tests ─────────────────────────────────────────────────────────────
        for src in _selected("test"):
            raw = parsed[src]
            test = raw.get("test", {})
            title = test.get("name") or test.get("short_id", "")
            source_local_id = test.get("short_id") or src.stem
            if resolved_doi:
                raw = dict(raw)
                prov = dict(raw.get("provenance") or {})
                prov.setdefault("citation_doi", resolved_doi)
                raw["provenance"] = prov

            # Relationships: testsCell -> cell, conformsTo -> test_spec.
            related = []
            if test.get("cell_id"):
                related.append({"relationship": "testsCell", "resource_type": "cell", "canonical_iri": test["cell_id"]})
            if test.get("protocol_id"):
                related.append({"relationship": "conformsTo", "resource_type": "test_spec", "canonical_iri": test["protocol_id"]})

            payload = _simple_submission_payload(
                raw, resource_type="test", rdf_type="BatteryTest",
                record_key="test", wid=wid, pid=pid, ver=ver,
                source_local_id=source_local_id, title=title,
                related_resources=related,
            )
            outcomes.append(_do_submit(payload, url, key, title,
                                       source_local_id=source_local_id, publication_mode=publication_mode,
                                       validation=validations[src]))

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
            ds = {**ds, "distributions": inner_dists}
            if resolved_doi:
                prov = dict(raw.get("provenance") or {})
                prov.setdefault("citation_doi", resolved_doi)
                raw = {**raw, "dataset": ds, "provenance": prov}
            else:
                raw = {**raw, "dataset": ds}

            # Relationships: aboutCell -> cell, generatedByTest -> test.
            links = ds_links.get(self_iri, {})
            related = []
            if links.get("cell"):
                related.append({"relationship": "aboutCell", "resource_type": "cell", "canonical_iri": links["cell"]})
            if links.get("test"):
                related.append({"relationship": "generatedByTest", "resource_type": "test", "canonical_iri": links["test"]})

            # Preview image: this dataset's static plot PNG.
            preview = None
            png_dist = next((d for d in top_dists if d.get("role") == "plot_static"), None)
            if png_dist and png_dist.get("access_url"):
                preview = {"image": {"src": png_dist["access_url"], "alt": f"{title} preview"}}

            payload = _simple_submission_payload(
                raw, resource_type="dataset", rdf_type="Dataset",
                record_key="dataset", wid=wid, pid=pid, ver=ver,
                source_local_id=source_local_id, title=title,
                distributions=top_dists,
                related_resources=related,
                preview=preview,
            )
            outcomes.append(_do_submit(payload, url, key, title,
                                       source_local_id=source_local_id, publication_mode=publication_mode,
                                       validation=validations[src]))

        if outcomes:
            self._search_cache = None
            live = [o for o in outcomes if o.get("status") == "published"]
            staged = [o for o in outcomes if o.get("status") == "validated"]
            failed = [o for o in outcomes if not o.get("ok")]
            print(f"\nAttempted {len(outcomes)} record(s) to {url}: "
                  f"{len(live)} live, {len(staged)} staged for review, {len(failed)} failed")
            if live:
                print("  Live records are on the platform. Run ws.status() to see them.")
            if staged:
                print("  Staged records await a registry admin's approval "
                      "(ws.pending() to list, ws.approve(<id>) to promote).")
            if failed:
                print(f"  {len(failed)} record(s) did NOT publish — see the ERROR lines above.")
                if not allow_partial:
                    raise SubmitError(
                        f"{len(failed)} of {len(outcomes)} record(s) failed to submit.",
                        failed=failed, outcomes=outcomes,
                    )
        return outcomes

    def pending(
        self,
        registry_url: str | None = None,
        workspace_id: str | None = None,
    ) -> list[dict]:
        """List submissions staged for review (status ``validated``).

        Most submissions publish immediately, so this is usually empty — it only
        returns records submitted in staged-publication mode, which a registry
        admin must approve with :meth:`approve`.

        Example::

            submissions = ws.pending()
            # returns list of dicts with id, title, status, resource_type
        """
        import urllib.request

        url = registry_url or self._registry_url or os.environ.get("BATTINFO_REGISTRY_URL")
        wid = workspace_id or os.environ.get("BATTINFO_WORKSPACE_ID")
        if not url:
            raise RuntimeError("registry_url required. Pass it or set BATTINFO_REGISTRY_URL.")
        if not wid:
            raise RuntimeError("workspace_id required. Pass it or set BATTINFO_WORKSPACE_ID.")

        endpoint = f"{url.rstrip('/')}/workspaces/{wid}/submissions?status_filter=validated"
        with urllib.request.urlopen(endpoint, timeout=10) as resp:  # noqa: S310
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
            Registry base URL. Falls back to BATTINFO_REGISTRY_URL env var.
        admin_token:
            Registry admin token. Falls back to BATTINFO_ADMIN_TOKEN env var.

        Example::

            submissions = ws.pending()
            ws.approve(submissions[0]["id"], reviewed_by="simon",
                       comment="Verified against datasheet.")
        """
        import urllib.request

        url   = registry_url or self._registry_url or os.environ.get("BATTINFO_REGISTRY_URL")
        token = admin_token or os.environ.get("BATTINFO_ADMIN_TOKEN")
        if not url:
            raise RuntimeError("registry_url required. Pass it or set BATTINFO_REGISTRY_URL.")
        if not token:
            raise RuntimeError("admin_token required. Pass it or set BATTINFO_ADMIN_TOKEN.")

        body = json.dumps({
            "reviewed_by":     reviewed_by or "",
            "review_comment":  comment or "",
        }).encode()
        req = urllib.request.Request(
            f"{url.rstrip('/')}/submissions/{submission_id}/approve",
            data=body,
            headers={
                "Content-Type":          "application/json",
                "X-Battinfo-Admin-Token": token,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            result = json.loads(resp.read().decode())

        self._search_cache = None  # force rebuild on next search
        print(f"  approved: {result.get('title')}  [{result.get('status')}]  {result.get('canonical_iri', '')}")
        return result

    def process(self, *, max_points: int = 4000) -> list[Path]:
        """Generate a curve preview (interactive + static) for each saved dataset.

        For every dataset record, reads its processed BDF file (parquet or csv) and
        writes a downsampled Plotly figure ``<stem>.plot.json`` and a ``<stem>.png``
        next to it, then registers them on the dataset.  ``ws.upload()`` pushes them
        to R2 and ``ws.submit()`` exposes them as ``plot_data`` / ``plot_static``
        distributions — what the platform renders as the dataset's curve preview.

        Run **after** ``ws.save()`` and **before** ``ws.upload()``::

            ws.save()
            ws.process()
            ws.upload()
            ws.submit()

        Requires the plotting extras (``pip install "battinfo[processing]"``);
        datasets whose columns are unrecognised are skipped with a warning.
        """
        import hashlib

        from battinfo import processing

        ds_dir = self._records_root / "examples" / "dataset"
        if not ds_dir.exists():
            print("  No dataset records — run ws.save() first.")
            return []

        written: list[Path] = []
        for record_path in sorted(ds_dir.glob("*.json")):
            raw = json.loads(record_path.read_text(encoding="utf-8"))
            ds = raw.get("dataset", {})
            dists = ds.get("distributions") or []
            if any((d.get("name") or "").endswith(".plot.json") for d in dists):
                continue  # preview already generated

            processed = next((d for d in dists if d.get("role") == "processed"), None)
            src_url = (processed or {}).get("content_url") or ds.get("access_url") or ""
            local = Path(src_url.replace("file:///", "").replace("file://", ""))
            if not local.is_absolute():
                local = self._root / local
            if not local.exists():
                print(f"  WARNING: processed file not found, skipping preview: {local.name}")
                continue

            json_path, png_path = processing.generate_dataset_plots(
                local, local.parent, title=ds.get("name"), max_points=max_points
            )
            if json_path is None and png_path is None:
                print(f"  could not generate a preview for {ds.get('name')} (unrecognised columns?)")
                continue

            for path, fmt in ((json_path, "application/json"), (png_path, "image/png")):
                if path is None or not path.exists():
                    continue
                dists.append({
                    # Schema-safe inner role; ws.submit() promotes *.plot.json/*.png
                    # to plot_data/plot_static in the page-model distributions.
                    "role": "other",
                    "content_url": path.resolve().as_uri(),
                    "name": path.name,
                    "encoding_format": fmt,
                    "content_size": str(path.stat().st_size),
                    "checksum": {"algorithm": "sha256", "value": hashlib.sha256(path.read_bytes()).hexdigest()},
                })
                written.append(path)
                print(f"  preview: {path.name}  ->  {ds.get('name')}")

            ds["distributions"] = dists
            raw["dataset"] = ds
            _atomic_write_text(record_path, json.dumps(raw, indent=2, ensure_ascii=False))

        print(f"\nGenerated {len(written)} preview file(s) across the datasets.")
        return written

    def upload(
        self,
        bucket: str | None = None,
        public: bool = True,
        dry_run: bool = False,
    ) -> list[str]:
        """Upload dataset files to R2 and update ``access_url`` in saved records.

        Reads credentials from environment variables (or ``.battinfo/credentials``):

        * ``R2_ENDPOINT`` — e.g. ``https://<account>.eu.r2.cloudflarestorage.com``
        * ``R2_ACCESS_KEY_ID``
        * ``R2_SECRET_ACCESS_KEY``
        * ``R2_BUCKET`` — defaults to ``battinfo-public``
        * ``R2_PUBLIC_BASE_URL`` — public download root, e.g. ``https://pub-xxx.r2.dev``

        Upload is **idempotent**: if an object already exists in R2 with a
        matching SHA-256, the file is skipped.  Each dataset record on disk is
        updated in-place so ``ws.submit()`` sends the R2 URL, not the local path.

        Parameters
        ----------
        bucket:
            Override the R2 bucket name.
        public:
            Write to the public bucket (default).  Pass ``False`` to use
            ``R2_BUCKET_PRIVATE`` / a private bucket.
        dry_run:
            Print what would be uploaded without doing anything.

        Returns
        -------
        list[str]
            Public URLs of all uploaded (or already present) files.

        Example::

            ws.save()
            ws.upload()    # files → R2, access_url updated
            ws.submit()    # registry receives R2 URLs
        """
        try:
            import boto3
            from boto3.s3.transfer import TransferConfig
        except ImportError:
            raise ImportError(
                "boto3 is required for ws.push_datasets(). "
                "Install with: pip install boto3"
            )
        import hashlib

        endpoint = os.environ.get("R2_ENDPOINT")
        access_key = os.environ.get("R2_ACCESS_KEY_ID")
        secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
        bucket_name = bucket or os.environ.get("R2_BUCKET") or (
            os.environ.get("R2_BUCKET_PUBLIC") if public
            else os.environ.get("R2_BUCKET_PRIVATE")
        )
        public_base = (os.environ.get("R2_PUBLIC_BASE_URL") or "").rstrip("/")

        if not endpoint:
            raise RuntimeError("R2_ENDPOINT required. Set it or add to .battinfo/credentials.")
        if not access_key or not secret_key:
            raise RuntimeError("R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY required.")
        if not bucket_name:
            raise RuntimeError("R2_BUCKET required. Set it or add to .battinfo/credentials.")

        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        transfer_cfg = TransferConfig(
            multipart_threshold=50 * 1024 * 1024,   # 50 MB
            multipart_chunksize=10 * 1024 * 1024,   # 10 MB
            max_concurrency=4,
        )

        ds_dir = self._records_root / "examples" / "dataset"
        if not ds_dir.exists():
            print("  No dataset records — run ws.save() first.")
            return []

        urls: list[str] = []
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
            for dist in dists:
                local_url = dist.get("content_url") or ds.get("access_url") or ""
                local_file = Path(local_url.replace("file:///", "").replace("file://", ""))
                if not local_file.is_absolute():
                    local_file = self._root / local_file

                if not local_file.exists():
                    print(f"  WARNING: file not found, skipping: {local_file.name}")
                    new_dists.append(dist)
                    continue

                # Compute SHA-256 of local file
                sha256 = hashlib.sha256(local_file.read_bytes()).hexdigest()

                # R2 key: datasets/{short_id}/{filename}
                r2_key = f"datasets/{short_id}/{local_file.name}"
                public_url = f"{public_base}/{r2_key}" if public_base else f"s3://{bucket_name}/{r2_key}"

                if dry_run:
                    print(f"  [dry-run] would upload {local_file.name} → {r2_key}")
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
                                f"Checksum mismatch after upload for {r2_key}: "
                                f"expected {sha256}, got {remote_sha}"
                            )
                        print(f"    -> {public_url}")

                # Update this distribution with the R2 URL + checksum
                dist = {**dist, "content_url": public_url,
                        "checksum": {"algorithm": "sha256", "value": sha256}}
                new_dists.append(dist)
                # The primary (processed) distribution sets the dataset access_url.
                if primary_url is None and dist.get("role") != "raw":
                    primary_url = public_url

            if not new_dists:
                continue
            urls.append(primary_url or new_dists[0]["content_url"])
            raw["dataset"]["access_url"] = primary_url or new_dists[0]["content_url"]
            raw["dataset"]["distributions"] = new_dists
            _atomic_write_text(record_path, json.dumps(raw, indent=2, ensure_ascii=False))

            # Keep session paths in sync so submit() picks up the updated record
            self._session_paths.add(record_path)

        print(f"\nPushed {len(urls)} dataset(s) to {bucket_name}")
        return urls

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
        creators: list[dict] | None = None,
        contributors: list[dict] | None = None,
        license: str = "cc-by-4.0",
        keywords: list[str] | None = None,
    ) -> "ZenodoResult":
        """Deposit workspace records and data files to Zenodo.

        Creates a new Zenodo record or a new version of an existing one, uploads
        all data files plus a ``battinfo.json`` linked data document, and
        optionally publishes.

        Safe to re-run: if the workspace already has a record this never errors. With
        ``record_id=None`` it *warns* and moves the workflow forward — a published
        record forks a NEW VERSION; an existing open draft is UPDATED in place (Zenodo
        permits one open draft per concept). Delete ``.battinfo/zenodo.json`` to force a
        brand-new record. Default ``publish=False`` leaves a reviewable draft, so a new
        version is never published (and no DOI minted) without an explicit ``publish=True``
        or a click on Zenodo.

        Credentials are read from ``.battinfo/credentials`` or env vars:
        ``ZENODO_API_TOKEN`` (production) / ``ZENODO_SANDBOX_TOKEN`` (sandbox).

        Parameters
        ----------
        record_id:
            ``None`` → continue this workspace's record (new version of a published
            record, or update its open draft); first run creates a new record. An
            explicit Zenodo record ID forks a new version from that record.
        publish:
            ``False`` (default) — leave a draft for review; publish by clicking on
            Zenodo or re-running with ``publish=True``.
        sandbox:
            Use ``sandbox.zenodo.org`` for testing.
        community:
            Zenodo community identifier (default ``"battinfo-reference"``).
        creators:
            List of ``{"name": "...", "affiliation": "...", "orcid": "..."}`` dicts.
        keywords:
            Extra keywords appended to auto-derived list.

        Returns
        -------
        ZenodoResult

        Example::

            ws.save()
            result = ws.zenodo(publish=False)   # draft for review
            print(result.draft_url)

            result = ws.zenodo(record_id=result.record_id, publish=True)
            ws.submit(doi=result.doi)
        """
        import shutil
        import tempfile

        from battinfo.zenodo import ZenodoClient

        # ── Resolve token ──────────────────────────────────────────────────────
        tok = token or os.environ.get(
            "ZENODO_SANDBOX_TOKEN" if sandbox else "ZENODO_API_TOKEN"
        )
        if not tok:
            var = "ZENODO_SANDBOX_TOKEN" if sandbox else "ZENODO_API_TOKEN"
            raise RuntimeError(
                f"Zenodo token required. Pass token= or set {var} in .battinfo/credentials."
            )

        # ── Resolve what this call should do (warn, never error) ───────────────
        # A workspace that already has a record keeps moving forward on re-run: a
        # published record forks a new version; an open draft is updated in place.
        import warnings  # noqa: PLC0415
        state = self._load_zenodo_state()
        record_id, reuse_draft_id, _version_warning = _plan_zenodo_deposit(
            state.get("record_id"), bool(state.get("published")), record_id,
        )
        if _version_warning:
            warnings.warn(_version_warning, stacklevel=2)
            print(f"  ⚠️  {_version_warning}")

        examples = self._records_root / "examples"
        if not examples.exists():
            raise RuntimeError("No records found — run ws.save() first.")

        client = ZenodoClient(token=tok, sandbox=sandbox)
        domain = "sandbox.zenodo.org" if sandbox else "zenodo.org"

        # ── Create / version / reuse the deposit ───────────────────────────────
        # Files are synced incrementally below (sync_files): a new version inherits the
        # prior version's files from Zenodo, so unchanged data is NOT re-uploaded.
        if reuse_draft_id is not None:
            deposit = client.get_deposit(reuse_draft_id)   # update existing draft
        elif record_id is not None:
            deposit = client.create_new_version(record_id)  # fork from published
        else:
            deposit = client.create_empty_deposit()         # brand-new record

        deposit_id: int     = deposit["id"]
        zenodo_record_id: int = deposit["record_id"]
        prereserved_doi: str = (
            deposit.get("metadata", {})
            .get("prereserve_doi", {})
            .get("doi", f"10.5281/zenodo.{zenodo_record_id}")
        )

        # A version (new fork or an updated draft) is a version of its concept record;
        # record the lineage in the JSON-LD. For a new fork that's the source record_id;
        # for a reused draft it's the deposit's concept record id.
        if record_id:
            is_version_of = f"https://{domain}/records/{record_id}"
        elif reuse_draft_id and deposit.get("conceptrecid"):
            is_version_of = f"https://{domain}/records/{deposit['conceptrecid']}"
        else:
            is_version_of = ""

        # ── Build staging directory ────────────────────────────────────────────
        tmpdir = Path(tempfile.mkdtemp(prefix="battinfo-zenodo-"))
        try:
            record_url = f"https://{domain}/records/{zenodo_record_id}"

            # Bundle data files (zip by test kind if >90 files)
            data_filenames = self._bundle_data_files(tmpdir, examples)

            # Single consolidated JSON-LD (replaces all individual JSON records)
            jsonld = self._build_zenodo_jsonld(
                zenodo_record_id=zenodo_record_id,
                prereserved_doi=prereserved_doi,
                record_url=record_url,
                data_filenames=data_filenames,
                title=title or "",
                description=description or "",
                creators=creators or [],
                contributors=contributors or [],
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
                data_filenames,
                title=title or "",
                description=description or "",
                creators=creators or [],
                contributors=contributors or [],
                license=license,
                zenodo_record_id=zenodo_record_id,
                prereserved_doi=prereserved_doi,
                sandbox=sandbox,
            )


            upload_map = {f: f.name for f in sorted(tmpdir.iterdir()) if f.is_file()}
            # Incremental sync: only files whose content changed are uploaded; unchanged
            # files already on the deposit (e.g. inherited data on a new version) are kept.
            sync = client.sync_files(deposit_id, upload_map)
            print(f"  Files on deposit {deposit_id}: "
                  f"{len(sync['uploaded'])} uploaded, {len(sync['kept'])} unchanged (kept), "
                  f"{len(sync['removed'])} removed")
            for name in sync["uploaded"]:
                print(f"    + {name}")

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        # ── Set metadata ───────────────────────────────────────────────────────
        metadata = self._build_zenodo_metadata(
            title=title, description=description,
            creators=creators or [],
            contributors=contributors or [],
            license=license, community=community,
            extra_keywords=keywords,
        )
        client.update_metadata(deposit_id, metadata)

        # ── Publish or leave as draft ──────────────────────────────────────────
        draft_url = f"https://{domain}/deposit/{deposit_id}"
        doi        = prereserved_doi
        published  = False

        if publish:
            self._assert_publishable(jsonld)  # fail closed BEFORE minting an irreversible DOI (R-7)
            pub = client.publish_deposit(deposit_id)
            doi = pub.get("doi", prereserved_doi)
            published = True
            print(f"  Published: {record_url}")
            print(f"  DOI: {doi}")
        else:
            print(f"  Draft (not published): {draft_url}")
            print(f"  Pre-reserved DOI: {doi}")
            print("  Review it, then click \"Publish\" on Zenodo — or re-run with publish=True.")

        self._save_zenodo_state({
            "record_id": str(zenodo_record_id),
            "doi":       doi,
            "published": published,
            "sandbox":   sandbox,
        })

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

        Requires ``pip install rocrate``.

        Example::

            ws.preview_rocrate()
            ws.validate_rocrate()
        """
        try:
            from rocrate.rocrate import ROCrate  # type: ignore[import]
        except ImportError:
            print("  rocrate not installed — run: pip install rocrate")
            print("  Alternatively validate at: https://www.researchobject.org/ro-crate/")
            return False

        p = Path(path) if path else self._root
        if p.is_file():
            p = p.parent   # accept the metadata file itself, use its directory

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
            shutil.rmtree(tmpdir, ignore_errors=True)

    def preview_rocrate(
        self,
        output: str | Path | None = None,
        title: str = "Battery dataset",
        description: str = "Battery dataset published via BattINFO.",
        creators: list[dict] | None = None,
        contributors: list[dict] | None = None,
        license: str = "cc-by-4.0",
    ) -> Path:
        """Generate ``ro-crate-metadata.json`` locally for review.

        Uses placeholder values for the Zenodo URL.

        Example::

            ws.save()
            ws.preview_rocrate()   # writes ro-crate-metadata.preview.json
        """
        import shutil
        import tempfile

        examples = self._records_root / "examples"
        if not examples.exists():
            raise RuntimeError("No records found — run ws.save() first.")

        tmpdir = Path(tempfile.mkdtemp(prefix="battinfo-rocrate-"))
        try:
            data_filenames = self._bundle_data_files(tmpdir, examples)
            # Write a placeholder linked-data file so contentSize is available
            placeholder = tmpdir / BATTINFO_LD_FILENAME
            placeholder.write_text("{}", encoding="utf-8")
            self._build_rocrate(
                tmpdir, data_filenames,
                title=title, description=description,
                creators=creators or [], contributors=contributors or [],
                license=license,
                zenodo_record_id=0, prereserved_doi="10.5281/zenodo.RECORD_ID",
            )
            src = tmpdir / "ro-crate-metadata.json"
            out = Path(output) if output else self._root / "ro-crate-metadata.preview.json"
            shutil.copy2(src, out)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        print(f"  Written: {out}")
        return out

    def preview_jsonld(
        self,
        output: str | Path | None = None,
        *,
        title: str = "",
        description: str = "",
        creators: list[dict] | None = None,
        contributors: list[dict] | None = None,
        license: str = "",
        keywords: list[str] | None = None,
        version: str = "",
        is_version_of: str = "",
    ) -> Path:
        """Generate ``battinfo.json`` locally for review before uploading to Zenodo.

        Uses placeholder values for the Zenodo record URL and DOI so the
        structure can be inspected without creating a deposit.  Pass the same
        ``title``/``creators``/``license`` you would give :meth:`upload` to preview
        the rights and attribution that will be embedded in the published record.

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
        import shutil
        import tempfile

        examples = self._records_root / "examples"
        if not examples.exists():
            raise RuntimeError("No records found — run ws.save() first.")

        # Collect data filenames using same logic as the real upload (dry run)
        tmpdir = Path(tempfile.mkdtemp(prefix="battinfo-preview-"))
        try:
            data_filenames = self._bundle_data_files(tmpdir, examples)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        jsonld = self._build_zenodo_jsonld(
            zenodo_record_id=0,
            prereserved_doi="10.5281/zenodo.RECORD_ID",
            record_url="https://zenodo.org/records/RECORD_ID",
            data_filenames=data_filenames,
            title=title or "",
            description=description or "",
            creators=creators or [],
            contributors=contributors or [],
            license=license or "",
            keywords=keywords or [],
            version=version or "",
            is_version_of=is_version_of or "",
        )

        out = Path(output) if output else self._root / "battinfo.preview.jsonld"

        # Gold-standard review runs BEFORE the file is written, so a metadata-poor or
        # non-conformant record is surfaced up front rather than after an authoritative-looking
        # file has already been produced (D-4). Uses the FULL publication validator (JSON-LD +
        # structural + SHACL), not just the syntactic JSON-LD check.
        try:
            from battinfo.validate import validate_publication_report  # noqa: PLC0415
            report = validate_publication_report(jsonld, policy="publisher")
            errors = [i for i in report.issues if i.severity == "error"]
            warnings = [i for i in report.issues if i.severity == "warning"]
            if not errors and not warnings:
                print("  Gold-standard: PASS (no validation issues)")
            else:
                print(f"  Gold-standard: {len(errors)} error(s), {len(warnings)} warning(s) "
                      "— address before publishing:")
                for i in errors:
                    print(f"    ERROR   {i.message}")
                for i in warnings:
                    print(f"    warning {i.message}")
        except Exception as exc:  # noqa: BLE001 — preview must still write + return its path
            print(f"  Gold-standard validation could not run: {exc}")

        out.write_text(json.dumps(jsonld, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  Written: {out}")
        print(f"  Graph nodes: {len(jsonld.get('@graph', []))}")
        print(f"  Data files:  {len(data_filenames)}")
        return out

    def _assert_publishable(self, jsonld: dict) -> None:
        """Fail closed before minting an irreversible DOI: refuse to publish a record that has
        validation errors, or a distribution whose data file is missing from the deposit (R-7).

        Missing data files are checked from the most recent :meth:`_bundle_data_files` run."""
        missing = getattr(self, "_missing_data_files", [])
        if missing:
            raise RuntimeError(
                f"Refusing to publish: {len(missing)} distribution data file(s) are missing and were "
                f"not uploaded, so the deposit would be incomplete: {'; '.join(missing[:5])}. "
                "Fix the paths (or remove the distributions), then re-run."
            )
        try:
            from battinfo.validate import validate_publication_report  # noqa: PLC0415
            report = validate_publication_report(jsonld, policy="publisher")
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Could not validate the record before publishing: {exc}") from exc
        errors = [i for i in report.issues if i.severity == "error"]
        if errors:
            raise RuntimeError(
                f"Refusing to publish: {len(errors)} validation error(s) in the record "
                "(run ws.preview_jsonld() to see them, or leave the deposit as a draft): "
                + "; ".join(i.message for i in errors[:5])
            )

    def _bundle_data_files(self, tmpdir: Path, examples: Path) -> list[str]:
        """Copy data files into *tmpdir*, zipping by test kind when >90 files."""
        import shutil
        import zipfile

        # Map dataset IRI → test kind via test records
        ds_to_kind: dict[str, str] = {}
        test_dir = examples / "test"
        if test_dir.exists():
            for f in sorted(test_dir.glob("*.json")):
                try:
                    raw  = json.loads(f.read_text(encoding="utf-8"))
                    test = raw.get("test", {})
                    kind = test.get("kind", "other")
                    for ds_id in (test.get("dataset_ids") or []):
                        ds_to_kind[ds_id] = kind
                except Exception:
                    continue

        # Collect local data file paths
        collected: list[tuple[Path, str]] = []  # (local_path, kind)
        missing: list[str] = []  # file-scheme distributions whose local file is absent
        ds_dir = examples / "dataset"
        if ds_dir.exists():
            for ds_file in sorted(ds_dir.glob("*.json")):
                try:
                    raw   = json.loads(ds_file.read_text(encoding="utf-8"))
                    ds    = raw.get("dataset", {})
                    ds_id = ds.get("id", "")
                    kind  = ds_to_kind.get(ds_id, "other")
                    for dist in (ds.get("distributions") or []):
                        url = dist.get("content_url") or ""
                        if not url.startswith("file://"):
                            continue
                        lp = Path(url.replace("file:///", "").replace("file://", ""))
                        if lp.exists():
                            collected.append((lp, kind))
                        else:
                            # Do NOT silently drop a distribution whose data file is missing: the
                            # deposit would be published incomplete (a distribution pointing at a
                            # file that was never uploaded). Warn now; block publish later (R-7).
                            missing.append(str(lp))
                            print(f"  ⚠️  data file for a distribution is missing (not uploaded): {lp}")
                except Exception:
                    continue
        # Surfaced to zenodo()/publish so publishing can fail closed on an incomplete deposit.
        self._missing_data_files = missing

        # Deduplicate (a file may appear in multiple distributions)
        seen: set[str] = set()
        unique: list[tuple[Path, str]] = []
        for lp, kind in collected:
            if lp.name not in seen:
                seen.add(lp.name)
                unique.append((lp, kind))

        # ── Actionable artifacts (Layer B) ─────────────────────────────────────
        # Only files the user has explicitly placed in the workspace are published;
        # artifacts that live elsewhere are flagged (warn, never block) and left out
        # rather than auto-copied, so publication contains exactly what was opted in.
        from battinfo.publication import plan_artifact_inclusion  # noqa: PLC0415
        artifact_records: list[dict] = []
        for sub in ("test-protocol", "test"):
            sub_dir = examples / sub
            if sub_dir.exists():
                for f in sorted(sub_dir.glob("*.json")):
                    try:
                        artifact_records.append(json.loads(f.read_text(encoding="utf-8")))
                    except Exception:
                        continue
        artifact_files, artifact_warnings = plan_artifact_inclusion(artifact_records, self._root)
        self._artifact_warnings = artifact_warnings
        for warning in artifact_warnings:
            print(f"  ⚠️  {warning}")
        for lp in artifact_files:
            if lp.name not in seen:
                seen.add(lp.name)
                unique.append((lp, "protocol"))

        filenames: list[str] = []
        if len(unique) <= 90:
            for lp, _ in unique:
                shutil.copy2(lp, tmpdir / lp.name)
                filenames.append(lp.name)
        else:
            # Group by test kind → one zip per kind
            by_kind: dict[str, list[Path]] = {}
            for lp, kind in unique:
                by_kind.setdefault(kind, []).append(lp)
            for kind, paths in sorted(by_kind.items()):
                zip_name = f"{kind}.zip"
                with zipfile.ZipFile(tmpdir / zip_name, "w", zipfile.ZIP_DEFLATED) as zf:
                    for lp in sorted(paths):
                        zf.write(lp, lp.name)
                filenames.append(zip_name)
                print(f"  Bundled {len(paths)} files → {zip_name}")

        return filenames

    @staticmethod
    def _assemble_zenodo_jsonld(
        record_sets: dict[str, list[dict]],
        *,
        zenodo_record_id: int,
        prereserved_doi: str,
        record_url: str,
        data_filenames: list[str],
        title: str = "",
        description: str = "",
        creators: list[dict] | None = None,
        contributors: list[dict] | None = None,
        license: str = "",
        files_base_url: str | None = None,
        keywords: list[str] | None = None,
        version: str = "",
        is_version_of: str = "",
    ) -> dict:
        """Assemble the consolidated battinfo JSON-LD from canonical record dicts.

        This is the single, input-agnostic graph builder shared by every publication
        path: it takes ``record_sets`` (keys ``cell-spec``, ``cell-instance``,
        ``test``, ``test-protocol``, ``dataset`` → lists of record dicts in the
        canonical on-disk shape) rather than reading a workspace, so both the
        interactive authoring flow (:meth:`_build_zenodo_jsonld`) and the
        programmatic contribution flow (``publication.build_zenodo_package``) emit
        byte-identical graphs.

        Cell specs use domain-battery OWL classes (``CylindricalBattery`` etc.)
        and EMMO's ``hasProperty`` / ``hasNumericalPart`` / ``hasMeasurementUnit``
        pattern for measurements.  DCAT and schema.org wrap the dataset level for
        broad discoverability.  The document is processable by OWL reasoners and
        any JSON-LD tool that resolves the embedded context.
        """
        from battinfo.jsonld import (
            _PROP_MAP,
            _UNIT_MAP,
            TEST_CONDITION_CLASS,
            TEST_CONDITION_GENERIC_CLASSES,
            TEST_CONDITION_UNIT_IRI,
            funding_to_jsonld,
            setpoint_emmo_class,
            step_emmo_class,
            termination_emmo_class,
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

        _DATA_DIR = Path(__file__).parent / "data"

        # ── Load entity-type map (format / chemistry / iec_code → class names) ──
        _entity_map_path = _DATA_DIR / "mappings" / "domain-battery" / "entity_type_map.json"
        _entity_map: dict = {}
        if _entity_map_path.exists():
            _entity_map = json.loads(
                _entity_map_path.read_text(encoding="utf-8")
            ).get("mappings", {})

        def _physical_types(format_val: str, chemistry_val: str, iec_val: str) -> list[str]:
            """Return domain-battery prefLabel class names for a cell's descriptors."""
            types: list[str] = []
            for section, key in (
                ("format",   format_val.lower()),
                ("chemistry", chemistry_val.lower()),
                ("iec_code",  iec_val.lower()),
            ):
                entry = _entity_map.get(section, {}).get(key, {})
                for bt in entry.get("battery_types", []):
                    if bt not in types and bt in _LABEL_TO_COMPACT:
                        types.append(bt)
            return types or ["BatteryCell"]

        # ── Build prefLabel lookup tables from curated mapping files ───────────
        # {class_iri → prefLabel}  e.g. "https://...#electrochemistry_639b..." → "NominalVoltage"
        _iri_to_label: dict[str, str] = {}
        _prop_json = _DATA_DIR / "mappings" / "domain-battery" / "property_map.curated.json"
        _unit_json = _DATA_DIR / "mappings" / "domain-battery" / "unit_map.curated.json"
        if _prop_json.exists():
            for m in json.loads(_prop_json.read_text(encoding="utf-8")).get("mappings", []):
                if m.get("class_iri") and m.get("class_pref_label"):
                    _iri_to_label[m["class_iri"]] = m["class_pref_label"]
        # {unit_symbol → (unit_iri, prefLabel)}
        _unit_label: dict[str, tuple[str, str]] = {}
        if _unit_json.exists():
            for m in json.loads(_unit_json.read_text(encoding="utf-8")).get("mappings", []):
                if m.get("symbol") and m.get("unit_iri") and m.get("unit_pref_label"):
                    _unit_label[m["symbol"]] = (m["unit_iri"], m["unit_pref_label"])

        # battery type class → prefLabel (from entity_type_map prefLabels)
        # _FORMAT_LABEL / _CHEM_LABEL removed — now loaded from entity_type_map.json
        # prefLabel → full compact IRI (for context terms)
        _LABEL_TO_COMPACT: dict[str, str] = {
            "BatteryTest":            "battery:battery_dca7729a_421a_4921_90cf_9692bb9eb081",
            "BatteryCell":            "battery:battery_68ed592a_7924_45d0_a108_94d6275d57f0",
            "BatteryCellSpecification":"battery:battery_1cfbba6c_8824_4932_a23e_2141483acef7",
            "CylindricalBattery":     "battery:battery_ac604ecd_cc60_4b98_b57c_74cd5d3ccd40",
            "PrismaticBattery":       "battery:battery_86c9ca80_de6f_417f_afdc_a7e52fa6322d",
            "PouchCell":              "battery:battery_392b3f47_d62a_4bd4_a819_b58b09b8843a",
            "CoinCell":               "battery:battery_b7fdab58_6e91_4c84_b097_b06eff86a124",
            "LithiumIonBattery":                  "battery:battery_96addc62_ea04_449a_8237_4cd541dd8e5f",
            "LithiumMetalBattery":                "battery:battery_ada13509_4eed_4e40_a7b1_4cc488144154",
            "SodiumIonBattery":                   "battery:battery_42329a95_03fe_4ec1_83cb_b7e8ed52f68a",
            "AlkalineZincManganeseDioxideBattery":"battery:battery_b572826a_b4e4_4986_b57d_f7b945061f8b",
            "AlkalineCell":                       "battery:battery_50b911f7_c903_4700_9764_c308d8a95470",
            "PrimaryBattery":                     "battery:battery_3b0b0d6e_8b0e_4491_885e_8421d3eb3b69",
            "SecondaryBattery":                   "battery:battery_efc38420_ecbb_42e4_bb3f_208e7c417098",
            # IEC standard size codes — subclasses already defined in domain-battery
            "LR03":   "battery:battery_a5299801_2a8d_4d03_a476_ca2c5e9ca702",  # AAA alkaline
            "LR6":    "battery:battery_6b2540b9_5af6_478a_81ae_583db9636db8",  # AA alkaline
            "LR14":   "battery:battery_d00e842e_ee0b_4e25_bd17_d64d76d69730",  # C alkaline
            "LR20":   "battery:battery_0c9979c2_c981_48ea_a8e1_72bdcb58fd58",  # D alkaline
            "LR1":    "battery:battery_1c0306f5_5698_4874_b6ce_e5cc45a46b91",  # N alkaline
            "CR2032": "battery:battery_b61b96ac_f2f4_4b74_82d5_565fe3a2d88b",  # coin
            "CR2025": "battery:battery_9984642f_c9dc_4b98_94f6_6ffe20cfc014",  # coin
            "LR44":   "battery:battery_d10ff656_f9fd_4b0e_9de9_4812a44ea359",  # button
            "HR6":    "battery:battery_a71a4bf2_dee6_4aa4_8ad4_9f38c261fb84",  # AA NiMH
            "KR6":    "battery:battery_ad7c1d81_9a9f_4174_88ea_3ba3e8f4dbe2",  # AA NiCd
        }
        # Add quantity class prefLabels → compact IRI
        def _compact_iri(iri: str) -> str:
            for prefix, base in (
                ("battery:", "https://w3id.org/emmo/domain/battery#"),
                ("electrochemistry:", "https://w3id.org/emmo/domain/electrochemistry#"),
                ("emmo:", "https://w3id.org/emmo#"),
            ):
                if iri.startswith(base):
                    return prefix + iri[len(base):]
            return iri

        for iri, label in _iri_to_label.items():
            _LABEL_TO_COMPACT[label] = _compact_iri(iri)
        # Add unit prefLabels → compact IRI
        for sym, (unit_iri, unit_label) in _unit_label.items():
            _LABEL_TO_COMPACT[unit_label] = _compact_iri(unit_iri)

        def _quantity_node(prop_key: str, value: float, unit_symbol: str) -> dict | None:
            class_iri = _PROP_MAP.get(prop_key)
            if not class_iri:
                return None
            # Use prefLabel as @type (readable) — context maps it to the full IRI
            label = _iri_to_label.get(class_iri, _compact_iri(class_iri))
            node: dict = {
                "@type":            label,
                "hasNumericalPart": {"hasNumberValue": value},
            }
            ul = _unit_label.get(unit_symbol)
            if ul:
                unit_iri, _ulabel = ul
                node["hasMeasurementUnit"] = {"@id": _compact_iri(unit_iri)}
            elif unit_symbol:
                unit_iri = _UNIT_MAP.get(unit_symbol)
                if unit_iri:
                    node["hasMeasurementUnit"] = {"@id": _compact_iri(unit_iri)}
            return node

        def _resolve_unit_iri(unit_symbol: str) -> str | None:
            """Symbol → compact unit IRI, across curated maps, the records context
            (V, mA, degC, …) and the test-condition extras (A/Ah for C-rate)."""
            if not unit_symbol:
                return None
            ul = _unit_label.get(unit_symbol)
            if ul:
                return _compact_iri(ul[0])
            if unit_symbol in _UNIT_MAP:
                return _compact_iri(_UNIT_MAP[unit_symbol])
            ctx_val = _RECORDS_CONTEXT.get(unit_symbol)
            if isinstance(ctx_val, str) and (":" in ctx_val or ctx_val.startswith("http")):
                return ctx_val
            return TEST_CONDITION_UNIT_IRI.get(unit_symbol)

        def _condition_quantity_node(key: str, value: Any, unit_symbol: str) -> dict | None:
            """A test condition → EMMO quantity node (the @type comes from the
            controlled vocabulary), or None if the key is unmapped (caller falls
            back to schema:PropertyValue and emits a warning)."""
            cls = TEST_CONDITION_CLASS.get(str(key).lower())
            if not cls:
                return None
            node: dict = {"@type": cls, "hasNumericalPart": {"hasNumberValue": value}}
            # A generic class (e.g. ConventionalProperty for temperature) needs a
            # human label to say *which* property it is.
            if cls in TEST_CONDITION_GENERIC_CLASSES:
                node["rdfs:label"] = str(key).replace("_", " ")
            unit_iri = _resolve_unit_iri(unit_symbol) if unit_symbol else (
                # C-rate is dimensionless-by-symbol; default to AmperePerAmpereHour.
                TEST_CONDITION_UNIT_IRI["A/Ah"] if cls == "CRate" else None
            )
            if unit_iri:
                node["hasMeasurementUnit"] = {"@id": unit_iri}
            return node

        def _typed_quantity_node(emmo_class: str, value: Any, unit_symbol: str) -> dict:
            """An EMMO quantity node with an explicit @type (used for method steps)."""
            node: dict = {"@type": emmo_class, "hasNumericalPart": {"hasNumberValue": value}}
            unit_iri = _resolve_unit_iri(unit_symbol) if unit_symbol else None
            if unit_iri:
                node["hasMeasurementUnit"] = {"@id": unit_iri}
            return node

        def _method_step_node(step: dict) -> dict:
            """A descriptive method step → EMMO process node. Groups become an
            IterativeWorkflow with NumberOfIterations + nested hasTask; leaf steps
            carry hasControlParameter / hasTerminationParameter / hasProperty."""
            mode = step.get("mode")
            if mode == "group":
                gnode: dict = {"@type": step_emmo_class("group", None) or "IterativeWorkflow"}
                count = step.get("count")
                if isinstance(count, int):
                    gnode["NumberOfIterations"] = {"hasNumericalPart": {"hasNumberValue": count}}
                gnode["hasTask"] = [_method_step_node(s) for s in (step.get("steps") or [])]
                return gnode

            node: dict = {"@type": step_emmo_class(mode, step.get("direction")) or "ElectrochemicalProcess"}
            if step.get("description"):
                node["rdfs:label"] = step["description"]
            controls: list = []
            for key, qty in (step.get("setpoints") or {}).items():
                qcls = setpoint_emmo_class(key) or TEST_CONDITION_CLASS.get(str(key).lower())
                if qcls and isinstance(qty, dict) and qty.get("value") is not None:
                    controls.append(_typed_quantity_node(qcls, qty["value"], qty.get("unit", "")))
            if controls:
                node["hasControlParameter"] = controls
            terminations: list = []
            for term in (step.get("termination") or []):
                if not isinstance(term, dict):
                    continue
                tcls = termination_emmo_class(term.get("quantity"), term.get("direction"))
                if tcls and term.get("value") is not None:
                    terminations.append(_typed_quantity_node(tcls, term["value"], term.get("unit", "")))
            duration = step.get("duration")
            if isinstance(duration, dict) and duration.get("value") is not None:
                dcls = termination_emmo_class("duration", "elapsed") or "Duration"
                terminations.append(_typed_quantity_node(dcls, duration["value"], duration.get("unit", "")))
            if terminations:
                node["hasTerminationParameter"] = terminations
            temperature = step.get("temperature")
            if isinstance(temperature, dict) and temperature.get("value") is not None:
                tnode = _condition_quantity_node("temperature", temperature["value"], temperature.get("unit", ""))
                if tnode is not None:
                    node["hasProperty"] = [tnode]
            return node

        def _artifact_download_url(loc: str) -> Any:
            """Resolve an artifact locator to its download URL. An http(s) locator is
            already hosted; a workspace file that is being uploaded resolves to its
            hosted URL (like data files); an un-uploaded local locator is kept as the
            relative literal (no hosted copy exists)."""
            text = str(loc)
            if text.startswith(("http://", "https://")):
                return {"@id": text}
            raw = text[len("file://"):] if text.startswith("file://") else text
            fname = Path(raw).name
            if fname in data_filenames:
                base = files_base_url or f"{record_url}/files"
                return {"@id": f"{base}/{fname}"}
            return text

        def _artifact_distribution(art: dict) -> dict:
            """An actionable artifact link → a dcat:Distribution node, so the runnable
            protocol file is machine-discoverable alongside the descriptive method."""
            node: dict = {"@type": "dcat:Distribution"}
            role = art.get("role")
            fmt = art.get("format")
            title = (role or "").replace("_", " ")
            if fmt:
                title = f"{title} ({fmt})".strip()
            if title:
                node["dcterms:title"] = title
            loc = art.get("locator")
            if loc:
                node["dcat:downloadURL"] = _artifact_download_url(loc)
            if art.get("media_type"):
                node["dcat:mediaType"] = art["media_type"]
            ct = art.get("conforms_to")
            if ct:
                node["dcterms:conformsTo"] = (
                    {"@id": ct} if str(ct).startswith(("http://", "https://")) else ct
                )
            if isinstance(art.get("byte_size"), int):
                node["dcat:byteSize"] = art["byte_size"]
            # Standard vocabulary (no custom battinfo: terms): the artifact role is a
            # dcterms:type, the format token a dcterms:format, the checksum an spdx:Checksum.
            if role:
                node["dcterms:type"] = role
            if fmt:
                node["dcterms:format"] = fmt
            if art.get("sha256"):
                node["spdx:checksum"] = {
                    "@type": "spdx:Checksum",
                    "spdx:algorithm": "spdx:checksumAlgorithm_sha256",
                    "spdx:checksumValue": art["sha256"],
                }
            return node

        # ── Load cell specs ────────────────────────────────────────────────────
        spec_nodes: dict[str, dict] = {}
        _ct_recs = record_sets.get("cell-spec", [])
        if _ct_recs:
            for raw in _ct_recs:
                try:
                    prod = raw.get("cell_spec", {})
                    iri  = prod.get("id", "")
                    if not iri:
                        continue
                    mfr      = prod.get("manufacturer", {})
                    mfr_name = mfr.get("name", "") if isinstance(mfr, dict) else str(mfr)
                    fmt      = (prod.get("cell_format") or "").lower()
                    chem     = (prod.get("chemistry") or "").lower()
                    short_id = iri.split("/")[-1]

                    # Physical battery types — loaded from entity_type_map.json
                    iec_code     = prod.get("iec_code", "")
                    rechargeable = prod.get("rechargeable")
                    physical_types = _physical_types(fmt, chem, iec_code)
                    # rechargeable maps to SecondaryBattery / PrimaryBattery in domain-battery
                    if rechargeable is True and "SecondaryBattery" not in physical_types:
                        physical_types.append("SecondaryBattery")
                    elif rechargeable is False and "PrimaryBattery" not in physical_types:
                        physical_types.append("PrimaryBattery")

                    node: dict = {
                        # BatteryCellSpecification = a Description (information artifact),
                        # not a physical battery — the physical individual is linked via
                        # isDescriptionFor below, so the schema.org co-type is CreativeWork.
                        "@type":       ["BatteryCellSpecification", "schema:CreativeWork"],
                        "@id":         iri,
                        "schema:name": prod.get("name", ""),
                        "schema:model":prod.get("model", ""),
                        "schema:manufacturer": {
                            "@type":       "schema:Organization",
                            "schema:name": mfr_name,
                        },
                        "schema:url": (
                            f"https://www.battery-genome.org/registry/spec/{short_id}"
                        ),
                        # isDescriptionFor links the spec to an anonymous individual
                        # of the correct physical battery type
                        "isDescriptionFor": {
                            "@type": physical_types if len(physical_types) > 1
                                     else physical_types[0],
                        },
                    }
                    if prod.get("size_code"):
                        node["schema:identifier"] = prod["size_code"]
                    if prod.get("iec_code"):
                        node["schema:productID"] = prod["iec_code"]
                    if prod.get("product_type"):
                        node["schema:additionalType"] = str(prod["product_type"])
                    if prod.get("country_of_origin"):
                        node["schema:countryOfOrigin"] = {
                            "@type":       "schema:Country",
                            "schema:name": prod["country_of_origin"],
                        }
                    if prod.get("year"):
                        node["schema:releaseDate"] = f"{prod['year']}-01-01"
                    if prod.get("schema_version"):
                        node["schema:schemaVersion"] = prod["schema_version"]
                    # Preserve original chemistry and format strings verbatim
                    # so the round-trip through JSON-LD is lossless.
                    if prod.get("chemistry"):
                        node["battinfo:chemistry"] = prod["chemistry"]
                    if prod.get("cell_format"):
                        node["battinfo:cellFormat"] = prod["cell_format"]
                    # rechargeable is already encoded in @type via PrimaryBattery/SecondaryBattery

                    # Measurements using EMMO hasProperty pattern
                    specs = raw.get("properties", {})
                    quantity_nodes = []
                    for prop_key, qty in (specs or {}).items():
                        if not isinstance(qty, dict) or qty.get("value") is None:
                            continue
                        qn = _quantity_node(prop_key, qty["value"], qty.get("unit", ""))
                        if qn:
                            quantity_nodes.append(qn)
                    if quantity_nodes:
                        node["hasProperty"] = quantity_nodes

                    spec_nodes[iri] = node
                except Exception:
                    continue

        # ── Map cell instance IRI → {cell_spec_id, serial_number} ──────────────────
        instances: dict[str, dict] = {}
        _ci_recs = record_sets.get("cell-instance", [])
        if _ci_recs:
            for raw in _ci_recs:
                try:
                    ci  = raw.get("cell_instance", {})
                    iri = ci.get("id", "")
                    if iri:
                        instances[iri] = {
                            "name":           ci.get("name", ""),
                            "serial_number":  ci.get("serial_number", ""),
                            "cell_spec_id":        ci.get("cell_spec_id", ""),
                            "grade":          ci.get("grade"),
                            "manufactured_at": ci.get("manufactured_at"),
                            "expires_at":      ci.get("expires_at"),
                            "batch_id":        ci.get("batch_id"),
                            "conformance":    ci.get("conformance"),
                        }
                except Exception:
                    continue

        # ── Build test instance nodes + dataset→test mapping ──────────────────
        ds_to_test: dict[str, dict] = {}
        test_nodes: list[dict] = []
        _test_recs = record_sets.get("test", [])
        if _test_recs:
            for raw in _test_recs:
                try:
                    test     = raw.get("test", {})
                    test_iri = test.get("id", "")
                    cell_id  = test.get("cell_id", "")
                    protocol = test.get("protocol_name", "")
                    instrument = test.get("instrument_name", "")

                    for ds_id in (test.get("dataset_ids") or []):
                        ds_to_test[ds_id] = {
                            "kind":       test.get("kind", ""),
                            "cell_id":    cell_id,
                            "protocol":   protocol,
                            "test_iri":   test_iri,
                        }

                    if test_iri and cell_id:
                        tnode: dict = {
                            "@type":         ["BatteryTest", "schema:Action", "prov:Activity"],
                            "@id":           test_iri,
                            "hasTestObject": {"@id": cell_id},   # domain-battery: physical object tested
                            # PROV mirror of hasTestObject so a PROV-only consumer
                            # reaches the cell; the spec is appended in _apply below.
                            "prov:used":     [{"@id": cell_id}],
                        }
                        # Human label so agents/consumers see more than an opaque IRI.
                        _cell_nm = instances.get(cell_id, {}).get("name", "")
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
                        if instrument:
                            # Instrument is EMMO-canonical (schema.org has no apt
                            # predicate — schema:instrument is an Action property and
                            # this node is an Activity, so it is intentionally omitted).
                            tnode["hasTestEquipment"] = {
                                "@type":       "schema:Thing",
                                "schema:name": instrument,
                            }
                        # hasOutput → the dataset IRIs produced by this test, mirrored
                        # as prov:generated so PROV alone reaches the output dataset.
                        outputs = [{"@id": ds_id} for ds_id in (test.get("dataset_ids") or [])]
                        if outputs:
                            tnode["hasOutput"] = outputs
                            tnode["prov:generated"] = outputs
                        # Activity timing (measured period, sourced from the data) —
                        # PROV start/end plus schema.org mirror so the test is placed in
                        # time without parsing the time-series.
                        _start = _unix_to_iso(int(test["started_at"])) if str(test.get("started_at") or "").isdigit() else test.get("started_at")
                        _end = _unix_to_iso(int(test["ended_at"])) if str(test.get("ended_at") or "").isdigit() else test.get("ended_at")
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
                except Exception:
                    continue

        # ── Build test spec (protocol) nodes ───────────────────────────────────
        # Each test activity's ``prov:used`` points at the spec it followed. Emit a
        # described node for that spec so the link resolves to a real node in the
        # graph instead of a dangling IRI — mirroring how cell specs and datasets
        # are inlined above. PROV-O: the thing a ``prov:used`` plan-link targets is a
        # ``prov:Plan``; ``schema:HowTo`` is the schema.org analog for a procedure.
        # The importer keys off ``BatteryTest``/``BatteryCellSpecification`` types
        # (see import_), so these nodes are ignored on round-trip — safe to add.
        test_spec_nodes: list[dict] = []
        _tspec_recs = record_sets.get("test-protocol", [])
        if _tspec_recs:
            for raw in _tspec_recs:
                try:
                    spec = raw.get("test_spec", {})
                    iri  = spec.get("id", "")
                    if not iri:
                        continue
                    snode: dict = {
                        "@type": ["prov:Plan", "schema:HowTo"],
                        "@id":   iri,
                    }
                    if spec.get("name"):
                        snode["schema:name"] = spec["name"]
                    if spec.get("kind"):
                        snode["schema:additionalType"] = spec["kind"]
                    if spec.get("description"):
                        snode["schema:description"] = spec["description"]
                    # ── Descriptive method → EMMO process graph (queryable) ───────
                    # The ordered method becomes a hasTask chain of typed step nodes,
                    # each carrying hasControlParameter / hasTerminationParameter /
                    # hasProperty quantities. Protocol-level ambient conditions attach
                    # as hasProperty; names outside the controlled vocabulary fall back
                    # to schema:PropertyValue (and trigger a publication warning).
                    method = raw.get("method") or []
                    if method:
                        snode["hasTask"] = [_method_step_node(s) for s in method]
                    _props: list = []
                    _fallback: list = []
                    for _name, _val in (raw.get("conditions") or {}).items():
                        _v = _val.get("value") if isinstance(_val, dict) else _val
                        _u = _val.get("unit", "") if isinstance(_val, dict) else ""
                        qnode = _condition_quantity_node(_name, _v, _u) if _v is not None else None
                        if qnode is not None:
                            _props.append(qnode)
                        else:
                            _fallback.append(_property_value(_name, _val, "conditions"))
                    if _props:
                        snode["hasProperty"] = _props
                    if _fallback:
                        snode["schema:additionalProperty"] = _fallback
                    # Actionable layer: link runnable protocol files as distributions.
                    if raw.get("artifacts"):
                        snode["dcat:distribution"] = [
                            _artifact_distribution(a) for a in raw["artifacts"] if isinstance(a, dict)
                        ]
                    test_spec_nodes.append(snode)
                except Exception:
                    continue

        # ── Build dataset metadata ─────────────────────────────────────────────
        # A dataset may carry several distributions (files) — e.g. a normalised
        # "processed" file plus the original "raw" instrument file kept for
        # provenance. Collect every distribution, not just the last.
        ds_meta: dict[str, dict] = {}
        _ds_recs = record_sets.get("dataset", [])
        if _ds_recs:
            for raw in _ds_recs:
                try:
                    ds    = raw.get("dataset", {})
                    ds_id = ds.get("id", "")
                    ti    = ds_to_test.get(ds_id, {})
                    dists = []
                    for dist in (ds.get("distributions") or []):
                        url   = dist.get("content_url") or ""
                        fname = Path(url.replace("file:///", "").replace("file://", "")).name
                        cs    = dist.get("checksum", {})
                        dists.append({
                            "filename":     fname,
                            "content_url":  url,
                            "format":       dist.get("encoding_format", ""),
                            "checksum":     cs.get("value", ""),
                            "role":         dist.get("role", ""),
                            "description":  dist.get("description", ""),
                            "content_size": dist.get("content_size", ""),
                        })
                    ds_meta[ds_id] = {
                        "name":      ds.get("name", ""),
                        "cell_id":   ti.get("cell_id", ""),
                        "test_iri":  ti.get("test_iri", ""),
                        "kind":      ti.get("kind", ""),
                        "dists":     dists,
                        "ds":        ds,   # full dataset record for discoverability fields
                    }
                except Exception:
                    continue

        # ── Build member dataset nodes (one dcat:Dataset per test result) ──────
        # The Zenodo record is a CATALOG; each test result is its own dcat:Dataset
        # grouping its distributions. A run's processed (.bdf.csv) and raw (.ndax)
        # files are two distributions (forms) of the SAME dataset — distributions of
        # one dataset are alternative representations, which is true within a run but
        # NOT across runs (those are distinct measurements on different cells).
        #
        # Provenance chain: Distribution ──wasGeneratedBy──> BatteryTest (processed)
        #                   BatteryTest  ──hasTestObject──>  CellInstance
        #                   BatteryTest  ──prov:used──>      TestSpec (plan)
        #                   CellInstance ──hasDescription──> CellSpec
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
            fname = dist["filename"]
            _files_base = files_base_url or f"{record_url}/files"
            cu = dist.get("content_url") or ""
            if cu.startswith(("http://", "https://")):
                return cu                       # already a hosted file — use verbatim
            if fname in data_filenames:
                return f"{_files_base}/{fname}"
            kind_zip = f"{kind}.zip"
            return f"{_files_base}/{kind_zip}" if kind_zip in data_filenames else ""

        for ds_id, meta in sorted(ds_meta.items()):
            dists = []
            schema_dists = []   # schema.org mirror of dcat:distribution (generated)
            # The hosted URL of the raw (pre-conversion) file, so each processed file
            # can declare prov:wasDerivedFrom it (the conversion provenance chain).
            _raw_url = next((_download_url(d, meta["kind"])
                             for d in meta["dists"] if d.get("role") == "raw"), "")
            for dist in meta["dists"]:
                fname = dist["filename"]
                dl_url = _download_url(dist, meta["kind"])

                media_type = dist["format"] or "application/x-parquet"
                # DCAT-AP: dcat:mediaType should be the IANA media-type IRI, not a bare
                # string. schema:encodingFormat (below) keeps the MIME string for
                # schema.org consumers.
                _iana_media = (f"https://www.iana.org/assignments/media-types/{media_type}"
                               if "/" in media_type else None)
                dnode: dict = {
                    "@type":            "dcat:Distribution",
                    "dcat:downloadURL": dl_url,
                    "dcat:mediaType":   {"@id": _iana_media} if _iana_media else media_type,
                    "schema:name":      fname,
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

                if dist["checksum"]:
                    dnode["spdx:checksum"] = {
                        "@type":                  "spdx:Checksum",
                        # IRI reference to the SPDX algorithm individual, not a literal.
                        "spdx:checksumAlgorithm": {"@id": "spdx:checksumAlgorithm_sha256"},
                        "spdx:checksumValue":     dist["checksum"],
                    }
                # File size: dcat:byteSize is an integer; schema:contentSize is text.
                _size = str(dist.get("content_size") or "")
                if _size.isdigit():
                    dnode["dcat:byteSize"] = int(_size)
                dists.append(dnode)

                # schema.org DataDownload mirror so a schema.org-only consumer can
                # reach the file bytes (schema.org has no dcat:downloadURL). Generated
                # from the same source in one pass, so it cannot drift from the DCAT form.
                sdl: dict = {
                    "@type":                "schema:DataDownload",
                    "schema:contentUrl":    dl_url,
                    "schema:encodingFormat": media_type,
                    "schema:name":          fname,
                    "schema:isPartOf":      {"@id": ds_id},
                }
                if dist["checksum"]:
                    sdl["schema:sha256"] = dist["checksum"]
                if dist.get("description"):
                    sdl["schema:description"] = dist["description"]
                if _size.isdigit():
                    sdl["schema:contentSize"] = _size
                if is_bdf:
                    sdl["dcterms:conformsTo"] = {"@id": BDF_TABLE_SCHEMA_IRI}
                schema_dists.append(sdl)

            cell_name = instances.get(meta.get("cell_id", ""), {}).get("name", "")
            ds_name = meta.get("name") or (
                f"{cell_name} {meta.get('kind', '')}".strip() or ds_id.split("/")[-1]
            )
            member: dict = {
                "@type":             ["dcat:Dataset", "schema:Dataset"],
                "@id":               ds_id,
                "schema:name":       ds_name,
                "dcat:distribution": dists,
                "schema:distribution": schema_dists,
                "dcterms:isPartOf":  {"@id": record_url},
            }
            if meta.get("cell_id"):
                # List form: schema:about may carry several subjects, and the
                # publication validator expects a uniform array of @id references.
                member["schema:about"] = [{"@id": meta["cell_id"]}]

            # ── Discoverability metadata (FAIR / Google Dataset Search) ────────
            # Carried straight from the dataset record when present, so every member
            # dataset — not just the catalog — is independently discoverable. All
            # additive: records that omit a field simply don't emit it.
            _ds = meta.get("ds") or {}
            if _ds.get("description"):
                member["schema:description"] = _ds["description"]
            if _ds.get("access_url", "").startswith(("http://", "https://")):
                # Only publish a web access URL here; a local file:// directory URL
                # (local-publication case) is set by that path's adapter instead.
                member["schema:url"] = _ds["access_url"]
            if _ds.get("license"):
                lic = _ds["license"]
                member["schema:license"] = {"@id": lic} if str(lic).startswith("http") else lic
            # Propagate catalog-level rights/attribution down to each member — RDF has
            # no inheritance, so a dataset lifted out of the catalog would otherwise lose
            # its licence and creators. Record-level values (above) take precedence.
            if "schema:license" not in member and license:
                _lic_iri = license if license.startswith("http") else f"https://spdx.org/licenses/{license}.html"
                member["schema:license"]  = {"@id": _lic_iri}
                member["dcterms:license"] = {"@id": _lic_iri}
            if creators:
                # Full creator nodes (not @id refs) so a member is self-describing even
                # lifted out of the catalog, and so creators without an ORCID @id are
                # still carried.
                member["schema:creator"] = [_agent_node(c) for c in creators]
            if _ds.get("keywords"):
                member["schema:keywords"] = list(_ds["keywords"])
            if _ds.get("version"):
                member["schema:version"] = _ds["version"]
            if _ds.get("measurement_techniques"):
                member["schema:measurementTechnique"] = list(_ds["measurement_techniques"])
            if _ds.get("measurement_methods"):
                member["schema:measurementMethod"] = list(_ds["measurement_methods"])
            # Dates: convert Unix timestamps to ISO-8601; pass ISO strings through.
            def _as_iso(v: object) -> object:
                return _unix_to_iso(int(v)) if isinstance(v, (int, float)) else v
            if _ds.get("created_at"):
                member["schema:dateCreated"] = _as_iso(_ds["created_at"])
            if _ds.get("modified_at"):
                member["schema:dateModified"] = _as_iso(_ds["modified_at"])
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
            cell_spec_id   = inst.get("cell_spec_id", "")
            spec_node = spec_nodes.get(cell_spec_id, {})
            # Inherit the physical type from the spec's isDescriptionFor
            phys_type = spec_node.get("isDescriptionFor", {}).get("@type", "BatteryCell")

            inode: dict = {
                "@type": phys_type,
                "@id":   cell_iri,
                "dcterms:conformsTo":  {"@id": cell_spec_id},   # instance-of link
                "hasDescription":      {"@id": cell_spec_id},
            }
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
                external_spec_stubs.append({
                    "@id":             tid,
                    "@type":           "BatteryCellSpecification",
                    "rdfs:isDefinedBy": {"@id": tid},
                })

        # ── Compose @graph ─────────────────────────────────────────────────────
        # The Zenodo record is a CATALOG of the per-test datasets above, not a flat
        # bag of distributions: those files are distinct measurements, not
        # alternative encodings of one dataset. schema:Dataset/Collection typing is
        # kept so Zenodo and schema.org consumers still see a top-level dataset — it
        # carries the DOI for the whole deposit.
        member_refs = [{"@id": ds_id} for ds_id in sorted(ds_meta)]
        catalog_node: dict = {
            # dcat:Catalog + schema:DataCatalog so catalog-aware consumers in both
            # vocabularies recognise it; schema:Dataset is retained so generic
            # schema.org/Zenodo consumers still see a top-level dataset carrying the DOI.
            "@type":             ["dcat:Catalog", "schema:DataCatalog", "schema:Dataset"],
            "@id":               record_url,
            "schema:url":        record_url,
            "dcat:dataset":      member_refs,   # DCAT: catalog → member datasets
            "schema:hasPart":    member_refs,   # schema.org equivalent
            "rdfs:seeAlso":      {"@id": "https://www.battery-genome.org/registry"},
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
            catalog_node["dcterms:title"] = title          # DCAT consumers key on dcterms
        if description:
            catalog_node["schema:description"] = description
            catalog_node["dcterms:description"] = description
        # English text; declare it so language-aware consumers don't have to guess.
        catalog_node["dcterms:language"] = "en"
        catalog_node["schema:inLanguage"] = "en"
        if license:
            # Emit the licence as a dereferenceable IRI (SPDX) rather than a bare code,
            # so a consumer can resolve the exact terms. Matches the RO-Crate path.
            lic_iri = license if license.startswith("http") else f"https://spdx.org/licenses/{license}.html"
            catalog_node["dcterms:license"] = {"@id": lic_iri}
            catalog_node["schema:license"]  = {"@id": lic_iri}
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
                "@type":       ["schema:Organization", "prov:Agent"],
                "@id":         _ror_url(provider_ror) if provider_ror else f"{record_url}#provider",
                "schema:name": provider_name,
            }
            catalog_node["schema:publisher"]    = {"@id": provider_node["@id"]}
            catalog_node["dcterms:publisher"]   = {"@id": provider_node["@id"]}  # DCAT mirror
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
        for _sn in spec_nodes.values():
            for _k in ("battinfo:chemistry", "battinfo:cellFormat"):
                if _sn.get(_k):
                    _kw.add(str(_sn[_k]))
            _mfr = _sn.get("schema:manufacturer")
            if isinstance(_mfr, dict) and _mfr.get("schema:name"):
                _kw.add(_mfr["schema:name"])
        for _m in ds_meta.values():
            if _m.get("kind"):
                _kw.add(str(_m["kind"]))
        for _k in (keywords or []):
            _kw.add(str(_k))
        _kw.discard("")
        if _kw:
            catalog_node["schema:keywords"] = sorted(_kw)
            catalog_node["dcat:keyword"]    = sorted(_kw)   # DCAT mirror of schema:keywords

        graph = (
            [catalog_node]
            + ([provider_node] if provider_node else [])
            + dataset_member_nodes
            + list(spec_nodes.values())
            + external_spec_stubs
            + test_spec_nodes
            + instance_nodes
            + test_nodes
        )

        # ── Inline context: load from records.context.json + dynamic prefLabel terms ─
        # _RECORDS_CONTEXT is generated by `python scripts/assemble_context.py`
        # from schema/*.yaml (the LinkML single source of truth).
        # _LABEL_TO_COMPACT adds quantity/unit prefLabels loaded from curated JSON maps.
        context = dict(_RECORDS_CONTEXT)
        context.update(_LABEL_TO_COMPACT)
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
        data_filenames: list[str],
        title: str = "",
        description: str = "",
        creators: list[dict] | None = None,
        contributors: list[dict] | None = None,
        license: str = "",
        keywords: list[str] | None = None,
        version: str = "",
        is_version_of: str = "",
    ) -> dict:
        """Read this workspace's saved records and assemble the deposit JSON-LD.

        Thin adapter over :meth:`_assemble_zenodo_jsonld` (the shared graph builder):
        it only sources the canonical record dicts from the workspace directory.
        """
        record_sets = _read_record_sets(self._records_root / "examples")
        return self._assemble_zenodo_jsonld(
            record_sets,
            zenodo_record_id=zenodo_record_id,
            prereserved_doi=prereserved_doi,
            record_url=record_url,
            data_filenames=data_filenames,
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
        data_filenames: list[str],
        *,
        title: str,
        description: str,
        creators: list[dict],
        contributors: list[dict],
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
        """
        import hashlib

        domain    = "sandbox.zenodo.org" if sandbox else "zenodo.org"
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

        creator_nodes     = [_creator_node(c) for c in creators] if creators else []
        contributor_nodes = [_contributor_node(c) for c in contributors] if contributors else []

        # Root Dataset
        parts = [{"@id": BATTINFO_LD_FILENAME}] + [{"@id": fn} for fn in data_filenames]
        root: dict = {
            "@type":         "Dataset",
            "@id":           "./",
            "name":          title,
            "description":   description,
            "datePublished": _now_iso()[:10],
            "license":       {"@id": f"https://spdx.org/licenses/{license}.html"},
            "url":           record_url,
            "identifier":    prereserved_doi,
            "hasPart":       parts,
        }
        if creator_nodes:
            root["creator"] = creator_nodes if len(creator_nodes) > 1 else creator_nodes[0]
        if contributor_nodes:
            root["contributor"] = contributor_nodes if len(contributor_nodes) > 1 else contributor_nodes[0]

        # linked-data file entity
        jsonld_entity: dict = {
            "@type":          ["File", "CreativeWork"],
            "@id":            BATTINFO_LD_FILENAME,
            "name":           "BattINFO linked data",
            "description":    "Battery domain metadata using EMMO/domain-battery ontology terms.",
            "encodingFormat": "application/ld+json",
            "conformsTo":     {"@id": "https://w3id.org/battinfo/"},
        }
        jsonld_path = tmpdir / BATTINFO_LD_FILENAME
        if jsonld_path.exists():
            jsonld_entity["contentSize"] = str(jsonld_path.stat().st_size)

        # Data file entities
        file_entities: list[dict] = []
        for fn in data_filenames:
            fp = tmpdir / fn
            entity: dict = {
                "@type": "File",
                "@id":   fn,
                "name":  fn,
                "encodingFormat": (
                    "application/x-parquet" if fn.endswith(".parquet")
                    else "text/csv" if fn.endswith(".csv")
                    else "application/zip" if fn.endswith(".zip")
                    else "application/octet-stream"
                ),
            }
            if fp.exists():
                entity["contentSize"] = str(fp.stat().st_size)
                sha = hashlib.sha256(fp.read_bytes()).hexdigest()
                entity["sha256"] = sha
            file_entities.append(entity)

        graph = [
            # Required self-reference node
            {
                "@type":      "CreativeWork",
                "@id":        "ro-crate-metadata.json",
                "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
                "about":      {"@id": "./"},
            },
            root,
            jsonld_entity,
            *file_entities,
        ]

        crate = {
            "@context": "https://w3id.org/ro/crate/1.1/context",
            "@graph":   graph,
        }
        (tmpdir / "ro-crate-metadata.json").write_text(
            json.dumps(crate, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _build_zenodo_metadata(
        self,
        *,
        title: str | None,
        description: str | None,
        creators: list[dict],
        contributors: list[dict] | None = None,
        license: str,
        community: str | None,
        extra_keywords: list[str] | None,
    ) -> dict:
        ct_dir = self._records_root / "examples" / "cell-spec"
        specs: list[dict] = []
        if ct_dir.exists():
            for f in sorted(ct_dir.glob("*.json")):
                try:
                    raw  = json.loads(f.read_text(encoding="utf-8"))
                    prod = raw.get("cell_spec", {})
                    mfr  = prod.get("manufacturer", {})
                    specs.append({
                        "manufacturer": mfr.get("name", "") if isinstance(mfr, dict) else str(mfr),
                        "model":       prod.get("model", ""),
                        "chemistry":   prod.get("chemistry", ""),
                        "format":      prod.get("cell_format", ""),
                        "iec_code":    prod.get("iec_code", ""),
                    })
                except Exception:
                    continue

        def _clean_meta(v: Any) -> str | None:
            """Drop empty / placeholder ('unknown') metadata so it never leaks into
            the published title, description, or keywords (no double spaces, no
            literal 'unknown')."""
            text = str(v).strip() if v is not None else ""
            return text if text and text.lower() != "unknown" else None

        s0 = specs[0] if specs else {}
        n_ds = len(list((self._records_root / "examples" / "dataset").glob("*.json"))
                   if (self._records_root / "examples" / "dataset").exists() else [])

        if s0:
            name_parts = [p for p in (_clean_meta(s0.get("manufacturer")), _clean_meta(s0.get("model"))) if p]
            attr_parts = [p for p in (_clean_meta(s0.get("format")), _clean_meta(s0.get("chemistry"))) if p]
            subject = " ".join(name_parts)
            auto_title = f"{subject or 'Battery'} — BattINFO Battery Dataset"
            if attr_parts:
                subject = f"{subject} ({', '.join(attr_parts)})".strip()
            auto_desc = (
                f"Battery dataset for {subject or 'battery cells'}. "
                f"Contains {n_ds} dataset(s). "
                "Published via BattINFO (https://github.com/BIG-MAP/BattINFO)."
            )
        else:
            auto_title = "Battery Dataset — BattINFO"
            auto_desc = "Battery dataset published via BattINFO."

        kw: list[str] = ["BattINFO", "battery", "electrochemistry"]
        for s in specs:
            for v in (s["manufacturer"], s["model"], s["chemistry"], s["format"], s["iec_code"]):
                cv = _clean_meta(v)
                if cv and cv not in kw:
                    kw.append(cv)
        for k in (extra_keywords or []):
            if k not in kw:
                kw.append(k)

        meta: dict = {
            "upload_type":  "dataset",
            "title":        title or auto_title,
            "description":  description or auto_desc,
            "creators":     creators,
            "access_right": "open",
            "license":      license,
            "keywords":     kw,
        }
        if contributors:
            # Zenodo requires a "type" on each contributor; default to "ProjectMember"
            meta["contributors"] = [
                {**c, "type": c.get("type", "ProjectMember")}
                for c in contributors
            ]
        if community:
            meta["communities"] = [{"identifier": community}]
        # Funding project (grant) → a related identifier pointing at the project's
        # resolvable page (CORDIS for EU grants). Safe: Zenodo always accepts a URL
        # related identifier, so it never risks failing the deposit (unlike the
        # native `grants` field, which 400s on an id Zenodo doesn't recognise).
        ref = self._get_project()
        if ref is not None and ref.id:
            meta.setdefault("related_identifiers", []).append({
                "identifier": ref.id,
                "relation": "isPartOf",
                "scheme": "url",
            })
        return meta

    def _zenodo_state_path(self) -> Path:
        return self._root / ".battinfo" / "zenodo.json"

    def _load_zenodo_state(self) -> dict:
        p = self._zenodo_state_path()
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

    def _save_zenodo_state(self, state: dict) -> None:
        p = self._zenodo_state_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

    # ── Conversion provenance: converted-file → original-source mapping ──────────
    def _conversions_path(self) -> Path:
        return self._root / ".battinfo" / "conversions.json"

    def _load_conversions(self) -> dict[str, str]:
        """Mapping of converted-file path → original source path (both absolute)."""
        if self._conversion_sources is None:
            p = self._conversions_path()
            self._conversion_sources = (
                json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
            )
        return self._conversion_sources

    def _record_conversion(self, src: Path, out: Path) -> None:
        """Remember that *out* was converted from *src*, for provenance at publish."""
        conv = self._load_conversions()
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
        src = conv.get(str(data_path.resolve()))
        if not src:
            return None
        sp = Path(src)
        return sp if sp.exists() else None

    def export(
        self,
        fmt: str = "json-ld",
        output_dir: str | Path | None = None,
    ) -> list[Path]:
        """Export all workspace records as RDF.

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
            "json-ld":  ("json-ld", ".jsonld"),
            "jsonld":   ("json-ld", ".jsonld"),
            "json_ld":  ("json-ld", ".jsonld"),
            "ttl":      ("turtle",  ".ttl"),
            "turtle":   ("turtle",  ".ttl"),
            "xml":      ("xml",     ".rdf"),
            "rdf":      ("xml",     ".rdf"),
            "nt":       ("nt",      ".nt"),
            "ntriples": ("nt",      ".nt"),
            "n3":       ("n3",      ".n3"),
        }
        rdflib_fmt, ext = _FMT_MAP.get(fmt.lower(), (fmt.lower(), f".{fmt.lower()}"))

        records_root = self._records_root / "examples"
        if not records_root.exists():
            print("  No records found — run ws.save() first.")
            return []

        out_root = Path(output_dir).resolve() if output_dir else None
        written: list[Path] = []

        _TYPE_MAP = {
            "cell-spec":     "cell-spec",
            "cell-instance": "cell-instance",
            "test":          "test",
            "dataset":       "dataset",
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
                    doc = record_to_jsonld(raw, jsonld_type)
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
                        dst.write_text(g.serialize(format=rdflib_fmt),
                                       encoding="utf-8")
                    written.append(dst)
                except Exception as exc:
                    print(f"  WARNING: {src.name} — {exc}")

        print(f"Exported {len(written)} file(s) [{fmt}] to "
              f"{out_root or records_root}")
        return written

    # ── Internal helpers ────────────────────────────────────────────────────────

    def _search_records(self, terms: list[str], threshold: float = 0.75) -> list[dict]:
        cache = self._get_search_cache()
        scored: list[tuple[float, dict]] = []
        for entry in cache:
            score = _fuzzy_score(terms, entry["_mfr"], entry["_model"],
                                 frozenset(entry.get("_size") or []))
            if score < threshold:
                continue

            if entry.get("source") == "api":
                scored.append((score, {
                    "id":            entry["id"],
                    "_canonical_id": entry.get("_canonical_id", ""),
                    "manufacturer":  entry["_mfr"],
                    "model":         entry["_model"],
                    "source":        "api",
                }))
            else:
                try:
                    data = json.loads(Path(entry["source"]).read_text(encoding="utf-8"))
                except Exception:
                    continue
                product = data.get("cell_spec", {})
                mfr = product.get("manufacturer", {})
                scored.append((score, {
                    "id":           entry["id"],
                    "manufacturer": mfr.get("name", "") if isinstance(mfr, dict) else str(mfr),
                    "model":        product.get("model", ""),
                    "source":       entry["source"],
                    "_record":      data,
                }))
        scored.sort(key=lambda x: -x[0])
        return [r for _, r in scored]

    _INDEX_FILE = ".search-index.json"

    def _get_search_cache(self) -> list[dict]:
        """Return the search index: registry API first, local clone as fallback."""
        if self._search_cache is not None:
            return self._search_cache
        if self._registry_url:
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

    def _build_api_cache(self) -> list[dict]:
        """Fetch all published cell-spec summaries from the registry API."""
        import urllib.request
        url = f"{self._registry_url}/resources?resource_type=cell_spec"
        req = urllib.request.Request(url, headers={"User-Agent": "battinfo-client/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
            data = json.loads(resp.read().decode())

        entries: list[dict] = []
        for r in data:
            title    = r.get("title", "")
            metadata = r.get("metadata") or {}

            mfr   = str(metadata.get("manufacturer") or "").lower()
            model = str(metadata.get("model") or "").lower()
            if not mfr:
                # Fall back: parse first token of title as manufacturer
                parts = title.split(None, 1)
                mfr   = parts[0].lower() if parts else ""
                model = parts[1].lower() if len(parts) > 1 else ""

            size_code = str(metadata.get("size_code") or "")
            iec_code  = str(metadata.get("iec_code")  or "")
            size_exp  = _expand_size_codes(size_code, iec_code)

            entries.append({
                "id":            r.get("canonical_iri", ""),
                "_canonical_id": r.get("canonical_id", ""),
                "_mfr":          mfr,
                "_model":        model,
                "_size":         size_exp.split() if size_exp else [],
                "_title":        title,
                "source":        "api",
            })
        return entries

    def _load_or_build_index(self) -> list[dict]:
        """Load the persisted index if it matches current record count; rebuild otherwise."""
        curated = self._records_repo / "records" / "cell-spec"
        staging = self._records_repo / "records" / "_staging" / "cell-spec"
        index_path = self._records_repo / self._INDEX_FILE

        current_count = (
            sum(1 for _ in curated.glob("*/record.json")) if curated.exists() else 0
        ) + (
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
            (staging,  "*.json"),
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
                iec_code  = str(product.get("iec_code")  or "")
                size_exp  = _expand_size_codes(size_code, iec_code)
                entries.append({
                    "id":      product.get("id", ""),
                    "_mfr":   mfr_name.lower(),
                    "_model": str(product.get("model", "") or "").lower(),
                    "_size":  size_exp.split() if size_exp else [],
                    "source": str(f),
                })

        try:
            index_path.write_text(
                json.dumps({"count": current_count, "entries": entries}, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass  # index is optional — searches will be slower without it

        return entries

    def _load_from_file(self, path: Path) -> Any:
        raw = json.loads(path.read_text(encoding="utf-8"))
        # Filter out null spec values so the schema stays valid
        specs = {k: v for k, v in (raw.get("properties") or {}).items() if v and v.get("value") is not None}
        ct = self._ws.cell_spec(
            manufacturer=raw["manufacturer"],
            model=raw["model"],
            format=raw["format"],
            chemistry=raw["chemistry"],
            positive_electrode_basis=raw.get("positive_electrode_basis"),
            negative_electrode_basis=raw.get("negative_electrode_basis"),
            size_code=raw.get("size_code"),
            iec_code=raw.get("iec_code"),
            country_of_origin=raw.get("country_of_origin"),
            rechargeable=raw.get("rechargeable"),
            year=raw.get("year"),
            specs=specs or None,
            source_type="datasheet",
            source_file=raw.get("source_file"),
            citation=raw.get("citation"),
        )
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
        """
        from battinfo.bundle import CellInstance  # noqa: PLC0415
        cell = CellInstance(
            id=result.get("id"),
            cell_spec_id=result.get("cell_spec_id"),
            name=result.get("name"),
            serial_number=result.get("serial_number"),
            batch_id=result.get("batch_id"),
        )
        for label in (result.get("name"), result.get("serial_number")):
            if label:
                self._cells_by_short_id[label] = cell
                sid = _short_id(label)
                if sid:
                    self._cells_by_short_id[sid] = cell
        return cell

    def _reference_spec(self, result: dict) -> Any:
        """Build a referenced CellSpecification reusing its existing IRI (NOT queued to publish)."""
        from battinfo.bundle import CellSpecification, ProvenanceInfo  # noqa: PLC0415
        record = self._fetch_cell_spec_record(result) if result.get("source") == "api" else result.get("_record", {})
        product = record.get("cell_spec", {}) or {}
        specs_raw = record.get("properties", {}) or {}
        specs = {k: v for k, v in specs_raw.items() if isinstance(v, dict) and v.get("value") is not None}
        mfr = product.get("manufacturer") or {}
        mfr_name = mfr.get("name", "") if isinstance(mfr, dict) else str(mfr)
        ct = CellSpecification(
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

    def _add_cell_instances(
        self,
        spec: Any,
        from_file: str | Path | None = None,
        match: str | None = None,
        iris: list[str] | None = None,
        names: list[str] | None = None,
        serial_numbers: list[str] | None = None,
        grade: str | None = None,
        production_date: int | str | None = None,
        expiration_date: int | str | None = None,
        conformance: Any = None,
    ) -> list:
        """Create cell instances.

        * ``names`` — human labels (e.g. lab batch IDs); the primary identifier.
        * ``serial_numbers`` — manufacturer serials (optional); parallel to ``names``
          when both are given.
        * ``iris`` — pre-allocated IRIs to reuse instead of minting (parallel, equal length).
        * ``from_file`` — JSON file mapping ``{name: pre-allocated-IRI}``.
        """
        # Build (name, serial, iri) entries.
        entries: list[tuple[str | None, str | None, str | None]] = []

        if from_file is not None:
            fp = Path(from_file)
            if not fp.is_absolute():
                fp = self._root / fp
            raw = json.loads(fp.read_text(encoding="utf-8"))
            items = {k: v for k, v in raw.items() if not k.startswith("_") and v}
            if match:
                items = {k: v for k, v in items.items() if match.lower() in k.lower()}
            entries = [(label, None, iri) for label, iri in items.items()]
        else:
            if names is not None and serial_numbers is not None:
                if len(names) != len(serial_numbers):
                    raise ValueError(
                        f"names and serial_numbers must have the same length "
                        f"({len(names)} vs {len(serial_numbers)})."
                    )
                pairs = list(zip(names, serial_numbers))
            elif names is not None:
                pairs = [(n, None) for n in names]
            elif serial_numbers is not None:
                pairs = [(None, s) for s in serial_numbers]
            else:
                print("  No cell instances to add (pass names=[...] or serial_numbers=[...]).")
                return []

            if iris is not None:
                if len(iris) != len(pairs):
                    raise ValueError(
                        f"iris must match the number of cells "
                        f"({len(iris)} IRIs vs {len(pairs)} cells)."
                    )
                entries = [(n, s, iri) for (n, s), iri in zip(pairs, iris)]
            else:
                entries = [(n, s, None) for (n, s) in pairs]

            # Drop duplicates and cells already in this session (by their label).
            seen: set[str] = set()
            already: list[str] = []
            deduped: list[tuple[str | None, str | None, str | None]] = []
            for n, s, iri in entries:
                label = n or s or ""
                if label in seen:
                    continue
                if label and label in self._cells_by_short_id:
                    already.append(label)
                    continue
                seen.add(label)
                deduped.append((n, s, iri))
            if already:
                print(f"  WARNING: {len(already)} already in workspace — skipping: {already[:5]}"
                      + (" ..." if len(already) > 5 else ""))
            entries = deduped

        if not entries:
            print("  No cell instances to add" + (f" (match={match!r})." if match else "."))
            return []

        # Inherit spec properties as default measured values on each instance.
        spec_defaults: dict[str, Any] = {}
        try:
            specs_obj = getattr(spec, "properties", None)
            raw_specs: dict = specs_obj if isinstance(specs_obj, dict) else (
                spec.to_record().get("properties") or {}
            )
            spec_defaults = {
                k: v for k, v in raw_specs.items()
                if isinstance(v, dict) and v.get("value") is not None
            }
        except Exception:
            pass

        # Conformance (vs the cell spec): one value applied to all, or a parallel list.
        if isinstance(conformance, (list, tuple)):
            if len(conformance) != len(entries):
                raise ValueError(
                    f"conformance list must match the number of cells "
                    f"({len(conformance)} vs {len(entries)})."
                )
            confs = [_coerce_conformance(c) for c in conformance]
        else:
            confs = [_coerce_conformance(conformance)] * len(entries)

        cells = []
        for (name, serial, iri), conf in zip(entries, confs):
            cell = self._ws.cell(
                spec,
                name=name,
                serial_number=serial,
                grade=grade,
                manufactured_at=production_date,
                expires_at=expiration_date,
                measured=spec_defaults if spec_defaults else None,
                conformance=conf,
            )
            if iri is not None:
                cell.id = iri
            # Index by both the name and the serial (and their short IDs) for matching.
            for label in (name, serial):
                if label:
                    self._cells_by_short_id[label] = cell
                    sid = _short_id(label)
                    if sid:
                        self._cells_by_short_id[sid] = cell
            cells.append(cell)
            print(f"  cell: {name or serial}  {iri or '(IRI auto-assigned)'}")
        return cells

    def _load_test_spec(self, path: Path) -> Any:
        raw = json.loads(path.read_text(encoding="utf-8"))
        # Forward the authored method so it survives into the saved record (and
        # thence the published JSON-LD as an EMMO process graph). Humans author the
        # PyBaMM-style `experiment`/`steps` strings; a pre-built structured `method`
        # is also accepted. Protocol-level record/safety/conditions/artifacts pass through.
        tp = self._ws.test_protocol(
            name=raw.get("name", ""),
            type=raw.get("type") or raw.get("kind", ""),
            description=raw.get("description"),
            experiment=raw.get("experiment") or raw.get("steps"),
            cycles=raw.get("cycles"),
            method=raw.get("method"),
            conditions=raw.get("conditions"),
            record=raw.get("record"),
            safety=raw.get("safety"),
            artifacts=raw.get("artifacts"),
        )
        return tp

    def _add_tests(
        self,
        type: str | None = None,
        *,
        cell: Any = None,
        data: "str | Path | list[str | Path] | None" = None,
        raw: "str | Path | list[str | Path] | None" = None,
        datasets: "str | list[str | Path] | None" = None,
        kind: str | None = None,                 # backward-compat alias for type
        spec: Any = None,
        protocol: Any = None,                    # backward-compat alias for spec
        conformance: Any = None,
        name: str | None = None,
        instrument: str | None = None,
        license: str | None = None,
        description: str | None = None,
        status: str = "completed",
    ) -> list:
        """Create a test (+ dataset(s)).

        Explicit (preferred): ``cell=<serial|IRI|object>`` and ``data=<path|list>``.
        Batch: ``datasets="glob"`` matches files to loaded cells by short ID.

        ``raw`` attaches the original, pre-conversion instrument file(s) alongside
        each processed ``data`` file as a "raw"-role distribution, so the source
        travels with the deposit for provenance. If omitted, originals recorded by
        :meth:`convert` are attached automatically.

        ``conformance`` flags how the run followed its referenced test spec — a status
        string (``"conformant"`` / ``"non-conformant"``; ``"unknown"`` = not assessed)
        or a dict ``{"status": ..., "note": ..., "deviations": [...]}``. Pass the spec
        via ``spec=`` so the conformance binds to it.
        """
        # Resolve the test type (type=, legacy kind=, or from a linked spec).
        test_type = type or kind
        test_spec = spec if spec is not None else protocol
        protocol_name = protocol_url = None
        if test_spec is not None:
            if isinstance(test_spec, str):
                protocol_name = test_spec
            else:
                protocol_name = getattr(test_spec, "name", None)
                protocol_url = getattr(test_spec, "id", None)
                spec_kind = getattr(test_spec, "test_type", None)
                if spec_kind is not None and not test_type:
                    test_type = spec_kind.value if hasattr(spec_kind, "value") else str(spec_kind)
        if not test_type:
            raise ValueError(
                "ws.add('test', ...) requires type=... (or a spec that defines it). "
                + _test_kind_hint()
            )
        test_type = _normalize_test_kind(test_type)
        protocol_name = protocol_name or test_type.replace("_", " ")
        # Link the test to its spec object so conformance binds to that spec's IRI.
        protocol_ref = test_spec if (test_spec is not None and not isinstance(test_spec, str)) else None

        # Normalise / validate the conformance flag (status + optional deviations).
        conformance = _coerce_conformance(conformance)

        # ── Explicit mode: a named cell (+ optional data files) ──────────────────
        if cell is not None:
            resolved = self._resolve_cell(cell)
            files = self._as_data_paths(data)
            raw_files = self._as_data_paths(raw)
            if raw_files and len(raw_files) != len(files):
                raise ValueError(
                    f"raw= has {len(raw_files)} file(s) but data= has {len(files)}; "
                    "pass one original per processed file (same order), or omit raw= "
                    "to use the originals recorded by ws.convert()."
                )
            # Measured period per data file (from the BDF unix_time_second column), so
            # the test activity and each dataset are placed in time from the data itself
            # rather than the record-assembly clock.
            periods = [_bdf_measurement_period(f) for f in files]
            _spans = [p for p in periods if p]
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
                started_at=min(s for s, _ in _spans) if _spans else None,
                ended_at=max(e for _, e in _spans) if _spans else None,
            )
            label = getattr(resolved, "name", None) or getattr(resolved, "serial_number", None) or resolved.id or "cell"
            n_raw = 0
            for i, f in enumerate(files):
                # Explicit raw= wins; otherwise fall back to the convert() manifest.
                src = raw_files[i] if raw_files else self._resolve_raw_source(f)
                if src is not None:
                    n_raw += 1
                _per = periods[i]
                _tc = (f"{_unix_to_iso(_per[0])}/{_unix_to_iso(_per[1])}" if _per else None)
                self._ws.dataset(
                    resolved,
                    title=f"{name or label} data",
                    test=test,
                    path=f,
                    source_path=src,
                    license=license,
                    format=_guess_format(f),
                    temporal_coverage=_tc,
                )
            conf_status = conformance.status if conformance is not None else None
            print(f"  test [{test_type}] on {label}"
                  + (f"  +{len(files)} dataset(s)" if files else "")
                  + (f"  (+{n_raw} raw source{'s' if n_raw != 1 else ''})" if n_raw else "")
                  + (f"  conformance: {conf_status}" if conf_status else ""))
            return [test]

        # ── Batch mode: match a glob of files to loaded cells by short ID ────────
        if datasets is not None:
            if conformance is not None:
                raise ValueError(
                    "conformance is per-test — use the explicit form "
                    "ws.add('test', cell=..., conformance=...) to flag each test."
                )
            return self._add_tests_by_filename(
                test_type, datasets, protocol_name, protocol_url, protocol_ref,
                instrument, license, description, status,
            )

        raise ValueError(
            "ws.add('test', ...) needs either cell=<serial|IRI|object> (with data=...) "
            "for an explicit test, or datasets='glob' to match files to loaded cells."
        )

    def _as_data_paths(self, data: Any) -> list[Path]:
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
        """Resolve a cell reference: this session, then local index, then the registry.

        Accepts a ``CellInstance``, a search result, a serial / short ID, or an IRI.
        An instance found only in the registry is referenced (not re-published).
        """
        from battinfo.bundle import CellInstance  # noqa: PLC0415
        if isinstance(ref, CellInstance):
            return ref
        if isinstance(ref, dict):  # a search result
            return self.load(ref)
        if isinstance(ref, str):
            s = ref.strip()
            if s.startswith("http"):  # an IRI
                return self._reference_cell({"id": s, "type": "cell"})
            hit = self._cells_by_short_id.get(s)
            if hit is None and _short_id(s):
                hit = self._cells_by_short_id.get(_short_id(s))
            if hit is not None:
                return hit
            found = self._query_registry_cells(serials=[s])
            if found:
                return self._reference_cell({**found[0], "type": "cell"})
            raise ValueError(
                f"Could not resolve cell {ref!r} in this session, locally, or the registry. "
                "Create it with ws.add('cell', ...), or check the serial."
            )
        raise TypeError("cell= must be a serial, IRI, CellInstance, or search result.")

    def _add_tests_by_filename(
        self,
        test_type: str,
        datasets: "str | list[str | Path]",
        protocol_name: str | None,
        protocol_url: str | None,
        protocol_ref: Any,
        instrument: str | None,
        license: str | None,
        description: str | None,
        status: str,
    ) -> list:
        """Batch helper: match a glob of data files to loaded cells by short ID."""
        if isinstance(datasets, str):
            matched_files = sorted(self._root.glob(datasets))
        else:
            matched_files = [Path(p) if not isinstance(p, Path) else p for p in datasets]
            matched_files = [p if p.is_absolute() else self._root / p for p in matched_files]
        if not matched_files:
            print(f"  No dataset files matched: {datasets!r}")
            return []

        # Auto-reload cells saved in a previous session so matching can succeed.
        if not self._cells_by_short_id:
            ci_dir = self._records_root / "examples" / "cell-instance"
            if ci_dir.exists() and any(ci_dir.glob("*.json")):
                print("  No cells in memory - reloading saved cell instances...")
                self.reload_cells()
        if not self._cells_by_short_id:
            raise RuntimeError(
                "No cell instances available to match.\n"
                "  Create them:                ws.add('cell', spec=spec, serial_numbers=[...])\n"
                "  Or reference existing ones: ws.load(ws.search(type='cell', batch='...'))"
            )

        print(f"Matching {len(matched_files)} file(s) to cell instances...")
        unmatched: list[Path] = []
        tests = []
        for f in matched_files:
            sid = _short_id(f.stem)
            if sid and sid in self._cells_by_short_id:
                cell, how = self._cells_by_short_id[sid], f'short id "{sid}"'
            elif f.stem in self._cells_by_short_id:
                cell, how = self._cells_by_short_id[f.stem], "serial number"
            else:
                unmatched.append(f)
                print(f"  NO MATCH  {f.name}")
                continue
            test = self._ws.record_test(
                cell, kind=test_type, path=f, protocol=protocol_name,
                protocol_url=protocol_url, protocol_ref=protocol_ref, description=description,
                instrument=instrument, status=status, license=license,
                format=_guess_format(f),
                source_path=self._resolve_raw_source(f),
            )
            print(f"  matched   {f.name}  ->  {cell.name or cell.serial_number}  (by {how})")
            tests.append(test)

        if unmatched:
            known = sorted({
                (c.name or c.serial_number) for c in self._cells_by_short_id.values()
                if getattr(c, "name", None) or getattr(c, "serial_number", None)
            })
            print(f"\n  {len(unmatched)} file(s) had no matching cell instance:")
            for f in unmatched:
                print(f"    {f.name}")
            stems = ", ".join(repr(f.stem) for f in unmatched[:5])
            print("  Reference the missing cells (e.g. registered at manufacture), then re-run:")
            print(f"      ws.load(ws.search(type='cell', serials=[{stems}]))")
            print("  ...or pass them explicitly: ws.add('test', cell='<serial>', data='<file>').")
            if known:
                shown = ", ".join(known[:8]) + (" ..." if len(known) > 8 else "")
                print(f"  Cells currently in this workspace: {shown}")

        print(f"\nCreated {len(tests)} test(s)"
              + (f"; {len(unmatched)} unmatched file(s) skipped" if unmatched else ""))
        return tests


def _norm(s: str) -> str:
    """Lowercase and strip all non-alphanumeric characters."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


# Canonical size-code alias groups.  Every alias in a group expands to all others,
# so searching any of them matches cells indexed under any of them.
_SIZE_ALIAS_GROUPS: list[list[str]] = [
    ["r03",   "lr03",  "fr03",  "aaa",   "tripleа"],
    ["r6",    "lr6",   "fr6",   "aa",    "doublea"],
    ["r14",   "lr14",  "c"],
    ["r20",   "lr20",  "d"],
    ["lr1",   "r1",    "n"],
    ["6lr61", "6f22",  "9v"],
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


def _now_iso() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


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
    return {
        "schema_version": "0.1.0",
        "kind": "BattinfoSubmission",
        "submission_mode": "resource",
        "generated_at": _now_iso(),
        "workspace_id": wid,
        "publisher_id": pid,
        "source_version": ver,
        "title": title,
        "publication_intent": {"mode": STAGED_PUBLICATION_MODE},
        "provenance": {
            "source_system": "battinfo-authoring",
            "workflow_name": "authoring-workspace-submission",
            "generated_at": _now_iso(),
        },
        "release": {"version": ver},
        "workspace": None,
        "resource": {
            "resource_type": "cell_spec",
            "source_local_id": source_local_id,
            "title": title,
            "semantic_payload": {
                "@type": "CellSpecification",
                "battinfo_records": {"cell_spec": record},
            },
            "related_resources": related_resources or [],
            "distributions": [],
        },
        "artifacts": [],
        "validation": {"ok": True, "errors": [], "policy": "default"},
    }


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
            related.append({
                "relationship": "instanceOf",
                "resource_type": "cell_spec",
                "canonical_iri": cell_spec_id,
            })

    semantic_payload: dict = {
        "@type": "CellInstance",
        "battinfo_records": {
            "cell": record,
            **({"cell_spec": spec_record} if spec_record else {}),
        },
    }
    if preview:
        semantic_payload["preview"] = preview

    return {
        "schema_version": "0.1.0",
        "kind": "BattinfoSubmission",
        "submission_mode": "resource",
        "generated_at": _now_iso(),
        "workspace_id": wid,
        "publisher_id": pid,
        "source_version": ver,
        "title": title,
        "publication_intent": {"mode": STAGED_PUBLICATION_MODE},
        "provenance": {
            "source_system": "battinfo-authoring",
            "workflow_name": "authoring-workspace-submission",
            "generated_at": _now_iso(),
        },
        "release": {"version": ver},
        "workspace": None,
        "resource": {
            "resource_type": "cell",
            "source_local_id": source_local_id,
            "title": title,
            "semantic_payload": semantic_payload,
            "related_resources": related,
            "distributions": [],
        },
        "artifacts": [],
        "validation": {"ok": True, "errors": [], "policy": "default"},
    }


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
            top_level.append({"title": name, "access_url": url, "role": "plot_data",
                              "media_type": fmt or "application/json"})
        elif name.endswith(".png"):
            top_level.append({"title": name, "access_url": url, "role": "plot_static",
                              "media_type": fmt or "image/png"})
        else:
            inner.append(d)
            top_level.append({"title": name or d.get("role") or "data", "access_url": url,
                              "role": d.get("role") or "processed", "media_type": fmt})
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
            related.append({
                "relationship": "about",
                "resource_type": "cell",
                "canonical_iri": related_cell_id,
            })
    semantic_payload: dict = {
        "@type": rdf_type,
        "battinfo_records": {record_key: record},
    }
    if preview:
        semantic_payload["preview"] = preview
    return {
        "schema_version": "0.1.0",
        "kind": "BattinfoSubmission",
        "submission_mode": "resource",
        "generated_at": _now_iso(),
        "workspace_id": wid,
        "publisher_id": pid,
        "source_version": ver,
        "title": title,
        "publication_intent": {"mode": STAGED_PUBLICATION_MODE},
        "provenance": {
            "source_system": "battinfo-authoring",
            "workflow_name": "authoring-workspace-submission",
            "generated_at": _now_iso(),
        },
        "release": {"version": ver},
        "workspace": None,
        "resource": {
            "resource_type": resource_type,
            "source_local_id": source_local_id,
            "title": title,
            "semantic_payload": semantic_payload,
            "related_resources": related,
            "distributions": distributions or [],
        },
        "artifacts": [],
        "validation": {"ok": True, "errors": [], "policy": "default"},
    }


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


def _do_submit(
    payload: dict,
    url: str,
    key: str,
    title: str,
    *,
    source_local_id: str = "",
    publication_mode: str = STAGED_PUBLICATION_MODE,
    validation: dict[str, Any] | None = None,
) -> dict:
    """Submit one record; return a structured outcome (never silently drop it).

    Retries once with a bumped source_version on 409. Returns a dict with ``ok``
    (True for published/validated, False for failed/rejected/errored), ``status``,
    ``error`` (the message when not ok), ``iri`` and the raw ``result``. A failed
    record is reported in the outcome, never swallowed, so the batch surfaces it.
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
            result = submit_publication_package(payload, registry_base_url=url, api_key=key)
            response = result.get("response") if isinstance(result.get("response"), dict) else {}
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
            return {"title": title, "source_local_id": source_local_id, "ok": ok,
                    "status": status, "iri": iri, "error": None, "result": result,
                    "version_bumped": bumped_version}
        except RuntimeError as exc:
            # Prefer the structured status code (RegistryClientError.status_code) over matching
            # the string "409", which could appear anywhere in an error/response body.
            is_conflict = getattr(exc, "status_code", None) == 409 or "409" in str(exc)
            if attempt == 0 and is_conflict:
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
                print(f"  {title}  [conflict — retrying as version {bumped_version}]")
                continue
            print(f"  ERROR: {title} — {exc}")
            return {"title": title, "source_local_id": source_local_id, "ok": False,
                    "status": "error", "iri": "", "error": str(exc), "result": None,
                    "version_bumped": bumped_version}
    # Unreachable in practice (the loop returns on every path); defensive for mypy.
    return {"title": title, "source_local_id": source_local_id, "ok": False,
            "status": "error", "iri": "", "error": "submission failed after retry", "result": None,
            "version_bumped": bumped_version}


def _bump_version(ver: str) -> str:
    """Increment a trailing counter on a version string: '2026-05-29' → '2026-05-29-v2'."""
    import re
    m = re.search(r"-v(\d+)$", ver)
    if m:
        return ver[: m.start()] + f"-v{int(m.group(1)) + 1}"
    return ver + "-v2"


def _import_resolve_source(source: str, *, sandbox: bool = False, token: str | None = None) -> str:
    """Return raw JSON-LD text from a Zenodo record ID, URL, or local file path."""
    import urllib.request

    # Local file
    p = Path(source)
    if p.exists():
        return p.read_text(encoding="utf-8")

    # URL
    if source.startswith("http://") or source.startswith("https://"):
        headers = {"User-Agent": "battinfo-client/1.0"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(source, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            return resp.read().decode("utf-8")

    # Zenodo record ID (numeric string)
    if source.isdigit():
        domain = "sandbox.zenodo.org" if sandbox else "zenodo.org"
        api_url = f"https://{domain}/api/records/{source}/files"
        headers = {"User-Agent": "battinfo-client/1.0"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            files = json.loads(resp.read())

        # Find the linked-data document (current battinfo.json, or legacy battinfo.jsonld).
        entry = next(
            (f for f in (files.get("entries") or [])
             if f.get("key") in (BATTINFO_LD_FILENAME, BATTINFO_LD_FILENAME_LEGACY)),
            None,
        )
        if entry is None:
            raise RuntimeError(
                f"No {BATTINFO_LD_FILENAME} found in Zenodo record {source}. "
                "Is this a battinfo-published record? "
                f"({BATTINFO_LD_FILENAME} is the standard entry point for battinfo Zenodo deposits.)"
            )
        download_url = entry.get("links", {}).get("content") or entry.get("url", "")
        return _import_resolve_source(download_url, token=token)

    raise ValueError(
        f"Cannot resolve import source {source!r}. "
        "Pass a Zenodo record ID, a URL, or a local file path."
    )


def _test_kind_values() -> list[str]:
    """Return the canonical test-kind strings from the BatteryTestType enum."""
    from battinfo.bundle import BatteryTestType  # noqa: PLC0415
    return [m.value for m in BatteryTestType]


# Common synonyms accepted as input and mapped to canonical BatteryTestType values.
# Keeps the authoring API forgiving without polluting the canonical vocabulary.
_TEST_KIND_ALIASES: dict[str, str] = {
    "calendar_aging": "calendar_ageing",   # American spelling
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
        f"{kind!r} is not a valid test kind. " + _test_kind_hint()
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
    record_id:      str
    doi:            str
    record_url:     str
    draft_url:      str
    published:      bool
    is_new_version: bool


_DEFAULT_REGISTRY_URL = "https://battinfo-registry.onrender.com"


def workspace(
    root: str | Path = ".",
    records_repo: str | Path | None = None,
    registry_url: str | None = _DEFAULT_REGISTRY_URL,
) -> AuthoringWorkspace:
    """Open (or create) a BattINFO workspace for authoring records.

    Parameters
    ----------
    root:
        Workspace directory. Records are written to ``{root}/.battinfo/records/``.
        Defaults to the current working directory.
    registry_url:
        Base URL of the battinfo-registry API.  Defaults to the canonical
        production registry.  Pass ``None`` to force offline/local-clone mode.
    records_repo:
        Path to a local ``battinfo-records`` clone for offline or development use.
        Auto-detected from sibling directories or ``BATTINFO_RECORDS`` env var
        if not given.  Only used when the registry is unreachable or ``registry_url``
        is ``None``.
    """
    return AuthoringWorkspace(root=root, records_repo=records_repo, registry_url=registry_url)
