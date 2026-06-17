"""Tests for the AuthoringWorkspace UX surface (battinfo.ws).

These cover the workspace ergonomics added for the PhD-student/lab-engineer
experience: friendly test-kind validation, multi-format convert detection,
the login/credentials flow (with graceful degradation), and the one-call
publish/discovery helpers.  All tests run offline — any registry calls are
monkeypatched.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.ws import (  # noqa: E402
    AuthoringWorkspace,
    _normalize_test_kind,
    _test_kind_values,
)


@pytest.fixture(autouse=True)
def _clean_battinfo_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate BATTINFO_* env vars so login() tests don't leak identity across tests."""
    for var in ("BATTINFO_API_KEY", "BATTINFO_WORKSPACE_ID", "BATTINFO_PUBLISHER_ID",
                "BATTINFO_REGISTRY_URL", "BATTINFO_ADMIN_TOKEN"):
        monkeypatch.delenv(var, raising=False)


# ── test-kind validation (T1.3) ───────────────────────────────────────────────

def test_normalize_test_kind_canonical() -> None:
    assert _normalize_test_kind("cycling") == "cycling"
    assert _normalize_test_kind("Cycling") == "cycling"
    assert _normalize_test_kind("EIS") == "eis"


def test_normalize_test_kind_separators() -> None:
    assert _normalize_test_kind("rate capability") == "rate_capability"
    assert _normalize_test_kind("rate-capability") == "rate_capability"


def test_normalize_test_kind_aliases() -> None:
    assert _normalize_test_kind("calendar_aging") == "calendar_ageing"   # American
    assert _normalize_test_kind("rate") == "rate_capability"
    assert _normalize_test_kind("cycle") == "cycling"


def test_normalize_test_kind_invalid_lists_values() -> None:
    with pytest.raises(ValueError) as exc:
        _normalize_test_kind("thermal")
    msg = str(exc.value)
    assert "not a valid test kind" in msg
    # Error must enumerate real values from the enum.
    assert "cycling" in msg and "calendar_ageing" in msg


def test_test_kind_values_match_enum() -> None:
    from battinfo.bundle import BatteryTestType
    assert set(_test_kind_values()) == {m.value for m in BatteryTestType}


