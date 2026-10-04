"""Read published records and their data files from a BattINFO registry.

The workspace (:func:`battinfo.workspace`) is for describing and publishing.
This module is the other direction: finding what a registry holds and loading
it for analysis.

    from battinfo.registry import Registry

    reg = Registry()                       # the default public registry
    catalog = reg.catalog()                # one row per dataset, as a DataFrame
    row = catalog[catalog.test_kind == "cycling"].iloc[0]
    df = reg.read(row.dataset_id)          # time series with BDF column names

A registry is an index. It stores records and links, never the measurement
bytes; those sit wherever the publisher put them and each dataset record
carries the URL, size and checksum. ``download`` and ``read`` follow that link,
verify the checksum and keep a local copy so a file is fetched once.

``list``, ``get`` and ``files`` need nothing beyond the core install.
``read`` and ``catalog`` return pandas objects and need ``battinfo[tabular]``.

Provisional in 0.8: the method names are expected to stay, the catalog columns
may grow.
"""
from __future__ import annotations

import builtins
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from battinfo import __version__

__all__ = ["Registry", "RegistryFile", "bdf_column_names"]

DEFAULT_REGISTRY_URL = "https://battinfo-registry.onrender.com"

_PAGE_LIMIT = 1000  # the registry's maximum limit= for /resources
_IRI_RE = re.compile(r"^https?://[^\s]+/(?P<segment>[a-z][a-z_-]*)/(?P<uid>[0-9a-z]{4}(?:-[0-9a-z]{4}){3})/?$")
_UID_RE = re.compile(r"^[0-9a-z]{4}(?:-[0-9a-z]{4}){3}$")
_TABULAR_SUFFIXES = (".parquet", ".csv")

# Capacity keys in order of preference when a single "nominal" figure is wanted.
_CAPACITY_KEYS = ("nominal_capacity", "rated_capacity", "typical_capacity", "minimum_capacity")
_CAPACITY_TO_AH = {"ah": 1.0, "mah": 1e-3, "a.h": 1.0, "ma.h": 1e-3}


@dataclass(frozen=True)
class RegistryFile:
    """One downloadable file attached to a dataset record."""

    name: str
    url: str
    role: str | None = None
    media_type: str | None = None
    sha256: str | None = None
    size: int | None = None


# ── Column names ──────────────────────────────────────────────────────────────

