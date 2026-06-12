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
from pathlib import Path
from typing import Any

# Short-name pattern: 6 lowercase alphanumeric characters at the end of a
# dash-delimited name component (e.g. "666h1s" in "duracell-mn2400-2026-02-666h1s").
_SHORT_ID_RE = re.compile(r"-([a-z0-9]{6})(?:\.|$)")

# NEWARE server suffix in filenames: _<IP>-<instrument>-<channels>
_SERVER_RE = re.compile(r"_\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}-")

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
# BattINFO workspace credentials
# This file is loaded automatically by battinfo.workspace().
# Keep it out of version control — add .battinfo/credentials to .gitignore.

BATTINFO_API_KEY       =
BATTINFO_WORKSPACE_ID  = battinfo-records
BATTINFO_PUBLISHER_ID  = battinfo-authoring
BATTINFO_ADMIN_TOKEN   =

# R2 storage (for ws.upload())
R2_ENDPOINT            =
R2_ACCESS_KEY_ID       =
R2_SECRET_ACCESS_KEY   =
R2_BUCKET              = battinfo-public
R2_PUBLIC_BASE_URL     =

# Zenodo (for ws.zenodo())
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

    candidates = [
        root.parents[1] / "battinfo-records",
        root.parents[2] / "battinfo-records",
        root.parent / "battinfo-records",
        root / "battinfo-records",
    ]
    for c in candidates:
        if (c / "records").exists():
            return c
    return None


_CONFORMANCE_IRI = {
    "conformant":     "https://w3id.org/battinfo/ConformanceStatus/Conformant",
    "partial":        "https://w3id.org/battinfo/ConformanceStatus/PartialConformance",
    "non-conformant": "https://w3id.org/battinfo/ConformanceStatus/NonConformant",
    "unknown":        "https://w3id.org/battinfo/ConformanceStatus/ConformanceUnknown",
}

_UNIX_EPOCH = "1970-01-01T00:00:00Z"

# Loaded once at import time; used as the base for all JSON-LD context dicts.
# Generated by `python scripts/assemble_context.py` from schema/*.yaml.
_RECORDS_CONTEXT: dict = json.loads(
    (Path(__file__).parent / "data" / "context" / "records.context.json")
    .read_text(encoding="utf-8")
)["@context"]


