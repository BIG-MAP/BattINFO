"""Cross-record consistency QA for the canonical example corpus.

Checks invariants the JSON Schemas cannot express — the place content bugs hide:
IRI uniqueness, reference-type integrity, basis<->cathode<->material agreement,
cell<->housing format, electrolyte-family<->chemistry, per-chemistry value
plausibility, and JSON-LD emission. Prints a grouped report; exits 1 on ERROR.

    uv run python scripts/qa_consistency.py
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from battinfo.transform.json_to_jsonld import to_jsonld

EXAMPLES = Path("examples")
RECORD_KEYS = ("cell_spec", "cell_instance", "test", "test_spec", "dataset", "material_spec",
               "material", "electrode_spec", "electrode", "separator_spec", "separator",
               "current_collector_spec", "current_collector", "electrolyte_spec", "electrolyte",
               "housing_spec", "housing", "organization")

errors: list[str] = []
warnings: list[str] = []
info: list[str] = []

# ---- index every record by IRI ----
by_iri: dict[str, tuple[str, dict, Path]] = {}
records: list[tuple[str, dict, Path]] = []
for f in sorted(EXAMPLES.rglob("*.json")):
    doc = json.loads(f.read_text(encoding="utf-8"))
    key = next((k for k in RECORD_KEYS if k in doc), None)
    if key is None:
        continue
    body = doc[key]
    iri = body.get("id") if isinstance(body, dict) else None
    records.append((key, doc, f))
    if iri:
        if iri in by_iri:
            errors.append(f"DUPLICATE IRI {iri}: {f.name} and {by_iri[iri][2].name}")
        by_iri[iri] = (key, doc, f)


def ns_of(iri: str) -> str:
    return iri.rstrip("/").split("/")[-2] if iri.count("/") >= 2 else ""


# namespace -> the record key(s) it should resolve to
NS_KEYS = {
    "material-spec": {"material_spec"}, "material": {"material"},
    "electrode-spec": {"electrode_spec"}, "electrode": {"electrode"},
    "electrolyte-spec": {"electrolyte_spec"}, "electrolyte": {"electrolyte"},
    "separator-spec": {"separator_spec"}, "separator": {"separator"},
    "current-collector-spec": {"current_collector_spec"}, "current-collector": {"current_collector"},
    "housing-spec": {"housing_spec"}, "housing": {"housing"},
    "spec": {"cell_spec", "test_spec"}, "cell": {"cell_instance"}, "test": {"test"},
    "dataset": {"dataset"}, "organization": {"organization"},
}


def check_ref(iri, ctx, expect_ns=None):
    if not isinstance(iri, str):
        return
    if iri not in by_iri:
        errors.append(f"DANGLING REF {ctx}: {iri} resolves to no record")
        return
    key = by_iri[iri][0]
    ns = ns_of(iri)
    if expect_ns and ns != expect_ns:
        errors.append(f"WRONG-NS REF {ctx}: {iri} (expected namespace {expect_ns})")
    elif ns in NS_KEYS and key not in NS_KEYS[ns]:
        errors.append(f"WRONG-TYPE REF {ctx}: {iri} -> {key}")


# ---- per-chemistry plausibility bands ----
V_BANDS = {"LFP": (3.0, 3.4), "NMC811": (3.5, 3.95), "NMC622": (3.5, 3.95), "LCO": (3.6, 4.0),
           "LMFP": (3.5, 4.0), "LNMO": (4.4, 4.95), "MnO2": (1.2, 1.7)}
CAP_BANDS = {"Graphite": (300, 375), "LFP": (140, 175), "NMC811": (180, 215), "NMC622": (160, 195),
             "LCO": (135, 165), "LMFP": (140, 165), "LNMO": (125, 150), "Zinc": (750, 850), "MnO2": (260, 320)}


def active_material(electrode_spec_doc):
    """(name, material_spec_id) of an electrode-spec's first active material."""
    comp = electrode_spec_doc.get("electrode_spec", {}).get("coating", {}).get("component", {})
    am = (comp.get("active_material") or [{}])[0]
    return am.get("name"), am.get("material_spec_id")


referenced: set[str] = set()

