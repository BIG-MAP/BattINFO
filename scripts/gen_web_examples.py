"""Generate the website's "describe your thing" showcase from real authoring code.

Each showcase entry is a small snippet function below: its SOURCE is what the
/examples page displays, and its EXECUTION produces the record shown next to
it — so every example on the site is guaranteed to run against the current
library. Minted IRIs and timestamps are normalized to stable placeholders so
the committed output is deterministic; tests/test_web_generated.py
regenerates in memory and fails on drift.

Usage:
    uv run python scripts/gen_web_examples.py
"""
from __future__ import annotations

import inspect
import json
import re
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

OUT = ROOT / "web" / "lib" / "showcase.generated.ts"

NL = chr(10)


# ── Snippets: the code shown on the page IS the code that ran ────────────────

def snippet_material():
    from battinfo.authoring import material
    from battinfo.materials import material_spec_from_component

    nmc = material(
        "NMC811",
        molecular_formula="LiNi0.8Mn0.1Co0.1O2",
        mass_fraction={"value": 96, "unit": "%"},
    )

    # Lift it to a standalone, reusable material-spec record with its own IRI
    record = material_spec_from_component(nmc, material_class="active_material")
    return record


def snippet_electrode():
    from battinfo.authoring import bom, electrode, material

    cathode = electrode(
        bom=bom(
            active_material=material("NMC811", mass_fraction={"value": 96, "unit": "%"}),
            binder=material("PVDF", mass_fraction={"value": 2, "unit": "%"}),
            additive=material("Carbon black", mass_fraction={"value": 2, "unit": "%"}),
        ),
        loading={"value": 18.5, "unit": "mg/cm2"},
        calendered_density={"value": 3.4, "unit": "g/cm3"},
        current_collector="Aluminium foil",
    )
    record = cathode.model_dump(exclude_none=True)
    return record


def snippet_electrolyte():
    from battinfo.authoring import electrolyte_recipe, material

    lp30 = electrolyte_recipe(
        family="organic",
        salt=material("LiPF6", concentration={"value": 1.0, "unit": "mol/L"}),
        solvents=[
            material("EC", volume_fraction={"value": 50, "unit": "%"}),
            material("DMC", volume_fraction={"value": 50, "unit": "%"}),
        ],
        additives=[material("VC", mass_fraction={"value": 2.0, "unit": "%"})],
        comment="LP30 + 2% VC",
    )
    record = lp30.model_dump(exclude_none=True)
    return record


def snippet_separator():
    from battinfo.authoring import properties, separator_spec

    sep = separator_spec(
        material="Polypropylene",
        thickness={"value": 25.0, "unit": "µm"},
        properties=properties(porosity={"value": 41, "unit": "%"}),
        comment="Celgard 2500, single-layer PP",
    )
    record = sep.model_dump(exclude_none=True)
    return record


def snippet_cell_spec():
    from battinfo import CellSpec

    spec = CellSpec(
        # In the workspace flow the IRI is minted for you at ws.save();
        # standalone, you set it (or let publish() mint it).
        id="https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5",
        manufacturer="Samsung SDI",
        model="INR21700-50E",
        format="cylindrical",
        chemistry="Li-ion",
        positive_electrode_basis="NMC",
        negative_electrode_basis="graphite",
        properties={
            "nominal_capacity": {"value": 5.0, "unit": "Ah"},
            "nominal_voltage": {"value": 3.6, "unit": "V"},
            "mass": {"value": 68.0, "unit": "g"},
        },
        source={"type": "datasheet", "retrieved_at": 1750000000},
    )
    record = spec.to_record()
    return record


def snippet_cell():
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
        manufactured_at="2026-01-15",
    )
    record = cell.to_record()
    return record


