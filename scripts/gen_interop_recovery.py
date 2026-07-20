"""Generate the interop recovery scorecard page (docs/pages/interop-recovery.md).

Runs the real non-canonical JSON-LD source fixtures through BattINFO's interop
importers and scores, per source and per dimension, how completely each is
normalized into canonical BattINFO records + JSON-LD. The scoring is the
substance; the page is a green/yellow/red matrix over it with a per-source
expandable breakdown.

The same score_all() function backs tests/test_interop_recovery.py, so a drop in
recovery quality fails CI and shows up here. Deterministic: only counts and
ratings (no timestamps/IRIs), so the committed page is drift-checked like the
other generated reference pages.

    Regenerate:  uv run python scripts/gen_interop_recovery.py
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "pages" / "interop-recovery.md"

# --- ratings ------------------------------------------------------------------
PASS = "pass"       # green  — fully recovered
PARTIAL = "partial"  # yellow — recovered, but lossy or folded
FAIL = "fail"       # red    — not recovered

GLYPH = {PASS: "🟢", PARTIAL: "🟡", FAIL: "🔴"}
WORD = {PASS: "full", PARTIAL: "partial", FAIL: "none"}

DIMENSIONS: list[tuple[str, str]] = [
    ("ingest", "Ingest"),
    ("normalize", "Normalize"),
    ("identity", "Identity"),
    ("quantities", "Quantities"),
    ("components", "Components"),
    ("canonical", "Canonical JSON-LD"),
]

COMPONENT_KINDS = {
    "material_spec", "electrode_spec", "electrolyte_spec",
    "separator_spec", "current_collector_spec", "housing_spec",
}
KIND_KEYS = COMPONENT_KINDS | {
    "cell_spec", "cell_instance", "test", "test_spec", "dataset",
    "material", "electrode", "electrolyte", "separator",
    "current_collector", "housing", "equipment", "channel",
}


@dataclass
class SourceScore:
    key: str
    label: str
    family: str
    shape: str
    fixture: str
    dims: dict[str, tuple[str, str]] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


# --- source registry ----------------------------------------------------------
# Every entry is a real in-the-wild non-canonical JSON-LD document. loader()
# returns (raw_doc, canonical_records, extra_notes).
def _tolerant_load(path: Path) -> tuple[dict[str, Any], bool]:
    """R1: parse tolerating the bare `NaN`/`Infinity` the Excel converter emits."""
    text = path.read_text(encoding="utf-8")
    repaired = False
    for bad in ("NaN", "Infinity", "-Infinity"):
        token = f": {bad}"
        if token in text:
            text = text.replace(token, ": null")
            repaired = True
    return json.loads(text), repaired


def _detect_shape(doc: dict[str, Any]) -> str:
    if isinstance(doc.get("@graph"), list):
        return f"@graph[{len(doc['@graph'])}]"
    t = doc.get("@type")
    types = t if isinstance(t, list) else [t]
    if "BatteryTest" in types:
        return "BatteryTest-root"
    if any(isinstance(x, str) and ("Cell" in x or "Battery" in x) for x in types):
        return "cell-root"
    return "single-node"


def _converter_records(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    from battinfo.interop import import_converter_package

    doc, repaired = _tolerant_load(path)
    package = import_converter_package(doc, components=True)
    records: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str | None]] = set()
    for obj in package.objects():
        record = obj.to_record()
        kind = _kind_of(record)
        rid = record.get(kind, {}).get("id") if kind else None
        if (kind, rid) in seen:
            continue
        seen.add((kind, rid))
        records.append(record)
    records.extend(package.component_records())
    return doc, records, repaired


def _discovery_records(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    from battinfo.interop import import_discovery_eln

    doc, repaired = _tolerant_load(path)
    package = import_discovery_eln(path, validate=False)
    return doc, package.records(), repaired


SOURCES: list[dict[str, Any]] = [
    *[
        {
            "key": f"converter-v{v}",
            "label": f"Converter Excel v{v}",
            "family": "converter",
            "fixture": f"tests/fixtures/interop/converter-versions/converter-v{v}.coincell.jsonld",
            "loader": _converter_records,
        }
        for v in ("1.0.0", "1.1.2", "1.1.8", "1.1.11", "1.1.15", "1.1.17")
    ],
    {
        "key": "empa-sample",
        "label": "EMPA converter sample",
        "family": "converter",
        "fixture": "tests/fixtures/converter/coin-cell.converter.sample.jsonld",
        "loader": _converter_records,
    },
    {
        "key": "empa-reference-v3",
        "label": "EMPA reference v3",
        "family": "converter",
        "fixture": "tests/fixtures/converter/coincell_reference_v3.jsonld",
        "loader": _converter_records,
    },
    {
        "key": "discovery-eln",
        "label": "Discovery RO-Crate (.eln)",
        "family": "discovery",
        "fixture": "tests/fixtures/interop/discovery/ro-crate-metadata.sample.json",
        "loader": _discovery_records,
    },
]


# --- metric helpers -----------------------------------------------------------
def _kind_of(record: dict[str, Any]) -> str | None:
    for key in record:
        if key in KIND_KEYS:
            return key
    return None


def _count_quantities(node: Any) -> int:
    n = 0
    if isinstance(node, dict):
        if "value" in node and "unit" in node:
            n += 1
        for v in node.values():
            n += _count_quantities(v)
    elif isinstance(node, list):
        for v in node:
            n += _count_quantities(v)
    return n


def _cell_spec_record(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    for r in records:
        if "cell_spec" in r:
            return r
    return None


# --- scoring ------------------------------------------------------------------
def _score(src: dict[str, Any]) -> SourceScore:
    from battinfo.transform import to_jsonld
    from battinfo.validate import validate_record

    loader: Callable[[Path], tuple[dict[str, Any], list[dict[str, Any]], bool]] = src["loader"]
    path = ROOT / src["fixture"]
    score = SourceScore(
        key=src["key"], label=src["label"], family=src["family"],
        shape="?", fixture=src["fixture"],
    )

    # Ingest (R1) — parse tolerating emitter quirks.
    try:
        raw, records, repaired = loader(path)
    except Exception as exc:  # noqa: BLE001 - a failed source is a red cell, not a crash
        score.error = f"{type(exc).__name__}: {exc}"
        score.shape = "?"
        for dim, _ in DIMENSIONS:
            score.dims[dim] = (FAIL, "pipeline raised before this dimension")
        score.dims["ingest"] = (FAIL, score.error)
        return score

    score.shape = _detect_shape(raw)
    score.dims["ingest"] = (
        PASS,
        "parsed after repairing bare NaN/Infinity" if repaired else "parsed as-is",
    )

    # Normalize (R3) — a canonical cell spec of the right format came out.
    cell = _cell_spec_record(records)
    fmt = cell.get("cell_spec", {}).get("cell_format") if cell else None
    n_records = len(records)
    if cell is not None:
        score.dims["normalize"] = (PASS, f"{score.shape} → {n_records} canonical records; cell format {fmt!r}")
    else:
        score.dims["normalize"] = (FAIL, f"{score.shape} → no canonical cell spec")

    # Identity — core id/name/format required; manufacturer/chemistry/model are bonus.
    cs = (cell or {}).get("cell_spec", {})
    core = [k for k in ("id", "name", "cell_format") if cs.get(k)]
    bonus = [k for k in ("manufacturer", "chemistry", "model") if cs.get(k)]
    if len(core) == 3 and bonus:
        score.dims["identity"] = (PASS, "id, name, format" + (" + " + ", ".join(bonus) if bonus else ""))
    elif len(core) == 3:
        score.dims["identity"] = (PARTIAL, "id, name, format; no manufacturer/chemistry/model")
    else:
        score.dims["identity"] = (FAIL, f"missing core identity ({core})")

    # Quantities — value+unit pairs recovered across the canonical set.
    quant = sum(_count_quantities(r) for r in records)
    if quant >= 25:
        score.dims["quantities"] = (PASS, f"{quant} value+unit quantities")
    elif quant > 0:
        score.dims["quantities"] = (
            PARTIAL,
            f"{quant} value+unit quantities (electrode/electrolyte level; cell- and "
            "material-level source quantities not yet mapped)",
        )
    else:
        score.dims["quantities"] = (FAIL, "no quantities recovered")

    # Components — standalone component specs vs. reduced to basis strings.
    comp_specs = sum(1 for r in records if _kind_of(r) in COMPONENT_KINDS)
    basis = cs.get("positive_electrode_basis") or cs.get("negative_electrode_basis")
    if comp_specs > 0:
        score.dims["components"] = (PASS, f"{comp_specs} component specs (materials/electrodes/electrolytes)")
    elif basis:
        score.dims["components"] = (
            PARTIAL,
            "reduced to electrode basis strings; the component tree and its composition "
            "quantities are not extracted into component specs",
        )
    else:
        score.dims["components"] = (FAIL, "no component data recovered")

    # Canonical JSON-LD — every record validates and emits domain-battery JSON-LD.
    n_valid = 0
    n_jsonld = 0
    for r in records:
        try:
            if validate_record(r).ok:
                n_valid += 1
        except Exception:  # noqa: BLE001
            pass
        try:
            to_jsonld(r, target="domain-battery")
            n_jsonld += 1
        except Exception:  # noqa: BLE001
            pass
    if n_valid == n_records and n_jsonld == n_records and n_records:
        score.dims["canonical"] = (PASS, f"all {n_records} records validate and emit canonical JSON-LD")
    elif n_valid or n_jsonld:
        score.dims["canonical"] = (PARTIAL, f"{n_valid}/{n_records} validate, {n_jsonld}/{n_records} emit JSON-LD")
    else:
        score.dims["canonical"] = (FAIL, "no record validated or emitted JSON-LD")

    score.metrics = {
        "records": n_records, "quantities": quant, "component_specs": comp_specs,
        "cell_format": fmt, "validate": f"{n_valid}/{n_records}", "jsonld": f"{n_jsonld}/{n_records}",
    }
    return score


def score_all() -> list[SourceScore]:
    return [_score(src) for src in SOURCES]


# --- page generation ----------------------------------------------------------
IMPORTER = {
    "converter": "battinfo.interop.import_converter_package",
    "discovery": "battinfo.interop.import_discovery_eln",
}

DIMENSION_HELP = {
    "ingest": "the file parses, tolerating the bare `NaN` some emitters write for empty ids",
    "normalize": "the document's shape is recognised and a canonical cell spec comes out",
    "identity": "cell identity is recovered (id, name, format; manufacturer/chemistry/model where present)",
    "quantities": "measured value+unit quantities are recovered into the canonical records",
    "components": "electrodes, materials, and electrolytes come out as standalone component specs",
    "canonical": "every record validates against the canonical schema and emits BattINFO JSON-LD",
}

INTRO = """\
These are **real, non-canonical** JSON-LD documents produced by external tools —
the BattInfoConverter Excel export across six versions, two EMPA converter
exports, and the Discovery RO-Crate — run through BattINFO's interop importers.
The scorecard measures how completely each one is normalized into canonical
BattINFO records and JSON-LD. They are test inputs, not examples to copy.