# Human-readable BDF labels and their machine-readable names: the BDF
# vocabulary at ontology version 1.3.0, held here so that read() gives the same
# column names whether or not the batterydf package is installed.
_LABEL_TO_MACHINE: dict[str, str] = {
    "AC Internal Resistance / ohm": "ac_internal_resistance_ohm",
    "Absolute Impedance / ohm": "absolute_impedance_ohm",
    "Ambient Pressure / Pa": "ambient_pressure_pa",
    "Ambient Temperature / degC": "ambient_temperature_celsius",
    "Applied Pressure / Pa": "applied_pressure_pa",
    "Charging Capacity / Ah": "charging_capacity_ah",
    "Charging Energy / Wh": "charging_energy_wh",
    "Cumulative Capacity / Ah": "cumulative_capacity_ah",
    "Cumulative Energy / Wh": "cumulative_energy_wh",
    "Current / A": "current_ampere",
    "Cycle Charging Capacity / Ah": "cycle_charging_capacity_ah",
    "Cycle Charging Energy / Wh": "cycle_charging_energy_wh",
    "Cycle Count / 1": "cycle_count",
    "Cycle Cumulative Capacity / Ah": "cycle_cumulative_capacity_ah",
    "Cycle Cumulative Energy / Wh": "cycle_cumulative_energy_wh",
    "Cycle Discharging Capacity / Ah": "cycle_discharging_capacity_ah",
    "Cycle Discharging Energy / Wh": "cycle_discharging_energy_wh",
    "Cycle Net Capacity / Ah": "cycle_net_capacity_ah",
    "Cycle Net Energy / Wh": "cycle_net_energy_wh",
    "DC Internal Resistance / ohm": "dc_internal_resistance_ohm",
    "Discharging Capacity / Ah": "discharging_capacity_ah",
    "Discharging Energy / Wh": "discharging_energy_wh",
    "Frequency / Hz": "frequency_hertz",
    "Imaginary Impedance / ohm": "imaginary_impedance_ohm",
    "Internal Resistance / ohm": "internal_resistance_ohm",
    "Net Capacity / Ah": "net_capacity_ah",
    "Net Energy / Wh": "net_energy_wh",
    "Phase / deg": "phase_degree",
    "Power / W": "power_watt",
    "Real Impedance / ohm": "real_impedance_ohm",
    "Record Index / 1": "record_index",
    "Schedule Charging Capacity / Ah": "schedule_charging_capacity_ah",
    "Schedule Charging Energy / Wh": "schedule_charging_energy_wh",
    "Schedule Discharging Capacity / Ah": "schedule_discharging_capacity_ah",
    "Schedule Discharging Energy / Wh": "schedule_discharging_energy_wh",
    "Step Charging Capacity / Ah": "step_charging_capacity_ah",
    "Step Charging Energy / Wh": "step_charging_energy_wh",
    "Step Count / 1": "step_count",
    "Step Cumulative Capacity / Ah": "step_cumulative_capacity_ah",
    "Step Cumulative Energy / Wh": "step_cumulative_energy_wh",
    "Step Discharging Capacity / Ah": "step_discharging_capacity_ah",
    "Step Discharging Energy / Wh": "step_discharging_energy_wh",
    "Step ID": "step_id",
    "Step Net Capacity / Ah": "step_net_capacity_ah",
    "Step Net Energy / Wh": "step_net_energy_wh",
    "Step Record Index / 1": "step_record_index",
    "Step Time / s": "step_time_second",
    "Step Type": "step_type",
    "Surface Pressure / Pa": "surface_pressure_pa",
    "Surface Temperature / degC": "surface_temperature_celsius",
    "Temperature T1 / degC": "temperature_t1_celsius",
    "Temperature T2 / degC": "temperature_t2_celsius",
    "Temperature T3 / degC": "temperature_t3_celsius",
    "Temperature T4 / degC": "temperature_t4_celsius",
    "Temperature T5 / degC": "temperature_t5_celsius",
    "Test Time / s": "test_time_second",
    "Unix Time / s": "unix_time_second",
    "Voltage / V": "voltage_volt",
    # Labels from earlier BDF versions that published files still carry. They
    # keep the machine name they were published under: "Step Index / 1" was
    # written for the cycler's program step, which a later BDF version calls
    # step_id, and renaming it here would guess at what a publisher meant.
    "Step Index / 1": "step_index",
    "Step Capacity / Ah": "step_capacity_ah",
    "Step Energy / Wh": "step_energy_wh",
}

# Published files that state a quantity in a unit BDF does not use for it:
# source name -> (BDF name, factor to multiply by).
_UNIT_VARIANTS: dict[str, tuple[str, float]] = {
    "test_time_millisecond": ("test_time_second", 1e-3),
    "date_time_millisecond": ("unix_time_second", 1e-3),
    "unix_time_millisecond": ("unix_time_second", 1e-3),
    "step_time_millisecond": ("step_time_second", 1e-3),
    "current_milliampere": ("current_ampere", 1e-3),
    "voltage_millivolt": ("voltage_volt", 1e-3),
    "cycle_dimensionless": ("cycle_count", 1.0),
}


def bdf_column_names(df: Any) -> Any:
    """Return *df* with its columns renamed to machine-readable BDF names.

    Files in a registry come from many publishers and do not all spell their
    columns the same way. Two spellings are brought to one here:

    - human-readable labels (``Voltage / V``) become ``voltage_volt``;
    - a few unit variants (``test_time_millisecond``) are converted and
      renamed (``test_time_second``).

    Columns that are already machine names, and columns this function does not
    recognise, are returned unchanged. Nothing is dropped and no column is
    invented: a file with no step column still has none afterwards.
    """
    renames: dict[str, str] = {}
    scaled: dict[str, tuple[str, float]] = {}
    taken = set(df.columns)
    for column in df.columns:
        if not isinstance(column, str):
            continue
        if column in _UNIT_VARIANTS:
            target, factor = _UNIT_VARIANTS[column]
            if target not in taken:
                scaled[column] = (target, factor)
                taken.add(target)
            continue
        if column in _LABEL_TO_MACHINE:
            machine = _LABEL_TO_MACHINE[column]
            if machine not in taken:
                renames[column] = machine
                taken.add(machine)
    if not renames and not scaled:
        return df
    out = df.rename(columns=renames)
    for column, (target, factor) in scaled.items():
        if factor != 1.0:
            out[column] = out[column] * factor
        out = out.rename(columns={column: target})
    return out