def snippet_test_spec():
    from battinfo import TestSpec

    protocol = TestSpec(
        id="https://w3id.org/battinfo/spec/kxwy-5f5f-f682-hhch",
        name="1C cycle life at 25 °C",
        kind="cycling",
        experiment=[                       # PyBaMM syntax — runnable as-is
            "Charge at 1C until 4.2 V",
            "Hold at 4.2 V until C/20",
            "Discharge at 1C until 2.5 V",
            "Rest for 10 minutes",
        ],
        conditions={"ambient_temperature": {"value": 25.0, "unit": "degC"}},
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
        id="https://w3id.org/battinfo/test/6nec-h262-tthy-4rnt",
        cell=cell,                         # what you did, to which cell
        kind="capacity_check",
        protocol="C/10 constant-current discharge",
        instrument="Biologic VMP-300",
        status="completed",
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
        id="https://w3id.org/battinfo/test/6nec-h262-tthy-4rnt",
        cell=cell, kind="cycling", status="completed",
    )
    dataset = Dataset(
        id="https://w3id.org/battinfo/dataset/0rp6-kncv-cyem-qwcd",
        path="data/cycle-life-run",        # the folder with your measured files
        cell=cell,
        test=test,
        name="INR21700-50E cycle-life dataset",
        license="CC-BY-4.0",
        access_url="https://doi.org/10.5281/zenodo.1234567",  # where the data lives
    )
    record = dataset.to_record()
    return record


SHOWCASE = [
    {
        "slug": "material",
        "title": "A material",
        "tagline": "Any substance in the cell — actives, binders, salts, solvents — with its properties, reusable across every cell that contains it.",
        "recordType": None,
        "fn": snippet_material,
    },
    {
        "slug": "electrode",
        "title": "An electrode",
        "tagline": "A bill of materials plus the numbers that define the coating: loading, calendered density, current collector.",
        "recordType": None,
        "fn": snippet_electrode,
    },
    {
        "slug": "electrolyte",
        "title": "An electrolyte",
        "tagline": "Salt, solvents, and additives — all the same material(...) form, fractions and concentrations inline.",
        "recordType": None,
        "fn": snippet_electrolyte,
    },
    {
        "slug": "separator",
        "title": "A separator",
        "tagline": "Base material, thickness, porosity — and free text for what the numbers can't hold.",
        "recordType": None,
        "fn": snippet_separator,
    },
    {
        "slug": "cell-spec",
        "title": "A cell spec",
        "tagline": "The product datasheet, as data: identity, format, chemistry, and rated properties with units that resolve to EMMO.",
        "recordType": "cell-spec",
        "fn": snippet_cell_spec,
    },
    {
        "slug": "cell",
        "title": "A cell",
        "tagline": "One specific physical item with a serial number, permanently linked to the spec that describes it.",
        "recordType": None,
        "fn": snippet_cell,
    },
    {
        "slug": "test-spec",
        "title": "A test spec",
        "tagline": "The reusable procedure — steps in PyBaMM syntax a machine can re-run, conditions a human can check.",
        "recordType": None,
        "fn": snippet_test_spec,
    },
    {
        "slug": "test",
        "title": "A test",
        "tagline": "One execution of a procedure on one cell: instrument, status, and the link every dataset hangs off.",
        "recordType": "test",
        "fn": snippet_test,
    },
    {
        "slug": "dataset",
        "title": "A dataset",
        "tagline": "The measured files, linked to the cell and test that produced them — the shape data portals understand (DCAT).",
        "recordType": "dataset",
        "fn": snippet_dataset,
    },
]


# ── Determinism: normalize minted IRIs and clocks to stable placeholders ─────

UID_RE = re.compile(r"[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}")
PLACEHOLDER_UIDS = [
    "7d9k-2m4p-8t3x-6nq5", "y9xy-kr0v-y5tn-dfj7", "3w87-0ddf-ryjg-evxe",
    "kxwy-5f5f-f682-hhch", "6nec-h262-tthy-4rnt", "0rp6-kncv-cyem-qwcd",
    "me0t-k16f-eh5y-rq0k", "xcv1-hpy1-b0bw-z5s2", "s6y8-5mne-94gx-e5ve",
    "fm9p-sqkk-tbx3-rr66", "t4wz-ff8s-6vp6-af48", "7p3d-2e22-7yae-spyb",
]
TIME_KEYS = {
    "created_at", "modified_at", "published_at", "retrieved_at",
    "started_at", "ended_at", "issued_at", "saved_at",
}
FIXED_TIME = 1750000000


