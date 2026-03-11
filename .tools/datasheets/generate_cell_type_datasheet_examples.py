from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE_DIR = ROOT / "src" / "battinfo" / "data" / "examples" / "cells-clean"
DEFAULT_TARGET_DIR = ROOT / ".battinfo" / "datasheets" / "generated-cell-types"
DEFAULT_REVIEW_PATH = DEFAULT_TARGET_DIR / "CELLINFO_TOP10_REVIEW.md"
DEFAULT_QA_PATH = DEFAULT_TARGET_DIR / "CELLINFO_TOP10_QA.md"


SPEC_KEY_MAP = {
    "charge_voltage": "charging_voltage",
    "discharge_cutoff_voltage": "discharging_cutoff_voltage",
    "discharge_current": "discharging_current",
    "max_discharge_current": "max_discharging_current",
    "continuous_discharge_current": "continuous_discharging_current",
    "max_charge_current": "max_charging_current",
    "weight": "mass",
    "impedance": "internal_resistance",
    "storage_temperature_range": "storage_temperature",
    "minimum_capacity": "min_capacity",
}


ALLOWED_SPECS = {
    "nominal_capacity",
    "rated_capacity",
    "min_capacity",
    "nominal_energy",
    "nominal_specific_energy",
    "nominal_energy_density",
    "nominal_voltage",
    "charging_voltage",
    "discharging_cutoff_voltage",
    "charging_current",
    "max_charging_current",
    "discharging_current",
    "continuous_discharging_current",
    "max_discharging_current",
    "cycle_life",
    "internal_resistance",
    "mass",
    "height",
    "width",
    "length",
    "thickness",
    "diameter",
    "operating_temperature_charging",
    "operating_temperature_discharging",
    "storage_temperature",
}


UNIT_NORMALIZATION = {
    "g": "g",
    "kg": "kg",
    "v": "V",
    "a": "A",
    "ah": "Ah",
    "wh": "Wh",
    "count": "count",
    "mm": "mm",
    "cm": "cm",
    "m": "m",
    "ohm": "ohm",
    "mohm": "milliohm",
    "mω": "milliohm",
    "mΩ": "milliohm",
    "Ω": "ohm",
    "°c": "degC",
    "℃": "degC",
    "degc": "degC",
    "c": "C",
    "ma": "mA",
    "mg/cm2": "mg/cm^2",
    "g/cm3": "g/cm^3",
}


LI_ION_ELECTRODE_TOKENS = {
    "lfp",
    "lco",
    "lmo",
    "nca",
    "nmc",
    "nmc/lmo",
    "nmca",
    "lnmo",
    "lto",
}


FORMAT_ALLOWED = {"cylindrical", "prismatic", "pouch", "coin", "other", "unknown"}


SPEC_LABELS = {
    "nominal_capacity": "Nominal capacity",
    "rated_capacity": "Rated capacity",
    "min_capacity": "Minimum capacity",
    "nominal_energy": "Nominal energy",
    "nominal_specific_energy": "Nominal specific energy",
    "nominal_energy_density": "Nominal energy density",
    "nominal_voltage": "Nominal voltage",
    "charging_voltage": "Charging voltage",
    "discharging_cutoff_voltage": "Discharging cutoff voltage",
    "charging_current": "Charging current",
    "max_charging_current": "Max charging current",
    "discharging_current": "Discharging current",
    "continuous_discharging_current": "Continuous discharging current",
    "max_discharging_current": "Max discharging current",
    "cycle_life": "Cycle life",
    "internal_resistance": "Internal resistance",
    "mass": "Mass",
    "height": "Height",
    "width": "Width",
    "length": "Length",
    "thickness": "Thickness",
    "diameter": "Diameter",
    "operating_temperature_charging": "Operating temperature (charging)",
    "operating_temperature_discharging": "Operating temperature (discharging)",
    "storage_temperature": "Storage temperature",
}


SPEC_GROUPS: list[tuple[str, list[str]]] = [
    (
        "Key Performance",
        [
            "nominal_capacity",
            "rated_capacity",
            "min_capacity",
            "nominal_energy",
            "nominal_specific_energy",
            "nominal_energy_density",
            "nominal_voltage",
            "cycle_life",
            "mass",
            "internal_resistance",
        ],
    ),
    (
        "Electrical Limits",
        [
            "charging_voltage",
            "discharging_cutoff_voltage",
            "charging_current",
            "max_charging_current",
            "discharging_current",
            "continuous_discharging_current",
            "max_discharging_current",
        ],
    ),
    ("Dimensions", ["height", "width", "length", "thickness", "diameter"]),
    (
        "Temperature",
        ["operating_temperature_charging", "operating_temperature_discharging", "storage_temperature"],
    ),
]


