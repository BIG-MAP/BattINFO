"""
Zenodo REST API client and upload utilities for BattINFO datasets.

Supports both production (zenodo.org) and sandbox (sandbox.zenodo.org).

References:
    https://developers.zenodo.org/
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from battinfo.bundle import ZENODO_CELL_RECORD_FILENAME, ZenodoCellRecord

PathLike = str | Path

_DEFAULT_PUBLISH_FILENAME = "battinfo.publish.jsonld"
_DEFAULT_RO_CRATE_FILENAME = "ro-crate-metadata.json"


def _file_md5(path: Path) -> str:
    """MD5 hex digest of a file (Zenodo identifies file content by MD5)."""
    import hashlib
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _zenodo_checksum_matches(path: Path, checksum: str | None) -> bool:
    """True only if *path*'s content matches Zenodo's recorded MD5 checksum.

    Zenodo reports file checksums as MD5 (sometimes prefixed ``"md5:"``). Any
    missing/non-MD5/mismatching value returns False, so the caller safely re-uploads
    (correctness over optimisation)."""
    if not checksum:
        return False
    algo, _, digest = checksum.partition(":") if ":" in checksum else ("md5", "", checksum)
    if algo.lower() not in ("md5", ""):
        return False
    return _file_md5(path) == digest.strip().lower()


class ZenodoError(RuntimeError):
    """Raised when the Zenodo API returns an error response."""


class ZenodoClient:
    def __init__(self, *, token: str, sandbox: bool = False) -> None:
        self._token = token
        self._base = (
            "https://sandbox.zenodo.org/api"
            if sandbox
            else "https://zenodo.org/api"
        )
        self._sandbox = sandbox

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        *,
        data: bytes | None = None,
        content_type: str = "application/json",
        extra_headers: dict[str, str] | None = None,
        timeout: float = 60.0,
        max_attempts: int = 3,
    ) -> dict:
        url = self._base.rstrip("/") + path
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": content_type,
            **(extra_headers or {}),
        }
        # Only idempotent reads are retried. A write (POST/PUT/DELETE) is sent exactly once, even on
        # a timeout, because a retry could duplicate an irreversible action (e.g. double-publish).
        idempotent = method.upper() in ("GET", "HEAD")
        attempts = max_attempts if idempotent else 1
        last_exc: Exception | None = None
        for attempt in range(attempts):
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    body = resp.read()
                    return json.loads(body) if body else {}
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
                # Retry idempotent reads on transient server states (cold start / rate limit).
                if idempotent and exc.code in (429, 500, 502, 503, 504) and attempt < attempts - 1:
                    last_exc = exc
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                raise ZenodoError(f"Zenodo {exc.code} on {method} {url}: {body[:400]}") from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                # Connection reset / DNS / timeout: previously escaped as a raw, opaque exception.
                # Retry idempotent reads; otherwise surface as a clean ZenodoError.
                if idempotent and attempt < attempts - 1:
                    last_exc = exc
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                raise ZenodoError(f"Zenodo request failed ({method} {url}): {exc}") from exc
        raise ZenodoError(  # pragma: no cover — loop always returns or raises above
            f"Zenodo request failed after {attempts} attempt(s) ({method} {url}): {last_exc}"
        )

    def _json(self, method: str, path: str, payload: dict | None = None) -> dict:
        body = json.dumps(payload or {}).encode("utf-8")
        return self._request(method, path, data=body)

    # ── Deposits ───────────────────────────────────────────────────────────────

    def create_empty_deposit(self) -> dict:
        """Create a draft deposit with no metadata and return it.

        The returned dict includes ``record_id`` (the public record ID used in
        the Zenodo URL) and a pre-reserved DOI — use these before uploading so
        that placeholder URLs in staged files can be patched to the real values.
        """
        return self._json("POST", "/deposit/depositions", {})

    def create_deposit(self, metadata: dict) -> dict:
        """Create a new draft deposit, apply metadata, and return the full record."""
        deposit = self._json("POST", "/deposit/depositions", {})
        deposit_id = deposit["id"]
        self.update_metadata(deposit_id, metadata)
        return self._json("GET", f"/deposit/depositions/{deposit_id}")

    def update_metadata(self, deposit_id: int | str, metadata: dict) -> dict:
        """Update the metadata of an existing draft deposit."""
        return self._json(
            "PUT",
            f"/deposit/depositions/{deposit_id}",
            {"metadata": metadata},
        )

    def get_deposit(self, deposit_id: int | str) -> dict:
        return self._json("GET", f"/deposit/depositions/{deposit_id}")

    def publish_deposit(self, deposit_id: int | str) -> dict:
        """Publish a draft deposit. This action is irreversible.

        The publish POST is never retried (a retry could mint a second DOI). But a transient
        failure — a timeout or dropped connection — may still have committed server-side, leaving
        the caller unsure whether the DOI exists. On such a failure we confirm by re-reading the
        deposit: if it is already published, the publish succeeded and we return it; otherwise the
        original error is raised so the caller does not believe a draft went out.
        """
        try:
            return self._json("POST", f"/deposit/depositions/{deposit_id}/actions/publish")
        except ZenodoError as exc:
            try:
                deposit = self.get_deposit(deposit_id)
            except ZenodoError:
                raise exc from None
            state = str(deposit.get("state") or "").lower()
            if state == "done" or deposit.get("submitted") is True:
                return deposit
            raise

    def discard_deposit(self, deposit_id: int | str) -> None:
        """Discard (delete) an unpublished draft deposit."""
        self._json("DELETE", f"/deposit/depositions/{deposit_id}")

    def create_new_version(self, published_record_id: int | str) -> dict:
        """Fork a new draft from an existing published record.

        Returns the new draft deposit dict (same shape as ``create_empty_deposit``).
        """
        resp = self._json(
            "POST",
            f"/deposit/depositions/{published_record_id}/actions/newversion",
        )
        # The API returns the published record; the new draft is at latest_draft.
        draft_url = resp.get("links", {}).get("latest_draft", "")
        if not draft_url:
            raise ZenodoError(
                f"No latest_draft link in newversion response for {published_record_id}. "
                "Check that the record is published."
            )
        new_id = draft_url.rstrip("/").split("/")[-1]
        return self.get_deposit(new_id)

    def delete_all_files(self, deposit_id: int | str) -> int:
        """Delete every file from a draft deposit.  Returns the count deleted."""
        files = self.list_files(deposit_id)
        for f in files:
            self._request(
                "DELETE",
                f"/deposit/depositions/{deposit_id}/files/{f['id']}",
                data=b"",
            )
        return len(files)

    # ── Files ──────────────────────────────────────────────────────────────────

    def upload_files(
        self,
        deposit_id: int | str,
        files: dict[Path, str],
        *,
        timeout: float = 900.0,
        retries: int = 4,
    ) -> dict[Path, str]:
        """Upload files to a deposit via the S3-compatible bucket URL.

        Args:
            deposit_id: The deposit ID.
            files: Mapping of {local_path: zenodo_filename}.

        Returns:
            Mapping of {local_path: zenodo_download_url} for each uploaded file.
        """
        deposit = self.get_deposit(deposit_id)
        bucket_url = deposit.get("links", {}).get("bucket")
        if not bucket_url:
            raise ZenodoError(f"Deposit {deposit_id} has no bucket URL.")

        result: dict[Path, str] = {}
        for local_path, zenodo_name in files.items():
            local_path = Path(local_path)
            if not local_path.is_file():
                continue
            upload_url = f"{bucket_url}/{zenodo_name}"
            # Zenodo's S3-compatible bucket endpoint requires application/octet-stream
            # regardless of actual file type — it rejects other Content-Type values.
            data = local_path.read_bytes()
            # Retry transient network failures (socket read/write timeouts, dropped
            # connections) with backoff — large data files over a slow or flaky link
            # otherwise fail a whole publish. A bucket PUT is idempotent by filename,
            # so re-uploading the same name simply overwrites. HTTP errors (auth, quota)
            # are not transient and fail fast.
            file_record = None
            for attempt in range(1, retries + 1):
                req = urllib.request.Request(
                    upload_url,
                    data=data,
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Content-Type": "application/octet-stream",
                    },
                    method="PUT",
                )
                try:
                    with urllib.request.urlopen(req, timeout=timeout) as r:
                        file_record = json.loads(r.read())
                    break
                except urllib.error.HTTPError as exc:
                    body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
                    raise ZenodoError(f"Upload failed for {zenodo_name}: {exc.code} {body[:300]}") from exc
                except (urllib.error.URLError, TimeoutError, OSError) as exc:
                    if attempt >= retries:
                        raise ZenodoError(
                            f"Upload of {zenodo_name} failed after {retries} attempts: {exc}"
                        ) from exc
                    time.sleep(min(30.0, 5.0 * attempt))

            download_url = (
                file_record.get("links", {}).get("download")
                or file_record.get("links", {}).get("self")
                or upload_url
            )
            result[local_path] = download_url

        return result

    def list_files(self, deposit_id: int | str) -> list[dict]:
        return self._json("GET", f"/deposit/depositions/{deposit_id}/files")

    def delete_file(self, deposit_id: int | str, file_id: str) -> None:
        self._request("DELETE", f"/deposit/depositions/{deposit_id}/files/{file_id}", data=b"")

    def sync_files(
        self,
        deposit_id: int | str,
        files: dict[Path, str],
    ) -> dict[str, list[str]]:
        """Make the deposit's files match *files* while re-uploading as little as possible.

        Files already on the deposit whose content is unchanged (MD5 match) are kept;
        changed files are replaced; files no longer present are removed; new files are
        uploaded. This is what makes a new version cheap — Zenodo copies the prior
        version's files into the new draft, so unchanged data (often gigabytes) need not
        be re-uploaded; typically only ``battinfo.json``/``ro-crate-metadata.json`` change.

        ``files`` maps ``{local_path: zenodo_filename}`` (same shape as :meth:`upload_files`).
        Returns ``{"uploaded": [...], "kept": [...], "removed": [...]}``.
        """
        existing = {(f.get("filename") or f.get("key")): f for f in self.list_files(deposit_id)}
        desired = {name: Path(path) for path, name in files.items()}

        to_upload: dict[Path, str] = {}
        kept: list[str] = []
        for name, path in desired.items():
            ex = existing.get(name)
            if ex is not None and _zenodo_checksum_matches(path, ex.get("checksum")):
                kept.append(name)
            else:
                to_upload[path] = name

        removed = [name for name in existing if name not in desired]
        # A changed file must be deleted before its replacement is uploaded.
        changed = [name for name in to_upload.values() if name in existing]
        for name in removed + changed:
            self.delete_file(deposit_id, existing[name]["id"])

        self.upload_files(deposit_id, to_upload)
        return {"uploaded": sorted(to_upload.values()), "kept": sorted(kept), "removed": sorted(removed)}

    # ── Convenience ────────────────────────────────────────────────────────────

    @property
    def deposit_base_url(self) -> str:
        domain = "sandbox.zenodo.org" if self._sandbox else "zenodo.org"
        return f"https://{domain}/deposit"

    def record_url(self, record_id: int | str) -> str:
        domain = "sandbox.zenodo.org" if self._sandbox else "zenodo.org"
        return f"https://{domain}/records/{record_id}"


# ── Module-level utilities ─────────────────────────────────────────────────────

def _resolve_token(token: str | None) -> str:
    if token is not None:
        return token
    env = os.environ.get("ZENODO_API_TOKEN")
    if env:
        return env
    raise ZenodoError(
        "No Zenodo API token provided. Pass token= or set ZENODO_API_TOKEN."
    )


def _normalized_citation_doi(citation: dict[str, Any]) -> str | None:
    """Return a bare DOI (e.g. ``10.1038/...``) for a citation, or ``None``.

    Accepts the DOI as a bare string or a ``doi.org`` URL, in either the ``doi``
    or ``url`` field — so a citation carrying its identifier only as a URL is not
    dropped, and a URL-form DOI is normalised to the bare form Zenodo requires for
    ``scheme="doi"`` (a full URL is rejected by the API). Reuses the shared
    ``_citation_doi_from_url`` rather than re-implementing DOI parsing.
    """
    from battinfo.publication import _citation_doi_from_url  # local import avoids any import cycle

    for key in ("doi", "url"):
        value = citation.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        value = value.strip()
        extracted = _citation_doi_from_url(value)
        if extracted:
            return extracted
        if value.lower().startswith("10."):  # already a bare DOI
            return value
    return None


def _related_identifiers_from_citations(record: ZenodoCellRecord) -> list[dict[str, str]]:
    """Map the record's dataset citations to Zenodo ``related_identifiers``.

    The Zenodo deposit *is* the dataset(s), so each article citation
    (``kind != "dataset"``) becomes an ``isSupplementTo`` relation pointing at
    the publication DOI. The dataset's own self-citation (``kind == "dataset"``)
    is skipped — it describes this deposit, not a related work. The relationship
    itself originates in the BattINFO record's ``dataset.citations``; this only
    re-expresses it in Zenodo's native vocabulary so the published deposit is
    self-describing. DOIs are de-duplicated across all datasets in the record.
    """
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in record.datasets:
        for citation in entry.dataset.citations:
            if not isinstance(citation, dict):
                continue
            kind = citation.get("kind") or "article"
            if kind == "dataset":
                continue
            # Accept the DOI from the 'doi' or 'url' field, bare or as a doi.org URL,
            # and normalise to the bare form Zenodo requires for scheme='doi' (a full
            # URL is rejected). This also rescues citations whose DOI is only in 'url'.
            doi = _normalized_citation_doi(citation)
            if doi is None or doi in seen:
                continue
            seen.add(doi)
            related: dict[str, str] = {"identifier": doi, "relation": "isSupplementTo", "scheme": "doi"}
            if kind == "article":
                related["resource_type"] = "publication-article"
            out.append(related)
    return out


def _build_zenodo_metadata(
    record: ZenodoCellRecord,
    *,
    creators: list[dict[str, Any]],
    title: str | None,
    description: str | None,
    license: str,
    community: str | None,
    extra_keywords: list[str] | None,
) -> dict[str, Any]:
    ct = record.cell_spec

    def _clean_meta(val: Any) -> str | None:
        """Drop empty / placeholder ('unknown') metadata so it never leaks into the
        published title, description, or keywords."""
        text = str(val).strip() if val is not None else ""
        return text if text and text.lower() != "unknown" else None

    clean_name = _clean_meta(ct.name) or _clean_meta(ct.model) or "Battery"
    resolved_title = title or f"{clean_name} — BattINFO Reference Datasets"

    if description is None:
        n = len(record.datasets)
        name_parts = [p for p in (_clean_meta(ct.manufacturer), _clean_meta(ct.model)) if p]
        attr_parts = [p for p in (_clean_meta(ct.format), _clean_meta(ct.chemistry)) if p]
        subject = " ".join(name_parts)
        if attr_parts:
            subject = f"{subject} ({', '.join(attr_parts)})".strip()
        subject = subject or "battery cells"
        resolved_description = (
            f"BattINFO reference battery cycling datasets for {subject}. "
            f"Contains {n} dataset{'s' if n != 1 else ''}. "
            f"Published via the BattINFO battery data framework."
        )
    else:
        resolved_description = description

    kw: list[str] = ["BattINFO", "battery", "battery cycling"]
    for raw in (ct.manufacturer, ct.model, ct.format, ct.chemistry):
        val = _clean_meta(raw)
        if val and val not in kw:
            kw.append(val)
    if ct.iec_code and ct.iec_code not in kw:
        kw.append(ct.iec_code)
    if ct.positive_electrode_basis and ct.positive_electrode_basis not in kw:
        kw.append(ct.positive_electrode_basis)
    if ct.negative_electrode_basis and ct.negative_electrode_basis not in kw:
        kw.append(ct.negative_electrode_basis)
    if extra_keywords:
        for k in extra_keywords:
            if k not in kw:
                kw.append(k)

    metadata: dict[str, Any] = {
        "upload_type": "dataset",
        "title": resolved_title,
        "description": resolved_description,
        "creators": creators,
        "access_right": "open",
        "license": license,
        "keywords": kw,
    }
    if community is not None:
        metadata["communities"] = [{"identifier": community}]

    related_identifiers = _related_identifiers_from_citations(record)
    if related_identifiers:
        metadata["related_identifiers"] = related_identifiers

    return metadata


def patch_zenodo_urls(
    staging_dir: PathLike,
    record_id: str | int,
    *,
    placeholder: str = "ZENODO_RECORD_ID",
    sandbox: bool = False,
    publish_filename: str = _DEFAULT_PUBLISH_FILENAME,
    ro_crate_filename: str = _DEFAULT_RO_CRATE_FILENAME,
    bundle_filename: str = ZENODO_CELL_RECORD_FILENAME,
) -> dict[str, int]:
    """Replace placeholder Zenodo URLs in staged files with the real record ID.

    Patches ``battinfo.publish.jsonld``, ``ro-crate-metadata.json``, and
    ``battinfo.bundle.json`` in place.  The placeholder token is replaced
    everywhere it appears in the file text.

    Args:
        staging_dir: Directory containing the staged files.
        record_id: The real Zenodo record ID (from the deposit's ``record_id``
                   field, not the deposition ``id``).
        placeholder: Token used when building the package (default
                     ``ZENODO_RECORD_ID``).
        sandbox: If True, use ``sandbox.zenodo.org`` in patched URLs.
        publish_filename: Override for the JSON-LD filename.
        ro_crate_filename: Override for the RO-Crate filename.
        bundle_filename: Override for the bundle JSON filename.

    Returns:
        Dict mapping filename → number of replacements made.
    """
    staging = Path(staging_dir)
    domain = "sandbox.zenodo.org" if sandbox else "zenodo.org"
    old_url = f"https://zenodo.org/records/{placeholder}"
    new_url = f"https://{domain}/records/{record_id}"

    results: dict[str, int] = {}
    for fname in (publish_filename, ro_crate_filename, bundle_filename):
        fpath = staging / fname
        if not fpath.exists():
            continue
        text = fpath.read_text(encoding="utf-8")
        # Replace the full record URL first, then any remaining bare placeholder
        # tokens (e.g. inside the DOI "10.5281/zenodo.<placeholder>"), so the token
        # is gone everywhere it appears — as the docstring promises.
        url_patched = text.replace(old_url, new_url)
        count = text.count(old_url) + url_patched.count(placeholder)
        if count > 0:
            fpath.write_text(url_patched.replace(placeholder, str(record_id)), encoding="utf-8")
        results[fname] = count

    return results


def upload_zenodo_package(
    staging_dir: PathLike,
    creators: list[dict[str, Any]],
    *,
    token: str | None = None,
    sandbox: bool = False,
    community: str | None = "battinfo-reference",
    title: str | None = None,
    description: str | None = None,
    license: str = "cc-by-4.0",
    extra_keywords: list[str] | None = None,
    publish: bool = False,
    zenodo_record_id_placeholder: str = "ZENODO_RECORD_ID",
    publish_filename: str = _DEFAULT_PUBLISH_FILENAME,
    ro_crate_filename: str = _DEFAULT_RO_CRATE_FILENAME,
    bundle_filename: str = ZENODO_CELL_RECORD_FILENAME,
    upload_timeout: float = 300.0,
) -> dict[str, Any]:
    """Upload a staged Zenodo package and optionally publish it.

    Workflow:
    1. Load ``battinfo.bundle.json`` from *staging_dir* to derive metadata.
    2. Create an empty Zenodo deposit to obtain the pre-reserved record ID.
    3. Patch placeholder URLs in all staged files with the real record ID.
    4. Upload every file from *staging_dir* to the deposit.
    5. Set deposit metadata (title, creators, keywords, community, …).
    6. Optionally publish (or leave as draft for curator review).

    Args:
        staging_dir: Directory produced by ``build_zenodo_package``.
        creators: Zenodo creator list, e.g.
                  ``[{"name": "Clark, Simon", "affiliation": "SINTEF"}]``.
        token: Zenodo API token.  Falls back to ``ZENODO_API_TOKEN`` env var.
        sandbox: Use the Zenodo sandbox instead of production.
        community: Zenodo community identifier for submission
                   (``None`` skips community submission).
        title: Override the auto-derived record title.
        description: Override the auto-derived record description.
        license: SPDX license identifier (default ``cc-by-4.0``).
        extra_keywords: Additional keywords appended to the auto-derived list.
        publish: If True, publish the deposit immediately.  If False (default),
                 leave as a draft for manual review / curator acceptance.
        zenodo_record_id_placeholder: Must match the placeholder used in
                                      ``build_zenodo_package``.
        publish_filename: Override for the JSON-LD filename.
        ro_crate_filename: Override for the RO-Crate filename.
        bundle_filename: Override for the bundle JSON filename.
        upload_timeout: Per-file upload timeout in seconds.

    Returns:
        Dict with ``deposit_id``, ``record_id``, ``record_url``,
        ``deposit_url``, ``doi``, ``patch_counts``, ``uploaded_files``,
        and ``published`` keys.
    """
    if not creators:
        raise ValueError("creators must be a non-empty list.")

    staging = Path(staging_dir)
    api_token = _resolve_token(token)
    client = ZenodoClient(token=api_token, sandbox=sandbox)

    bundle_path = staging / bundle_filename
    if not bundle_path.exists():
        raise FileNotFoundError(f"{bundle_filename} not found in {staging}")
    record = ZenodoCellRecord.from_path(bundle_path)

    deposit = client.create_empty_deposit()
    deposit_id: int = deposit["id"]
    record_id: int = deposit["record_id"]
    prereserved_doi: str = (
        deposit.get("metadata", {})
        .get("prereserve_doi", {})
        .get("doi", f"10.5281/zenodo.{record_id}")
    )

    patch_counts = patch_zenodo_urls(
        staging,
        record_id,
        placeholder=zenodo_record_id_placeholder,
        sandbox=sandbox,
        publish_filename=publish_filename,
        ro_crate_filename=ro_crate_filename,
        bundle_filename=bundle_filename,
    )

    all_files: list[Path] = sorted(f for f in staging.iterdir() if f.is_file())
    upload_map: dict[Path, str] = {f: f.name for f in all_files}
    client.upload_files(deposit_id, upload_map, timeout=upload_timeout)

    metadata = _build_zenodo_metadata(
        record,
        creators=creators,
        title=title,
        description=description,
        license=license,
        community=community,
        extra_keywords=extra_keywords,
    )
    client.update_metadata(deposit_id, metadata)

    domain = "sandbox.zenodo.org" if sandbox else "zenodo.org"
    record_url = f"https://{domain}/records/{record_id}"
    deposit_url = f"https://{domain}/deposit/{deposit_id}"

    published = False
    if publish:
        client.publish_deposit(deposit_id)
        published = True

    return {
        "deposit_id": deposit_id,
        "record_id": record_id,
        "record_url": record_url,
        "deposit_url": deposit_url,
        "doi": prereserved_doi,
        "patch_counts": patch_counts,
        "uploaded_files": [f.name for f in all_files],
        "published": published,
        "sandbox": sandbox,
    }


__all__ = [
    "ZenodoClient",
    "ZenodoError",
    "patch_zenodo_urls",
    "upload_zenodo_package",
]
