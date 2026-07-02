"""A-3 / A-4: authoring identity must not silently duplicate or overwrite.

A-4 — save() exposes ``mode`` so the create-only guard is reachable (a fresh run can refuse to
touch records left by a previous session), and an upsert that replaces genuinely different content
is reported (content_changed) rather than overwriting silently.

A-3 — a registry 409 is detected by its status code, not by matching the string "409" anywhere in
an error body, and the version bump it triggers is surfaced (printed + version_bumped) instead of
silently proliferating -vN copies."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo import ws as ws_module
from battinfo.api import (
    REGISTER_MODE_CREATE_ONLY,
    REGISTER_MODE_UPSERT,
    RegistryClientError,
    _record_content_differs,
    save_record,
)

EXAMPLE = ROOT / "src/battinfo/data/examples/cell-spec/A123__ANR26650M1-B.json"


# ── A-4: content-change detection ─────────────────────────────────────────────
def _write(path: Path, doc: dict) -> Path:
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_record_content_differs_ignores_volatile_only_changes(tmp_path: Path) -> None:
    base = {"specification": {"id": "x", "nominal_capacity": {"value": 2.5, "unit": "Ah"}}}
    existing = _write(tmp_path / "a.json", {**base, "generated_at": "2026-01-01T00:00:00Z"})
    same_but_newer = {**base, "generated_at": "2026-07-02T09:00:00Z"}
    assert _record_content_differs(existing, same_but_newer) is False


def test_record_content_differs_on_real_change(tmp_path: Path) -> None:
    existing = _write(tmp_path / "a.json", {"specification": {"nominal_capacity": {"value": 2.5}}})
    changed = {"specification": {"nominal_capacity": {"value": 3.0}}}
    assert _record_content_differs(existing, changed) is True


def test_record_content_differs_when_existing_missing(tmp_path: Path) -> None:
    assert _record_content_differs(tmp_path / "nope.json", {"a": 1}) is True


def test_save_record_reports_content_changed_on_upsert(tmp_path: Path) -> None:
    doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    first = save_record(doc, source_root=tmp_path, mode=REGISTER_MODE_UPSERT, publish=False)
    assert first["status"] == "created"
    assert first["content_changed"] is False  # nothing was there before

    # Re-save identical content: an idempotent upsert, not a meaningful overwrite.
    again = save_record(doc, source_root=tmp_path, mode=REGISTER_MODE_UPSERT, publish=False)
    assert again["status"] == "updated"
    assert again["content_changed"] is False

    # Change a value and upsert: the overwrite is flagged, not silent.
    edited = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    edited.setdefault("properties", {})["nominal_capacity"] = {"value": 99.9, "unit": "Ah"}
    changed = save_record(edited, source_root=tmp_path, mode=REGISTER_MODE_UPSERT, publish=False)
    assert changed["status"] == "updated"
    assert changed["content_changed"] is True


def test_save_record_create_only_guard_is_reachable(tmp_path: Path) -> None:
    doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    save_record(doc, source_root=tmp_path, mode=REGISTER_MODE_UPSERT, publish=False)
    with pytest.raises(ValueError, match="already exists"):
        save_record(doc, source_root=tmp_path, mode=REGISTER_MODE_CREATE_ONLY, publish=False)


# ── A-3: 409 conflict handling ────────────────────────────────────────────────
def _ok_result(iri: str = "iri-x") -> dict:
    return {"status": "ok", "status_code": 200,
            "response": {"status": "validated", "resources": [{"canonical_iri": iri}]}}


def _payload() -> dict:
    return {"source_version": "2026-07-02", "resource": {"source_version": "2026-07-02"}}


def _run_do_submit(monkeypatch: pytest.MonkeyPatch, behavior) -> dict:
    monkeypatch.setattr("battinfo.api.submit_publication_package", behavior)
    return ws_module._do_submit(_payload(), "https://registry.example", "k", "Cell X")


def test_conflict_bumps_version_and_surfaces_it(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str | None] = []
    state = {"n": 0}

    def behavior(payload, **kw):  # noqa: ANN001
        state["n"] += 1
        seen.append(payload.get("source_version"))
        if state["n"] == 1:
            raise RegistryClientError("Registry submission failed with HTTP 409: conflict",
                                      status_code=409)
        return _ok_result()

    out = _run_do_submit(monkeypatch, behavior)
    assert out["ok"] is True
    assert out["version_bumped"] == "2026-07-02-v2"
    assert seen == ["2026-07-02", "2026-07-02-v2"]  # retried once, with the bumped version


def test_conflict_detected_by_status_code_not_string(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"n": 0}

    def behavior(payload, **kw):  # noqa: ANN001
        state["n"] += 1
        if state["n"] == 1:
            raise RegistryClientError("resource already exists", status_code=409)  # no "409" text
        return _ok_result()

    out = _run_do_submit(monkeypatch, behavior)
    assert out["ok"] is True
    assert out["version_bumped"] == "2026-07-02-v2"


def test_non_conflict_error_does_not_bump(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"n": 0}

    def behavior(payload, **kw):  # noqa: ANN001
        state["n"] += 1
        raise RegistryClientError("Registry submission failed with HTTP 422: invalid",
                                  status_code=422)

    out = _run_do_submit(monkeypatch, behavior)
    assert out["ok"] is False
    assert out["version_bumped"] is None
    assert state["n"] == 1  # a non-conflict error is not retried
