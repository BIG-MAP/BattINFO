from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CANDIDATE_DIR = ROOT / ".battinfo" / "ingest" / "candidates" / "cellinfo"
DEFAULT_EXISTING_DIR = ROOT / "assets" / "datasheets" / "cell-types"
DEFAULT_OUT = ROOT / ".battinfo" / "ingest" / "reports" / "candidate-match-report.md"
DEFAULT_JSON_OUT = ROOT / ".battinfo" / "ingest" / "reports" / "candidate-match-report.json"

TEXT_TOKEN_RE = re.compile(r"[^a-z0-9]+")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare ingestion candidates against existing BattINFO datasheets and produce match decisions."
    )
    parser.add_argument("--candidate-dir", type=Path, default=DEFAULT_CANDIDATE_DIR, help="*.candidate.json directory.")
    parser.add_argument("--existing-dir", type=Path, default=DEFAULT_EXISTING_DIR, help="*.datasheet.json directory.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output markdown report path.")
    parser.add_argument("--json-out", type=Path, default=DEFAULT_JSON_OUT, help="Output JSON report path.")
    parser.add_argument("--match-threshold", type=float, default=0.80, help="Score threshold for match_existing.")
    parser.add_argument(
        "--ambiguous-gap",
        type=float,
        default=0.05,
        help="If top two scores differ by <= gap, mark as ambiguous_match.",
    )
    parser.add_argument("--max-rows", type=int, default=200, help="Max candidate rows shown in markdown table.")
    return parser.parse_args()


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _norm_text(value: Any) -> str:
    token = str(value or "").strip().lower()
    token = TEXT_TOKEN_RE.sub(" ", token).strip()
    return token


def _spec_number(specs: Any, key: str) -> float | None:
    if not isinstance(specs, dict):
        return None
    item = specs.get(key)
    if not isinstance(item, dict):
        return None
    for field in ("value", "value_typical", "value_max", "value_min"):
        value = item.get(field)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _extract_candidate(path: Path) -> dict[str, Any]:
    doc = _load_json(path)
    candidate = doc.get("candidate", {})
    product = candidate.get("product", {}) if isinstance(candidate, dict) else {}
    specs = candidate.get("specs", {}) if isinstance(candidate, dict) else {}
    return {
        "path": str(path),
        "candidate_id": candidate.get("candidate_id"),
        "source_document_id": candidate.get("source_document_id"),
        "manufacturer": product.get("manufacturer"),
        "model": product.get("model"),
        "chemistry": product.get("chemistry"),
        "format": product.get("format"),
        "nominal_capacity": _spec_number(specs, "nominal_capacity"),
        "nominal_voltage": _spec_number(specs, "nominal_voltage"),
    }


def _extract_existing(path: Path) -> dict[str, Any]:
    doc = _load_json(path)
    product = doc.get("product", {})
    specs = doc.get("specs", {})
    return {
        "path": str(path),
        "identifier": product.get("identifier"),
        "manufacturer": product.get("manufacturer"),
        "model": product.get("model"),
        "chemistry": product.get("chemistry"),
        "format": product.get("format"),
        "nominal_capacity": _spec_number(specs, "nominal_capacity"),
        "nominal_voltage": _spec_number(specs, "nominal_voltage"),
    }


def _score(candidate: dict[str, Any], existing: dict[str, Any]) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    c_man = _norm_text(candidate.get("manufacturer"))
    e_man = _norm_text(existing.get("manufacturer"))
    if c_man and e_man and c_man == e_man:
        score += 0.35
        reasons.append("manufacturer exact")
    elif c_man and e_man and (c_man in e_man or e_man in c_man):
        score += 0.20
        reasons.append("manufacturer partial")

    c_model = _norm_text(candidate.get("model"))
    e_model = _norm_text(existing.get("model"))
    if c_model and e_model and c_model == e_model:
        score += 0.45
        reasons.append("model exact")
    elif c_model and e_model and (c_model in e_model or e_model in c_model):
        score += 0.25
        reasons.append("model partial")

    c_chem = _norm_text(candidate.get("chemistry"))
    e_chem = _norm_text(existing.get("chemistry"))
    if c_chem and e_chem and c_chem == e_chem:
        score += 0.10
        reasons.append("chemistry exact")

    c_fmt = _norm_text(candidate.get("format"))
    e_fmt = _norm_text(existing.get("format"))
    if c_fmt and e_fmt and c_fmt == e_fmt:
        score += 0.05
        reasons.append("format exact")

    c_cap = candidate.get("nominal_capacity")
    e_cap = existing.get("nominal_capacity")
    if isinstance(c_cap, float) and isinstance(e_cap, float):
        if e_cap > 0:
            rel = abs(c_cap - e_cap) / e_cap
            if rel <= 0.10:
                score += 0.03
                reasons.append("nominal_capacity close")

    c_v = candidate.get("nominal_voltage")
    e_v = existing.get("nominal_voltage")
    if isinstance(c_v, float) and isinstance(e_v, float):
        if abs(c_v - e_v) <= 0.10:
            score += 0.02
            reasons.append("nominal_voltage close")

    return min(score, 1.0), reasons


def _conflicts(candidate: dict[str, Any], existing: dict[str, Any]) -> list[str]:
    out: list[str] = []
    c_cap = candidate.get("nominal_capacity")
    e_cap = existing.get("nominal_capacity")
    if isinstance(c_cap, float) and isinstance(e_cap, float) and e_cap > 0:
        rel = abs(c_cap - e_cap) / e_cap
        if rel > 0.20:
            out.append(f"nominal_capacity differs by {rel:.0%}")
    c_v = candidate.get("nominal_voltage")
    e_v = existing.get("nominal_voltage")
    if isinstance(c_v, float) and isinstance(e_v, float):
        dv = abs(c_v - e_v)
        if dv > 0.30:
            out.append(f"nominal_voltage differs by {dv:.2f} V")
    return out


