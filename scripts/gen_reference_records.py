"""Generate docs/reference-records/ — the reference-records chapter.

One page per record type, each carrying the same triplet, produced live at
generation time so it cannot lie:

  1. the authoring code (a snippet function below; its SOURCE is what the page
     shows, its EXECUTION produces the record beside it),
  2. the canonical record JSON it produced (IRIs and timestamps normalized to
     the same stable placeholders the web showcase uses),
  3. the emitted JSON-LD (record_to_jsonld, hosted-context mode, so the
     committed artifact stays compact and diffs stay semantic).

Every record is validated under the STRICT policy during generation and this
script fails on any issue — a schema or emitter change that breaks a reference
record breaks this generator in the same PR that caused it.

tests/test_reference_records.py regenerates the chapter in memory and fails on
drift, so any PR that changes what these pages show must regenerate them:

    uv run python scripts/gen_reference_records.py           # write
    uv run python scripts/gen_reference_records.py --check   # CI drift gate

The chapter is the review surface for change propagation: the git history of
docs/reference-records/ is the record of how schema, API, and emitter changes
reached real examples.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Shared determinism helpers: the SAME uid-placeholder pool and timestamp
# freezing the web showcase uses, so one record authored in both surfaces
# renders identically in both.
_spec = importlib.util.spec_from_file_location(
    "gen_web_examples", Path(__file__).resolve().parent / "gen_web_examples.py"
)
assert _spec is not None and _spec.loader is not None
_web = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_web)
normalize = _web.normalize
snippet_source = _web.snippet_source

OUT_DIR = ROOT / "docs" / "reference-records"
NL = chr(10)


# ── Snippets: the code shown on the page IS the code that ran ────────────────
# Each function returns the canonical record dict. Explicit IRIs are shown the
# way the workspace would mint them; in the ws.add()/ws.save() flow you never
# set them yourself.


def snippet_cell_spec():
    from battinfo import CellSpec

    spec = CellSpec(
        # The published flagship IRI — dereference it (Accept:
        # application/ld+json) to get this exact record.
        id="https://w3id.org/battinfo/spec/pge5-wer6-2q82-v9k0",
        manufacturer="A123",
        model="ANR26650M1-B",
        format="cylindrical",
        chemistry="Li-ion",
        positive_electrode_basis="LFP",
        properties={
            "nominal_capacity": {"value": 2.5, "unit": "Ah"},
            "nominal_voltage": {"value": 3.3, "unit": "V"},
            "mass": {"value": 76.0, "unit": "g"},
        },
        source={"type": "datasheet", "retrieved_at": 1750000000},
    )
    record = spec.to_record()
    return record


def snippet_cell_instance():
    from battinfo import Cell, CellSpec

    spec = CellSpec(
        id="https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5",
        manufacturer="Samsung SDI",
        model="INR21700-50E",
        format="cylindrical",
        chemistry="Li-ion",
    )
    cell = Cell(
        id="https://w3id.org/battinfo/cell/y9xy-kr0v-y5tn-dfj7",
        cell_spec=spec,                    # every cell links to its spec
        serial_number="LAB-2026-0001",
        batch_id="2026-W03",
        manufactured_at="2026-01-15",
        source={"type": "lab", "retrieved_at": 1750000000},
    )
    record = cell.to_record()
    return record


def snippet_test_protocol():
    from battinfo import TestSpec

    protocol = TestSpec(
        id="https://w3id.org/battinfo/spec/kxwy-5f5f-f682-hhch",
        name="1C cycle life at 25 degC",
        kind="cycling",
        experiment=[                       # PyBaMM syntax — runnable as-is
            "Charge at 1C until 4.2 V",
            "Hold at 4.2 V until C/20",
            "Discharge at 1C until 2.5 V",
            "Rest for 10 minutes",
        ],
        # Conditions are quantities ({value, unit}), by contract (#363).
        conditions={"ambient_temperature": {"value": 25.0, "unit": "degC"}},
        source={"type": "manual", "retrieved_at": 1750000000},
    )
    record = protocol.to_record()
    return record


def snippet_test():
    from battinfo import Cell, CellSpec, Test

    cell = Cell(
        id="https://w3id.org/battinfo/cell/y9xy-kr0v-y5tn-dfj7",
        cell_spec=CellSpec(
            id="https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5",
            manufacturer="Samsung SDI", model="INR21700-50E",
            format="cylindrical", chemistry="Li-ion",
        ),
        serial_number="LAB-2026-0001",
    )
    test = Test(
        id="https://w3id.org/battinfo/test/3w87-0ddf-ryjg-evxe",
        cell=cell,                         # what you did, to which cell
        kind="cycling",
        protocol_id="https://w3id.org/battinfo/spec/kxwy-5f5f-f682-hhch",
        protocol="1C cycle life at 25 degC",
        instrument="Biologic VMP-300",
        status="completed",
        # As-run conditions: what actually applied, as {value, unit}
        # quantities (planned conditions live on the protocol).
        conditions={"ambient_temperature": {"value": 24.6, "unit": "degC"}},
        started_at=1750000000,
        source={"type": "measurement", "retrieved_at": 1750000000},
    )
    record = test.to_record()
    return record


def snippet_dataset():
    from battinfo import Cell, CellSpec, Dataset, Test

    cell = Cell(
        id="https://w3id.org/battinfo/cell/y9xy-kr0v-y5tn-dfj7",
        cell_spec=CellSpec(
            id="https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5",
            manufacturer="Samsung SDI", model="INR21700-50E",
            format="cylindrical", chemistry="Li-ion",
        ),
        serial_number="LAB-2026-0001",
    )
    test = Test(
        id="https://w3id.org/battinfo/test/3w87-0ddf-ryjg-evxe",
        cell=cell, kind="cycling", status="completed",
    )
    dataset = Dataset(
        id="https://w3id.org/battinfo/dataset/6nec-h262-tthy-4rnt",
        name="INR21700-50E cycle-life dataset",
        description="Cycle-life time series for cell LAB-2026-0001.",
        cell=cell,
        test=test,
        license="https://creativecommons.org/licenses/by/4.0/",
        access_url="https://doi.org/10.5281/zenodo.1234567",
        download_url="https://zenodo.org/records/1234567/files/run.parquet",
        data_format="application/x-parquet",
        checksum_algorithm="md5",
        checksum_value="9e107d9d372bb6826bd81d3542a419d6",
        # Membership in a dataset series (a collection record): emitted as
        # dcat:inSeries and schema:isPartOf. The collection publishes first.
        series_id="https://w3id.org/battinfo/dataset/0rp6-kncv-cyem-qwcd",
        source={"type": "measurement", "retrieved_at": 1750000000},
    )
    record = dataset.to_record()
    return record


def snippet_dataset_series():
    from battinfo import Dataset

    collection = Dataset(
        id="https://w3id.org/battinfo/dataset/0rp6-kncv-cyem-qwcd",
        name="INR21700-50E cycle-life collection",
        description="All cycle-life datasets of the 2026 INR21700-50E study.",
        # The series flavor: an ordinary dataset record, typed
        # dcat:DatasetSeries by this marker — no separate record type.
        additional_type=["DatasetSeries"],
        # The collection IS the deposit, so the deposit DOI is its own
        # external identifier.
        identifier={"property_id": "doi", "value": "10.5281/zenodo.1234567"},
        license="https://creativecommons.org/licenses/by/4.0/",
        access_url="https://doi.org/10.5281/zenodo.1234567",
        # No cell, test, or distributions: the member datasets carry those.
        source={"type": "catalog", "retrieved_at": 1750000000},
    )
    record = collection.to_record()
    return record


# ── Pages ────────────────────────────────────────────────────────────────────
# Each page groups one or more sections; a section is one triplet. `notice`
# lines name what a reader should find in the emitted JSON-LD — keep every
# claim true of the current output (the drift test re-renders these pages, so
# a stale claim survives only until the next regeneration is reviewed).

PAGES = [
    {
        "slug": "cell-spec",
        "title": "Cell spec",
        "intro": (
            "The specification of a cell design — the datasheet, not a physical "
            "unit. Physical cells (`cell-instance` records) point at it."
        ),
        "sections": [
            {
                "heading": "A commercial cell from its datasheet",
                "fn": snippet_cell_spec,
                "record_type": "cell-spec",
                "notice": [
                    "The node is EMMO-typed (`BatteryCellSpecification`) and each "
                    "spec property becomes a typed quantity under `hasProperty`.",
                    "`schema:manufacturer` and `schema:model` carry the identity "
                    "that seeded the IRI.",
                ],
            },
        ],
    },
    {
        "slug": "cell-instance",
        "title": "Cell instance",
        "intro": (
            "One physical cell: a serial number and batch under a cell spec. "
            "The (spec, serial) pair seeds its IRI."
        ),
        "sections": [
            {
                "heading": "A lab cell under a commercial spec",
                "fn": snippet_cell_instance,
                "record_type": "cell-instance",
                "notice": [
                    "`cell_spec_id` is the instantiation edge; the JSON-LD states "
                    "it as a reference to the spec node.",
                    "`schema:serialNumber` carries the physical identity.",
                ],
            },
        ],
    },
    {
        "slug": "test",
        "title": "Test and protocol",
        "intro": (
            "Two layers: the protocol (`test-protocol`, the plan) and the test "
            "(the execution on one cell). Planned conditions live on the "
            "protocol; as-run conditions on the test. Conditions are "
            "`{value, unit}` quantities by contract."
        ),
        "sections": [
            {
                "heading": "The protocol",
                "fn": snippet_test_protocol,
                "record_type": "test-protocol",
                "notice": [
                    "The PyBaMM-style `experiment` strings become the structured "
                    "`method` steps at the record top level, and the JSON-LD "
                    "emits a typed EMMO workflow (`prov:Plan` / `schema:HowTo`).",
                ],
            },
            {
                "heading": "The execution",
                "fn": snippet_test,
                "record_type": "test",
                "notice": [
                    "`hasTestObject` / `schema:object` point at the cell; "
                    "`dcterms:conformsTo` points at the protocol.",
                    "As-run conditions emit as `schema:PropertyValue` entries "
                    "under `schema:additionalProperty`.",
                ],
            },
        ],
    },
    {
        "slug": "dataset",
        "title": "Dataset and series",
        "intro": (
            "A dataset describes measured data files; a dataset SERIES is the "
            "collection they belong to — an ordinary dataset record flavored "
            "by `additional_type: [\"DatasetSeries\"]`, with membership on each "
            "member's `series_id`. The collection publishes first, because "
            "members carry the forward edge."
        ),
        "sections": [
            {
                "heading": "A member dataset",
                "fn": snippet_dataset,
                "record_type": "dataset",
                "notice": [
                    "`series_id` emits BOTH `dcat:inSeries` (the DCAT 3 "
                    "membership edge) and `schema:isPartOf` (what dataset "
                    "search engines read).",
                    "`about` links the cell and the test; the distribution "
                    "carries the download URL and checksum.",
                ],
            },
            {
                "heading": "The collection (dataset series)",
                "fn": snippet_dataset_series,
                "record_type": "dataset",
                "notice": [
                    "`@type` carries `dcat:DatasetSeries` alongside "
                    "`dcat:Dataset` — no new record type exists.",
                    "No `about` and no distributions: the members hold the cell "
                    "links and the files, and the strict policy admits that "
                    "for the series flavor only.",
                ],
            },
        ],
    },
]


# ── Build ────────────────────────────────────────────────────────────────────

def _validate_or_die(record: dict, where: str) -> str:
    """Strict-validate; die loudly on ANY issue; return the verdict line."""
    import battinfo
    from battinfo.validate.record import validate_record_report

    report = validate_record_report(record, policy="strict")
    if report.issues:
        details = NL.join(
            f"  - {issue.severity} {issue.code} at {issue.path}: {issue.message}"
            for issue in report.issues
        )
        raise SystemExit(
            f"gen_reference_records: the '{where}' reference record no longer "
            f"validates clean under the strict policy:{NL}{details}{NL}"
            "A reference record is contract — fix the record shape or the "
            "change that broke it, in this same PR."
        )
    return (
        "**Validated clean** — strict policy, 0 errors, 0 warnings "
        f"(battinfo {battinfo.__version__})."
    )


def build_sections(page: dict) -> list[dict]:
    from battinfo import record_to_jsonld

    sections = []
    for section in page["sections"]:
        record = normalize(section["fn"]())
        verdict = _validate_or_die(record, f"{page['slug']}: {section['heading']}")
        jsonld = record_to_jsonld(record, section["record_type"])
        sections.append({**section, "record": record, "jsonld": jsonld, "verdict": verdict})
    return sections


BANNER = (
    "<!-- GENERATED by scripts/gen_reference_records.py — do not edit." + NL
    + "     Regenerate: uv run python scripts/gen_reference_records.py" + NL
    + "     tests/test_reference_records.py fails when this page drifts. -->" + NL
)


def render_page(page: dict, sections: list[dict]) -> str:
    parts = [BANNER, NL, f"# {page['title']}", NL, NL, page["intro"], NL]
    for section in sections:
        parts += [NL, f"## {section['heading']}", NL, NL]
        parts += ["```python", NL, snippet_source(section["fn"]), NL, "```", NL, NL]
        parts += ["The canonical record this produces:", NL, NL]
        parts += ["```json", NL, json.dumps(section["record"], indent=2, ensure_ascii=False), NL, "```", NL, NL]
        parts += [
            "The JSON-LD it emits (`record_to_jsonld`, hosted-context mode):",
            NL, NL,
            "```json", NL, json.dumps(section["jsonld"], indent=2, ensure_ascii=False), NL, "```", NL, NL,
        ]
        if section.get("notice"):
            parts += ["What to notice:", NL, NL]
            for line in section["notice"]:
                parts += [f"- {line}", NL]
            parts += [NL]
        parts += [section["verdict"], NL]
    return "".join(parts)


def render_index() -> str:
    rows = NL.join(
        f"| [{page['title']}]({page['slug']}.md) | "
        + " · ".join(s["heading"] for s in page["sections"]) + " |"
        for page in PAGES
    )
    toc = NL.join(f"{page['slug']}" for page in PAGES)
    return (
        BANNER + NL
        + "# Reference records" + NL + NL
        + "One exemplar per record type: the authoring code, the canonical "
        + "record it produces, and the JSON-LD that record emits — generated "
        + "against the current library on every change, validated clean under "
        + "the strict policy, and drift-gated so a schema, API, or emitter "
        + "change must regenerate this chapter in the same PR. The git history "
        + "of `docs/reference-records/` is therefore the record of how changes "
        + "propagate to real examples." + NL + NL
        + "| Page | Exemplars |" + NL
        + "|---|---|" + NL
        + rows + NL + NL
        + "Coverage accounting (every schema property exercised by a reference "
        + "record, or waived with a reason) arrives with the next expansion of "
        + "this chapter." + NL + NL
        + "```{toctree}" + NL + ":hidden:" + NL + NL
        + toc + NL
        + "```" + NL
    )


def render_all() -> dict[str, str]:
    files = {"index.md": render_index()}
    for page in PAGES:
        files[f"{page['slug']}.md"] = render_page(page, build_sections(page))
    return files


def main() -> int:
    files = render_all()
    if "--check" in sys.argv:
        stale = []
        for name, text in files.items():
            path = OUT_DIR / name
            current = path.read_text(encoding="utf-8").replace("\r\n", "\n") if path.exists() else ""
            if current != text.replace("\r\n", "\n"):
                stale.append(name)
        if stale:
            print(
                "docs/reference-records/ drifts: " + ", ".join(sorted(stale))
                + " — run `uv run python scripts/gen_reference_records.py`",
                file=sys.stderr,
            )
            return 1
        print(f"reference records in sync ({len(files)} pages).")
        return 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (OUT_DIR / name).write_text(text, encoding="utf-8", newline=NL)
    print(f"Wrote {len(files)} pages -> {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