for key, doc, f in records:
    body = doc[key]

    # material-spec specific_capacity plausibility
    if key == "material_spec":
        name = body.get("name")
        cap = (body.get("property") or {}).get("specific_capacity", {}).get("value")
        if name in CAP_BANDS and isinstance(cap, (int, float)):
            lo, hi = CAP_BANDS[name]
            if not (lo <= cap <= hi):
                warnings.append(f"PLAUSIBILITY {f.name}: {name} specific_capacity {cap} mAh/g outside [{lo},{hi}]")

    # cell-spec: refs + basis<->cathode<->material + format<->housing + electrolyte<->chemistry + voltage
    if key == "cell_spec":
        cs = body
        model = cs.get("model", f.name)
        for fld, ns in (("positive_electrode_spec_id", "electrode-spec"),
                        ("negative_electrode_spec_id", "electrode-spec"),
                        ("electrolyte_spec_id", "electrolyte-spec"),
                        ("separator_spec_id", "separator-spec"),
                        ("housing_spec_id", "housing-spec")):
            ref = doc.get(fld)
            if ref:
                check_ref(ref, f"{model}.{fld}", ns)
                referenced.add(ref)
        mid = cs.get("manufacturer", {})
        if isinstance(mid, dict) and mid.get("id"):
            check_ref(mid["id"], f"{model}.manufacturer.id", "organization")
            referenced.add(mid["id"])

        # basis <-> cathode active <-> material name
        pos_ref = doc.get("positive_electrode_spec_id")
        basis = (cs.get("positive_electrode_basis") or "").strip().lower()
        if pos_ref in by_iri and basis:
            am_name, am_mat = active_material(by_iri[pos_ref][1])
            if am_name and am_name.strip().lower() != basis:
                warnings.append(f"BASIS-MISMATCH {model}: basis '{basis}' != cathode active '{am_name}'")
            if am_mat in by_iri:
                mname = by_iri[am_mat][1].get("material_spec", {}).get("name", "")
                if am_name and mname and am_name.strip().lower() != mname.strip().lower():
                    warnings.append(f"ACTIVE-MATERIAL-MISMATCH {model}: cathode active '{am_name}' != material-spec '{mname}'")

        # cell format <-> housing format
        hs_ref = doc.get("housing_spec_id")
        fmt = cs.get("cell_format")
        if hs_ref in by_iri and fmt:
            hfmt = by_iri[hs_ref][1].get("housing_spec", {}).get("cell_format")
            if hfmt and hfmt != fmt:
                warnings.append(f"FORMAT-MISMATCH {model}: cell_format '{fmt}' != housing '{hfmt}'")

        # electrolyte family <-> chemistry
        el_ref = doc.get("electrolyte_spec_id")
        chem = (cs.get("chemistry") or "").lower()
        if el_ref in by_iri:
            fam = by_iri[el_ref][1].get("electrolyte_spec", {}).get("family")
            if "zn" in chem and fam != "aqueous":
                warnings.append(f"ELECTROLYTE-MISMATCH {model}: {chem} chemistry but electrolyte family '{fam}'")
            if "li-ion" in chem and fam not in (None, "organic"):
                warnings.append(f"ELECTROLYTE-MISMATCH {model}: Li-ion but electrolyte family '{fam}'")

        # nominal voltage plausibility per cathode basis
        volt = (doc.get("properties") or {}).get("nominal_voltage", {}).get("value")
        pos_basis = cs.get("positive_electrode_basis")
        if pos_basis in V_BANDS and isinstance(volt, (int, float)):
            lo, hi = V_BANDS[pos_basis]
            if not (lo <= volt <= hi):
                warnings.append(f"PLAUSIBILITY {model}: nominal_voltage {volt} V outside {pos_basis} band [{lo},{hi}]")

    # instance -> spec refs + electrode coating material refs
    for fld in ("material_spec_id", "electrode_spec_id", "electrolyte_spec_id", "separator_spec_id",
                "current_collector_spec_id", "housing_spec_id", "cell_spec_id"):
        if isinstance(body, dict) and body.get(fld):
            check_ref(body[fld], f"{f.name}.{fld}")
            referenced.add(body[fld])
    if key == "test":
        for fld in ("cell_id", "protocol_id"):
            if body.get(fld):
                check_ref(body[fld], f"{f.name}.{fld}")
                referenced.add(body[fld])

    # JSON-LD emission (skip organization — not a domain-battery node)
    if key not in ("organization",):
        try:
            to_jsonld(doc, target="domain-battery")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"JSON-LD FAIL {f.name}: {exc}")

# orphan specs (info only)
for key, doc, f in records:
    body = doc[key]
    if key.endswith("_spec") and isinstance(body, dict):
        iri = body.get("id")
        if iri and iri not in referenced:
            info.append(f"UNREFERENCED {key} {body.get('name','?')} ({f.name})")

print("=" * 72)
print(f"QA CONSISTENCY — {len(records)} records, {len(by_iri)} unique IRIs")
print("=" * 72)
for label, items in (("ERRORS", errors), ("WARNINGS", warnings), ("INFO (orphans)", info)):
    print(f"\n{label}: {len(items)}")
    for x in items:
        print("  -", x)

sys.exit(1 if errors else 0)