def test_add_test_with_bad_type_raises_before_touching_files(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    with pytest.raises(ValueError, match="not a valid test kind"):
        ws.add("test", type="bogus-kind", cell="S1", data="x.csv")


def test_add_test_kind_alias_still_accepted(tmp_path: Path) -> None:
    # kind= remains a backward-compat alias for type=.
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    with pytest.raises(ValueError, match="not a valid test kind"):
        ws.add("test", kind="nonsense", cell="S1", data="x.csv")


def test_add_test_without_type_or_spec_raises(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    with pytest.raises(ValueError, match="requires type"):
        ws.add("test", type="", datasets="bdf/*.csv")


# ── credentials + login (T1.1) ────────────────────────────────────────────────

def test_setup_creates_credentials_and_gitignore(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    cred = ws.setup()
    assert cred.exists()
    assert "BATTINFO_API_KEY" in cred.read_text(encoding="utf-8")
    gitignore = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ".battinfo/credentials" in gitignore


def test_set_credentials_merges_without_clobbering(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    ws.setup()
    # Pre-seed an unrelated credential the merge must preserve.
    cred = ws._credentials_path()
    cred.write_text(cred.read_text(encoding="utf-8").replace(
        "R2_BUCKET              = battinfo-public",
        "R2_BUCKET              = my-private-bucket",
    ), encoding="utf-8")

    ws._set_credentials({"BATTINFO_API_KEY": "secret-key-123"})
    text = cred.read_text(encoding="utf-8")
    assert "secret-key-123" in text
    assert "my-private-bucket" in text  # untouched


def _fake_urlopen_returning(profile: dict):
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(profile).encode("utf-8")

    def _open(req, timeout=0):  # noqa: ARG001
        return _Resp()

    return _open


def test_login_uses_registry_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.request

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        _fake_urlopen_returning({
            "publisher_id": "alice-lab",
            "workspace_id": "alice-workspace",
            "display_name": "Alice Researcher",
        }),
    )
    ws = AuthoringWorkspace(root=tmp_path, registry_url="https://registry.example")
    result = ws.login(api_key="key-abc")
    assert result["workspace_id"] == "alice-workspace"
    assert result["publisher_id"] == "alice-lab"
    cred = ws._credentials_path().read_text(encoding="utf-8")
    assert "alice-workspace" in cred and "key-abc" in cred


def test_login_degrades_gracefully_without_me_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import urllib.request

    def _boom(req, timeout=0):  # noqa: ARG001
        raise OSError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    ws = AuthoringWorkspace(root=tmp_path, registry_url="https://registry.example")
    result = ws.login(api_key="key-xyz")
    # Falls back to defaults; key is still saved.
    assert result["workspace_id"] == "battinfo-records"
    assert result["publisher_id"] == "battinfo-authoring"
    assert "key-xyz" in ws._credentials_path().read_text(encoding="utf-8")


def test_login_rejects_empty_key(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    with pytest.raises(ValueError, match="api_key is required"):
        ws.login(api_key="")


# ── discovery helpers (T5.2/T5.3) — must not raise ─────────────────────────────

def test_commands_runs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    ws.commands()
    out = capsys.readouterr().out
    assert "ws.convert()" in out and "ws.publish" in out


def test_quickstart_runs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    ws.quickstart()
    out = capsys.readouterr().out
    assert "ws.login" in out and "ws.convert()" in out and "ws.publish" in out


def test_bdf_columns_lists_canonical_names(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    cols = ws.bdf_columns()
    assert "voltage_volt" in cols and "current_ampere" in cols


# ── convert() guidance path (T1.2) ─────────────────────────────────────────────

def test_convert_no_files_prints_help(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pytest.importorskip("bdf")
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    result = ws.convert()
    assert result == []
    out = capsys.readouterr().out
    assert "Auto-detected" in out and ".ndax" in out


def test_convert_flags_unsupported_arbin(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    pytest.importorskip("bdf")
    (tmp_path / "run1.res").write_text("dummy", encoding="utf-8")
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    ws.convert()
    out = capsys.readouterr().out
    assert "run1.res" in out and "Arbin" in out


# ── convert_csv() (T4.2) ───────────────────────────────────────────────────────

def test_convert_csv_remaps_columns(tmp_path: Path) -> None:
    pd = pytest.importorskip("pandas")
    src = tmp_path / "maccor.csv"
    pd.DataFrame({"Cycle": [1, 2], "Voltage(V)": [3.7, 3.6]}).to_csv(src, index=False)

    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    out = ws.convert_csv(
        src,
        hints={"Cycle": "cycle_count", "Voltage(V)": "voltage_volt"},
        validate=False,
    )
    assert out.exists()
    written = pd.read_csv(out)
    assert "cycle_count" in written.columns and "voltage_volt" in written.columns


# ── submit() _glob ordering regression (latent NameError) ──────────────────────

def test_submit_does_not_crash_on_cell_spec_glob(tmp_path: Path) -> None:
    """Regression: `_glob` was referenced in the cell-spec loop before its
    definition, so ws.submit() raised NameError on the default publish path
    whenever the examples dir existed.  It must now return cleanly."""
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    # Make the examples dir exist so submit() proceeds past its early return,
    # but leave the per-type subdirs empty so no network call is attempted.
    (ws._records_root / "examples").mkdir(parents=True, exist_ok=True)
    result = ws.submit(
        registry_url="https://registry.example",
        api_key="k",
        workspace_id="w",
        publisher_id="p",
    )
    assert result == []


# ── unified search(type=...) + load()/cell= for existing instances ─────────────

_REG_CELL = {
    "id": "https://w3id.org/battinfo/cell/abcd-1234-ef56-7890",
    "serial_number": "duracell-mn2400-2026-02-tpejqj",
    "batch_id": "2026-02",
    "cell_spec_id": "https://w3id.org/battinfo/spec/avzy-5vjx-5nkj-jgsj",
    "manufacturer": "Duracell",
    "model": "MN2400",
    "title": "duracell-mn2400-2026-02-tpejqj",
}


def test_add_cell_reuses_provided_iris(tmp_path: Path) -> None:
    """serial_numbers= + iris= (parallel) bakes the given IRIs into the records."""
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    (tmp_path / "d.cell-spec.json").write_text(
        '{"manufacturer":"Duracell","model":"MN2400","format":"cylindrical",'
        '"chemistry":"Zn-MnO2","size_code":"R03","iec_code":"LR03",'
        '"properties":{"nominal_voltage":{"value":1.5,"unit":"V"}}}',
        encoding="utf-8",
    )
    spec = ws.load(tmp_path / "d.cell-spec.json")
    serials = ["duracell-mn2400-2026-02-tpejqj", "duracell-mn2400-2026-02-666h1s"]
    iris = [
        "https://w3id.org/battinfo/cell/abcd-1234-ef56-7890",
        "https://w3id.org/battinfo/cell/bd2e-xbd0-6rt5-5dhz",
    ]
    cells = ws.add("cell", spec=spec, serial_numbers=serials, iris=iris)
    assert [c.id for c in cells] == iris
    res = ws.save()
    saved = sorted(
        __import__("json").loads(p.read_text(encoding="utf-8"))["cell_instance"]["id"]
        for p in (ws._records_root / "examples" / "cell-instance").glob("*.json")
    )
    assert saved == sorted(iris), "saved records must carry the provided IRIs"
    assert len(res["cell_instances"]) == 2


def test_add_cell_iris_length_mismatch_raises(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    (tmp_path / "d.cell-spec.json").write_text(
        '{"manufacturer":"X","model":"Y","format":"pouch","chemistry":"nmc"}', encoding="utf-8"
    )
    spec = ws.load(tmp_path / "d.cell-spec.json")
    with pytest.raises(ValueError, match="iris must match"):
        ws.add("cell", spec=spec, serial_numbers=["a", "b"], iris=["only-one"])


def _write_spec(ws, tmp_path):
    (tmp_path / "d.cell-spec.json").write_text(
        '{"manufacturer":"X","model":"Y","format":"pouch","chemistry":"nmc"}', encoding="utf-8"
    )
    return ws.load(tmp_path / "d.cell-spec.json")


def test_add_cell_names_vs_serials_are_distinct(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    spec = _write_spec(ws, tmp_path)
    n = ws.add("cell", spec=spec, names=["lab-A"])
    assert n[0].name == "lab-A" and n[0].serial_number is None
    s = ws.add("cell", spec=spec, serial_numbers=["SN-1"])
    assert s[0].serial_number == "SN-1"
    b = ws.add("cell", spec=spec, names=["lab-B"], serial_numbers=["SN-2"])
    assert b[0].name == "lab-B" and b[0].serial_number == "SN-2"


def test_cell_name_persists_in_record_without_serial(tmp_path: Path) -> None:
    import json as _json
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    spec = _write_spec(ws, tmp_path)
    ws.add("cell", spec=spec, names=["lab-tpejqj"])
    ws.save()
    rec = _json.loads(
        next((ws._records_root / "examples" / "cell-instance").glob("*.json")).read_text(encoding="utf-8")
    )["cell_instance"]
    assert rec.get("name") == "lab-tpejqj"
    assert "serial_number" not in rec, "no serial should be persisted when none was given"


def test_add_cell_names_serials_length_mismatch_raises(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    spec = _write_spec(ws, tmp_path)
    with pytest.raises(ValueError, match="same length"):
        ws.add("cell", spec=spec, names=["a", "b"], serial_numbers=["only-one"])


def test_add_test_resolves_cell_by_name(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    spec = _write_spec(ws, tmp_path)
    ws.add("cell", spec=spec, names=["duracell-mn2400-2026-02-tpejqj"])
    (tmp_path / "f.csv").write_text("a,b\n0,1\n", encoding="utf-8")
    tests = ws.add("test", type="capacity_check", cell="tpejqj", data="f.csv")  # short-ID of the name
    assert len(tests) == 1
    res = ws.save()
    assert len(res["tests"]) == 1 and len(res["cell_instances"]) == 1


# ── JSON-LD validity (the @context must be accepted by strict 1.1 processors) ──


def test_records_context_has_no_iri_form_term_keys() -> None:
    """Regression: a term key containing '/' or ':' makes the whole context invalid
    under JSON-LD 1.1 ('term in form of IRI must expand to definition')."""
    ctx = json.loads(
        (ROOT / "src" / "battinfo" / "data" / "context" / "records.context.json")
        .read_text(encoding="utf-8")
    )["@context"]
    prefixes = {k for k, v in ctx.items() if isinstance(v, str) and v.endswith(("#", "/"))}
    offenders = [
        k for k in ctx
        if not k.startswith("@") and k not in prefixes and ("/" in k or ":" in k)
    ]
    assert not offenders, f"IRI-form term keys break JSON-LD 1.1: {offenders}"


def test_validate_jsonld_rejects_iri_form_term() -> None:
    from battinfo import validate_jsonld
    with pytest.raises(ValueError, match="not valid JSON-LD"):
        validate_jsonld({"@context": {"@version": 1.1, "Wh/kg": "https://w3id.org/emmo#X"},
                         "@graph": []})


def test_built_zenodo_jsonld_is_valid_and_carries_raw_provenance(tmp_path: Path) -> None:
    """ws.add('test', ..., raw=) attaches the original file as a 'raw' distribution,
    and the generated linked-data document is valid JSON-LD."""
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    spec = _write_spec(ws, tmp_path)
    ws.add("cell", spec=spec, names=["c1"])
    (tmp_path / "c1.bdf.csv").write_text("a,b\n0,1\n", encoding="utf-8")
    (tmp_path / "c1.ndax").write_bytes(b"RAW-INSTRUMENT-BYTES")  # original source
    ws.add("test", type="capacity_check", cell="c1",
           data="c1.bdf.csv", raw="c1.ndax")
    ws.save()

    # Dataset record carries both roles.
    ds = json.loads(
        next((ws._records_root / "examples" / "dataset").glob("*.json")).read_text(encoding="utf-8")
    )["dataset"]
    roles = {d.get("role") for d in ds["distributions"]}
    assert roles == {"processed", "raw"}

    # Building the deposit document validates JSON-LD internally; assert it returns
    # and that the raw original appears as a distribution with a provenance note.
    doc = ws._build_zenodo_jsonld(
        zenodo_record_id=1,
        prereserved_doi="10.5281/zenodo.1",
        record_url="https://sandbox.zenodo.org/records/1",
        data_filenames=["c1.bdf.csv", "c1.ndax"],
    )
    dataset_node = next(n for n in doc["@graph"] if "dcat:distribution" in n)
    names = {d["schema:name"] for d in dataset_node["dcat:distribution"]}
    assert {"c1.bdf.csv", "c1.ndax"} <= names
    raw_dist = next(d for d in dataset_node["dcat:distribution"] if d["schema:name"] == "c1.ndax")
    assert "schema:description" in raw_dist
    assert "prov:wasGeneratedBy" not in raw_dist  # raw is an input, not an output


def test_zenodo_jsonld_is_catalog_of_per_test_datasets(tmp_path: Path) -> None:
    """The record is a dcat:Catalog; each test result is its own dcat:Dataset
    grouping its own (processed + raw) distributions — not one flat bag."""
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    spec = _write_spec(ws, tmp_path)
    ws.add("cell", spec=spec, names=["c1", "c2"])
    for c in ("c1", "c2"):
        (tmp_path / f"{c}.bdf.csv").write_text("a,b\n0,1\n", encoding="utf-8")
        (tmp_path / f"{c}.ndax").write_bytes(b"RAW")
        ws.add("test", type="capacity_check", cell=c,
               data=f"{c}.bdf.csv", raw=f"{c}.ndax")
    ws.save()

    doc = ws._build_zenodo_jsonld(
        zenodo_record_id=1,
        prereserved_doi="10.5281/zenodo.1",
        record_url="https://sandbox.zenodo.org/records/1",
        data_filenames=["c1.bdf.csv", "c1.ndax", "c2.bdf.csv", "c2.ndax"],
    )
    graph = doc["@graph"]

    # Exactly one catalog, pointing to its member datasets.
    catalog = next(n for n in graph if "dcat:Catalog" in n.get("@type", []))
    members = {m["@id"] for m in catalog["dcat:dataset"]}
    assert len(members) == 2
    # The catalog itself carries no distributions (those live on the members).
    assert "dcat:distribution" not in catalog

    # Two member datasets, each with exactly its own two distributions.
    ds_nodes = [n for n in graph
                if "dcat:Dataset" in n.get("@type", []) and "dcat:distribution" in n]
    assert {n["@id"] for n in ds_nodes} == members
    for n in ds_nodes:
        names = {d["schema:name"] for d in n["dcat:distribution"]}
        # one processed + one raw, both for the SAME cell (a shared prefix)
        assert len(names) == 2
        stems = {nm.split(".")[0] for nm in names}
        assert len(stems) == 1, f"member mixes runs: {names}"
        assert n["dcterms:isPartOf"]["@id"] == "https://sandbox.zenodo.org/records/1"

    # Each test's hasOutput now resolves to a real member dataset node (no dangle).
    test_nodes = [n for n in graph if "BatteryTest" in n.get("@type", [])]
    for t in test_nodes:
        for out in t["hasOutput"]:
            assert out["@id"] in members


# ── "gold-standard" agent-completeness checks ──────────────────────────────────
# Each persona (no-dangle / PROV / schema.org) must be able to traverse the record
# without hitting a foreign predicate it has to give up on, or a reference that
# resolves to nothing. These operationalise the gold-standard goal as executable
# regression guards.

def _build_doc(tmp_path: Path) -> dict:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    spec = _write_spec(ws, tmp_path)
    ws.add("cell", spec=spec, names=["c1"])
    (tmp_path / "c1.bdf.csv").write_text("a,b\n0,1\n", encoding="utf-8")
    (tmp_path / "c1.ndax").write_bytes(b"RAW")
    ws.add("test", type="capacity_check", cell="c1", data="c1.bdf.csv", raw="c1.ndax")
    ws.save()
    return ws._build_zenodo_jsonld(
        zenodo_record_id=1,
        prereserved_doi="10.5281/zenodo.1",
        record_url="https://sandbox.zenodo.org/records/1",
        data_filenames=["c1.bdf.csv", "c1.ndax"],
        title="t", description="d",
        creators=[{"name": "A", "affiliation": "Org"}],
        license="CC-BY-4.0",
    )


def _refs(node, acc: set[str]) -> None:
    """Collect every @id value referenced anywhere under a node (depth-first)."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "@id" and isinstance(v, str):
                acc.add(v)
            else:
                _refs(v, acc)
    elif isinstance(node, list):
        for item in node:
            _refs(item, acc)


def test_no_dangling_internal_references(tmp_path: Path) -> None:
    """Every referenced battinfo IRI resolves to a node in the graph — including the
    remote cell spec, which appears as a typed stub rather than a bare dangling @id."""
    graph = _build_doc(tmp_path)["@graph"]
    node_ids = {n["@id"] for n in graph if "@id" in n}
    referenced: set[str] = set()
    for n in graph:
        _refs(n, referenced)
    internal = {r for r in referenced if r.startswith("https://w3id.org/battinfo/")}
    dangling = internal - node_ids
    assert not dangling, f"internal references with no node: {dangling}"


def test_prov_graph_is_self_complete(tmp_path: Path) -> None:
    """A PROV-only consumer reaches the cell, spec and output dataset of every test."""
    graph = _build_doc(tmp_path)["@graph"]
    node_ids = {n["@id"] for n in graph if "@id" in n}
    tests = [n for n in graph if "prov:Activity" in n.get("@type", [])
             and "BatteryTest" in n.get("@type", [])]
    assert tests
    for t in tests:
        used = {u["@id"] for u in t["prov:used"]}            # cell (+ spec if any)
        generated = {g["@id"] for g in t["prov:generated"]}  # output dataset(s)
        # The cell (also under hasTestObject) is always reachable via prov:used,
        # and the output dataset(s) via prov:generated — so PROV alone is complete.
        assert t["hasTestObject"]["@id"] in used
        assert generated and generated <= node_ids
        # If the test followed a spec, that spec is also a prov:used plan.
        if "dcterms:conformsTo" in t:
            assert t["dcterms:conformsTo"]["@id"] in used


def test_tier3_richness_structured_conditions_versioning_keywords_ror() -> None:
    """Structured test conditions, versioning, auto keywords, and ROR org ids."""
    rs = {
        "cell-spec": [{"cell_spec": {"id": "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-dddd",
                                    "name": "X", "model": "M", "manufacturer": {"name": "SINTEF"},
                                    "cell_format": "cylindrical", "chemistry": "nmc"}, "properties": {}}],
        "cell-instance": [{"cell_instance": {"id": "https://w3id.org/battinfo/cell/c1",
                                             "cell_spec_id": "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-dddd",
                                             "name": "c1"}}],
        "test": [{"test": {"id": "https://w3id.org/battinfo/test/t1",
                           "cell_id": "https://w3id.org/battinfo/cell/c1", "kind": "capacity_check",
                           "protocol_name": "CC", "dataset_ids": ["https://w3id.org/battinfo/dataset/d1"],
                           "protocol_id": "https://w3id.org/battinfo/spec/qhkt"}}],
        "test-protocol": [{"test_spec": {"id": "https://w3id.org/battinfo/spec/qhkt", "name": "CC",
                                         "kind": "capacity_check"},
                           "method": [{"mode": "group", "count": 50, "steps": [
                               {"mode": "cc", "direction": "discharge",
                                "setpoints": {"c_rate": {"value": 0.05, "unit": "A/Ah"}},
                                "termination": [{"quantity": "voltage", "direction": "below",
                                                 "value": 0.9, "unit": "V"}]}]}],
                           "conditions": {"temperature": {"value": 25, "unit": "degC"}}}],
        "dataset": [{"dataset": {"id": "https://w3id.org/battinfo/dataset/d1", "name": "d1",
                                 "distributions": [{"content_url": "f.csv", "encoding_format": "text/csv",
                                                    "role": "processed", "checksum": {"value": "a" * 64}}]}}],
    }
    doc = AuthoringWorkspace._assemble_zenodo_jsonld(
        rs, zenodo_record_id=0, prereserved_doi="10.5281/zenodo.1",
        record_url="https://zenodo.org/records/1", data_filenames=["f.csv"], title="T",
        creators=[{"name": "A", "affiliation": "SINTEF", "affiliation_ror": "01f677e56"}],
        version="2", is_version_of="https://zenodo.org/records/concept",
    )
    plan = next(n for n in doc["@graph"] if "prov:Plan" in (n.get("@type") or []))
    cat = next(n for n in doc["@graph"] if "dcat:Catalog" in (n.get("@type") or []))
    prov = next(n for n in doc["@graph"]
                if {"prov:Agent", "schema:Organization"} <= set(n.get("@type") or []))

    # The method is an EMMO process graph: a 50× IterativeWorkflow wrapping the CC step.
    group = plan["hasTask"][0]
    assert group["@type"] == "IterativeWorkflow"
    assert group["NumberOfIterations"]["hasNumericalPart"]["hasNumberValue"] == 50
    # Termination is emitted as an EMMO quantity under the step's domain-battery relation,
    # not as a schema:PropertyValue string (the controlled-vocabulary names resolve).
    term = group["hasTask"][0]["hasTerminationParameter"][0]
    assert term["@type"] == "LowerVoltageLimit"
    assert term["hasNumericalPart"]["hasNumberValue"] == 0.9
    assert term["hasMeasurementUnit"] == {"@id": "emmo:Volt"}
    prop = plan["hasProperty"][0]
    assert prop["@type"] == "ConventionalProperty"
    assert prop["hasNumericalPart"]["hasNumberValue"] == 25
    assert prop["rdfs:label"] == "temperature"
    assert "schema:additionalProperty" not in plan   # all names mapped → no fallback
    assert {"battery", "capacity_check", "cylindrical", "nmc", "SINTEF"} <= set(cat["schema:keywords"])
    assert cat["schema:version"] == "2"
    assert cat["dcterms:isVersionOf"]["@id"] == "https://zenodo.org/records/concept"
    assert prov["@id"] == "https://ror.org/01f677e56"


def test_dcat_richness_dcterms_bytesize_derivation_mediatype() -> None:
    """Cross-vocab richness: dcterms mirrors on the catalog, attribution propagated to
    members, IANA media-type IRIs, byte sizes, distribution @ids, and conversion
    provenance (processed file derived from the raw instrument file)."""
    ds_id = "https://w3id.org/battinfo/dataset/d1"
    rs = {
        "cell-spec": [{"cell_spec": {"id": "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-dddd",
                                    "name": "X", "model": "M", "manufacturer": {"name": "SINTEF"},
                                    "cell_format": "cylindrical", "chemistry": "nmc"}, "properties": {}}],
        "cell-instance": [{"cell_instance": {"id": "https://w3id.org/battinfo/cell/c1",
                                             "cell_spec_id": "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-dddd",
                                             "name": "c1"}}],
        "test": [{"test": {"id": "https://w3id.org/battinfo/test/t1",
                           "cell_id": "https://w3id.org/battinfo/cell/c1", "kind": "capacity_check",
                           "protocol_name": "CC", "dataset_ids": [ds_id]}}],
        "test-protocol": [],
        "dataset": [{"dataset": {"id": ds_id, "name": "d1", "distributions": [
            {"name": "f.bdf.csv", "content_url": "f.bdf.csv", "encoding_format": "text/csv",
             "role": "processed", "checksum": {"value": "a" * 64}, "content_size": "12345"},
            {"name": "f.ndax", "content_url": "f.ndax", "encoding_format": "application/octet-stream",
             "role": "raw", "checksum": {"value": "b" * 64}, "content_size": "999",
             "description": "Original instrument data file (pre-conversion source for f.bdf.csv)."},
        ]}}],
    }
    doc = AuthoringWorkspace._assemble_zenodo_jsonld(
        rs, zenodo_record_id=0, prereserved_doi="10.5281/zenodo.1",
        record_url="https://zenodo.org/records/1",
        data_filenames=["f.bdf.csv", "f.ndax"], title="My title", description="desc",
        creators=[{"name": "A", "affiliation": "SINTEF", "affiliation_ror": "01f677e56"}],
        license="cc-by-4.0",
    )
    cat = next(n for n in doc["@graph"] if "dcat:Catalog" in (n.get("@type") or []))
    assert cat["dcterms:title"] == "My title"
    assert cat["dcterms:description"] == "desc"
    assert cat["dcterms:language"] == "en"
    assert "dcterms:publisher" in cat and "dcat:keyword" in cat

    member = next(n for n in doc["@graph"] if n.get("@id") == ds_id)
    assert member["schema:license"] == {"@id": "https://spdx.org/licenses/cc-by-4.0.html"}
    assert member["schema:creator"]  # propagated from catalog-level creators

    dists = {d["schema:name"]: d for d in member["dcat:distribution"]}
    csv, ndax = dists["f.bdf.csv"], dists["f.ndax"]
    assert csv["dcat:mediaType"] == {"@id": "https://www.iana.org/assignments/media-types/text/csv"}
    assert csv["dcat:byteSize"] == 12345 and ndax["dcat:byteSize"] == 999
    assert csv["@id"].endswith("/f.bdf.csv")
    # Conversion provenance: processed ← raw, and only on the processed file.
    assert csv["prov:wasDerivedFrom"]["@id"].endswith("/f.ndax")
    assert "prov:wasDerivedFrom" not in ndax
    # Bug fix: the raw file names the PROCESSED file as what it is a source for.
    assert "f.bdf.csv" in ndax["schema:description"]


def test_timing_doi_and_top_level_distribution() -> None:
    """V5/V6: activity timing from the data, member temporalCoverage (no misleading
    datePublished), DOI sameAs on the catalog, and downloads surfaced at the top level."""
    ds_id = "https://w3id.org/battinfo/dataset/d1"
    rs = {
        "cell-spec": [{"cell_spec": {"id": "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-dddd",
                                    "name": "X", "model": "M", "manufacturer": {"name": "SINTEF"},
                                    "cell_format": "cylindrical", "chemistry": "nmc"}, "properties": {}}],
        "cell-instance": [{"cell_instance": {"id": "https://w3id.org/battinfo/cell/c1",
                                             "cell_spec_id": "https://w3id.org/battinfo/spec/aaaa-bbbb-cccc-dddd",
                                             "name": "c1"}}],
        "test": [{"test": {"id": "https://w3id.org/battinfo/test/t1",
                           "cell_id": "https://w3id.org/battinfo/cell/c1", "kind": "capacity_check",
                           "protocol_name": "CC", "dataset_ids": [ds_id],
                           "started_at": 1700000000, "ended_at": 1700086400}}],
        "test-protocol": [],
        "dataset": [{"dataset": {"id": ds_id, "name": "d1",
                                 "temporal_coverage": "2023-11-14T22:13:20Z/2023-11-15T22:13:20Z",
                                 "published_at": 1781525115,  # assembly-time: must NOT surface
                                 "distributions": [
                                     {"name": "f.bdf.csv", "content_url": "f.bdf.csv",
                                      "encoding_format": "text/csv", "role": "processed",
                                      "checksum": {"value": "a" * 64}}]}}],
    }
    doc = AuthoringWorkspace._assemble_zenodo_jsonld(
        rs, zenodo_record_id=0, prereserved_doi="10.5281/zenodo.99",
        record_url="https://zenodo.org/records/99", data_filenames=["f.bdf.csv"], title="T",
    )
    cat = next(n for n in doc["@graph"] if "dcat:Catalog" in (n.get("@type") or []))
    assert cat["schema:sameAs"] == {"@id": "https://doi.org/10.5281/zenodo.99"}
    assert cat["dcterms:identifier"] == "10.5281/zenodo.99"
    assert cat["schema:temporalCoverage"].startswith("2023-11-14")
    assert len(cat["schema:distribution"]) == 1   # download surfaced at top level

    member = next(n for n in doc["@graph"] if n.get("@id") == ds_id)
    assert member["schema:temporalCoverage"].startswith("2023-11-14")
    assert "schema:datePublished" not in member    # misleading assembly-time date dropped

    test = next(n for n in doc["@graph"] if "BatteryTest" in (n.get("@type") or []))
    assert test["prov:startedAtTime"] == "2023-11-14T22:13:20Z"
    assert test["prov:endedAtTime"] == "2023-11-15T22:13:20Z"
    assert test["schema:startTime"] == test["prov:startedAtTime"]


def test_bdf_measurement_period(tmp_path: Path) -> None:
    from battinfo.ws import _bdf_measurement_period
    csv = tmp_path / "x.bdf.csv"
    csv.write_text(
        "test_time_second,voltage_volt,unix_time_second\n"
        "0.0,1.5,1700000000.0\n10.0,1.4,1700000010.0\n20.0,1.3,1700000020.0\n",
        encoding="utf-8",
    )
    assert _bdf_measurement_period(csv) == (1700000000, 1700000020)
    # No unix column → None (only relative time available).
    csv2 = tmp_path / "y.bdf.csv"
    csv2.write_text("test_time_second,voltage_volt\n0.0,1.5\n10.0,1.4\n", encoding="utf-8")
    assert _bdf_measurement_period(csv2) is None


def test_published_graph_passes_publication_validation(tmp_path: Path) -> None:
    """The assembled graph must pass the publication gate (JSON-LD + dict-structural +
    SHACL over the gold-standard topology) at the strict publisher policy."""
    from battinfo.validate import validate_publication_report

    doc = _build_doc(tmp_path)
    report = validate_publication_report(doc, policy="publisher")
    errors = [i for i in report.issues if i.severity == "error"]
    assert not errors, f"publication validation errors: {[(i.code, i.message) for i in errors]}"


def test_publication_shacl_catches_broken_provenance(tmp_path: Path) -> None:
    """A test missing prov:used must be rejected by the structural SHACL layer."""

    from battinfo.validate import validate_publication_report

    doc = _build_doc(tmp_path)
    for node in doc["@graph"]:
        if "BatteryTest" in (node.get("@type") or []):
            node.pop("prov:used", None)
            break
    report = validate_publication_report(doc, policy="publisher")
    assert any(i.code == "publication.shacl_constraint" and i.severity == "error"
               for i in report.issues)


def test_schema_org_consumer_reaches_every_download(tmp_path: Path) -> None:
    """A schema.org-only consumer can find the file bytes via schema:DataDownload —
    not only via the DCAT distribution (schema.org has no dcat:downloadURL)."""
    graph = _build_doc(tmp_path)["@graph"]
    members = [n for n in graph if "dcat:distribution" in n]
    assert members
    for m in members:
        dcat_urls = {d["dcat:downloadURL"] for d in m["dcat:distribution"]}
        schema_urls = {d["schema:contentUrl"] for d in m["schema:distribution"]}
        assert dcat_urls == schema_urls, "schema.org mirror missing a download"


def test_resolve_raw_source_uses_convert_manifest(tmp_path: Path) -> None:
    """convert() records source→output so add('test', data=) auto-attaches the raw."""
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    src = tmp_path / "orig.ndax"
    src.write_bytes(b"RAW")
    out = tmp_path / "bdf" / "orig.bdf.csv"
    out.parent.mkdir()
    out.write_text("a,b\n0,1\n", encoding="utf-8")
    ws._record_conversion(src, out)
    assert ws._resolve_raw_source(out) == src
    # A file not produced by convert() has no recorded original.
    other = tmp_path / "unknown.csv"
    other.write_text("x\n", encoding="utf-8")
    assert ws._resolve_raw_source(other) is None


def test_add_test_conformance_flag(tmp_path: Path) -> None:
    import json as _json
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    spec = _write_spec(ws, tmp_path)
    proto = ws._ws.test_spec(name="CC discharge", type="capacity_check")
    ws.add("cell", spec=spec, names=["c1"])
    (tmp_path / "c1.csv").write_text("a,b\n0,1\n", encoding="utf-8")
    tests = ws.add(
        "test", type="capacity_check", cell="c1", data="c1.csv", spec=proto,
        conformance={"status": "non-conformant", "note": "current 2x setpoint",
                     "deviations": [{"category": "setpoint_deviation",
                                     "type": "discharge current", "description": "500 vs 250 mA"}]},
    )
    assert tests[0].conformance.status == "non-conformant"
    ws.save()
    rec = _json.loads(
        next((ws._records_root / "examples" / "test").glob("*.json")).read_text(encoding="utf-8")
    )["test"]
    assert rec["conformance"]["status"] == "non-conformant"
    dev = rec["conformance"]["deviations"][0]
    assert dev["category"] == "setpoint_deviation" and dev["type"] == "discharge current"
    assert rec.get("protocol_id"), "test should link the spec it (non-)conforms to"


def test_add_cell_conformance(tmp_path: Path) -> None:
    """Conformance is general: a cell can be (non-)conformant vs its cell-spec."""
    import json as _json
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    spec = _write_spec(ws, tmp_path)
    # single value broadcast + per-cell list both supported
    ws.add("cell", spec=spec, names=["c-ok"], conformance="conformant")
    ws.add("cell", spec=spec, names=["c-a", "c-b"],
           conformance=["conformant",
                        {"status": "non-conformant", "note": "capacity low",
                         "deviations": [{"category": "out_of_tolerance", "type": "capacity 10% below spec"}]}])
    ws.save()
    by_name = {}
    for p in (ws._records_root / "examples" / "cell-instance").glob("*.json"):
        ci = _json.loads(p.read_text(encoding="utf-8"))["cell_instance"]
        by_name[ci.get("name")] = ci.get("conformance")
    assert by_name["c-ok"]["status"] == "conformant"
    assert by_name["c-a"]["status"] == "conformant"
    assert by_name["c-b"]["status"] == "non-conformant"
    assert by_name["c-b"]["deviations"][0]["category"] == "out_of_tolerance"


def test_add_cell_conformance_list_length_mismatch_raises(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    spec = _write_spec(ws, tmp_path)
    with pytest.raises(ValueError, match="conformance list must match"):
        ws.add("cell", spec=spec, names=["a", "b"], conformance=["conformant"])


def test_deviation_category_back_compat_and_new_form() -> None:
    from battinfo import Deviation
    legacy = Deviation.from_record({"type": "parameter_drift", "description": "x"})
    assert legacy.category == "parameter_drift" and legacy.type is None
    new = Deviation.from_record({"category": "setpoint_deviation", "type": "current mismatch"})
    assert new.category == "setpoint_deviation" and new.type == "current mismatch"
    assert new.to_record() == {"category": "setpoint_deviation", "type": "current mismatch"}


def test_conformance_is_general_alias() -> None:
    from battinfo import Conformance, TestConformance
    assert Conformance is TestConformance


def test_add_test_invalid_conformance_status_raises(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    spec = _write_spec(ws, tmp_path)
    ws.add("cell", spec=spec, names=["c1"])
    (tmp_path / "c1.csv").write_text("a,b\n0,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="conformance status"):
        ws.add("test", type="capacity_check", cell="c1", data="c1.csv", conformance="bogus")


def test_canon_type_mapping():
    from battinfo.ws import _canon_type
    assert _canon_type("cell-spec") == "cell_spec"
    assert _canon_type("cell") == "cell"
    assert _canon_type("test-spec") == "test_protocol"
    assert _canon_type("test") == "test"
    assert _canon_type("dataset") == "dataset"
    with pytest.raises(ValueError, match="Unknown type"):
        _canon_type("banana")


def test_search_cell_requires_a_filter(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url="https://registry.example")
    with pytest.raises(ValueError, match="serial"):
        ws.search(type="cell")


def test_search_cellspec_rejects_serial(tmp_path: Path) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url=None)
    with pytest.raises(ValueError, match="serial"):
        ws.search("duracell", type="cell-spec", serial="x")


def test_search_cell_returns_registry_matches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = AuthoringWorkspace(root=tmp_path, registry_url="https://registry.example")
    monkeypatch.setattr(ws, "_query_registry_cells", lambda **kw: [dict(_REG_CELL)])
    found = ws.search(type="cell", serial="tpejqj")
    assert len(found) == 1 and found[0]["id"] == _REG_CELL["id"]
    assert found[0]["type"] == "cell"


def test_serial_matches_short_id_and_full():
    from battinfo.ws import _serial_matches
    full = "duracell-mn2400-2026-02-tpejqj"
    assert _serial_matches("tpejqj", full)        # short id -> full serial
    assert _serial_matches(full, full)            # exact
    assert _serial_matches(full, "x-y-z-tpejqj")  # shared short id
    assert not _serial_matches("zzzzzz", full)


def test_load_then_add_test_links_existing_cell_without_duplicating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """search(type='cell') -> load() references an existing instance; add('test')
    attaches to its IRI and saves NO duplicate cell."""
    ws = AuthoringWorkspace(root=tmp_path, registry_url="https://registry.example")
    monkeypatch.setattr(ws, "_query_registry_cells", lambda **kw: [dict(_REG_CELL)])

    cell = ws.load(ws.search(type="cell", serial="tpejqj")[0])
    assert cell.id == _REG_CELL["id"]
    assert ws._ws.cells == []   # referenced, not queued for save

    (tmp_path / "data.csv").write_text("a,b\n0,1\n", encoding="utf-8")
    ws.add("test", type="capacity_check", cell="tpejqj", data="data.csv")
    res = ws.save()

    assert len(res.get("cell_instances", [])) == 0
    assert len(res.get("cell_specs", [])) == 0
    assert len(res.get("tests", [])) == 1
    assert len(res.get("datasets", [])) == 1
    rec_text = next((ws._records_root / "examples" / "test").glob("*.json")).read_text(encoding="utf-8")
    assert _REG_CELL["id"] in rec_text, "the test must link to the existing registry IRI"


def test_add_test_cell_arg_resolves_from_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """cell= resolves an existing instance straight from the registry — no explicit load."""
    ws = AuthoringWorkspace(root=tmp_path, registry_url="https://registry.example")
    monkeypatch.setattr(ws, "_query_registry_cells", lambda **kw: [dict(_REG_CELL)])
    (tmp_path / "d.csv").write_text("a,b\n0,1\n", encoding="utf-8")
    tests = ws.add("test", type="cycling", cell="tpejqj", data="d.csv")
    assert len(tests) == 1
    res = ws.save()
    assert len(res.get("cell_instances", [])) == 0 and len(res.get("tests", [])) == 1
