"""Artifact storage helpers for use with publish_ingest_workspace.

Install the optional S3/R2 backend with::

    pip install "battinfo[storage]"

Configure via environment variables::

    BATTINFO_STORAGE_ENDPOINT_URL   # e.g. https://<account>.r2.cloudflarestorage.com
    BATTINFO_STORAGE_BUCKET         # bucket name
    BATTINFO_STORAGE_ACCESS_KEY_ID
    BATTINFO_STORAGE_SECRET_ACCESS_KEY
    BATTINFO_STORAGE_PUBLIC_BASE_URL  # public CDN base URL (no trailing slash)
"""
from __future__ import annotations

import mimetypes
import os
from collections.abc import Callable
from pathlib import Path


class S3ArtifactUploader:
    """Upload artifact files to an S3-compatible bucket (including R2).

    Implements the ``Callable[[str, Path], str]`` contract expected by
    :func:`battinfo.ingest.publish_ingest_workspace`.  Files already present
    in the bucket are skipped; the public URL is returned either way.
    """

    def __init__(
        self,
        bucket: str,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        public_base_url: str | None = None,
        region: str = "auto",
    ) -> None:
        try:
            import boto3
        except ImportError as exc:
            raise ImportError(
                "boto3 is required for S3 artifact upload. "
                'Install it with: pip install "battinfo[storage]"'
            ) from exc

        self._bucket = bucket
        self._public_base_url = public_base_url.rstrip("/") if public_base_url else None
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
        )

    # ------------------------------------------------------------------
    # Callable interface
    # ------------------------------------------------------------------

    def __call__(self, key: str, source_path: Path) -> str:
        """Upload *source_path* to *key*; return its public URL.

        Skips the upload if the key already exists in the bucket.
        """
        if self._exists(key):
            return self._url(key)
        media_type = mimetypes.guess_type(source_path.name)[0] or "application/octet-stream"
        self._client.put_object(
            Bucket=self._bucket,
            Key=key,
            Body=source_path.read_bytes(),
            ContentType=media_type,
        )
        return self._url(key)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError:
            return False

    def _url(self, key: str) -> str:
        if self._public_base_url:
            return f"{self._public_base_url}/{key}"
        return f"s3://{self._bucket}/{key}"


def build_uploader_from_env() -> Callable[[str, Path], str] | None:
    """Return an :class:`S3ArtifactUploader` configured from environment variables.

    Returns ``None`` when ``BATTINFO_STORAGE_BUCKET`` is not set, so callers
    can branch on whether artifact upload is configured without raising.

    Required env var:
        ``BATTINFO_STORAGE_BUCKET``

    Optional env vars:
        ``BATTINFO_STORAGE_ENDPOINT_URL``,
        ``BATTINFO_STORAGE_ACCESS_KEY_ID``,
        ``BATTINFO_STORAGE_SECRET_ACCESS_KEY``,
        ``BATTINFO_STORAGE_PUBLIC_BASE_URL``
    """
    bucket = os.environ.get("BATTINFO_STORAGE_BUCKET", "").strip()
    if not bucket:
        return None
    return S3ArtifactUploader(
        bucket=bucket,
        endpoint_url=os.environ.get("BATTINFO_STORAGE_ENDPOINT_URL") or None,
        access_key_id=os.environ.get("BATTINFO_STORAGE_ACCESS_KEY_ID") or None,
        secret_access_key=os.environ.get("BATTINFO_STORAGE_SECRET_ACCESS_KEY") or None,
        public_base_url=os.environ.get("BATTINFO_STORAGE_PUBLIC_BASE_URL") or None,
    )