def _unix_to_iso(ts: int | None) -> str | None:
    """Convert a Unix timestamp (seconds) to an ISO-8601 datetime string."""
    if ts is None:
        return None
    import datetime
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _apply_conformance_jsonld(
    tnode: dict,
    protocol_id: str | None,
    conformance: dict | None,
) -> None:
    """Mutate *tnode* in-place to add PROV-O spec linkage and DQV conformance annotation."""
    if protocol_id:
        # prov:used links the test activity to the spec (its "plan" in PROV-O terms)
        tnode["prov:used"] = {"@id": protocol_id}
        # dct:conformsTo only when fully conformant (strong claim)
        if conformance and conformance.get("status") == "conformant":
            tnode["dcterms:conformsTo"] = {"@id": protocol_id}

    if not conformance:
        return

    status = conformance.get("status", "unknown")
    status_iri = _CONFORMANCE_IRI.get(status, _CONFORMANCE_IRI["unknown"])
    note = conformance.get("note")

    annotation: dict = {
        "@type": "dqv:QualityAnnotation",
        "oa:motivatedBy": {"@id": "oa:assessing"},
        "dqv:value": {"@id": status_iri},
    }
    if note:
        annotation["schema:description"] = note

    tnode["dqv:hasQualityAnnotation"] = annotation

    deviations = conformance.get("deviations") or []
    if deviations:
        influenced_by = []
        for dev in deviations:
            dev_node: dict = {
                "@type": "prov:Activity",
                "schema:description": f"{dev.get('type', 'deviation')}"
                + (f" — {dev['description']}" if dev.get("description") else ""),
            }
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
        tnode["prov:wasInfluencedBy"] = influenced_by


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
        # paths written by the most recent ws.save() — submit() uses this to
        # avoid re-submitting records from previous sessions in the same directory
        self._session_paths: set[Path] = set()

    # ── Public API ─────────────────────────────────────────────────────────────

    def setup(self) -> Path:
        """Create a credentials template at ``.battinfo/credentials``.

        Fill in the generated file with your API key and workspace/publisher IDs,
        then re-run the notebook.  The file is loaded automatically on every
        ``battinfo.workspace()`` call — no environment variables needed.

        The file should be added to ``.gitignore`` to avoid committing credentials.

        Example::

            ws.setup()
            # edit .battinfo/credentials
            # then re-run: ws = battinfo.workspace(".")
        """
        cred_path = self._root / ".battinfo" / "credentials"
        cred_path.parent.mkdir(parents=True, exist_ok=True)

        gitignore = self._root / ".gitignore"
        if gitignore.exists():
            content = gitignore.read_text(encoding="utf-8")
            if ".battinfo/credentials" not in content:
                gitignore.write_text(content.rstrip() + "\n.battinfo/credentials\n",
                                     encoding="utf-8")
        else:
            gitignore.write_text(".battinfo/credentials\n", encoding="utf-8")

        if cred_path.exists():
            print(f"Credentials file already exists: {cred_path}")
        else:
            cred_path.write_text(_CREDENTIALS_TEMPLATE, encoding="utf-8")
            print(f"Created: {cred_path}")
            print("  Fill in BATTINFO_API_KEY and BATTINFO_ADMIN_TOKEN, then re-run the notebook.")

        return cred_path

    def convert(self, pattern: str = "*.ndax", fmt: str = "csv") -> list[Path]:
        """Convert raw instrument files to BDF (Battery Data Format).

        Finds all files matching *pattern* in the workspace root, converts each
        to ``bdf/<batch-key>.bdf.<fmt>``, and skips files already converted.

        Requires the ``bdf`` package (``pip install bdf``).

        Parameters
        ----------
        pattern:
            Glob pattern for input files.  Defaults to ``*.ndax``.
        fmt:
            Output format — ``"csv"`` (default) or ``"parquet"``.

            **CSV** is the recommended archival format: universally readable,
            no library dependencies, suitable for Zenodo publication.
            **Parquet** is the working format: compressed, fast, columnar —
            use it when ingesting into the battery-genome analysis pipeline.

        Example::

            ws.convert()                    # CSV (default, for archival)
            ws.convert(fmt="parquet")       # Parquet (for analysis)
            ws.convert("*.nda")             # older NEWARE format → CSV
        """
        if fmt not in ("parquet", "csv"):
            raise ValueError(f"fmt must be 'parquet' or 'csv' (got {fmt!r})")

        try:
            import bdf as _bdf
            import bdf.io as _bdf_io
            import bdf.repair as _bdf_repair
        except ImportError:
            raise ImportError("bdf package not installed.  Run: pip install bdf")

        ndax_files = sorted(self._root.glob(pattern))
        if not ndax_files:
            print(f"  No files matched: {pattern!r}")
            return []

        bdf_dir = self._root / "bdf"
        bdf_dir.mkdir(exist_ok=True)

        suffix = f".bdf.{fmt}"
        written: list[Path] = []
        for ndax in ndax_files:
            batch_key = _make_batch_key(ndax.stem)
            out = bdf_dir / f"{batch_key}{suffix}"
            if out.exists():
                print(f"  skip (exists): {out.name}")
                continue
            print(f"  {ndax.name}")
            df = _bdf.read(ndax, validate=False)
            df = _bdf_repair.fix_time(df)
            _bdf_io.save(df, out)
            print(f"    -> {out.name}  ({out.stat().st_size / 1e6:.1f} MB)")
            written.append(out)
        return written

    def search(self, query: str, threshold: float = 0.75) -> list[dict]:
        """Search battinfo-records for cell specs matching a free-text query.

        Tolerates typos and incomplete names. Results are ranked by match
        quality (best match first).

        Parameters
        ----------
        query:
            Free-text search string, e.g. ``"duracell mn2400"``.
        threshold:
            Minimum match score in [0, 1]. Lower values return more results
            but with weaker matches. Defaults to 0.75.

        Example::

            ws.search("duracell mn2400")    # exact
            ws.search("duracel mn2400")     # typo tolerated
            ws.search("ANR26650")           # partial model number
        """
        terms = [t.lower() for t in query.split()]
        results = self._search_records(terms, threshold=threshold)
        if results:
            print(f"Found {len(results)} match(es):")
            for r in results:
                print(f"  {r['manufacturer']} {r['model']}  {r['id']}")
        else:
            print(f"No match found for {query!r}.")
            print(f"  Tip: ws.template('cell-spec', manufacturer='...', model='...')")
        return results

    def template(self, record_type: str, **kwargs) -> Path:
        """Write a fillable JSON template for a cell spec or test spec.

        Fill in the generated file, then load it with ``ws.load(path)``.

        Examples::

            ws.template("cell-spec", manufacturer="Duracell", model="MN2400",
                        format="cylindrical", chemistry="Zn-MnO2")

            ws.template("test-spec",
                        name="CC discharge C/5",
                        kind="capacity_check",
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
            "specs": _default_specs_for(format_, chemistry),
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
        kind = kwargs.get("kind", "")
        template = {
            "name":        name,
            "kind":        kind,
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

    def load(self, source: str | Path | dict) -> Any:
        """Load a cell spec or test protocol from a template file, a search result, or an IRI.

        Accepts:
          - a path to a ``.cell-spec.json`` or ``.test-protocol.json`` template
          - a dict returned by :meth:`search`
          - an IRI string (``https://w3id.org/battinfo/spec/...``)
        """
        if isinstance(source, dict):
            return self._load_from_search_result(source)
        source = Path(source) if not isinstance(source, Path) else source
        if not source.is_absolute():
            source = self._root / source
        if not source.exists():
            raise FileNotFoundError(f"Template not found: {source}")
        if ".test-spec" in source.name or ".test-protocol" in source.name:
            return self._load_test_spec(source)
        return self._load_from_file(source)

    def add(self, record_type: str, **kwargs) -> list:
        """Add records to the workspace.

        **Cell instances** (``record_type="cell-instance"``)::

            # From a pre-allocated IRI mapping file:
            ws.add("cell-instance", spec=spec,
                   from_file="cell_iris.json", match="duracell-mn2400")

            # From a list of factory serial numbers (IRIs auto-assigned):
            ws.add("cell-instance", spec=spec,
                   serial_numbers=["FAC-001", "FAC-002", "FAC-003"],
                   production_date="2026-01")

        ``serial_numbers`` accepts any list of factory-assigned IDs.
        IRIs are generated automatically on publication.
        ``from_file`` expects a JSON file mapping batch-key → pre-allocated IRI.
        ``match`` filters the ``from_file`` keys by substring (optional).

        **Tests** (``record_type="test"``)::

            ws.add("test",
                   kind="capacity_check",
                   datasets="data/*.csv",
                   spec=protocol,               # TestSpec from ws.load()
                   instrument="Maccor 4200")

        ``datasets`` is a glob pattern.  Each file is matched to a cell
        instance by the 6-char short ID embedded in the filename, or by the
        full filename stem as a serial number (e.g. ``TRFFC00174.csv``).
        """
        rt = record_type.replace("_", "-").lower()
        if rt == "cell-instance":
            return self._add_cell_instances(**kwargs)
        if rt == "test":
            return self._add_tests(**kwargs)
        raise ValueError(
            f"Unknown record type {record_type!r}. "
            "Supported: 'cell-instance', 'test'."
        )

    def save(self, validation_policy: str = "strict") -> dict:
        """Save all records and rebuild the workspace index.

        Returns a summary dict with counts of written records.
        Only the records saved in this call will be submitted by the next
        ``ws.submit()`` — records left over from previous sessions in the
        same directory are ignored.
        """
        result = self._ws.save(
            mode="upsert",
            resolve_references=False,
            validation_policy=validation_policy,
        )
        # Track the exact files written so submit() only sends this session's work.
        self._session_paths = set()
        for key in ("cell_types", "cell_instances", "tests", "datasets", "test_specs"):
            for item in result.get(key, []):
                p = item.get("path") if isinstance(item, dict) else str(item)
                if p:
                    self._session_paths.add(Path(p))

        ct = len(result.get("cell_types", []))
        ci = len(result.get("cell_instances", []))
        t  = len(result.get("tests", []))
        ds = len(result.get("datasets", []))
        print(
            f"Saved: {ct} cell spec(s), {ci} cell instance(s), "
            f"{t} test(s), {ds} dataset(s)"
        )
        print(f"  Records: {self._records_root}")
        return result

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
            "cell-type":     ("product",       "name",          "id"),
            "cell-instance": ("cell_instance",  "serial_number", "id"),
            "test":          ("test",           "name",          "id"),
            "dataset":       ("dataset",        "name",          "id"),
            "test-protocol": ("test_spec",  "name",          "id"),
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
            marker = lambda i: " *" if i["session"] else ""  # noqa: E731
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
                    cell_type_id=ci.get("type_id"),
                    serial_number=ci.get("serial_number"),
                    batch_id=ci.get("batch_id"),
                )
                serial = ci.get("serial_number") or ""
                if serial:
                    self._cells_by_short_id[serial] = cell
                sid = _short_id(serial)
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

    def import_(
        self,
        source: str,
        sandbox: bool = False,
        token: str | None = None,
    ) -> dict:
        """Import workspace records from a ``battinfo.jsonld`` document.

        Parses the JSON-LD `@graph`, reconstructs cell specs, cell instances,
        tests, and datasets, then populates this workspace ready for
        ``ws.save()`` and ``ws.submit()``.  All canonical IRIs from the source
        document are preserved — no new IRIs are minted.

        Parameters
        ----------
        source:
            One of:

            * A **Zenodo record ID** (string of digits, e.g. ``"14523891"``)
            * A **URL** pointing directly to a ``battinfo.jsonld`` file
            * A **local file path** to a ``battinfo.jsonld`` file

        sandbox:
            When *source* is a Zenodo record ID, use ``sandbox.zenodo.org``
            instead of production.
        token:
            Optional Zenodo API token for private records.

        Returns
        -------
        dict
            Counts of imported entities, e.g.
            ``{"specs": 3, "instances": 8, "tests": 8, "datasets": 8}``.

        Example::

            ws.import_("14523891")          # from Zenodo
            ws.import_("battinfo.jsonld")   # from local file
            ws.save()
            ws.submit()
        """
        import urllib.request

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
                value = (node.get("hasNumericalPart") or {}).get("hasNumericalValue")
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
        spec_objects: dict[str, Any] = {}   # IRI → CellType
        for iri, node in sorted(spec_nodes_by_iri.items()):
            phys = node.get("isDescriptionFor", {})
            phys_types = phys.get("@type", [])
            if isinstance(phys_types, str):
                phys_types = [phys_types]
            descriptors = _extract_descriptors(phys_types)

            mfr_node = node.get("schema:manufacturer", {})
            mfr_name  = mfr_node.get("schema:name", "") if isinstance(mfr_node, dict) else str(mfr_node)
            specs = _specs_from_property_nodes(node.get("hasProperty", []))

            ct = self._ws.cell_type(
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

        for test_iri, tnode in sorted(test_nodes_by_iri.items()):
            cell_iri = (tnode.get("hasTestObject") or tnode.get("prov:used") or {}).get("@id", "")
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
            "specs":     len(spec_objects),
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
    ) -> list[dict]:
        """Submit workspace records to the battinfo registry.

        POSTs saved records directly to the registry API.
        Records are queued as ``pending_review`` and appear on the platform
        after curator approval.  No git or filesystem dependency.

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

        # If a Zenodo DOI is provided (or stored from ws.zenodo()), include it in provenance
        resolved_doi = doi or self._load_zenodo_state().get("doi")
        if resolved_doi:
            doi_note = f"Zenodo DOI: {resolved_doi}"
            note = f"{note}. {doi_note}" if note else doi_note

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

        from battinfo.api import submit_publication_package

        examples = self._records_root / "examples"
        if not examples.exists():
            print("  No records found — run ws.save() first.")
            return []

        # Normalise the `only` filter to a set of canonical directory names
        _ALIASES: dict[str, str] = {
            "cell-spec":      "cell-type",
            "cell_spec":      "cell-type",
            "cell-type":      "cell-type",
            "cell_type":      "cell-type",
            "cell-instance":  "cell-instance",
            "cell_instance":  "cell-instance",
            "test-spec":      "test-protocol",
            "test_spec":      "test-protocol",
            "test-protocol":  "test-protocol",
            "test_spec":  "test-protocol",
            "test":           "test",
            "dataset":        "dataset",
        }
        if only is not None:
            raw_only = [only] if isinstance(only, str) else list(only)
            allowed: set[str] | None = {
                _ALIASES.get(rt.lower().replace("_", "-"), rt.lower())
                for rt in raw_only
            }
        else:
            allowed = None   # None means all types

        def _want(subdir: str) -> bool:
            return allowed is None or subdir in allowed

        results: list[dict] = []

        # ── Cell specs ────────────────────────────────────────────────────────
        for src in (_glob("cell-type") if _want("cell-type") else []):
            raw = json.loads(src.read_text(encoding="utf-8"))
            product = raw.get("product", {})
            mfr = product.get("manufacturer", {})
            mfr_name = mfr.get("name", "") if isinstance(mfr, dict) else str(mfr)
            model = product.get("model", "")
            year  = product.get("year") or datetime.date.today().year
            title = f"{mfr_name} {model}".strip()
            source_local_id = _make_record_slug(mfr_name, model, year)

            if note:
                raw = dict(raw)
                prov = dict(raw.get("provenance") or {})
                prov["comment"] = note
                raw["provenance"] = prov

            payload = _cell_type_submission_payload(
                raw, wid=wid, pid=pid, ver=ver,
                source_local_id=source_local_id, title=title,
            )
            results.extend(_do_submit(payload, url, key, title))

        def _glob(subdir: str) -> list[Path]:
            d = examples / subdir
            if not d.exists():
                return []
            all_files = sorted(d.glob("*.json"))
            if self._session_paths:
                # Only submit what was written by the most recent ws.save()
                return [f for f in all_files if f in self._session_paths]
            # Fallback: no session tracking (e.g. submit called without save in this session)
            return all_files

        # ── Cell instances ────────────────────────────────────────────────────
        cell_type_dir = examples / "cell-type"
        for src in (_glob("cell-instance") if _want("cell-instance") else []):
            raw = json.loads(src.read_text(encoding="utf-8"))
            ci = raw.get("cell_instance", {})
            serial = ci.get("serial_number") or ci.get("short_id", "")
            source_local_id = ci.get("short_id") or serial.lower().replace(" ", "-")
            if note:
                raw = dict(raw)
                prov = dict(raw.get("provenance") or {})
                prov["comment"] = note
                raw["provenance"] = prov
            spec_record = _find_spec_record(cell_type_dir, ci.get("type_id", ""))
            payload = _cell_instance_submission_payload(
                raw, wid=wid, pid=pid, ver=ver,
                source_local_id=source_local_id, title=serial,
                spec_record=spec_record,
            )
            results.extend(_do_submit(payload, url, key, serial))

        # ── Tests ─────────────────────────────────────────────────────────────
        for src in (_glob("test") if _want("test") else []):
            raw = json.loads(src.read_text(encoding="utf-8"))
            test = raw.get("test", {})
            title = test.get("name") or test.get("short_id", "")
            source_local_id = test.get("short_id") or src.stem
            payload = _simple_submission_payload(
                raw, resource_type="test", rdf_type="BatteryTest",
                record_key="test", wid=wid, pid=pid, ver=ver,
                source_local_id=source_local_id, title=title,
                related_cell_id=test.get("cell_id"),
            )
            results.extend(_do_submit(payload, url, key, title))

        # ── Datasets ──────────────────────────────────────────────────────────
        for src in (_glob("dataset") if _want("dataset") else []):
            raw = json.loads(src.read_text(encoding="utf-8"))
            ds = raw.get("dataset", {})
            title = ds.get("name") or ds.get("short_id", "")
            source_local_id = ds.get("short_id") or src.stem
            payload = _simple_submission_payload(
                raw, resource_type="dataset", rdf_type="Dataset",
                record_key="dataset", wid=wid, pid=pid, ver=ver,
                source_local_id=source_local_id, title=title,
            )
            results.extend(_do_submit(payload, url, key, title))

        if results:
            statuses = {(r.get("response") or {}).get("status") for r in results}
            self._search_cache = None
            print(f"\nSubmitted {len(results)} record(s) to {url}")
            if "published" in statuses:
                print("  Published — records are live on the platform.")
            if "pending_review" in statuses:
                print("  Some records are pending_review — approve via ws.approve().")
        return results

    def pending(
        self,
        registry_url: str | None = None,
        workspace_id: str | None = None,
    ) -> list[dict]:
        """List submissions awaiting review for this workspace.

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

        endpoint = f"{url.rstrip('/')}/workspaces/{wid}/submissions?status_filter=pending_review"
        with urllib.request.urlopen(endpoint, timeout=10) as resp:  # noqa: S310
            submissions = json.loads(resp.read().decode())

        if not submissions:
            print("No pending submissions.")
        else:
            print(f"{len(submissions)} pending submission(s):")
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
        import urllib.parse

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

            dist = dists[0]
            local_url = dist.get("content_url") or ds.get("access_url") or ""
            local_file = Path(local_url.replace("file:///", "").replace("file://", ""))
            if not local_file.is_absolute():
                local_file = self._root / local_file

            if not local_file.exists():
                print(f"  WARNING: file not found, skipping: {local_file.name}")
                continue

            # Compute SHA-256 of local file
            sha256 = hashlib.sha256(local_file.read_bytes()).hexdigest()

            # R2 key: datasets/{short_id}/{filename}
            r2_key = f"datasets/{short_id}/{local_file.name}"
            public_url = f"{public_base}/{r2_key}" if public_base else f"s3://{bucket_name}/{r2_key}"

            if dry_run:
                print(f"  [dry-run] would upload {local_file.name} → {r2_key}")
                urls.append(public_url)
                continue

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
                urls.append(public_url)
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
                urls.append(public_url)

            # Update the dataset record with the R2 URL
            dist["content_url"] = public_url
            dist["checksum"] = {"algorithm": "sha256", "value": sha256}
            raw["dataset"]["access_url"] = public_url
            raw["dataset"]["distributions"] = [dist] + dists[1:]
            record_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")

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
        all data files plus a ``battinfo.jsonld`` linked data document, and
        optionally publishes.

        Credentials are read from ``.battinfo/credentials`` or env vars:
        ``ZENODO_API_TOKEN`` (production) / ``ZENODO_SANDBOX_TOKEN`` (sandbox).

        Parameters
        ----------
        record_id:
            ``None`` → new Zenodo record.  A Zenodo record ID → new version.
        publish:
            ``False`` (default) — leave as draft for review on zenodo.org first.
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

        # ── Guard against accidental duplicate records ─────────────────────────
        state = self._load_zenodo_state()
        existing_id = state.get("record_id")
        if existing_id and record_id is None:
            raise RuntimeError(
                f"This workspace already has a Zenodo record ({existing_id}).\n"
                f"Pass record_id={existing_id!r} to add a new version, "
                "or delete .battinfo/zenodo.json to force a new record."
            )

        examples = self._records_root / "examples"
        if not examples.exists():
            raise RuntimeError("No records found — run ws.save() first.")

        client = ZenodoClient(token=tok, sandbox=sandbox)
        domain = "sandbox.zenodo.org" if sandbox else "zenodo.org"

        # ── Create or version the deposit ──────────────────────────────────────
        if record_id is not None:
            deposit = client.create_new_version(record_id)
            client.delete_all_files(deposit["id"])
        else:
            deposit = client.create_empty_deposit()

        deposit_id: int     = deposit["id"]
        zenodo_record_id: int = deposit["record_id"]
        prereserved_doi: str = (
            deposit.get("metadata", {})
            .get("prereserve_doi", {})
            .get("doi", f"10.5281/zenodo.{zenodo_record_id}")
        )

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
            )
            (tmpdir / "battinfo.jsonld").write_text(
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
            print(f"  Uploading {len(upload_map)} file(s) to Zenodo deposit {deposit_id}...")
            for path, name in upload_map.items():
                print(f"    {name}  ({path.stat().st_size / 1e6:.1f} MB)")
            client.upload_files(deposit_id, upload_map)

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
            pub = client.publish_deposit(deposit_id)
            doi = pub.get("doi", prereserved_doi)
            published = True
            print(f"  Published: {record_url}")
            print(f"  DOI: {doi}")
        else:
            print(f"  Draft: {draft_url}")
            print(f"  Pre-reserved DOI: {doi}")
            print(f"  Review, then: ws.zenodo(record_id={zenodo_record_id!r}, publish=True)")

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
            # Write a placeholder battinfo.jsonld so contentSize is available
            placeholder = tmpdir / "battinfo.jsonld"
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

    def preview_jsonld(self, output: str | Path | None = None) -> Path:
        """Generate ``battinfo.jsonld`` locally for review before uploading to Zenodo.

        Uses placeholder values for the Zenodo record URL and DOI so the
        structure can be inspected without creating a deposit.

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
        )

        out = Path(output) if output else self._root / "battinfo.preview.jsonld"
        out.write_text(json.dumps(jsonld, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  Written: {out}")
        print(f"  Graph nodes: {len(jsonld.get('@graph', []))}")
        print(f"  Data files:  {len(data_filenames)}")
        return out

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
                except Exception:
                    continue

        # Deduplicate (a file may appear in multiple distributions)
        seen: set[str] = set()
        unique: list[tuple[Path, str]] = []
        for lp, kind in collected:
            if lp.name not in seen:
                seen.add(lp.name)
                unique.append((lp, kind))

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

    def _build_zenodo_jsonld(
        self,
        *,
        zenodo_record_id: int,
        prereserved_doi: str,
        record_url: str,
        data_filenames: list[str],
    ) -> dict:
        """Build a consolidated JSON-LD using domain-battery terms natively.

        Cell specs use domain-battery OWL classes (``CylindricalBattery`` etc.)
        and EMMO's ``hasProperty`` / ``hasNumericalPart`` / ``hasMeasurementUnit``
        pattern for measurements.  DCAT and schema.org wrap the dataset level for
        broad discoverability.  The document is processable by OWL reasoners and
        any JSON-LD tool that resolves the embedded context.
        """
        from battinfo.jsonld import _PROP_MAP, _UNIT_MAP

        _DATA_DIR = Path(__file__).parent / "data"

        examples = self._records_root / "examples"

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
                "hasNumericalPart": {"hasNumericalValue": value},
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

        # ── Load cell specs ────────────────────────────────────────────────────
        spec_nodes: dict[str, dict] = {}
        ct_dir = examples / "cell-type"
        if ct_dir.exists():
            for f in sorted(ct_dir.glob("*.json")):
                try:
                    raw  = json.loads(f.read_text(encoding="utf-8"))
                    prod = raw.get("product", {})
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
                        # BatteryCellSpecification = a Description, not a physical battery
                        "@type":       ["BatteryCellSpecification", "schema:Product"],
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
                    # Preserve original chemistry and format strings verbatim
                    # so the round-trip through JSON-LD is lossless.
                    if prod.get("chemistry"):
                        node["battinfo:chemistry"] = prod["chemistry"]
                    if prod.get("cell_format"):
                        node["battinfo:cellFormat"] = prod["cell_format"]
                    # rechargeable is already encoded in @type via PrimaryBattery/SecondaryBattery

                    # Measurements using EMMO hasProperty pattern
                    specs = raw.get("specs", {})
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

        # ── Map cell instance IRI → {type_id, serial_number} ──────────────────
        instances: dict[str, dict] = {}
        ci_dir = examples / "cell-instance"
        if ci_dir.exists():
            for f in sorted(ci_dir.glob("*.json")):
                try:
                    raw = json.loads(f.read_text(encoding="utf-8"))
                    ci  = raw.get("cell_instance", {})
                    iri = ci.get("id", "")
                    if iri:
                        instances[iri] = {
                            "serial_number":  ci.get("serial_number", ""),
                            "type_id":        ci.get("type_id", ""),
                            "grade":          ci.get("grade"),
                            "manufactured_at": ci.get("manufactured_at"),
                            "expires_at":      ci.get("expires_at"),
                            "batch_id":        ci.get("batch_id"),
                        }
                except Exception:
                    continue

        # ── Build test instance nodes + dataset→test mapping ──────────────────
        ds_to_test: dict[str, dict] = {}
        test_nodes: list[dict] = []
        test_dir = examples / "test"
        if test_dir.exists():
            for f in sorted(test_dir.glob("*.json")):
                try:
                    raw      = json.loads(f.read_text(encoding="utf-8"))
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
                            "@type":         ["BatteryTest", "prov:Activity"],
                            "@id":           test_iri,
                            "hasTestObject": {"@id": cell_id},   # domain-battery: physical object tested
                        }
                        if protocol:
                            tnode["schema:measurementTechnique"] = protocol
                        if instrument:
                            tnode["hasTestEquipment"] = {
                                "@type":       "schema:Thing",
                                "schema:name": instrument,
                            }
                            tnode["schema:instrument"] = instrument
                        # hasOutput → the dataset IRIs produced by this test
                        outputs = [{"@id": ds_id} for ds_id in (test.get("dataset_ids") or [])]
                        if outputs:
                            tnode["hasOutput"] = outputs
                        # spec conformance ─────────────────────────────────────
                        protocol_id = test.get("protocol_id")
                        conformance = test.get("conformance")
                        _apply_conformance_jsonld(tnode, protocol_id, conformance)
                        test_nodes.append(tnode)
                except Exception:
                    continue

        # ── Build dataset metadata ─────────────────────────────────────────────
        ds_meta: dict[str, dict] = {}
        ds_dir = examples / "dataset"
        if ds_dir.exists():
            for f in sorted(ds_dir.glob("*.json")):
                try:
                    raw   = json.loads(f.read_text(encoding="utf-8"))
                    ds    = raw.get("dataset", {})
                    ds_id = ds.get("id", "")
                    ti    = ds_to_test.get(ds_id, {})
                    for dist in (ds.get("distributions") or []):
                        url   = dist.get("content_url") or ""
                        fname = Path(url.replace("file:///", "").replace("file://", "")).name
                        cs    = dist.get("checksum", {})
                        ds_meta[ds_id] = {
                            "filename":  fname,
                            "format":    dist.get("encoding_format", ""),
                            "checksum":  cs.get("value", ""),
                            "cell_id":   ti.get("cell_id", ""),
                            "test_iri":  ti.get("test_iri", ""),
                            "kind":      ti.get("kind", ""),
                        }
                except Exception:
                    continue

        # ── Build dcat:Distribution nodes ──────────────────────────────────────
        # Provenance chain: Distribution ──wasGeneratedBy──> BatteryTest
        #                   BatteryTest  ──hasTestObject──>  CellInstance
        #                   BatteryTest  ──prov:used──>      TestSpec (plan)
        #                   CellInstance ──hasDescription──> CellSpec
        distributions = []
        for ds_id, meta in sorted(ds_meta.items()):
            fname = meta["filename"]
            if fname in data_filenames:
                dl_url = f"{record_url}/files/{fname}"
            else:
                kind_zip = f"{meta['kind']}.zip"
                dl_url = (f"{record_url}/files/{kind_zip}"
                          if kind_zip in data_filenames else "")

            node: dict = {
                "@type":            "dcat:Distribution",
                "dcat:downloadURL": dl_url,
                "dcat:mediaType":   meta["format"] or "application/x-parquet",
                "schema:name":      fname,
            }

            # wasGeneratedBy → BatteryTest (the Activity), not the cell (Entity)
            if meta.get("test_iri"):
                node["prov:wasGeneratedBy"] = {"@id": meta["test_iri"]}

            if meta["checksum"]:
                node["spdx:checksum"] = {
                    "@type":                  "spdx:Checksum",
                    "spdx:checksumAlgorithm": "spdx:checksumAlgorithm_sha256",
                    "spdx:checksumValue":     meta["checksum"],
                }
            distributions.append(node)

        # ── Build cell instance nodes ──────────────────────────────────────────
        # Each instance is a physical battery whose type is described by its spec.
        instance_nodes: list[dict] = []
        for cell_iri, inst in sorted(instances.items()):
            type_id   = inst.get("type_id", "")
            spec_node = spec_nodes.get(type_id, {})
            # Inherit the physical type from the spec's isDescriptionFor
            phys_type = spec_node.get("isDescriptionFor", {}).get("@type", "BatteryCell")

            inode: dict = {
                "@type": phys_type,
                "@id":   cell_iri,
                "schema:serialNumber": inst.get("serial_number", ""),
                "dcterms:conformsTo":  {"@id": type_id},
                "hasDescription":      {"@id": type_id},
            }
            if inst.get("grade"):
                inode["schema:quality"] = inst["grade"]
            if inst.get("manufactured_at"):
                inode["schema:productionDate"] = inst["manufactured_at"]
            if inst.get("expires_at"):
                inode["schema:expires"] = inst["expires_at"]
            if inst.get("batch_id"):
                inode["schema:identifier"] = inst["batch_id"]
            instance_nodes.append(inode)

        # ── Compose @graph ─────────────────────────────────────────────────────
        dataset_node: dict = {
            "@type":             ["dcat:Dataset", "schema:Dataset"],
            "@id":               record_url,
            "schema:identifier": prereserved_doi,
            "schema:url":        record_url,
            "dcat:distribution": distributions,
            "rdfs:seeAlso":      {"@id": "https://www.battery-genome.org/registry"},
        }
        if spec_nodes:
            dataset_node["schema:about"] = [{"@id": iri} for iri in spec_nodes]

        graph = [dataset_node] + list(spec_nodes.values()) + instance_nodes + test_nodes

        # ── Inline context: load from records.context.json + dynamic prefLabel terms ─
        # _RECORDS_CONTEXT is generated by `python scripts/assemble_context.py`
        # from schema/*.yaml (the LinkML single source of truth).
        # _LABEL_TO_COMPACT adds quantity/unit prefLabels loaded from curated JSON maps.
        context = dict(_RECORDS_CONTEXT)
        context.update(_LABEL_TO_COMPACT)

        return {"@context": context, "@graph": graph}

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
        - Lists ``battinfo.jsonld`` and all data files as ``hasPart``
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
        parts = [{"@id": "battinfo.jsonld"}] + [{"@id": fn} for fn in data_filenames]
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

        # battinfo.jsonld entity
        jsonld_entity: dict = {
            "@type":          ["File", "CreativeWork"],
            "@id":            "battinfo.jsonld",
            "name":           "BattINFO linked data",
            "description":    "Battery domain metadata using EMMO/domain-battery ontology terms.",
            "encodingFormat": "application/ld+json",
            "conformsTo":     {"@id": "https://w3id.org/battinfo/"},
        }
        jsonld_path = tmpdir / "battinfo.jsonld"
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
        ct_dir = self._records_root / "examples" / "cell-type"
        specs: list[dict] = []
        if ct_dir.exists():
            for f in sorted(ct_dir.glob("*.json")):
                try:
                    raw  = json.loads(f.read_text(encoding="utf-8"))
                    prod = raw.get("product", {})
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

        s0 = specs[0] if specs else {}
        n_ds = len(list((self._records_root / "examples" / "dataset").glob("*.json"))
                   if (self._records_root / "examples" / "dataset").exists() else [])

        auto_title = (
            f"{s0.get('manufacturer','')} {s0.get('model','')} — BattINFO Battery Dataset".strip()
            if s0 else "Battery Dataset — BattINFO"
        )
        auto_desc = (
            f"Battery dataset for {s0.get('manufacturer','')} {s0.get('model','')} "
            f"({s0.get('format','')}, {s0.get('chemistry','')}). "
            f"Contains {n_ds} dataset(s). "
            "Published via BattINFO (https://github.com/BIG-MAP/BattINFO)."
            if s0 else "Battery dataset published via BattINFO."
        )

        kw: list[str] = ["BattINFO", "battery", "electrochemistry"]
        for s in specs:
            for v in (s["manufacturer"], s["model"], s["chemistry"], s["format"], s["iec_code"]):
                if v and v not in kw:
                    kw.append(v)
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
        from battinfo.jsonld import record_to_jsonld
        from rdflib import Graph

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
            "cell-type":     "cell-spec",
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
                product = data.get("product", {})
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
        url = f"{self._registry_url}/resources?resource_type=cell_type"
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
        curated = self._records_repo / "records" / "cell-type"
        staging = self._records_repo / "records" / "_staging" / "cell-type"
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
                product = data.get("product", {})
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
        specs = {k: v for k, v in (raw.get("specs") or {}).items() if v and v.get("value") is not None}
        ct = self._ws.cell_type(
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

    def _load_from_search_result(self, result: dict) -> Any:
        """Load a CellType from a search result, reusing the existing spec IRI."""
        if result.get("source") == "api":
            return self._load_from_api(result)

        record = result.get("_record", {})
        product = record.get("product", {})
        specs_raw = record.get("specs", {})
        specs = {k: v for k, v in specs_raw.items() if v and v.get("value") is not None} if specs_raw else None
        ct = self._ws.cell_type(
            manufacturer=product.get("manufacturer", {}).get("name", ""),
            model=product.get("model", ""),
            format=product.get("cell_format", ""),
            chemistry=product.get("chemistry", ""),
            positive_electrode_basis=product.get("positive_electrode_basis"),
            negative_electrode_basis=product.get("negative_electrode_basis"),
            size_code=product.get("size_code"),
            iec_code=product.get("iec_code"),
            country_of_origin=product.get("country_of_origin"),
            year=product.get("year"),
            specs=specs,
            source_type="datasheet",
        )
        if result.get("id"):
            ct.id = result["id"]  # reuse the existing canonical IRI
        return ct

    def _load_from_api(self, result: dict) -> Any:
        """Fetch a full cell-spec record from the registry API and load it."""
        import urllib.request

        if not self._registry_url:
            raise RuntimeError("No registry_url configured — cannot load from API.")

        canonical_id = result.get("_canonical_id", "")
        url = f"{self._registry_url}/resources/cell_type/{canonical_id}"
        with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
            data = json.loads(resp.read().decode())

        payload = data.get("semantic_payload") or {}

        # The canonical record is nested under battinfo_records.cell_type
        # in the publication model; fall back to top-level keys for older records.
        cell_type_record = (
            (payload.get("battinfo_records") or {}).get("cell_type") or payload
        )
        product  = cell_type_record.get("product") or {}
        specs_raw = cell_type_record.get("specs") or {}
        specs = {k: v for k, v in specs_raw.items() if v and v.get("value") is not None} or None

        mfr = product.get("manufacturer") or {}
        mfr_name = mfr.get("name", "") if isinstance(mfr, dict) else str(mfr)

        ct = self._ws.cell_type(
            manufacturer=mfr_name,
            model=product.get("model", ""),
            format=product.get("cell_format", ""),
            chemistry=product.get("chemistry", ""),
            positive_electrode_basis=product.get("positive_electrode_basis"),
            negative_electrode_basis=product.get("negative_electrode_basis"),
            size_code=product.get("size_code"),
            iec_code=product.get("iec_code"),
            country_of_origin=product.get("country_of_origin"),
            year=product.get("year"),
            specs=specs,
            source_type="registry",
        )
        iri = product.get("id") or result.get("id")
        if iri:
            ct.id = iri
        return ct

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
    ) -> list:
        """Create cell instances from a mapping file, parallel lists, or a serial-number list.

        Three input modes (mutually exclusive):

        * ``from_file`` — JSON file mapping ``{name: pre-allocated-IRI}``
        * ``iris`` + ``names`` — parallel lists with pre-allocated IRIs
        * ``serial_numbers`` — list of factory serial numbers; IRIs are
          assigned automatically by the registry on publication
        """
        # Mode 1: from_file (name → pre-allocated IRI)
        mapping: dict[str, str | None] = {}

        if from_file is not None:
            fp = Path(from_file)
            if not fp.is_absolute():
                fp = self._root / fp
            raw = json.loads(fp.read_text(encoding="utf-8"))
            mapping = {k: v for k, v in raw.items() if not k.startswith("_") and v}
            if match:
                mapping = {k: v for k, v in mapping.items() if match.lower() in k.lower()}

        # Mode 2: parallel iris + names lists
        elif iris is not None and names is not None:
            if len(iris) != len(names):
                raise ValueError("iris and names must have the same length")
            mapping = dict(zip(names, iris))

        # Mode 3: serial numbers only — IRIs generated automatically
        elif serial_numbers is not None:
            counts = {sn: serial_numbers.count(sn) for sn in serial_numbers}
            dupes = [sn for sn, n in counts.items() if n > 1]
            if dupes:
                print(f"  WARNING: {len(dupes)} duplicate serial number(s) — skipping: {dupes[:5]}"
                      + (" ..." if len(dupes) > 5 else ""))
            already = [sn for sn in serial_numbers if sn in self._cells_by_short_id]
            if already:
                print(f"  WARNING: {len(already)} serial number(s) already in workspace — skipping: {already[:5]}"
                      + (" ..." if len(already) > 5 else ""))
            skip = set(dupes) | set(already)
            mapping = {sn: None for sn in dict.fromkeys(serial_numbers) if sn not in skip}

        if not mapping:
            print(f"  No cell instances to add (mapping is empty{f', match={match!r}' if match else ''}).")
            return []

        # Inherit spec properties as default measured values on each instance.
        # The researcher can overwrite individual values after creation.
        spec_defaults: dict[str, Any] = {}
        try:
            specs_obj = getattr(spec, "specs", None)
            raw_specs: dict = specs_obj if isinstance(specs_obj, dict) else (
                spec.to_record().get("specs") or {}
            )
            spec_defaults = {
                k: v for k, v in raw_specs.items()
                if isinstance(v, dict) and v.get("value") is not None
            }
        except Exception:
            pass

        cells = []
        for name, iri in mapping.items():
            cell = self._ws.cell(
                spec,
                serial_number=name,
                grade=grade,
                manufactured_at=production_date,
                expires_at=expiration_date,
                measured=spec_defaults if spec_defaults else None,
            )
            if iri is not None:
                cell.id = iri
            sid = _short_id(name)
            if sid:
                self._cells_by_short_id[sid] = cell
            self._cells_by_short_id[name] = cell  # also index by full serial number
            cells.append(cell)
            print(f"  cell-instance: {name}  {iri or '(IRI auto-assigned)'}")
        return cells

    def _load_test_spec(self, path: Path) -> Any:
        raw = json.loads(path.read_text(encoding="utf-8"))
        tp = self._ws.test_protocol(
            name=raw.get("name", ""),
            kind=raw.get("kind", ""),
            description=raw.get("description"),
        )
        return tp

    def _add_tests(
        self,
        kind: str,
        datasets: str | list[str | Path],
        spec: Any = None,
        protocol: Any = None,  # backward-compat alias for spec
        instrument: str | None = None,
        license: str | None = None,
        description: str | None = None,
        status: str = "completed",
    ) -> list:
        """Create test + dataset records, matching each file to a cell instance
        by the shared 6-char short ID in the filename."""
        if isinstance(datasets, str):
            matched_files = sorted(self._root.glob(datasets))
        else:
            matched_files = [Path(p) if not isinstance(p, Path) else p for p in datasets]
            matched_files = [p if p.is_absolute() else self._root / p for p in matched_files]

        if not matched_files:
            print(f"  No dataset files matched: {datasets!r}")
            return []

        unmatched: list[str] = []
        tests = []
        for f in matched_files:
            # Match by 6-char short ID embedded in the filename, OR by the full stem
            # as a serial number (e.g. files named "TRFFC00174.csv").
            sid = _short_id(f.stem)
            cell = (self._cells_by_short_id.get(sid) if sid else None) \
                or self._cells_by_short_id.get(f.stem)
            if cell is None:
                unmatched.append(f.name)
                continue
            # Accept a test spec object or a plain string; prefer `spec`, fall back to `protocol`
            test_spec = spec if spec is not None else protocol
            protocol_name = protocol_url = None
            if test_spec is not None:
                if isinstance(test_spec, str):
                    protocol_name = test_spec
                else:
                    protocol_name = getattr(test_spec, "name", None)
                    protocol_url  = getattr(test_spec, "id", None)
                    # Use test_type (Pydantic field) — .kind is a ClassVar on BundleJsonModel
                    spec_kind = getattr(test_spec, "test_type", None)
                    if spec_kind is not None and not kind:
                        kind = spec_kind.value if hasattr(spec_kind, "value") else str(spec_kind)
            protocol_name = protocol_name or kind.replace("_", " ")

            test = self._ws.record_test(
                cell,
                kind=kind,
                path=f,
                protocol=protocol_name,
                protocol_url=protocol_url,
                description=description,
                instrument=instrument,
                status=status,
                license=license,
                format=_guess_format(f),
            )
            print(f"  test: {cell.serial_number}  <->  {f.name}")
            tests.append(test)

        if unmatched:
            print(f"  WARNING: {len(unmatched)} dataset(s) had no matching cell instance:")
            for name in unmatched:
                print(f"    {name}  (short ID not found in added cell instances)")
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


def _cell_type_submission_payload(
    record: dict,
    *,
    wid: str,
    pid: str,
    ver: str,
    source_local_id: str,
    title: str,
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
        "publication_intent": {"mode": "canonical-publication"},
        "provenance": {
            "source_system": "battinfo-authoring",
            "workflow_name": "authoring-workspace-submission",
            "generated_at": _now_iso(),
        },
        "release": {"version": ver},
        "workspace": None,
        "resource": {
            "resource_type": "cell_type",
            "source_local_id": source_local_id,
            "title": title,
            "semantic_payload": {
                "@type": "CellType",
                "battinfo_records": {"cell_type": record},
            },
            "related_resources": [],
            "distributions": [],
        },
        "artifacts": [],
        "validation": {"ok": True, "errors": [], "policy": "default"},
    }


def _find_spec_record(cell_type_dir: Path, type_id: str) -> dict | None:
    """Return the cell-type record dict whose product.id matches type_id."""
    if not cell_type_dir.exists():
        return None
    for f in cell_type_dir.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("product", {}).get("id") == type_id:
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
) -> dict:
    ci = record.get("cell_instance", {})
    related: list[dict] = []
    type_id = ci.get("type_id")
    if type_id:
        related.append({
            "relationship": "instanceOf",
            "resource_type": "cell_type",
            "canonical_iri": type_id,
        })

    return {
        "schema_version": "0.1.0",
        "kind": "BattinfoSubmission",
        "submission_mode": "resource",
        "generated_at": _now_iso(),
        "workspace_id": wid,
        "publisher_id": pid,
        "source_version": ver,
        "title": title,
        "publication_intent": {"mode": "canonical-publication"},
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
            "semantic_payload": {
                "@type": "CellInstance",
                "battinfo_records": {
                    "cell": record,
                    **({"cell_type": spec_record} if spec_record else {}),
                },
            },
            "related_resources": related,
            "distributions": [],
        },
        "artifacts": [],
        "validation": {"ok": True, "errors": [], "policy": "default"},
    }


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
) -> dict:
    related: list[dict] = []
    if related_cell_id:
        related.append({
            "relationship": "about",
            "resource_type": "cell",
            "canonical_iri": related_cell_id,
        })
    return {
        "schema_version": "0.1.0",
        "kind": "BattinfoSubmission",
        "submission_mode": "resource",
        "generated_at": _now_iso(),
        "workspace_id": wid,
        "publisher_id": pid,
        "source_version": ver,
        "title": title,
        "publication_intent": {"mode": "canonical-publication"},
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
            "semantic_payload": {
                "@type": rdf_type,
                "battinfo_records": {record_key: record},
            },
            "related_resources": related,
            "distributions": [],
        },
        "artifacts": [],
        "validation": {"ok": True, "errors": [], "policy": "default"},
    }


