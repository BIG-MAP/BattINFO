"""scripts/zenodo_sandbox_check.py: the release checklist's Zenodo sandbox run, which never runs here.

The script deposits to sandbox.zenodo.org with a real token, so it is run by
hand. These tests check what keeps it safe and what it checks, without running
a single step: it refuses to start under pytest or in CI, no workflow runs it,
its network guard lets requests reach the sandbox only, and its check of a
deposit's data files. Nothing here reaches the network.
"""

from __future__ import annotations

import importlib.util
import sys
import urllib.error
import urllib.request
from pathlib import Path

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
