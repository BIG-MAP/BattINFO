"""Every registry submission path builds its envelope in ONE place (4.3).

The authoring workspace and the curated editorial pipeline used to parallel-
build their envelopes in ws.py and api.py; they forked (envelope version,
payload shape) without anyone noticing. Both now delegate to
api.build_submission_envelope — this test pins that the two paths differ ONLY
in the fields that should differ.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.api import build_curated_cell_spec_submission  # noqa: E402
from battinfo.bundle import SCHEMA_VERSION  # noqa: E402
from battinfo.ws import _cell_spec_submission_payload  # noqa: E402

RECORD_FILE = ROOT / "examples" / "cell-spec" / "A123__ANR26650M1-B.json"

# Fields that legitimately differ between the authoring and curated paths.
INTENDED_DIFFERENCES = {"publication_intent", "provenance", "validation", "workspace", "generated_at"}


def _normalise(payload: dict) -> dict:
    return {k: v for k, v in payload.items() if k not in INTENDED_DIFFERENCES}


def test_authoring_and_curated_envelopes_share_one_shape() -> None:
    record = json.loads(RECORD_FILE.read_text(encoding="utf-8"))

    authoring = _cell_spec_submission_payload(
        record, wid="w", pid="p", ver="v1",
        source_local_id="a123-anr26650m1-b", title="A123 ANR26650M1-B",
    )
    curated = build_curated_cell_spec_submission(
        RECORD_FILE, workspace_id="w", publisher_id="p", source_version="v1",
        source_local_id="a123-anr26650m1-b", title="A123 ANR26650M1-B",
    )

    assert set(authoring) == set(curated), "envelope key sets forked"
    assert _normalise(authoring) == _normalise(curated), (
        "the two submission paths produced different envelopes outside the "
        f"intended fields {sorted(INTENDED_DIFFERENCES)}"
    )
    # The intended differences say what they should say.
    assert authoring["publication_intent"]["mode"] == "staged-publication"
    assert curated["publication_intent"]["mode"] == "canonical-publication"
    assert authoring["provenance"]["source_system"] == "battinfo-authoring"
    assert curated["provenance"]["source_system"] == "battinfo-records"


def test_envelope_version_is_the_single_constant() -> None:
    record = json.loads(RECORD_FILE.read_text(encoding="utf-8"))
    payload = _cell_spec_submission_payload(
        record, wid="w", pid="p", ver="v1", source_local_id="x", title="t",
    )
    assert payload["schema_version"] == SCHEMA_VERSION, (
        "the authoring envelope hardcoded 0.1.0 for months — it must track SCHEMA_VERSION"
    )