class Candidate:
    def __init__(self, path: Path, doc: dict[str, Any]) -> None:
        self.path = path
        self.doc = doc
        cell = doc.get("cell", {})
        self.model_name = str(cell.get("model_name") or "unknown-model")
        self.manufacturer = str(cell.get("manufacturer") or "Unknown")
        self.format = str(cell.get("format") or "unknown")
        self.electrode_basis = str(cell.get("chemistry") or "unknown")
        self.chemistry = _infer_chemistry_family(self.electrode_basis, self.model_name)
        self.spec_count = len(doc.get("specs", {})) if isinstance(doc.get("specs"), dict) else 0


class GenerationResult:
    def __init__(self, source: Path, uid: str, datasheet: dict[str, Any], skipped_specs: list[str]) -> None:
        self.source = source
        self.uid = uid
        self.datasheet = datasheet
        self.skipped_specs = skipped_specs


def _infer_negative_electrode_basis(
    chemistry_family: str, positive_electrode_basis: str, model_name: str
) -> tuple[str, dict[str, str] | None]:
    chemistry = chemistry_family.strip().lower()
    positive = positive_electrode_basis.strip().lower()
    model = model_name.strip().lower()
    merged = f"{chemistry} {positive} {model}"

    if chemistry != "li-ion":
        return "unknown", None

    if "lto" in merged or "titanate" in merged:
        return "LTO", {
            "rule_id": "li_ion_lto_signature",
            "confidence": "heuristic-medium",
            "source": "rule-based",
        }

    graphite_signatures = ("inr", "icr", "ncr", "imr", "ifr", "nmc", "nca", "lco", "lmo", "lfp")
    if any(token in merged for token in graphite_signatures):
        confidence = "heuristic-medium" if any(token in model for token in ("inr", "icr", "ncr", "imr", "ifr")) else "heuristic-low"
        return "Graphite", {
            "rule_id": "li_ion_graphite_default",
            "confidence": confidence,
            "source": "rule-based",
        }

    return "Graphite", {
        "rule_id": "li_ion_graphite_fallback",
        "confidence": "heuristic-low",
        "source": "rule-based",
    }


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _infer_chemistry_family(raw: str, model_name: str = "") -> str:
    token = raw.strip().lower()
    model_token = model_name.strip().lower()
    merged = f"{token} {model_token}"

    if token in LI_ION_ELECTRODE_TOKENS:
        return "Li-ion"
    if any(prefix in merged for prefix in ("nmc", "ncm", "lfp", "lco", "lmo", "nca", "lto", "li-")):
        return "Li-ion"
    if any(code in merged for code in (" inr", " icr", " ncr", " ifr", " imr", " lir")):
        return "Li-ion"
    if "na" in merged:
        return "Na-ion"
    if "zn" in merged:
        return "Zn-based"
    return "unknown"


def _normalize_unit(unit: Any) -> str | None:
    if not isinstance(unit, str):
        return None
    token = unit.strip()
    if not token:
        return None
    return UNIT_NORMALIZATION.get(token.lower(), token)


def _uid_from_cell_id(cell_id: str) -> str:
    return cell_id.rstrip("/").split("/")[-1]


def _short_id(uid: str) -> str:
    return uid.replace("-", "")[:6]


