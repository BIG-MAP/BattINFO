"""BattINFO → Zenodo sandbox demo.

Authors a tiny workspace (one coin cell + one capacity test + its raw data) and
pushes it to the Zenodo SANDBOX (sandbox.zenodo.org) as a reviewable draft — no
DOI is minted, nothing is published.

Prereqs:
  * A sandbox.zenodo.org account + a personal access token with scopes
    ``deposit:write`` and ``deposit:actions``.
  * Set it in the environment before running:
        $env:ZENODO_SANDBOX_TOKEN = "your-sandbox-token"   # PowerShell

Run:
    .venv/Scripts/python.exe scripts/demo_zenodo_sandbox.py
"""
from __future__ import annotations

import os
from pathlib import Path

import battinfo

ROOT = Path.home() / "Documents" / "battinfo-zenodo-demo"
ROOT.mkdir(parents=True, exist_ok=True)

# A small raw data file to archive alongside the linked-data records.
csv = ROOT / "DEMO-001_capacity.csv"
csv.write_text("cycle,discharge_capacity_mAh\n1,452\n2,451\n3,450\n", encoding="utf-8")

# Offline workspace — the demo does not depend on the live registry being up.
ws = battinfo.workspace(ROOT, registry_url=None)

# 1. Author a minimal cell spec from a fillable template.
spec_path = ws.template(
    "cell-spec",
    manufacturer="DemoCells Inc.",
    model="DC-2032",
    format="coin",
    chemistry="Li-ion",
)
spec = ws.load(spec_path)

# 2. Register the physical cell we tested.
ws.add("cell", spec=spec, serial_numbers=["DEMO-001"])

# 3. Attach a capacity test and its raw data file.
ws.add("test", type="capacity_check", cell="DEMO-001", data=str(csv), instrument="Demo cycler")

# 4. Persist the workspace records.
ws.save()
print("[ok] authored + saved workspace at", ROOT)

# 5. Push to the Zenodo SANDBOX as a draft (only if a token is present).
if not os.environ.get("ZENODO_SANDBOX_TOKEN"):
    print("\nSet ZENODO_SANDBOX_TOKEN and re-run to push the draft to sandbox.zenodo.org.")
    raise SystemExit(0)

result = ws.zenodo(
    publish=False,
    sandbox=True,
    title="BattINFO community demo — coin cell capacity",
    description="Demonstration deposit created with ws.zenodo() from BattINFO.",
    creators=[{"name": "Clark, Simon"}],
    keywords=["BattINFO", "demo", "battery"],
)
print("\n[ok] Zenodo sandbox draft created")
print("  Draft URL:", result.draft_url)
print("  Record ID:", result.record_id)