# ── Record helpers ────────────────────────────────────────────────────────────

def _record_ref(record: Any) -> tuple[str | None, str]:
    """Split a record reference into ``(type_segment, uid)``.

    Accepts a canonical IRI, a ``type/uid`` pair written as one string, a bare
    uid, or any dict the registry returned (list item or full record).
    """
    if isinstance(record, dict):
        iri = record.get("canonical_iri")
        if iri:
            return _record_ref(iri)
        uid = record.get("canonical_id") or record.get("id")
        if uid:
            return record.get("resource_type"), str(uid)
        raise ValueError("record has neither canonical_iri nor canonical_id")
    text = str(record).strip()
    match = _IRI_RE.match(text)
    if match:
        return match["segment"], match["uid"]
    if "/" in text:
        segment, _, uid = text.rstrip("/").rpartition("/")
        if _UID_RE.match(uid):
            return segment.rpartition("/")[2] or None, uid
    if _UID_RE.match(text):
        return None, text
    raise ValueError(f"not a record IRI or id: {record!r}")


def _quantity_ah(properties: Any) -> tuple[float | None, str | None]:
    """First stated capacity in *properties*, in Ah, with the key it came from."""
    if not isinstance(properties, dict):
        return None, None
    for key in _CAPACITY_KEYS:
        entry = properties.get(key)
        if not isinstance(entry, dict):
            continue
        value, unit = entry.get("value"), str(entry.get("unit") or "").strip().lower()
        if isinstance(value, (int, float)) and unit in _CAPACITY_TO_AH:
            return float(value) * _CAPACITY_TO_AH[unit], key
    return None, None


def _files_of(record: dict) -> list[RegistryFile]:
    """Every file a full dataset record points at, merged across its two listings."""
    details: dict[str, dict] = {}
    payload = record.get("semantic_payload") or {}
    body = ((payload.get("battinfo_records") or {}).get("dataset") or {}).get("dataset") or {}
    for dist in body.get("distributions") or []:
        url = dist.get("content_url")
        if url:
            details[url] = dist
    files: list[RegistryFile] = []
    seen: set[str] = set()

    def add(url: str, name: str | None, role: str | None, media_type: str | None) -> None:
        if not url or url in seen:
            return
        seen.add(url)
        extra = details.get(url, {})
        checksum = extra.get("checksum") or {}
        sha256 = checksum.get("value") if str(checksum.get("algorithm", "")).lower() == "sha256" else None
        raw_size = extra.get("content_size") or extra.get("byte_size")
        try:
            size = int(raw_size) if raw_size is not None else None
        except (TypeError, ValueError):
            size = None
        files.append(RegistryFile(
            name=name or extra.get("name") or url.rsplit("/", 1)[-1],
            url=url,
            role=role or extra.get("role"),
            media_type=media_type or extra.get("encoding_format"),
            sha256=sha256,
            size=size,
        ))

    for dist in record.get("distributions") or []:
        add(dist.get("access_url"), dist.get("title"), dist.get("role"), dist.get("media_type"))
    for url, dist in details.items():
        add(url, dist.get("name"), dist.get("role"), dist.get("encoding_format"))
    return files


def _cache_file(folder: Path, name: str) -> Path:
    """Where to keep a download named *name*, staying inside OS path limits.

    Published file names can run past a hundred characters, and Windows
    refuses paths longer than about 260. A name that would push the full path
    over that is replaced by a short digest of itself, keeping the extension.
    """
    name = Path(name).name or "data"
    target = folder / name
    if len(str(target)) + len(".part") <= 240:
        return target
    suffix = "".join(Path(name).suffixes[-2:])[-20:]
    return folder / (hashlib.sha256(name.encode("utf-8")).hexdigest()[:16] + suffix)


def _default_cache_dir() -> Path:
    override = os.environ.get("BATTINFO_CACHE_DIR")
    if override:
        return Path(override)
    base = os.environ.get("XDG_CACHE_HOME") or os.environ.get("LOCALAPPDATA")
    return (Path(base) if base else Path.home() / ".cache") / "battinfo"


# ── The client ────────────────────────────────────────────────────────────────