def normalize(record: dict) -> dict:
    text = json.dumps(record, ensure_ascii=False)
    seen: dict[str, str] = {}
    for uid in UID_RE.findall(text):
        if uid not in seen:
            if len(seen) >= len(PLACEHOLDER_UIDS):
                raise RuntimeError("placeholder uid pool exhausted")
            seen[uid] = PLACEHOLDER_UIDS[len(seen)]
    for real, fake in seen.items():
        text = text.replace(real, fake)
        text = text.replace(real.replace("-", ""), fake.replace("-", ""))
        text = text.replace(real.replace("-", "")[:6], fake.replace("-", "")[:6])
    doc = json.loads(text)

    def fix_times(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in TIME_KEYS and isinstance(value, (int, float)):
                    node[key] = FIXED_TIME
                else:
                    fix_times(value)
        elif isinstance(node, list):
            for item in node:
                fix_times(item)

    fix_times(doc)
    return doc


def snippet_source(fn) -> str:
    lines = inspect.getsource(fn).splitlines()
    body = lines[1:]  # drop "def ...():"
    while body and not body[0].strip():
        body.pop(0)
    if body and body[-1].strip() == "return record":
        body = body[:-1]
    while body and not body[-1].strip():
        body.pop()
    return textwrap.dedent(NL.join(body))


def build_entries() -> list[dict]:
    from battinfo import record_to_jsonld

    entries = []
    for item in SHOWCASE:
        record = normalize(item["fn"]())
        jsonld = (
            record_to_jsonld(record, item["recordType"]) if item["recordType"] else None
        )
        entries.append(
            {
                "slug": item["slug"],
                "title": item["title"],
                "tagline": item["tagline"],
                "recordType": item["recordType"],
                "code": snippet_source(item["fn"]),
                "record": record,
                "jsonld": jsonld,
            }
        )
    return entries


def render(entries: list[dict]) -> str:
    banner = (
        "// GENERATED by scripts/gen_web_examples.py — do not edit." + NL
        + "// Each entry's `code` is the literal source of a snippet function in that" + NL
        + "// script, and `record` is what executing it produced (IRIs/timestamps" + NL
        + "// normalized). tests/test_web_generated.py fails when this file drifts." + NL + NL
    )
    body = (
        "export const showcase: {" + NL
        + "  slug: string;" + NL
        + "  title: string;" + NL
        + "  tagline: string;" + NL
        + "  recordType: string | null;" + NL
        + "  code: string;" + NL
        + "  record: Record<string, unknown>;" + NL
        + "  jsonld: Record<string, unknown> | null;" + NL
        + "}[] = " + json.dumps(entries, indent=2, ensure_ascii=False) + ";" + NL
    )
    return banner + body


PUBLIC_DIR = ROOT / "web" / "public" / "jsonld"


def render_public(entries: list) -> dict:
    """Raw JSON-LD for showcase entries that have one, served at
    /jsonld/showcase-<slug>.jsonld so the W3C Playground can fetch them
    (CORS headers for /jsonld/* are set in web/vercel.json)."""
    return {
        f"showcase-{e['slug']}.jsonld": json.dumps(e["jsonld"], indent=2, ensure_ascii=False) + NL
        for e in entries
        if e["jsonld"] is not None
    }


def main() -> int:
    entries = build_entries()
    OUT.write_text(render(entries), encoding="utf-8", newline=NL)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    public = render_public(entries)
    for name, text in public.items():
        (PUBLIC_DIR / name).write_text(text, encoding="utf-8", newline=NL)
    print(f"Wrote {OUT} + {len(public)} public jsonld files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
