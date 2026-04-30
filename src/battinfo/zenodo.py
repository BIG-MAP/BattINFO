"""
Minimal Zenodo REST API client for depositing BattINFO datasets.

Supports both the production API (zenodo.org) and the sandbox
(sandbox.zenodo.org) for testing before real publication.

References:
    https://developers.zenodo.org/
"""
from __future__ import annotations

import json
import mimetypes
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


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
    ) -> dict:
        url = self._base.rstrip("/") + path
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": content_type,
            **(extra_headers or {}),
        }
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            raise ZenodoError(f"Zenodo {exc.code} on {method} {url}: {body[:400]}") from exc

    def _json(self, method: str, path: str, payload: dict | None = None) -> dict:
        body = json.dumps(payload or {}).encode("utf-8")
        return self._request(method, path, data=body)

    # ── Deposits ───────────────────────────────────────────────────────────────

    def create_deposit(self, metadata: dict) -> dict:
        """Create a new draft deposit and return the full deposit record."""
        deposit = self._json("POST", "/deposit/depositions", {})
        deposit_id = deposit["id"]
        self.update_metadata(deposit_id, metadata)
        # Re-fetch to get the updated record with prereserved DOI
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
        """Publish a draft deposit. This action is irreversible."""
        return self._json("POST", f"/deposit/depositions/{deposit_id}/actions/publish")

    def discard_deposit(self, deposit_id: int | str) -> None:
        """Discard (delete) an unpublished draft deposit."""
        self._json("DELETE", f"/deposit/depositions/{deposit_id}")

    # ── Files ──────────────────────────────────────────────────────────────────

    def upload_files(
        self,
        deposit_id: int | str,
        files: dict[Path, str],
        *,
        timeout: float = 300.0,
    ) -> dict[Path, str]:
        """
        Upload files to a deposit.

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
            media_type = mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
            data = local_path.read_bytes()
            resp = self._request(
                "PUT",
                "",  # full URL passed via extra_headers trick below
                data=data,
                content_type=media_type,
                timeout=timeout,
            )
            # Re-issue with the full bucket URL directly
            req = urllib.request.Request(
                upload_url,
                data=data,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": media_type,
                },
                method="PUT",
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    file_record = json.loads(r.read())
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
                raise ZenodoError(f"Upload failed for {zenodo_name}: {exc.code} {body[:300]}") from exc

            download_url = (
                file_record.get("links", {}).get("download")
                or file_record.get("links", {}).get("self")
                or upload_url
            )
            result[local_path] = download_url

        return result

    def list_files(self, deposit_id: int | str) -> list[dict]:
        return self._json("GET", f"/deposit/depositions/{deposit_id}/files")

    # ── Convenience ────────────────────────────────────────────────────────────

    @property
    def deposit_base_url(self) -> str:
        domain = "sandbox.zenodo.org" if self._sandbox else "zenodo.org"
        return f"https://{domain}/deposit"
