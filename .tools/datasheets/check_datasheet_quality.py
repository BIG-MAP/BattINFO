from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = ROOT / ".battinfo" / "datasheets" / "generated-cell-specs"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run quality gates for BattINFO cell-spec datasheet batches.")
    parser.add_argument(
        "--dir",
        type=Path,
        default=DEFAULT_DIR,
        help="Directory containing *.datasheet.json files.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Optional markdown report path. If omitted, no report file is written.",
    )
    parser.add_argument("--max-empty-specs", type=int, default=0)
    parser.add_argument("--max-unknown-manufacturer", type=int, default=0)
    parser.add_argument("--max-unknown-chemistry", type=int, default=0)
    parser.add_argument("--max-unknown-positive-electrode-basis", type=int, default=0)
    parser.add_argument(
        "--max-unknown-negative-electrode-basis",
        type=int,
        default=-1,
        help="Set >=0 to enforce; -1 disables this gate.",
    )
    parser.add_argument(
        "--required-spec",
        action="append",
        default=["nominal_capacity", "nominal_voltage"],
        help="Spec key that must meet minimum coverage. Repeat for multiple keys.",
    )
    parser.add_argument(
        "--min-required-spec-coverage",
        type=float,
        default=1.0,
        help="Required fraction [0,1] of records containing each required spec key.",
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
    token = value.strip().lower()
    return token in {"", "unknown", "na", "n/a", "none"}


def _build_report(
    files: list[Path],
    unknown_manufacturer: int,
    unknown_chemistry: int,
    unknown_positive: int,
    unknown_negative: int,
    empty_specs: int,
    spec_counter: Counter[str],
    required_specs: list[str],
    min_cov: float,
    failures: list[str],
) -> str:
    total = len(files)
    lines: list[str] = []
    lines.append(f"# Datasheet Quality Gate Report ({total} records)")
    lines.append("")
    lines.append("## Metrics")
    lines.append("")
    lines.append(f"- Total records: `{total}`")
    lines.append(f"- Empty specs blocks: `{empty_specs}`")
    lines.append(f"- Unknown manufacturer: `{unknown_manufacturer}`")
    lines.append(f"- Unknown chemistry: `{unknown_chemistry}`")
    lines.append(f"- Unknown positive electrode basis: `{unknown_positive}`")
    lines.append(f"- Unknown negative electrode basis: `{unknown_negative}`")
    lines.append("")
    lines.append("## Required Spec Coverage")
    lines.append("")
    lines.append(f"- Minimum required coverage: `{min_cov:.0%}`")
    lines.append("| Spec key | Coverage | Count |")
    lines.append("|---|---:|---:|")
    for key in sorted(set(required_specs)):
        count = spec_counter.get(key, 0)
        cov = (count / total) if total else 0.0
        lines.append(f"| `{key}` | `{cov:.0%}` | `{count}` |")
    lines.append("")
    lines.append("## Failures")
    lines.append("")
    if failures:
        for failure in failures:
            lines.append(f"- {failure}")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = _parse_args()

    if args.min_required_spec_coverage < 0 or args.min_required_spec_coverage > 1:
        print("[ERROR] --min-required-spec-coverage must be between 0 and 1.")
        return 2

    files = sorted(args.dir.glob("*.datasheet.json"))
    if not files:
        print(f"[WARN] No datasheet files found in: {_display_path(args.dir)}")
        return 0

    unknown_manufacturer = 0
    unknown_chemistry = 0
    unknown_positive = 0
    unknown_negative = 0
    empty_specs = 0
    spec_counter: Counter[str] = Counter()

    for path in files:
        doc = _load_json(path)
        product = doc.get("cell_spec", {})
        specs = doc.get("properties", {})

        if _is_unknown(product.get("manufacturer")):
            unknown_manufacturer += 1
        if _is_unknown(product.get("chemistry")):
            unknown_chemistry += 1
        if _is_unknown(product.get("positive_electrode_basis")):
            unknown_positive += 1
        if _is_unknown(product.get("negative_electrode_basis")):
            unknown_negative += 1

        if not isinstance(specs, dict) or not specs:
            empty_specs += 1
        else:
            for key in specs.keys():
                spec_counter[str(key)] += 1

    total = len(files)
    failures: list[str] = []

    if empty_specs > args.max_empty_specs:
        failures.append(f"empty_specs={empty_specs} exceeds max_empty_specs={args.max_empty_specs}")
    if unknown_manufacturer > args.max_unknown_manufacturer:
        failures.append(
            f"unknown_manufacturer={unknown_manufacturer} exceeds max_unknown_manufacturer={args.max_unknown_manufacturer}"
        )
    if unknown_chemistry > args.max_unknown_chemistry:
        failures.append(f"unknown_chemistry={unknown_chemistry} exceeds max_unknown_chemistry={args.max_unknown_chemistry}")
    if unknown_positive > args.max_unknown_positive_electrode_basis:
        failures.append(
            "unknown_positive_electrode_basis="
            f"{unknown_positive} exceeds max_unknown_positive_electrode_basis={args.max_unknown_positive_electrode_basis}"
        )
    if args.max_unknown_negative_electrode_basis >= 0 and unknown_negative > args.max_unknown_negative_electrode_basis:
        failures.append(
            "unknown_negative_electrode_basis="
            f"{unknown_negative} exceeds max_unknown_negative_electrode_basis={args.max_unknown_negative_electrode_basis}"
        )

    required_specs = [key for key in args.required_spec if isinstance(key, str) and key.strip()]
    for key in sorted(set(required_specs)):
        present = spec_counter.get(key, 0)
        coverage = (present / total) if total else 0.0
        if coverage < args.min_required_spec_coverage:
            failures.append(
                f"required_spec={key} coverage={coverage:.1%} below min_required_spec_coverage={args.min_required_spec_coverage:.1%}"
            )

    print(f"[INFO] Checked {total} datasheet file(s) in {_display_path(args.dir)}")
    print(
        "[INFO] Metrics: "
        f"empty_specs={empty_specs} unknown_manufacturer={unknown_manufacturer} "
        f"unknown_chemistry={unknown_chemistry} unknown_positive={unknown_positive} "
        f"unknown_negative={unknown_negative}"
    )

    if args.report is not None:
        report_text = _build_report(
            files=files,
            unknown_manufacturer=unknown_manufacturer,
            unknown_chemistry=unknown_chemistry,
            unknown_positive=unknown_positive,
            unknown_negative=unknown_negative,
            empty_specs=empty_specs,
            spec_counter=spec_counter,
            required_specs=required_specs,
            min_cov=args.min_required_spec_coverage,
            failures=failures,
        )
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report_text, encoding="utf-8")
        print(f"[INFO] Wrote report: {_display_path(args.report)}")

    if failures:
        print("[FAIL] Quality gates failed:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("[OK] Quality gates passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

