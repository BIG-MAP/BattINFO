from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False)


def test_generate_datasheet_examples_first_strategy(tmp_path: Path) -> None:
    target_dir = tmp_path / "datasheets"
    source_dir = ROOT / "src" / "battinfo" / "data" / "examples" / "cells-clean"

    result = _run(
        [
            sys.executable,
            ".tools/datasheets/generate_cell_type_datasheet_examples.py",
            "--count",
            "3",
            "--strategy",
            "first",
            "--source-dir",
            str(source_dir),
            "--target-dir",
            str(target_dir),
            "--batch-tag",
            "test-batch-first",
            "--clean-target",
        ]
    )
    assert result.returncode == 0, result.stderr

    json_files = sorted(target_dir.glob("*.datasheet.json"))
    md_files = sorted(target_dir.glob("*.datasheet.md"))
    assert len(json_files) == 3
    assert len(md_files) == 3
    assert (target_dir / "CELLINFO_TOP10_REVIEW.md").exists()
    assert (target_dir / "CELLINFO_TOP10_QA.md").exists()

    sample = json.loads(json_files[0].read_text(encoding="utf-8"))
    assert sample["version"] == "1.0.0-draft"
    assert sample["status"] == "draft"
    assert sample["extensions"]["x-battinfo-ingest_batch"] == "test-batch-first"


def test_generate_datasheet_with_negative_inference(tmp_path: Path) -> None:
    target_dir = tmp_path / "datasheets"
    source_dir = ROOT / "src" / "battinfo" / "data" / "examples" / "cells-clean"

    result = _run(
        [
            sys.executable,
            ".tools/datasheets/generate_cell_type_datasheet_examples.py",
            "--count",
            "1",
            "--strategy",
            "first",
            "--source-dir",
            str(source_dir),
            "--target-dir",
            str(target_dir),
            "--batch-tag",
            "test-batch-infer",
            "--infer-negative-electrode-basis",
            "--clean-target",
        ]
    )
    assert result.returncode == 0, result.stderr

    sample_path = next(target_dir.glob("*.datasheet.json"))
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    assert sample["product"]["negative_electrode_basis"] != "unknown"
    assert "product.negative_electrode_basis" in sample["quality"].get("inferred_fields", [])
    enrichment = sample["extensions"].get("x-battinfo-enrichment", {}).get("negative_electrode_basis", {})
    assert enrichment.get("applied") is True
    assert enrichment.get("rule_id")


def test_validate_datasheet_script_on_generated_dir(tmp_path: Path) -> None:
    target_dir = tmp_path / "datasheets"
    source_dir = ROOT / "src" / "battinfo" / "data" / "examples" / "cells-clean"

    generated = _run(
        [
            sys.executable,
            ".tools/datasheets/generate_cell_type_datasheet_examples.py",
            "--count",
            "2",
            "--strategy",
            "diverse",
            "--source-dir",
            str(source_dir),
            "--target-dir",
            str(target_dir),
            "--batch-tag",
            "test-batch-validate",
            "--clean-target",
        ]
    )
    assert generated.returncode == 0, generated.stderr

    validated = _run(
        [
            sys.executable,
            ".tools/datasheets/validate_cell_type_datasheets.py",
            "--dir",
            str(target_dir),
            "--profile",
            "cell-type-datasheet",
        ]
    )
    assert validated.returncode == 0, validated.stderr
    assert "Failures: 0." in validated.stdout