The scores come from `scripts/gen_interop_recovery.py` and are asserted by
`tests/test_interop_recovery.py`, so a drop in recovery quality fails CI and
changes a cell here. This page is generated; regenerate it with
`uv run python scripts/gen_interop_recovery.py`.
"""


def _summary_glyphs(score: SourceScore) -> str:
    return "".join(GLYPH[score.dims[dim][0]] for dim, _ in DIMENSIONS)


def build() -> str:
    scores = score_all()
    tally = {PASS: 0, PARTIAL: 0, FAIL: 0}
    for s in scores:
        for dim, _ in DIMENSIONS:
            tally[s.dims[dim][0]] += 1
    total = len(scores) * len(DIMENSIONS)

    lines: list[str] = []
    lines.append("<!-- GENERATED by scripts/gen_interop_recovery.py — do not edit. -->")
    lines.append("<!-- Regenerate: uv run python scripts/gen_interop_recovery.py -->")
    lines.append("")
    lines.append("# Interop recovery scorecard")
    lines.append("")
    lines.append(INTRO)
    lines.append(
        f"Across {len(scores)} sources and {len(DIMENSIONS)} dimensions: "
        f"{GLYPH[PASS]} {tally[PASS]} full · {GLYPH[PARTIAL]} {tally[PARTIAL]} partial · "
        f"{GLYPH[FAIL]} {tally[FAIL]} none, out of {total}."
    )
    lines.append("")
    lines.append(f"Legend: {GLYPH[PASS]} full · {GLYPH[PARTIAL]} partial · {GLYPH[FAIL]} none.")
    lines.append("")

    # Matrix.
    head = ["Source", "Shape", *[t for _, t in DIMENSIONS]]
    lines.append("| " + " | ".join(head) + " |")
    lines.append("|" + "|".join(["---"] * len(head)) + "|")
    for s in scores:
        cells = [f"**{s.label}**", f"`{s.shape}`"]
        cells += [GLYPH[s.dims[dim][0]] for dim, _ in DIMENSIONS]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    # What each column means.
    lines.append("## What the columns mean")
    lines.append("")
    for dim, title in DIMENSIONS:
        lines.append(f"- **{title}** — {DIMENSION_HELP[dim]}.")
    lines.append("")

    # Per-source detail.
    lines.append("## Per-source detail")
    lines.append("")
    for s in scores:
        lines.append(f":::{{dropdown}} {_summary_glyphs(s)}  {s.label}")
        lines.append(f"**Fixture:** `{s.fixture}`  ")
        lines.append(f"**Importer:** `{IMPORTER.get(s.family, s.family)}`  ")
        lines.append(f"**Shape in:** `{s.shape}`" + (f" · **records out:** {s.metrics.get('records')}" if s.metrics else ""))
        lines.append("")
        if s.error:
            lines.append(f"Failed before scoring: `{s.error}`")
            lines.append("")
        for dim, title in DIMENSIONS:
            rating, detail = s.dims[dim]
            lines.append(f"- {GLYPH[rating]} **{title}** — {detail}.")
        lines.append(":::")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write() -> None:
    OUT.write_text(build(), encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    import sys

    if "--debug" in sys.argv:
        ABBR = {PASS: "GRN", PARTIAL: "YEL", FAIL: "RED"}
        for s in score_all():
            print(f"\n{s.label}  [{s.shape}]  {s.metrics}")
            for dim, title in DIMENSIONS:
                r, detail = s.dims[dim]
                print(f"   {ABBR[r]} {title:18} {detail}")
    else:
        write()