def _normalize_spec_item(key: str, item: Any) -> tuple[str | None, dict[str, Any] | None]:
    out_key = SPEC_KEY_MAP.get(key, key)
    if out_key not in ALLOWED_SPECS:
        return None, None
    if not isinstance(item, dict):
        return None, None

    out: dict[str, Any] = {}
    for field in ("value", "value_min", "value_max", "value_typical", "value_text"):
        if field in item:
            out[field] = item[field]

    # Support range structures from parsed datasheets.
    if "min" in item and isinstance(item["min"], dict) and "value" in item["min"]:
        out["value_min"] = item["min"]["value"]
        if "unit" not in out and "unit" in item["min"]:
            out["unit"] = item["min"]["unit"]
    if "max" in item and isinstance(item["max"], dict) and "value" in item["max"]:
        out["value_max"] = item["max"]["value"]
        if "unit" not in out and "unit" in item["max"]:
            out["unit"] = item["max"]["unit"]

    if "unit" not in out and "unit" in item:
        out["unit"] = item["unit"]

    normalized_unit = _normalize_unit(out.get("unit"))
    if normalized_unit is None:
        return None, None
    out["unit"] = normalized_unit

    if out_key == "mass" and out.get("unit") == "g" and "value" in out:
        out["value"] = float(out["value"]) / 1000.0
        out["unit"] = "kg"

    has_value = any(k in out for k in ("value", "value_min", "value_max", "value_typical", "value_text"))
    if not has_value:
        return None, None

    return out_key, out


def _iter_candidates(source_dir: Path) -> list[Candidate]:
    candidates: list[Candidate] = []
    for source in sorted(source_dir.glob("*.json")):
        doc = _load_json(source)
        source_id = str(doc.get("provenance", {}).get("source_id", ""))
        if not source_id.startswith("cellinfo:"):
            continue
        candidates.append(Candidate(source, doc))
    return candidates


def _select_first(candidates: list[Candidate], count: int) -> list[Candidate]:
    return candidates[:count]


def _select_diverse(candidates: list[Candidate], count: int) -> list[Candidate]:
    remaining = candidates[:]
    selected: list[Candidate] = []
    seen_manufacturers: set[str] = set()
    seen_chemistry: set[str] = set()
    seen_format: set[str] = set()

    while remaining and len(selected) < count:
        best = None
        best_score = None
        for cand in remaining:
            score = 0.0
            if cand.manufacturer not in seen_manufacturers:
                score += 3.0
            if cand.chemistry not in seen_chemistry:
                score += 2.0
            if cand.format not in seen_format:
                score += 1.0
            score += min(cand.spec_count, 20) / 100.0
            tie_break = cand.path.name
            if best is None or score > best_score[0] or (score == best_score[0] and tie_break < best_score[1]):
                best = cand
                best_score = (score, tie_break)

        if best is None:
            break
        selected.append(best)
        seen_manufacturers.add(best.manufacturer)
        seen_chemistry.add(best.chemistry)
        seen_format.add(best.format)
        remaining.remove(best)

    if len(selected) < count:
        for cand in candidates:
            if cand in selected:
                continue
            selected.append(cand)
            if len(selected) >= count:
                break

    return selected[:count]


def _format_number(value: Any) -> str:
    if isinstance(value, float):
        text = f"{value:.6g}"
        return text
    return str(value)


def _spec_value_str(item: dict[str, Any]) -> str:
    if "value" in item:
        return _format_number(item["value"])
    if "value_typical" in item:
        return f"{_format_number(item['value_typical'])} (typ)"
    if "value_min" in item and "value_max" in item:
        return f"{_format_number(item['value_min'])} .. {_format_number(item['value_max'])}"
    if "value_min" in item:
        return f">= {_format_number(item['value_min'])}"
    if "value_max" in item:
        return f"<= {_format_number(item['value_max'])}"
    if "value_text" in item:
        return str(item["value_text"])
    return "-"


def _spec_label(key: str) -> str:
    if key in SPEC_LABELS:
        return SPEC_LABELS[key]
    return key.replace("_", " ").capitalize()


