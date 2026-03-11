from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROPERTY_MAP = ROOT / "assets" / "mappings" / "domain-battery" / "property_map.candidates.json"
DEFAULT_UNIT_MAP = ROOT / "assets" / "mappings" / "domain-battery" / "unit_map.candidates.json"
DEFAULT_REPORT = ROOT / "assets" / "mappings" / "domain-battery" / "quantitative_mapping_gate.md"


@dataclass
class GateSummary:
    property_total: int
    property_unmapped: int
    property_low_confidence: int
    unit_total: int
    unit_unmapped: int
    unit_low_confidence: int


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check ontology mapping candidate quality gates and emit a markdown report."
    )
    parser.add_argument("--property-map", type=Path, default=DEFAULT_PROPERTY_MAP, help="Property candidate map JSON.")
    parser.add_argument("--unit-map", type=Path, default=DEFAULT_UNIT_MAP, help="Unit candidate map JSON.")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT, help="Markdown report output path.")
    parser.add_argument(
        "--min-property-confidence",
        type=float,
        default=0.9,
        help="Minimum confidence required for mapped property candidates.",
    )
    parser.add_argument(
        "--min-unit-confidence",
        type=float,
        default=0.9,
        help="Minimum confidence required for mapped unit candidates.",
    )
    parser.add_argument("--max-unmapped-properties", type=int, default=0, help="Maximum allowed unmapped properties.")
    parser.add_argument("--max-unmapped-units", type=int, default=0, help="Maximum allowed unmapped units.")
    parser.add_argument(
        "--max-low-confidence-properties",
        type=int,
        default=0,
        help="Maximum allowed low-confidence mapped properties.",
    )
    parser.add_argument(
        "--max-low-confidence-units",
        type=int,
        default=0,
        help="Maximum allowed low-confidence mapped units.",
    )
    return parser.parse_args()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_candidate(row: dict[str, Any]) -> bool:
    return str(row.get("status", "")).strip().lower() == "candidate"


