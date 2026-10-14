"""scripts/zenodo_sandbox_check.py: the release checklist's Zenodo sandbox run, which never runs here.

The script deposits to sandbox.zenodo.org with a real token, so it is run by
hand. These tests check what keeps it safe and what it checks, without running
a single step: it refuses to start under pytest or in CI, no workflow runs it,
its network guard lets requests reach the sandbox only, and its check of a
deposit's data files. Nothing here reaches the network.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("zenodo_sandbox_check", ROOT / "scripts" / "zenodo_sandbox_check.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check = _load()

SANDBOX = "https://sandbox.zenodo.org/api/deposit/depositions"


def test_it_will_not_run_under_pytest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ZENODO_SANDBOX_TOKEN", "not-a-token")
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    workdir = tmp_path / "workspace"

    assert check.main(["--workdir", str(workdir)]) == 2

    assert "does not run under pytest" in capsys.readouterr().err
    assert not workdir.exists()


def test_it_will_not_run_in_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ZENODO_SANDBOX_TOKEN", "not-a-token")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    reason = check.refuse_to_run_here()
    assert reason is not None and "does not run in CI" in reason


def test_no_workflow_runs_it() -> None:
    workflows = sorted((ROOT / ".github" / "workflows").iterdir())
    assert workflows
    for path in workflows:
        assert "zenodo_sandbox_check" not in path.read_text(encoding="utf-8"), path.name


class _Opener:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def __call__(self, request: urllib.request.Request, *args: object, **kwargs: object) -> str:
        self.urls.append(request.full_url)
        return "answered"


def test_the_network_guard_lets_requests_reach_the_sandbox_only() -> None:
    opener = _Opener()
    network = check.Network(opener)

    assert network(urllib.request.Request(SANDBOX)) == "answered"
    refused = [
        "https://zenodo.org/api/deposit/depositions",
        "https://sandbox.zenodo.org.example.org/api/deposit/depositions",
        "https://registry.invalid/api/publish",
    ]
    for url in refused:
        with pytest.raises(check.RefusedRequest):
            network(urllib.request.Request(url, data=b"{}", method="POST"))

    assert opener.urls == [SANDBOX]
    assert network.refused == [("POST", url) for url in refused]
    assert [url for _method, url in network.requests] == [SANDBOX, *refused]


def test_a_step_that_checks_how_a_zenodo_org_deposit_begins_still_sends_nothing_there() -> None:
    opener = _Opener()
    network = check.Network(opener)
    network.expect_production = True
    create = "https://zenodo.org/api/deposit/depositions"

    with pytest.raises(check.RefusedRequest):
        network(urllib.request.Request(create, data=b"{}", method="POST"))
    with pytest.raises(check.RefusedRequest):
        network(urllib.request.Request("https://registry.invalid/api/publish", data=b"{}", method="POST"))

    assert opener.urls == []
    assert network.stopped == [("POST", create)]
    assert network.refused == [("POST", "https://registry.invalid/api/publish")]


def test_the_guard_fails_one_upload_of_the_named_file_once() -> None:
    opener = _Opener()
    network = check.Network(opener)
    network.fail_upload = "battinfo.json"
    data_file = urllib.request.Request("https://sandbox.zenodo.org/api/files/b1/cycling.csv", data=b"x", method="PUT")
    graph = urllib.request.Request("https://sandbox.zenodo.org/api/files/b1/battinfo.json", data=b"{}", method="PUT")

    assert network(data_file) == "answered"
    with pytest.raises(urllib.error.HTTPError) as failed:
        network(graph)
    assert failed.value.code == 503
    assert network.fail_upload is None
    assert network(graph) == "answered"
    assert opener.urls == [data_file.full_url, graph.full_url]


DEPOSIT = {
    "cycling.csv": "aaa",
    "3f2a9c1d-cycling.csv": "bbb",
    "0b1c2d3e-CYCLING.csv": "ccc",
    "battinfo.json": "ddd",
    "ro-crate-metadata.json": "eee",
}
EXPECTED = {"C01": "aaa", "C02": "bbb", "C03": "ccc"}


def test_each_data_file_is_in_the_deposit_once_under_its_own_name() -> None:
    names = check.check_data_files(DEPOSIT, EXPECTED)
    assert names == ["cycling.csv", "3f2a9c1d-cycling.csv", "0b1c2d3e-CYCLING.csv"]


@pytest.mark.parametrize(
    ("deposit", "message"),
    [
        ({**DEPOSIT, "3f2a9c1d-cycling.csv": "aaa"}, "C01's data file .* 2 times"),
        ({k: v for k, v in DEPOSIT.items() if v != "ccc"}, "C03's data file .* 0 times"),
        ({**{k: v for k, v in DEPOSIT.items() if v != "ccc"}, "CYCLING.csv": "ccc"}, "share a name, ignoring case"),
        ({**{k: v for k, v in DEPOSIT.items() if v != "bbb"}, "cycling (1).csv": "bbb"}, "not as 'cycling.csv'"),
    ],
)
def test_a_lost_doubled_or_clashing_data_file_fails_the_check(deposit: dict[str, str], message: str) -> None:
    with pytest.raises(check.CheckFailed, match=message):
        check.check_data_files(deposit, EXPECTED)


def test_the_deposit_listing_is_read_with_or_without_the_md5_prefix() -> None:
    class _Client:
        def list_files(self, record_id: str) -> list[dict]:
            assert record_id == "123"
            return [{"filename": "cycling.csv", "checksum": "aaa"}, {"key": "battinfo.json", "checksum": "md5:ddd"}]

    assert check.deposit_files(_Client(), "123") == {"cycling.csv": "aaa", "battinfo.json": "ddd"}


# ── Step 4, against a stand-in for the sandbox ────────────────────────────────

# The deposit name of each test's data file in every version.
NAMES = {"C01": "cycling.csv", "C02": "0b1c-cycling.csv", "C03": "0d2e-CYCLING.csv"}


class _Sandbox:
    """Stands in for ws.zenodo() and ZenodoClient.list_files() on the sandbox, one record per version.

    *deleted* says what a new version does with a data file deleted locally:
    "keep" the copy the version before holds, or "refuse". *rename* gives
    C01, which does not change, a new name in the new version.
    """

    def __init__(self, root: Path, *, deleted: str, rename: bool = False) -> None:
        self.root = root
        self.deleted = deleted
        self.rename = rename
        first = {NAMES[serial]: check.md5(check.data_file(root, serial).read_bytes()) for serial in check.DATA_FILES}
        self.versions = {"1": first}
        self._state("1")

    def _state(self, record_id: str) -> None:
        state = {"environment": "sandbox", "record_id": record_id, "concept_record_id": "100", "published": True}
        (self.root / ".battinfo").mkdir(exist_ok=True)
        (self.root / ".battinfo" / "zenodo-sandbox.json").write_text(json.dumps(state), encoding="utf-8")

    def list_files(self, record_id: str) -> list[dict]:
        return [{"filename": name, "checksum": f"md5:{md5}"} for name, md5 in self.versions[record_id].items()]

    def zenodo(self, **kwargs: object) -> SimpleNamespace:
        assert kwargs["sandbox"] is True and kwargs["publish"] is True
        before = self.versions[max(self.versions, key=int)]
        files = {}
        for serial in check.DATA_FILES:
            path = check.data_file(self.root, serial)
            if path.exists():
                checksum = check.md5(path.read_bytes())
            elif self.deleted == "refuse":
                raise ValueError(f"data file not found: {path}")
            else:
                checksum = before[NAMES[serial]]
            files["ffff-cycling.csv" if self.rename and serial == "C01" else NAMES[serial]] = checksum
        record_id = str(len(self.versions) + 1)
        self.versions[record_id] = files
        self._state(record_id)
        return SimpleNamespace(record_id=record_id, published=True, doi=f"10.5072/zenodo.{record_id}")


def _run(tmp_path: Path, **sandbox: object) -> tuple[object, _Sandbox]:
    for serial, name in check.DATA_FILES.items():
        path = tmp_path / serial / name
        path.parent.mkdir(parents=True)
        path.write_bytes(f"test_time_second,voltage_volt\n0,3.0\n# {serial}\n".encode())
    stand_in = _Sandbox(tmp_path, **sandbox)  # type: ignore[arg-type]
    run = object.__new__(check.Run)  # without the real workspace and client
    run.root = tmp_path
    run.token = "not-a-token"
    run.network = check.Network(_Opener())
    run.client = stand_in
    run.ws = stand_in
    run.md5s = {serial: check.md5(check.data_file(tmp_path, serial).read_bytes()) for serial in check.DATA_FILES}
    run.records = []
    run.published = SimpleNamespace(record_id="1")
    return run, stand_in


def test_a_new_version_keeps_the_copy_of_a_data_file_deleted_locally(tmp_path: Path) -> None:
    run, sandbox = _run(tmp_path, deleted="keep")
    c02 = check.data_file(tmp_path, "C02").read_bytes()

    outcome = run.new_version()

    assert "copy of C02" in outcome
    assert run.published.record_id == "2"
    assert sandbox.versions["2"][NAMES["C02"]] == sandbox.versions["1"][NAMES["C02"]]
    assert sandbox.versions["2"][NAMES["C03"]] != sandbox.versions["1"][NAMES["C03"]]
    assert check.data_file(tmp_path, "C02").read_bytes() == c02  # put back for the steps that follow


def test_a_new_version_refused_for_a_data_file_deleted_locally_fails_the_step(tmp_path: Path) -> None:
    run, sandbox = _run(tmp_path, deleted="refuse")

    with pytest.raises(check.CheckFailed, match="C02 deleted locally, the new version failed after 0 requests"):
        run.new_version()

    assert list(sandbox.versions) == ["1"]
    assert check.data_file(tmp_path, "C02").exists()


def test_a_new_version_that_renames_a_file_that_did_not_change_fails_the_step(tmp_path: Path) -> None:
    run, _sandbox = _run(tmp_path, deleted="keep", rename=True)

    with pytest.raises(check.CheckFailed, match="renamed in the new version: .*C01: cycling.csv -> ffff-cycling.csv"):
        run.new_version()
