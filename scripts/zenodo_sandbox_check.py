"""The Zenodo sandbox run of the release checklist: run by hand, never in tests or CI.

Run it against a release candidate installed in a clean environment, with a
token made on sandbox.zenodo.org. It builds a small workspace in a new folder
and deposits it to the Zenodo sandbox the ways a user does, checking after
each step what the deposit holds and what the records say:

1. Same-named files. Three tests whose data files share a name, two of them
   differing only in case, go into one draft. Each file must be in the
   deposit once, with its own md5, under a name no other file has (ignoring
   case).
2. Draft then publish. Publishing the draft keeps its record and its files.
3. A retry. A new version whose run stops part-way (this script fails the
   upload of battinfo.json once, on purpose) is finished by the same call
   run again: the same draft, no second new version, every file there.
4. A new version, made after one data file changed and another was deleted
   locally. The changed file goes up again, the deleted one keeps the copy
   the version before holds, and the files that did not change keep the
   names they had, in the same concept.
5. Draft then submit. After a sandbox draft, ws.submit() refuses the
   records' local paths before anything is sent, and with
   allow_local_files=True it sends neither a sandbox URL nor a DOI. No
   registry is contacted: this script takes the submissions instead.
6. Sandbox then production. The sandbox runs leave the dataset records and
   the zenodo.org state file (.battinfo/zenodo.json) alone. A deposit to
   zenodo.org then begins by creating a record of its own: this script stops
   that first request, and every other request to zenodo.org, before it is
   sent. A deposit to zenodo.org from a record pointing at a sandbox file the
   workspace has no local copy of is refused before any request, and so is a
   batch upload to zenodo.org.

The script only ever sends requests to sandbox.zenodo.org: any other request
is stopped before it is sent, and fails the step that made it unless that
step checks how a deposit to zenodo.org begins. It drops ZENODO_API_TOKEN and
ZENODO_TOKEN from its environment, and it will not run in CI or under pytest,
because it needs a real sandbox token and makes real sandbox records.

Usage::

    ZENODO_SANDBOX_TOKEN=<token> python scripts/zenodo_sandbox_check.py [--workdir DIR]

It prints each step's result and the sandbox records it made, and exits with
status 1 at the first step that fails. The workspace stays in the folder it
names, for a look at what was deposited.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import warnings
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SANDBOX_HOST = "sandbox.zenodo.org"
PRODUCTION_HOST = "zenodo.org"
# Tokens this script must never use, removed from its environment at start.
PRODUCTION_TOKENS = ("ZENODO_API_TOKEN", "ZENODO_TOKEN")
CREATORS = [{"name": "Check, BattINFO Release", "affiliation": "BattINFO release checklist"}]
METADATA = {
    "title": "BattINFO release check: Zenodo sandbox run",
    "description": "Made by scripts/zenodo_sandbox_check.py from the BattINFO repository. Safe to delete.",
    "keywords": ["BattINFO release check"],
    "community": None,
}
# Three tests' data files: two named cycling.csv, and one whose name differs from those only in case.
DATA_FILES = {"C01": "cycling.csv", "C02": "cycling.csv", "C03": "CYCLING.csv"}
# Keys under which a record gives a data location.
LOCATION_KEYS = ("access_url", "content_url", "download_url", "source_url", "record_url")


class CheckFailed(Exception):
    """A step found something other than what it checks for."""


class RefusedRequest(OSError):
    """A request to a host other than the Zenodo sandbox, stopped before it was sent."""


class FailedOnPurpose(urllib.error.HTTPError):
    """The upload this script fails once, to make a run stop part-way."""


class Network:
    """Stands in for urlopen: logs each request, lets through only those to the sandbox.

    A request to any other host is stopped before it is sent. It goes into
    ``refused``, which fails the step, unless ``expect_production`` is set
    and the host is zenodo.org: then it goes into ``stopped``, for a step
    that checks how a deposit there would begin. ``fail_upload`` names a file
    whose next upload (a PUT ending in its name) fails with HTTP 503, once.
    """

    def __init__(self, urlopen: Callable[..., Any]) -> None:
        self._urlopen = urlopen
        self.requests: list[tuple[str, str]] = []
        self.refused: list[tuple[str, str]] = []
        self.stopped: list[tuple[str, str]] = []
        self.expect_production = False
        self.fail_upload: str | None = None

    def __call__(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(request, urllib.request.Request):
            method, url = request.get_method(), request.full_url
        else:
            method, url = "GET", str(request)
        self.requests.append((method, url))
        host = urllib.parse.urlsplit(url).hostname or ""
        if host != SANDBOX_HOST:
            if self.expect_production and host == PRODUCTION_HOST:
                self.stopped.append((method, url))
            else:
                self.refused.append((method, url))
            raise RefusedRequest(f"zenodo_sandbox_check stopped a request to {host or url}: only {SANDBOX_HOST}")
        if self.fail_upload and method == "PUT" and urllib.parse.unquote(url).endswith("/" + self.fail_upload):
            self.fail_upload = None
            raise FailedOnPurpose(url, 503, "failed on purpose by zenodo_sandbox_check", None, io.BytesIO(b""))  # type: ignore[arg-type]
        return self._urlopen(request, *args, **kwargs)

    def since(self, mark: int) -> list[tuple[str, str]]:
        return self.requests[mark:]


def expect(condition: object, message: str) -> None:
    if not condition:
        raise CheckFailed(message)


def md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()  # noqa: S324 - Zenodo's file checksum


# ── The workspace ─────────────────────────────────────────────────────────────


def build_workspace(battinfo: Any, root: Path) -> Any:
    """A cell spec, three cells and one cycling test per cell, each with its own data file."""
    ws = battinfo.workspace(root, registry_url=None)
    ws.license("cc-by-4.0")
    spec = battinfo.CellSpec(
        manufacturer="BattINFO release check", model="SANDBOX-2032", format="coin", chemistry="li-ion"
    )
    ws.add("cell", spec=spec, serial_numbers=list(DATA_FILES))
    for serial, name in DATA_FILES.items():
        path = root / serial / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"test_time_second,voltage_volt,current_ampere\n0,3.0,0\n60,3.5,0.001\n# {serial}\n".encode())
        ws.add("test", type="cycling", cell=serial, data=f"{serial}/{name}")
    ws.save()
    return ws


def data_file(root: Path, serial: str) -> Path:
    return root / serial / DATA_FILES[serial]


def dataset_records(root: Path) -> list[Path]:
    return sorted((root / ".battinfo" / "records" / "dataset").glob("*.json"))


def locations(root: Path) -> list[str]:
    """Every data location the saved dataset records give."""
    found: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in LOCATION_KEYS and isinstance(value, str):
                    found.append(value)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for path in dataset_records(root):
        walk(json.loads(path.read_text(encoding="utf-8")))
    return found


def state(root: Path, name: str) -> dict[str, Any] | None:
    path = root / ".battinfo" / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# ── What the sandbox holds ────────────────────────────────────────────────────


def deposit_files(client: Any, record_id: str) -> dict[str, str]:
    """The files of a sandbox deposit, as {name: md5}."""
    listing = client.list_files(record_id)
    files: dict[str, str] = {}
    for entry in listing:
        name = str(entry.get("filename") or entry.get("key") or "")
        checksum = str(entry.get("checksum") or "")
        files[name] = checksum.removeprefix("md5:")
    return files


def check_data_files(files: dict[str, str], expected: dict[str, str]) -> list[str]:
    """Each expected data file (serial -> md5) is in *files* once, under its own name.

    Returns the deposit names of the data files, in the order of *expected*.
    """
    names: list[str] = []
    for serial, checksum in expected.items():
        holders = [name for name, held in files.items() if held == checksum]
        expect(
            len(holders) == 1,
            f"{serial}'s data file (md5 {checksum}) is in the deposit {len(holders)} times: {holders}",
        )
        local_name = DATA_FILES[serial]
        expect(
            re.fullmatch(rf"(?:[0-9a-f]+-)?{re.escape(local_name)}", holders[0]),
            f"{serial}'s data file is in the deposit as {holders[0]!r}, not as {local_name!r} with an optional prefix",
        )
        names.append(holders[0])
    expect(
        len({name.casefold() for name in names}) == len(names), f"two data files share a name, ignoring case: {names}"
    )
    return names


def check_sandbox_left_records_alone(root: Path) -> None:
    on_zenodo = [
        location
        for location in locations(root)
        if (urllib.parse.urlsplit(location).hostname or "").endswith("zenodo.org")
    ]
    expect(not on_zenodo, f"a sandbox deposit changed the dataset records, which now name {on_zenodo}")
    expect(
        state(root, "zenodo.json") is None, "a sandbox deposit wrote .battinfo/zenodo.json, the zenodo.org state file"
    )


# ── The steps ─────────────────────────────────────────────────────────────────


class Run:
    def __init__(self, battinfo: Any, root: Path, token: str, network: Network) -> None:
        from battinfo.zenodo import ZenodoClient

        self.battinfo = battinfo
        self.root = root
        self.token = token
        self.network = network
        self.client = ZenodoClient(token=token, sandbox=True)
        self.ws = build_workspace(battinfo, root)
        self.md5s = {serial: md5(data_file(root, serial).read_bytes()) for serial in DATA_FILES}
        self.records: list[str] = []

    def deposit(self, *, publish: bool) -> Any:
        result = self.ws.zenodo(sandbox=True, publish=publish, token=self.token, creators=CREATORS, **METADATA)
        if result.record_id not in self.records:
            self.records.append(result.record_id)
        return result

    def sandbox_state(self) -> dict[str, Any]:
        found = state(self.root, "zenodo-sandbox.json")
        expect(found is not None, "no .battinfo/zenodo-sandbox.json after a sandbox deposit")
        assert found is not None
        expect(
            found.get("environment") == "sandbox",
            f"the sandbox state names the environment {found.get('environment')!r}",
        )
        return found

    def same_named_files(self) -> str:
        draft = self.deposit(publish=False)
        expect(not draft.published, "the first deposit was published, not left as a draft")
        names = check_data_files(deposit_files(self.client, draft.record_id), self.md5s)
        check_sandbox_left_records_alone(self.root)
        expect(self.sandbox_state().get("published") is False, "the sandbox state does not record a draft")
        self.draft = draft
        return f"draft {draft.record_id} holds {', '.join(names)}"

    def draft_then_publish(self) -> str:
        published = self.deposit(publish=True)
        expect(published.published, "the run with publish=True did not publish")
        expect(
            published.record_id == self.draft.record_id,
            f"it published {published.record_id}, not the draft {self.draft.record_id}",
        )
        check_data_files(deposit_files(self.client, published.record_id), self.md5s)
        recorded = self.sandbox_state()
        expect(
            recorded.get("published") is True and recorded.get("record_id") == published.record_id,
            f"the state says {recorded}",
        )
        check_sandbox_left_records_alone(self.root)
        self.published = published
        return f"record {published.record_id} published, {published.doi}"

    def retry(self) -> str:
        path = data_file(self.root, "C01")
        path.write_bytes(path.read_bytes() + b"120,3.6,0.001\n")
        self.md5s["C01"] = md5(path.read_bytes())
        self.network.fail_upload = "battinfo.json"
        try:
            stopped_run = self.deposit(publish=True)
        except Exception as exc:  # noqa: BLE001 - any failure will do; the retry is what is checked
            failure = f"{type(exc).__name__}: {exc}"
        else:
            expect(not stopped_run.published, "the run published although the upload of battinfo.json failed")
            failure = f"it left draft {stopped_run.record_id} unpublished"
        expect(self.network.fail_upload is None, "the run stopped before it uploaded battinfo.json")
        stopped = self.sandbox_state()
        draft_id = str(stopped.get("record_id"))
        expect(
            stopped.get("published") is False and draft_id != self.published.record_id,
            f"after the failed run the state says {stopped}",
        )

        mark = len(self.network.requests)
        finished = self.deposit(publish=True)
        expect(
            finished.published and finished.record_id == draft_id,
            f"the retry made {finished.record_id}, not the draft {draft_id}",
        )
        again = [
            url for method, url in self.network.since(mark) if method == "POST" and url.endswith("/actions/newversion")
        ]
        expect(not again, f"the retry made another new version: {again}")
        check_data_files(deposit_files(self.client, finished.record_id), self.md5s)
        check_sandbox_left_records_alone(self.root)
        self.published = finished
        return f"the run stopped ({failure[:80]}); the retry published draft {finished.record_id}"

    def new_version(self) -> str:
        # One data file changed and another deleted locally. The new version
        # carries the changed file and keeps the copy of the deleted one that
        # the version before holds, each file under the name it had.
        concept = self.sandbox_state().get("concept_record_id")
        before = check_data_files(deposit_files(self.client, self.published.record_id), self.md5s)
        changed = data_file(self.root, "C03")
        changed.write_bytes(changed.read_bytes() + b"180,3.7,0.001\n")
        self.md5s["C03"] = md5(changed.read_bytes())
        gone = data_file(self.root, "C02")
        kept = gone.read_bytes()
        gone.unlink()
        mark = len(self.network.requests)
        try:
            version = self.deposit(publish=True)
        except Exception as exc:  # noqa: BLE001 - reported as the step's failure
            sent = len(self.network.since(mark))
            raise CheckFailed(
                f"with C03 changed and C02 deleted locally, the new version failed after {sent} requests: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        finally:
            gone.write_bytes(kept)  # back for the steps that follow
        expect(
            version.published and version.record_id != self.published.record_id,
            f"no new version was published: {version.record_id}",
        )
        after = check_data_files(deposit_files(self.client, version.record_id), self.md5s)
        kept_names = [(serial, old, new) for serial, old, new in zip(DATA_FILES, before, after) if serial != "C03"]
        moved = [f"{serial}: {old} -> {new}" for serial, old, new in kept_names if old != new]
        expect(not moved, f"files that did not change were renamed in the new version: {moved}")
        recorded = self.sandbox_state()
        expect(
            recorded.get("record_id") == version.record_id and recorded.get("concept_record_id") == concept,
            f"the new version is not recorded under the same concept ({concept}): the state says {recorded}",
        )
        check_sandbox_left_records_alone(self.root)
        self.published = version
        return (
            f"version {version.record_id} holds the changed C03, the copy of C02 (deleted locally) "
            "and C01, the last two under the names they had"
        )

    def draft_then_submit(self) -> str:
        from battinfo.ws import SubmitError

        draft = self.deposit(publish=False)
        expect(not draft.published, "the deposit was published, not left as a draft")
        dois = {result for result in (self.published.doi, draft.doi) if result}
        registry = dict(
            registry_url="https://registry.invalid", api_key="check", workspace_id="check", publisher_id="check"
        )
        with submissions(self.battinfo) as sent:
            mark = len(self.network.requests)
            try:
                self.ws.submit(resume=False, **registry)
            except SubmitError:
                pass
            else:
                raise CheckFailed("ws.submit() sent records whose data locations are local paths")
            expect(not sent and not self.network.since(mark), "the refused submit sent something")
            self.ws.submit(resume=False, allow_local_files=True, **registry)
        payloads = json.dumps(sent)
        expect(sent, "ws.submit(allow_local_files=True) sent nothing")
        expect(SANDBOX_HOST not in payloads, "the submission names a sandbox URL")
        leaked = sorted(doi for doi in dois if doi in payloads)
        expect(not leaked, f"the submission carries the sandbox DOI(s) {leaked}")
        expect("citation_doi" not in payloads, "the submission carries a citation DOI")
        return f"draft {draft.record_id}; {len(sent)} submissions with no sandbox URL or DOI"

    def sandbox_then_production(self) -> str:
        from battinfo.zenodo import upload_zenodo_package

        check_sandbox_left_records_alone(self.root)

        # A deposit to zenodo.org from this workspace, with its requests stopped
        # before they are sent: it must begin by creating a record of its own
        # there, not by continuing anything the sandbox runs made.
        mark = len(self.network.requests)
        self.network.expect_production = True
        try:
            self.ws.zenodo(sandbox=False, publish=False, token="not-a-real-token", creators=CREATORS, **METADATA)
        except Exception as exc:  # noqa: BLE001 - its first request is stopped
            ended = f"{type(exc).__name__}: {exc}"
        else:
            raise CheckFailed("a deposit to zenodo.org went through, although its requests were stopped")
        finally:
            self.network.expect_production = False
        made = self.network.since(mark)
        expect(made, f"the zenodo.org deposit was refused before any request: {ended}")
        expect(
            made[0] == ("POST", f"https://{PRODUCTION_HOST}/api/deposit/depositions"),
            f"the zenodo.org deposit began with {made[0]}, not by creating a record of its own",
        )
        elsewhere = [url for _method, url in made if urllib.parse.urlsplit(url).hostname != PRODUCTION_HOST]
        expect(not elsewhere, f"the zenodo.org deposit sent requests elsewhere: {elsewhere}")
        expect(state(self.root, "zenodo.json") is None, "the stopped zenodo.org deposit wrote .battinfo/zenodo.json")
        check_sandbox_left_records_alone(self.root)

        # A record pointing at a file in a sandbox record that this workspace
        # has no local file for: a deposit to zenodo.org refuses it before any
        # request, since sandbox records do not last.
        [first, *_] = dataset_records(self.root)
        original = first.read_text(encoding="utf-8")
        record = json.loads(original)
        unknown = f"https://{SANDBOX_HOST}/records/{self.published.record_id}/files/not-deposited-from-here.csv"
        record["dataset"]["distributions"][0]["content_url"] = unknown
        first.write_text(json.dumps(record, indent=2), encoding="utf-8")
        mark = len(self.network.requests)
        try:
            self.ws.zenodo(sandbox=False, publish=False, token="not-a-real-token", creators=CREATORS, **METADATA)
        except Exception as exc:  # noqa: BLE001
            refusal = f"{type(exc).__name__}: {exc}"
        else:
            raise CheckFailed("a deposit to zenodo.org from a record on a sandbox file went through")
        finally:
            first.write_text(original, encoding="utf-8")
        expect(not self.network.since(mark), f"the zenodo.org deposit sent requests: {self.network.since(mark)}")
        expect(unknown in refusal, f"the refusal does not name the sandbox file: {refusal}")
        expect(state(self.root, "zenodo.json") is None, "the refused deposit wrote .battinfo/zenodo.json")

        staging = self.root / "batch-staging"
        staging.mkdir(exist_ok=True)
        mark = len(self.network.requests)
        try:
            upload_zenodo_package(staging, CREATORS, token="not-a-real-token", sandbox=False)
        except ValueError as exc:
            expect("sandbox" in str(exc), f"the batch upload was refused for another reason: {exc}")
        else:
            raise CheckFailed("a batch upload to zenodo.org went through")
        expect(not self.network.since(mark), "the batch upload to zenodo.org sent requests")
        return (
            "a zenodo.org deposit begins with a record of its own (its first request, stopped here); "
            "a record on a sandbox file it has no local copy of, and a batch upload to zenodo.org, "
            "were refused before any request"
        )


@contextmanager
def submissions(battinfo: Any) -> Iterator[list[dict]]:
    """Take the submissions ws.submit() makes instead of sending them to a registry."""
    import battinfo.api as api

    sent: list[dict] = []

    def take(payload: dict, **_kwargs: Any) -> dict:
        sent.append(json.loads(json.dumps(payload)))
        return {"status": "ok", "status_code": 200, "response": {"status": "validated", "resources": []}}

    original = api.submit_publication_package
    api.submit_publication_package = take  # type: ignore[assignment]
    try:
        yield sent
    finally:
        api.submit_publication_package = original


STEPS = (
    ("Same-named files", "same_named_files"),
    ("Draft then publish", "draft_then_publish"),
    ("A retry", "retry"),
    ("A new version", "new_version"),
    ("Draft then submit", "draft_then_submit"),
    ("Sandbox then production", "sandbox_then_production"),
)


def refuse_to_run_here() -> str | None:
    """Why this script will not run in this process, or None."""
    if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
        return "it does not run in CI: it needs a sandbox token and makes real sandbox records."
    if "pytest" in sys.modules or os.environ.get("PYTEST_CURRENT_TEST"):
        return "it does not run under pytest: it makes real sandbox records."
    if not os.environ.get("ZENODO_SANDBOX_TOKEN"):
        return (
            "set ZENODO_SANDBOX_TOKEN to a token made on sandbox.zenodo.org (scopes deposit:write and deposit:actions)."
        )
    return None


def guard_network() -> Network:
    """Route every urlopen in urllib and battinfo through a :class:`Network`."""
    import battinfo.api
    import battinfo.validate.jsonld
    import battinfo.zenodo  # noqa: F401 - loaded so its urlopen is guarded too

    real = urllib.request.urlopen
    network = Network(real)
    urllib.request.urlopen = network  # type: ignore[assignment]
    for name, module in list(sys.modules.items()):
        if (name == "battinfo" or name.startswith("battinfo.")) and getattr(module, "urlopen", None) is real:
            module.urlopen = network  # type: ignore[attr-defined]
    return network


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--workdir", type=Path, help="an empty or new folder for the workspace (default: a new temporary one)"
    )
    args = parser.parse_args(argv)

    reason = refuse_to_run_here()
    if reason:
        print(f"zenodo_sandbox_check: {reason}", file=sys.stderr)
        return 2
    for name in PRODUCTION_TOKENS:
        os.environ.pop(name, None)
    token = os.environ["ZENODO_SANDBOX_TOKEN"]
    if args.workdir:
        root = args.workdir.resolve()
        if root.exists() and any(root.iterdir()):
            print(f"zenodo_sandbox_check: {root} is not empty; give an empty or new folder.", file=sys.stderr)
            return 2
        root.mkdir(parents=True, exist_ok=True)
    else:
        root = Path(tempfile.mkdtemp(prefix="battinfo-sandbox-check-"))

    import battinfo

    network = guard_network()
    print(f"Zenodo sandbox check of battinfo {battinfo.__version__} ({Path(battinfo.__file__).parent})")
    print(f"Workspace: {root}\n")
    run = Run(battinfo, root, token, network)
    for number, (title, method) in enumerate(STEPS, start=1):
        print(f"{number}. {title}")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                outcome = getattr(run, method)()
                expect(not network.refused, f"requests to other hosts were refused: {network.refused}")
            except CheckFailed as exc:
                print(f"   FAIL: {exc}")
                return _finish(run, ok=False)
            except Exception as exc:  # noqa: BLE001 - report it as the step's failure
                print(f"   FAIL: {type(exc).__name__}: {exc}")
                return _finish(run, ok=False)
        for warning in caught:
            print(f"   warning: {str(warning.message).splitlines()[0]}")
        print(f"   PASS: {outcome}")
    return _finish(run, ok=True)


def _finish(run: Run, *, ok: bool) -> int:
    print()
    print("All six steps passed." if ok else "The check failed.")
    if run.records:
        print("Sandbox records made (sandbox.zenodo.org clears them from time to time):")
        for record_id in run.records:
            print(f"  https://{SANDBOX_HOST}/records/{record_id}")
    print(f"Workspace kept at {run.root}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
