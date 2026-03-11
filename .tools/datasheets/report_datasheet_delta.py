from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare two datasheet directories and summarize quality deltas.")
    parser.add_argument("--baseline-dir", type=Path, required=True, help="Baseline datasheet directory.")
    parser.add_argument("--enriched-dir", type=Path, required=True, help="Enriched datasheet directory.")
    parser.add_argument("--out", type=Path, required=True, help="Output markdown report path.")
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


def _stats(directory: Path) -> dict[str, int]:
    files = sorted(directory.glob("*.datasheet.json"))
    stats = {
        "total": len(files),
        "unknown_negative": 0,
        "unknown_positive": 0,
        "unknown_chemistry": 0,
        "inferred_negative": 0,
    }
    for path in files:
        doc = _load_json(path)
        product = doc.get("product", {})
        quality = doc.get("quality", {})
        if _is_unknown(product.get("negative_electrode_basis")):
            stats["unknown_negative"] += 1
        if _is_unknown(product.get("positive_electrode_basis")):
            stats["unknown_positive"] += 1
        if _is_unknown(product.get("chemistry")):
            stats["unknown_chemistry"] += 1
        if "product.negative_electrode_basis" in quality.get("inferred_fields", []):
            stats["inferred_negative"] += 1
    return stats


def main() -> int:
    args = _parse_args()
    base = _stats(args.baseline_dir)
    enriched = _stats(args.enriched_dir)

    if base["total"] == 0 or enriched["total"] == 0:
        print("[ERROR] One of the directories has no datasheet files.")
        return 1

    lines: list[str] = []
    lines.append("# Datasheet Delta Report")
    lines.append("")
    lines.append(f"- Baseline: `{_display_path(args.baseline_dir)}`")
    lines.append(f"- Enriched: `{_display_path(args.enriched_dir)}`")
    lines.append("")
    lines.append("| Metric | Baseline | Enriched | Delta (enriched - baseline) |")
    lines.append("|---|---:|---:|---:|")
    for key in ("total", "unknown_negative", "unknown_positive", "unknown_chemistry", "inferred_negative"):
        b = base[key]
        e = enriched[key]
        lines.append(f"| `{key}` | `{b}` | `{e}` | `{e - b}` |")
    lines.append("")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] Wrote delta report: {_display_path(args.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

