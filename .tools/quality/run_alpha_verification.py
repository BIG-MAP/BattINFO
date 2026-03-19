from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ALPHA_TESTS = [
    "tests/test_alpha_workflow.py",
    "tests/test_alpha_descriptor_matrix.py",
    "tests/test_alpha_scope_acceptance.py",
]


def _run(step: str, command: list[str]) -> dict[str, object]:
    print(f"[alpha] {step}: {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)
    return {
        "step": step,
        "command": command,
        "status": "ok",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the BattINFO alpha verification gate.")
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip the source/wheel build check. Intended only for debugging.",
    )
    parser.add_argument(
        "--report-json",
        type=Path,
        help="Write a machine-readable summary report to the given JSON path.",
    )
    args = parser.parse_args()

    steps: list[dict[str, object]] = []
    steps.append(_run("pytest", [sys.executable, "-m", "pytest", "-q", *ALPHA_TESTS]))
    steps.append(_run("installed-smoke", [sys.executable, "tests/installed_smoke.py"]))

    if args.skip_build:
        report = {
            "status": "ok",
            "root": str(ROOT),
            "skip_build": True,
            "steps": steps,
        }
        if args.report_json is not None:
            args.report_json.parent.mkdir(parents=True, exist_ok=True)
            args.report_json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        return

    if importlib.util.find_spec("build") is None:
        raise SystemExit(
            "The 'build' package is not installed. Run 'python -m pip install -e .[dev]' before alpha verification."
        )
    steps.append(_run("build", [sys.executable, "-m", "build", "--no-isolation"]))

    report = {
        "status": "ok",
        "root": str(ROOT),
        "skip_build": False,
        "steps": steps,
    }
    if args.report_json is not None:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        args.report_json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