def _build_datasheet(candidate: Candidate, batch_tag: str, infer_negative_electrode_basis: bool = False) -> GenerationResult:
    doc = candidate.doc
    source_file = candidate.path.name
    cell = doc.get("cell", {})
    specs = doc.get("specs", {})
    provenance = doc.get("provenance", {})
    quality = doc.get("quality", {})

    model_name = str(cell.get("model_name") or "unknown-model")
    manufacturer = str(cell.get("manufacturer") or "Unknown")
    cell_format = str(cell.get("format") or "unknown")
    cell_id = str(cell.get("id") or "")
    uid = _uid_from_cell_id(cell_id)

    out_specs: dict[str, Any] = {}
    skipped_specs: list[str] = []
    if isinstance(specs, dict):
        for key, item in specs.items():
            mapped_key, mapped_item = _normalize_spec_item(str(key), item)
            if mapped_key is None or mapped_item is None:
                skipped_specs.append(str(key))
                continue
            out_specs[mapped_key] = mapped_item

    out_quality = {
        "missing_fields": list(quality.get("missing_fields", [])),
        "inferred_fields": list(quality.get("inferred_fields", [])),
        "warnings": list(quality.get("warnings", [])),
    }
    if skipped_specs:
        out_quality["warnings"].append(
            "Skipped source specs not yet mapped to standard keys: " + ", ".join(sorted(set(skipped_specs)))
        )

    negative_basis = "unknown"
    enrichment_negative: dict[str, str] | None = None
    if infer_negative_electrode_basis:
        negative_basis, enrichment_negative = _infer_negative_electrode_basis(
            chemistry_family=candidate.chemistry,
            positive_electrode_basis=candidate.electrode_basis,
            model_name=model_name,
        )

    out: dict[str, Any] = {
        "version": "1.0.0-draft",
        "status": "draft",
        "product": {
            "type": "Product",
            "identifier": cell_id,
            "short_id": _short_id(uid),
            "name": model_name,
            "description": f"Draft cell-type datasheet derived from CellInfo source record {provenance.get('source_id', source_file)}.",
            "brand": manufacturer,
            "manufacturer": manufacturer,
            "model": model_name,
            "chemistry": candidate.chemistry,
            "positive_electrode_basis": candidate.electrode_basis,
            "negative_electrode_basis": negative_basis,
            "format": cell_format if cell_format in FORMAT_ALLOWED else "unknown",
            "category": f"{cell_format} battery cell" if cell_format else "battery cell",
            "application": "battery cell",
        },
        "specs": out_specs,
        "lineage": {
            "source_record": f"src/battinfo/data/examples/cells-clean/{source_file}",
            "source_type": provenance.get("source_type", "other"),
            "source_file": provenance.get("source_file", source_file),
            "source_id": provenance.get("source_id"),
            "source_url": provenance.get("source_url"),
            "extracted_at": provenance.get("extracted_at"),
        },
        "quality": out_quality,
        "notes": [
            "Draft v1 datasheet generated from BattINFO canonical cells-clean record.",
            "This is not an original manufacturer PDF datasheet.",
            "Capacity convention: if both typical and rated capacities are available, keep typical in specs.nominal_capacity.value_typical and rated in specs.rated_capacity.value.",
            "Electrode-basis fields can be more specific than chemistry family.",
        ],
        "extensions": {
            "x-battinfo-ingest_batch": batch_tag,
        },
    }

    if enrichment_negative is not None:
        inferred = "product.negative_electrode_basis"
        if inferred not in out_quality["inferred_fields"]:
            out_quality["inferred_fields"].append(inferred)
        out["notes"].append("Negative electrode basis inferred using a conservative heuristic rule; verify during curation.")
        out["extensions"]["x-battinfo-enrichment"] = {
            "negative_electrode_basis": {
                "applied": True,
                **enrichment_negative,
            }
        }
    elif infer_negative_electrode_basis:
        out["extensions"]["x-battinfo-enrichment"] = {
            "negative_electrode_basis": {
                "applied": False,
                "reason": "no_rule_matched",
                "source": "rule-based",
            }
        }

    source_url = provenance.get("source_url")
    if isinstance(source_url, str) and source_url:
        out["references"] = [
            {
                "type": "database",
                "title": str(provenance.get("source_file") or source_file),
                "url": source_url,
                "accessed_at": provenance.get("extracted_at"),
            }
        ]

    return GenerationResult(source=candidate.path, uid=uid, datasheet=out, skipped_specs=sorted(set(skipped_specs)))


