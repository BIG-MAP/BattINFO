from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = ROOT / ".battinfo" / "datasheets" / "generated-cell-types"
DEFAULT_OUT = ROOT / ".battinfo" / "reports" / "datasheet-curation-backlog.md"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a curation backlog report for BattINFO datasheet batches.")
    parser.add_argument(
        "--dir",
        type=Path,
        default=DEFAULT_DIR,
        help="Directory containing *.datasheet.json files.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help="Output markdown report path.",
    )
    parser.add_argument(
        "--max-list",
        type=int,
        default=30,
        help="Maximum entries to list per issue category.",
    )
    return parser.parse_args()


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_unknown(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    return value.strip().lower() in {"", "unknown", "na", "n/a", "none"}


def _spec_value(specs: dict[str, Any], key: str) -> float | None:
    item = specs.get(key)
    if not isinstance(item, dict):
        return None
    value = item.get("value")
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _make_row(uid: str, model: str, manufacturer: str, reason: str) -> str:
    return f"| `{uid}` | `{model}` | `{manufacturer}` | {reason} |"


def main() -> int:
    args = _parse_args()
    files = sorted(args.dir.glob("*.datasheet.json"))
    if not files:
        print(f"[WARN] No datasheet files found in: {_display_path(args.dir)}")
        return 0

    unknown_negative: list[str] = []
    unknown_positive: list[str] = []
    cylindrical_missing_diameter: list[str] = []
    prismatic_missing_dims: list[str] = []
    low_nominal_voltage: list[str] = []
    high_nominal_voltage: list[str] = []

    for path in files:
        doc = _load_json(path)
        product = doc.get("product", {})
        specs = doc.get("specs", {})
        uid = path.stem.replace(".datasheet", "")
        model = str(product.get("model", ""))
        manufacturer = str(product.get("manufacturer", ""))
        fmt = str(product.get("format", "unknown"))

        if _is_unknown(product.get("negative_electrode_basis")):
            unknown_negative.append(_make_row(uid, model, manufacturer, "negative_electrode_basis is unknown"))
        if _is_unknown(product.get("positive_electrode_basis")):
            unknown_positive.append(_make_row(uid, model, manufacturer, "positive_electrode_basis is unknown"))

        has_diameter = "diameter" in specs
        has_height = "height" in specs
        has_length = "length" in specs
        has_width = "width" in specs

        if fmt == "cylindrical" and not has_diameter:
            cylindrical_missing_diameter.append(
                _make_row(uid, model, manufacturer, "format=cylindrical but diameter spec missing")
            )
        if fmt == "prismatic" and (not has_length or not has_width or not has_height):
            prismatic_missing_dims.append(
                _make_row(
                    uid,
                    model,
                    manufacturer,
                    "format=prismatic but one or more of length/width/height missing",
                )
            )

        nominal_voltage = _spec_value(specs, "nominal_voltage")
        if nominal_voltage is not None:
            if nominal_voltage < 2.5:
                low_nominal_voltage.append(
                    _make_row(uid, model, manufacturer, f"nominal_voltage={nominal_voltage:g} V below 2.5 V")
                )
            if nominal_voltage > 4.4:
                high_nominal_voltage.append(
                    _make_row(uid, model, manufacturer, f"nominal_voltage={nominal_voltage:g} V above 4.4 V")
                )

    report_lines: list[str] = []
    report_lines.append(f"# Datasheet Curation Backlog ({len(files)} records)")
    report_lines.append("")
    report_lines.append("Prioritized curation candidates detected from generated datasheets.")
    report_lines.append("")
    report_lines.append("## Summary")
    report_lines.append("")
    report_lines.append(f"- Unknown negative electrode basis: `{len(unknown_negative)}`")
    report_lines.append(f"- Unknown positive electrode basis: `{len(unknown_positive)}`")
    report_lines.append(f"- Cylindrical records missing diameter: `{len(cylindrical_missing_diameter)}`")
    report_lines.append(f"- Prismatic records missing one or more dimensions: `{len(prismatic_missing_dims)}`")
    report_lines.append(f"- Nominal voltage below 2.5 V: `{len(low_nominal_voltage)}`")
    report_lines.append(f"- Nominal voltage above 4.4 V: `{len(high_nominal_voltage)}`")
    report_lines.append("")

    def _append_section(title: str, rows: list[str]) -> None:
        report_lines.append(f"## {title}")
        report_lines.append("")
        if not rows:
            report_lines.append("- none")
            report_lines.append("")
            return
        report_lines.append("| UID | Model | Manufacturer | Reason |")
        report_lines.append("|---|---|---|---|")
        for row in rows[: args.max_list]:
            report_lines.append(row)
        if len(rows) > args.max_list:
            report_lines.append(f"| ... | ... | ... | +{len(rows) - args.max_list} additional record(s) omitted |")
        report_lines.append("")

    _append_section("Unknown Negative Electrode Basis", unknown_negative)
    _append_section("Unknown Positive Electrode Basis", unknown_positive)
    _append_section("Cylindrical Missing Diameter", cylindrical_missing_diameter)
    _append_section("Prismatic Missing Dimensions", prismatic_missing_dims)
    _append_section("Low Nominal Voltage", low_nominal_voltage)
    _append_section("High Nominal Voltage", high_nominal_voltage)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"[OK] Wrote backlog report: {_display_path(args.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

