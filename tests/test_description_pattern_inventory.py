"""Description-pattern drift gate: every physical-payload touchpoint is known.

The description pattern moved all physical payload (hasProperty, composition
relations) onto the described individual under isDescriptionFor. The refactor
that completed it converted every WRITER and missed several READERS — the
workbench rendered empty datasheets, load_publication silently returned {},
the /create page taught the retired shape. The systemic hole: nothing tripped
when a file touched the physical vocabulary without knowing about the pattern.

This gate closes it. Every file under src/battinfo and web that mentions a
physical-payload key must appear in the waiver table below with a reason —
either "description-aware" (it handles the isDescriptionFor location) or an
explicit external-document justification. A new touchpoint fails this test
until it is reviewed and added.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_PHYSICAL_KEYS = (
    "hasProperty",
    "hasPositiveElectrode",
    "hasNegativeElectrode",
    "hasWorkingElectrode",
    "hasCounterElectrode",
    "hasReferenceElectrode",
    "hasElectrolyte",
    "hasSeparator",
    "hasActiveMaterial",
    "hasConstituent",
    "hasCase",
)
_PATTERN = re.compile("|".join(_PHYSICAL_KEYS))

# path (POSIX, repo-relative) -> why this file may touch physical keys.
WAIVERS: dict[str, str] = {
    # Emitters and the shared builder: they WRITE the canonical shape.
    "src/battinfo/transform/json_to_jsonld.py": "canonical emitter (writes the described-side shape)",
    "src/battinfo/transform/cell_spec_node.py": "canonical spec-node builder (writes the described-side shape)",
    "src/battinfo/jsonld.py": "record_to_jsonld dispatch + test emitter (description-aware)",
    # Readers taught the described-side location with legacy fallback.
    "src/battinfo/ws.py": "package importer reads described side first with old-shape fallback",
    "src/battinfo/bundle.py": "from_jsonld reads described side first with old-shape fallback",
    # External-document readers: these parse THIRD-PARTY graphs whose shape is
    # not ours (BattINFO Converter exports, Discovery RO-Crates, BDC bundles).
    "src/battinfo/interop/converter.py": "reads BattINFO Converter documents (external shape)",
    "src/battinfo/interop/_converter_components.py": "reads BattINFO Converter documents (external shape)",
    "src/battinfo/interop/discovery.py": "reads Discovery-Benchmark RO-Crates (external shape)",
    # Web surfaces taught the described-side location.
    "web/lib/jsonld-workbench.ts": "reads described side first with top-level fallback",
    "web/lib/create-model.ts": "teaching emitter (writes the described-side shape)",
    "web/components/jsonld-graph.tsx": "generic graph walker (shape-agnostic, depth covers the extra level)",
    "web/scripts/check-create-model-terms.ts": "shape guard for the create-model emitter",
    "web/scripts/check-jsonld-workbench.ts": "CI check exercising the canonical (described-side) example",
    # Vocabulary tables, not graph readers.
    "src/battinfo/electrodes.py": "role -> relation vocabulary table (no graph access)",
}


def _scan_roots() -> list[Path]:
    files: list[Path] = []
    files.extend((ROOT / "src" / "battinfo").rglob("*.py"))
    for sub in ("lib", "components", "scripts"):
        base = ROOT / "web" / sub
        if base.exists():
            files.extend(base.rglob("*.ts"))
            files.extend(base.rglob("*.tsx"))
    return files


def test_every_physical_key_touchpoint_is_waived() -> None:
    touching: set[str] = set()
    for path in _scan_roots():
        if ".generated" in path.name:
            continue  # vendored context/schema/example mirrors, not logic
        text = path.read_text(encoding="utf-8", errors="replace")
        if _PATTERN.search(text):
            touching.add(path.relative_to(ROOT).as_posix())

    unwaived = sorted(touching - set(WAIVERS))
    assert not unwaived, (
        "Files touch physical-payload keys without a description-pattern "
        f"waiver: {unwaived}. Read the module docstring: teach the file the "
        "isDescriptionFor location (or justify it as an external-document "
        "reader), then add it to WAIVERS with the reason."
    )

    stale = sorted(set(WAIVERS) - touching)
    assert not stale, f"WAIVERS entries no longer touch physical keys — prune: {stale}"