def _render_spec_table(spec_keys: list[str], specs: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    lines.append("| Property | Value | Unit |")
    lines.append("|---|---:|---|")
    for key in spec_keys:
        if key not in specs:
            continue
        item = specs[key]
        lines.append(f"| {_spec_label(key)} | {_spec_value_str(item)} | {item.get('unit', '')} |")
    return lines


def _render_markdown(doc: dict[str, Any]) -> str:
    product = doc["product"]
    specs = doc.get("specs", {})
    lineage = doc.get("lineage", {})
    quality = doc.get("quality", {})
    refs = doc.get("references", [])

    lines: list[str] = []
    lines.append("# BattINFO Cell-Type Datasheet (Draft)")
    lines.append("")
    lines.append("## Standard Metadata")
    lines.append("")
    lines.append(f"- Version: `{doc.get('version', '')}`")
    lines.append(f"- Status: `{doc.get('status', '')}`")
    lines.append("")
    lines.append("## Identity")
    lines.append("")
    lines.append(f"- Product identifier: `{product.get('identifier', '')}`")
    lines.append(f"- ShortID: `{product.get('short_id', '')}`")
    lines.append(f"- Product name: `{product.get('name', '')}`")
    lines.append(f"- Model: `{product.get('model', '')}`")
    lines.append(f"- Brand: `{product.get('brand', '')}`")
    lines.append(f"- Manufacturer: `{product.get('manufacturer', '')}`")
    lines.append(f"- Category: `{product.get('category', '')}`")
    lines.append(f"- Format: `{product.get('format', '')}`")
    lines.append("")
    lines.append("## Electrochemistry")
    lines.append("")
    lines.append(f"- Chemistry: `{product.get('chemistry', '')}`")
    lines.append(f"- Positive electrode basis: `{product.get('positive_electrode_basis', '')}`")
    lines.append(f"- Negative electrode basis: `{product.get('negative_electrode_basis', '')}`")
    lines.append("")

    for group_name, group_keys in SPEC_GROUPS:
        present = [k for k in group_keys if k in specs]
        if not present:
            continue
        lines.append(f"## {group_name}")
        lines.append("")
        lines.extend(_render_spec_table(present, specs))
        lines.append("")

    # Include non-grouped specs at the end for completeness.
    grouped = {k for _, keys in SPEC_GROUPS for k in keys}
    remainder = sorted(k for k in specs.keys() if k not in grouped)
    if remainder:
        lines.append("## Additional Specs")
        lines.append("")
        lines.extend(_render_spec_table(remainder, specs))
        lines.append("")

    lines.append("## Provenance")
    lines.append("")
    lines.append(f"- Source record: `{lineage.get('source_record', '')}`")
    lines.append(f"- Source type: `{lineage.get('source_type', '')}`")
    lines.append(f"- Source ID: `{lineage.get('source_id', '')}`")
    lines.append(f"- Source URL: `{lineage.get('source_url', '')}`")
    lines.append(f"- Extracted at: `{lineage.get('extracted_at', '')}`")
    lines.append("")
    lines.append("## Quality")
    lines.append("")
    missing = quality.get("missing_fields", []) or ["none"]
    inferred = quality.get("inferred_fields", []) or ["none"]
    warnings = quality.get("warnings", []) or ["none"]
    lines.append(f"- Missing fields: {', '.join(missing)}")
    lines.append(f"- Inferred fields: {', '.join(inferred)}")
    lines.append(f"- Warnings: {', '.join(warnings)}")
    if refs:
        lines.append("")
        lines.append("## References")
        lines.append("")
        for ref in refs:
            lines.append(f"- {ref.get('title', 'reference')}: `{ref.get('url', '')}`")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    for note in doc.get("notes", []):
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


def _spec_value_with_unit(specs: dict[str, Any], key: str) -> str:
    item = specs.get(key)
    if not isinstance(item, dict):
        return "-"
    if "value" not in item or "unit" not in item:
        return _spec_value_str(item)
    return f"{_format_number(item['value'])} {item['unit']}"


def _render_review(
    results: list[GenerationResult], strategy: str, batch_tag: str, infer_negative_electrode_basis: bool
) -> str:
    lines: list[str] = []
    lines.append(f"# CellInfo Conversion Review ({len(results)} records)")
    lines.append("")
    lines.append(
        "This batch contains CellInfo-derived records converted into BattINFO cell-type datasheet resources (`.json` + `.md`)."
    )
    lines.append("")
    lines.append(f"- Selection strategy: `{strategy}`")
    lines.append(f"- Batch tag: `{batch_tag}`")
    lines.append(f"- Negative electrode inference: `{'enabled' if infer_negative_electrode_basis else 'disabled'}`")
    lines.append("")
    lines.append("## Included Resources")
    lines.append("")
    lines.append("| UID | Model | Manufacturer | Format | Chemistry | Nominal Capacity | Nominal Voltage | Source Record |")
    lines.append("|---|---|---|---|---|---:|---:|---|")
    for result in results:
        doc = result.datasheet
        product = doc["product"]
        specs = doc.get("specs", {})
        lineage = doc.get("lineage", {})
        lines.append(
            "| `{uid}` | `{name}` | `{manufacturer}` | `{format}` | `{chemistry}` | `{cap}` | `{volt}` | `{source}` |".format(
                uid=result.uid,
                name=product.get("name", ""),
                manufacturer=product.get("manufacturer", ""),
                format=product.get("format", ""),
                chemistry=product.get("chemistry", ""),
                cap=_spec_value_with_unit(specs, "nominal_capacity"),
                volt=_spec_value_with_unit(specs, "nominal_voltage"),
                source=lineage.get("source_record", ""),
            )
        )
    lines.append("")
    lines.append("## File Pattern")
    lines.append("")
    lines.append("- JSON: `<target-dir>/<uid>.datasheet.json`")
    lines.append("- Markdown: `<target-dir>/<uid>.datasheet.md`")
    lines.append("")
    lines.append("Generated with:")
    lines.append("")
    lines.append("- `.tools/datasheets/generate_cell_type_datasheet_examples.py`")
    lines.append("")
    return "\n".join(lines)


def _render_qa(
    results: list[GenerationResult], strategy: str, batch_tag: str, infer_negative_electrode_basis: bool
) -> str:
    manufacturer_counter: Counter[str] = Counter()
    format_counter: Counter[str] = Counter()
    chemistry_counter: Counter[str] = Counter()
    spec_counter: Counter[str] = Counter()
    warning_counter: Counter[str] = Counter()
    skipped_counter: Counter[str] = Counter()

    unknown_manufacturer = 0
    unknown_chemistry = 0
    unknown_positive = 0
    unknown_negative = 0
    inferred_negative = 0
    empty_specs = 0

    for result in results:
        doc = result.datasheet
        product = doc["product"]
        specs = doc.get("specs", {})
        quality = doc.get("quality", {})
        manufacturer = str(product.get("manufacturer", "unknown"))
        chemistry = str(product.get("chemistry", "unknown"))
        fmt = str(product.get("format", "unknown"))

        manufacturer_counter[manufacturer] += 1
        chemistry_counter[chemistry] += 1
        format_counter[fmt] += 1

        if manufacturer.strip().lower() == "unknown":
            unknown_manufacturer += 1
        if chemistry.strip().lower() == "unknown":
            unknown_chemistry += 1
        if str(product.get("positive_electrode_basis", "unknown")).strip().lower() == "unknown":
            unknown_positive += 1
        if str(product.get("negative_electrode_basis", "unknown")).strip().lower() == "unknown":
            unknown_negative += 1
        if "product.negative_electrode_basis" in quality.get("inferred_fields", []):
            inferred_negative += 1

        if not isinstance(specs, dict) or not specs:
            empty_specs += 1
        else:
            for key in specs.keys():
                spec_counter[str(key)] += 1

        for warning in quality.get("warnings", []):
            warning_counter[str(warning)] += 1
        for skipped in result.skipped_specs:
            skipped_counter[skipped] += 1

    lines: list[str] = []
    lines.append(f"# CellInfo Conversion QA ({len(results)} records)")
    lines.append("")
    lines.append(f"- Selection strategy: `{strategy}`")
    lines.append(f"- Batch tag: `{batch_tag}`")
    lines.append(f"- Negative electrode inference: `{'enabled' if infer_negative_electrode_basis else 'disabled'}`")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Total records: `{len(results)}`")
    lines.append(f"- Empty specs blocks: `{empty_specs}`")
    lines.append(f"- Unknown manufacturer: `{unknown_manufacturer}`")
    lines.append(f"- Unknown chemistry: `{unknown_chemistry}`")
    lines.append(f"- Unknown positive electrode basis: `{unknown_positive}`")
    lines.append(f"- Unknown negative electrode basis: `{unknown_negative}`")
    lines.append(f"- Inferred negative electrode basis: `{inferred_negative}`")
    lines.append("")

    lines.append("## Distribution")
    lines.append("")
    lines.append("### Manufacturer")
    lines.append("")
    for name, count in sorted(manufacturer_counter.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"- `{name}`: `{count}`")
    lines.append("")
    lines.append("### Chemistry")
    lines.append("")
    for name, count in sorted(chemistry_counter.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"- `{name}`: `{count}`")
    lines.append("")
    lines.append("### Format")
    lines.append("")
    for name, count in sorted(format_counter.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"- `{name}`: `{count}`")
    lines.append("")

    lines.append("## Spec Coverage")
    lines.append("")
    lines.append("| Spec key | Present in records |")
    lines.append("|---|---:|")
    for key, count in sorted(spec_counter.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"| `{key}` | `{count}` |")
    lines.append("")

    lines.append("## Warnings")
    lines.append("")
    if warning_counter:
        for warning, count in sorted(warning_counter.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"- `{count}`x: {warning}")
    else:
        lines.append("- none")
    lines.append("")

    lines.append("## Unmapped Source Specs")
    lines.append("")
    if skipped_counter:
        for key, count in sorted(skipped_counter.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"- `{key}`: `{count}`")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate BattINFO datasheet examples from CellInfo-derived cells-clean records.")
    parser.add_argument("--count", type=int, default=10, help="Number of examples to generate (default: 10).")
    parser.add_argument(
        "--strategy",
        choices=["diverse", "first"],
        default="diverse",
        help="Selection strategy for choosing source examples (default: diverse).",
    )
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR, help="Source directory of cells-clean JSON.")
    parser.add_argument("--target-dir", type=Path, default=DEFAULT_TARGET_DIR, help="Target directory for datasheets.")
    parser.add_argument(
        "--batch-tag",
        type=str,
        default="cellinfo-batch-v1",
        help="Batch tag stored in extensions.x-battinfo-ingest_batch.",
    )
    parser.add_argument(
        "--infer-negative-electrode-basis",
        action="store_true",
        help="Infer product.negative_electrode_basis using conservative rule-based heuristics.",
    )
    parser.add_argument(
        "--clean-target",
        action="store_true",
        help="Remove existing *.datasheet.json/*.datasheet.md and review/qa markdown from target directory before writing.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show selected files but do not write outputs.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.count < 1:
        print("[ERROR] --count must be at least 1.")
        return 1

    candidates = _iter_candidates(args.source_dir)
    if len(candidates) < args.count:
        print(f"[ERROR] Requested {args.count} examples but only found {len(candidates)} CellInfo-derived records.")
        return 1

    if args.strategy == "diverse":
        selected = _select_diverse(candidates, args.count)
    else:
        selected = _select_first(candidates, args.count)

    print(f"[INFO] Selected {len(selected)} records with strategy={args.strategy}")
    for cand in selected:
        print(f"  - {cand.path.name}")

    if args.dry_run:
        return 0

    if args.clean_target:
        for pattern in (
            "*.datasheet.json",
            "*.datasheet.md",
            "CELLINFO_TOP10_REVIEW.md",
            "CELLINFO_TOP10_QA.md",
            "PILOT100_GATE.md",
            "PILOT100_CURATION_BACKLOG.md",
            "PILOT100_DELTA.md",
        ):
            for path in args.target_dir.glob(pattern):
                path.unlink(missing_ok=True)
        print(f"[INFO] Cleared existing datasheet outputs in {_display_path(args.target_dir)}")

    results: list[GenerationResult] = []
    for cand in selected:
        result = _build_datasheet(
            cand,
            batch_tag=args.batch_tag,
            infer_negative_electrode_basis=args.infer_negative_electrode_basis,
        )
        results.append(result)
        json_path = args.target_dir / f"{result.uid}.datasheet.json"
        md_path = args.target_dir / f"{result.uid}.datasheet.md"
        _dump_json(json_path, result.datasheet)
        _write_text(md_path, _render_markdown(result.datasheet))
        print(f"[OK] wrote {_display_path(json_path)}")

    review_path = args.target_dir / DEFAULT_REVIEW_PATH.name
    qa_path = args.target_dir / DEFAULT_QA_PATH.name
    _write_text(
        review_path,
        _render_review(
            results,
            strategy=args.strategy,
            batch_tag=args.batch_tag,
            infer_negative_electrode_basis=args.infer_negative_electrode_basis,
        ),
    )
    _write_text(
        qa_path,
        _render_qa(
            results,
            strategy=args.strategy,
            batch_tag=args.batch_tag,
            infer_negative_electrode_basis=args.infer_negative_electrode_basis,
        ),
    )
    print(f"[OK] wrote {_display_path(review_path)}")
    print(f"[OK] wrote {_display_path(qa_path)}")
    print(f"\nGenerated {len(results)} datasheet JSON/MD pairs in {_display_path(args.target_dir)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