def _confidence(row: dict[str, Any]) -> float:
    raw = row.get("confidence", 0.0)
    if isinstance(raw, (int, float)):
        return float(raw)
    return 0.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _summarize(
    properties: list[dict[str, Any]],
    units: list[dict[str, Any]],
    *,
    min_property_confidence: float,
    min_unit_confidence: float,
) -> tuple[GateSummary, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    property_unmapped = [row for row in properties if not _is_candidate(row)]
    property_low_conf = [row for row in properties if _is_candidate(row) and _confidence(row) < min_property_confidence]
    unit_unmapped = [row for row in units if not _is_candidate(row)]
    unit_low_conf = [row for row in units if _is_candidate(row) and _confidence(row) < min_unit_confidence]

    summary = GateSummary(
        property_total=len(properties),
        property_unmapped=len(property_unmapped),
        property_low_confidence=len(property_low_conf),
        unit_total=len(units),
        unit_unmapped=len(unit_unmapped),
        unit_low_confidence=len(unit_low_conf),
    )
    return summary, property_unmapped, property_low_conf, unit_unmapped, unit_low_conf


def _render_report(
    *,
    property_map_path: Path,
    unit_map_path: Path,
    min_property_confidence: float,
    min_unit_confidence: float,
    max_unmapped_properties: int,
    max_unmapped_units: int,
    max_low_confidence_properties: int,
    max_low_confidence_units: int,
    summary: GateSummary,
    property_unmapped: list[dict[str, Any]],
    property_low_conf: list[dict[str, Any]],
    unit_unmapped: list[dict[str, Any]],
    unit_low_conf: list[dict[str, Any]],
    passed: bool,
) -> str:
    lines = [
        "# Quantitative Mapping Gate Report",
        "",
        f"- Generated at: `{_now_iso()}`",
        f"- Property map: `{property_map_path}`",
        f"- Unit map: `{unit_map_path}`",
        f"- Result: `{'PASS' if passed else 'FAIL'}`",
        "",
        "## Thresholds",
        "",
        f"- `min_property_confidence`: `{min_property_confidence}`",
        f"- `min_unit_confidence`: `{min_unit_confidence}`",
        f"- `max_unmapped_properties`: `{max_unmapped_properties}`",
        f"- `max_unmapped_units`: `{max_unmapped_units}`",
        f"- `max_low_confidence_properties`: `{max_low_confidence_properties}`",
        f"- `max_low_confidence_units`: `{max_low_confidence_units}`",
        "",
        "## Summary",
        "",
        f"- Properties total: `{summary.property_total}`",
        f"- Properties unmapped: `{summary.property_unmapped}`",
        f"- Properties low-confidence: `{summary.property_low_confidence}`",
        f"- Units total: `{summary.unit_total}`",
        f"- Units unmapped: `{summary.unit_unmapped}`",
        f"- Units low-confidence: `{summary.unit_low_confidence}`",
        "",
    ]

    lines.extend(
        [
            "## Unmapped Properties",
            "",
            "| Key | Status | Candidate IRI | prefLabel | Confidence |",
            "|---|---|---|---|---|",
        ]
    )
    for row in property_unmapped:
        lines.append(
            f"| `{row.get('key')}` | `{row.get('status')}` | `{row.get('class_iri') or '-'}` | "
            f"`{row.get('class_pref_label') or '-'}` | `{float(row.get('confidence', 0.0)):.3f}` |"
        )
    if not property_unmapped:
        lines.append("| - | - | - | - | - |")

    lines.extend(
        [
            "",
            "## Low-Confidence Properties",
            "",
            "| Key | Candidate IRI | prefLabel | Confidence |",
            "|---|---|---|---|",
        ]
    )
    for row in property_low_conf:
        lines.append(
            f"| `{row.get('key')}` | `{row.get('class_iri') or '-'}` | `{row.get('class_pref_label') or '-'}` | "
            f"`{float(row.get('confidence', 0.0)):.3f}` |"
        )
    if not property_low_conf:
        lines.append("| - | - | - | - |")

    lines.extend(
        [
            "",
            "## Unmapped Units",
            "",
            "| Symbol | Status | Candidate IRI | prefLabel | Confidence |",
            "|---|---|---|---|---|",
        ]
    )
    for row in unit_unmapped:
        lines.append(
            f"| `{row.get('symbol')}` | `{row.get('status')}` | `{row.get('unit_iri') or '-'}` | "
            f"`{row.get('unit_pref_label') or '-'}` | `{float(row.get('confidence', 0.0)):.3f}` |"
        )
    if not unit_unmapped:
        lines.append("| - | - | - | - | - |")

    lines.extend(
        [
            "",
            "## Low-Confidence Units",
            "",
            "| Symbol | Candidate IRI | prefLabel | Confidence |",
            "|---|---|---|---|",
        ]
    )
    for row in unit_low_conf:
        lines.append(
            f"| `{row.get('symbol')}` | `{row.get('unit_iri') or '-'}` | `{row.get('unit_pref_label') or '-'}` | "
            f"`{float(row.get('confidence', 0.0)):.3f}` |"
        )
    if not unit_low_conf:
        lines.append("| - | - | - | - |")

    return "\n".join(lines) + "\n"


def main() -> int:
    args = _parse_args()
    try:
        property_doc = _load_json(args.property_map)
        unit_doc = _load_json(args.unit_map)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] Failed to read candidate maps: {exc}", file=sys.stderr)
        return 2

    property_rows = property_doc.get("mappings", [])
    unit_rows = unit_doc.get("mappings", [])
    if not isinstance(property_rows, list) or not isinstance(unit_rows, list):
        print("[ERROR] Candidate map documents must contain list field 'mappings'.", file=sys.stderr)
        return 2

    summary, property_unmapped, property_low_conf, unit_unmapped, unit_low_conf = _summarize(
        property_rows,
        unit_rows,
        min_property_confidence=args.min_property_confidence,
        min_unit_confidence=args.min_unit_confidence,
    )

    passed = (
        summary.property_unmapped <= args.max_unmapped_properties
        and summary.unit_unmapped <= args.max_unmapped_units
        and summary.property_low_confidence <= args.max_low_confidence_properties
        and summary.unit_low_confidence <= args.max_low_confidence_units
    )

    report = _render_report(
        property_map_path=args.property_map,
        unit_map_path=args.unit_map,
        min_property_confidence=args.min_property_confidence,
        min_unit_confidence=args.min_unit_confidence,
        max_unmapped_properties=args.max_unmapped_properties,
        max_unmapped_units=args.max_unmapped_units,
        max_low_confidence_properties=args.max_low_confidence_properties,
        max_low_confidence_units=args.max_low_confidence_units,
        summary=summary,
        property_unmapped=property_unmapped,
        property_low_conf=property_low_conf,
        unit_unmapped=unit_unmapped,
        unit_low_conf=unit_low_conf,
        passed=passed,
    )

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report, encoding="utf-8")

    print(f"report={args.report}")
    print(f"result={'PASS' if passed else 'FAIL'}")
    print(
        f"unmapped_properties={summary.property_unmapped} low_confidence_properties={summary.property_low_confidence}"
    )
    print(f"unmapped_units={summary.unit_unmapped} low_confidence_units={summary.unit_low_confidence}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