def _do_submit(payload: dict, url: str, key: str, title: str) -> list[dict]:
    """Submit one record, retrying once with a bumped source_version on 409."""
    from battinfo.api import submit_publication_package
    import copy

    for attempt in range(2):
        try:
            result = submit_publication_package(payload, registry_base_url=url, api_key=key)
            resources = (result.get("response") or {}).get("resources") or []
            iri    = resources[0].get("canonical_iri", "") if resources else ""
            status = (result.get("response") or {}).get("status", "unknown")
            print(f"  {title}  [{status}]  {iri}")
            return [result]
        except RuntimeError as exc:
            if attempt == 0 and "409" in str(exc):
                # Payload changed since last submission — bump source_version and retry
                payload = copy.deepcopy(payload)
                ver = payload.get("source_version", "")
                payload["source_version"] = _bump_version(ver)
                if "resource" in payload:
                    payload["resource"]["source_version"] = payload["source_version"]  # type: ignore[index]
                continue
            print(f"  ERROR: {title} — {exc}")
            return []
    return []


def _bump_version(ver: str) -> str:
    """Increment a trailing counter on a version string: '2026-05-29' → '2026-05-29-v2'."""
    import re
    m = re.search(r"-v(\d+)$", ver)
    if m:
        return ver[: m.start()] + f"-v{int(m.group(1)) + 1}"
    return ver + "-v2"


import dataclasses
from dataclasses import dataclass


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

        # Find battinfo.jsonld in the file list (single source of truth)
        entry = next(
            (f for f in (files.get("entries") or []) if f.get("key") == "battinfo.jsonld"),
            None,
        )
        if entry is None:
            raise RuntimeError(
                f"No battinfo.jsonld found in Zenodo record {source}. "
                "Is this a battinfo-published record? "
                "(battinfo.jsonld is the standard entry point for battinfo Zenodo deposits.)"
            )
        download_url = entry.get("links", {}).get("content") or entry.get("url", "")
        return _import_resolve_source(download_url, token=token)

    raise ValueError(
        f"Cannot resolve import source {source!r}. "
        "Pass a Zenodo record ID, a URL, or a local file path."
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