class Registry:
    """Read-only client for one BattINFO registry.

    Parameters
    ----------
    url:
        Base URL of the registry. Defaults to ``$BATTINFO_REGISTRY_URL`` and
        then to the public registry.
    cache_dir:
        Where downloaded files and the catalog are kept. Defaults to
        ``$BATTINFO_CACHE_DIR`` and then to the user cache directory.
    timeout:
        Seconds to wait on each request. The public registry can take half a
        minute to answer the first request after it has been idle.
    """

    def __init__(
        self,
        url: str | None = None,
        *,
        cache_dir: str | Path | None = None,
        timeout: float = 90,
    ) -> None:
        self.url = (url or os.environ.get("BATTINFO_REGISTRY_URL") or DEFAULT_REGISTRY_URL).rstrip("/")
        self.cache_dir = Path(cache_dir) if cache_dir else _default_cache_dir()
        self.timeout = timeout
        self._user_agent = f"battinfo/{__version__} (registry reader)"

    def __repr__(self) -> str:
        return f"Registry({self.url!r})"

    # -- HTTP ---------------------------------------------------------------

    def _open(self, url: str, *, retries: int = 2):
        request = urllib.request.Request(url, headers={"User-Agent": self._user_agent})
        for attempt in range(retries + 1):
            try:
                return urllib.request.urlopen(request, timeout=self.timeout)  # noqa: S310
            except urllib.error.HTTPError as exc:
                if exc.code < 500 or attempt == retries:
                    raise
            except (urllib.error.URLError, TimeoutError):
                if attempt == retries:
                    raise
            time.sleep(1.5 * (attempt + 1))
        raise RuntimeError("unreachable")  # pragma: no cover

    def _get_json(self, path: str, params: dict | None = None) -> Any:
        url = f"{self.url}{path}"
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        with self._open(url) as response:
            return json.loads(response.read().decode("utf-8"))

    # -- Records ------------------------------------------------------------

    def list(
        self,
        record_type: str,
        *,
        kind: str | None = None,
        q: str | None = None,
        cell_spec: str | None = None,
        status: str | None = None,
    ) -> builtins.list[dict]:
        """Every published record of one type, as summaries.

        *record_type* is ``"dataset"``, ``"test"``, ``"cell"``, ``"cell_spec"``,
        ``"test_spec"`` and so on (hyphenated spellings work too). *kind*
        filters on the record's kind, for example ``kind="cycling"`` for tests.
        *q* matches text in the title. *cell_spec* (an IRI or id) restricts
        cells to instances of one spec.

        A summary carries the IRI, title, publisher, status and a ``metadata``
        dict. Use :meth:`get` for the full record with its links and files.
        """
        params: dict[str, Any] = {"resource_type": record_type, "kind": kind, "q": q, "status": status}
        if cell_spec is not None:
            params["cell_spec_id"] = _record_ref(cell_spec)[1]
        rows: builtins.list[dict] = []
        previous: builtins.list | None = None
        offset = 0
        while True:
            page = self._get_json("/resources", dict(params, limit=_PAGE_LIMIT, offset=offset))
            if not isinstance(page, list) or (offset and page == previous):
                return rows
            rows.extend(page)
            if len(page) < _PAGE_LIMIT:
                return rows
            previous = page
            offset += _PAGE_LIMIT

    def get(self, record: Any, *, record_type: str | None = None) -> dict:
        """The full record for an IRI, an id, or a summary from :meth:`list`.

        The result adds ``related_resources`` (links to the cell, test or spec)
        and ``distributions`` (files) to what the summary holds. A bare id
        needs *record_type*; an IRI or a summary already says what it is.
        """
        segment, uid = _record_ref(record)
        segment = record_type or segment
        if not segment:
            raise ValueError(f"record_type is required to look up a bare id: {record!r}")
        return self._get_json(f"/resources/{segment}/{uid}")

    def links(self, record: Any) -> dict[str, builtins.list[str]]:
        """IRIs a record points at, grouped by the type of the target."""
        full = record if isinstance(record, dict) and "related_resources" in record else self.get(record)
        grouped: dict[str, builtins.list[str]] = {}
        for link in full.get("related_resources") or []:
            iri, target = link.get("canonical_iri"), link.get("resource_type")
            if iri and target:
                grouped.setdefault(target, []).append(iri)
        return grouped

    # -- Files --------------------------------------------------------------

    def files(self, dataset: Any, *, role: str | None = None) -> builtins.list[RegistryFile]:
        """The files attached to a dataset, optionally only those with one *role*.

        The measurement data has role ``"processed"``; ``"raw"`` is the
        original instrument file where the publisher included it.
        """
        full = dataset if isinstance(dataset, dict) and "distributions" in dataset else self.get(dataset, record_type="dataset")
        found = _files_of(full)
        return [f for f in found if f.role == role] if role else found

    def download(
        self,
        dataset: Any,
        *,
        role: str = "processed",
        dest: str | Path | None = None,
        verify: bool = True,
    ) -> Path:
        """Fetch a dataset's data file and return the local path.

        The file is kept under the cache directory (or *dest*) and reused on
        the next call. When the record states a SHA-256 the download is checked
        against it, and a cached copy that no longer matches is fetched again.
        """
        candidates = self.files(dataset, role=role)
        tabular = [f for f in candidates if f.url.lower().split("?")[0].endswith(_TABULAR_SUFFIXES)]
        if not (tabular or candidates):
            raise FileNotFoundError(f"dataset {_record_ref(dataset)[1]} has no file with role {role!r}")
        chosen = (tabular or candidates)[0]
        uid = _record_ref(dataset)[1]
        folder = Path(dest) if dest else self.cache_dir / "files" / uid
        target = _cache_file(folder, chosen.name)
        if target.exists() and (not verify or not chosen.sha256 or _sha256(target) == chosen.sha256):
            return target
        folder.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".part")
        digest = hashlib.sha256()
        with self._open(chosen.url) as response, open(partial, "wb") as handle:
            while chunk := response.read(1 << 20):
                digest.update(chunk)
                handle.write(chunk)
        if verify and chosen.sha256 and digest.hexdigest() != chosen.sha256:
            partial.unlink(missing_ok=True)
            raise OSError(
                f"checksum mismatch for {chosen.url}: the record states {chosen.sha256}, "
                f"the download has {digest.hexdigest()}"
            )
        partial.replace(target)
        return target

    def read(self, dataset: Any, *, bdf_names: bool = True, role: str = "processed"):
        """Load a dataset's measurement data as a pandas DataFrame.

        With *bdf_names* (the default) the columns are renamed to
        machine-readable BDF names, see :func:`bdf_column_names`, so files from
        different publishers can be handled by the same code. Pass
        ``bdf_names=False`` for the file exactly as published.
        """
        from battinfo._util import require_extra  # noqa: PLC0415

        pd = require_extra("pandas", "tabular", "Registry.read() loads data files into DataFrames")
        path = self.download(dataset, role=role)
        suffix = path.suffix.lower()
        if suffix == ".parquet":
            df = pd.read_parquet(path)
        elif suffix == ".csv":
            df = pd.read_csv(path)
        else:
            raise ValueError(f"cannot load {path.name}: only .parquet and .csv data files are supported")
        return bdf_column_names(df) if bdf_names else df

    # -- Catalog ------------------------------------------------------------

    def catalog(self, *, refresh: bool = False, workers: int = 6):
        """One row per dataset, joined with its test, cell and cell spec.

        This is the table to filter before downloading anything. Columns:

        - ``dataset_id``, ``title``, ``license``, ``doi``
        - ``file_url``, ``file_name``, ``media_type``, ``sha256``, ``size_bytes``
        - ``test_id``, ``test_kind``
        - ``cell_id``, ``cell_name``, ``cell_spec_id``
        - ``manufacturer``, ``model``, ``format``, ``chemistry``,
          ``positive_electrode_basis``, ``negative_electrode_basis``
        - ``nominal_capacity_ah`` and ``nominal_capacity_source`` (which stated
          capacity it is: nominal, rated, typical or minimum; empty when the
          cell and its spec state none)

        Building it reads every dataset record once, which takes a few minutes
        on a large registry. The result is cached and reused until the registry
        reports a change; pass ``refresh=True`` to rebuild regardless.
        """
        from battinfo._util import require_extra  # noqa: PLC0415

        pd = require_extra("pandas", "tabular", "Registry.catalog() returns a DataFrame")
        stamp = self._corpus_stamp()
        cache = self.cache_dir / "catalog" / (hashlib.sha256(self.url.encode()).hexdigest()[:12] + ".json")
        if not refresh and cache.exists():
            try:
                saved = json.loads(cache.read_text(encoding="utf-8"))
                if saved.get("stamp") == stamp:
                    return pd.DataFrame(saved["rows"], columns=_CATALOG_COLUMNS)
            except (OSError, ValueError, KeyError):
                pass
        rows = self._build_catalog(workers)
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({"stamp": stamp, "rows": rows}), encoding="utf-8")
        except OSError:
            pass  # a read-only cache directory must not fail the call
        return pd.DataFrame(rows, columns=_CATALOG_COLUMNS)

    def _corpus_stamp(self) -> str:
        """A value that changes when the registry's published corpus does."""
        revision: Any = None
        try:
            revision = (self._get_json("/health") or {}).get("corpus_revision")
        except Exception:  # noqa: BLE001 - /health is advisory here
            pass
        count: Any = None
        try:
            url = f"{self.url}/resources?" + urllib.parse.urlencode({"resource_type": "dataset", "limit": 1})
            with self._open(url) as response:
                count = response.headers.get("X-Total-Count")
        except Exception:  # noqa: BLE001
            pass
        return f"{revision}:{count}"

    def _build_catalog(self, workers: int) -> builtins.list[dict]:
        datasets = self.list("dataset")
        tests = {t["canonical_iri"]: t for t in self.list("test")}
        cells = {c["canonical_iri"]: c for c in self.list("cell")}
        specs = {s["canonical_iri"]: s for s in self.list("cell_spec")}

        def full(summary: dict) -> dict | None:
            try:
                return self.get(summary, record_type="dataset")
            except Exception:  # noqa: BLE001 - one unreadable record must not sink the table
                return None

        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            details = builtins.list(pool.map(full, datasets))

        rows: builtins.list[dict] = []
        for summary, detail in zip(datasets, details):
            meta = summary.get("metadata") or {}
            row: dict[str, Any] = dict.fromkeys(_CATALOG_COLUMNS)
            row.update(
                dataset_id=summary.get("canonical_iri"),
                title=summary.get("title"),
                license=meta.get("license"),
                doi=meta.get("doi"),
                file_url=meta.get("record_url"),
                media_type=meta.get("media_type"),
            )
            if detail:
                links = self.links(detail)
                processed = [f for f in _files_of(detail) if f.role == "processed"]
                if processed:
                    first = processed[0]
                    row.update(file_url=first.url, file_name=first.name, sha256=first.sha256,
                               size_bytes=first.size, media_type=first.media_type or row["media_type"])
                test_id = next(iter(links.get("test", [])), None)
                cell_id = next(iter(links.get("cell", [])), None)
                row.update(test_id=test_id, cell_id=cell_id)
                test = tests.get(test_id or "")
                if test:
                    row["test_kind"] = (test.get("metadata") or {}).get("kind")
                cell = cells.get(cell_id or "")
                if cell:
                    cmeta = cell.get("metadata") or {}
                    spec_id = cmeta.get("cell_spec_id")
                    row.update(
                        cell_name=cmeta.get("name") or cell.get("title"),
                        cell_spec_id=spec_id,
                        manufacturer=cmeta.get("manufacturer"),
                        model=cmeta.get("model"),
                        format=cmeta.get("format"),
                        chemistry=cmeta.get("chemistry"),
                        positive_electrode_basis=cmeta.get("positive_electrode_basis"),
                        negative_electrode_basis=cmeta.get("negative_electrode_basis"),
                    )
                    capacity, source = _quantity_ah(cmeta.get("properties"))
                    if capacity is None:
                        spec = specs.get(spec_id or "") or {}
                        capacity, source = _quantity_ah((spec.get("benchmark") or {}).get("properties"))
                    row.update(nominal_capacity_ah=capacity, nominal_capacity_source=source)
            rows.append(row)
        return rows


_CATALOG_COLUMNS = [
    "dataset_id", "title", "license", "doi",
    "file_url", "file_name", "media_type", "sha256", "size_bytes",
    "test_id", "test_kind",
    "cell_id", "cell_name", "cell_spec_id",
    "manufacturer", "model", "format", "chemistry",
    "positive_electrode_basis", "negative_electrode_basis",
    "nominal_capacity_ah", "nominal_capacity_source",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()
