"""Record-level license: workspace default, precedence, emission, and nudge.

Blind-review finding (Prompt C, finding 2): served/local records carried no
license (FAIR R1.1 failed at the identifier); license lived only on the Zenodo
leg. ``ws.license(...)`` sets a workspace default persisted in workspace.json and
stamped onto every record at save, mirroring ``ws.contributor``.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import pytest

from battinfo.jsonld import record_to_jsonld
from battinfo.ws import AuthoringWorkspace

_SPEC_JSON = (
    '{"manufacturer":"Duracell","model":"MN2400","format":"cylindrical",'
    '"chemistry":"Zn-MnO2","size_code":"R03","iec_code":"LR03",'
    '"properties":{"nominal_voltage":{"value":1.5,"unit":"V"}}}'
)


def _ws_with_cell(tmp_path: Path) -> AuthoringWorkspace:
    (tmp_path / "d.cell-spec.json").write_text(_SPEC_JSON, encoding="utf-8")
    (tmp_path / "f.csv").write_text("unix_time_second,voltage\n0,1\n", encoding="utf-8")
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    spec = ws.load(tmp_path / "d.cell-spec.json")
    ws.add("cell", spec=spec, serial_numbers=["SN-1"])
    return ws


def _read_one(ws: AuthoringWorkspace, subdir: str) -> dict:
    return json.loads(next((ws._ws.source_root / subdir).glob("*.json")).read_text(encoding="utf-8"))


# ── API: setter / getter / persistence / validation ────────────────────────────

def test_license_setter_persists_and_getter_returns(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    assert ws.license() is None                      # unset getter
    assert ws.license("cc-by-4.0") == "cc-by-4.0"    # setter returns normalized
    assert ws.license() == "cc-by-4.0"               # getter reflects it
    state = json.loads((tmp_path / ".battinfo" / "workspace.json").read_text(encoding="utf-8"))
    assert state["license"] == "cc-by-4.0"
    # A fresh instance loads it from disk.
    assert AuthoringWorkspace(root=tmp_path, registry_url=None).license() == "cc-by-4.0"


def test_license_known_id_is_case_normalized(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    assert ws.license("CC-BY-4.0") == "cc-by-4.0"


def test_license_unknown_id_kept_verbatim_with_warning(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = ws.license("My-Custom-License-1.2")
    assert result == "My-Custom-License-1.2"                 # verbatim, not rejected
    assert any("not a recognised SPDX" in str(w.message) for w in caught)


def test_license_url_kept_verbatim(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        assert ws.license("https://creativecommons.org/licenses/by/4.0/") == (
            "https://creativecommons.org/licenses/by/4.0/"
        )


def test_license_clear(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    ws.license("cc-by-4.0")
    assert ws.license(clear=True) is None
    assert ws.license() is None
    state = json.loads((tmp_path / ".battinfo" / "workspace.json").read_text(encoding="utf-8"))
    assert "license" not in state


# ── Stamping: license lands in every saved record ──────────────────────────────

def test_license_stamped_on_every_saved_record(tmp_path: Path) -> None:
    ws = _ws_with_cell(tmp_path)
    ws.add("test", type="capacity_check", cell="SN-1", data="f.csv")
    ws.license("cc-by-4.0")
    ws.save()

    # Non-dataset records carry it at the top level.
    for sub in ("cell-spec", "cell-instance", "test"):
        assert _read_one(ws, sub)["license"] == "cc-by-4.0", sub
    # Datasets carry it on the dataset body (the existing slot the emitter reads).
    assert _read_one(ws, "dataset")["dataset"]["license"] == "cc-by-4.0"


def test_license_stamped_into_record_to_jsonld(tmp_path: Path) -> None:
    ws = _ws_with_cell(tmp_path)
    ws.add("test", type="capacity_check", cell="SN-1", data="f.csv")
    ws.license("cc-by-4.0")
    ws.save()

    for sub, rt in (("cell-spec", "cell-spec"), ("cell-instance", "cell-instance"),
                    ("test", "test"), ("dataset", "dataset")):
        ld = record_to_jsonld(_read_one(ws, sub), rt)
        assert ld.get("dcterms:license") == {"@id": "cc-by-4.0"}, sub


def test_no_license_means_no_stamp(tmp_path: Path) -> None:
    # Without ws.license, saved records must not sprout a license key.
    ws = _ws_with_cell(tmp_path)
    ws.save()
    assert "license" not in _read_one(ws, "cell-instance")


# ── Precedence: explicit ws.add(license=) > workspace default ───────────────────

def test_explicit_add_license_overrides_workspace_default(tmp_path: Path) -> None:
    ws = _ws_with_cell(tmp_path)
    ws.license("cc-by-4.0")                           # workspace default
    ws.add("test", type="capacity_check", cell="SN-1", data="f.csv", license="mit")
    ws.save()
    # The dataset keeps the explicit per-record license; the workspace default
    # only back-fills records that have none.
    assert _read_one(ws, "dataset")["dataset"]["license"] == "mit"
    # A record with no explicit license still gets the workspace default.
    assert _read_one(ws, "cell-instance")["license"] == "cc-by-4.0"


# ── Emission: preview bundle carries the license; ws.zenodo default resolution ──

def test_preview_bundle_carries_workspace_license(tmp_path: Path) -> None:
    ws = _ws_with_cell(tmp_path)
    ws.add("test", type="capacity_check", cell="SN-1", data="f.csv")
    ws.license("cc-by-4.0")
    ws.save()
    out = ws.preview_jsonld(output=tmp_path / "preview.jsonld")
    graph = json.loads(Path(out).read_text(encoding="utf-8"))["@graph"]
    catalog = next(n for n in graph if "dcat:Catalog" in (n.get("@type") or []))
    assert catalog.get("dcterms:license") or catalog.get("schema:license")


class _StubZenodoClient:
    """Offline stand-in: returns a minimal deposit so the flow reaches the
    JSON-LD builder without touching the network."""

    def __init__(self, *a, **k) -> None:  # noqa: ANN002, ANN003
        pass

    def create_empty_deposit(self) -> dict:
        return {"id": 1, "record_id": 1, "metadata": {"prereserve_doi": {"doi": "10.5281/zenodo.1"}}}


def test_zenodo_license_defaults_to_workspace_license(monkeypatch, tmp_path: Path) -> None:
    # ws.zenodo(license=None) must resolve to the workspace default, not the
    # hard-coded cc-by-4.0, when a default is set.
    captured: dict = {}

    def _fake_build(self, **kwargs):  # noqa: ANN001, ANN003
        captured["license"] = kwargs.get("license")
        raise RuntimeError("stop after license resolution")

    ws = _ws_with_cell(tmp_path)
    ws.add("test", type="capacity_check", cell="SN-1", data="f.csv")
    ws.license("mit")
    ws.save()
    monkeypatch.setattr("battinfo.zenodo.ZenodoClient", _StubZenodoClient)
    monkeypatch.setattr(AuthoringWorkspace, "_build_zenodo_jsonld", _fake_build)
    monkeypatch.setenv("ZENODO_API_TOKEN", "x")
    # Stop the flow right after license resolution — we only assert the value
    # wired downstream, not a real deposit.
    with pytest.raises(RuntimeError, match="stop after license resolution"):
        ws.zenodo()
    assert captured.get("license") == "mit"


def test_zenodo_explicit_license_overrides_workspace_default(monkeypatch, tmp_path: Path) -> None:
    captured: dict = {}

    def _fake_build(self, **kwargs):  # noqa: ANN001, ANN003
        captured["license"] = kwargs.get("license")
        raise RuntimeError("stop")

    ws = _ws_with_cell(tmp_path)
    ws.add("test", type="capacity_check", cell="SN-1", data="f.csv")
    ws.license("mit")
    ws.save()
    monkeypatch.setattr("battinfo.zenodo.ZenodoClient", _StubZenodoClient)
    monkeypatch.setattr(AuthoringWorkspace, "_build_zenodo_jsonld", _fake_build)
    monkeypatch.setenv("ZENODO_API_TOKEN", "x")
    with pytest.raises(RuntimeError):
        ws.zenodo(license="cc-by-4.0")
    assert captured.get("license") == "cc-by-4.0"


# ── Gold-standard panel: a licenseless publication warns (not errors) ───────────

def test_missing_license_produces_a_warning_nudge(tmp_path: Path) -> None:
    from battinfo.validate import validate_publication_report

    ws = _ws_with_cell(tmp_path)
    ws.add("test", type="capacity_check", cell="SN-1", data="f.csv")
    ws.save()
    # No license anywhere -> the assembled publication catalog has none.
    jsonld = ws._build_zenodo_jsonld(
        zenodo_record_id=0,
        prereserved_doi="10.5281/zenodo.RECORD_ID",
        record_url="https://zenodo.org/records/RECORD_ID",
        data_filenames=[],
        title="t",
        description="d",
        license="",
    )
    report = validate_publication_report(jsonld, policy="publisher")
    lic = [i for i in report.issues if i.code == "publication.license_missing"]
    assert lic and all(i.severity == "warning" for i in lic)
    assert "ws.license" in lic[0].message


def test_present_license_produces_no_nudge(tmp_path: Path) -> None:
    from battinfo.validate import validate_publication_report

    ws = _ws_with_cell(tmp_path)
    ws.add("test", type="capacity_check", cell="SN-1", data="f.csv")
    ws.license("cc-by-4.0")
    ws.save()
    jsonld = ws._build_zenodo_jsonld(
        zenodo_record_id=0,
        prereserved_doi="10.5281/zenodo.RECORD_ID",
        record_url="https://zenodo.org/records/RECORD_ID",
        data_filenames=[],
        title="t",
        description="d",
        license="cc-by-4.0",
    )
    report = validate_publication_report(jsonld, policy="publisher")
    assert not [i for i in report.issues if i.code == "publication.license_missing"]
