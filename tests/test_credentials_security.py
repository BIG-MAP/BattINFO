"""A-6: the credentials file must be owner-only, and a registry response body embedded in an
error message must not leak the api_key (defence in depth against a registry that echoes it)."""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.api import _scrub_secret
from battinfo.ws import AuthoringWorkspace


def test_scrub_secret_redacts_key_and_tokens() -> None:
    key = "bk_live_ABC123def456"
    scrubbed = _scrub_secret(f"401 Unauthorized: key {key} rejected; also bk_test_zzz999", key)
    assert key not in scrubbed
    assert "bk_test_zzz999" not in scrubbed  # any bk_ token redacted, not just the one we sent
    assert "Unauthorized" in scrubbed  # non-secret context preserved
    assert _scrub_secret("no secrets here", "") == "no secrets here"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are a no-op on Windows")
def test_credentials_file_is_owner_only(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    path = ws._set_credentials({"api_key": "bk_live_secret"})
    assert path.exists()
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600, oct(mode)  # no group/other read of API keys / R2 secrets / tokens