def test_quality_gate_script_passes_and_fails(tmp_path: Path) -> None:
    target_dir = tmp_path / "datasheets"
    source_dir = ROOT / "src" / "battinfo" / "data" / "examples" / "cells-clean"
    report_path = tmp_path / "quality-report.md"

    generated = _run(
        [
            sys.executable,
            ".tools/datasheets/generate_cell_type_datasheet_examples.py",
            "--count",
            "3",
            "--strategy",
            "first",
            "--source-dir",
            str(source_dir),
            "--target-dir",
            str(target_dir),
            "--batch-tag",
            "test-batch-quality",
            "--clean-target",
        ]
    )
    assert generated.returncode == 0, generated.stderr

    passing = _run(
        [
            sys.executable,
            ".tools/datasheets/check_datasheet_quality.py",
            "--dir",
            str(target_dir),
            "--report",
            str(report_path),
            "--max-empty-specs",
            "0",
            "--max-unknown-manufacturer",
            "0",
            "--max-unknown-chemistry",
            "0",
            "--max-unknown-positive-electrode-basis",
            "0",
            "--max-unknown-negative-electrode-basis",
            "-1",
            "--required-spec",
            "nominal_capacity",
            "--required-spec",
            "nominal_voltage",
            "--min-required-spec-coverage",
            "1.0",
        ]
    )
    assert passing.returncode == 0, passing.stderr
    assert "[OK] Quality gates passed." in passing.stdout
    assert report_path.exists()

    failing = _run(
        [
            sys.executable,
            ".tools/datasheets/check_datasheet_quality.py",
            "--dir",
            str(target_dir),
            "--max-unknown-negative-electrode-basis",
            "0",
        ]
    )
    assert failing.returncode == 1
    assert "unknown_negative_electrode_basis" in failing.stdout


def test_curation_backlog_report_script(tmp_path: Path) -> None:
    target_dir = tmp_path / "datasheets"
    source_dir = ROOT / "src" / "battinfo" / "data" / "examples" / "cells-clean"
    backlog_path = tmp_path / "backlog.md"

    generated = _run(
        [
            sys.executable,
            ".tools/datasheets/generate_cell_type_datasheet_examples.py",
            "--count",
            "4",
            "--strategy",
            "diverse",
            "--source-dir",
            str(source_dir),
            "--target-dir",
            str(target_dir),
            "--batch-tag",
            "test-batch-backlog",
            "--clean-target",
        ]
    )
    assert generated.returncode == 0, generated.stderr

    backlog = _run(
        [
            sys.executable,
            ".tools/datasheets/report_datasheet_curation_backlog.py",
            "--dir",
            str(target_dir),
            "--out",
            str(backlog_path),
            "--max-list",
            "5",
        ]
    )
    assert backlog.returncode == 0, backlog.stderr
    assert backlog_path.exists()
    text = backlog_path.read_text(encoding="utf-8")
    assert "Datasheet Curation Backlog" in text
    assert "Unknown Negative Electrode Basis" in text


def test_datasheet_delta_report_script(tmp_path: Path) -> None:
    source_dir = ROOT / "src" / "battinfo" / "data" / "examples" / "cells-clean"
    baseline_dir = tmp_path / "baseline"
    enriched_dir = tmp_path / "enriched"
    delta_path = tmp_path / "delta.md"

    baseline = _run(
        [
            sys.executable,
            ".tools/datasheets/generate_cell_type_datasheet_examples.py",
            "--count",
            "2",
            "--strategy",
            "first",
            "--source-dir",
            str(source_dir),
            "--target-dir",
            str(baseline_dir),
            "--batch-tag",
            "test-baseline",
            "--clean-target",
        ]
    )
    assert baseline.returncode == 0, baseline.stderr

    enriched = _run(
        [
            sys.executable,
            ".tools/datasheets/generate_cell_type_datasheet_examples.py",
            "--count",
            "2",
            "--strategy",
            "first",
            "--source-dir",
            str(source_dir),
            "--target-dir",
            str(enriched_dir),
            "--batch-tag",
            "test-enriched",
            "--infer-negative-electrode-basis",
            "--clean-target",
        ]
    )
    assert enriched.returncode == 0, enriched.stderr

    delta = _run(
        [
            sys.executable,
            ".tools/datasheets/report_datasheet_delta.py",
            "--baseline-dir",
            str(baseline_dir),
            "--enriched-dir",
            str(enriched_dir),
            "--out",
            str(delta_path),
        ]
    )
    assert delta.returncode == 0, delta.stderr
    text = delta_path.read_text(encoding="utf-8")
    assert "Datasheet Delta Report" in text
    assert "unknown_negative" in text