def _classify(
    candidate: dict[str, Any],
    existing_rows: list[dict[str, Any]],
    match_threshold: float,
    ambiguous_gap: float,
) -> dict[str, Any]:
    scored: list[dict[str, Any]] = []
    for existing in existing_rows:
        score, reasons = _score(candidate, existing)
        scored.append(
            {
                "identifier": existing.get("identifier"),
                "path": existing.get("path"),
                "score": round(score, 4),
                "reasons": reasons,
            }
        )
    scored.sort(key=lambda row: float(row.get("score", 0.0)), reverse=True)

    best = scored[0] if scored else None
    second = scored[1] if len(scored) > 1 else None

    decision = "new_cell_type"
    decision_reason = "no existing match above threshold"
    conflict_notes: list[str] = []
    best_identifier = None
    best_score = 0.0

    if best is not None:
        best_score = float(best.get("score", 0.0))
        best_identifier = best.get("identifier")
        if best_score >= match_threshold:
            if second is not None and (best_score - float(second.get("score", 0.0))) <= ambiguous_gap:
                decision = "ambiguous_match"
                decision_reason = "top candidates are too close in score"
            else:
                decision = "match_existing"
                decision_reason = "top score exceeds threshold with clear margin"
        else:
            decision = "new_cell_type"
            decision_reason = "top score below threshold"

    if decision == "match_existing" and best_identifier is not None:
        existing_map = {row.get("identifier"): row for row in existing_rows}
        matched_existing = existing_map.get(best_identifier)
        if isinstance(matched_existing, dict):
            conflict_notes = _conflicts(candidate, matched_existing)
            if conflict_notes:
                decision = "conflict_manual_review"
                decision_reason = "strong field-level differences detected"

    return {
        "candidate_id": candidate.get("candidate_id"),
        "source_document_id": candidate.get("source_document_id"),
        "decision": decision,
        "decision_reason": decision_reason,
        "best_match_identifier": best_identifier,
        "best_match_score": round(best_score, 4),
        "best_match_reasons": best.get("reasons", []) if best else [],
        "conflicts": conflict_notes,
        "top_matches": scored[:5],
        "candidate_path": candidate.get("path"),
    }


def _markdown(results: list[dict[str, Any]], match_threshold: float, ambiguous_gap: float, max_rows: int) -> str:
    summary: dict[str, int] = {}
    for item in results:
        decision = str(item.get("decision"))
        summary[decision] = summary.get(decision, 0) + 1

    lines: list[str] = []
    lines.append("# Candidate Match Report")
    lines.append("")
    lines.append(f"- Candidates evaluated: `{len(results)}`")
    lines.append(f"- Match threshold: `{match_threshold:.2f}`")
    lines.append(f"- Ambiguous gap: `{ambiguous_gap:.2f}`")
    lines.append("")
    lines.append("## Decision Counts")
    lines.append("")
    for key in sorted(summary):
        lines.append(f"- `{key}`: `{summary[key]}`")
    lines.append("")
    lines.append("## Candidate Decisions")
    lines.append("")
    lines.append("| Candidate | Decision | Best match | Score | Reason |")
    lines.append("|---|---|---|---:|---|")
    for item in results[:max_rows]:
        lines.append(
            "| "
            f"`{item.get('candidate_id')}` | "
            f"`{item.get('decision')}` | "
            f"`{item.get('best_match_identifier') or '-'}` | "
            f"`{item.get('best_match_score'):.2f}` | "
            f"{item.get('decision_reason')} |"
        )
    if len(results) > max_rows:
        lines.append(f"| ... | ... | ... | ... | +{len(results) - max_rows} additional candidate(s) omitted |")
    lines.append("")
    lines.append("## Conflicts")
    lines.append("")
    conflicts = [item for item in results if item.get("decision") == "conflict_manual_review"]
    if not conflicts:
        lines.append("- none")
    else:
        for item in conflicts:
            joined = "; ".join(str(entry) for entry in item.get("conflicts", []))
            lines.append(f"- `{item.get('candidate_id')}` vs `{item.get('best_match_identifier')}`: {joined}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    args = _parse_args()
    candidate_files = sorted(args.candidate_dir.glob("*.candidate.json"))
    if not candidate_files:
        print(f"[WARN] No candidate files found in: {_display_path(args.candidate_dir)}")
        return 0
    existing_files = sorted(args.existing_dir.glob("*.datasheet.json"))
    if not existing_files:
        print(f"[WARN] No existing datasheets found in: {_display_path(args.existing_dir)}")
        return 0

    candidates = [_extract_candidate(path) for path in candidate_files]
    existing_rows = [_extract_existing(path) for path in existing_files]

    results = [
        _classify(
            candidate=row,
            existing_rows=existing_rows,
            match_threshold=args.match_threshold,
            ambiguous_gap=args.ambiguous_gap,
        )
        for row in candidates
    ]
    results.sort(key=lambda item: (str(item.get("decision")), -(float(item.get("best_match_score", 0.0)))))

    payload = {
        "version": "1.0.0",
        "candidate_count": len(candidates),
        "existing_count": len(existing_rows),
        "match_threshold": args.match_threshold,
        "ambiguous_gap": args.ambiguous_gap,
        "results": results,
    }

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"[OK] Wrote JSON report: {_display_path(args.json_out)}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        _markdown(
            results=results,
            match_threshold=args.match_threshold,
            ambiguous_gap=args.ambiguous_gap,
            max_rows=args.max_rows,
        ),
        encoding="utf-8",
    )
    print(f"[OK] Wrote markdown report: {_display_path(args.out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

